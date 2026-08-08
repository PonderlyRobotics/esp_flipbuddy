# SoftAP early gate — MUST stay before heavy imports.
# After machine.soft_reset() the heap is clean; we bring SoftAP up here (no boot.py).
# RTC marks: FBAP1 = run SoftAP on this boot; APDON = already tried this USB face.
_AP_BOOT_MARK = b"FBAP1"
_AP_DONE_MARK = b"APDON"
SOFTAP_CAPTIVE_PORTAL_ENABLED = True


def _early_softap_gate():
    """If ActiveFSM requested SoftAP via soft_reset, run portal before loading main stack."""
    try:
        from machine import RTC, reset_cause
    except Exception:
        return
    try:
        from machine import SOFT_RESET
    except ImportError:
        SOFT_RESET = 5  # MicroPython ESP32
    try:
        rtc = RTC()
        mem = rtc.memory()
    except Exception:
        return
    if not mem or len(mem) < 5 or mem[:5] != _AP_BOOT_MARK:
        return
    # Stale FBAP1 after power-on/hard reset must not steal BootFSM (WiFi/NTP/config).
    try:
        cause = reset_cause()
    except Exception:
        cause = -1
    if cause != SOFT_RESET:
        try:
            rtc.memory(b"")
        except Exception:
            pass
        return
    try:
        rtc.memory(_AP_DONE_MARK)
    except Exception:
        pass
    try:
        
        gc.collect()
        import ap_session

        # Success: portal then deepsleep (does not return).
        # Failure: returns so heavy imports + BootFSM/ActiveFSM still run.
        ap_session.run()
        gc.collect()
    except Exception as e:
        try:
            print("early SoftAP gate:", e)
        except Exception:
            pass


_early_softap_gate()

# --- normal firmware (heavy imports only after SoftAP gate) ---
# E402 ignored for this file in pyproject.toml (gate before models/MPU/http).
import gc
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
from network_helper import (
    async_do_connect,
    release_sta,
    release_wifi_radios,
    stop_softap,
)
import network_helper
from ntptime import settime as ntp_settime
from util import read_battery_voltage, rgb_self_test, str_to_epoch, suppress, time_iso

# 240Mhz Note: Going lower cause led flicker due to software based async execution
freq(240000000)

DEFAULT_BAT_CAPACITY = const(550)
DEFAULT_SLEEP_TIME = const(18)  # seconds
DEFAULT_UPLOAD_FRQ = const(300)  # seconds
DEFAULT_OTA = const(7)  # days
DEFAULT_INDICATOR_BLINK_DURATION = const(7000)  # ms
DEFAULT_INDICATOR_BLINK_CYCLE = const(1)
MAX_SLEEP_TIME = const(900)  # seconds
FACES = const(("front", "back", "left", "right", "top", "bottom"))

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
TIMER_NUM = const(1)
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
    print('     Hidden SSID: set "hidden": true on that entry')
    print("  3. just put-credentials   (or just fast-track)")
    print("  4. Power cycle (or soft-reboot)")
    print("=" * 48)
    print("Staying at REPL - app not started.")
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
        # Ignore AP markers and other non-backoff payloads
        prefix = backoff_state[:5]
        if prefix in (_AP_BOOT_MARK, _AP_DONE_MARK):
            return 0, default_sleep_time
        try:
            backoff_counter, prev_sleep_time = map(
                int, backoff_state.decode().split(",")
            )
        except ValueError:
            backoff_counter, prev_sleep_time = 0, default_sleep_time
    else:
        backoff_counter, prev_sleep_time = 0, default_sleep_time
    return backoff_counter, prev_sleep_time


def is_ap_cooldown():
    """True if we already attempted AP for this USB-face placement."""
    try:
        mem = rtc_mem.memory()
        return bool(mem and mem[:5] == _AP_DONE_MARK)
    except Exception:
        return False


def set_ap_cooldown():
    """Block another AP clean-reboot until USB face is left."""
    try:
        rtc_mem.memory(_AP_DONE_MARK)
    except Exception:
        pass


def clear_ap_cooldown():
    """Allow AP again after leaving back_cutout."""
    try:
        mem = rtc_mem.memory()
        if mem and mem[:5] in (_AP_DONE_MARK, _AP_BOOT_MARK):
            reset_backoff(DEFAULT_SLEEP_TIME)
    except Exception:
        pass


def request_ap_soft_reset_handoff():
    """Soft-reset into early SoftAP gate (clean heap). Does not return on success."""
    rtc_mem.memory(_AP_BOOT_MARK)
    dprint("AP mode: soft_reset -> early SoftAP gate...")

    global scheduler_wd
    try:
        if "scheduler_wd" in globals() and scheduler_wd is not None:
            scheduler_wd.deinit()
            scheduler_wd = None
    except Exception:
        pass

    release_sta()
    stop_softap()
    time.sleep_ms(100)

    try:
        from machine import soft_reset

        soft_reset()
    except (ImportError, AttributeError):
        dprint("AP mode: soft_reset unavailable, machine.reset() fallback")
        time.sleep_ms(50)
        reset()


def fibonacci(n, default_sleep_time, max_sleep_time):
    """Calculate the nth Fibonacci number, capped at max_sleep_time."""
    a, b = default_sleep_time, default_sleep_time
    for _ in range(n):
        a, b = b, a + b
        if b >= max_sleep_time:
            return max_sleep_time
    return b


def apply_backoff(default_sleep_time, max_sleep_time):
    """Apply Fibonacci backoff and store state in RTC memory."""
    backoff_counter, _ = retrieve_last_backoff(default_sleep_time)
    backoff_counter += 1
    sleep_time = fibonacci(backoff_counter, default_sleep_time, max_sleep_time)
    rtc_mem.memory(f"{backoff_counter},{sleep_time}".encode())
    return sleep_time


def reset_backoff(default_sleep_time):
    """Reset backoff counter and sleep time."""
    rtc_mem.memory(f"0,{default_sleep_time}".encode())


async def wait_for_connection(retry_interval=1.0, max_attempts=4):
    """Asynchronously wait for WiFi connection with retries.

    If credentials are missing, do not retry. Empty scan still attempts connect
    (radio may not be ready yet); only explicit no_creds aborts early.
    """
    attempts = 0
    try:
        while attempts < max_attempts:
            wdt_feed()
            if await async_do_connect(timeout=10):
                return True
            # no_creds: nothing to try. no_ssid after empty scan is no longer terminal
            # (network_helper falls back to trying configured SSIDs).
            if network_helper.last_connect_status == "no_creds":
                dprint(f"WiFi give up early ({network_helper.last_connect_status})")
                return False
            attempts += 1
            dprint(f"Connection retry {attempts}/{max_attempts}")
            wdt_feed()
            await asyncio.sleep(retry_interval)
        return False
    except Exception:
        dprint("wait_for_connection exception")
        return False


async def disconnect_wifi():
    """Disconnect station Wi-Fi without constructing interfaces unnecessarily."""
    try:
        release_sta()
        stop_softap()
    except OSError as e:
        dprint("disconnect_wifi:", e)
    await asyncio.sleep(0.1)


async def sync_time_if_possible():
    """NTP when online. Boot does this once; upload path re-syncs so RTC does not drift."""
    try:
        ntp_settime()
        dprint("NTP synced", time_iso(time.localtime()))
        return True
    except Exception as e:
        dprint("NTP failed:", e)
        return False


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
    gc.collect()

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
# -- BootFSM - first boot / cold start -------
# ------------------------------------------
class BootFSM(BaseFSM):
    S_FIRST_BOOT = "FIRST_BOOT"
    S_DEEP_SLEEP_WAKE = "DEEP_SLEEP_WAKE"
    S_SENSOR_INIT = "SENSOR_INIT"
    S_WIFI_CONNECT = "WIFI_CONNECT"
    S_SYNC_NTP = "SYNC_NTP"
    S_FETCH_CONFIG = "FETCH_CONFIG"
    S_CALIBRATE = "CALIBRATE"
    S_PARSE_FACES = "PARSE_FACES"
    S_APPLY_REMOTE = "APPLY_REMOTE"
    S_DISCONNECT = "DISCONNECT"
    S_DEEP_SLEEP = "DEEP_SLEEP"

    def __init__(self, config, tracker, np_obj=None, adc_vin=None, np_vcc=None):
        self.config = config
        self.tracker = tracker
        self.np_obj = np_obj
        self.adc_vin = adc_vin
        self.np_vcc = np_vcc
        self.state = self.S_FIRST_BOOT
        self.is_connected = False
        self.rules = {
            self.S_FIRST_BOOT: [
                Transition(
                    self.S_SENSOR_INIT, lambda: True, lambda: self.enter_sensor_init()
                ),
            ],
            self.S_DEEP_SLEEP_WAKE: [
                Transition(
                    "FACE_DETECT", lambda: True, lambda: self.wake_peripherals()
                ),
            ],
            self.S_SENSOR_INIT: [
                Transition(self.S_WIFI_CONNECT, lambda: True, lambda: self.connect_wifi()),
            ],
            # Online: NTP + remote face map. Offline: keep Tracker defaults and continue.
            self.S_WIFI_CONNECT: [
                Transition(
                    self.S_SYNC_NTP, lambda: self.is_connected, lambda: self.sync_ntp()
                ),
                Transition(
                    self.S_CALIBRATE,
                    lambda: not self.is_connected,
                    lambda: self.boot_offline(),
                ),
            ],
            self.S_SYNC_NTP: [
                Transition(
                    self.S_FETCH_CONFIG,
                    lambda: True,
                    lambda: self.fetch_config(),
                ),
            ],
            self.S_FETCH_CONFIG: [
                Transition(self.S_CALIBRATE, lambda: True, lambda: self.calibrate()),
            ],
            self.S_CALIBRATE: [
                Transition(self.S_PARSE_FACES, lambda: True, lambda: self.parse_faces()),
            ],
            self.S_PARSE_FACES: [
                Transition(self.S_APPLY_REMOTE, lambda: True, lambda: self.apply_remote()),
            ],
            self.S_APPLY_REMOTE: [
                Transition(self.S_DISCONNECT, lambda: True, lambda: self.disconnect()),
            ],
            self.S_DISCONNECT: [
                Transition(self.S_DEEP_SLEEP, lambda: True, lambda: self.enter_deep_sleep()),
            ],
        }
        self.remote_config = None

    def enter_sensor_init(self):
        dprint("Initializing sensor and uploading DMP firmware...")
        wdt_feed()

        # Check if we already have calibration data
        cal_data = self.config.running.get("calibration", {})
        mean = cal_data.get("mean")
        stddev = cal_data.get("stddev")
        
        # Only skip calibration if waking from deep sleep AND we have valid data.
        # Hard resets, power cycles, etc., should always re-calibrate.
        should_calibrate = True
        if reset_cause() == DEEPSLEEP_RESET and (mean and stddev):
            should_calibrate = False

        s = sensor_init(
            enable_mpu=True,
            sda_pin=SDA_PIN,
            scl_pin=SCL_PIN,
            intruppt_pin=INTERRUPT_PIN,
            calibrate=should_calibrate,
            mean=mean,      # Pass existing data regardless
            stddev=stddev,
        )
        
        if should_calibrate:
            dprint("INFO: Performing full sensor calibration...")
            s.upload_dmp_firmware()
            self.config.running["calibration"]["mean"] = s.mean
            self.config.running["calibration"]["stddev"] = s.stddev
            self.config.apply(self.config.running)
            self.config.save()
            dprint("INFO: Calibration data saved to NVS.")
        else:
            dprint("INFO: Deep sleep wake. Using existing calibration data from NVS.")

        wdt_feed()
        
    async def connect_wifi(self):
        dprint("Connecting to WiFi...")
        wdt_feed()
        if await wait_for_connection():
            self.is_connected = True
        else:
            # Offline-first: no reboot loop — continue with default faces / NVS state.
            dprint("WiFi unavailable - continuing offline (default faces)")
            self.is_connected = False

    async def boot_offline(self):
        """First boot without network: keep calibrated sensor + NVS face state."""
        dprint("BootFSM offline: using NVS / default faces (no dashboard)")
        wdt_feed()
        # Light self-test so the user sees the cube is alive without cloud
        if self.np_vcc:
            self.np_vcc.on()
            time.sleep_ms(50)
        try:
            rgb_self_test(np_obj)
        except Exception as e:
            dprint("offline rgb_self_test:", e)
        # Item 2: after power-loss, resume or force-close open sessions (no silent drop).
        try:
            await self.tracker.reconcile_open_sessions_after_time_sync()
        except Exception as e:
            dprint("offline session reconcile:", e)
        self.tracker.apply(self.tracker.running)
        self.tracker.save()

    async def sync_ntp(self):
        dprint("Syncing NTP...")
        await sync_time_if_possible()
        wdt_feed()
        # Item 2: clock is trustworthy after NTP; resume or force-close open sessions.
        try:
            await self.tracker.reconcile_open_sessions_after_time_sync()
        except Exception as e:
            dprint("post-NTP session reconcile:", e)
        if self.np_vcc:
            self.np_vcc.on()
            time.sleep_ms(50)  # or 30-100ms for rail stabilization
        rgb_self_test(np_obj)

    async def fetch_config(self):
        dprint("Fetching remote config...")
        wdt_feed()
        await asyncio.sleep(2)
        wdt_feed()
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
            dprint("No remote config - keeping local/default face map")

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
    S_FACE_INDICATOR = "FACE_INDICATOR"
    S_FACE_DETECT = "FACE_DETECT"
    S_FACE_CHECKED = "FACE_CHECKED"
    S_AP_MODE = "AP_MODE"
    S_DEEP_SLEEP = "DEEP_SLEEP"
    S_STOP_FACE_CHECK = "STOP_FACE_CHECK"
    S_ACTIVE_TRACKING = "ACTIVE_TRACKING"
    S_STOP_TRACKING = "STOP_TRACKING"
    S_UPLOAD_NEEDED = "UPLOAD_NEEDED"

    def __init__(self, config, tracker, np_obj, adc_vin, np_vcc):
        self.config = config
        self.tracker = tracker
        self.np_obj = np_obj
        self.adc_vin = adc_vin
        self.np_vcc = np_vcc
        self.state = self.S_FACE_INDICATOR
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
            self.S_FACE_INDICATOR: [
                Transition(
                    self.S_FACE_DETECT, lambda: True, lambda: self.show_face_indicator()
                )
            ],
            self.S_FACE_DETECT: [
                Transition(self.S_FACE_CHECKED, lambda: True, lambda: self.detect_face()),
            ],
            self.S_FACE_CHECKED: [
                Transition(
                    self.S_AP_MODE,
                    lambda: (
                        SOFTAP_CAPTIVE_PORTAL_ENABLED
                        and self.config.running["settings"].get(
                            "ap_mode_enabled", False
                        )
                        and self.face_obj
                        and self.face_obj.orientation == "back_cutout"
                        and not is_ap_cooldown()
                    ),
                    lambda: self.start_ap_mode(),
                ),
                Transition(self.S_STOP_FACE_CHECK, lambda: True, lambda: None),
            ],
            # soft_reset does not return; if it fails, still evaluate upload (USB often present).
            self.S_AP_MODE: [
                Transition(
                    self.S_UPLOAD_NEEDED,
                    lambda: True,
                    lambda: self.handle_ap_mode(),
                ),
            ],
            self.S_DEEP_SLEEP: [],
            self.S_STOP_FACE_CHECK: [
                Transition(
                    self.S_ACTIVE_TRACKING,
                    lambda: not self.is_stop_face(),
                    lambda: self.start_tracking(),
                ),
                Transition(
                    self.S_STOP_TRACKING,
                    lambda: self.is_stop_face(),
                    lambda: self.stop_tracking(),
                ),
            ],
            self.S_ACTIVE_TRACKING: [
                Transition(self.S_UPLOAD_NEEDED, lambda: True, lambda: self.decide_upload()),
            ],
            self.S_STOP_TRACKING: [
                Transition(self.S_UPLOAD_NEEDED, lambda: True, lambda: self.decide_upload()),
            ],
            self.S_UPLOAD_NEEDED: [],
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
        # Leaving USB face clears AP one-shot cooldown so next USB placement works
        if not self.face_obj or self.face_obj.orientation != "back_cutout":
            clear_ap_cooldown()
        if self.face_obj is None:
            dprint("No such face/activity_name")
        else:
            msg = f"---> {self.face_obj.activity_name} Tracking: {self.face_obj.tracking} started: {self.face_obj.started} prv:{self.tracker.active_face}"
            dprint(msg)
            # Check for out_margin and low battery
            if self.face_obj.orientation == "out_margin":
                await self.face_obj.led.error_led(status=True, color_hex="#FF0000")
            if read_battery_voltage(self.adc_vin, capacity_mah=DEFAULT_BAT_CAPACITY)["adjusted_voltage_v"] < 3.3:
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
        """USB face: finalize open sessions, save, then soft_reset into SoftAP."""
        dprint("AP mode: finalize open sessions before soft_reset...")
        orient = self.face_obj.orientation if self.face_obj else None
        try:
            # Item 1: never soft_reset while activity faces are still tracking.
            await self.tracker.finalize_and_persist(active_orientation=orient)
        except Exception as e:
            dprint("AP mode: finalize failed:", e)
        with suppress(Exception):
            if self.face_obj and hasattr(self.face_obj, "led"):
                await self.face_obj.led.inactive()
        with suppress(Exception):
            self.np_vcc.off()
        self.ap_mode = True
        request_ap_soft_reset_handoff()

    async def handle_ap_mode(self):
        # Reached only if soft_reset failed; still try upload (USB power likely).
        dprint("AP handoff did not restart; evaluate upload then sleep")
        self.sleep_ms = DEFAULT_SLEEP_TIME * 1000
        await self.decide_upload()

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
        if self.is_stop_face():
            # Always finalize every open activity face on stop face, even when
            # active_face still names the previous activity orientation.
            base = self.config.running["settings"].get(
                "orientation_check_frequency", DEFAULT_SLEEP_TIME
            )
            backoff_s = apply_backoff(base, MAX_SLEEP_TIME)
            self.sleep_ms = backoff_s * 1000
            dprint(f"Stop face → accumulating backoff: {backoff_s}s")
            await self.tracker.stop_all()
            if self.face_obj:
                self.tracker.set_active_face(self.face_obj.orientation)
        elif self.face_obj and self.tracker.active_face == self.face_obj.orientation:
            await self.tracker.stop_all()
        else:
            await self.start_tracking()

    async def decide_upload(self):
        dprint("Deciding if upload is needed...")

        wdt_feed()
        batt = read_battery_voltage(self.adc_vin, capacity_mah=DEFAULT_BAT_CAPACITY)
        usb_connected = batt["adjusted_voltage_v"] > USB_VOLTAGE_THRESHOLD
        has_log = self.tracker.tracking_log_nonempty()
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
        dprint(
            "need_upload=",
            need_upload,
            "usb=",
            usb_connected,
            "has_log=",
            has_log,
            "v=",
            batt.get("adjusted_voltage_v"),
        )

    async def run(self):
        await self.run_fsm()
        if self.state == self.S_DEEP_SLEEP:
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
    S_UPLOAD_NEEDED = "UPLOAD_NEEDED"
    S_UPLOAD_DATA = "UPLOAD_DATA"
    S_DISCONNECT = "DISCONNECT"
    S_DEEP_SLEEP = "DEEP_SLEEP"

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
        self.state = self.S_UPLOAD_NEEDED

        self.rules = {
            self.S_UPLOAD_NEEDED: [
                Transition(
                    self.S_UPLOAD_DATA,
                    lambda: self.active_result["need_upload"],
                    lambda: self.do_upload(),
                ),
                Transition(self.S_DISCONNECT, lambda: True, lambda: self.skip_upload()),
            ],
            self.S_UPLOAD_DATA: [
                Transition(
                    self.S_DISCONNECT, lambda: self.is_connected, lambda: self.post_upload()
                ),
                # Offline / WiFi failed: still deep-sleep, keep local tracking_log
                Transition(self.S_DISCONNECT, lambda: True, lambda: self.skip_upload()),
            ],
            self.S_DISCONNECT: [
                Transition(
                    self.S_DEEP_SLEEP, lambda: True, lambda: self.cleanup_and_sleep()
                ),
            ],
            self.S_DEEP_SLEEP: [],
        }

    async def do_upload(self):
        dprint("Uploading tracking log...")
        wdt_feed()
        # SoftAP must be off before STA; wait_for_connection -> _prepare_sta does that
        if await wait_for_connection():
            self.is_connected = True
            # Deep-sleep wakes skip BootFSM NTP; refresh clock before upload
            await sync_time_if_possible()
            batt_reading = read_battery_voltage(self.adc_vin, capacity_mah=DEFAULT_BAT_CAPACITY)
            batt_reading.update(self.config.running["device"])
            await asyncio.sleep(2)
            wdt_feed()
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

            dprint("Uploading to the cloud....")
            data_to_remote = to_serializable(self.tracker.running)
            # Remove ad-hoc / ephemeral keys so they don't pollute NVS (item 4).
            self.tracker.strip_ephemeral_keys()
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
                    self.tracker.strip_ephemeral_keys()
                    self.tracker.upload_config(data_to_remote)
            except asyncio.TimeoutError:
                dprint("Upload timed out")
                # Still drop ephemeral keys so a failed upload cannot bloat NVS.
                self.tracker.strip_ephemeral_keys()


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

        # Persist state before power down (strip ephemeral keys via Tracker.save).
        self.tracker.strip_ephemeral_keys()
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
        # Cold boot / soft reset / hard reset: WiFi + NTP + remote config
        boot = BootFSM(config, tracker, np_obj, adc_vin, np_vcc)
        await boot.run()


if __name__ == "__main__":
    if not CREDENTIALS_OK:
        # main.py ends here → MicroPython friendly REPL (no SystemExit soft-reboot loop)
        pass
    else:
        scheduler_wd = Timer(TIMER_NUM)
        scheduler_wd.init(period=8000, mode=Timer.PERIODIC, callback=wdt_chk)

        # Free SoftAP left over from maintenance soft_reset; STA stays lazy.
        release_wifi_radios()
        # Keep soft WDT happy during multi-second WiFi connect / NTP / upload.
        network_helper.wdt_tick = wdt_feed

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
