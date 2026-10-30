# Frozen boot hook. Runs before filesystem main.py. Return normally.
# This generation does not replace main.py. SoftAP (RTC FBAP1) returns first.

_AP_BOOT_MARK = b"FBAP1"


def _softap_handoff():
    try:
        from machine import RTC

        mem = RTC().memory()
    except Exception:
        return False
    return bool(mem) and len(mem) >= 5 and mem[:5] == _AP_BOOT_MARK


def _confirm_slot():
    try:
        import esp32

        esp32.Partition.mark_app_valid_cancel_rollback()
    except Exception:
        return


if not _softap_handoff():
    _confirm_slot()
