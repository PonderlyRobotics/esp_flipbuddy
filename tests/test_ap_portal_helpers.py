"""Host tests for SoftAP portal helpers (ap_mode display/formatting)."""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

# conftest installs MicroPython shims before collection
import ap_mode


def test_esc_html():
    assert ap_mode._esc("<tag>") == "&lt;tag&gt;"
    assert ap_mode._esc('a"b') == "a&quot;b"
    assert ap_mode._esc(None) == ""


def test_clip_ellipsis():
    assert ap_mode._clip("short", 24) == "short"
    clipped = ap_mode._clip("abcdefghijklmnop", 8)
    assert clipped.endswith("…")
    assert len(clipped) == 8


def test_fmt_iso():
    assert ap_mode._fmt_iso("2026-07-21T15:39:24Z") == "2026-07-21 15:39:24"
    assert ap_mode._fmt_iso("2026-07-21T15:39:24") == "2026-07-21 15:39:24"


def test_faces_html_fixed_cards_and_clip():
    tracker = SimpleNamespace(running={"tracking_log": {}})
    long_name = "Very Long Activity Name That Should Clip"
    for face in ("front", "back", "left", "right", "top", "bottom"):
        setattr(
            tracker,
            face,
            SimpleNamespace(led_color="#abcdef", activity_name=long_name),
        )
    fsm = ap_mode.ApModeFSM(config=MagicMock(), tracker=tracker)
    html = fsm._faces_html()
    assert html.count('class="face"') == 6
    assert "face-orient" in html
    assert "face-act" in html
    assert "…" in html or "&" in html  # clipped label present
    assert long_name in html  # full text remains in title attribute


def test_tracking_log_html_table():
    tracker = SimpleNamespace(
        running={
            "tracking_log": {
                "front": [
                    "front,act-hobby,2026-07-21T10:00:00Z,2026-07-21T10:05:30Z",
                ],
                "back": [],
            }
        }
    )
    for face in ("front", "back", "left", "right", "top", "bottom"):
        if not hasattr(tracker, face):
            setattr(
                tracker,
                face,
                SimpleNamespace(led_color="#fff", activity_name=face),
            )
    fsm = ap_mode.ApModeFSM(config=MagicMock(), tracker=tracker)
    html = fsm._tracking_log_html()
    assert "log-table" in html
    assert "front" in html
    assert "act-hobby" in html
    assert "2026-07-21 10:00:00" in html
    assert "Duration" in html


def test_tracking_log_empty():
    tracker = SimpleNamespace(running={"tracking_log": {}})
    for face in ("front", "back", "left", "right", "top", "bottom"):
        setattr(tracker, face, SimpleNamespace(led_color="#fff", activity_name="x"))
    fsm = ap_mode.ApModeFSM(config=MagicMock(), tracker=tracker)
    html = fsm._tracking_log_html()
    assert "No finished sessions" in html
    assert 'class="muted"' in html
    assert "<class" not in html
    assert "&lt;p" not in html


def test_generate_html_empty_logs_renders_as_html_not_type_repr():
    """Regression: empty records must not look like <class 'muted'> raw text."""
    tracker = SimpleNamespace(running={"tracking_log": {}})
    for face in ("front", "back", "left", "right", "top", "bottom"):
        setattr(tracker, face, SimpleNamespace(led_color="#abcdef", activity_name="x"))
    fsm = ap_mode.ApModeFSM(config=MagicMock(), tracker=tracker)
    fsm._device_datetime_label = lambda: "2026-07-21 12:00:00 UTC"
    # Battery label with literal % must not break page assembly
    fsm._battery_status = lambda: {
        "label": "USB · 5.00 V · 100%",
        "percent": 100,
        "usb": True,
    }
    fsm.is_unlocked = lambda: False
    page = fsm.generate_html()
    assert "Activity records" in page
    assert "No finished sessions stored yet" in page
    assert 'class="muted"' in page
    assert "<class" not in page
    assert "100%" in page  # battery percent preserved
    assert "Content-Type" not in page  # body only


def test_tracking_log_skips_non_string_entries():
    tracker = SimpleNamespace(
        running={"tracking_log": {"front": [object(), "", "front,a,2026-07-21T10:00:00Z,2026-07-21T10:01:00Z"]}}
    )
    for face in ("front", "back", "left", "right", "top", "bottom"):
        if not hasattr(tracker, face):
            setattr(tracker, face, SimpleNamespace(led_color="#fff", activity_name=face))
    fsm = ap_mode.ApModeFSM(config=MagicMock(), tracker=tracker)
    html = fsm._tracking_log_html()
    assert "log-table" in html
    assert "<class" not in html
    assert "front" in html


def test_unlock_pin_and_change():
    import credentials

    # Seed NVS credentials
    credentials._write_to_nvs(
        {"device_id": "devABCDEF123456", "device_token": "tok", "wifi": {}}
    )
    tracker = SimpleNamespace(running={"tracking_log": {}})
    for face in ("front", "back", "left", "right", "top", "bottom"):
        setattr(tracker, face, SimpleNamespace(led_color="#fff", activity_name="x"))
    fsm = ap_mode.ApModeFSM(config=MagicMock(), tracker=tracker)
    factory = credentials.default_ap_unlock_pin("devABCDEF123456")
    assert factory == "123456"
    ok, msg = fsm.try_unlock(factory)
    assert ok is True
    assert fsm.is_unlocked() is True
    ok, msg = fsm.change_pin("secret1", "secret1")
    assert ok is True
    fsm.lock()
    assert fsm.is_unlocked() is False
    ok, _ = fsm.try_unlock(factory)
    assert ok is False
    ok, _ = fsm.try_unlock("secret1")
    assert ok is True


def test_reset_path_not_gated_by_helpers():
    # Reset is handled in HTTP layer without unlock; document intent via unlock state
    tracker = SimpleNamespace(running={"tracking_log": {}})
    for face in ("front", "back", "left", "right", "top", "bottom"):
        setattr(tracker, face, SimpleNamespace(led_color="#fff", activity_name="x"))
    fsm = ap_mode.ApModeFSM(config=MagicMock(), tracker=tracker)
    assert fsm.is_unlocked() is False
    # No exception when locked - unlock is independent of reset policy
    fsm.lock()


def test_flash_ok_vs_err_css_classes():
    tracker = SimpleNamespace(running={"tracking_log": {}})
    for face in ("front", "back", "left", "right", "top", "bottom"):
        setattr(tracker, face, SimpleNamespace(led_color="#fff", activity_name="x"))
    fsm = ap_mode.ApModeFSM(config=MagicMock(), tracker=tracker)
    fsm._device_datetime_label = lambda: "2026-07-21 12:00:00 UTC"
    fsm._battery_status = lambda: {"label": "USB · 5.00 V · 100%", "percent": 100, "usb": True}
    fsm.is_unlocked = lambda: False

    fsm._set_flash("Unlocked", ok=True)
    page_ok = fsm.generate_html()
    assert "flash-ok" in page_ok
    assert "Unlocked" in page_ok

    fsm._set_flash("Wrong PIN (1/8)", ok=False)
    page_err = fsm.generate_html()
    assert "flash-err" in page_err
    assert "Wrong PIN" in page_err


def test_pin_lockout_mentions_reset():
    tracker = SimpleNamespace(running={"tracking_log": {}})
    for face in ("front", "back", "left", "right", "top", "bottom"):
        setattr(tracker, face, SimpleNamespace(led_color="#fff", activity_name="x"))
    fsm = ap_mode.ApModeFSM(config=MagicMock(), tracker=tracker)
    fsm._pin_attempts = ap_mode._MAX_PIN_ATTEMPTS
    ok, msg = fsm.try_unlock("nope")
    assert ok is False
    assert "Reset" in msg
