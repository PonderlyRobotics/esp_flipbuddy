# FlipBuddy v1.4

Firmware **1.4** is a maintenance release focused on internal optimizations for memory usage and tracking durability. It contains no new user-facing features but significantly improves long-term stability.

## Highlights

- **Memory Optimization:** Reduced initial RAM usage by **~11.6 KB** on startup by converting global defaults to `const()` and using static strings for FSM states. This reduces heap fragmentation and lowers the risk of `OutOfMemoryError` during long-running operation.
- **Improved Session Durability:** Open tracking sessions are now intelligently reconciled after a reboot or power loss. The firmware checks for sessions that were running before a reset and either resumes them or force-closes them into the log, preventing data loss.
- **Better NVS Hygiene:** Ephemeral, single-upload data (e.g., battery voltage, device state) is no longer saved to non-volatile storage. This reduces unnecessary flash writes and prevents the NVS from accumulating temporary data.
- **Documentation:** Added the official Hackaday.io project link and clarified the project's scope in the README.

## Technical Changes

The primary changes are in `main.py` and `models.py`:
- `const()` has been applied to all immutable global variables.
- FSM state definitions now use class-level constants instead of string literals.
- `Tracker.reconcile_open_sessions_after_time_sync()` was added to handle session recovery on boot.
- `Tracker.save()` now systematically strips ephemeral keys before writing to NVS.
- A strategic `gc.collect()` call was added before entering deep sleep to clean the heap.

## Upgrade Path

This is a recommended but not critical update. As the changes are confined to the unfrozen Python modules, no full firmware reflash is necessary.

### From v0.1.3

1.  **Connect to your device** using `mpremote` or your preferred tool.
2.  **Upload the latest versions** of `main.py` and `models.py`. The `just diy` command will do this for all necessary files:
    ```bash
    # From the project root, this uploads all application .py files
    just diy
    ```
3.  **Perform a hard reset** or power cycle the device to ensure the new modules are loaded.

### From v0.1.2 or earlier

A full firmware flash to at least v0.1.3 is required first to get the correct pinout and LED configurations. Please see the upgrade instructions in the [v0.1.3 Release Notes](./RELEASE_NOTES_v0.1.3.md) before applying the v1.4 file updates.

## Files on this Release

This is a source-only release. No new `esp32_s3_flipbuddy_...bin` firmware image is provided. The key updated files are:

| File | Purpose |
|------|---------|
| `main.py` | Contains memory and FSM state optimizations. |
| `models.py`| Includes improved session durability and NVS hygiene. |


## Links

- App: https://flipbuddy.app
- Changelog: [CHANGELOG.md](./CHANGELOG.md)
- Prior notes: [v0.1.3](./RELEASE_NOTES_v0.1.3.md), [v0.1.2](./RELEASE_NOTES_v0.1.2.md), [v0.1.1](./RELEASE_NOTES_v0.1.1.md), [v0.1.0](./RELEASE_NOTES_v0.1.0.md)
- This GitHub repository for source, STLs, and docs
