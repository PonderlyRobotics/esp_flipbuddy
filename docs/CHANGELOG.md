# Changelog

Versions follow `pyproject.toml` and the GitHub Release tags (firmware / source tree).

## 0.1.1 (2026-07-22)

SoftAP maintenance mode and related host tooling:

- SoftAP captive portal on USB‑C face: status (UTC time, battery), PIN unlock, Wi‑Fi profiles, change PIN, LED self‑test, ungated device reset
- Early SoftAP gate + `ap_session` clean‑heap path (soft_reset handoff); lazy STA / SoftAP radio helpers
- Host tests under `tests/` (PIN, Wi‑Fi NVS, portal HTML helpers, handoff marks); CI runs `pytest tests/`
- README SoftAP builder steps, clock/Wi‑Fi FAQs; SECURITY SoftAP risks (cleartext HTTP, multi‑client unlock, factory PIN)
- Factory setup PIN = last 6 alphanumeric of `device_id`; optional custom PIN in NVS

Fast track: flash `esp32_s3_flipbuddy_0.1.1.bin` (when published on GitHub Releases), then place `main.py` + credentials. DIY / `just diy` still works with stock MicroPython + full sources.

## 0.1.0 (2026-07-16)

First public DIY release under Ponderly Robotics.

What is in the box, so to speak:

- MicroPython sources (Boot, Active, and Upload FSMs)
- Assembly PDF and STLs for enclosure v0.1.0
- Photos, wiring schematic, and dashboard screenshot in `docs/media/`
- MIT for software, CC BY-NC-SA 4.0 for hardware; frozen images also carry third-party code (see [NOTICE](./NOTICE))
- [SECURITY.md](../SECURITY.md)
- Fast track: frozen ESP32-S3 image on GitHub Releases (MicroPython 1.27); only `main.py` and `credentials.json` on the filesystem
- DIY path: stock MicroPython plus full source upload
- Continues offline if Wi-Fi is missing once credentials are installed
- Token rotate keeps Wi-Fi settings and updates the headers still in memory
- Host tools: `just`, tests, pre-commit, release-check, CI
- Aimed at ESP32-S3 Super Mini boards with a charger; full BOM is in the assembly PDF
