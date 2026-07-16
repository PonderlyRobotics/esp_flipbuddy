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

sta_if = WLAN(STA_IF)

# Last async_do_connect / do_connect outcome for callers (e.g. skip retries).
# One of: "connected", "no_creds", "no_ssid", "failed", "already"
last_connect_status = "failed"


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
        results = sta_if.scan() or []
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
    - otherwise only try SSIDs seen in the scan, plus any marked hidden
    """
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
    hostname("FlipBuddy")
    WLAN(AP_IF).active(False)
    sta_if.active(True)
    if low_power:
        sta_if.config(pm=sta_if.PM_POWERSAVE)


def do_connect(timeout=10, low_power=False):
    """Connects to WiFi from credentials (file/NVS). Tries each configured network in order."""
    global last_connect_status

    _prepare_sta(low_power)

    if sta_if.isconnected():
        print("Already connected:", sta_if.ifconfig())
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
        sta_if.connect(ssid, password)

        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < timeout * 1000:
            status = sta_if.status()

            if sta_if.isconnected():
                print(f"Connected to {ssid}! Config: {sta_if.ifconfig()}")
                last_connect_status = "connected"
                return True

            if status == STAT_WRONG_PASSWORD:
                print(f"Wrong password for {ssid}. Trying next...")
                break  # Try next config immediately

            if status in [STAT_NO_AP_FOUND, STAT_CONNECT_FAIL]:
                # Don't break immediately, give it a moment (e.g. if AP is just starting up)
                pass

            time.sleep_ms(50)

        print(f"Failed to connect to {ssid} within {timeout}s.")
        sta_if.disconnect()
        time.sleep_ms(100)  # Brief pause before next attempt

    print("All connection attempts failed.")
    last_connect_status = "failed"
    return False


async def async_do_connect(timeout=10, low_power=False):
    """Async WiFi connect - non-blocking polling. Scans first; skips missing SSIDs."""
    global last_connect_status

    _prepare_sta(low_power)

    if sta_if.isconnected():
        print("Already connected:", sta_if.ifconfig())
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
        sta_if.connect(ssid, password)

        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < timeout * 1000:
            status = sta_if.status()

            if sta_if.isconnected():
                print(f"Connected to {ssid}! Config: {sta_if.ifconfig()}")
                last_connect_status = "connected"
                return True

            if status == STAT_WRONG_PASSWORD:
                print(f"Wrong password for {ssid}. Trying next...")
                break

            if status in [STAT_NO_AP_FOUND, STAT_CONNECT_FAIL]:
                pass  # Continue polling

            await asyncio.sleep_ms(100)  # Non-blocking!

        print(f"Failed to connect to {ssid} within {timeout}s.")
        sta_if.disconnect()
        await asyncio.sleep_ms(200)

    print("All connection attempts failed.")
    last_connect_status = "failed"
    return False
