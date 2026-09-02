"""Pairing helpers (claim body, code normalize, identify, unclaimed halt)."""

from credentials import (
    ap_ssid,
    chip_id_hex,
    load_ap_psk,
    load_credentials,
    missing_ap_psk_repl_lines,
)
from settings import (
    DEFAULT_API,
    ESP_IMAGE_MAGIC,
    FIRMWARE_VERSION,
    OTA_ALLOWED_HOSTS,
    OTA_MIN_APP_SEGMENTS,
    PAIRING_ALPHABET,
)


def ota_header_is_app(head):
    """True if bytes look like an ESP *app* image, not a bootloader / merged USB dump.

    esptool write-flash 0 images start with the bootloader (magic 0xE9, 3 segments).
    MicroPython app images use 0xE9 with more segments (currently 7). Writing a
    merged USB .bin into ota_1 yields ESP_ERR_OTA_VALIDATE_FAILED on set_boot.
    """
    if not head or len(head) < 2:
        return False
    return head[0] == ESP_IMAGE_MAGIC and head[1] >= OTA_MIN_APP_SEGMENTS


def normalize_pairing_code(raw):
    """Uppercase, drop hyphens/spaces; None if not 8 alphabet chars."""
    out = []
    for c in str(raw or ""):
        u = c.upper()
        if u in PAIRING_ALPHABET:
            out.append(u)
    code = "".join(out)
    if len(code) != 8:
        return None
    return code


def pairing_identify_on(config):
    """True when BootFSM/ActiveFSM must blink green and skip USB SoftAP."""
    try:
        return bool(config.running["settings"].get("pairing_identify"))
    except Exception:
        return False


def recover_after_auth_reject(config):
    """401/403: drop identify lockout so USB SoftAP / PIN Forget works.

    Keep device_id/device_token so claimed USB-face SoftAP Forget remains
    available. Do not invent ap_psk.
    """
    if config is None:
        return False
    try:
        running = config.running
        if not isinstance(running, dict):
            return False
        settings = running.get("settings")
        if not isinstance(settings, dict):
            settings = {}
            running["settings"] = settings
        if not settings.get("pairing_identify"):
            return True
        settings["pairing_identify"] = False
        if hasattr(config, "apply"):
            config.apply(running)
        if hasattr(config, "save"):
            config.save()
        print(
            "API 401/403: pairing_identify cleared; USB SoftAP / PIN Forget available"
        )
        return True
    except Exception as e:
        print("auth-reject recover failed:", e)
        return False


def ota_settings_enabled(config=None, tracker=None):
    """True only when settings.ota_enabled is set. Config wins over tracker raw_config."""
    val = None
    if tracker is not None:
        try:
            raw = tracker.running.get("raw_config") or {}
            settings = raw.get("settings") or {}
            if "ota_enabled" in settings:
                val = bool(settings.get("ota_enabled"))
        except Exception:
            pass
    if config is not None:
        try:
            settings = (config.running or {}).get("settings") or {}
            if "ota_enabled" in settings:
                val = bool(settings.get("ota_enabled"))
        except Exception:
            pass
    return bool(val)


def ota_address_allowed(address):
    """HTTPS mip URL on the OTA host allowlist. Not a generic remote-config URL."""
    addr = str(address or "").strip()
    if not addr.startswith("https://"):
        return False
    from credentials import _api_host

    return _api_host(addr) in OTA_ALLOWED_HOSTS


def pairing_stack_frozen():
    """True when pairing_portal is not on the filesystem (frozen image)."""
    try:
        import os
    except ImportError:
        return False
    for name in (
        "pairing_portal.py",
        "pairing_portal.mpy",
        "pairing.py",
        "pairing.mpy",
    ):
        try:
            os.stat(name)
            return False
        except OSError:
            pass
        try:
            os.stat("/" + name)
            return False
        except OSError:
            pass
    return True


def ota_settings_blob(config=None, tracker=None):
    """GET settings, preferring live config over tracker raw_config."""
    blob = {}
    if tracker is not None:
        try:
            raw = tracker.running.get("raw_config") or {}
            settings = raw.get("settings") or {}
            if isinstance(settings, dict):
                blob.update(settings)
        except Exception:
            pass
    if config is not None:
        try:
            settings = (config.running or {}).get("settings") or {}
            if isinstance(settings, dict):
                blob.update(settings)
        except Exception:
            pass
    return blob


def ota_should_install(tracker_obj, config=None):
    """Return (ota_url, None) or (None, skip_reason). Prefers settings.ota_address."""
    if not ota_settings_enabled(config=config, tracker=tracker_obj):
        return None, "ota_enabled is false"
    blob = ota_settings_blob(config=config, tracker=tracker_obj)
    addr = blob.get("ota_address")
    if addr is None or str(addr).strip() == "":
        try:
            addr = tracker_obj.running.get("ota_address")
        except Exception:
            addr = None
    if addr is None or str(addr).strip() == "":
        return None, "no ota_address"
    addr = str(addr).strip()
    if not ota_address_allowed(addr):
        return None, "address not allowlisted"
    ver = str(blob.get("ota_version") or "")
    try:
        applied = str((tracker_obj.running or {}).get("ota_applied_version") or "")
    except Exception:
        applied = ""
    if ver and applied and ver == applied:
        return None, "already applied"
    if pairing_stack_frozen() and str(blob.get("ota_kind") or "") == "overlay":
        return None, "pairing stack frozen; USB reflash required"
    return addr, None


def overlay_name_ok(name):
    s = str(name or "")
    if not s.endswith(".py") or "/" in s or "\\" in s or ".." in s:
        return False
    if len(s) > 64 or s[0] in ".-":
        return False
    return True


def unclaimed_must_halt():
    """Unclaimed (no device_token) and no host-provisioned ap_psk."""
    cred = load_credentials() or {}
    if cred.get("device_id") and cred.get("device_token"):
        return False
    return load_ap_psk() is None


def halt_lines():
    return missing_ap_psk_repl_lines()


def claim_url(api_base=None):
    base = (api_base or DEFAULT_API).rstrip("/") + "/"
    if not base.endswith("/api/") and base.endswith("/"):
        pass
    return base + "devices/claim/"


def claim_body(pairing_code, chip_id=None, firmware_version=None):
    """JSON for POST /devices/claim/.

    House SSID/password stay in NVS. Optional SoftAP `ap_psk` only.
    """
    code = normalize_pairing_code(pairing_code)
    if not code:
        raise ValueError("pairing code")
    cid = (chip_id or chip_id_hex() or "").lower()
    if not cid:
        raise ValueError("chip_id")
    body = {
        "pairing_code": code,
        "chip_id": cid,
        "firmware_version": firmware_version or FIRMWARE_VERSION,
    }
    psk = load_ap_psk()
    if psk:
        body["ap_psk"] = str(psk)
    return body


def scan_table_rows(scan_results):
    """Dedup STA scan tuples to [{ssid, rssi, hidden}]."""
    seen = {}
    for row in scan_results or ():
        try:
            ssid_b = row[0]
            rssi = int(row[3]) if len(row) > 3 else 0
        except Exception:
            continue
        if isinstance(ssid_b, bytes):
            try:
                ssid = ssid_b.decode("utf-8")
            except Exception:
                ssid = ""
        else:
            ssid = str(ssid_b or "")
        ssid = ssid.strip()
        if not ssid:
            continue
        prev = seen.get(ssid)
        if prev is None or rssi > prev["rssi"]:
            seen[ssid] = {"ssid": ssid, "rssi": rssi, "hidden": False}
    rows = list(seen.values())
    rows.sort(key=lambda r: r["rssi"], reverse=True)
    return rows


def parse_claim_response(text):
    """Return {device_id, device_token, api_url} or None."""
    if not text:
        return None
    try:
        import ujson
    except ImportError:
        import json as ujson
    try:
        data = ujson.loads(text)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if not data.get("device_id") or not data.get("device_token"):
        return None
    from credentials import normalize_api_url

    api_url = normalize_api_url(data.get("api_url") or DEFAULT_API, require_allowlist=True)
    if not api_url:
        api_url = DEFAULT_API
    return {
        "device_id": data["device_id"],
        "device_token": data["device_token"],
        "api_url": api_url,
    }


def join_hint_ssid():
    return ap_ssid()
