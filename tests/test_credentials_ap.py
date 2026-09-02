"""Host tests for SoftAP credential helpers (PIN + wifi profiles)."""

import json

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


def test_psk_from_file_bytes_json_object_only():
    raw = '{"ap_psk": "23456789"}'
    assert credentials._psk_from_file_bytes(raw) == "23456789"
    # Alphabet-scan of the whole blob would pull letters from the key name.
    assert credentials._normalize_ap_psk(raw) != "23456789"
    assert credentials._psk_from_file_bytes("23456789\n") is None
    assert credentials._psk_from_file_bytes('{"wifi": {}}') is None
    assert credentials._psk_from_file_bytes("{not json") is None


def test_load_ap_psk_migrates_json_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ap_psk.json").write_text(
        '{"ap_psk": "23456789"}\n', encoding="utf-8"
    )
    assert credentials.load_ap_psk() == "23456789"
    assert not (tmp_path / "ap_psk.json").exists()


def test_load_ap_psk_json_overwrites_nvs(tmp_path, monkeypatch):
    credentials.store_ap_psk("23456789ABCDEF")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ap_psk.json").write_text(
        '{"ap_psk": "ABCDEFGH"}\n', encoding="utf-8"
    )
    assert credentials.load_ap_psk() == "ABCDEFGH"
    assert not (tmp_path / "ap_psk.json").exists()


def test_load_ap_psk_ignores_plaintext_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ap_psk.txt").write_text("23456789\n", encoding="utf-8")
    assert credentials.load_ap_psk() is None


def test_store_and_load_ap_psk_not_derived_from_device_id():
    credentials.store_ap_psk("7k4m2q9h")
    assert credentials.load_ap_psk() == "7K4M2Q9H"
    _seed("devABCDEF123456")
    assert credentials.get_ap_psk() == "7K4M2Q9H"


def test_store_ap_psk_rejects_short():
    try:
        credentials.store_ap_psk("ABC")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_credentials_json_wifi_not_copied_to_nvs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "credentials.json").write_text(
        json.dumps(
            {
                "device_id": "devABCDEF123456",
                "device_token": "tok",
                "wifi": {"home": {"ssid": "MyNet", "password": "secret"}},
            }
        ),
        encoding="utf-8",
    )
    data = credentials.load_credentials()
    assert data["device_id"] == "devABCDEF123456"
    assert data["device_token"] == "tok"
    assert not data.get("wifi")
    assert not (tmp_path / "credentials.json").exists()


def test_credentials_json_does_not_wipe_nvs_wifi(tmp_path, monkeypatch):
    credentials.store_wifi_profile("home", "MyNet", "secret")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "credentials.json").write_text(
        json.dumps(
            {
                "device_id": "devABCDEF123456",
                "device_token": "tok",
                "wifi": {"other": {"ssid": "Cafe", "password": "nope"}},
            }
        ),
        encoding="utf-8",
    )
    data = credentials.load_credentials()
    assert data["device_id"] == "devABCDEF123456"
    assert data["wifi"]["home"]["ssid"] == "MyNet"
    assert data["wifi"]["home"]["password"] == "secret"
    assert "other" not in data["wifi"]
    assert not (tmp_path / "credentials.json").exists()


def test_store_wifi_profile_does_not_write_filesystem(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    credentials.store_wifi_profile("home", "MyNet", "secret")
    names = {p.name for p in tmp_path.iterdir()}
    assert "credentials.json" not in names
    assert "ap_psk.json" not in names


def test_store_wifi_profile_without_device_id():
    credentials.store_wifi_profile("home", "MyNet", "secret")
    pubs = credentials.wifi_profiles_public()
    assert pubs[0]["ssid"] == "MyNet"
    data = credentials.load_credentials()
    assert data["wifi"]["home"]["password"] == "secret"


def test_ap_ssid_uses_unique_id_suffix():
    assert credentials.ap_ssid() == "FlipBuddy-EEFF"
    assert credentials.chip_id_hex() == "aabbccddeeff"


def test_forget_account_keeps_ap_psk_and_wifi():
    credentials.store_ap_psk("23456789")
    _seed()
    credentials.store_api_url("https://evil.example/v1/api/")
    credentials.set_ap_unlock_pin("mypin99")
    credentials.store_wifi_profile("home", "MyNet", "secret")
    credentials.forget_account(keep_wifi=True)
    assert credentials.load_ap_psk() == "23456789"
    data = credentials.load_credentials()
    assert data is not None
    assert not data.get("device_id")
    assert not data.get("device_token")
    assert not data.get("api_url")
    assert not data.get("ap_unlock_pin")
    assert data["wifi"]["home"]["ssid"] == "MyNet"


def test_forget_account_can_drop_wifi():
    _seed()
    credentials.store_wifi_profile("home", "MyNet", "secret")
    credentials.forget_account(keep_wifi=False)
    data = credentials.load_credentials()
    assert not (data or {}).get("device_id")
    assert not (data or {}).get("wifi")


def test_load_credentials_keeps_api_url_without_device_id():
    credentials._write_to_nvs({"api_url": "https://example.invalid/v1/api/"})
    data = credentials.load_credentials()
    assert data["api_url"] == "https://example.invalid/v1/api/"
    assert not data.get("device_id")
    assert not data.get("ap_psk")


def test_store_and_load_api_url():
    url = credentials.store_api_url("https://example.invalid/v1/api")
    assert url == "https://example.invalid/v1/api/"
    assert credentials.load_api_url() == "https://example.invalid/v1/api/"
    assert "ap_psk" not in (credentials.load_credentials() or {})


def test_store_api_url_rejects_http():
    try:
        credentials.store_api_url("http://evil.example/v1/api/")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_missing_ap_psk_repl_names_just_recipes():
    text = "\n".join(credentials.missing_ap_psk_repl_lines())
    assert "just gen-ap-psk" in text
    assert "just put-ap-psk" in text
    assert "will not invent one at boot" in text
    assert "BOOT button" in text


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
