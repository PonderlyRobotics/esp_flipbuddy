"""SoftAP bring-up uses WPA2-PSK, not an open network."""

import credentials
import network
from ap_session import _bringup_softap


def test_bringup_softap_uses_stable_factory_psk():
    credentials._write_to_nvs(
        {
            "device_id": "d591f665-45dc-469b-ac5b-ebf8178b5778",
            "device_token": "tok",
            "wifi": {},
        }
    )
    ap = _bringup_softap()
    assert any(
        c.get("essid") == "FlipBuddy"
        and c.get("authmode") == network.AUTH_WPA_WPA2_PSK
        and c.get("password") == "FB8B5778"
        for c in ap.config_calls
    )
    assert all(c.get("authmode") != network.AUTH_OPEN for c in ap.config_calls)
