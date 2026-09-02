"""Device credentials and SoftAP settings stored in NVS.

House Wi-Fi (SSID/password) is NVS-only. Recovery `credentials.json` may carry
identity (`device_id` / `device_token`); firmware never copies `wifi` from a
filesystem file and never posts house Wi-Fi to the API.
"""

import os

import ujson
from esp32 import NVS
from settings import (
    ALLOWED_API_HOSTS,
    API_URL_FILE,
    AP_PSK_ALPHABET,
    AP_PSK_FILE,
    AP_PSK_KEY,
    AP_PSK_MIN_LEN,
    KEY,
    LAST_AP_KEY,
    NVS_NS,
)
from util import suppress

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


def _nvs_credentials_dict():
    nvs = _get_nvs()
    buffer = bytearray(1024)
    try:
        size = nvs.get_blob(KEY, buffer)
        if not size:
            return {}
        data = ujson.loads(buffer[:size].decode())
        return data if isinstance(data, dict) else {}
    except OSError:
        return {}
    except ValueError:
        print("NVS credentials corrupt")
        return {}


def _strip_house_wifi(data):
    """Drop house SSID/password so they cannot migrate from a filesystem file."""
    dropped = False
    if not isinstance(data, dict):
        return data, dropped
    if "wifi" in data:
        data.pop("wifi", None)
        dropped = True
    for k in ("ssid", "password"):
        if k in data:
            data.pop(k, None)
            dropped = True
    return data, dropped


def _remove_credentials_json():
    with suppress(OSError):
        os.remove("credentials.json")


def load_credentials():
    """Load identity from credentials.json once (migrate to NVS) or from NVS.

    House Wi-Fi in the recovery file is ignored. Existing NVS `wifi` is kept.
    The file is deleted after ingest so it cannot stay on the filesystem.
    Returns a dict, or None if nothing valid is stored.
    """
    file_data = None
    try:
        with open("credentials.json") as f:
            file_data = ujson.load(f)
    except OSError:
        file_data = None
    except ValueError as e:
        print("credentials.json is not valid JSON:", e)
        _remove_credentials_json()
        file_data = None

    if file_data is not None:
        nvs_data = _nvs_credentials_dict()
        if not isinstance(file_data, dict):
            print("credentials.json is not an object - not migrating")
            _remove_credentials_json()
        else:
            file_data, dropped = _strip_house_wifi(file_data)
            if dropped:
                print("credentials.json house Wi-Fi ignored (NVS / pairing only)")
            psk = file_data.get("ap_psk")
            if psk:
                try:
                    store_ap_psk(str(psk))
                except ValueError:
                    print("credentials.json ap_psk is not a valid SoftAP password")
            keep_wifi = nvs_data.get("wifi")
            if not isinstance(keep_wifi, dict):
                keep_wifi = None
            if file_data.get("device_id"):
                print("Migrating credentials from file to NVS")
                nvs_data.update(file_data)
                if keep_wifi:
                    nvs_data["wifi"] = keep_wifi
                else:
                    nvs_data.pop("wifi", None)
                nvs_data.pop("ap_psk", None)
                _write_to_nvs(nvs_data)
                _remove_credentials_json()
                return nvs_data
            print("credentials.json missing device_id - not migrating identity")
            _remove_credentials_json()

    data = _nvs_credentials_dict()
    if data and (
        data.get("device_id")
        or data.get("wifi")
        or data.get("ap_psk")
        or data.get("api_url")
    ):
        return data
    if data:
        print("NVS credentials incomplete (no device_id)")
        return None
    print("No credentials found")
    return None


def forget_account(keep_wifi=True):
    """Wipe SaaS identity. Keep SoftAP ap_psk. Optional keep house wifi.

    Claimed USB-face SoftAP PIN-gated Forget FlipBuddy account.
    """
    data = load_credentials() or {}
    data.pop("device_id", None)
    data.pop("device_token", None)
    data.pop("api_url", None)
    data.pop("ap_unlock_pin", None)
    if not keep_wifi:
        data["wifi"] = {}
    _write_to_nvs(data)
    print("Forget account: device_id/token/api_url/pin cleared; ap_psk kept")
    return True


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


def load_last_ap():
    """Return last successful STA AP {ssid, bssid?, channel?} or None.

    Stored on a separate NVS key so connect updates do not rewrite credentials.
    """
    nvs = _get_nvs()
    buffer = bytearray(128)
    try:
        size = nvs.get_blob(LAST_AP_KEY, buffer)
        if not size:
            return None
        data = ujson.loads(buffer[:size].decode())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("ssid"):
        return None
    return data


def store_last_ap(ssid, bssid=None, channel=0):
    """Remember the AP we just joined (ssid + optional bssid hex + channel)."""
    name = str(ssid or "").strip()
    if not name:
        return
    data = {"ssid": name}
    if bssid:
        data["bssid"] = str(bssid)
    try:
        ch = int(channel or 0)
    except (TypeError, ValueError):
        ch = 0
    if ch:
        data["channel"] = ch
    payload = ujson.dumps(data).encode()
    nvs = _get_nvs()
    with suppress(OSError):
        nvs.erase_key(LAST_AP_KEY)
    nvs.set_blob(LAST_AP_KEY, payload)
    nvs.commit()


def _normalize_ap_psk(raw):
    """Uppercase alphabet-only PSK; return None if too short."""
    out = []
    allowed = AP_PSK_ALPHABET
    for c in str(raw or ""):
        u = c.upper()
        if u in allowed:
            out.append(u)
    psk = "".join(out)
    if len(psk) < AP_PSK_MIN_LEN:
        return None
    if len(psk) > 63:
        psk = psk[:63]
    return psk


def store_ap_psk(raw):
    """Persist SoftAP join password in NVS. Host `just gen-ap-psk` is the source."""
    psk = _normalize_ap_psk(raw)
    if not psk:
        raise ValueError("ap_psk too short")
    nvs = _get_nvs()
    with suppress(OSError):
        nvs.erase_key(AP_PSK_KEY)
    nvs.set_blob(AP_PSK_KEY, psk.encode())
    nvs.commit()
    print("SoftAP PSK stored in NVS")
    return psk


def _psk_from_file_bytes(raw):
    """Parse host ap_psk.json object.

    Must not alphabet-scan the blob: the key name `ap_psk` is in the
    password alphabet and would prefix the real value.
    """
    text = str(raw or "").strip()
    if not text or text[:1] != "{":
        return None
    try:
        data = ujson.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    val = data.get("ap_psk")
    if val is None:
        return None
    s = str(val).strip()
    return s or None


def _read_ap_psk_file():
    try:
        with open(AP_PSK_FILE) as f:
            return _psk_from_file_bytes(f.read())
    except OSError:
        return None


def load_ap_psk():
    """Return NVS ap_psk, migrating from ap_psk.json once.

    Does not generate a password. OSS boot must halt if this is None and the
    cube is unclaimed (see missing_ap_psk_repl_lines).
    """
    nvs = _get_nvs()
    buffer = bytearray(64)
    try:
        size = nvs.get_blob(AP_PSK_KEY, buffer)
        if size:
            psk = _normalize_ap_psk(buffer[:size].decode())
            if psk:
                return psk
    except OSError:
        pass
    except ValueError:
        pass

    file_raw = _read_ap_psk_file()
    if file_raw:
        try:
            psk = store_ap_psk(file_raw)
            with suppress(OSError):
                os.remove(AP_PSK_FILE)
            print("SoftAP PSK %s" % psk_log_hint(psk))
            return psk
        except ValueError:
            print("ap_psk.json is not a valid SoftAP password")
    return None


def _api_host(url):
    rest = str(url or "")
    if rest.startswith("https://"):
        rest = rest[8:]
    elif rest.startswith("http://"):
        rest = rest[7:]
    else:
        return ""
    hostport = rest.split("/")[0]
    return hostport.split(":")[0].lower()


def psk_log_hint(psk):
    s = str(psk or "")
    if not s:
        return "missing"
    if len(s) < 2:
        return "set"
    return "set **%s" % s[-2:]


def normalize_api_url(raw, require_allowlist=False):
    """Return trailing-slash https API base or None."""
    url = str(raw or "").strip()
    if not url.startswith("https://"):
        return None
    url = url.rstrip("/") + "/"
    if require_allowlist and _api_host(url) not in ALLOWED_API_HOSTS:
        return None
    return url


def store_api_url(raw):
    """Persist claim/config API base in NVS. Does not copy ap_psk into the blob."""
    url = normalize_api_url(raw)
    if not url:
        raise ValueError("api_url")
    data = load_credentials() or {}
    data["api_url"] = url
    _write_to_nvs(data)
    return url


def load_api_url():
    """NVS api_url, migrating api_url.txt once. None → caller uses production default."""
    data = load_credentials() or {}
    url = normalize_api_url(data.get("api_url"))
    if url:
        return url
    try:
        with open(API_URL_FILE) as f:
            raw = f.read()
        url = store_api_url(raw)
        with suppress(OSError):
            os.remove(API_URL_FILE)
        return url
    except OSError:
        return None
    except ValueError:
        print("api_url.txt is not a valid URL")
        return None


def missing_ap_psk_repl_lines():
    """Exact REPL halt copy when unclaimed and NVS has no ap_psk."""
    return (
        "=" * 48,
        "FATAL: no SoftAP join password (NVS ap_psk).",
        "  The open-source image will not invent one at boot.",
        "  On the host, next to the justfile:",
        "    just gen-ap-psk",
        "    just put-ap-psk",
        "  Then power-cycle. Join FlipBuddy-XXXX with that password.",
        "  Reflash (BOOT button + erase-flash) wipes NVS; generate again.",
        "=" * 48,
    )


def print_missing_ap_psk_repl():
    for line in missing_ap_psk_repl_lines():
        print(line)


def chip_id_hex():
    """machine.unique_id() as lowercase hex (claim chip_id)."""
    try:
        import machine

        uid = machine.unique_id()
        if hasattr(uid, "hex"):
            return uid.hex().lower()
        from binascii import hexlify

        return hexlify(uid).decode().lower()
    except Exception:
        return ""


def ap_ssid():
    """SoftAP SSID FlipBuddy- + last 4 hex of unique_id (uppercase)."""
    hx = (chip_id_hex() or "0000").upper()
    return "FlipBuddy-" + hx[-4:]


def maintenance_ssid():
    """Claimed USB-face SSID: unique if ap_psk exists, else legacy FlipBuddy."""
    if load_ap_psk():
        return ap_ssid()
    return "FlipBuddy"


def store_wifi_profile(profile_name, ssid, password, hidden=False):
    """
    Add or update one wifi.* profile in NVS only (never a filesystem file).

    Empty password on update keeps the previous password (UI never echoes it).
    Allowed before device_id exists (pairing SoftAP).
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


def default_ap_psk(device_id):
    """WPA2 join password: FB + factory PIN (always 8 chars, independent of custom PIN)."""
    return "FB" + default_ap_unlock_pin(device_id)


def get_ap_psk():
    """SoftAP WPA2-PSK: NVS ap_psk, else claimed-legacy FB+device_id."""
    psk = load_ap_psk()
    if psk:
        return psk
    data = load_credentials() or {}
    return default_ap_psk(data.get("device_id") or "")


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
