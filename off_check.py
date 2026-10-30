"""Tracking-off sleep.

A check interval is used only when it is 300, 1800, or 7200.
Anything else uses the upload interval, then 300.
Motion does not restart a deadline that already started.
MPU deep-sleep motion bytes stay threshold 2 and sample_rate_div 16.
"""

ALLOWED_CHECK_S = (300, 1800, 7200)
MPU_USUAL_THRESHOLD = 2
MPU_USUAL_DIV = 16


def coerce_check_s(raw, upload_s, default_s=300):
    if type(raw) is int and raw in ALLOWED_CHECK_S:
        return raw
    try:
        upload = int(upload_s)
    except (TypeError, ValueError):
        return default_s
    if upload <= 0:
        return default_s
    return upload


def sleep_seconds(interval_s, elapsed_s, motion):
    """Seconds until the next deep sleep ends.

    ``elapsed_s`` is seconds since the last config GET, or None when that
    GET has never happened. Motion keeps the remaining time (at least 1s).
    A timer wake, or the first sleep, uses the full interval.
    """
    interval = interval_s if interval_s and interval_s > 0 else 300
    if not motion or elapsed_s is None:
        return interval
    remain = int(interval - elapsed_s)
    if remain > 1:
        return remain
    return 1


def mpu_motion(_level):
    return MPU_USUAL_THRESHOLD, MPU_USUAL_DIV
