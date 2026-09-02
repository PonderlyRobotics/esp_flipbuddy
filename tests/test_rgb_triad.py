"""Host tests for cutout triad static lighting (SoftAP back-cutout indicator)."""

from unittest.mock import MagicMock, patch

import rgb

pinout = rgb.pinout


class _NP:
    def __init__(self, n=6):
        self.n = n
        self._data = [(0, 0, 0)] * n
        self.wrote = False

    def __setitem__(self, i, v):
        self._data[i] = v

    def __getitem__(self, i):
        return self._data[i]

    def write(self):
        self.wrote = True


def test_back_cutout_triad_static_is_yellow_on_usb_cutout_leds():
    """SoftAP corner is back_cutout: left / back / bottom (same yellow triad)."""
    np = _NP()
    rgb.set_cutout_triad_static(np, "back_cutout", "#FFFF00")
    on = {
        pinout["left"]["led"],
        pinout["back"]["led"],
        pinout["bottom"]["led"],
    }
    assert np.wrote is True
    for i in range(6):
        r, g, b = np[i]
        if i in on:
            assert r > 0 and g > 0 and b == 0
        else:
            assert (r, g, b) == (0, 0, 0)


def test_front_cutout_triad_does_not_light_back_cutout_leds():
    np = _NP()
    rgb.set_cutout_triad_static(np, "front_cutout", "#FFFF00")
    assert np[pinout["left"]["led"]] == (0, 0, 0)
    assert np[pinout["back"]["led"]] == (0, 0, 0)
    assert np[pinout["bottom"]["led"]] == (0, 0, 0)
    assert np[pinout["right"]["led"]] != (0, 0, 0)
    assert np[pinout["top"]["led"]] != (0, 0, 0)
    assert np[pinout["front"]["led"]] != (0, 0, 0)


def test_active_clears_stop_so_blink_can_start_after_inactive():
    """After inactive(), active() must still be able to start blinking."""
    from rgb import FaceLEDNeoPixel

    np = _NP()
    led = FaceLEDNeoPixel("front", np, mode="blinking", hex_code="#FFFF00")
    led._stop = True
    led.task = None
    with patch("rgb.asyncio.create_task", return_value=MagicMock()) as ct:
        led.active()
    assert led._stop is False
    ct.assert_called()


def test_softap_indicator_disabled_is_noop():
    np = _NP()
    prev = rgb.ENABLE_SOFTAP_INDICATOR
    try:
        rgb.ENABLE_SOFTAP_INDICATOR = False
        rgb.set_cutout_triad_static(np, "back_cutout", rgb.SOFTAP_LED_COLOR)
    finally:
        rgb.ENABLE_SOFTAP_INDICATOR = prev
    assert np.wrote is False
    assert np._data == [(0, 0, 0)] * 6


def test_pairing_portal_leds_all_six_yellow():
    np = _NP()
    vcc = MagicMock()
    rgb.show_pairing_portal_leds(np, vcc)
    vcc.on.assert_called_once()
    assert np.wrote is True
    for i in range(6):
        r, g, b = np[i]
        assert r > 0 and g > 0 and b == 0


def test_pairing_portal_leds_skipped_when_indicator_disabled():
    np = _NP()
    vcc = MagicMock()
    prev = rgb.ENABLE_SOFTAP_INDICATOR
    try:
        rgb.ENABLE_SOFTAP_INDICATOR = False
        rgb.show_pairing_portal_leds(np, vcc)
    finally:
        rgb.ENABLE_SOFTAP_INDICATOR = prev
    vcc.on.assert_not_called()
    assert np.wrote is False
    assert np._data == [(0, 0, 0)] * 6
