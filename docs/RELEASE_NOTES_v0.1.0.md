# FlipBuddy v0.1.0

This is the first public DIY release under Ponderly Robotics.

You get a printed 8-face cube and MicroPython firmware for a stock ESP32-S3. Sessions show up in the free app at [flipbuddy.app](https://flipbuddy.app). I built it because I kept forgetting phone timers; I maintain it when I have free evenings.

## Who it is for

If you already print parts, can solder a little, and have flashed an ESP board before, you are in the right place. This is not a sealed consumer kit.

## Files on this Release

| File | Purpose |
|------|---------|
| `esp32_s3_flipbuddy_0.1.0.bin` | Frozen image (MicroPython 1.27 + FlipBuddy modules) |
| `esp32_s3_flipbuddy_0.1.0.bin.sha256` | Checksum |
| `SHA256SUMS` | Same digests |

```bash
sha256sum -c esp32_s3_flipbuddy_0.1.0.bin.sha256
```

## Quick start (Super Mini)

1. Print from `stl/` (the assembly PDF and `tolerance_check.stl` help).
2. Flash the `.bin` (details in the README).
3. Upload only `main.py` and your `credentials.json` (put Wi-Fi in the JSON).
4. Power cycle. Shake the cube if it already went to sleep.

The full walkthrough is in the repository README.

## License

- Sources: MIT
- Enclosure, CAD, assembly PDF: CC BY-NC-SA 4.0
- The `.bin` also contains MicroPython and other third-party code: see [NOTICE](./NOTICE)

## Links

- https://flipbuddy.app
- This GitHub repository for source, STLs, and docs
