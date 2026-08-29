"""Host tests for last-AP fast reconnect and fail-fast STA connect."""

import network
import network_helper as nh
import credentials


class FakeClock:
    def __init__(self):
        self.ms = 0
        self.sleeps = []

    def ticks_ms(self):
        return self.ms

    def ticks_diff(self, a, b):
        return a - b

    def sleep_ms(self, n):
        self.sleeps.append(int(n))
        self.ms += int(n)

    def sleep(self, n):
        self.sleep_ms(int(n * 1000))


def _clock():
    clock = FakeClock()
    nh.time = clock
    return clock


def _reset():
    nh._sta_if = None
    nh.last_connect_status = "failed"
    network.WLAN.created.clear()
    network.WLAN.connect_calls = []
    network.WLAN.connect_behavior = []
    network.WLAN.scan_results = []
    network.WLAN.scan_count = 0
    network.WLAN.auto_connect = False
    nvs = credentials._get_nvs()
    try:
        nvs.erase_key(credentials.LAST_AP_KEY)
    except OSError:
        pass


def _seed_wifi(ssid="Home", password="secret"):
    credentials._write_to_nvs(
        {
            "device_id": "dev1",
            "device_token": "tok",
            "wifi": {"home": {"ssid": ssid, "password": password}},
        }
    )


def _sta():
    for w in reversed(network.WLAN.created):
        if w.iface == network.STA_IF:
            return w
    return None


def test_do_connect_no_creds_does_not_scan():
    _reset()
    _clock()
    ok = nh.do_connect(timeout=5)
    assert ok is False
    assert nh.last_connect_status == "no_creds"
    assert network.WLAN.scan_count == 0
    assert network.WLAN.connect_calls == []


def test_fast_reconnect_skips_scan_and_uses_bssid_channel():
    _reset()
    clock = _clock()
    _seed_wifi()
    credentials.store_last_ap("Home", bssid="aabbccddeeff", channel=6)
    network.WLAN.auto_connect = True

    ok = nh.do_connect(timeout=5)
    assert ok is True
    assert nh.last_connect_status == "connected"
    assert network.WLAN.scan_count == 0
    assert 250 not in clock.sleeps
    call = network.WLAN.connect_calls[0]
    assert call["ssid"] == "Home"
    assert call["password"] == "secret"
    assert call["bssid"] == bytes.fromhex("aabbccddeeff")
    sta = _sta()
    assert any(c.get("channel") == 6 for c in sta.config_calls)
    assert any(c.get("reconnects") == 0 for c in sta.config_calls)


def test_fast_reconnect_unknown_ssid_falls_back_to_scan():
    _reset()
    _clock()
    _seed_wifi("Home", "secret")
    credentials.store_last_ap("Gone", bssid="aabbccddeeff", channel=1)
    network.WLAN.scan_results = [
        (b"Home", bytes.fromhex("010203040506"), 11, -40, 3, False)
    ]
    network.WLAN.connect_behavior = ["ok"]

    ok = nh.do_connect(timeout=5)
    assert ok is True
    assert network.WLAN.scan_count == 1
    call = network.WLAN.connect_calls[0]
    assert call["ssid"] == "Home"
    assert call["bssid"] == bytes.fromhex("010203040506")


def test_scan_path_skips_ssid_not_visible():
    _reset()
    _clock()
    credentials._write_to_nvs(
        {
            "device_id": "dev1",
            "device_token": "tok",
            "wifi": {
                "home": {"ssid": "Home", "password": "a"},
                "office": {"ssid": "Office", "password": "b"},
            },
        }
    )
    network.WLAN.scan_results = [
        (b"Home", bytes.fromhex("010203040506"), 6, -50, 3, False)
    ]
    network.WLAN.connect_behavior = ["ok"]

    ok = nh.do_connect(timeout=5)
    assert ok is True
    ssids = [c["ssid"] for c in network.WLAN.connect_calls]
    assert ssids == ["Home"]


def test_no_ap_fail_fast_does_not_burn_full_timeout():
    _reset()
    clock = _clock()
    _seed_wifi()
    network.WLAN.scan_results = [
        (b"Home", bytes.fromhex("010203040506"), 6, -50, 3, False)
    ]
    network.WLAN.connect_behavior = ["no_ap"]

    ok = nh.do_connect(timeout=5)
    assert ok is False
    assert nh.last_connect_status == "failed"
    assert clock.ms < 2000


def test_wrong_password_fails_faster_than_timeout():
    _reset()
    clock = _clock()
    _seed_wifi()
    network.WLAN.scan_results = [
        (b"Home", bytes.fromhex("010203040506"), 6, -50, 3, False)
    ]
    network.WLAN.connect_behavior = ["bad_pass"]

    ok = nh.do_connect(timeout=5)
    assert ok is False
    assert clock.ms < 1000


def test_successful_connect_remembers_last_ap():
    _reset()
    _clock()
    _seed_wifi()
    network.WLAN.scan_results = [
        (b"Home", bytes.fromhex("aabbccddeeff"), 6, -40, 3, False)
    ]
    network.WLAN.connect_behavior = ["ok"]

    assert nh.do_connect(timeout=5) is True
    assert network.WLAN.scan_count == 1
    last = credentials.load_last_ap()
    assert last["ssid"] == "Home"
    assert last["bssid"] == "aabbccddeeff"
    assert last["channel"] == 6


def test_fast_path_no_ap_then_scan_connects_with_scan_bssid():
    _reset()
    _clock()
    _seed_wifi()
    credentials.store_last_ap("Home", bssid="deadbeef0001", channel=1)
    network.WLAN.scan_results = [
        (b"Home", bytes.fromhex("aabbccddeeff"), 11, -30, 3, False)
    ]
    network.WLAN.connect_behavior = ["no_ap", "ok"]

    ok = nh.do_connect(timeout=5)
    assert ok is True
    assert network.WLAN.scan_count == 1
    assert len(network.WLAN.connect_calls) == 2
    assert network.WLAN.connect_calls[0]["bssid"] == bytes.fromhex("deadbeef0001")
    assert network.WLAN.connect_calls[1]["bssid"] == bytes.fromhex("aabbccddeeff")
