# FlipBuddy v0.1.4

Firmware **0.1.4** is a maintenance release focused on internal optimizations for memory usage and tracking durability. It contains no new user-facing features but significantly improves long-term stability.

## Highlights

- **Memory Optimization:** Reduced initial RAM usage by **~11.6 KB** on startup by converting global defaults to `const()` and using static strings for FSM states. This reduces heap fragmentation and lowers the risk of `OutOfMemoryError` during long-running operation.
- **Improved Session Durability:** Open tracking sessions are now intelligently reconciled after a reboot or power loss. The firmware checks for sessions that were running before a reset and either resumes them or force-closes them into the log, preventing data loss.
- **Better NVS Hygiene:** Ephemeral, single-upload data (e.g., battery voltage) is no longer saved to non-volatile storage. This reduces unnecessary flash writes and prevents the NVS from accumulating temporary data.
- **Documentation:** Added the official Hackaday.io project link and clarified the project's scope in the README.

## Upgrade

This is a recommended firmware update for all users. It includes significant memory and stability optimizations.

### From v0.1.3

1.  Download `esp32_s3_flipbuddy_0.1.4.bin` and its checksum from this Release.
2.  Verify the checksum and perform a **full firmware reflash**, as the optimizations are baked into the frozen modules.

    ```bash
    sha256sum -c esp32_s3_flipbuddy_0.1.4.bin.sha256
    esptool --chip esp32s3 --port /dev/ttyACM0 erase-flash
    esptool --chip esp32s3 --port /dev/ttyACM0 --baud 460800 write-flash 0 esp32_s3_flipbuddy_0.1.4.bin
    ```
3.  After flashing, upload your `credentials.json` and the latest `main.py` again.
4.  Power cycle the device.

### From v0.1.2 or earlier

Same full reflash procedure. This update includes all previous fixes, including the critical pinout and gravity remaps from v0.1.2 and v0.1.3.

## Files on this Release

| File                               | Purpose                                                        |
| ---------------------------------- | -------------------------------------------------------------- |
| `esp32_s3_flipbuddy_0.1.4.bin`       | Frozen image with MicroPython 1.27 and all firmware optimizations. |
| `esp32_s3_flipbuddy_0.1.4.bin.sha256` | Checksum for the firmware binary.                                |
| `SHA256SUMS`                       | Full list of release file digests.                             |

```bash
sha256sum -c esp32_s3_flipbuddy_0.1.4.bin.sha256
```

Expected digest:
```
a2201ff7b3118e1b1f6fada2c02bb146f70a1771d6189f50b6d74e8615a29c2a  esp32_s3_flipbuddy_0.1.4.bin
```

## Links

- App: https://flipbuddy.app
- Changelog: [CHANGELOG.md](./CHANGELOG.md)
- Prior notes: [v0.1.3](./RELEASE_NOTES_v0.1.3.md), [v0.1.2](./RELEASE_NOTES_v0.1.2.md), [v0.1.1](./RELEASE_NOTES_v0.1.1.md), [v0.1.0](./RELEASE_NOTES_v0.1.0.md)
- This GitHub repository for source, STLs, and docs
