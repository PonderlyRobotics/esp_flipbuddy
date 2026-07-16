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
    """Load device credentials from credentials.json (once) or NVS.

    Returns a dict, or None if nothing valid is stored.
    """
    nvs = _get_nvs()
    buffer = bytearray(1024)

    try:
        with open("credentials.json") as f:
            data = ujson.load(f)
        if not isinstance(data, dict) or not data.get("device_id"):
            print("credentials.json missing device_id — not migrating")
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
