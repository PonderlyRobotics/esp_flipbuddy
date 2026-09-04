# FlipBuddy v0.2.2

Firmware **0.2.2** is the Super Mini freeze on the same claim-pairing and dual-OTA table as **v0.2.1**. Prefer this FlipBuddy binary over stock MicroPython so you get faster bring-up, a tested pairing stack, pin/product tunables in LittleFS `settings.py`, and over-the-air security and bugfix images from flipbuddy.app.

This is **not** a drop-in file replace on a **v0.1.x** cube. Tags **v0.1.0** through **v0.1.5** used a factory partition table (no `ota_1`) and JSON-first pairing. They do **not** work with the Production claim-pairing and dual-OTA path. USB-flash **`esp32_s3_flipbuddy_0.2.2-ota.bin`**, then pair again.

v0.2.0 / v0.2.1 cubes can USB-flash this image (NVS is wiped: pair again) or wait for an app-slot OTA from flipbuddy.app when that package is published. Fast-track on a **0.2.1** USB image is not enough for this release: keep-alive HTTP, the tracking-off LED cue, and the unclaimed portal sleep path live in frozen helpers (`http.py`, `rgb.py`, `pairing_portal.py`, `credentials.py`).

## Highlights vs v0.2.1

- **Pause tracking:** the app `active` flag (default on). When it is off, pickup shows a rapid **red** blink on the upward face (triad on a cutout), finalizes any open session, and does not start a new one. Motion wakes skip Wi-Fi. Timer, USB, and a pending log still check config. Sleep uses `upload_frequency`, not the short orientation interval.
- **Unclaimed pairing:** the SoftAP portal no longer retries forever. After timeout or failure with no code, the cube deep-sleeps until the MPU wakes it (no RTC timer). Pick it up to try again. Yellow LEDs are on while the pairing Wi-Fi is up (~10 min).
- **Dashboard live preview:** when the app is watching (`live_ok_until` in NVS, not in `Config` hash), a pickup wake joins Wi-Fi during the ~7 s assigned-face map and POSTs `sensor/live_event` on face changes. Super Mini often timer-wakes instead of GPIO; watched timer wakes still run preview (STA+TLS in settle, no map). Tracking-off still skips that radio. Unwatched timer wakes stay one sample.
- **HTTP/1.1 keep-alive:** one TLS socket per wake for config GET + log POST + preview. Preview POST writes fully, then reads (do not cancel mid-drain). 204 is success with an empty body. OTA still uses a close-after-use GET for large bodies. LEDs dim during STA/TLS TX.

## Breaking (read this if you have v0.1.x)

Same as v0.2.0 / v0.2.1. You **cannot** OTA from 0.1.5 onto 0.2.x. USB only. After a USB erase, skip **Forget FlipBuddy account**. **Add Device**.

## Upgrade

1. Download the two USB `.bin` files and checksums from this Release. Verify:

    ```bash
    sha256sum -c esp32_s3_flipbuddy_0.2.2-ota.bin.sha256
    ```

2. Flash the **OTA USB** image (merged table + app). This erases NVS.

    ```bash
    just flash-firmware esp32_s3_flipbuddy_0.2.2-ota.bin
    # or:
    esptool --chip esp32s3 --port /dev/ttyACM0 erase-flash
    esptool --chip esp32s3 --port /dev/ttyACM0 --baud 460800 write-flash 0 esp32_s3_flipbuddy_0.2.2-ota.bin
    ```

3. `just fast-track` (uploads `main.py` + `settings.py` + a SoftAP password, hard reset). Write down the password.

4. [flipbuddy.app](https://flipbuddy.app) → **Add Device** → physical cube → 8-character code.

5. Keep USB plugged in. Join **`FlipBuddy-XXXX`**, open http://10.20.30.40/, house Wi-Fi + pairing code. Cube blinks green. Confirm in the app.

Factory / recovery USB image (no self-OTA): `esp32_s3_flipbuddy_0.2.2.bin`. Prefer `*-ota.bin` on Super Mini.

App-slot OTA packages are served by flipbuddy.app. They are **not** attached to this GitHub Release.

## Files on this Release

| File | Purpose |
|------|---------|
| `esp32_s3_flipbuddy_0.2.2-ota.bin` | **Flash this.** Merged USB image with dual-OTA table. |
| `esp32_s3_flipbuddy_0.2.2.bin` | Factory-table USB image (recovery; no `ota_1`). |
| `*.bin.sha256` / `SHA256SUMS` | Checksums |

Expected SHA-256:

```
889b869b90152a94e0c5e97b72fecbe82c5faedc2318e5f3a924c59a967349af  esp32_s3_flipbuddy_0.2.2.bin
f9ebf30dfac721985a0f3ca9b4335b81e52ffdfd8d66e31ed77d5e7ab152a9c2  esp32_s3_flipbuddy_0.2.2-ota.bin
```

```bash
sha256sum -c SHA256SUMS
```

## Partition table (4 MB Super Mini)

`nvs` 16 KB at `0x9000` (config, credentials, tracker; about 45-70 closed sessions offline). `ota_0` / `ota_1` 1.75 MB. LittleFS `0x70000` (448 KB) for `main.py` + `settings.py` + `ap_psk`. CSV: [partitions/partitions-4MiB-ota-flipbuddy.csv](../partitions/partitions-4MiB-ota-flipbuddy.csv).

## Links

- App: https://flipbuddy.app
- Changelog: [CHANGELOG.md](./CHANGELOG.md)
- README (flash + pair): [../README.md](../README.md)
- Prior notes: [v0.2.1](./RELEASE_NOTES_v0.2.1.md)
