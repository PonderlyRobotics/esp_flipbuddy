import gc

import uasyncio as asyncio
import utime as time
from credentials import load_credentials
from network import (
    AP_IF,
    STA_IF,
    STAT_CONNECT_FAIL,
    STAT_NO_AP_FOUND,
    STAT_WRONG_PASSWORD,
    WLAN,
    hostname,
)
from util import suppress

# Last async_do_connect / do_connect outcome for callers (e.g. skip retries).
# One of: "connected", "no_creds", "no_ssid", "failed", "already"
last_connect_status = "failed"

# Optional callable set by main.wdt_feed so long connect loops do not trip soft WDT.
wdt_tick = None

# Station interface is created on first use. Building WLAN(STA_IF) at import
# can fail with "WiFi Out of Memory" on ESP32-S3 after SoftAP sessions.
_sta_if = None


def _tick_wdt():
    if wdt_tick is not None:
        with suppress(Exception):
            wdt_tick()


def _get_sta():
    """Return the station WLAN, creating it only when first needed."""
    global _sta_if
    if _sta_if is None:
        gc.collect()
        with suppress(Exception):
            WLAN(AP_IF).active(False)
        gc.collect()
        _sta_if = WLAN(STA_IF)
    return _sta_if


class _StaProxy:
    """Lazy stand-in for module-level `sta_if` used across the firmware."""

    def __getattr__(self, name):
        return getattr(_get_sta(), name)

    def __bool__(self):
        return True


sta_if = _StaProxy()


def release_sta():
    """Drop station mode if it was created. Does not construct WLAN(STA_IF)."""
    global _sta_if
    if _sta_if is not None:
        with suppress(Exception):
            _sta_if.disconnect()
        with suppress(Exception):
            _sta_if.active(False)
        _sta_if = None
    gc.collect()


def stop_softap():
    """Turn SoftAP off so STA connect can own the radio. Safe if already off."""
    with suppress(Exception):
        ap = WLAN(AP_IF)
        with suppress(Exception):
            if ap.active():
                ap.active(False)
                time.sleep_ms(50)
    gc.collect()


def release_wifi_radios():
    """Deactivate SoftAP (if any) and cached STA. Never raises on OOM."""
    release_sta()
    stop_softap()


def prepare_for_softap(settle_ms=250):
    """Free station, stop SoftAP if active, return AP_IF for SoftAP-only mode."""
    release_sta()
    gc.collect()
    ap = WLAN(AP_IF)
    with suppress(Exception):
        if ap.active():
            ap.active(False)
            time.sleep_ms(settle_ms)
    gc.collect()
    return ap


def start_softap(essid, ip, subnet, authmode, settle_ms=250, retries=3):
    """Bring up SoftAP with retries. Raises last OSError if all attempts fail."""
    last_err = None
    for attempt in range(retries):
        try:
            gc.collect()
            print(
                "SoftAP attempt",
                attempt + 1,
                "mem_free=",
                gc.mem_free(),
            )
            ap = prepare_for_softap(settle_ms=settle_ms)
            ap.active(True)
            # config before ifconfig is more reliable on some MicroPython builds
            ap.config(essid=essid, authmode=authmode)
            ap.ifconfig((ip, subnet, ip, ip))
            print("SoftAP up", ap.ifconfig(), "mem_free=", gc.mem_free())
            return ap
        except OSError as e:
            last_err = e
            print("SoftAP failed:", e, "mem_free=", gc.mem_free())
            with suppress(Exception):
                WLAN(AP_IF).active(False)
            release_sta()
            gc.collect()
            time.sleep_ms(settle_ms * (attempt + 1))
    raise last_err


def _wifi_configs():
    """Return ordered list of wifi dicts from credentials (NVS/file)."""
    creds = load_credentials() or {}
    configs = []
    for _key, value in creds.get("wifi", {}).items():
        configs.append(value)
    return configs


def _scan_visible_ssids():
    """
    Active scan of nearby APs. Returns a set of SSID strings, or None if scan failed.

    Hidden SSIDs do not appear here — mark those entries with ``"hidden": true``
    in credentials so we still attempt connect without a scan hit.
    """
    try:
        results = _get_sta().scan() or []
    except OSError as e:
        print("WiFi scan failed:", e)
        return None

    ssids = set()
    for entry in results:
        raw = entry[0] if entry else b""
        if isinstance(raw, bytes):
            name = raw.decode("utf-8", "ignore")
        else:
            name = str(raw)
        if name:
            ssids.add(name)
    print(f"WiFi scan: {len(ssids)} SSID(s) visible")
    return ssids


def _configs_to_try(wifi_configs, visible):
    """
    Pick which credential networks to attempt.

    - visible is None → scan failed; try all (old behaviour)
    - visible empty set → radio likely not ready; try all (do not skip WiFi/NTP)
    - otherwise only try SSIDs seen in the scan, plus any marked hidden
    """
    if visible is not None and len(visible) == 0:
        print("WiFi scan empty; trying configured SSIDs anyway")
        visible = None
    to_try = []
    for config in wifi_configs:
        ssid = config.get("ssid")
        if not ssid:
            continue
        if visible is None or config.get("hidden") or ssid in visible:
            to_try.append(config)
        else:
            print(f"Skipping {ssid}: not in scan (AP away / wrong SSID)")
    return to_try


def _prepare_sta(low_power=False):
    """Prepare station mode for home Wi-Fi (SoftAP must be off first)."""
    hostname("FlipBuddy")
    gc.collect()
    # SoftAP left up after maintenance blocks STA NTP/upload
    stop_softap()
    # Recreate STA after SoftAP sessions so the radio is not stuck mid-mode
    release_sta()
    gc.collect()
    sta = _get_sta()
    if not sta.active():
        sta.active(True)
    # Empty scans are common if we scan immediately after active(True)
    time.sleep_ms(250)
    if low_power:
        with suppress(Exception):
            sta.config(pm=sta.PM_POWERSAVE)


def do_connect(timeout=10, low_power=False):
    """Connects to WiFi from credentials (file/NVS). Tries each configured network in order."""
    global last_connect_status

    _prepare_sta(low_power)
    sta = _get_sta()

    if sta.isconnected():
        print("Already connected:", sta.ifconfig())
        last_connect_status = "already"
        return True

    wifi_configs = _wifi_configs()
    if not wifi_configs:
        print("No WiFi credentials configured.")
        last_connect_status = "no_creds"
        return False

    visible = _scan_visible_ssids()
    candidates = _configs_to_try(wifi_configs, visible)
    if not candidates:
        print("No configured SSID visible; skipping connect attempts.")
        last_connect_status = "no_ssid"
        return False

    for config in candidates:
        ssid = config.get("ssid")
        password = config.get("password")

        print(f"Connecting to network: {ssid}...")
        sta.connect(ssid, password)

        start = time.ticks_ms()
        polls = 0
        while time.ticks_diff(time.ticks_ms(), start) < timeout * 1000:
            status = sta.status()

            if sta.isconnected():
                print(f"Connected to {ssid}! Config: {sta.ifconfig()}")
                last_connect_status = "connected"
                return True

            if status == STAT_WRONG_PASSWORD:
                print(f"Wrong password for {ssid}. Trying next...")
                break  # Try next config immediately

            if status in [STAT_NO_AP_FOUND, STAT_CONNECT_FAIL]:
                # Don't break immediately, give it a moment (e.g. if AP is just starting up)
                pass

            polls += 1
            if polls % 20 == 0:
                _tick_wdt()
            time.sleep_ms(50)

        print(f"Failed to connect to {ssid} within {timeout}s.")
        sta.disconnect()
        time.sleep_ms(100)  # Brief pause before next attempt

    print("All connection attempts failed.")
    last_connect_status = "failed"
    return False


async def async_do_connect(timeout=10, low_power=False):
    """Async WiFi connect - non-blocking polling. Scans first; skips missing SSIDs."""
    global last_connect_status

    _prepare_sta(low_power)
    sta = _get_sta()

    if sta.isconnected():
        print("Already connected:", sta.ifconfig())
        last_connect_status = "already"
        return True

    wifi_configs = _wifi_configs()
    if not wifi_configs:
        print("No WiFi credentials configured.")
        last_connect_status = "no_creds"
        return False

    # scan() is blocking on ESP; yield once before/after so other tasks can run
    await asyncio.sleep_ms(0)
    visible = _scan_visible_ssids()
    await asyncio.sleep_ms(0)

    candidates = _configs_to_try(wifi_configs, visible)
    if not candidates:
        print("No configured SSID visible; skipping connect attempts.")
        last_connect_status = "no_ssid"
        return False

    for config in candidates:
        ssid = config.get("ssid")
        password = config.get("password")

        print(f"Connecting to network: {ssid}...")
        sta.connect(ssid, password)

        start = time.ticks_ms()
        polls = 0
        while time.ticks_diff(time.ticks_ms(), start) < timeout * 1000:
            status = sta.status()

            if sta.isconnected():
                print(f"Connected to {ssid}! Config: {sta.ifconfig()}")
                last_connect_status = "connected"
                return True

            if status == STAT_WRONG_PASSWORD:
                print(f"Wrong password for {ssid}. Trying next...")
                break

            if status in [STAT_NO_AP_FOUND, STAT_CONNECT_FAIL]:
                pass  # Continue polling

            polls += 1
            if polls % 10 == 0:
                _tick_wdt()
            await asyncio.sleep_ms(100)  # Non-blocking!

        print(f"Failed to connect to {ssid} within {timeout}s.")
        sta.disconnect()
        await asyncio.sleep_ms(200)

    print("All connection attempts failed.")
    last_connect_status = "failed"
    return False
