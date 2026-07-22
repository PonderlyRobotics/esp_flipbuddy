"""Host tests for lazy Wi-Fi STA and SoftAP helpers."""

import network
import network_helper as nh


def test_sta_not_created_at_import():
    # Fresh module import via conftest reload leaves WLAN.created empty until use
    assert isinstance(nh.sta_if, nh._StaProxy)


def test_release_sta_without_constructing():
    network.WLAN.created.clear()
    nh._sta_if = None
    nh.release_sta()
    assert network.WLAN.created == []
    assert nh._sta_if is None


def test_get_sta_creates_once():
    network.WLAN.created.clear()
    nh._sta_if = None
    a = nh._get_sta()
    b = nh._get_sta()
    assert a is b
    # May create AP_IF cleanup + STA_IF
    ifaces = [w.iface for w in network.WLAN.created]
    assert network.STA_IF in ifaces


def test_start_softap_success():
    network.WLAN.created.clear()
    nh._sta_if = None
    ap = nh.start_softap(
        essid="FlipBuddy",
        ip="10.20.30.40",
        subnet="255.255.255.0",
        authmode=network.AUTH_OPEN,
        settle_ms=0,
        retries=1,
    )
    assert ap.active() is True
    assert ap.ifconfig()[0] == "10.20.30.40"
