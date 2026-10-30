"""Host tests for tracking-off sleep. No sensor hardware."""

import off_check


def test_absent_interval_follows_upload_then_default():
    assert off_check.coerce_check_s(None, 120) == 120
    assert off_check.coerce_check_s(None, 900) == 900
    assert off_check.coerce_check_s(None, None) == 300
    assert off_check.coerce_check_s("1800", 300) == 300
    assert off_check.coerce_check_s(0, 300) == 300
    assert off_check.coerce_check_s(True, 300) == 300


def test_present_interval_overrides_upload():
    assert off_check.coerce_check_s(300, 120) == 300
    assert off_check.coerce_check_s(1800, 300) == 1800
    assert off_check.coerce_check_s(7200, 900) == 7200


def test_motion_does_not_restart_the_deadline():
    assert off_check.sleep_seconds(7200, 100, True) == 7100
    assert off_check.sleep_seconds(300, 299, True) == 1
    assert off_check.sleep_seconds(300, None, True) == 300
    assert off_check.sleep_seconds(1800, 100, False) == 1800


def test_mpu_wake_bytes_stay_usual():
    assert off_check.mpu_motion(None) == (2, 16)
    assert off_check.mpu_motion("firm") == (2, 16)
