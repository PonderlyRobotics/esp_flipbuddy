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


def test_default_ap_psk_is_fb_plus_factory_pin():
    # WPA2 needs ≥8 chars; factory PIN is 6, so prefix FB.
    assert (
        credentials.default_ap_psk("d591f665-45dc-469b-ac5b-ebf8178b5778") == "FB8B5778"
    )
    assert credentials.default_ap_psk("abc") == "FBABC000"
    assert credentials.default_ap_psk("") == "FB000000"
    assert len(credentials.default_ap_psk("x")) == 8


def test_get_ap_psk_ignores_custom_unlock_pin():
    _seed("devABCDEF123456")
    assert credentials.get_ap_psk() == "FB123456"
    credentials.set_ap_unlock_pin("mypin99")
    assert credentials.get_ap_unlock_pin() == "MYPIN99"
    assert credentials.get_ap_psk() == "FB123456"


def test_get_ap_psk_without_credentials():
    credentials._nvs = None
    assert credentials.get_ap_psk() == "FB000000"


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


def test_last_ap_roundtrip_independent_of_wifi_profiles():
    _seed()
    assert credentials.load_last_ap() is None
    credentials.store_last_ap("HomeNet", bssid="aabbccddeeff", channel=6)
    last = credentials.load_last_ap()
    assert last["ssid"] == "HomeNet"
    assert last["bssid"] == "aabbccddeeff"
    assert last["channel"] == 6
    data = credentials.load_credentials()
    assert data["device_id"] == "devABCDEF123456"
    assert data["wifi"] == {}


def test_last_ap_corrupt_blob_returns_none():
    _seed()
    nvs = credentials._get_nvs()
    nvs.set_blob(credentials.LAST_AP_KEY, b"not-json")
    nvs.commit()
    assert credentials.load_last_ap() is None
