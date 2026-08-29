# FlipBuddy v0.1.5

Firmware **0.1.5** is the first Super Mini image on **MicroPython 1.28**. It adds last-AP Wi‑Fi reconnect, WPA2 SoftAP, USB-face yellow SoftAP LEDs, live face preview after pickup, and the physical cutout triad map.

## Highlights

- **MicroPython 1.28** frozen helpers, including the SoftAP portal (`ap_session`).
- **Last-AP fast reconnect:** the last successful home AP is remembered in NVS; the next join skips the extra scan and fails fast if that AP is gone.
- **WPA2 SoftAP:** join **`FlipBuddy`** with password **`FB` + last 6 alphanumeric of `device_id`**. The captive portal stays **HTTP** at `http://10.20.30.40/`.
- **USB-face SoftAP LEDs:** solid yellow (`#FFFF00`) on the USB-cutout triad (**left / back / bottom**).
- **Cutout triad:** `front_cutout` → right, top, front; `back_cutout` (USB) → left, back, bottom.
- **Pickup flow:** ~7 s assigned-face map → rotate → **10 s** solid on the live assigned face → usual tracking blink → upload if needed and/or deep sleep.

## Upgrade

Full reflash is recommended. SoftAP, cutout LEDs, and Wi‑Fi reconnect live in frozen modules.

### From v0.1.4

1. Download `esp32_s3_flipbuddy_0.1.5.bin` and its checksum from this Release.
2. Verify the checksum and perform a **full firmware reflash**.

    ```bash
    sha256sum -c esp32_s3_flipbuddy_0.1.5.bin.sha256
    esptool --chip esp32s3 --port /dev/ttyACM0 erase-flash
    esptool --chip esp32s3 --port /dev/ttyACM0 --baud 460800 write-flash 0 esp32_s3_flipbuddy_0.1.5.bin
    ```
3. After flashing, upload your `credentials.json` and the latest `main.py` again (`just fast-track` or `just put-main` + `just put-credentials`).
4. Power cycle the device.

### From v0.1.3 or earlier

Same full reflash procedure. This image includes the 0.1.2–0.1.4 pinout, gravity, memory, and session-durability work.

## Files on this Release

| File | Purpose |
|------|---------|
| `esp32_s3_flipbuddy_0.1.5.bin` | Frozen image with MicroPython 1.28 and 0.1.5 helpers. |
| `esp32_s3_flipbuddy_0.1.5.bin.sha256` | Checksum for the firmware binary. |
| `SHA256SUMS` | Full list of release file digests. |

```bash
sha256sum -c esp32_s3_flipbuddy_0.1.5.bin.sha256
```

Expected digest:
```
db17e275f2f6a9338ce7f3b36e6ffdca88a5d060efc87212afd51df8ebc3a644  esp32_s3_flipbuddy_0.1.5.bin
```

## Links

- App: https://flipbuddy.app
- Changelog: [CHANGELOG.md](https://github.com/PonderlyRobotics/esp_flipbuddy/blob/main/docs/CHANGELOG.md)
- Prior notes: [v0.1.4](./RELEASE_NOTES_v0.1.4.md), [v0.1.3](./RELEASE_NOTES_v0.1.3.md), [v0.1.2](./RELEASE_NOTES_v0.1.2.md)
- This GitHub repository for source, STLs, and docs
