# FlipBuddy v0.2.0

Firmware **0.2.0** is a **breaking** Super Mini freeze: **claim pairing** plus an **OTA-enabled** frozen image. Prefer this FlipBuddy binary over stock MicroPython so you get faster bring-up, a tested pairing stack, and over-the-air security and bugfix images from flipbuddy.app.

This is **not** a drop-in file replace on a **v0.1.x** cube. Tags **v0.1.0** through **v0.1.5** used a factory partition table (no `ota_1`) and JSON-first pairing. They do **not** work with the Production claim-pairing and dual-OTA path. USB-flash **`esp32_s3_flipbuddy_0.2.0-ota.bin`**, then pair again.

## Highlights vs v0.1.5

- **Claim pairing:** Add Device in the free app, join cube Wi-Fi **`FlipBuddy-XXXX`**, type house Wi-Fi plus the 8-character code. `credentials.json` is recovery only (`just put-credentials`). `just fast-track` never copies that file.
- **Host SoftAP password:** `just gen-ap-psk` / `just fast-track` writes `ap_psk.json`. The image will not invent a join password. Serial prints it as `XXXX XXXX` (type without the space).
- **Dual-OTA frozen image:** 4 MB table with `ota_0` / `ota_1` (1.75 MB each) plus a 448 KB filesystem. After one USB flash of `*-ota.bin`, later app-slot updates can ride HTTPS from flipbuddy.app.
- **OTA safety:** after the dual-OTA USB flash, later updates come from **flipbuddy.app** (app-slot package). Merged USB dumps (`write-flash 0`) are refused if someone tries to OTA them (`ESP_ERR_OTA_VALIDATE_FAILED` / size / bootloader header). All six LEDs stay **solid white** while the download runs. The app-slot blob is **not** a GitHub Release asset (USB-flashing it bricks the boot path).
- **House Wi-Fi stays on the cube.** The claim body never includes SSID/password. Recovery JSON is identity only.
- **Still MicroPython 1.28**, MPU6050 + ADC Super Mini hardware, WPA2 SoftAP, last-AP reconnect, USB-face yellow SoftAP LEDs, live face preview.
- **Pairing portal LEDs:** unclaimed cube Wi-Fi lights **all six** faces solid yellow. After claim, USB-face maintenance still uses the yellow triad; confirm still blinks green.

## Why not stock MicroPython

Stock `ESP32_GENERIC_S3` from micropython.org has **no** `ota_1` slot and no frozen FlipBuddy helpers. You copy every `.py` with `just diy`, and you apply updates with USB. The FlipBuddy freeze is the path I test for pairing, security, and bugfix binaries.

## Breaking (read this if you have v0.1.x)

| v0.1.0 … v0.1.5 | v0.2.0 |
|--|--|
| First setup: `main.py` + `credentials.json` | First setup: `just fast-track`, then Add Device + cube Wi-Fi |
| SoftAP SSID often `FlipBuddy` | Unclaimed: `FlipBuddy-XXXX` (last 4 of chip id) |
| Factory table, no self-OTA | Dual-OTA table; self-write app-slot only |
| Token / Wi-Fi often survived a `main.py` copy | Full `erase-flash` of `*-ota.bin` wipes NVS; pair again |
| Works with the old JSON claim path | **Does not** complete Production claim pairing / OTA |

You **cannot** OTA from 0.1.5 onto 0.2.0. There is no second app slot, and the table is different. USB only.

After a USB erase, skip **Forget FlipBuddy account**. The cube is already unclaimed. **Add Device**.

## Upgrade from v0.1.5

1. Download the two USB `.bin` files and checksums from this Release. Verify:

    ```bash
    sha256sum -c esp32_s3_flipbuddy_0.2.0-ota.bin.sha256
    ```

2. Flash the **OTA USB** image (merged table + app). This erases NVS.

    ```bash
    just flash-firmware esp32_s3_flipbuddy_0.2.0-ota.bin
    # or:
    esptool --chip esp32s3 --port /dev/ttyACM0 erase-flash
    esptool --chip esp32s3 --port /dev/ttyACM0 --baud 460800 write-flash 0 esp32_s3_flipbuddy_0.2.0-ota.bin
    ```

3. `just fast-track` (uploads `main.py` + a SoftAP password, hard reset). Write down the password.

4. [flipbuddy.app](https://flipbuddy.app) → **Add Device** → physical cube → 8-character code.

5. Keep USB plugged in. Join **`FlipBuddy-XXXX`**, open http://10.20.30.40/, house Wi-Fi + pairing code. Cube blinks green. Confirm in the app.

Factory / recovery USB image (no self-OTA): `esp32_s3_flipbuddy_0.2.0.bin`. Prefer `*-ota.bin` on Super Mini.

App-slot OTA packages are served by flipbuddy.app. They are **not** attached to this GitHub Release.

## Files on this Release

| File | Purpose |
|------|---------|
| `esp32_s3_flipbuddy_0.2.0-ota.bin` | **Flash this.** Merged USB image with dual-OTA table. |
| `esp32_s3_flipbuddy_0.2.0.bin` | Factory-table USB image (recovery; no `ota_1`). |
| `*.bin.sha256` / `SHA256SUMS` | Checksums |

Expected SHA-256:

```
c435d9dc351eb517a9c3d4ee7d7ef0319dd72ebdf9a447f27451e5158664588a  esp32_s3_flipbuddy_0.2.0.bin
4106bdc3eeafc760db0fee42f84ba1ac3deddf56cb374a6c9db5243da7ec9623  esp32_s3_flipbuddy_0.2.0-ota.bin
```

```bash
sha256sum -c SHA256SUMS
```

## Partition table (4 MB Super Mini)

`nvs` 16 KB at `0x9000` (config, credentials, tracker; about 45-70 closed sessions offline). `ota_0` / `ota_1` 1.75 MB. LittleFS `0x70000` (448 KB) for `main.py` + `ap_psk`. CSV: [partitions/partitions-4MiB-ota-flipbuddy.csv](../partitions/partitions-4MiB-ota-flipbuddy.csv).

## Links

- App: https://flipbuddy.app
- Changelog: [CHANGELOG.md](./CHANGELOG.md)
- README (flash + pair): [../README.md](../README.md)
- Prior notes (historical, not for new flashes): [v0.1.5](./RELEASE_NOTES_v0.1.5.md)
