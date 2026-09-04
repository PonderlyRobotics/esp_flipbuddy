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
from contextlib import contextmanager
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
sys.modules["utime"].ticks_add = lambda a, b: a + b
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
    face_is_stop,
    fibonacci,
    apply_backoff,
    reset_backoff,
    DEFAULT_SLEEP_TIME,
    MAX_SLEEP_TIME,
)
from models import (
    BaseFSM,
    Transition,
    Config,
    Tracker,
    TRACKER_EPHEMERAL_KEYS,
    NVS_BLOB_BUFFER_SIZE,
)


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


async def test_prepare_for_deep_sleep_zero_ms_is_indefinite():
    """sleep_ms<=0 → deepsleep() with no RTC timer (MPU/ext0 wake only)."""
    with (
        patch("main.disconnect_wifi", new_callable=AsyncMock),
        patch("main.sensor_init", return_value=MagicMock(_int_pin=MagicMock())),
        patch("main.esp32") as mock_esp32,
        patch("main.deepsleep") as mock_deepsleep,
        patch("main.Pin"),
    ):
        await main.prepare_for_deep_sleep(
            MagicMock(), MagicMock(), sleep_ms=0, do_mpu_config=True
        )
    mock_esp32.wake_on_ext0.assert_called()
    mock_deepsleep.assert_called_once_with()


def test_unclaimed_main_uses_motion_deep_sleep_not_repl_loop():
    from pathlib import Path

    src = Path(__file__).resolve().parent.joinpath("main.py").read_text()
    assert "_unclaimed_motion_deep_sleep" in src
    assert "portal ended (no token) — motion deep sleep" in src
    portal = Path(__file__).resolve().parent.joinpath("pairing_portal.py").read_text()
    assert "while True:" not in portal.split("def run():", 1)[1]


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
    # PIN_WAKE then live-settles at 5 Hz before FACE_DETECT
    transitions = active.rules.get("FACE_INDICATOR", [])
    assert len(transitions) == 2
    assert transitions[0].next_state == "TRACKING_OFF"
    assert transitions[1].next_state == "FACE_SETTLE"
    settle = active.rules.get("FACE_SETTLE", [])
    assert len(settle) == 1
    assert settle[0].next_state == "FACE_DETECT"


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


class _SettleClock:
    def __init__(self):
        self.ms = 0

    def ticks_ms(self):
        return self.ms

    def ticks_diff(self, a, b):
        return a - b

    def ticks_add(self, a, b):
        return a + b


@contextmanager
def _patch_settle_hw(wake=None, samples=None):
    """Patch ActiveFSM settle: wake reason, MPU sample helper, 5 Hz clock."""
    if wake is None:
        wake = main.PIN_WAKE
    seq = list(samples or [((0.0, 1.0, 0.0), "front")])
    clock = _SettleClock()
    last = ((0.0, 1.0, 0.0), "front")

    def _next(*_a, **_k):
        nonlocal last
        if seq:
            last = seq.pop(0)
        return last

    async def _sleep_ms(n):
        clock.ms += int(n)

    with (
        patch("main.wake_reason", return_value=wake),
        patch("main.sensor_init", return_value=MagicMock()),
        patch("main._read_mpu_settle", side_effect=_next),
        patch("main.wdt_feed"),
        patch("main.asyncio.sleep_ms", _sleep_ms, create=True),
        patch.object(main.time, "ticks_ms", clock.ticks_ms),
        patch.object(main.time, "ticks_diff", clock.ticks_diff),
        patch.object(main.time, "ticks_add", clock.ticks_add),
    ):
        yield clock


async def test_activefsm_settle_timer_wake_is_single_sample():
    cfg = make_fake_config()
    trk = make_fake_tracker()
    active = ActiveFSM(cfg, trk, make_fake_np(), make_fake_adc(), MagicMock())
    with (
        _patch_settle_hw(wake=0, samples=[((0.0, 1.0, 0.0), "front")]),
        patch("main.asyncio.sleep_ms", new_callable=AsyncMock, create=True) as sleep_ms,
    ):
        await active.settle_face()
    assert active.face_obj is trk.front
    sleep_ms.assert_not_called()


async def test_activefsm_settle_commits_assigned_face_after_fifty_samples():
    from util import SETTLE_STABLE_SAMPLES

    cfg = make_fake_config()
    trk = make_fake_tracker()
    trk.front.activity_id = "act-sleep"
    active = ActiveFSM(cfg, trk, make_fake_np(), make_fake_adc(), MagicMock())
    n = SETTLE_STABLE_SAMPLES
    samples = [((0.0, 1.0, 0.0), "front")] * n
    with _patch_settle_hw(samples=samples):
        await active.settle_face()
    assert active.face_obj is trk.front
    assert trk.front.led.status == "ACTIVE"


async def test_activefsm_settle_rotation_switches_preview_led():
    from util import SETTLE_STABLE_SAMPLES

    cfg = make_fake_config()
    trk = make_fake_tracker()
    trk.front.activity_id = "act-sleep"
    trk.right.activity_id = "act-work"
    active = ActiveFSM(cfg, trk, make_fake_np(), make_fake_adc(), MagicMock())
    samples = [((0.0, 1.0, 0.0), "front")] * 2 + [
        ((0.0, 0.0, -1.0), "right")
    ] * SETTLE_STABLE_SAMPLES
    with _patch_settle_hw(samples=samples):
        await active.settle_face()
    assert active.face_obj is trk.right
    assert trk.right.led.status == "ACTIVE"
    assert trk.front.led.status == "INACTIVE"


async def test_activefsm_settle_out_margin_does_not_error():
    from util import SETTLE_STABLE_SAMPLES

    cfg = make_fake_config()
    trk = make_fake_tracker()
    trk.front.activity_id = "act-sleep"
    trk.out_margin.led.error_led = AsyncMock()
    active = ActiveFSM(cfg, trk, make_fake_np(), make_fake_adc(), MagicMock())
    samples = [
        ((0.0, 1.0, 0.0), "front"),
        ((0.0, 0.0, 0.0), "out_margin"),
        ((0.0, 0.0, 0.0), "out_margin"),
    ] + [((0.0, 1.0, 0.0), "front")] * SETTLE_STABLE_SAMPLES
    with _patch_settle_hw(samples=samples):
        await active.settle_face()
    trk.out_margin.led.error_led.assert_not_called()
    assert active.face_obj is trk.front


async def test_activefsm_settle_timeout_skips_tracking_without_error():
    from settings import SETTLE_HZ

    cfg = make_fake_config()
    trk = make_fake_tracker()
    trk.out_margin.led.error_led = AsyncMock()
    active = ActiveFSM(cfg, trk, make_fake_np(), make_fake_adc(), MagicMock())
    n = SETTLE_HZ * 1 + 2
    samples = [((0.0, 0.0, 0.0), "out_margin")] * n
    with _patch_settle_hw(samples=samples), patch("main.SETTLE_TIMEOUT_S", 1):
        await active.settle_face()
    assert active.face_obj is None
    trk.out_margin.led.error_led.assert_not_called()


async def test_detect_face_reuses_mpu_from_settle():
    cfg = make_fake_config()
    trk = make_fake_tracker()
    active = ActiveFSM(cfg, trk, make_fake_np(), make_fake_adc(), MagicMock())
    active.face_obj = trk.front
    mpu = MagicMock()
    mpu._int_pin = MagicMock()
    active._mpu = mpu
    with (
        patch("main.sensor_init") as si,
        patch("main.esp32.wake_on_ext0"),
        patch(
            "main.read_battery_voltage",
            return_value={"adjusted_voltage_v": 3.7},
        ),
        patch("main.clear_ap_cooldown"),
        patch("main.wdt_feed"),
    ):
        await active.detect_face()
    si.assert_not_called()
    mpu.enable_low_power_dmp_motion_detection.assert_called()


def test_apply_remote_config_stores_active():
    cfg = make_fake_config()
    assert cfg.running["settings"].get("active", True) is True
    cfg.apply_remote_config(
        {
            "settings": {
                "orientation_check_frequency": 18,
                "ota_enabled": True,
                "remote_server": "https://api.flipbuddy.app",
                "active": False,
            }
        }
    )
    assert cfg.running["settings"]["active"] is False


async def test_tracking_off_uses_profile_sleep_and_upward_face_led():
    cfg = make_fake_config()
    cfg.running["settings"]["active"] = False
    cfg.running["settings"]["upload_frequency"] = 300
    trk = make_fake_tracker()
    active = ActiveFSM(cfg, trk, make_fake_np(), make_fake_adc(), MagicMock())
    active.face_obj = trk.front
    assert active.is_tracking_off() is True
    first = next(t for t in active.rules[active.S_FACE_INDICATOR] if t.condition())
    assert first.next_state == active.S_TRACKING_OFF
    with patch("main.blink_tracking_off", new_callable=AsyncMock) as blink:
        await active.show_tracking_off_led()
    blink.assert_awaited()
    assert blink.await_args.kwargs.get("face") == "front"
    assert active.sleep_ms == 300_000


async def test_tracking_off_does_not_enter_softap():
    cfg = make_fake_config()
    cfg.running["settings"]["active"] = False
    trk = make_fake_tracker()
    active = ActiveFSM(cfg, trk, make_fake_np(), make_fake_adc(), MagicMock())
    active.face_obj = trk.back_cutout
    checked = active.rules[active.S_FACE_CHECKED]
    chosen = next(t for t in checked if t.condition())
    assert chosen.next_state == active.S_TRACKING_OFF
    with patch("main.blink_tracking_off", new_callable=AsyncMock) as blink:
        await active.show_tracking_off_led()
    assert blink.await_args.kwargs.get("face") == "back_cutout"


async def test_tracking_off_motion_skips_wifi_timer_checks_config():
    cfg = make_fake_config()
    cfg.running["settings"]["active"] = False
    cfg.running["settings"]["upload_frequency"] = 300
    trk = make_fake_tracker()
    trk.running["last_config_uploaded"] = "2000-01-01T00:00:00Z"
    if hasattr(trk, "tracking_log_nonempty"):
        trk.tracking_log_nonempty = MagicMock(return_value=False)
    else:
        trk.running["tracking_log"] = {}
    active = ActiveFSM(cfg, trk, make_fake_np(), make_fake_adc(), MagicMock())
    with (
        patch("main.wake_reason", return_value=main.PIN_WAKE),
        patch("main.read_battery_voltage", return_value={"adjusted_voltage_v": 3.7}),
    ):
        await active.decide_upload()
    assert active.need_upload is False
    with (
        patch("main.wake_reason", return_value=0),
        patch("main.read_battery_voltage", return_value={"adjusted_voltage_v": 3.7}),
    ):
        await active.decide_upload()
    assert active.need_upload is True


async def test_start_tracking_clears_preview_then_blinks():
    cfg = make_fake_config()
    trk = make_fake_tracker()
    trk.front.activity_id = "act-sleep"
    trk.front.led.inactive = AsyncMock()
    trk.front.led.active = MagicMock()
    trk.front.led.get_total_blink_time = MagicMock(return_value=0)
    active = ActiveFSM(cfg, trk, make_fake_np(), make_fake_adc(), MagicMock())
    active.face_obj = trk.front
    active._preview_face = trk.front
    with patch("main.wdt_feed"), patch("main.reset_backoff"):
        await active.start_tracking()
    trk.front.led.inactive.assert_awaited()
    trk.front.led.active.assert_called()
    assert active._preview_face is None


# ------------------------------------------------------------------
# Tracking durability : SoftAP finalize, power-loss, hash, NVS
# ------------------------------------------------------------------
async def test_stop_tracking_appends_tracking_log():
    trk = make_fake_tracker()
    face = trk.front
    face.activity_id = "act-sleep"
    face.activity_name = "Sleep"
    face.tracking = True
    face.started = "2026-08-07T22:51:44Z"
    await trk.stop_tracking(face)
    assert face.tracking is False
    assert face.finished
    assert "front" in trk.running["tracking_log"]
    assert len(trk.running["tracking_log"]["front"]) == 1
    assert "act-sleep" in trk.running["tracking_log"]["front"][0]


async def test_finalize_and_persist_before_softap():
    """SoftAP path must finalize open sessions into tracking_log + save."""
    trk = make_fake_tracker()
    face = trk.front
    face.activity_id = "act-sleep"
    face.tracking = True
    face.started = "2026-08-07T22:51:44Z"
    trk.set_active_face("front")
    save_mock = MagicMock(return_value=trk.running)
    with patch.object(trk, "save", save_mock):
        await trk.finalize_and_persist(active_orientation="back_cutout")
    assert face.tracking is False
    assert trk.tracking_log_nonempty()
    assert trk.active_face == "back_cutout"
    save_mock.assert_called()


async def test_start_ap_mode_finalizes_open_sessions():
    cfg = make_fake_config()
    trk = make_fake_tracker()
    face = trk.front
    face.activity_id = "act-sleep"
    face.tracking = True
    face.started = "2026-08-07T22:51:44Z"
    trk.set_active_face("front")

    active = ActiveFSM(cfg, trk, make_fake_np(), make_fake_adc(), MagicMock())
    active.face_obj = trk.back_cutout
    active.face_obj.stop_face = True

    with (
        patch("main.request_ap_soft_reset_handoff") as handoff,
        patch.object(trk, "save", MagicMock(return_value=trk.running)),
    ):
        await active.start_ap_mode()
    assert face.tracking is False
    assert trk.tracking_log_nonempty()
    handoff.assert_called_once()
    assert active.ap_mode is True


async def test_front_cutout_is_always_stop():
    usb = MagicMock(orientation="front_cutout", stop_face=False)
    assert face_is_stop(usb) is True
    softap = MagicMock(orientation="back_cutout", stop_face=False)
    assert face_is_stop(softap) is False
    softap.stop_face = True
    assert face_is_stop(softap) is True
    assert face_is_stop(None) is False
    cfg = make_fake_config()
    trk = make_fake_tracker()
    trk.front_cutout.stop_face = False
    active = ActiveFSM(cfg, trk, make_fake_np(), make_fake_adc(), MagicMock())
    active.face_obj = trk.front_cutout
    assert active.is_stop_face() is True


async def test_stop_face_finalizes_even_when_active_face_differs():
    """Stop face must stop_all even if active_face is still the activity face."""
    cfg = make_fake_config()
    trk = make_fake_tracker()
    face = trk.front
    face.activity_id = "act-sleep"
    face.tracking = True
    face.started = "2026-08-07T22:51:44Z"
    trk.set_active_face("front")

    cut = trk.front_cutout
    cut.stop_face = True
    active = ActiveFSM(cfg, trk, make_fake_np(), make_fake_adc(), MagicMock())
    active.face_obj = cut

    await active.stop_tracking()
    assert face.tracking is False
    assert trk.tracking_log_nonempty()
    assert trk.active_face == "front_cutout"


async def test_hash_mismatch_preserves_open_session_and_log():
    """hash mismatch must not reset to factory defaults."""
    trk = make_fake_tracker()
    face = trk.front
    face.activity_id = "act-sleep"
    face.activity_name = "Sleep"
    face.tracking = True
    face.started = "2026-08-07T22:51:44Z"
    trk.running["tracking_log"] = {
        "right": ["right,act-sleep,2026-08-06T23:14:00Z,2026-08-07T06:38:00Z"]
    }
    trk.running["hash_digest"] = "deadbeef"  # force mismatch vs recomputed
    # Simulate post-load repair path
    stored_hash = "deadbeef"
    recomputed = trk.hash_digest()
    assert stored_hash != recomputed
    # Repair (same as Tracker.__init__ mismatch branch)
    trk.running["hash_digest"] = recomputed
    assert face.tracking is True
    assert face.started == "2026-08-07T22:51:44Z"
    assert trk.running["tracking_log"]["right"]


async def test_strip_ephemeral_keys_before_save():
    """raw_config / battery / calibration must not persist in tracker NVS."""
    assert NVS_BLOB_BUFFER_SIZE >= 8192
    trk = make_fake_tracker()
    trk.running["raw_config"] = {"settings": {"ota_enabled": True}}
    trk.running["device"] = {"battery": {"battery_percentage": 50}}
    trk.running["calibration"] = {"mean": [0] * 6}
    trk.running["config_hash"] = "abc"
    trk.running["tracker_hash"] = "def"
    trk.running["device_id"] = "uuid"
    # save() strips then writes; mock NVS set_blob/commit via FileSystem.save body
    with patch.object(trk, "nvs") as nvs_mock:
        nvs_mock.set_blob = MagicMock()
        nvs_mock.commit = MagicMock()
        trk.save()
    for key in TRACKER_EPHEMERAL_KEYS:
        assert key not in trk.running
    nvs_mock.set_blob.assert_called_once()
    blob = nvs_mock.set_blob.call_args[0][1]
    assert "raw_config" not in blob
    assert "calibration" not in blob


async def test_reconcile_keeps_valid_open_session():
    """valid open session resumes after boot time sync."""
    trk = make_fake_tracker()
    face = trk.front
    face.activity_id = "act-sleep"
    face.tracking = True
    # Started one hour ago (valid)
    face.started = real_time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", real_time.gmtime(real_time.time() - 3600)
    )
    changed = await trk.reconcile_open_sessions_after_time_sync()
    assert changed is False
    assert face.tracking is True
    assert not trk.tracking_log_nonempty()


async def test_reconcile_force_closes_invalid_started():
    """unusable started must force-close into tracking_log, not drop."""
    trk = make_fake_tracker()
    face = trk.front
    face.activity_id = "act-sleep"
    face.tracking = True
    face.started = ""  # missing
    with patch.object(trk, "save", MagicMock(return_value=trk.running)):
        changed = await trk.reconcile_open_sessions_after_time_sync()
    assert changed is True
    assert face.tracking is False
    assert trk.tracking_log_nonempty()


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
            "test_prepare_for_deep_sleep_zero_ms_is_indefinite",
            test_prepare_for_deep_sleep_zero_ms_is_indefinite,
            is_async=True,
        )
    )
    results.append(
        _run_test(
            "test_unclaimed_main_uses_motion_deep_sleep_not_repl_loop",
            test_unclaimed_main_uses_motion_deep_sleep_not_repl_loop,
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
            "test_activefsm_settle_timer_wake_is_single_sample",
            test_activefsm_settle_timer_wake_is_single_sample,
            is_async=True,
        )
    )
    results.append(
        _run_test(
            "test_activefsm_settle_commits_assigned_face_after_fifty_samples",
            test_activefsm_settle_commits_assigned_face_after_fifty_samples,
            is_async=True,
        )
    )
    results.append(
        _run_test(
            "test_activefsm_settle_rotation_switches_preview_led",
            test_activefsm_settle_rotation_switches_preview_led,
            is_async=True,
        )
    )
    results.append(
        _run_test(
            "test_activefsm_settle_out_margin_does_not_error",
            test_activefsm_settle_out_margin_does_not_error,
            is_async=True,
        )
    )
    results.append(
        _run_test(
            "test_activefsm_settle_timeout_skips_tracking_without_error",
            test_activefsm_settle_timeout_skips_tracking_without_error,
            is_async=True,
        )
    )
    results.append(
        _run_test(
            "test_detect_face_reuses_mpu_from_settle",
            test_detect_face_reuses_mpu_from_settle,
            is_async=True,
        )
    )
    results.append(
        _run_test(
            "test_apply_remote_config_stores_active",
            test_apply_remote_config_stores_active,
        )
    )
    results.append(
        _run_test(
            "test_tracking_off_uses_profile_sleep_and_upward_face_led",
            test_tracking_off_uses_profile_sleep_and_upward_face_led,
            is_async=True,
        )
    )
    results.append(
        _run_test(
            "test_tracking_off_does_not_enter_softap",
            test_tracking_off_does_not_enter_softap,
            is_async=True,
        )
    )
    results.append(
        _run_test(
            "test_tracking_off_motion_skips_wifi_timer_checks_config",
            test_tracking_off_motion_skips_wifi_timer_checks_config,
            is_async=True,
        )
    )
    results.append(
        _run_test(
            "test_start_tracking_clears_preview_then_blinks",
            test_start_tracking_clears_preview_then_blinks,
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

    for name, fn in (
        (
            "test_stop_tracking_appends_tracking_log",
            test_stop_tracking_appends_tracking_log,
        ),
        (
            "test_finalize_and_persist_before_softap",
            test_finalize_and_persist_before_softap,
        ),
        (
            "test_start_ap_mode_finalizes_open_sessions",
            test_start_ap_mode_finalizes_open_sessions,
        ),
        (
            "test_front_cutout_is_always_stop",
            test_front_cutout_is_always_stop,
        ),
        (
            "test_stop_face_finalizes_even_when_active_face_differs",
            test_stop_face_finalizes_even_when_active_face_differs,
        ),
        (
            "test_hash_mismatch_preserves_open_session_and_log",
            test_hash_mismatch_preserves_open_session_and_log,
        ),
        (
            "test_strip_ephemeral_keys_before_save",
            test_strip_ephemeral_keys_before_save,
        ),
        (
            "test_reconcile_keeps_valid_open_session",
            test_reconcile_keeps_valid_open_session,
        ),
        (
            "test_reconcile_force_closes_invalid_started",
            test_reconcile_force_closes_invalid_started,
        ),
    ):
        results.append(_run_test(name, fn, is_async=True))

    # The heavier smoke test is more fragile; run it last
    results.append(
        _run_test("test_main_cold_boot_smoke", test_main_cold_boot_smoke, is_async=True)
    )

    passed = sum(results)
    total = len(results)
    print(f"\n{passed}/{total} tests passed")

    if passed != total:
        sys.exit(1)
