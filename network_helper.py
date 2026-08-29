import gc

import uasyncio as asyncio
import utime as time
from credentials import load_credentials, load_last_ap, store_last_ap
from micropython import const
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

SCAN_SETTLE_MS = const(250)
FAIL_FAST_MS = const(250)
SYNC_POLL_MS = const(50)
ASYNC_POLL_MS = const(100)
FAST_TIMEOUT_S = const(2)
DEFAULT_TIMEOUT_S = const(5)

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


def start_softap(essid, ip, subnet, authmode, settle_ms=250, retries=3, password=None):
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
            # config before ifconfig is more reliable on some MicroPython builds.
            # password + authmode must be the same call (IDF applies kwargs together).
            if password:
                ap.config(essid=essid, authmode=authmode, password=password)
            else:
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


def _parse_bssid(raw):
    """Normalize bssid from bytes or hex string to 6 bytes, else None."""
    if raw is None:
        return None
    if isinstance(raw, bytes):
        return raw if len(raw) == 6 else None
    if not isinstance(raw, str):
        return None
    chars = []
    for c in raw:
        if c not in ":-":
            chars.append(c)
    s = "".join(chars)
    if len(s) != 12:
        return None
    try:
        return bytes(int(s[i : i + 2], 16) for i in range(0, 12, 2))
    except ValueError:
        return None


def _bssid_hex(bssid):
    parsed = _parse_bssid(bssid)
    if not parsed:
        return None
    return "".join("%02x" % b for b in parsed)


def _scan_visible_ssids():
    """
    Active scan of nearby APs.

    Returns (ssid_set_or_None, best_by_ssid). None ssids means scan failed.
    best_by_ssid maps SSID -> {bssid, channel, rssi} (strongest RSSI).

    Hidden SSIDs do not appear here — mark those entries with ``"hidden": true``
    in credentials so we still attempt connect without a scan hit.
    """
    try:
        results = _get_sta().scan() or []
    except OSError as e:
        print("WiFi scan failed:", e)
        return None, {}

    ssids = set()
    best = {}
    for entry in results:
        if not entry:
            continue
        raw = entry[0]
        if isinstance(raw, bytes):
            name = raw.decode("utf-8", "ignore")
        else:
            name = str(raw)
        if not name:
            continue
        ssids.add(name)
        bssid = entry[1] if len(entry) > 1 else None
        channel = entry[2] if len(entry) > 2 else 0
        rssi = entry[3] if len(entry) > 3 else -127
        prev = best.get(name)
        if prev is None or rssi > prev["rssi"]:
            best[name] = {"bssid": bssid, "channel": channel, "rssi": rssi}
    print(f"WiFi scan: {len(ssids)} SSID(s) visible")
    return ssids, best


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


def _prepare_sta(low_power=False, settle_ms=0):
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
    if settle_ms:
        time.sleep_ms(settle_ms)
    # 0 = one association attempt; default unlimited reconnects burn the poll timeout
    with suppress(Exception):
        sta.config(reconnects=0)
    if low_power:
        with suppress(Exception):
            sta.config(pm=sta.PM_POWERSAVE)


def _fast_candidate(wifi_configs):
    """Last successful AP if it still has a password in credentials."""
    last = load_last_ap()
    if not last:
        return None
    ssid = last.get("ssid")
    if not ssid:
        return None
    for config in wifi_configs:
        if config.get("ssid") == ssid:
            out = dict(config)
            if last.get("bssid"):
                out["bssid"] = last["bssid"]
            if last.get("channel"):
                out["channel"] = last["channel"]
            return out
    return None


def _with_scan_hint(config, best):
    if not best:
        return config
    hint = best.get(config.get("ssid"))
    if not hint:
        return config
    merged = dict(config)
    if hint.get("bssid"):
        merged["bssid"] = hint["bssid"]
    if hint.get("channel"):
        merged["channel"] = hint["channel"]
    return merged


def _sta_outcome(sta):
    if sta.isconnected():
        return "connected"
    status = sta.status()
    if status == STAT_WRONG_PASSWORD:
        return "wrong_password"
    if status in (STAT_NO_AP_FOUND, STAT_CONNECT_FAIL):
        return "no_ap"
    return "wait"


def _start_connect(sta, config):
    ssid = config.get("ssid")
    password = config.get("password")
    bssid = _parse_bssid(config.get("bssid"))
    try:
        channel = int(config.get("channel") or 0)
    except (TypeError, ValueError):
        channel = 0
    if channel:
        with suppress(Exception):
            sta.config(channel=channel)
    print(f"Connecting to network: {ssid}...")
    if bssid:
        try:
            sta.connect(ssid, password, bssid=bssid)
        except TypeError:
            sta.connect(ssid, password)
            bssid = None
    else:
        sta.connect(ssid, password)
    return ssid, bssid


def _remember_ap(sta, ssid, bssid):
    ch = 0
    with suppress(Exception):
        ch = int(sta.config("channel") or 0)
    with suppress(Exception):
        store_last_ap(ssid, _bssid_hex(bssid), ch)


def _wait_connected(sta, timeout, poll_ms):
    start = time.ticks_ms()
    no_ap_since = None
    polls = 0
    limit = int(timeout * 1000)
    while time.ticks_diff(time.ticks_ms(), start) < limit:
        outcome = _sta_outcome(sta)
        if outcome == "connected":
            return "connected"
        if outcome == "wrong_password":
            return "wrong_password"
        if outcome == "no_ap":
            now = time.ticks_ms()
            if no_ap_since is None:
                no_ap_since = now
            elif time.ticks_diff(now, no_ap_since) >= FAIL_FAST_MS:
                return "no_ap"
        else:
            no_ap_since = None
        polls += 1
        if polls % 20 == 0:
            _tick_wdt()
        time.sleep_ms(poll_ms)
    return "timeout"


async def _wait_connected_async(sta, timeout, poll_ms):
    start = time.ticks_ms()
    no_ap_since = None
    polls = 0
    limit = int(timeout * 1000)
    while time.ticks_diff(time.ticks_ms(), start) < limit:
        outcome = _sta_outcome(sta)
        if outcome == "connected":
            return "connected"
        if outcome == "wrong_password":
            return "wrong_password"
        if outcome == "no_ap":
            now = time.ticks_ms()
            if no_ap_since is None:
                no_ap_since = now
            elif time.ticks_diff(now, no_ap_since) >= FAIL_FAST_MS:
                return "no_ap"
        else:
            no_ap_since = None
        polls += 1
        if polls % 10 == 0:
            _tick_wdt()
        await asyncio.sleep_ms(poll_ms)
    return "timeout"


def _finish_attempt(sta, ssid, bssid, outcome):
    if outcome == "connected":
        print(f"Connected to {ssid}! Config: {sta.ifconfig()}")
        _remember_ap(sta, ssid, bssid)
        return "connected"
    if outcome == "wrong_password":
        print(f"Wrong password for {ssid}. Trying next...")
    else:
        print(f"Failed to connect to {ssid} ({outcome}).")
    with suppress(Exception):
        sta.disconnect()
    return outcome


def _try_one(sta, config, timeout, poll_ms):
    ssid, bssid = _start_connect(sta, config)
    outcome = _finish_attempt(sta, ssid, bssid, _wait_connected(sta, timeout, poll_ms))
    if outcome != "connected":
        time.sleep_ms(100)
    return outcome


async def _try_one_async(sta, config, timeout, poll_ms):
    ssid, bssid = _start_connect(sta, config)
    outcome = _finish_attempt(
        sta, ssid, bssid, await _wait_connected_async(sta, timeout, poll_ms)
    )
    if outcome != "connected":
        await asyncio.sleep_ms(100)
    return outcome


def _scan_candidates(wifi_configs):
    time.sleep_ms(SCAN_SETTLE_MS)
    visible, best = _scan_visible_ssids()
    return _configs_to_try(wifi_configs, visible), best


def do_connect(timeout=DEFAULT_TIMEOUT_S, low_power=False):
    """Connect from credentials. Last AP first (no full scan); then scan fallback."""
    global last_connect_status

    _prepare_sta(low_power, settle_ms=0)
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

    fast = _fast_candidate(wifi_configs)
    if fast:
        print(f"Fast reconnect to {fast.get('ssid')}...")
        if _try_one(sta, fast, FAST_TIMEOUT_S, SYNC_POLL_MS) == "connected":
            last_connect_status = "connected"
            return True
        print("Fast reconnect failed; scanning")

    candidates, best = _scan_candidates(wifi_configs)
    if not candidates:
        print("No configured SSID visible; skipping connect attempts.")
        last_connect_status = "no_ssid"
        return False

    for config in candidates:
        merged = _with_scan_hint(config, best)
        if _try_one(sta, merged, timeout, SYNC_POLL_MS) == "connected":
            last_connect_status = "connected"
            return True

    print("All connection attempts failed.")
    last_connect_status = "failed"
    return False


async def async_do_connect(timeout=DEFAULT_TIMEOUT_S, low_power=False):
    """Async STA connect: last-AP fast path, then scan; fail-fast on NO_AP."""
    global last_connect_status

    _prepare_sta(low_power, settle_ms=0)
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

    fast = _fast_candidate(wifi_configs)
    if fast:
        print(f"Fast reconnect to {fast.get('ssid')}...")
        await asyncio.sleep_ms(0)
        if (
            await _try_one_async(sta, fast, FAST_TIMEOUT_S, ASYNC_POLL_MS)
            == "connected"
        ):
            last_connect_status = "connected"
            return True
        print("Fast reconnect failed; scanning")

    await asyncio.sleep_ms(0)
    candidates, best = _scan_candidates(wifi_configs)
    await asyncio.sleep_ms(0)
    if not candidates:
        print("No configured SSID visible; skipping connect attempts.")
        last_connect_status = "no_ssid"
        return False

    for config in candidates:
        merged = _with_scan_hint(config, best)
        if await _try_one_async(sta, merged, timeout, ASYNC_POLL_MS) == "connected":
            last_connect_status = "connected"
            return True

    print("All connection attempts failed.")
    last_connect_status = "failed"
    return False
