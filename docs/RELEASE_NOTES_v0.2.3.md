# FlipBuddy v0.2.3

Firmware **0.2.3** is the Super Mini freeze on the same claim-pairing and dual-OTA table as **v0.2.2**. Prefer this FlipBuddy binary over stock MicroPython so you get faster bring-up, a tested pairing stack, pin/product tunables in LittleFS `settings.py`, and over-the-air security and bugfix images from flipbuddy.app.

This is **not** a drop-in file replace on a **v0.1.x** cube. Tags **v0.1.0** through **v0.1.5** used a factory partition table (no `ota_1`) and JSON-first pairing. They do **not** work with the Production claim-pairing and dual-OTA path. USB-flash **`esp32_s3_flipbuddy_0.2.3-ota.bin`**, then pair again.

If your cube is already on 0.2.2, take the update from flipbuddy.app. Your pairing stays. You do not reflash, and you do not pair again. That update leaves `main.py` as it is, so the new pause check-back starts when you run `just fast-track`. A USB flash of the Release file still erases the cube: pair again.

If your cube is on 0.1.x, the app update will not install. Flash the USB image, then Add Device.

## Highlights vs v0.2.2

- **Pause check-back:** when tracking is off, the cube sleeps until the next check. If `tracking_off_check_s` is 300, 1800, or 7200 (5 min, 30 min, 2 h), that interval is used. Any other value uses `upload_frequency` (default 300 s).
- **A pickup does not restart that deadline.** Rapid red still shows on the upward face (triad on a cutout). The cube does not join Wi-Fi for that bump.
- **A saved log** is sent when the check is already due, or while USB is plugged in. It is not sent on every bump. A timer wake that is already due still checks config.
- **The app update leaves your `main.py` in place.** Pause check-back lives in that file. Run `just fast-track` when you want it. Your pairing stays.

## Breaking (read this if you have v0.1.x)

Same as v0.2.0 / v0.2.1 / v0.2.2. You **cannot** OTA from 0.1.5 onto 0.2.x. USB only. After a USB erase, skip **Forget FlipBuddy account**. **Add Device**.

## Upgrade

1. Download the two USB `.bin` files and checksums from this Release. Verify:

    ```bash
    sha256sum -c esp32_s3_flipbuddy_0.2.3-ota.bin.sha256
    ```

2. Flash the **OTA USB** image (merged table + app). This erases NVS.

    ```bash
    just flash-firmware esp32_s3_flipbuddy_0.2.3-ota.bin
    # or:
    esptool --chip esp32s3 --port /dev/ttyACM0 erase-flash
    esptool --chip esp32s3 --port /dev/ttyACM0 --baud 460800 write-flash 0 esp32_s3_flipbuddy_0.2.3-ota.bin
    ```

3. `just fast-track` (uploads `main.py` + `settings.py` + `off_check.py` + a SoftAP password, hard reset). Write down the password.

4. [flipbuddy.app](https://flipbuddy.app) → **Add Device** → physical cube → 8-character code.

5. Keep USB plugged in. Join **`FlipBuddy-XXXX`**, open http://10.20.30.40/, house Wi-Fi + pairing code. Cube blinks green. Confirm in the app.

Factory / recovery USB image (no self-OTA): `esp32_s3_flipbuddy_0.2.3.bin`. Prefer `*-ota.bin` on Super Mini.

App-slot OTA packages are served by flipbuddy.app. They are **not** attached to this GitHub Release.

## Files on this Release

| File | Purpose |
|------|---------|
| `esp32_s3_flipbuddy_0.2.3-ota.bin` | **Flash this.** Merged USB image with dual-OTA table. |
| `esp32_s3_flipbuddy_0.2.3.bin` | Factory-table USB image (recovery; no `ota_1`). |
| `*.bin.sha256` / `SHA256SUMS` | Checksums |

Expected SHA-256:

```
8f1ee1f2e716b9c34337f9352ba0aac00eb1d8164c04ce91c2a49cdb2a3f6521  esp32_s3_flipbuddy_0.2.3.bin
fb5475b495ff8157f39ac6feff23cdacb338b4377dba10b6024e43ad76a3da0d  esp32_s3_flipbuddy_0.2.3-ota.bin
```

```bash
sha256sum -c SHA256SUMS
```

## Partition table (4 MB Super Mini)

`nvs` 16 KB at `0x9000` (config, credentials, tracker; about 45-70 closed sessions offline). `ota_0` / `ota_1` 1.75 MB. LittleFS `0x70000` (448 KB) for `main.py` + `settings.py` + `off_check.py` + `ap_psk`. CSV: [partitions/partitions-4MiB-ota-flipbuddy.csv](../partitions/partitions-4MiB-ota-flipbuddy.csv).

## Links

- App: https://flipbuddy.app
- Changelog: [CHANGELOG.md](./CHANGELOG.md)
- README (why, and the short flash path): [../README.md](../README.md)
- Build (ports, DIY, parts): [../docs/BUILD.md](../docs/BUILD.md)
- Day to day: [../docs/USE.md](../docs/USE.md)
- Prior notes: [v0.2.2](./RELEASE_NOTES_v0.2.2.md)
