# Changelog

Versions follow `pyproject.toml` and the GitHub Release tags (firmware / source tree).

## 0.2.1 (2026-09-02)

LittleFS **`settings.py`** overlay on the Super Mini freeze. Same claim pairing + dual-OTA table as **0.2.0**. Flash **`esp32_s3_flipbuddy_0.2.1-ota.bin`**. See [RELEASE_NOTES_v0.2.1.md](./RELEASE_NOTES_v0.2.1.md).

- Super Mini GPIO and product tunables live in `settings.py` on the filesystem (not frozen). `just fast-track` / `just put-main` copy `main.py` + `settings.py` + a host SoftAP password
- Unclaimed pairing brings the LED rail up once in the portal (`configure_board_hw`); claimed boot does it before the NeoPixel strip
- Host tests cover the overlay pin map and LittleFS vs freeze lists

Frozen GitHub Release images: `esp32_s3_flipbuddy_0.2.1-ota.bin` (preferred USB), `esp32_s3_flipbuddy_0.2.1.bin` (factory table). App-slot OTA files stay on flipbuddy.app; they are not GitHub assets.

## 0.2.0 (2026-09-01)

Firmware **0.2.0** frozen Super Mini image (`pairing.FIRMWARE_VERSION`). **Breaking** vs every **v0.1.x** tag. Flash **`esp32_s3_flipbuddy_0.2.0-ota.bin`**. Tags **v0.1.0**–**v0.1.5** do not work with Production claim pairing or dual-OTA; they stay on GitHub as history only. See [RELEASE_NOTES_v0.2.0.md](./RELEASE_NOTES_v0.2.0.md). LittleFS at this tag: `main.py` + `ap_psk.json`. The pin overlay `settings.py` ships in **0.2.1**.

Breaking:

- Pairing JSON is not the first setup step. `just fast-track` uploads `main.py` plus a host SoftAP password (`ap_psk`). Dashboard `credentials.json` is recovery only (`just put-credentials`).
- Unclaimed SoftAP SSID is **`FlipBuddy-XXXX`** (last 4 of chip id), not always `FlipBuddy`.
- Dual-OTA 4 MB table (`ota_0` / `ota_1`). v0.1.5 factory images have no `ota_1`; you cannot self-update 0.1.5 to 0.2.0.
- Full USB `erase-flash` of the OTA USB image wipes NVS. Pair again with Add Device. Skip Forget after a reflash.

Also:

- Frozen pairing portal (`pairing.py` / `pairing_portal.py`) in the image; fast track only places `main.py` + `ap_psk.json`
- Unclaimed pairing SoftAP: all six LEDs solid yellow (`SOFTAP_LED_COLOR`); claimed USB-face SoftAP stays the yellow triad
- Confirm-timeout 401/403 on GET config or sensor POST: clear NVS `pairing_identify` so USB-face SoftAP / PIN Forget works without erase-flash (token kept)
- OTA: skip unless `settings.ota_enabled`; skip if `ota_address` is missing (do not claim success); HTTPS host allowlist only (`api.flipbuddy.app`, `raw.githubusercontent.com`); refuse merged USB / oversize / bootloader-header files; solid white LEDs during download; frozen pairing stack is not mip-updated
- House Wi-Fi never copied from recovery JSON and never posted on claim
- NVS stays 16 KB (about 45-70 closed sessions offline). OTA slot padding is unused flash, not a session store.

Frozen GitHub Release images: `esp32_s3_flipbuddy_0.2.0-ota.bin` (preferred USB), `esp32_s3_flipbuddy_0.2.0.bin` (factory table). App-slot OTA files stay on flipbuddy.app; they are not GitHub assets. Prefer the FlipBuddy freeze over stock MicroPython.

## 0.1.5 (2026-08-29)

**Superseded.** This factory-table image does **not** work with Production claim pairing or dual-OTA. New Super Mini flashes: **0.2.1**.

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
