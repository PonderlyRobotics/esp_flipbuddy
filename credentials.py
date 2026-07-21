"""Device credentials and SoftAP settings stored in NVS (or one-time credentials.json)."""

import os

import ujson
from esp32 import NVS
from util import suppress

NVS_NS = "cred"
KEY = "json"
_nvs = None


def _get_nvs():
    global _nvs
    if _nvs is None:
        _nvs = NVS(NVS_NS)
    return _nvs


def _write_to_nvs(data):
    payload = ujson.dumps(data).encode()
    nvs = _get_nvs()
    with suppress(OSError):
        nvs.erase_key(KEY)
    nvs.set_blob(KEY, payload)
    nvs.commit()


def load_credentials():
    """Load credentials from credentials.json once (migrate to NVS) or from NVS.

    Returns a dict, or None if nothing valid is stored.
    """
    nvs = _get_nvs()
    buffer = bytearray(1024)

    try:
        with open("credentials.json") as f:
            data = ujson.load(f)
        if not isinstance(data, dict) or not data.get("device_id"):
            print("credentials.json missing device_id - not migrating")
        else:
            print("Migrating credentials from file to NVS")
            _write_to_nvs(data)
            with suppress(OSError):
                os.remove("credentials.json")
            return data
    except OSError:
        pass
    except ValueError as e:
        print("credentials.json is not valid JSON:", e)

    try:
        size = nvs.get_blob(KEY, buffer)
        if size == 0:
            raise OSError
        data = ujson.loads(buffer[:size].decode())
        if isinstance(data, dict) and data.get("device_id"):
            return data
        print("NVS credentials incomplete (no device_id)")
        return None
    except OSError:
        print("No credentials found")
        return None
    except ValueError as e:
        print("NVS credentials corrupt:", e)
        return None


def store_credentials(device_id, device_token):
    """Update device_id / device_token in NVS, preserving wifi and other keys."""
    data = load_credentials() or {}
    data["device_id"] = device_id
    data["device_token"] = device_token
    _write_to_nvs(data)
    print("Credentials saved to NVS")


def wifi_profiles_public():
    """List wifi profiles without passwords (for SoftAP status UI)."""
    data = load_credentials() or {}
    wifi = data.get("wifi") or {}
    out = []
    if not isinstance(wifi, dict):
        return out
    for name, cfg in wifi.items():
        if not isinstance(cfg, dict):
            continue
        out.append(
            {
                "name": str(name),
                "ssid": str(cfg.get("ssid") or ""),
                "hidden": bool(cfg.get("hidden")),
                "has_password": bool(cfg.get("password")),
            }
        )
    return out


def store_wifi_profile(profile_name, ssid, password, hidden=False):
    """
    Add or update one wifi.* profile in NVS.

    Empty password on update keeps the previous password (UI never echoes it).
    Does not touch device_id / device_token.
    """
    name = (profile_name or "").strip() or "default"
    ssid = (ssid or "").strip()
    if not ssid:
        raise ValueError("ssid required")
    if len(ssid) > 32:
        raise ValueError("ssid too long")
    if password is not None and len(password) > 64:
        raise ValueError("password too long")

    data = load_credentials() or {}
    if not data.get("device_id"):
        raise ValueError("no device credentials in NVS")

    wifi = data.get("wifi")
    if not isinstance(wifi, dict):
        wifi = {}
        data["wifi"] = wifi

    prev = wifi.get(name) if isinstance(wifi.get(name), dict) else {}
    entry = {
        "ssid": ssid,
        "password": password if password else prev.get("password", ""),
    }
    if hidden:
        entry["hidden"] = True

    wifi[name] = entry
    data["wifi"] = wifi
    _write_to_nvs(data)
    print("Wi-Fi profile saved:", name, "ssid=", ssid)


def _alnum_upper(s):
    out = []
    for c in str(s or ""):
        o = ord(c)
        if (48 <= o <= 57) or (65 <= o <= 90) or (97 <= o <= 122):
            out.append(c.upper() if o >= 97 else c)
    return "".join(out)


def default_ap_unlock_pin(device_id):
    """Factory SoftAP unlock PIN: last 6 alphanumeric characters of device_id."""
    raw = _alnum_upper(device_id)
    if not raw:
        return "000000"
    if len(raw) >= 6:
        return raw[-6:]
    return (raw + "000000")[:6]


def get_ap_unlock_pin(device_id=None):
    """Return SoftAP unlock PIN (custom NVS value, else factory default from device_id)."""
    data = load_credentials() or {}
    custom = data.get("ap_unlock_pin")
    if custom is not None and str(custom).strip():
        pin = _alnum_upper(custom)
        if 4 <= len(pin) <= 16:
            return pin
    if device_id is None:
        device_id = data.get("device_id") or ""
    return default_ap_unlock_pin(device_id)


def set_ap_unlock_pin(new_pin):
    """Persist a custom SoftAP unlock PIN (4-16 alphanumeric)."""
    pin = _alnum_upper(new_pin)
    if len(pin) < 4 or len(pin) > 16:
        raise ValueError("PIN must be 4-16 letters/numbers")
    data = load_credentials() or {}
    if not data.get("device_id"):
        raise ValueError("no device credentials in NVS")
    data["ap_unlock_pin"] = pin
    _write_to_nvs(data)
    print("AP unlock PIN updated")
    return pin
