"""Super Mini LittleFS settings overlay (pins + app consts, not frozen)."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]

_APP_MODULES = (
    "main.py",
    "ap_session.py",
    "ap_mode.py",
    "pairing.py",
    "pairing_portal.py",
    "rgb.py",
    "util.py",
    "credentials.py",
    "network_helper.py",
)

# Names that must be assigned in settings.py and not reassigned in app modules.
_MOVED = (
    "NP_VCC_PIN",
    "NP_DATA_PIN",
    "VIN_PIN",
    "MPU_INT_PIN",
    "I2C_SDA",
    "I2C_SCL",
    "NUM_LEDS",
    "USB_VOLTAGE_THRESHOLD",
    "ONBOARD_LED",
    "BATTERY_FULL_V",
    "BATTERY_CUTOFF_V",
    "BATTERY_NOMINAL_V",
    "DEFAULT_BAT_CAPACITY",
    "CPU_FREQ_HZ",
    "DEBUG",
    "SETTLE_STILL_MS",
    "FIRMWARE_VERSION",
    "OTA_APP_MAX",
    "OTA_HOLD_COLOR",
    "DEFAULT_SLEEP_TIME",
    "DEFAULT_UPLOAD_FRQ",
    "DEFAULT_OTA",
    "DEFAULT_INDICATOR_BLINK_DURATION",
    "DEFAULT_INDICATOR_BLINK_CYCLE",
    "MAX_SLEEP_TIME",
    "FACES",
    "TIMER_NUM",
    "SOFTAP_CAPTIVE_PORTAL_ENABLED",
    "AP_SSID",
    "AP_IP",
    "AP_SUBNET",
    "AP_DURATION_S",
    "SLEEP_MS",
    "MAX_PIN_ATTEMPTS",
    "UNLOCK_IDLE_MS",
    "PAIR_DURATION_S",
    "PAIRING_ALPHABET",
    "DEFAULT_API",
    "IDENTIFY_GREEN",
    "OTA_ALLOWED_HOSTS",
    "OTA_MIN_APP_SEGMENTS",
    "ESP_IMAGE_MAGIC",
    "CALIBRATION_RED",
    "CALIBRATION_GREEN",
    "CALIBRATION_BLUE",
    "MAX_INTENSITY",
    "DEFAULT_INTENSITY_LEVEL",
    "TX_DIM_FACTOR",
    "LED_PINOUT",
    "TRIAD_FACES",
    "USB_CUTOUT",
    "SOFTAP_CUTOUT",
    "ENABLE_SOFTAP_INDICATOR",
    "SOFTAP_LED_COLOR",
    "SETTLE_HZ",
    "SETTLE_STABLE_SAMPLES",
    "SETTLE_MOVE_G",
    "SETTLE_TIMEOUT_S",
    "NVS_NS",
    "KEY",
    "LAST_AP_KEY",
    "LIVE_OK_KEY",
    "AP_PSK_KEY",
    "AP_PSK_ALPHABET",
    "AP_PSK_MIN_LEN",
    "AP_PSK_LEN",
    "ALLOWED_API_HOSTS",
    "AP_PSK_FILE",
    "API_URL_FILE",
    "DEFAULT_API_URL",
    "SCAN_SETTLE_MS",
    "FAIL_FAST_MS",
    "SYNC_POLL_MS",
    "ASYNC_POLL_MS",
    "FAST_TIMEOUT_S",
    "DEFAULT_TIMEOUT_S",
    "PREVIEW_HTTP_MS",
)

_MAIN_MUST_NOT_ASSIGN = (
    "NP_VCC_PIN",
    "NP_DATA_PIN",
    "VIN_PIN",
    "ONBOARD_LED",
    "NUM_LEDS",
    "SDA_PIN",
    "SCL_PIN",
    "INTERRUPT_PIN",
    "I2C_SDA",
    "I2C_SCL",
    "MPU_INT_PIN",
    "OTA_APP_MAX",
    "DEFAULT_BAT_CAPACITY",
    "DEFAULT_SLEEP_TIME",
    "DEFAULT_UPLOAD_FRQ",
    "DEFAULT_OTA",
    "DEFAULT_INDICATOR_BLINK_DURATION",
    "DEFAULT_INDICATOR_BLINK_CYCLE",
    "FACES",
    "BATTERY_FULL_V",
    "BATTERY_CUTOFF_V",
    "BATTERY_NOMINAL_V",
    "USB_VOLTAGE_THRESHOLD",
    "TIMER_NUM",
    "DEBUG",
    "SETTLE_STILL_MS",
    "CPU_FREQ_HZ",
    "MAX_SLEEP_TIME",
    "OTA_HOLD_COLOR",
    "SOFTAP_CAPTIVE_PORTAL_ENABLED",
)


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _just_list(src: str, key: str) -> list[str]:
    m = re.search(rf'^{key} := "([^"]+)"', src, re.M)
    assert m, f"missing {key} in justfile"
    return m.group(1).split()


def _assigns(src: str, name: str) -> bool:
    return re.search(rf"^{name}\s*=", src, re.M) is not None


def test_supermini_pin_map():
    import settings

    assert settings.HW_FAMILY == "supermini"
    assert settings.CHIP == "s3"
    assert settings.NP_VCC_PIN == 7
    assert settings.NP_DATA_PIN == 8
    assert settings.VIN_PIN == 9
    assert settings.MPU_INT_PIN == 10
    assert settings.I2C_SDA == 11
    assert settings.I2C_SCL == 12
    assert settings.NUM_LEDS == 6
    assert settings.USB_VOLTAGE_THRESHOLD == 4.3
    assert settings.ONBOARD_LED == 48
    assert settings.BATTERY_FULL_V == 4.2
    assert settings.BATTERY_CUTOFF_V == 2.8
    assert settings.BATTERY_NOMINAL_V == 3.7
    assert settings.DEFAULT_BAT_CAPACITY == 550
    assert settings.CPU_FREQ_HZ == 240000000
    assert settings.DEBUG is False
    assert settings.SETTLE_STILL_MS == 10000
    assert settings.FIRMWARE_VERSION == "0.2.1"


def test_led_pinout_matches_physical_chain():
    """DIN 0..5: front, bottom, back, left, top, right."""
    import settings

    p = settings.LED_PINOUT
    assert p["front"]["led"] == 0
    assert p["bottom"]["led"] == 1
    assert p["back"]["led"] == 2
    assert p["left"]["led"] == 3
    assert p["top"]["led"] == 4
    assert p["right"]["led"] == 5
    usb = {p[f]["led"] for f in settings.TRIAD_FACES[settings.USB_CUTOUT]}
    softap = {p[f]["led"] for f in settings.TRIAD_FACES[settings.SOFTAP_CUTOUT]}
    assert settings.USB_CUTOUT == "front_cutout"
    assert settings.SOFTAP_CUTOUT == "back_cutout"
    assert settings.TRIAD_FACES["front_cutout"] == ("top", "front", "right")
    assert settings.TRIAD_FACES["back_cutout"] == ("left", "back", "bottom")
    assert usb == {4, 0, 5}
    assert softap == {3, 2, 1}


def test_overlay_face_from_tilt_matches_led_pinout():
    from settings import overlay_face_from_tilt as face

    z = (0, 0, 0)
    assert face(*z, 0, 0, 1, 0, 0) == "left"
    assert face(*z, 0, 0, -1, 0, 0) == "right"
    assert face(*z, 1, 0, 0, 0, 0) == "bottom"
    assert face(*z, -1, 0, 0, 0, 0) == "top"
    assert face(*z, 0, 1, 0, 0, 0) == "front"
    assert face(*z, 0, -1, 0, 0, 0) == "back"
    assert face(*z, 0, 0, 0, 130, -40) == "front_cutout"
    assert face(*z, 0, 0, 0, -40, 30) == "back_cutout"


def test_apply_orientation_overlay_patches_frozen_pinout():
    import settings
    import rgb

    frozen = {
        "back": {"led": 0, "type": "neopixel"},
        "left": {"led": 1, "type": "neopixel"},
        "front": {"led": 2, "type": "neopixel"},
        "bottom": {"led": 3, "type": "neopixel"},
        "right": {"led": 4, "type": "neopixel"},
        "top": {"led": 5, "type": "neopixel"},
    }
    rgb.pinout = frozen
    settings.apply_orientation_overlay()
    assert frozen["front"]["led"] == 0
    assert frozen["bottom"]["led"] == 1
    assert frozen["back"]["led"] == 2
    assert frozen is not settings.LED_PINOUT
    rgb.pinout = settings.LED_PINOUT
    settings.apply_orientation_overlay()
    assert rgb.pinout is settings.LED_PINOUT
    assert settings.LED_PINOUT["front"]["led"] == 0
    assert settings.LED_PINOUT["bottom"]["led"] == 1
    assert settings.LED_PINOUT["back"]["led"] == 2
    import mpu6050

    assert mpu6050.face_from_tilt is settings.overlay_face_from_tilt
    rgb.pinout = {name: dict(spec) for name, spec in settings.LED_PINOUT.items()}


def test_gpio_7_8_are_led_rail_not_i2c():
    """Super Mini: GPIO 7/8 are LED VCC / NeoPixel data, not I2C."""
    import settings

    assert settings.NP_VCC_PIN == 7
    assert settings.NP_DATA_PIN == 8
    assert settings.I2C_SDA not in (7, 8)
    assert settings.I2C_SCL not in (7, 8)
    assert {settings.I2C_SDA, settings.I2C_SCL} == {11, 12}


def test_settings_has_supermini_section_headings():
    src = _read("settings.py")
    for heading in (
        "# --- Identity ---",
        "# --- CPU / debug ---",
        "# --- Pins / I2C ---",
        "# --- LED VCC / VIN ADC ---",
        "# --- Product timings ---",
        "# --- SoftAP / pairing ---",
        "# --- OTA ---",
        "# --- API / credentials ---",
        "# --- LED / RGB ---",
        "# --- Orientation / settle ---",
        "# --- STA timings ---",
    ):
        assert heading in src, heading


def test_configure_board_hw_sets_led_vcc_rail_and_vin_adc(monkeypatch):
    import machine
    import settings

    created = []

    class FakePin:
        OUT = object()
        PULL_DOWN = object()
        DRIVE_2 = object()

        def __init__(self, n, mode=None, pull=None, **kwargs):
            self.id = n
            self.mode = mode
            self.pull = pull
            self.kwargs = kwargs
            self.off = MagicMock()
            self.on = MagicMock()
            self.value = MagicMock()
            created.append(self)

    class FakeADC:
        ATTN_11DB = object()
        WIDTH_12BIT = object()

        def __init__(self, pin, atten=None):
            self.pin = pin
            self.atten = atten
            self.width = MagicMock()

    monkeypatch.setattr(machine, "Pin", FakePin)
    monkeypatch.setattr(machine, "ADC", FakeADC)

    np_vcc, adc_vin = settings.configure_board_hw()

    vcc = next(p for p in created if p.id == settings.NP_VCC_PIN)
    assert vcc.mode is FakePin.OUT
    assert vcc.pull is FakePin.PULL_DOWN
    assert vcc.kwargs.get("drive") is FakePin.DRIVE_2
    vcc.off.assert_called()
    assert np_vcc is vcc

    data = next(p for p in created if p.id == settings.NP_DATA_PIN)
    data.value.assert_called_with(0)

    assert adc_vin.pin.id == settings.VIN_PIN
    assert adc_vin.atten is FakeADC.ATTN_11DB
    adc_vin.width.assert_called_with(FakeADC.WIDTH_12BIT)


def test_pairing_and_ap_session_import_settings_pins():
    pairing = _read("pairing_portal.py")
    ap = _read("ap_session.py")
    for src, name in ((pairing, "pairing_portal"), (ap, "ap_session")):
        assert "from settings import" in src, name
        assert "hw_config" not in src, name
        assert re.search(r"Pin\(\s*[789]\s*", src) is None, name
    assert "configure_board_hw" in pairing
    assert "NP_DATA_PIN" in pairing
    assert "NUM_LEDS" in pairing
    assert "Pin(NP_VCC_PIN, Pin.OUT)" not in pairing
    assert "NP_DATA_PIN" in ap
    assert "configure_board_hw" in ap
    assert "NUM_LEDS" in ap


def test_unclaimed_path_brings_up_hw_before_pairing():
    src = _read("main.py")
    block = src.split('if __name__ == "__main__":', 1)[1]
    unclaimed, claimed = block.rsplit("else:", 1)
    assert "pairing_portal.run()" in unclaimed
    assert "configure_board_hw" not in unclaimed
    assert "NeoPixel" not in unclaimed
    assert "configure_board_hw" in claimed
    assert "hw_config" not in src
    assert "from settings import" in src


def test_claimed_path_builds_strip_after_led_rail():
    src = _read("main.py")
    top = src.split('if __name__ == "__main__":', 1)[0]
    # Import-time module body must not construct the strip. The pairing-sleep
    # helper may construct NeoPixel at runtime after the portal.
    import_body = top
    marker = "async def _unclaimed_motion_deep_sleep"
    if marker in import_body:
        import_body = import_body.split(marker, 1)[0]
    assert "neopixel.NeoPixel" not in import_body
    cfg = src.rfind("configure_board_hw")
    strip = src.rfind("neopixel.NeoPixel")
    tracker = src.rfind("Tracker(np_obj)")
    assert cfg != -1 and strip != -1 and tracker != -1
    assert cfg < strip < tracker


def test_claimed_path_brings_up_led_rail_before_config():
    """Motion wake should power the strip before NVS Config/Tracker work."""
    src = _read("main.py")
    _unclaimed, claimed = src.split('if __name__ == "__main__":', 1)[1].rsplit(
        "else:", 1
    )
    rail = claimed.find("configure_board_hw")
    strip = claimed.find("neopixel.NeoPixel")
    config = claimed.find("Config()")
    tracker = claimed.find("Tracker(np_obj)")
    rail_on = claimed.find("np_vcc.on()")
    assert rail != -1 and strip != -1 and config != -1 and tracker != -1
    assert rail < strip < config < tracker
    assert "PIN_WAKE" in claimed
    assert rail_on != -1 and strip < rail_on < config


def test_rgb_pinout_is_local_dict_not_settings_alias():
    """Frozen rgb must keep its own pinout so import does not alias LittleFS settings."""
    src = _read("rgb.py")
    assert "LED_PINOUT as pinout" not in src
    assert _assigns(src, "pinout")
    import importlib

    import rgb
    import settings

    rgb = importlib.reload(rgb)
    assert rgb.pinout is not settings.LED_PINOUT
    assert rgb.pinout["front"]["led"] == settings.LED_PINOUT["front"]["led"]
    assert rgb.pinout["bottom"]["led"] == settings.LED_PINOUT["bottom"]["led"]
    assert rgb.pinout["back"]["led"] == settings.LED_PINOUT["back"]["led"]


def test_pairing_led_hw_uses_configure_board_hw():
    src = _read("pairing_portal.py")
    fn = src.split("def _led_hw():", 1)[1].split("class PairingPortal", 1)[0]
    assert "configure_board_hw" in fn
    assert "Pin(NP_VCC_PIN, Pin.OUT)" not in fn
    assert fn.find("configure_board_hw()") < fn.find("neopixel.NeoPixel")


def test_settings_is_littlefs_not_frozen():
    just = _read("justfile")
    device_py = _just_list(just, "device_py")
    cleaned_py = _just_list(just, "cleaned_py")
    assert "settings.py" in device_py
    assert "settings.py" not in cleaned_py
    assert "hw_config.py" not in device_py
    assert "hw_config.py" not in cleaned_py

    freeze_files = re.findall(r'"([a-z0-9_]+\.py)"', _read("clean_frozen.py"))
    assert "settings.py" not in freeze_files
    assert "hw_config.py" not in freeze_files

    fast = just[just.find("fast-track api_url") : just.find("diy api_url")]
    assert "settings.py" in fast
    assert "hw_config.py" not in fast
    diy = just[just.find("diy api_url") : just.find("pull-nvs-state")]
    assert "device_py" in diy or "settings.py" in diy

    put_main = just[just.find("\nput-main:") : just.find("gen-ap-psk")]
    assert "settings.py" in put_main
    assert "hw_config.py" not in put_main
    assert "cp main.py settings.py :" in put_main


def test_hw_config_py_is_gone():
    assert not (ROOT / "hw_config.py").exists()
    assert (ROOT / "settings.py").exists()


def test_main_does_not_redefine_overlay_constants():
    src = _read("main.py")
    for name in _MAIN_MUST_NOT_ASSIGN:
        assert not _assigns(src, name), name
    assert "freq(CPU_FREQ_HZ)" in src
    assert "240000000" not in src


def test_app_modules_import_settings_and_do_not_reassign_moved_consts():
    settings_src = _read("settings.py")
    for name in _MOVED:
        assert _assigns(settings_src, name), name

    for fname in _APP_MODULES:
        src = _read(fname)
        assert "from settings import" in src or "import settings" in src, fname
        for name in _MOVED:
            assert not _assigns(src, name), f"{fname} assigns {name}"
        assert "hw_config" not in src, fname


def test_portal_css_and_pair_script_stay_in_modules():
    ap = _read("ap_mode.py")
    portal = _read("pairing_portal.py")
    assert _assigns(ap, "PORTAL_CSS")
    assert _assigns(portal, "PAIR_SCRIPT")
    assert not _assigns(portal, "PAIR_DURATION_S")
    assert "PAIR_DURATION_S" in portal
    assert not _assigns(_read("settings.py"), "PORTAL_CSS")
    assert not _assigns(_read("settings.py"), "PAIR_SCRIPT")
