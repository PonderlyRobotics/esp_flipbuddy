# Changelog

Versions follow `pyproject.toml` and the GitHub Release tags (firmware / source tree).

## 0.1.5 (2026-08-29)

Firmware **0.1.5** on **MicroPython 1.28**. Super Mini hardware is still MPU6050 + ADC.

- **Last-AP fast reconnect:** remember the last successful STA AP (NVS `lastap`); skip the extra scan; fail-fast when the AP is gone; no 2 s post-IP sleep
- **SoftAP WPA2-PSK:** join password `FB` + last 6 alnum of `device_id`; portal remains `http://10.20.30.40/`
- **SoftAP USB-face LEDs:** solid yellow (`#FFFF00`) on the back-cutout triad (left / back / bottom)
- **Cutout triad:** `front_cutout` is right/top/front; `back_cutout` is left/back/bottom (physical corners; 0.1.3 map was swapped)
- **Live face preview:** after the 7 s assigned-face map, MPU6050 5 Hz preview until **10 s still** (wall-clock), then the usual tracking blink, then upload if needed and/or deep sleep
- **Pickup blink:** after the assigned-face map and 10 s still, the cube does the usual tracking blink (not only on the next wake)
- **Frozen 1.28 image:** includes `ap_session` and the current helpers (IDF 5.5.1)

Frozen Release image: `esp32_s3_flipbuddy_0.1.5.bin`. Full reflash recommended. See [RELEASE_NOTES_v0.1.5.md](./RELEASE_NOTES_v0.1.5.md).

## 0.1.4 (2026-08-08)

Maintenance release with internal firmware optimizations for memory and stability.

- **Memory Optimization:** Reduced initial RAM usage by ~11.6 KB through `const()` declarations and static FSM state strings, lowering heap fragmentation.
- **Session Durability:** Open tracking sessions are now reconciled after a reboot, preventing data loss.
- **NVS Hygiene:** Ephemeral data is no longer saved to non-volatile storage, reducing flash writes.

Frozen Release image: `esp32_s3_flipbuddy_0.1.4.bin`. Full reflash recommended. See [RELEASE_NOTES_v0.1.4.md](./RELEASE_NOTES_v0.1.4.md).

## 0.1.3 (2026-07-31)

Cutout triad LED fix (prefer this over 0.1.2 for new flashes):

- Swap `triad_led` mappings so after the 0.1.2 pinout rename, `front_cutout` lights bottom/left/back and `back_cutout` lights top/right/front
- Flat-face gravity remap and pinout labels unchanged from 0.1.2

Frozen Release image: `esp32_s3_flipbuddy_0.1.3.bin`. Full reflash required (frozen `rgb.py`). See [RELEASE_NOTES_v0.1.3.md](./RELEASE_NOTES_v0.1.3.md).

## 0.1.2 (2026-07-31)

Face orientation aligned to the physical LED chain and enclosure:

- Remap NeoPixel face labels in `rgb.py` pinout (DIN 0…5): back→front, left→bottom, front→back, bottom→left, right→top, top→right
- Same rename in `cube_face_upward()` gravity returns so upward face, LED, and tracker name agree
- Cutout triad tuples were updated with the rename but **swapped** relative to front/back cutout — fixed in **0.1.3**
- CI: GitHub Actions `checkout` and `setup-python` majors that run on Node 24

Frozen Release image: `esp32_s3_flipbuddy_0.1.2.bin` (known cutout triad bug). Prefer **0.1.3**. See [RELEASE_NOTES_v0.1.2.md](./RELEASE_NOTES_v0.1.2.md).

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
