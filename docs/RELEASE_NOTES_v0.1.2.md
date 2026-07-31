# FlipBuddy v0.1.2

Firmware **0.1.2** release: face orientation and NeoPixel pinout aligned to the physical enclosure.

This is a small but important hardware-alignment fix on top of **0.1.1**. SoftAP maintenance mode, frozen MicroPython 1.27 stack, and the fast-track workflow are unchanged. If the wrong LED lit when you flipped a face, or tracking names did not match the side you held up, reflash this image.

## Highlights

- **Correct face names for gravity detection** — `cube_face_upward()` returns the same face labels used by the tracker, dashboard, and LEDs
- **NeoPixel pinout renamed** to match the LED chain on the board / enclosure (DIN index 0…5)
- **Cutout triad LEDs updated** so USB / front cutout blink patterns still light the right three cells
- **Cutout orientation names unchanged** — `front_cutout` / `back_cutout` (SoftAP USB face) keep the same roll/pitch detection
- Host CI: checkout + setup-python actions on Node 24 majors (tooling only)

## What changed (face remap)

Physical gravity axes were already stable. What was wrong was the **name** attached to each axis and each LED index. Detection and pinout now use one shared rename:

| Old face name | New face name |
|---------------|---------------|
| `back`        | `front`       |
| `left`        | `bottom`      |
| `front`       | `back`        |
| `bottom`      | `left`        |
| `right`       | `top`         |
| `top`         | `right`       |

### LED chain (DIN starts at 0)

| Index | 0.1.1 label | 0.1.2 label |
|------:|-------------|-------------|
| 0     | back        | **front**   |
| 1     | left        | **bottom**  |
| 2     | front       | **back**    |
| 3     | bottom      | **left**    |
| 4     | right       | **top**     |
| 5     | top         | **right**   |

### Gravity → name (`cube_face_upward`)

| Dominant axis | 0.1.1 return     | 0.1.2 return     |
|---------------|------------------|------------------|
| +Z / −Z       | bottom / top     | **left** / **right** |
| +X / −X       | left / right     | **bottom** / **top** |
| +Y / −Y       | back / front     | **front** / **back** |

Modules touched in source: `rgb.py` (pinout + triad), `mpu6050.py` (`cube_face_upward` only). Both ship **frozen** in the Release `.bin`, so this fix is not applied by uploading `main.py` alone.

## Why upgrade

- Upward face, lit LED, and dashboard face name should agree after assembly
- Activity colors map to the physical side you intend when assigning faces in the app / SoftAP status view
- DIY builders who already flashed 0.1.1 with a finished cube get correct orientation without rewiring LEDs

If you never noticed swapped faces, you can stay on 0.1.1; behavior is otherwise the same SoftAP + tracking stack.

## Upgrade from 0.1.1

1. Download **`esp32_s3_flipbuddy_0.1.2.bin`** and its `.sha256` from this Release.
2. Verify checksum (below).
3. **Reflash the full frozen image** (erase optional but recommended if you had a messy filesystem):

   ```bash
   sha256sum -c esp32_s3_flipbuddy_0.1.2.bin.sha256
   esptool --chip esp32s3 --port /dev/ttyACM0 erase-flash
   esptool --chip esp32s3 --port /dev/ttyACM0 --baud 460800 write-flash 0 esp32_s3_flipbuddy_0.1.2.bin
   ```

   Or from a checkout that has the file:

   ```bash
   just flash-firmware build/esp32_s3_flipbuddy_0.1.2.bin
   ```

4. Put **`main.py`** and **`credentials.json`** again (fast track). NVS Wi‑Fi / PIN from SoftAP usually survive a flash; if STA fails, re-enter Wi‑Fi via SoftAP or credentials.
5. Power cycle. Flip each face once: the LED on the **up** face should match that face’s activity color.

### Activity map note

Face **names** in the free app / tracker (`front`, `back`, `left`, `right`, `top`, `bottom`) are unchanged as API strings. What moved is which **physical** side of the cube those names refer to after assembly. If you had mentally assigned “this painted side is left” under 0.1.1’s wrong map, re-check assignments after upgrading — the firmware names should now match the enclosure orientation described in the assembly PDF / wiring notes.

SoftAP factory PIN, custom PIN, multi-profile Wi‑Fi, and USB-face portal behavior are the same as 0.1.1. See README SoftAP section and [SECURITY.md](../SECURITY.md).

## Files on this Release

| File | Purpose |
|------|---------|
| `esp32_s3_flipbuddy_0.1.2.bin` | Frozen image (MicroPython 1.27 + FlipBuddy modules, face remap applied) |
| `esp32_s3_flipbuddy_0.1.2.bin.sha256` | Checksum |
| `SHA256SUMS` | Same digests (when attached) |

```bash
sha256sum -c esp32_s3_flipbuddy_0.1.2.bin.sha256
```

Expected digest for the published image:

```
5db186d3c28633d95de4b0d9928d799049a65943df50b7509b63e27eda13a593  esp32_s3_flipbuddy_0.1.2.bin
```

## Quick start (Super Mini)

1. Flash the **0.1.2** `.bin` (README fast track).
2. Upload only **`main.py`** and your **`credentials.json`** (Wi‑Fi under `wifi.<name>`).
3. Power cycle. Shake if it already deep-slept.
4. SoftAP: USB‑C face up → join open Wi‑Fi **`FlipBuddy`** → portal `http://10.20.30.40/`.

DIY / `just diy` on stock MicroPython still works: upload full sources (including updated `rgb.py` and `mpu6050.py`) instead of the frozen image.

Full SoftAP steps, PIN rules, clock FAQ: repository README. SoftAP risks: [SECURITY.md](../SECURITY.md).

## What is not in this release

- No new SoftAP features (those landed in 0.1.1)
- No enclosure / STL / assembly PDF revision
- No API or credentials schema change
- No MicroPython version bump (still 1.27)

## License

- Sources: MIT
- Enclosure, CAD, assembly PDF: CC BY-NC-SA 4.0
- The `.bin` also contains MicroPython and other third-party code: see [NOTICE](./NOTICE)

## Links

- App: https://flipbuddy.app
- Changelog: [CHANGELOG.md](./CHANGELOG.md)
- Prior notes: [v0.1.1](./RELEASE_NOTES_v0.1.1.md), [v0.1.0](./RELEASE_NOTES_v0.1.0.md)
- This GitHub repository for source, STLs, and docs
