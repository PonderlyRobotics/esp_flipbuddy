# FlipBuddy v0.1.3

Firmware **0.1.3** release: cutout triad LED fix on top of the 0.1.2 face pinout remap.

If you already flashed **0.1.2**, reflash this image. Flat-face tracking was fine on 0.1.2; **USB / front cutout** triad patterns lit the wrong three cells.

## Highlights

- **Correct cutout triad faces** after the 0.1.2 pinout rename:
  - `front_cutout` → `bottom`, `left`, `back`
  - `back_cutout` → `top`, `right`, `front`
- Same face gravity remap and NeoPixel labels as **0.1.2** (no further rename)
- SoftAP, MicroPython 1.27 frozen stack, and fast-track workflow unchanged

## What was wrong in 0.1.2

0.1.2 remapped the six flat faces and also swapped the cutout **triad** tuples with the pinout rename. That put the wrong three LEDs on `front_cutout` / `back_cutout` blink patterns. Detection names (`front_cutout` / `back_cutout`) and roll/pitch thresholds were never the bug — only which NeoPixel indices blinked.

## Cutout LEDs (0.1.3)

| Orientation   | Triad faces              | DIN indices |
|---------------|--------------------------|-------------|
| `front_cutout` | bottom, left, back      | 1, 3, 2     |
| `back_cutout`  | top, right, front       | 4, 5, 0     |

(Plus each cutout’s own `led_pin` during the blink loop: front_cutout → bottom; back_cutout → top.)

## Flat faces (unchanged from 0.1.2)

| Old name | New name |
|----------|----------|
| back     | front    |
| left     | bottom   |
| front    | back     |
| bottom   | left     |
| right    | top      |
| top      | right    |

LED DIN 0…5: **front, bottom, back, left, top, right**.

## Upgrade

### From 0.1.2

1. Download `esp32_s3_flipbuddy_0.1.3.bin` + checksum from this Release.
2. Verify and **full reflash** (frozen modules include `rgb.py`):

   ```bash
   sha256sum -c esp32_s3_flipbuddy_0.1.3.bin.sha256
   esptool --chip esp32s3 --port /dev/ttyACM0 erase-flash
   esptool --chip esp32s3 --port /dev/ttyACM0 --baud 460800 write-flash 0 esp32_s3_flipbuddy_0.1.3.bin
   ```

   Or: `just flash-firmware build/esp32_s3_flipbuddy_0.1.3.bin`

3. Put `main.py` + `credentials.json` again. Power cycle.
4. Rest USB face (`back_cutout`) and the opposite cutout once — triad colors should match the three faces around that corner.

### From 0.1.1 or earlier

Same full reflash; you also get the 0.1.2 face pinout / gravity fix. See [RELEASE_NOTES_v0.1.2.md](./RELEASE_NOTES_v0.1.2.md).

## Files on this Release

| File | Purpose |
|------|---------|
| `esp32_s3_flipbuddy_0.1.3.bin` | Frozen image (MicroPython 1.27 + SoftAP + face remap + triad fix) |
| `esp32_s3_flipbuddy_0.1.3.bin.sha256` | Checksum |
| `SHA256SUMS` | Digests (when attached) |

```bash
sha256sum -c esp32_s3_flipbuddy_0.1.3.bin.sha256
```

Expected digest:

```
53e11655c321b035f680131f0a4b84af39bae2ef0512c5996fe7665e292c4131  esp32_s3_flipbuddy_0.1.3.bin
```

## Quick start (Super Mini)

1. Flash the **0.1.3** `.bin` (README fast track).
2. Upload only **`main.py`** and **`credentials.json`**.
3. Power cycle. SoftAP: USB‑C face up → Wi‑Fi **`FlipBuddy`** → `http://10.20.30.40/`.

DIY / `just diy`: upload full sources including the fixed `rgb.py`.

SoftAP risks: [SECURITY.md](../SECURITY.md).

## What is not in this release

- No new SoftAP features
- No enclosure / STL changes
- No MicroPython version bump (still 1.27)
- Tag **v0.1.2** is left as published (known triad bug); use **0.1.3** for new flashes

## License

- Sources: MIT
- Enclosure, CAD, assembly PDF: CC BY-NC-SA 4.0
- The `.bin` also contains MicroPython and other third-party code: see [NOTICE](./NOTICE)

## Links

- App: https://flipbuddy.app
- Changelog: [CHANGELOG.md](./CHANGELOG.md)
- Prior notes: [v0.1.2](./RELEASE_NOTES_v0.1.2.md), [v0.1.1](./RELEASE_NOTES_v0.1.1.md), [v0.1.0](./RELEASE_NOTES_v0.1.0.md)
- This GitHub repository for source, STLs, and docs
