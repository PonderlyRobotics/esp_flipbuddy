from http import (
    async_post_request,
    async_rotate_device_token,
    get_request,
)

import esp32
import mip
import neopixel
import uasyncio as asyncio
import utime as time
from ap_mode import ApModeFSM
from credentials import load_credentials
from machine import (
    ADC,
    DEEPSLEEP_RESET,
    PIN_WAKE,
    RTC,
    Pin,
    Timer,
    deepsleep,
    freq,
    reset,
    reset_cause,
    wake_reason,
)
from micropython import const
from models import BaseFSM, Config, Tracker, Transition, to_serializable
from mpu6050 import cube_face_upward, sensor_init
from network import AP_IF, WLAN
from network_helper import async_do_connect, sta_if
import network_helper
from ntptime import settime as ntp_settime
from util import read_battery_voltage, rgb_self_test, str_to_epoch, suppress

# 240Mhz Note: Going lower cause led flicker due to software based async execution
freq(240000000)

DEFAULT_SLEEP_TIME = 18  # seconds
DEFAULT_UPLOAD_FRQ = 300  # seconds
DEFAULT_OTA = 7  # days
DEFAULT_INDICATOR_BLINK_DURATION = 7000  # ms
DEFAULT_INDICATOR_BLINK_CYCLE = 1
MAX_SLEEP_TIME = 900  # seconds
FACES = ["front", "back", "left", "right", "top", "bottom"]

# Hardware pins
NP_VCC_PIN = const(7)
NP_DATA_PIN = const(8)
VIN_PIN = const(9)
ONBOARD_LED = const(48)

# NeoPixel
NUM_LEDS = const(6)
SDA_PIN = const(11)
SCL_PIN = const(12)
INTERRUPT_PIN = const(10)

# Battery ADC settings
BATTERY_FULL_V = const(4.2)
BATTERY_CUTOFF_V = const(2.8)
BATTERY_NOMINAL_V = const(3.7)

USB_VOLTAGE_THRESHOLD = const(4.3)  # > this → USB power

# General
TIMER_NUM = 1
# PIN_WAKE = 7  # micropython passed gpio wake reason directly when GPIO is used for wake not ext0/1

DEBUG = False


def dprint(*args, **kwargs):
    """Debug print that can be disabled. All other prints in main.py were converted to this."""
    if DEBUG:
        print(*args, **kwargs)


# ----------------------------------
# -- Global objects & credentials --
# ----------------------------------
np_obj = neopixel.NeoPixel(Pin(NP_DATA_PIN), NUM_LEDS)

device_cred = load_credentials()
# Do NOT raise SystemExit here — on MicroPython that soft-reboots and loops.
# Fall through to a clean end of main.py so the friendly REPL stays up for upload.
CREDENTIALS_OK = bool(
    device_cred and device_cred.get("device_id") and device_cred.get("device_token")
)
if not CREDENTIALS_OK:
    print("=" * 48)
    print("FATAL: no device credentials (device_id / device_token).")
    print("  1. Download credentials.json from flipbuddy.app")
    print('  2. Add Wi-Fi under wifi.<name>: {"ssid": "...", "password": "..."}')
    print('     Example: "wifi": {"home": {"ssid": "MyNet", "password": "secret"}}')
    print("     Hidden SSID: set \"hidden\": true on that entry")
    print("  3. just put-credentials   (or just fast-track)")
    print("  4. Power cycle (or soft-reboot)")
    print("=" * 48)
    print("Staying at REPL — app not started.")
    TOKEN = ""
    HEADERS = {}
    API_BASE = "https://api.flipbuddy.app/v1/api/"
else:
    TOKEN = device_cred["device_id"]
    HEADERS = {
        "Device-ID": device_cred["device_id"],
        "Device-Token": device_cred["device_token"],
        "User-Agent": "Mozilla/5.0 (compatible; FlipBuddy/ESP32; +https://flipbuddy.app)",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.5",
        "Connection": "close",
    }
    API_BASE = device_cred.get("api_url", "https://api.flipbuddy.app/v1/api/")
    if not API_BASE.endswith("/"):
        API_BASE += "/"

rtc_mem = RTC()


async def get_remote_config():
    """Fetch remote configuration from the server."""
    try:
        return await get_request(
            API_BASE + f"sensor/data/{TOKEN}/", extra_header=HEADERS
        )
    except Exception:
        return False


async def push_tracking_log_to_remote(data, timeout=5):
    """Push tracking log data to the remote server asynchronously and return success status."""
    dprint("API_BASE:", API_BASE)
    try:
        # Rotate may issue a new token (saved to NVS). Also refresh in-memory
        # HEADERS so this same wake's POST does not still send the old token.
        new_token = await async_rotate_device_token(API_BASE + "sensor/token/rotate/")
        if new_token:
            HEADERS["Device-Token"] = new_token
        return (
            await async_post_request(
                API_BASE + "sensor/data/", data, extra_header=HEADERS, timeout=timeout
            )
            is not None
        )
    except Exception:
        return False


def retrieve_last_backoff(default_sleep_time):
    """Retrieve the last backoff state from RTC memory."""
    backoff_state = rtc_mem.memory()
    if backoff_state:
        try:
            backoff_counter, prev_sleep_time = map(
                int, backoff_state.decode().split(",")
            )
        except ValueError:
            backoff_counter, prev_sleep_time = 0, default_sleep_time
    else:
        backoff_counter, prev_sleep_time = 0, default_sleep_time
    return backoff_counter, prev_sleep_time


def fibonacci(n, default_sleep_time, max_sleep_time):
    """Calculate the nth Fibonacci number, capped at max_sleep_time."""
    a, b = default_sleep_time, default_sleep_time
    for _ in range(n):
        a, b = b, a + b
        if b > max_sleep_time:
            return max_sleep_time
    return b


def apply_backoff(default_sleep_time, max_sleep_time):
    """Apply exponential backoff using Fibonacci sequence."""
    backoff_counter, _ = retrieve_last_backoff(default_sleep_time)
    backoff_counter += 1
    new_sleep_time = fibonacci(backoff_counter, default_sleep_time, max_sleep_time)
    rtc_mem.memory(f"{backoff_counter},{new_sleep_time}".encode())
    return new_sleep_time


def reset_backoff(default_sleep_time):
    """Reset backoff counter and sleep time."""
    rtc_mem.memory(f"0,{default_sleep_time}".encode())


async def wait_for_connection(retry_interval=1.0, max_attempts=4):
    """Asynchronously wait for WiFi connection with retries.

    If a scan shows no configured SSID (or no credentials), do not retry — the
    radio already did useful work and further 10s connect loops would only drain battery.
    """
    attempts = 0
    try:
        while attempts < max_attempts:
            if await async_do_connect(timeout=10):
                return True
            # no_ssid / no_creds: scan already answered; more attempts won't help this wake
            if network_helper.last_connect_status in ("no_ssid", "no_creds"):
                dprint(f"WiFi give up early ({network_helper.last_connect_status})")
                return False
            attempts += 1
            dprint(f"Connection retry {attempts}/{max_attempts}")
            await asyncio.sleep(retry_interval)
        return False
    except Exception:
        dprint("wait_for_connection exception")
        return False


async def disconnect_wifi():
    """Disconnect WiFi and deactivate interface."""
    if sta_if.isconnected():
        sta_if.disconnect()
        sta_if.active(False)
        await asyncio.sleep(0.1)


async def prepare_for_deep_sleep(
    np_vcc=None,
    np_obj=None,
    sleep_ms=None,
    face_obj=None,
    tracker=None,
    do_mpu_config=True,
):
    """Centralized preparation for deep sleep.

    - All LED tasks cancelled + inactive (so no background work keeps things alive)
    - LED strip fully blacked out via np_obj
    - DATA pin forced low (prevents back-powering the strip through the data line when VCC gated)
    - np_vcc gate turned off (no current to RGB LEDs)
    - MPU put into known low-power DMP motion detection state (for PIN_WAKE on motion)
    - WiFi fully disconnected
    - Watchdog timer deinitialized

    This is the single place that should perform the power-down sequence so that
    deep sleep current is minimized (target << 1mA when LEDs and MPU are correctly gated).
    """
    dprint("prepare_for_deep_sleep: powering down peripherals for minimal current draw")

    # Safe fallbacks to module-level objects
    if np_vcc is None:
        np_vcc = globals().get("np_vcc")
    if np_obj is None:
        np_obj = globals().get("np_obj")
    if sleep_ms is None:
        sleep_ms = DEFAULT_SLEEP_TIME * 1000

    if np_obj:
        try:
            np_obj.fill((0, 0, 0))
            np_obj.write()
        except Exception as e:
            dprint("np_obj blackout warning:", e)
    try:
        Pin(NP_DATA_PIN, Pin.OUT).value(0)
    except Exception as e:
        dprint("DATA pin force-low warning:", e)

    if np_vcc:
        try:
            np_vcc.off()
        except Exception as e:
            dprint("np_vcc.off() warning:", e)

    if do_mpu_config:
        try:
            s = sensor_init(
                enable_mpu=True,
                calibrate=False,
                mean=[0, 0, 0, 0, 0, 0],
                stddev=[1, 1, 1, 1, 1, 1],
                sda_pin=SDA_PIN,
                scl_pin=SCL_PIN,
                intruppt_pin=INTERRUPT_PIN,
            )
            esp32.wake_on_ext0(pin=s._int_pin, level=esp32.WAKEUP_ANY_HIGH)
            if hasattr(s, "configure_for_deep_sleep"):
                s.configure_for_deep_sleep()
            else:
                s.enable_low_power_dmp_motion_detection(threshold=2, sample_rate_div=16)
            dprint("MPU configured for low-power DMP motion detection (deep sleep)")
        except Exception as e:
            dprint("MPU deep-sleep config warning (non-fatal):", e)

    try:
        await disconnect_wifi()
    except Exception as e:
        dprint("disconnect_wifi warning:", e)

    global scheduler_wd
    try:
        if "scheduler_wd" in globals() and scheduler_wd is not None:
            scheduler_wd.deinit()
    except Exception as e:
        dprint("scheduler_wd.deinit() warning:", e)

    dprint(f"→ Deep sleep {sleep_ms // 1000}s")
    deepsleep(sleep_ms)


async def ota_weekly_check(tracker_obj):
    """update/run OTA weekly on"""
    now = time.time()
    last = tracker_obj.running.get("last_ota_check", 0)
    if now - last < tracker_obj.running.get("ota_frequency", DEFAULT_OTA) * 24 * 3600:
        return False
    dprint("Weekly OTA window - checking for firmware update...")
    try:
        scheduler_wd.deinit()
        scheduler_wd.init(period=60000, mode=Timer.PERIODIC, callback=wdt_chk)
        mip.install(tracker_obj.running["ota_address"])
        dprint("OTA successful - rebooting in 1 second...")
        tracker_obj.running["last_ota_check"] = now
        tracker_obj.apply(tracker_obj.running)
        tracker_obj.save()
        await asyncio.sleep(1)
        reset()
    except Exception as e:
        dprint("OTA check failed or no new version:", e)
        tracker_obj.running["last_ota_check"] = now
        tracker_obj.apply(tracker_obj.running)
        tracker_obj.save()
        return False


# ------------------------------------------
# -- BootFSM - first boot & wake handling --
# ------------------------------------------
class BootFSM(BaseFSM):
    def __init__(self, config, tracker, np_obj=None, adc_vin=None, np_vcc=None):
        self.config = config
        self.tracker = tracker
        self.np_obj = np_obj
        self.adc_vin = adc_vin
        self.np_vcc = np_vcc
        self.state = "FIRST_BOOT"
        self.is_connected = False
        self.rules = {
            "FIRST_BOOT": [
                Transition(
                    "SENSOR_INIT", lambda: True, lambda: self.enter_sensor_init()
                ),
            ],
            "DEEP_SLEEP_WAKE": [
                Transition(
                    "FACE_DETECT", lambda: True, lambda: self.wake_peripherals()
                ),
            ],
            "SENSOR_INIT": [
                Transition("WIFI_CONNECT", lambda: True, lambda: self.connect_wifi()),
            ],
            # Online: NTP + remote face map. Offline: keep Tracker defaults and continue.
            "WIFI_CONNECT": [
                Transition(
                    "SYNC_NTP", lambda: self.is_connected, lambda: self.sync_ntp()
                ),
                Transition(
                    "CALIBRATE",
                    lambda: not self.is_connected,
                    lambda: self.boot_offline(),
                ),
            ],
            "SYNC_NTP": [
                Transition(
                    "FETCH_CONFIG",
                    lambda: True,
                    lambda: self.fetch_config(),
                ),
            ],
            "FETCH_CONFIG": [
                Transition("CALIBRATE", lambda: True, lambda: self.calibrate()),
            ],
            "CALIBRATE": [
                Transition("PARSE_FACES", lambda: True, lambda: self.parse_faces()),
            ],
            "PARSE_FACES": [
                Transition("APPLY_REMOTE", lambda: True, lambda: self.apply_remote()),
            ],
            "APPLY_REMOTE": [
                Transition("DISCONNECT", lambda: True, lambda: self.disconnect()),
            ],
            "DISCONNECT": [
                Transition("DEEP_SLEEP", lambda: True, lambda: self.enter_deep_sleep()),
            ],
        }
        self.remote_config = None

    def enter_sensor_init(self):
        dprint("Initializing sensor and uploading DMP firmware...")
        s = sensor_init(
            enable_mpu=True,
            sda_pin=SDA_PIN,
            scl_pin=SCL_PIN,
            intruppt_pin=INTERRUPT_PIN,
        )
        s.upload_dmp_firmware()
        self.config.running["calibration"]["mean"] = s.mean
        self.config.running["calibration"]["stddev"] = s.stddev
        self.config.apply(self.config.running)
        self.config.save()

    async def connect_wifi(self):
        dprint("Connecting to WiFi...")
        if await wait_for_connection():
            self.is_connected = True
        else:
            # Offline-first: no reboot loop — continue with default faces / NVS state.
            dprint("WiFi unavailable — continuing offline (default faces)")
            self.is_connected = False

    async def boot_offline(self):
        """First boot without network: keep calibrated sensor + factory/default faces."""
        dprint("BootFSM offline: using configured default faces (no dashboard)")
        wdt_feed()
        # Light self-test so the user sees the cube is alive without cloud
        if self.np_vcc:
            self.np_vcc.on()
            time.sleep_ms(50)
        try:
            rgb_self_test(np_obj)
        except Exception as e:
            dprint("offline rgb_self_test:", e)
        # Keep empty factory face map (nudge: assign faces via dashboard when online)
        self.tracker.apply(self.tracker.running)
        self.tracker.save()

    async def sync_ntp(self):
        dprint("Syncing NTP...")
        try:
            ntp_settime()
        except Exception as e:
            dprint("NTP failed (continuing):", e)
        wdt_feed()
        if self.np_vcc:
            self.np_vcc.on()
            time.sleep_ms(50)  # or 30-100ms for rail stabilization
        rgb_self_test(np_obj)

    async def fetch_config(self):
        dprint("Fetching remote config...")
        await asyncio.sleep(2)
        self.remote_config = await get_remote_config()
        if self.remote_config:
            # Only apply + save if the meaningful settings actually changed.
            # This avoids unnecessary NVS commits (and was the original purpose of hash_digest).
            old_hash = self.config.running.get("hash_digest", "")
            self.config.apply_remote_config(self.remote_config)
            new_hash = self.config.hash_digest()
            if new_hash != old_hash:
                self.config.apply(self.config.running)
                self.config.save()

    async def calibrate(self):
        dprint("Applying calibration...")

    async def parse_faces(self):
        dprint("Parsing faces...")
        self.tracker.parse_faces()

    async def apply_remote(self):
        dprint("Applying remote face config...")
        if self.remote_config:
            # Guard using the (now cleaned) assignment hash so flips don't trigger saves.
            old_hash = self.tracker.running.get("hash_digest", "")
            self.tracker.apply_remote_config(self.remote_config)
            new_hash = self.tracker.hash_digest()
            if new_hash != old_hash:
                self.tracker.apply(self.tracker.running)
                self.tracker.save()
        else:
            dprint("No remote config — keeping local/default face map")

    async def disconnect(self):
        dprint("Disconnecting WiFi...")
        await disconnect_wifi()

    async def enter_deep_sleep(self):
        # Short sleep then DEEPSLEEP_RESET → ActiveFSM (online or offline tracking)
        dprint("BootFSM → deep sleep 100ms (hand off to ActiveFSM)")
        await prepare_for_deep_sleep(self.np_vcc, self.np_obj, 100, do_mpu_config=False)

    async def run(self):
        if reset_cause() == DEEPSLEEP_RESET:
            return "SKIP"
        await self.run_fsm()
        return "OK"


# -------------------------------------------
# -- ActiveFSM - face detection & tracking --
# -------------------------------------------
class ActiveFSM(BaseFSM):
    def __init__(self, config, tracker, np_obj, adc_vin, np_vcc):
        self.config = config
        self.tracker = tracker
        self.np_obj = np_obj
        self.adc_vin = adc_vin
        self.np_vcc = np_vcc
        self.state = "FACE_INDICATOR"
        self.face_obj = None
        self.sleep_ms = (
            self.config.running["settings"].get(
                "orientation_check_frequency", DEFAULT_SLEEP_TIME
            )
            * 1000
        )
        self.need_upload = False
        self.ap_mode = False

        self.rules = {
            "FACE_INDICATOR": [
                Transition(
                    "FACE_DETECT", lambda: True, lambda: self.show_face_indicator()
                )
            ],
            "FACE_DETECT": [
                Transition("FACE_CHECKED", lambda: True, lambda: self.detect_face()),
            ],
            "FACE_CHECKED": [
                Transition(
                    "AP_MODE",
                    lambda: self.config.running["settings"].get(
                        "ap_mode_enabled", False
                    )
                    and self.face_obj
                    and self.face_obj.orientation == "back_cutout",
                    lambda: self.start_ap_mode(),
                ),
                Transition("STOP_FACE_CHECK", lambda: True, lambda: None),
            ],
            "AP_MODE": [
                Transition(
                    "DEEP_SLEEP",
                    lambda: True,
                    lambda: self.handle_ap_mode(),
                ),
            ],
            "DEEP_SLEEP": [],
            "STOP_FACE_CHECK": [
                Transition(
                    "ACTIVE_TRACKING",
                    lambda: not self.is_stop_face(),
                    lambda: self.start_tracking(),
                ),
                Transition(
                    "STOP_TRACKING",
                    lambda: self.is_stop_face(),
                    lambda: self.stop_tracking(),
                ),
            ],
            "ACTIVE_TRACKING": [
                Transition("UPLOAD_NEEDED", lambda: True, lambda: self.decide_upload()),
            ],
            "STOP_TRACKING": [
                Transition("UPLOAD_NEEDED", lambda: True, lambda: self.decide_upload()),
            ],
            "UPLOAD_NEEDED": [],
        }

    def is_stop_face(self):
        wdt_feed()
        dprint(self.face_obj)
        if self.face_obj and hasattr(self.face_obj, "stop_face"):
            return self.face_obj.stop_face
        return False

    async def show_face_indicator(self):
        if wake_reason() == PIN_WAKE:
            self.np_vcc.on()
            assigned_face = [
                getattr(self.tracker, f)
                for f in FACES
                if getattr(self.tracker, f).activity_id != ""
            ]
            ref_face = self.tracker.back_cutout
            if assigned_face:
                indicator_fade_time = DEFAULT_INDICATOR_BLINK_DURATION  # 7 seconds
                for face in assigned_face:
                    face.led.duration_ms = indicator_fade_time
                    face.led.cycles = DEFAULT_INDICATOR_BLINK_CYCLE
                    face.led.update_blinking_params()
                await asyncio.gather(
                    *[face.led.blinking_effect() for face in assigned_face]
                )
                for face in assigned_face:
                    face.led.reset_color()
                    with suppress(asyncio.CancelledError):
                        await face.led.inactive()
            else:
                await ref_face.led.error_led(status=True, color_hex="#11D6EC")
                t = ref_face.led.get_total_blink_time()
                await asyncio.sleep(t)
                await ref_face.led.error_led(status=False)
                ref_face.led.reset_color()
            with suppress(asyncio.CancelledError):
                await ref_face.led.inactive()

    async def detect_face(self):
        dprint("Detecting upward face...")
        self.np_vcc.on()
        s = sensor_init(
            enable_mpu=True,
            calibrate=False,
            mean=self.config.running["calibration"]["mean"],
            stddev=self.config.running["calibration"]["stddev"],
            sda_pin=SDA_PIN,
            scl_pin=SCL_PIN,
            intruppt_pin=INTERRUPT_PIN,
        )
        esp32.wake_on_ext0(pin=s._int_pin, level=esp32.WAKEUP_ANY_HIGH)
        await asyncio.sleep(0.1)
        face_name = cube_face_upward(s)
        dprint(f"ActiveFSM → face: {face_name}")
        self.face_obj = getattr(self.tracker, face_name, None)
        if self.face_obj is None:
            dprint("No such face/activity_name")
        else:
            msg = f"---> {self.face_obj.activity_name} Tracking: {self.face_obj.tracking} started: {self.face_obj.started} prv:{self.tracker.active_face}"
            dprint(msg)
            # Check for out_margin and low battery
            if self.face_obj.orientation == "out_margin":
                await self.face_obj.led.error_led(status=True, color_hex="#FF0000")
            if read_battery_voltage(self.adc_vin)["adjusted_voltage_v"] < 3.3:
                await self.face_obj.led.error_led(status=True, color_hex="#EC1169")

            if self.face_obj.orientation in ("front_cutout", "back_cutout"):
                # Only blink if not already tracking the same face
                if not (
                    self.face_obj.orientation == self.tracker.active_face
                    and self.face_obj.tracking
                ):
                    dprint(f"Calling triad_led for {self.face_obj.orientation}")
                    await self.face_obj.led.triad_led(
                        self.face_obj.orientation,
                        status=True,
                        color_hex=self.face_obj.led.hex_code,
                    )
                    # For cutouts, await the blink duration
                    # given one is stop_face and will be stopped if not awaited here
                    t = self.face_obj.led.get_total_blink_time()
                    await asyncio.sleep(t * 2)  # two cycles
        s.enable_low_power_dmp_motion_detection()

    async def start_ap_mode(self):
        dprint("Starting AP mode...")
        ap_fsm = ApModeFSM(self.config, self.tracker, adc_vin=self.adc_vin)
        await ap_fsm.run()
        self.ap_mode = True

    async def handle_ap_mode(self):
        dprint("Running AP mode for 5 minutes...")
        # Loop 300 times (5 minutes), feeding watchdog each second to prevent reset
        for _ in range(300):
            wdt_feed()
            await asyncio.sleep(1)
        self.sleep_ms = DEFAULT_SLEEP_TIME * 1000

    async def start_tracking(self):
        wdt_feed()
        dprint("Starting active tracking...")

        dprint(self.face_obj)
        if self.face_obj:
            await self.tracker.start_tracking(self.face_obj)
            # Activate LED - background task handles blinking
            self.face_obj.led.active()
            t = self.face_obj.led.get_total_blink_time()
            await asyncio.sleep(t * 2)  # two cycles
            # Reset backoff when we start actively tracking a real face.
            # Next stop face will start the Fibonacci sequence from the beginning.
            base = self.config.running["settings"].get(
                "orientation_check_frequency", DEFAULT_SLEEP_TIME
            )
            reset_backoff(base)

    async def stop_tracking(self):
        dprint("Stopping tracking...")
        if (
            self.face_obj
            and hasattr(self.face_obj.led, "task")
            and self.face_obj.led.task
            and not self.face_obj.orientation.endswith("_cutout")
        ):
            led = self.face_obj.led
            led.task.cancel()
            with suppress(asyncio.CancelledError):
                await led.task
            led.task = None
        if self.face_obj and self.tracker.active_face == self.face_obj.orientation:
            if self.is_stop_face():
                # True accumulating Fibonacci backoff while staying on stop face.
                # Counter persists in RTC mem across deep sleeps.
                # Only reset when we move to an active (non-stop) face.
                base = self.config.running["settings"].get(
                    "orientation_check_frequency", DEFAULT_SLEEP_TIME
                )
                backoff_s = apply_backoff(base, MAX_SLEEP_TIME)
                self.sleep_ms = backoff_s * 1000
                dprint(f"Stop face → accumulating backoff: {backoff_s}s")
            await self.tracker.stop_all()
        else:
            await self.start_tracking()

    async def decide_upload(self):
        dprint("Deciding if upload is needed...")

        wdt_feed()
        batt = read_battery_voltage(self.adc_vin)
        usb_connected = batt["adjusted_voltage_v"] > USB_VOLTAGE_THRESHOLD
        has_log = bool(self.tracker.running.get("tracking_log"))
        last_upload = self.tracker.running.get("last_config_uploaded", "")
        upload_freq = self.config.running["settings"].get(
            "upload_frequency", DEFAULT_UPLOAD_FRQ
        )
        time_since_upload = (
            time.time() - str_to_epoch(last_upload) if last_upload else float("inf")
        )
        need_upload = (
            last_upload == ""
            or time_since_upload >= upload_freq
            or (self.face_obj and self.face_obj.stop_face)
            or has_log
            or usb_connected
            or wake_reason() == PIN_WAKE
        )
        self.need_upload = need_upload
        # if not self.need_upload:
        #     self.sleep_ms = self.sleep_ms

    async def run(self):
        await self.run_fsm()
        if self.state == "DEEP_SLEEP":
            await prepare_for_deep_sleep(
                self.np_vcc,
                self.np_obj,
                self.sleep_ms,
                face_obj=self.face_obj,
                tracker=self.tracker,
                do_mpu_config=True,
            )
        return {
            "sleep_ms": self.sleep_ms,
            "need_upload": self.need_upload,
            "face_obj": self.face_obj,
            "ap_mode": self.ap_mode,
        }


# --------------------------------------------------
# -- UploadFSM - upload + LED breathe + deepsleep --
# --------------------------------------------------
class UploadFSM(BaseFSM):
    def __init__(
        self, config, tracker, np_obj, adc_vin, np_vcc, token, headers, active_result
    ):
        self.config = config
        self.tracker = tracker
        self.np_obj = np_obj
        self.adc_vin = adc_vin
        self.np_vcc = np_vcc
        self.token = token
        self.headers = headers
        self.active_result = active_result
        self.is_connected = False
        self.sleep_ms = (
            active_result["sleep_ms"]
            if active_result["sleep_ms"]
            else DEFAULT_SLEEP_TIME
        )
        self.state = "UPLOAD_NEEDED"

        self.rules = {
            "UPLOAD_NEEDED": [
                Transition(
                    "UPLOAD_DATA",
                    lambda: self.active_result["need_upload"],
                    lambda: self.do_upload(),
                ),
                Transition("DISCONNECT", lambda: True, lambda: self.skip_upload()),
            ],
            "UPLOAD_DATA": [
                Transition(
                    "DISCONNECT", lambda: self.is_connected, lambda: self.post_upload()
                ),
                # Offline / Wi‑Fi failed: still deep-sleep, keep local tracking_log
                Transition("DISCONNECT", lambda: True, lambda: self.skip_upload()),
            ],
            "DISCONNECT": [
                Transition(
                    "DEEP_SLEEP", lambda: True, lambda: self.cleanup_and_sleep()
                ),
            ],
            "DEEP_SLEEP": [],
        }

    async def do_upload(self):
        dprint("Uploading tracking log...")
        wdt_feed()
        if await wait_for_connection():
            self.is_connected = True
            batt_reading = read_battery_voltage(self.adc_vin)
            batt_reading.update(self.config.running["device"])
            await asyncio.sleep(2)
            remote_config = await get_remote_config()
            if remote_config:
                # Guard: only persist if settings hash actually changed (saves NVS writes).
                old_hash = self.config.running.get("hash_digest", "")
                self.config.apply_remote_config(remote_config)
                new_hash = self.config.hash_digest()
                if new_hash != old_hash:
                    self.config.apply(self.config.running)
                    self.config.save()
            self.tracker.running.update({"device_id": self.token})
            self.tracker.running.update(
                {
                    "calibration": {
                        "mean": self.config.running["calibration"]["mean"],
                        "stddev": self.config.running["calibration"]["stddev"],
                    }
                }
            )
            _ = await ota_weekly_check(self.tracker)

            self.tracker.running.update(
                {
                    "device": {"battery": batt_reading},
                    "raw_config": self.config.running,
                }
            )
            # Advertise current hashes to the server so it can avoid sending
            # unchanged config/face assignments in future responses.
            self.tracker.running["config_hash"] = self.config.hash_digest()
            self.tracker.running["tracker_hash"] = self.tracker.hash_digest()

            dprint(" Uploading to the cloud....")
            data_to_remote = to_serializable(self.tracker.running)
            # Remove ad-hoc hash advertisement keys so they don't pollute the persisted tracker state.
            self.tracker.running.pop("config_hash", None)
            self.tracker.running.pop("tracker_hash", None)
            # Only apply when the server actually returned a face map (not local faces).
            if remote_config and remote_config.get("faces"):
                self.tracker.apply_remote_config(remote_config)

            # The calibration is stored in config,
            # here we aim to send all data in one api call
            dprint(data_to_remote)
            try:
                success = await asyncio.wait_for_ms(
                    push_tracking_log_to_remote(data_to_remote, timeout=4), 5000
                )
                if success:
                    dprint("-------------cleaning....")
                    self.tracker.running.pop("calibration", None)
                    self.tracker.running.pop("device", None)
                    self.tracker.upload_config(data_to_remote)
            except asyncio.TimeoutError:
                dprint("Upload timed out")

    async def skip_upload(self):
        dprint("Skipping upload...")

    async def post_upload(self):
        dprint("Post-upload actions...")
        # Only reset backoff on successful upload if we are NOT on a stop face.
        # While on stop face we want the Fibonacci counter to keep accumulating
        # so sleep times grow (36s → 54s → 90s ... up to 15min).
        face = self.active_result.get("face_obj")
        is_stop = bool(face and getattr(face, "stop_face", False))
        if not is_stop:
            base = self.config.running["settings"].get(
                "orientation_check_frequency", DEFAULT_SLEEP_TIME
            )
            reset_backoff(base)

    async def cleanup_and_sleep(self):
        dprint("Cleaning up and preparing for deep sleep...")

        face = self.active_result.get("face_obj")
        if face:
            led = face.led
            if hasattr(led, "task") and led.task:
                led.task.cancel()
                with suppress(asyncio.CancelledError):
                    await led.task
                led.task = None
            with suppress(asyncio.CancelledError):
                await led.inactive()

        # Persist state before power down
        self.tracker.apply(self.tracker.running)
        self.tracker.save()

        await prepare_for_deep_sleep(
            self.np_vcc,
            self.np_obj,
            self.sleep_ms,
            face_obj=face,
            tracker=self.tracker,
            do_mpu_config=True,
        )

    async def run(self):
        await self.run_fsm()


_wdt_counter = 0


def wdt_feed():
    global _wdt_counter
    _wdt_counter -= 1


def wdt_chk(t):
    """Using Timer since builtin MicroPython WDT hard reset, we need deepsleep"""
    global _wdt_counter
    _wdt_counter += 1
    if _wdt_counter >= 4:
        t.deinit()
        deepsleep(DEFAULT_SLEEP_TIME * 1000)


async def main():
    if reset_cause() == DEEPSLEEP_RESET:
        if wake_reason() == PIN_WAKE:
            dprint("Woke from deep sleep via pin!")
        active = ActiveFSM(config, tracker, np_obj, adc_vin, np_vcc)
        active_result = await active.run()

        upload = UploadFSM(
            config,
            tracker,
            np_obj,
            adc_vin,
            np_vcc,
            TOKEN,
            HEADERS,
            active_result,
        )
        await upload.run()

    else:
        # After first boot setup, go to deep sleep
        boot = BootFSM(config, tracker, np_obj, adc_vin, np_vcc)
        await boot.run()


if __name__ == "__main__":
    if not CREDENTIALS_OK:
        # main.py ends here → MicroPython friendly REPL (no SystemExit soft-reboot loop)
        pass
    else:
        scheduler_wd = Timer(TIMER_NUM)
        scheduler_wd.init(period=8000, mode=Timer.PERIODIC, callback=wdt_chk)

        WLAN(AP_IF).active(False)
        sta_if.active(False)

        config = Config()
        tracker = Tracker(np_obj)

        np_vcc = Pin(NP_VCC_PIN, Pin.OUT, Pin.PULL_DOWN, drive=Pin.DRIVE_2)  # 20mA max
        np_vcc.off()  # ensure LEDs start with power gated off
        try:  # noqa: SIM105
            Pin(NP_DATA_PIN, Pin.OUT).value(
                0
            )  # prevent any data-line backfeed on start
        except Exception:
            pass
        adc_vin = ADC(Pin(VIN_PIN), atten=ADC.ATTN_11DB)
        adc_vin.width(ADC.WIDTH_12BIT)

        asyncio.run(main())
