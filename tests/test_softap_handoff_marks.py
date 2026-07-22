"""SoftAP RTC handoff mark protocol (kept free of full main.py import)."""

# These must stay in sync with main.py early SoftAP gate
_AP_BOOT_MARK = b"FBAP1"
_AP_DONE_MARK = b"APDON"


def test_ap_mark_lengths_and_values():
    assert _AP_BOOT_MARK == b"FBAP1"
    assert _AP_DONE_MARK == b"APDON"
    assert len(_AP_BOOT_MARK) == 5
    assert len(_AP_DONE_MARK) == 5
    assert _AP_BOOT_MARK != _AP_DONE_MARK


def test_ap_cooldown_protocol():
    store = {"m": b""}

    def memory(data=None):
        if data is None:
            return store["m"]
        store["m"] = data

    def is_ap_cooldown():
        mem = memory()
        return bool(mem and mem[:5] == _AP_DONE_MARK)

    def set_ap_cooldown():
        memory(_AP_DONE_MARK)

    def clear_ap_cooldown():
        mem = memory()
        if mem and mem[:5] in (_AP_DONE_MARK, _AP_BOOT_MARK):
            memory(b"0,18")

    def early_gate_should_run(mem, reset_cause, soft_reset=5):
        """Mirror main._early_softap_gate decision (no SoftAP on stale power-on mark)."""
        if not mem or len(mem) < 5 or mem[:5] != _AP_BOOT_MARK:
            return False
        return reset_cause == soft_reset

    assert is_ap_cooldown() is False
    memory(_AP_BOOT_MARK)
    assert early_gate_should_run(memory(), reset_cause=5) is True
    assert early_gate_should_run(memory(), reset_cause=0) is False  # power-on stale
    set_ap_cooldown()
    assert is_ap_cooldown() is True
    assert early_gate_should_run(memory(), reset_cause=5) is False  # APDON not FBAP1
    clear_ap_cooldown()
    assert is_ap_cooldown() is False


def test_empty_scan_falls_back_to_all_configs():
    """Regression: empty WiFi scan must not skip all SSIDs (blocks NTP/upload)."""
    import network_helper as nh

    configs = [
        {"ssid": "HomeNet", "password": "secret"},
        {"ssid": "HiddenNet", "password": "x", "hidden": True},
    ]
    # Empty scan previously yielded zero candidates → no WiFi forever
    assert nh._configs_to_try(configs, set()) == configs
    # Real scan miss still skips non-hidden
    only_hidden = nh._configs_to_try(configs, {"OtherSSID"})
    assert only_hidden == [configs[1]]
