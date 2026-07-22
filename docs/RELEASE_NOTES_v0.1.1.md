# FlipBuddy v0.1.1

Firmware **0.1.1** release: SoftAP maintenance mode and related host tooling.

## Highlights

- **SoftAP maintenance mode** on the USB‑C face: join open Wi‑Fi **`FlipBuddy`**, portal at `http://10.20.30.40/`
- Status without PIN: **UTC time**, battery, faces, local activity records, **Reset device**
- After setup PIN: Wi‑Fi profiles, change PIN, LED self‑test
- Factory PIN = last 6 alphanumeric of `device_id` (or custom PIN in NVS)
- Clean-heap SoftAP path (`ap_session` + early gate); lazy STA helpers
- Host tests + CI for SoftAP helpers; docs in README and SECURITY

## Files on this Release

| File | Purpose |
|------|---------|
| `esp32_s3_flipbuddy_0.1.1.bin` | Frozen image (MicroPython 1.27 + FlipBuddy modules including SoftAP stack) |
| `esp32_s3_flipbuddy_0.1.1.bin.sha256` | Checksum |
| `SHA256SUMS` | Same digests |

```bash
sha256sum -c esp32_s3_flipbuddy_0.1.1.bin.sha256
```

## Quick start (Super Mini)

1. Flash the **0.1.1** `.bin` (README fast track).
2. Upload only **`main.py`** and your **`credentials.json`**.
3. Power cycle. SoftAP: USB‑C face up → `FlipBuddy` → portal.

Full SoftAP steps, PIN rules, and clock FAQ: repository README. SoftAP risks: SECURITY.md.

## License

- Sources: MIT
- Enclosure, CAD, assembly PDF: CC BY-NC-SA 4.0
- The `.bin` also contains MicroPython and other third-party code: see [NOTICE](./NOTICE)

## Links

- https://flipbuddy.app
- This GitHub repository for source, STLs, and docs
