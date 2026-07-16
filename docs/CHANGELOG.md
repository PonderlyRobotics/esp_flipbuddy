# Changelog

Versions follow `pyproject.toml` and the GitHub Release tags. Firmware and enclosure for this release are both **0.1.0**.

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
