"""Host tests for pairing helpers (v0.2.0)."""

import importlib.util
import json
from pathlib import Path

import credentials
import pairing
from pairing_portal import generate_pairing_html, parse_pair_form
from rgb import IDENTIFY_GREEN, set_all_pixels


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
        '{"device_id":"u1","device_token":"t1","api_url":"https://x/v1/api/"}'
    )
    assert parsed["device_id"] == "u1"
    assert parsed["device_token"] == "t1"


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
    assert text == "SoftAP join password:\n  A6XVQEQ8"
    full = mod.banner("A6XVQEQ8", quiet=False)
    assert "Next: just put-ap-psk" in full
    assert "credentials.json" not in full
    assert "gitignored" not in full


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
    monkeypatch.setattr(mod, "generate_ap_psk", lambda: "ABCDEFGH")
    assert mod.main(["--ensure", "--quiet"]) == 0
    assert json.loads((tmp_path / "ap_psk.json").read_text(encoding="utf-8")) == {
        "ap_psk": "ABCDEFGH"
    }


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
    assert "23456789" in out


def test_set_all_pixels_green():
    class Fake:
        n = 6
        data = [(0, 0, 0)] * 6

        def __setitem__(self, i, v):
            self.data[i] = v

        def write(self):
            pass

    np = Fake()
    set_all_pixels(np, IDENTIFY_GREEN)
    assert all(p != (0, 0, 0) for p in np.data)
