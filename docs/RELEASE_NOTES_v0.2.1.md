# FlipBuddy v0.2.1

Firmware **0.2.1** is the Super Mini freeze with a LittleFS **`settings.py`** overlay. Claim pairing and the dual-OTA table are the same as **v0.2.0**. Prefer this FlipBuddy binary over stock MicroPython so you get faster bring-up, a tested pairing stack, pin/product tunables you can edit without rebuilding MicroPython, and over-the-air security and bugfix images from flipbuddy.app.

This is **not** a drop-in file replace on a **v0.1.x** cube. Tags **v0.1.0** through **v0.1.5** used a factory partition table (no `ota_1`) and JSON-first pairing. They do **not** work with the Production claim-pairing and dual-OTA path. USB-flash **`esp32_s3_flipbuddy_0.2.1-ota.bin`**, then pair again.

v0.2.0 cubes can USB-flash this image (NVS is wiped: pair again) or wait for an app-slot OTA from flipbuddy.app when that package is published.

## Highlights vs v0.2.0

- **LittleFS overlay:** Super Mini GPIO and product tunables live in `settings.py` on the filesystem. Frozen helpers stay in the image. `just fast-track` / `just put-main` copy `main.py` **and** `settings.py`, plus a host SoftAP password. Do not skip `settings.py` on a manual `mpremote` copy.
- **Face names:** DIN 0..5 is front, bottom, back, left, top, right. `front_cutout` is the USB-C port and stop (top/front/right). `back_cutout` is SoftAP; yellow triad stays left/back/bottom. The overlay patches frozen `rgb` / `mpu6050` so you do not need a new freeze to pick this up.
- **LED rail:** unclaimed pairing brings the rail up once in the portal (`configure_board_hw`). Claimed boot does the same before constructing the NeoPixel strip.
- **Still claim pairing + dual-OTA:** Add Device, join **`FlipBuddy-XXXX`**, type house Wi-Fi plus the 8-character code. USB image is `*-ota.bin`. App-slot packages stay on flipbuddy.app.

## Breaking (read this if you have v0.1.x)

Same as v0.2.0. You **cannot** OTA from 0.1.5 onto 0.2.x. USB only. After a USB erase, skip **Forget FlipBuddy account**. **Add Device**.

## Upgrade

1. Download the two USB `.bin` files and checksums from this Release. Verify:

    ```bash
    sha256sum -c esp32_s3_flipbuddy_0.2.1-ota.bin.sha256
    ```

2. Flash the **OTA USB** image (merged table + app). This erases NVS.

    ```bash
    just flash-firmware esp32_s3_flipbuddy_0.2.1-ota.bin
    # or:
    esptool --chip esp32s3 --port /dev/ttyACM0 erase-flash
    esptool --chip esp32s3 --port /dev/ttyACM0 --baud 460800 write-flash 0 esp32_s3_flipbuddy_0.2.1-ota.bin
    ```

3. `just fast-track` (uploads `main.py` + `settings.py` + a SoftAP password, hard reset). Write down the password.

4. [flipbuddy.app](https://flipbuddy.app) → **Add Device** → physical cube → 8-character code.

5. Keep USB plugged in. Join **`FlipBuddy-XXXX`**, open http://10.20.30.40/, house Wi-Fi + pairing code. Cube blinks green. Confirm in the app.

Factory / recovery USB image (no self-OTA): `esp32_s3_flipbuddy_0.2.1.bin`. Prefer `*-ota.bin` on Super Mini.

App-slot OTA packages are served by flipbuddy.app. They are **not** attached to this GitHub Release.

## Files on this Release

| File | Purpose |
|------|---------|
| `esp32_s3_flipbuddy_0.2.1-ota.bin` | **Flash this.** Merged USB image with dual-OTA table. |
| `esp32_s3_flipbuddy_0.2.1.bin` | Factory-table USB image (recovery; no `ota_1`). |
| `*.bin.sha256` / `SHA256SUMS` | Checksums |

Expected SHA-256:

```
3026b63a61414ef56c57b50450e9cf6e8228937d2ad9a416fbd9e9f45d5fb06f  esp32_s3_flipbuddy_0.2.1.bin
43694c8659ef76a821913fd3b3501375b64e73f52266092f8ef72778200c9240  esp32_s3_flipbuddy_0.2.1-ota.bin
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
- Prior notes: [v0.2.0](./RELEASE_NOTES_v0.2.0.md)
