"""Host tests for cutout triad static lighting (SoftAP USB-face indicator)."""

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
    """USB face is back_cutout: left / back / bottom."""
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
