"""Host tests for pairing helpers (v0.2.1)."""

import importlib.util
import json
import types
from pathlib import Path
from unittest.mock import MagicMock

import credentials
import pairing
from http import HttpAuthError, http_result_for_status, is_http_auth_error
from pairing_portal import PairingPortal, generate_pairing_html, parse_pair_form
from rgb import set_all_pixels
from settings import IDENTIFY_GREEN, OTA_APP_MAX


def test_firmware_version():
    assert pairing.FIRMWARE_VERSION == "0.2.1"


def test_claim_url_default_is_production_v1():
    assert pairing.DEFAULT_API.rstrip("/").endswith("/v1/api")
    assert pairing.claim_url() == "https://api.flipbuddy.app/v1/api/devices/claim/"
    assert "/v2/api/" not in pairing.claim_url()


def test_http_401_403_surface_as_auth_error():
    err = http_result_for_status("401", "")
    assert is_http_auth_error(err)
    assert err.status == 401
    assert not err
    err403 = http_result_for_status(403, "nope")
    assert is_http_auth_error(err403)
    assert err403.status == 403
    assert http_result_for_status("200", '{"ok":true}') == '{"ok":true}'
    assert http_result_for_status("500", "x") is None
    assert not is_http_auth_error(None)
    assert isinstance(HttpAuthError(401), HttpAuthError)


class _FakeConfig:
    def __init__(self, identify=True):
        self.running = {"settings": {"pairing_identify": identify}}
        self.saved = False

    def apply(self, running):
        self.running = running

    def save(self):
        self.saved = True


def test_recover_after_401_clears_pairing_identify_keeps_token():
    credentials.store_ap_psk("23456789ABCDEF")
    credentials._write_to_nvs(
        {
            "device_id": "devABCDEF123456",
            "device_token": "tok",
            "wifi": {},
        }
    )
    cfg = _FakeConfig(identify=True)
    assert pairing.pairing_identify_on(cfg) is True
    assert pairing.recover_after_auth_reject(cfg) is True
    assert pairing.pairing_identify_on(cfg) is False
    assert cfg.running["settings"]["pairing_identify"] is False
    assert cfg.saved is True
    cred = credentials.load_credentials()
    assert cred["device_id"] == "devABCDEF123456"
    assert cred["device_token"] == "tok"
    assert credentials.load_ap_psk() == "23456789ABCDEF"


def test_recover_after_401_already_cleared_does_not_save():
    cfg = _FakeConfig(identify=False)
    assert pairing.recover_after_auth_reject(cfg) is True
    assert cfg.saved is False


def test_ota_skips_while_pairing_identify():
    cfg = types.SimpleNamespace(
        running={
            "settings": {
                "ota_enabled": True,
                "pairing_identify": True,
                "ota_address": "https://api.flipbuddy.app/v1/api/sensor/ota/",
            }
        }
    )
    trk = types.SimpleNamespace(running={})
    addr, skip = pairing.ota_should_install(trk, cfg)
    assert addr is None
    assert skip == "pairing_identify"


def test_ota_enabled_false_skips():
    trk = types.SimpleNamespace(
        running={
            "ota_address": "https://api.flipbuddy.app/mip/pkg",
            "raw_config": {"settings": {"ota_enabled": True}},
        }
    )
    cfg = types.SimpleNamespace(running={"settings": {"ota_enabled": False}})
    addr, skip = pairing.ota_should_install(trk, cfg)
    assert addr is None
    assert skip == "ota_enabled is false"


def test_ota_missing_address_skips():
    trk = types.SimpleNamespace(
        running={"raw_config": {"settings": {"ota_enabled": True}}}
    )
    cfg = types.SimpleNamespace(running={"settings": {"ota_enabled": True}})
    addr, skip = pairing.ota_should_install(trk, cfg)
    assert addr is None
    assert skip == "no ota_address"
    empty = types.SimpleNamespace(
        running={
            "ota_address": "",
            "raw_config": {"settings": {"ota_enabled": True}},
        }
    )
    addr, skip = pairing.ota_should_install(empty, cfg)
    assert addr is None
    assert skip == "no ota_address"


def test_ota_rejects_non_allowlisted_address():
    cfg = types.SimpleNamespace(running={"settings": {"ota_enabled": True}})
    trk = types.SimpleNamespace(
        running={"ota_address": "https://evil.example/mip/pkg"}
    )
    addr, skip = pairing.ota_should_install(trk, cfg)
    assert addr is None
    assert skip == "address not allowlisted"
    assert pairing.ota_address_allowed("http://api.flipbuddy.app/pkg") is False
    assert pairing.ota_address_allowed("https://api.flipbuddy.app/v2/api/sensor/ota/") is True


def test_pairing_stack_not_frozen_when_sources_on_fs():
    assert pairing.pairing_stack_frozen() is False


def test_ota_skips_frozen_pairing_stack(monkeypatch):
    cfg = types.SimpleNamespace(
        running={
            "settings": {
                "ota_enabled": True,
                "ota_address": "https://api.flipbuddy.app/v2/api/sensor/ota/",
                "ota_kind": "overlay",
            }
        }
    )
    trk = types.SimpleNamespace(running={})
    monkeypatch.setattr(pairing, "pairing_stack_frozen", lambda: True)
    addr, skip = pairing.ota_should_install(trk, cfg)
    assert addr is None
    assert "frozen" in skip


def test_ota_uses_settings_address():
    cfg = types.SimpleNamespace(
        running={
            "settings": {
                "ota_enabled": True,
                "ota_address": "https://api.flipbuddy.app/v2/api/sensor/ota/",
                "ota_version": "0.2.1",
                "ota_kind": "overlay",
            }
        }
    )
    now = 1_800_000_000
    trk = types.SimpleNamespace(
        running={"ota_applied_version": "", "last_ota_check": now - 8 * 86400}
    )
    addr, skip = pairing.ota_should_install(trk, cfg, now=now)
    assert skip is None
    assert addr.endswith("/sensor/ota/")
    trk.running["ota_applied_version"] = "0.2.1"
    addr, skip = pairing.ota_should_install(trk, cfg, now=now)
    assert addr is None
    assert skip == "already applied"


def test_ota_interval_skips_first_check_and_respects_days():
    cfg = types.SimpleNamespace(
        running={
            "settings": {
                "ota_enabled": True,
                "ota_address": "https://api.flipbuddy.app/v2/api/sensor/ota/",
                "ota_version": "0.2.1",
            }
        }
    )
    now = 1_800_000_000
    fresh = types.SimpleNamespace(running={"ota_applied_version": ""})
    addr, skip = pairing.ota_should_install(fresh, cfg, now=now)
    assert addr is None
    assert skip == "ota interval arm"
    addr, skip = pairing.ota_should_install(fresh, cfg, now=0)
    assert skip == "ota clock not set"
    waiting = types.SimpleNamespace(
        running={"ota_applied_version": "", "last_ota_check": now - 2 * 86400}
    )
    addr, skip = pairing.ota_should_install(waiting, cfg, now=now)
    assert addr is None
    assert skip == "ota interval not due"
    due = types.SimpleNamespace(
        running={"ota_applied_version": "", "last_ota_check": now - 8 * 86400}
    )
    addr, skip = pairing.ota_should_install(due, cfg, now=now)
    assert skip is None
    assert addr.endswith("/sensor/ota/")
    cfg.running["settings"]["ota_frequency"] = 1
    sooner = types.SimpleNamespace(
        running={"ota_applied_version": "", "last_ota_check": now - 2 * 86400}
    )
    addr, skip = pairing.ota_should_install(sooner, cfg, now=now)
    assert skip is None
    assert pairing.ota_interval_days(cfg) == 1
    cfg.running["settings"]["ota_frequency"] = 0
    assert pairing.ota_interval_days(cfg) == 7


def test_ota_weekly_check_only_from_upload_not_boot():
    src = Path(__file__).resolve().parents[1].joinpath("main.py").read_text(encoding="utf-8")
    fetch = src.split("async def fetch_config", 1)[1].split("async def ", 1)[0]
    assert "ota_weekly_check" not in fetch
    assert src.count("await ota_weekly_check(") == 1
    upload = src.split("async def do_upload", 1)[1].split("async def ", 1)[0]
    assert "ota_weekly_check" in upload


def test_main_does_not_import_pairing_at_module_level():
    """Claimed PIN_WAKE must not compile/import pairing before the LED map."""
    src = Path(__file__).resolve().parents[1].joinpath("main.py").read_text(encoding="utf-8")
    for i, line in enumerate(src.splitlines(), 1):
        code = line.split("#", 1)[0].rstrip()
        if not code or code.startswith((" ", "\t")):
            continue
        assert not code.startswith("from pairing import"), f"module-level pairing import:{i}:{code}"
        assert code != "import pairing" and not code.startswith("import pairing,"), (
            f"module-level pairing import:{i}:{code}"
        )
    assert "from pairing import ota_should_install" in src
    assert "from pairing import pairing_identify_on" in src


def test_normalize_pairing_code():
    assert pairing.normalize_pairing_code("7k4m-2q9h") == "7K4M2Q9H"
    assert pairing.normalize_pairing_code("short") is None
    assert pairing.normalize_pairing_code("00000000") is None


def test_claim_body_omits_house_wifi():
    credentials.store_ap_psk("23456789")
    credentials.store_wifi_profile("home", "MyNet", "super-secret-wifi")
    body = pairing.claim_body("7K4M2Q9H", chip_id="AABBCCDDEEFF")
    assert "wifi" not in body
    assert "ssid" not in body
    assert "password" not in body
    dumped = json.dumps(body)
    assert "MyNet" not in dumped
    assert "super-secret-wifi" not in dumped
    assert body["pairing_code"] == "7K4M2Q9H"
    assert body["chip_id"] == "aabbccddeeff"
    assert body["ap_psk"] == "23456789"
    assert set(body) <= {"pairing_code", "chip_id", "firmware_version", "ap_psk"}


def test_unclaimed_must_halt_without_psk():
    assert pairing.unclaimed_must_halt() is True
    credentials.store_ap_psk("23456789ABCDEF")
    assert pairing.unclaimed_must_halt() is False


def test_unclaimed_does_not_halt_when_claimed_without_psk():
    credentials._write_to_nvs(
        {"device_id": "devABCDEF123456", "device_token": "tok", "wifi": {}}
    )
    assert pairing.unclaimed_must_halt() is False


def test_scan_table_rows_dedup_strongest():
    rows = pairing.scan_table_rows(
        [
            (b"Home", b"\x00", 0, -80, 4, False),
            (b"Home", b"\x00", 0, -40, 4, False),
            (b"Cafe", b"\x00", 0, -60, 4, False),
            (b"", b"\x00", 0, -30, 4, False),
        ]
    )
    assert rows[0]["ssid"] == "Home"
    assert rows[0]["rssi"] == -40
    assert rows[1]["ssid"] == "Cafe"


def test_parse_pair_form_scan_or_typed():
    code, wifi = parse_pair_form(
        {
            "pairing_code": "7k4m2q9h",
            "ssid": "Scanned",
            "ssid_typed": "HiddenNet",
            "password": "secret",
            "hidden": "1",
        }
    )
    assert code == "7K4M2Q9H"
    assert wifi["ssid"] == "HiddenNet"
    assert wifi["hidden"] is True


def test_parse_pair_form_accepts_hyphenated_display_code():
    code, wifi = parse_pair_form(
        {
            "pairing_code": "7K4M-2Q9H",
            "ssid": "Home",
            "password": "secret",
        }
    )
    assert code == "7K4M2Q9H"
    assert wifi["ssid"] == "Home"


def test_generate_pairing_html_matches_maintenance_portal():
    html = generate_pairing_html([{"ssid": "Home", "rssi": -40}])
    assert "<span class=\"brand\">FlipBuddy</span>" in html
    assert 'class="top-bar"' in html
    assert 'class="card"' in html
    assert 'class="form"' in html
    assert 'class="content"' in html
    assert "pairing_code" in html
    assert "Home" in html
    assert "Scan networks" in html
    assert "Hidden" in html
    assert "WPA2" in html
    assert "HTTP" in html
    assert "desk" in html.lower()
    assert "Join home Wi-Fi and pair" in html
    assert "background:#111827" in html
    assert "cafe" not in html.lower()
    assert 'placeholder="XXXX-XXXX"' in html
    assert "XXXX-XXXX" in html
    assert 'name="pairing_code"' in html
    assert "<script>" in html
    assert 'name="password"' in html
    assert 'id="pw"' in html
    assert "pw-toggle" in html
    assert 'type="button"' in html
    assert 'aria-label="Show password"' in html


def test_generate_pairing_html_flash_and_selected_ssid():
    ok = generate_pairing_html([], flash="ok: Scan complete")
    assert "flash-ok" in ok
    assert "Scan complete" in ok
    assert "ok: Scan" not in ok
    err = generate_pairing_html([], flash="Need the pairing code (XXXX-XXXX)")
    assert "flash-err" in err
    selected = generate_pairing_html(
        [{"ssid": "Home", "rssi": -40}], ssid_value="Home"
    )
    assert "selected" in selected


def test_parse_claim_response():
    parsed = pairing.parse_claim_response(
        '{"device_id":"u1","device_token":"t1","api_url":"https://api.flipbuddy.app/v1/api/"}'
    )
    assert parsed["device_id"] == "u1"
    assert parsed["device_token"] == "t1"
    assert parsed["api_url"] == "https://api.flipbuddy.app/v1/api/"
    evil = pairing.parse_claim_response(
        '{"device_id":"u1","device_token":"t1","api_url":"http://evil.example/v1/api/"}'
    )
    assert evil["api_url"] == pairing.DEFAULT_API
    other_https = pairing.parse_claim_response(
        '{"device_id":"u1","device_token":"t1","api_url":"https://x/v1/api/"}'
    )
    assert other_https["api_url"] == pairing.DEFAULT_API


def _load_gen_ap_psk():
    path = Path(__file__).resolve().parents[1] / "scripts" / "gen_ap_psk.py"
    spec = importlib.util.spec_from_file_location("gen_ap_psk", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_host_gen_ap_psk_is_8_alphabet_chars():
    mod = _load_gen_ap_psk()
    psk = mod.generate_ap_psk()
    assert len(psk) == 8
    assert all(c in credentials.AP_PSK_ALPHABET for c in psk)


def test_host_gen_ap_psk_quiet_banner_is_password_only():
    mod = _load_gen_ap_psk()
    text = mod.banner("A6XVQEQ8", quiet=True)
    assert "A6XV QEQ8" in text
    assert "Spaces are only for reading." in text
    full = mod.banner("A6XVQEQ8", quiet=False)
    assert "Next: just put-ap-psk" in full
    assert "credentials.json" not in full
    assert "gitignored" not in full


def _load_strip_credentials_wifi():
    path = Path(__file__).resolve().parents[1] / "scripts" / "strip_credentials_wifi.py"
    spec = importlib.util.spec_from_file_location("strip_credentials_wifi", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_strip_credentials_wifi_drops_house_keys(tmp_path):
    mod = _load_strip_credentials_wifi()
    src = tmp_path / "credentials.json"
    dst = tmp_path / "out.json"
    src.write_text(
        json.dumps(
            {
                "device_id": "devABCDEF123456",
                "device_token": "tok",
                "wifi": {"home": {"ssid": "MyNet", "password": "secret"}},
                "ssid": "MyNet",
                "password": "secret",
            }
        ),
        encoding="utf-8",
    )
    assert mod.main([str(src), str(dst)]) == 0
    out = json.loads(dst.read_text(encoding="utf-8"))
    assert out == {"device_id": "devABCDEF123456", "device_token": "tok"}


def test_host_gen_ap_psk_does_not_write_credentials_json(tmp_path):
    mod = _load_gen_ap_psk()
    cred = tmp_path / "credentials.json"
    cred.write_text('{"device_id": "devABCDEF123456"}\n', encoding="utf-8")
    before = cred.read_text(encoding="utf-8")
    mod.persist_ap_psk("23456789", root=tmp_path)
    data = json.loads((tmp_path / "ap_psk.json").read_text(encoding="utf-8"))
    assert data == {"ap_psk": "23456789"}
    assert cred.read_text(encoding="utf-8") == before
    assert "ap_psk" not in before


def test_host_ensure_ignores_plaintext_file(tmp_path, monkeypatch):
    mod = _load_gen_ap_psk()
    (tmp_path / "ap_psk.txt").write_text("23456789\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod, "generate_ap_psk", lambda length=16: "ABCDEFGH")
    assert mod.main(["--ensure", "--quiet"]) == 0
    assert json.loads((tmp_path / "ap_psk.json").read_text(encoding="utf-8")) == {
        "ap_psk": "ABCDEFGH"
    }


def test_ota_header_is_app_rejects_bootloader_and_merged():
    boot = bytes([0xE9, 0x03, 0x02, 0x2F]) + b"\x00" * 12
    app = bytes([0xE9, 0x07, 0x02, 0x2F]) + b"\x00" * 12
    assert pairing.ota_header_is_app(app) is True
    assert pairing.ota_header_is_app(boot) is False
    assert pairing.ota_header_is_app(b"\xff" * 16) is False
    assert pairing.ota_header_is_app(b"") is False
    assert pairing.ota_header_is_app(None) is False
    assert OTA_APP_MAX == 1769472
    assert 1817552 > OTA_APP_MAX
    assert 1752016 < OTA_APP_MAX


def test_host_ensure_reuses_existing_json(tmp_path, monkeypatch, capsys):
    mod = _load_gen_ap_psk()
    (tmp_path / "ap_psk.json").write_text(
        '{"ap_psk": "23456789"}\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    assert mod.main(["--ensure", "--quiet"]) == 0
    assert json.loads((tmp_path / "ap_psk.json").read_text(encoding="utf-8")) == {
        "ap_psk": "23456789"
    }
    out = capsys.readouterr().out
    assert "2345 6789" in out


def test_host_ensure_regenerates_wrong_length(tmp_path, monkeypatch, capsys):
    mod = _load_gen_ap_psk()
    (tmp_path / "ap_psk.json").write_text(
        '{"ap_psk": "9CD36BM9JCW7P7Y4"}\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod, "generate_ap_psk", lambda length=8: "ABCDEFGH")
    assert mod.main(["--ensure", "--quiet"]) == 0
    assert json.loads((tmp_path / "ap_psk.json").read_text(encoding="utf-8")) == {
        "ap_psk": "ABCDEFGH"
    }
    out = capsys.readouterr().out
    assert "ABCD EFGH" in out
    assert "9CD36BM9JCW7P7Y4" not in out


def test_identify_blink_once_on_boot_not_held_in_active():
    src = Path(__file__).resolve().parents[1].joinpath("main.py").read_text(encoding="utf-8")
    fetch = src.split("async def fetch_config", 1)[1].split("async def calibrate", 1)[0]
    assert "pairing_identify_blink_once" in fetch
    show = src.split("async def show_face_indicator", 1)[1].split("def _face_from_name", 1)[0]
    assert "IDENTIFY_GREEN" not in show
    assert "pairing_identify_blink_once" not in show
    helper = src.split("async def pairing_identify_blink_once", 1)[1].split("class BootFSM", 1)[0]
    assert "range(4)" not in helper
    assert 'set_all_pixels(np_obj, "#000000")' in helper


def test_set_all_pixels_green():
    class Fake:
        n = 6
        data = [(0, 0, 0)] * 6

        def __setitem__(self, i, v):
            self.data[i] = v

        def write(self):
            pass

    np = Fake()
    set_all_pixels(np, IDENTIFY_GREEN, intensity_level=50)
    assert all(p != (0, 0, 0) for p in np.data)
    assert all(p[1] > p[0] and p[1] > p[2] for p in np.data)


def test_pairing_portal_show_leds_all_six_yellow_then_shutdown_cuts_vcc():
    class Fake:
        n = 6
        data = [(0, 0, 0)] * 6

        def __setitem__(self, i, v):
            self.data[i] = v

        def __getitem__(self, i):
            return self.data[i]

        def write(self):
            pass

    np = Fake()
    vcc = MagicMock()
    fsm = PairingPortal()
    fsm.np_obj = np
    fsm.np_vcc = vcc
    fsm._show_leds()
    vcc.on.assert_called()
    assert all(p[0] > 0 and p[1] > 0 and p[2] == 0 for p in np.data)
    fsm.shutdown()
    vcc.off.assert_called()
