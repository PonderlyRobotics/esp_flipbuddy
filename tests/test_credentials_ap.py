"""Host tests for SoftAP credential helpers (PIN + wifi profiles)."""

import credentials


def _seed(device_id="devABCDEF123456"):
    credentials._write_to_nvs(
        {
            "device_id": device_id,
            "device_token": "token",
            "wifi": {},
        }
    )


def test_default_ap_unlock_pin():
    assert credentials.default_ap_unlock_pin("my-device-ABCDEF123456") == "123456"
    assert credentials.default_ap_unlock_pin("abc") == "ABC000"
    assert credentials.default_ap_unlock_pin("") == "000000"


def test_get_set_ap_unlock_pin():
    _seed()
    assert credentials.get_ap_unlock_pin() == "123456"
    credentials.set_ap_unlock_pin("my-pin-99")
    assert credentials.get_ap_unlock_pin() == "MYPIN99"
    # Invalid too short
    try:
        credentials.set_ap_unlock_pin("ab")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_store_wifi_profile_and_public():
    _seed()
    credentials.store_wifi_profile("home", "MyNet", "secret", hidden=True)
    pubs = credentials.wifi_profiles_public()
    assert len(pubs) == 1
    assert pubs[0]["ssid"] == "MyNet"
    assert pubs[0]["has_password"] is True
    assert pubs[0]["hidden"] is True
    # blank password keeps previous
    credentials.store_wifi_profile("home", "MyNet2", "", hidden=False)
    data = credentials.load_credentials()
    assert data["wifi"]["home"]["password"] == "secret"
    assert data["wifi"]["home"]["ssid"] == "MyNet2"
    assert "hidden" not in data["wifi"]["home"]


def test_store_wifi_requires_ssid():
    _seed()
    try:
        credentials.store_wifi_profile("home", "", "x")
        assert False, "expected ValueError"
    except ValueError:
        pass
