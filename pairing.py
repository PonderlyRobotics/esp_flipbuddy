"""Pairing helpers (claim body, code normalize, identify, unclaimed halt)."""

from credentials import (
    ap_ssid,
    chip_id_hex,
    load_ap_psk,
    load_credentials,
    missing_ap_psk_repl_lines,
)

PAIRING_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
DEFAULT_API = "https://api.flipbuddy.app/v1/api/"
IDENTIFY_GREEN = "#00FF00"
FIRMWARE_VERSION = "0.1.5-pairing"


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
    return {
        "device_id": data["device_id"],
        "device_token": data["device_token"],
        "api_url": data.get("api_url") or DEFAULT_API,
    }


def join_hint_ssid():
    return ap_ssid()
