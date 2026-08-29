"""Pytest fixtures and MicroPython shims for host-side firmware tests."""

from __future__ import annotations

import json as stdjson
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import gc as _host_gc

import pytest

# MicroPython exposes gc.mem_free(); host CPython does not.
if not hasattr(_host_gc, "mem_free"):
    _host_gc.mem_free = lambda: 200_000  # type: ignore[attr-defined]


def _ensure_micropython_shims():
    """Install lightweight MicroPython module shims before project imports."""
    for name in (
        "ujson",
        "utime",
        "uasyncio",
        "umqtt",
        "urequests",
        "ustruct",
        "mip",
        "micropython",
    ):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)

    sys.modules["micropython"].const = lambda x: x

    sys.modules["ujson"].dumps = stdjson.dumps
    sys.modules["ujson"].loads = stdjson.loads
    sys.modules["ujson"].dump = stdjson.dump
    sys.modules["ujson"].load = stdjson.load

    import time as real_time

    utime = sys.modules["utime"]
    utime.time = real_time.time
    utime.localtime = real_time.localtime
    utime.sleep = real_time.sleep
    utime.sleep_ms = lambda ms: None
    utime.ticks_ms = lambda: int(real_time.time() * 1000)
    utime.ticks_diff = lambda a, b: a - b
    utime.ticks_add = lambda a, b: a + b
    utime.mktime = real_time.mktime

    if "machine" not in sys.modules:
        machine = types.ModuleType("machine")
        machine.reset = MagicMock()
        machine.soft_reset = MagicMock()
        machine.deepsleep = MagicMock()
        machine.unique_id = MagicMock(return_value=b"\xaa\xbb\xcc\xdd\xee\xff")
        machine.Pin = MagicMock
        machine.ADC = MagicMock
        machine.RTC = MagicMock
        machine.Timer = MagicMock
        machine.freq = MagicMock()
        machine.reset_cause = MagicMock(return_value=0)
        machine.wake_reason = MagicMock(return_value=0)
        machine.DEEPSLEEP_RESET = 1
        machine.PIN_WAKE = 2
        sys.modules["machine"] = machine

    if "network" not in sys.modules:
        network = types.ModuleType("network")
        # ESP32 port values (wifi_err_reason_t), not the CYW43 numbers.
        network.AP_IF = 0
        network.STA_IF = 1
        network.AUTH_OPEN = 0
        network.AUTH_WPA2_PSK = 3
        network.AUTH_WPA_WPA2_PSK = 4
        network.STAT_IDLE = 1000
        network.STAT_CONNECTING = 1001
        network.STAT_GOT_IP = 1010
        network.STAT_NO_AP_FOUND = 201
        network.STAT_WRONG_PASSWORD = 202
        network.STAT_CONNECT_FAIL = 203
        network.hostname = MagicMock()

        class WLAN:
            created = []
            connect_calls = []
            connect_behavior = []
            scan_results = []
            scan_count = 0
            auto_connect = False
            status_code = 0

            def __init__(self, iface):
                self.iface = iface
                self._active = False
                self._cfg = None
                self._connected = False
                self._status = WLAN.status_code
                self._config = {}
                self.config_calls = []
                WLAN.created.append(self)

            def active(self, v=None):
                if v is None:
                    return self._active
                self._active = bool(v)
                return self._active

            def isconnected(self):
                return self._connected

            def disconnect(self):
                self._connected = False

            def connect(self, ssid=None, password=None, **kw):
                WLAN.connect_calls.append({"ssid": ssid, "password": password, **kw})
                action = None
                if WLAN.connect_behavior:
                    action = WLAN.connect_behavior.pop(0)
                elif WLAN.auto_connect:
                    action = "ok"
                if action == "ok":
                    self._connected = True
                    self._status = network.STAT_GOT_IP
                elif action == "no_ap":
                    self._connected = False
                    self._status = network.STAT_NO_AP_FOUND
                elif action == "bad_pass":
                    self._connected = False
                    self._status = network.STAT_WRONG_PASSWORD
                elif action == "fail":
                    self._connected = False
                    self._status = network.STAT_CONNECT_FAIL

            def status(self):
                return self._status

            def scan(self):
                WLAN.scan_count += 1
                return list(WLAN.scan_results)

            def ifconfig(self, cfg=None):
                if cfg is not None:
                    self._cfg = cfg
                if self._connected:
                    return self._cfg or (
                        "192.168.1.2",
                        "255.255.255.0",
                        "192.168.1.1",
                        "8.8.8.8",
                    )
                return self._cfg or ("0.0.0.0", "0.0.0.0", "0.0.0.0", "0.0.0.0")

            def config(self, *args, **k):
                if k:
                    self.config_calls.append(dict(k))
                    self._config.update(k)
                    return None
                if args:
                    return self._config.get(args[0])
                return None

            PM_POWERSAVE = 1

        network.WLAN = WLAN
        sys.modules["network"] = network

    if "esp32" not in sys.modules:
        esp32 = types.ModuleType("esp32")

        class NVS:
            store = {}

            def __init__(self, ns):
                self.ns = ns
                NVS.store.setdefault(ns, {})

            def erase_key(self, key):
                NVS.store.setdefault(self.ns, {}).pop(key, None)

            def set_blob(self, key, value):
                NVS.store.setdefault(self.ns, {})[key] = bytes(value)

            def get_blob(self, key, buf):
                data = NVS.store.setdefault(self.ns, {}).get(key)
                if data is None:
                    raise OSError
                n = min(len(data), len(buf))
                buf[:n] = data[:n]
                return len(data)

            def commit(self):
                pass

        esp32.NVS = NVS
        esp32.wake_on_ext0 = MagicMock()
        sys.modules["esp32"] = esp32

    if "neopixel" not in sys.modules:
        neopixel = types.ModuleType("neopixel")

        class NeoPixel:
            def __init__(self, pin, n):
                self.n = n
                self._data = [(0, 0, 0)] * n

            def __setitem__(self, i, v):
                self._data[i] = v

            def __getitem__(self, i):
                return self._data[i]

            def write(self):
                pass

            def fill(self, v):
                self._data = [v] * self.n

        neopixel.NeoPixel = NeoPixel
        sys.modules["neopixel"] = neopixel

    if "uasyncio" in sys.modules:
        import asyncio as real_asyncio

        if not hasattr(real_asyncio, "sleep_ms"):

            async def _sleep_ms(ms):
                await real_asyncio.sleep(0)

            real_asyncio.sleep_ms = _sleep_ms
        sys.modules["uasyncio"] = real_asyncio


_ensure_micropython_shims()


def _clear_nvs_store():
    """Clear host NVS mock if present (ignore MagicMock / incomplete shims)."""
    esp32 = sys.modules.get("esp32")
    nvs = getattr(esp32, "NVS", None) if esp32 is not None else None
    store = getattr(nvs, "store", None) if nvs is not None else None
    if store is not None and hasattr(store, "clear"):
        store.clear()


_SECRET_FS_NAMES = frozenset(
    ("credentials.json", "ap_psk.json", "api_url.txt")
)


@pytest.fixture(autouse=True)
def _ignore_workspace_credentials_json(monkeypatch):
    """Keep host tests on NVS; do not read repo-root secret files."""
    import builtins

    real_open = builtins.open
    repo = Path(__file__).resolve().parents[1]

    def guarded(path, *args, **kwargs):
        name = path if isinstance(path, str) else getattr(path, "name", path)
        p = Path(str(name))
        if p.name in _SECRET_FS_NAMES:
            resolved = p if p.is_absolute() else (Path.cwd() / p)
            try:
                resolved = resolved.resolve()
            except OSError:
                pass
            if resolved.parent == repo:
                raise OSError(2, "No such file")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded)


@pytest.fixture(autouse=True)
def _reset_nvs():
    """Isolate NVS state between tests."""
    _clear_nvs_store()
    network = sys.modules.get("network")
    wlan = getattr(network, "WLAN", None) if network is not None else None
    created = getattr(wlan, "created", None) if wlan is not None else None
    if created is not None and hasattr(created, "clear"):
        created.clear()
    if wlan is not None:
        if hasattr(wlan, "connect_calls"):
            wlan.connect_calls = []
        if hasattr(wlan, "connect_behavior"):
            wlan.connect_behavior = []
        if hasattr(wlan, "scan_results"):
            wlan.scan_results = []
        if hasattr(wlan, "scan_count"):
            wlan.scan_count = 0
        if hasattr(wlan, "auto_connect"):
            wlan.auto_connect = False
        if hasattr(wlan, "status_code"):
            wlan.status_code = 0
    # Drop cached project modules so they re-bind to fresh NVS
    for mod in ("credentials", "ap_mode", "network_helper", "ap_session", "pairing"):
        sys.modules.pop(mod, None)
    yield
    _clear_nvs_store()
