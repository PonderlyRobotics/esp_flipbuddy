"""
test_fsm.py - Host runnable skeleton for testing the FSMs and helpers.

Run with:
    python -m pytest test_fsm.py -q --tb=line
    or: just test

This file mocks MicroPython modules so the tests can execute on a normal
CPython host (no hardware, no uasyncio quirks beyond real asyncio).

It focuses on:
- BaseFSM / Transition mechanics (from models)
- Helper functions (backoff, time utils)
- High-level FSM construction and skip/transition logic (Boot/Active/Upload)
- Key decision methods

The mocks are intentionally lightweight. Expand them as you add behavior.
"""

import asyncio
import json as stdjson
import sys
import time as real_time
import types
from unittest.mock import MagicMock, patch, AsyncMock

# ------------------------------------------------------------------
# Early mocks for MicroPython modules (must happen BEFORE any project imports)
# ------------------------------------------------------------------
# Provide shims for common u* modules so "import main" doesn't explode on host.
for name in ("ujson", "utime", "uasyncio", "umqtt", "urequests", "ustruct", "mip"):
    if name not in sys.modules:
        mod = types.ModuleType(name)
        sys.modules[name] = mod

# ujson shim (very common)
sys.modules["ujson"].dumps = stdjson.dumps
sys.modules["ujson"].loads = stdjson.loads
sys.modules["ujson"].dump = stdjson.dump
sys.modules["ujson"].load = stdjson.load

# utime minimal
sys.modules["utime"].time = real_time.time
sys.modules["utime"].sleep = real_time.sleep
sys.modules["utime"].sleep_ms = lambda ms: real_time.sleep(ms / 1000.0)
sys.modules["utime"].ticks_ms = lambda: int(real_time.time() * 1000)
sys.modules["utime"].ticks_diff = lambda a, b: a - b
sys.modules["utime"].localtime = real_time.localtime
sys.modules["utime"].mktime = real_time.mktime

# uasyncio -> real asyncio (most async code works)
sys.modules["uasyncio"] = asyncio

# ustruct
import struct as stdstruct

sys.modules["ustruct"].unpack = stdstruct.unpack
sys.modules["ustruct"].pack = stdstruct.pack

# Other
sys.modules["mip"].install = MagicMock()

# micropython module (for const)
mock_micropython = types.ModuleType("micropython")
mock_micropython.const = lambda x: x  # const(x) == x on host is fine for tests
sys.modules["micropython"] = mock_micropython

# --- Hardware mocks ---
mock_machine = MagicMock()
mock_machine.DEEPSLEEP_RESET = 3
mock_machine.PIN_WAKE = 2
mock_machine.reset_cause = MagicMock(return_value=0)
mock_machine.wake_reason = MagicMock(return_value=0)
mock_machine.Pin = MagicMock
mock_machine.Timer = MagicMock
mock_machine.ADC = MagicMock
mock_machine.deepsleep = MagicMock()
mock_machine.reset = MagicMock()
mock_machine.freq = MagicMock()

mock_esp32 = MagicMock()
mock_esp32.wake_on_ext0 = MagicMock()
mock_esp32.WAKEUP_ANY_HIGH = 1
mock_esp32.NVS = MagicMock

mock_neopixel = MagicMock()
mock_neopixel.NeoPixel = MagicMock(return_value=MagicMock())

mock_network = MagicMock()
mock_network.WLAN = MagicMock(
    return_value=MagicMock(
        isconnected=MagicMock(return_value=False),
        active=MagicMock(),
        connect=MagicMock(),
        disconnect=MagicMock(),
        status=MagicMock(return_value=0),
        ifconfig=MagicMock(
            return_value=("10.0.0.2", "255.255.255.0", "10.0.0.1", "8.8.8.8")
        ),
    )
)
mock_network.AP_IF = 1
mock_network.STA_IF = 0
mock_network.hostname = MagicMock()
mock_network.STAT_CONNECT_FAIL = 1
mock_network.STAT_NO_AP_FOUND = 2
mock_network.STAT_WRONG_PASSWORD = 3

mock_ntptime = MagicMock()
mock_ntptime.settime = MagicMock()

# Install the hardware mocks (override the placeholder ones)
sys.modules["machine"] = mock_machine
sys.modules["esp32"] = mock_esp32
sys.modules["neopixel"] = mock_neopixel
sys.modules["network"] = mock_network
sys.modules["ntptime"] = mock_ntptime

# Also provide "credentials" shim early so load_credentials doesn't require real file/NVS at import
mock_credentials = MagicMock()
mock_credentials.load_credentials = MagicMock(
    return_value={
        "device_id": "test123",
        "device_token": "tok456",
        "api_url": "https://example.invalid/",
        "wifi": {},
    }
)
sys.modules.setdefault("credentials", mock_credentials)

# ------------------------------------------------------------------
# Now safe to import project code
# ------------------------------------------------------------------
import main
from main import (
    BootFSM,
    ActiveFSM,
    UploadFSM,
    fibonacci,
    apply_backoff,
    reset_backoff,
    DEFAULT_SLEEP_TIME,
    MAX_SLEEP_TIME,
)
from models import BaseFSM, Transition, Config, Tracker


# ------------------------------------------------------------------
# Fixtures / helpers
# ------------------------------------------------------------------
def make_fake_np():
    np = MagicMock()
    np.__len__ = lambda self: 6
    np.n = 6
    np.fill = MagicMock()
    np.write = MagicMock()
    return np


def make_fake_tracker(np_obj=None):
    """Create a minimally functional Tracker for tests (bypasses real NVS)."""
    nvs_mock = MagicMock()
    nvs_mock.get_blob.return_value = 0
    with patch("models.NVS", return_value=nvs_mock):
        t = Tracker(np_obj or make_fake_np())
    # Reset to clean state for tests
    t.running["active_face"] = ""
    t.running["tracking_log"] = {}
    for face in t.running.get("faces", []):
        face.tracking = False
        face.activity_id = ""
        face.stop_face = False
    return t


def make_fake_config():
    nvs_mock = MagicMock()
    nvs_mock.get_blob.return_value = 0  # simulate no saved data
    with patch("models.NVS", return_value=nvs_mock):
        c = Config()
    return c


def make_fake_adc():
    adc = MagicMock()
    adc.read_uv.return_value = 3_700_000  # ~3.7V after scaling
    return adc


# ------------------------------------------------------------------
# Tests for pure helpers (no hardware)
# ------------------------------------------------------------------
def test_fibonacci_basic():
    assert fibonacci(0, 18, 900) == 18
    assert fibonacci(1, 18, 900) == 36
    assert fibonacci(2, 18, 900) == 54
    assert fibonacci(3, 18, 900) == 90
    assert fibonacci(10, 18, 900) == 900  # capped by max


def test_apply_and_reset_backoff():
    # Fresh RTC state simulation via the functions themselves
    reset_backoff(DEFAULT_SLEEP_TIME)
    sleep1 = apply_backoff(DEFAULT_SLEEP_TIME, MAX_SLEEP_TIME)
    assert sleep1 > DEFAULT_SLEEP_TIME

    reset_backoff(DEFAULT_SLEEP_TIME)
    sleep2 = apply_backoff(DEFAULT_SLEEP_TIME, MAX_SLEEP_TIME)
    assert sleep2 == sleep1  # same starting point


# ------------------------------------------------------------------
# BaseFSM tests (core engine)
# ------------------------------------------------------------------
async def test_base_fsm_simple_transitions():
    fsm = BaseFSM()
    fsm.state = "START"

    calls = []

    async def action_a():
        calls.append("a")

    def cond_b():
        return True

    async def action_b():
        calls.append("b")

    fsm.rules = {
        "START": [
            Transition("A", lambda: True, action_a),
        ],
        "A": [
            Transition("B", cond_b, action_b),
        ],
        "B": [],
    }

    await fsm.run_fsm()
    assert fsm.state == "B"
    assert calls == ["a", "b"]


async def test_base_fsm_condition_false_stops():
    fsm = BaseFSM()
    fsm.state = "S1"
    fsm.rules = {
        "S1": [
            Transition("S2", lambda: False, lambda: None),
        ],
        "S2": [],
    }
    await fsm.run_fsm()
    assert fsm.state == "S1"  # did not transition


# ------------------------------------------------------------------
# BootFSM tests
# ------------------------------------------------------------------
async def test_bootfsm_skips_on_deepsleep_reset():
    with patch.object(main, "reset_cause", return_value=main.DEEPSLEEP_RESET):
        boot = BootFSM(
            config=make_fake_config(),
            tracker=make_fake_tracker(),
            np_obj=make_fake_np(),
            adc_vin=make_fake_adc(),
            np_vcc=MagicMock(),
        )
        result = await boot.run()
        assert result == "SKIP"


async def test_bootfsm_cold_boot_runs_to_deep_sleep():
    """Cold boot should execute the full chain and end in DEEP_SLEEP state."""
    with patch.object(main, "reset_cause", return_value=0):  # not deep sleep
        # Patch heavy side effects
        with (
            patch(
                "main.wait_for_connection", new_callable=AsyncMock, return_value=True
            ),
            patch("main.ntp_settime"),
            patch("main.rgb_self_test"),
            patch("main.get_remote_config", new_callable=AsyncMock, return_value=None),
            patch("main.disconnect_wifi", new_callable=AsyncMock),
            patch("main.prepare_for_deep_sleep", new_callable=AsyncMock),
            patch(
                "main.sensor_init",
                return_value=MagicMock(
                    mean=[0] * 6, stddev=[1] * 6, upload_dmp_firmware=MagicMock()
                ),
            ),
        ):
            boot = BootFSM(
                config=make_fake_config(),
                tracker=make_fake_tracker(),
                np_obj=make_fake_np(),
                adc_vin=make_fake_adc(),
                np_vcc=MagicMock(),
            )
            # Run the FSM
            await boot.run_fsm()
            assert boot.state == "DEEP_SLEEP"
            assert boot.is_connected is True


async def test_bootfsm_offline_when_wifi_fails():
    """No Wi‑Fi: skip NTP/cloud, keep offline defaults, deep sleep (no reset loop)."""
    with (
        patch.object(main, "reset_cause", return_value=0),
        patch("main.wait_for_connection", new_callable=AsyncMock, return_value=False),
        patch("main.rgb_self_test"),
        patch("main.disconnect_wifi", new_callable=AsyncMock),
        patch("main.prepare_for_deep_sleep", new_callable=AsyncMock) as mock_sleep,
        patch(
            "main.sensor_init",
            return_value=MagicMock(
                mean=[0] * 6, stddev=[1] * 6, upload_dmp_firmware=MagicMock()
            ),
        ),
        patch("main.reset") as mock_reset,
    ):
        boot = BootFSM(
            config=make_fake_config(),
            tracker=make_fake_tracker(),
            np_obj=make_fake_np(),
            adc_vin=make_fake_adc(),
            np_vcc=MagicMock(),
        )
        await boot.run_fsm()
        assert boot.state == "DEEP_SLEEP"
        assert boot.is_connected is False
        mock_reset.assert_not_called()
        mock_sleep.assert_called()


# ------------------------------------------------------------------
# ActiveFSM tests (face + tracking decisions)
# ------------------------------------------------------------------
async def test_activefsm_face_indicator_to_detect():
    active = ActiveFSM(
        config=make_fake_config(),
        tracker=make_fake_tracker(),
        np_obj=make_fake_np(),
        adc_vin=make_fake_adc(),
        np_vcc=MagicMock(),
    )
    # Force the first transition
    active.state = "FACE_INDICATOR"
    # The transition action is show_face_indicator (now fixed name)
    # We just check that the rule exists and leads to FACE_DETECT
    transitions = active.rules.get("FACE_INDICATOR", [])
    assert len(transitions) == 1
    assert transitions[0].next_state == "FACE_DETECT"


async def test_activefsm_upload_needed_logic():
    cfg = make_fake_config()
    trk = make_fake_tracker()

    # Simulate conditions that should trigger upload
    trk.running["last_config_uploaded"] = ""
    trk.running["tracking_log"] = {"front": ["..."]}

    active = ActiveFSM(cfg, trk, make_fake_np(), make_fake_adc(), MagicMock())
    active.face_obj = MagicMock(stop_face=False, orientation="front")

    # Directly invoke the decision (it sets self.need_upload)
    await active.decide_upload()
    assert active.need_upload is True


# ------------------------------------------------------------------
# UploadFSM tests
# ------------------------------------------------------------------
async def test_uploadfsm_skips_when_not_needed():
    # scheduler_wd is a global created late in main.py
    main.scheduler_wd = MagicMock()

    active_result = {
        "sleep_ms": 18000,
        "need_upload": False,
        "face_obj": None,
        "ap_mode": False,
    }

    upload = UploadFSM(
        config=make_fake_config(),
        tracker=make_fake_tracker(),
        np_obj=make_fake_np(),
        adc_vin=make_fake_adc(),
        np_vcc=MagicMock(),
        token="dev123",
        headers={},
        active_result=active_result,
    )
    # Starting state should go to DISCONNECT when need_upload=False
    await upload.run_fsm()
    assert upload.state in ("DISCONNECT", "DEEP_SLEEP")


# ------------------------------------------------------------------
# Integration-ish: full main path with heavy mocks (smoke)
# ------------------------------------------------------------------
async def test_main_cold_boot_smoke():
    """Ensure the top-level main() doesn't explode with mocks."""
    # Inject the globals that main.main() expects (they are normally created
    # only in the if __name__ == "__main__" block of main.py)
    main.config = make_fake_config()
    main.tracker = make_fake_tracker()
    main.np_obj = make_fake_np()
    main.np_vcc = MagicMock()
    main.adc_vin = make_fake_adc()
    main.TOKEN = "test-device"
    main.HEADERS = {}
    main.scheduler_wd = MagicMock()  # referenced in some paths

    with (
        patch.object(main, "reset_cause", return_value=0),
        patch("main.wait_for_connection", new_callable=AsyncMock, return_value=True),
        patch("main.async_do_connect", new_callable=AsyncMock, return_value=True),
        patch("main.get_remote_config", new_callable=AsyncMock, return_value=None),
        patch(
            "main.push_tracking_log_to_remote",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("main.rgb_self_test"),
        patch("main.ntp_settime"),
        patch(
            "main.sensor_init",
            return_value=MagicMock(
                mean=[0] * 6,
                stddev=[1] * 6,
                _int_pin=MagicMock(),
                upload_dmp_firmware=MagicMock(),
                enable_low_power_dmp_motion_detection=MagicMock(),
                tilt_refin=MagicMock(return_value=(0, 0, 90, 0, 0, 1, 0, 0)),
            ),
        ),
        patch("main.cube_face_upward", return_value="front"),
    ):
        # Prevent real deepsleep / reset from killing the test process
        with patch("main.deepsleep"), patch("main.reset"):
            # Run the real main coroutine (it will hit deepsleep which is patched)
            await main.main()


# ------------------------------------------------------------------
# If run directly (python3 test_fsm.py)
# This allows "just test" to work even without pytest installed.
# ------------------------------------------------------------------
def _run_test(name, fn, is_async=False):
    try:
        if is_async:
            asyncio.run(fn())
        else:
            fn()
        print(f"✓ {name}")
        return True
    except AssertionError as e:
        print(f"✗ {name}: {e}")
        return False
    except Exception as e:
        print(f"✗ {name}: {type(e).__name__}: {e}")
        return False


if __name__ == "__main__":
    print("Running FSM tests (host mode, no hardware)...\n")

    results = []

    # Sync helpers
    results.append(_run_test("test_fibonacci_basic", test_fibonacci_basic))
    results.append(
        _run_test("test_apply_and_reset_backoff", test_apply_and_reset_backoff)
    )

    # Async core
    results.append(
        _run_test(
            "test_base_fsm_simple_transitions",
            test_base_fsm_simple_transitions,
            is_async=True,
        )
    )
    results.append(
        _run_test(
            "test_base_fsm_condition_false_stops",
            test_base_fsm_condition_false_stops,
            is_async=True,
        )
    )

    # FSM behavior (these now have better NVS mocks)
    results.append(
        _run_test(
            "test_bootfsm_skips_on_deepsleep_reset",
            test_bootfsm_skips_on_deepsleep_reset,
            is_async=True,
        )
    )
    results.append(
        _run_test(
            "test_bootfsm_cold_boot_runs_to_deep_sleep",
            test_bootfsm_cold_boot_runs_to_deep_sleep,
            is_async=True,
        )
    )
    results.append(
        _run_test(
            "test_bootfsm_offline_when_wifi_fails",
            test_bootfsm_offline_when_wifi_fails,
            is_async=True,
        )
    )
    results.append(
        _run_test(
            "test_activefsm_face_indicator_to_detect",
            test_activefsm_face_indicator_to_detect,
            is_async=True,
        )
    )
    results.append(
        _run_test(
            "test_activefsm_upload_needed_logic",
            test_activefsm_upload_needed_logic,
            is_async=True,
        )
    )
    results.append(
        _run_test(
            "test_uploadfsm_skips_when_not_needed",
            test_uploadfsm_skips_when_not_needed,
            is_async=True,
        )
    )

    # The heavier smoke test is more fragile; run it last
    results.append(
        _run_test("test_main_cold_boot_smoke", test_main_cold_boot_smoke, is_async=True)
    )

    passed = sum(results)
    total = len(results)
    print(f"\n{passed}/{total} tests passed")

    if passed != total:
        sys.exit(1)
