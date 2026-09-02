"""Super Mini LittleFS hw_config overlay (pins + bring-up, not frozen)."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _just_list(src: str, key: str) -> list[str]:
    m = re.search(rf'^{key} := "([^"]+)"', src, re.M)
    assert m, f"missing {key} in justfile"
    return m.group(1).split()


def test_supermini_pin_map():
    import hw_config

    assert hw_config.HW_FAMILY == "supermini"
    assert hw_config.CHIP == "s3"
    assert hw_config.NP_VCC_PIN == 7
    assert hw_config.NP_DATA_PIN == 8
    assert hw_config.VIN_PIN == 9
    assert hw_config.MPU_INT_PIN == 10
    assert hw_config.I2C_SDA == 11
    assert hw_config.I2C_SCL == 12
    assert hw_config.NUM_LEDS == 6
    assert hw_config.USB_VOLTAGE_THRESHOLD == 4.3


def test_gpio_7_8_are_led_rail_not_i2c():
    """Super Mini: GPIO 7/8 are LED VCC / NeoPixel data, not I2C."""
    import hw_config

    assert hw_config.NP_VCC_PIN == 7
    assert hw_config.NP_DATA_PIN == 8
    assert hw_config.I2C_SDA not in (7, 8)
    assert hw_config.I2C_SCL not in (7, 8)
    assert {hw_config.I2C_SDA, hw_config.I2C_SCL} == {11, 12}


def test_hw_config_is_supermini_not_som():
    src = _read("hw_config.py")
    for banned in (
        "BQ21061",
        "BQ27427",
        "BMA400",
        "som_power",
        "CHEM",
        "ICHG",
        "TS_ENABLE",
        "pinhole",
    ):
        assert banned not in src, banned


def test_configure_board_hw_sets_led_vcc_rail_and_vin_adc(monkeypatch):
    import machine
    import hw_config

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

    np_vcc, adc_vin = hw_config.configure_board_hw()

    vcc = next(p for p in created if p.id == hw_config.NP_VCC_PIN)
    assert vcc.mode is FakePin.OUT
    assert vcc.pull is FakePin.PULL_DOWN
    assert vcc.kwargs.get("drive") is FakePin.DRIVE_2
    vcc.off.assert_called()
    assert np_vcc is vcc

    data = next(p for p in created if p.id == hw_config.NP_DATA_PIN)
    data.value.assert_called_with(0)

    assert adc_vin.pin.id == hw_config.VIN_PIN
    assert adc_vin.atten is FakeADC.ATTN_11DB
    adc_vin.width.assert_called_with(FakeADC.WIDTH_12BIT)


def test_pairing_and_ap_session_import_hw_config_pins():
    pairing = _read("pairing_portal.py")
    ap = _read("ap_session.py")
    for src, name in ((pairing, "pairing_portal"), (ap, "ap_session")):
        assert "hw_config" in src, name
        assert re.search(r"Pin\(\s*[789]\s*", src) is None, name
    assert "NP_VCC_PIN" in pairing
    assert "NP_DATA_PIN" in pairing
    assert "NUM_LEDS" in pairing
    assert "NP_DATA_PIN" in ap
    assert "VIN_PIN" in ap or "configure_board_hw" in ap
    assert "NUM_LEDS" in ap


def test_unclaimed_path_brings_up_hw_before_pairing():
    block = _read("main.py").split('if __name__ == "__main__":', 1)[1]
    cfg = block.find("configure_board_hw")
    run = block.find("pairing_portal.run()")
    assert cfg != -1
    assert run != -1
    assert cfg < run


def test_hw_config_is_littlefs_not_frozen():
    just = _read("justfile")
    device_py = _just_list(just, "device_py")
    cleaned_py = _just_list(just, "cleaned_py")
    assert "hw_config.py" in device_py
    assert "hw_config.py" not in cleaned_py

    freeze_files = re.findall(r'"([a-z0-9_]+\.py)"', _read("clean_frozen.py"))
    assert "hw_config.py" not in freeze_files

    fast = just[just.find("fast-track api_url") : just.find("diy api_url")]
    assert "hw_config.py" in fast
    diy = just[just.find("diy api_url") : just.find("pull-nvs-state")]
    assert "device_py" in diy or "hw_config.py" in diy
