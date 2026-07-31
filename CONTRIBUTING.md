# Contributing

Thanks for caring enough to open this file.

The [README](./README.md) is for people building a cube. This page is for people who want to change firmware, docs, or the little host tools around them. I work on FlipBuddy in the evenings under Ponderly Robotics, so reviews may take a while. That is fine. Careful patches are still welcome.

## Where to look

| Role | Start here |
|------|------------|
| Building a cube | [README.md](./README.md) |
| Contributing code or docs | This file |
| Shipping a frozen `.bin` | [Publishing frozen firmware](#publishing-frozen-firmware) |
| Licenses | [LICENSE](./LICENSE), [LICENSE-HARDWARE](./LICENSE-HARDWARE) |

## Pull requests

For big ideas (new boards, protocol changes, a different enclosure), open an issue first so we do not talk past each other. Typos, small bugs, and clear print notes can go straight to a PR.

Things that help a lot: power and sensor fixes, clearer wiring notes with photos, tests, shell variants that actually print on a normal FDM machine.

Be kind. There is no CLA. If you know embedded systems, a hard look at the FSM and sleep path is gold.

## Host tools (your PC, not the cube)

### Setup

```bash
uv sync
```

That makes a `.venv` and installs what `pyproject.toml` lists (`esptool`, `mpremote`, `adafruit-ampy`, and friends).

You can also:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

Or install the flash tools yourself and skip the project venv entirely.

`mise.toml` is optional. If you need a different git author in this folder (for example a Ponderly identity while your global git is personal), use `mise.local.toml` (gitignored). There is a template in `mise.local.toml.example`.

### Useful `just` recipes

After `uv sync`, recipes prefer `.venv` for `python` / `ruff` / `pytest` (same idea as `pull-nvs-state`).

| Recipe | What it does |
|--------|----------------|
| `just put-main` | Upload `main.py` only |
| `just put-credentials` | Upload `credentials.json` |
| `just fast-track` | `put-main` + `put-credentials` (frozen image path) |
| `just diy` | `upload` + `put-credentials` (full sources on stock MP) |
| `just upload` | Copy firmware modules (`device_py`) to the device |
| `just pull-nvs-state` | Dump config/tracker from NVS to local JSON |
| `just flash-firmware` | Erase and flash a `.bin` |
| `just shell` | Serial console |
| `just test` | Host tests (`tests/` + `test_fsm.py` via pytest) |
| `just check` / `just fix` / `just fmt` | Lint / format (ruff) |
| `just hooks` | Install pre-commit hooks |
| `just release-check` | Pre-release safety audit |
| `just release-assets <file.bin> [tag]` | Hash a frozen image for a GitHub Release |
| `just release-publish <file.bin> <tag>` | Hash + `gh release create` (needs `gh`) |
| `just clean-frozen` | Strip sources for frozen builds (advanced) |
| `just upload-clean` | Clean then upload stripped modules |

**Contributor loop (host, no hardware):**

```bash
uv sync
just check
just test
# optional: just fix && just fmt
```

**Device deploy (DIY / full SoftAP stack on filesystem):**

```bash
just diy          # or: just upload && just put-credentials
# frozen image path: just put-main (and put-credentials if needed)
```

Serial port defaults to `/dev/ttyACM0`. Override with `AMPY_PORT`.

### NVS on the device

After the first boot, credentials and runtime state live in NVS, not as ordinary files. `just ls` will not show them.

| Data | Namespace | Key |
|------|-----------|-----|
| Credentials | `cred` | `json` |
| Config | `config` | `cfg` |
| Tracker | `tracker` | `trk` |

`credentials.json` is copied into NVS and then removed from the filesystem.

```bash
just pull-nvs-state
# just pull-nvs-state out=./debug_dumps
```

That runs [scripts/pull_nvs_state.py](./scripts/pull_nvs_state.py): it pauses the soft watchdog, pulls the blobs out through temporary files, and leaves NVS alone. Local JSON dumps are gitignored.

## Pre-commit and safety checks

```bash
just hooks
```

Hooks cover secret scanning, private keys, [scripts/release_check.py](./scripts/release_check.py), and ruff (see `.pre-commit-config.yaml`).

Before you tag or push something public:

```bash
just release-check
```

Fix failures. Warnings are usually things like a local `credentials.json` that is already ignored.

Please do not commit real credentials, `.env` files, private keys, absolute home paths in tracked files, or the multi-megabyte firmware `.bin` files. Binaries go on GitHub Releases. Do not `git add -f` them.

## Publishing frozen firmware

We keep Super Mini images out of git and put them on Releases with checksums.

1. Build the image (MicroPython + IDF; `just clean-frozen` if that is part of your flow). Name it something like `esp32_s3_flipbuddy_0.1.2.bin`. Leave it untracked.

2. Run `just release-check` on the tree you built from.

3. Hash it:

   ```bash
   just release-assets esp32_s3_flipbuddy_0.1.2.bin v0.1.2
   ```

4. Tag that commit and push the tag.

5. Create the GitHub Release (`just release-publish …` or `gh release create`) and attach the `.bin` plus checksum files. [docs/RELEASE_NOTES_v0.1.2.md](./docs/RELEASE_NOTES_v0.1.2.md) is a fine template for the notes body.

6. If the README still names an old image, update the version string there.

Never `git add` the `.bin`.

To flash after download:

```bash
sha256sum -c esp32_s3_flipbuddy_0.1.2.bin.sha256
just flash-firmware esp32_s3_flipbuddy_0.1.2.bin
```

## Tests

```bash
just test
```

That runs:

1. `pytest tests/` - SoftAP portal, credentials PIN, network helpers  
2. `python test_fsm.py` - Boot / Active / Upload FSM suite (self-contained host runner)

No hardware required. Prefer `uv sync` first so `.venv` has pytest and ruff.

## Code map

| Area | File |
|------|------|
| Orchestration / FSMs | `main.py` (early SoftAP gate at top; Boot / Active / Upload) |
| SoftAP session (clean heap) | `ap_session.py` |
| SoftAP captive portal | `ap_mode.py` (PIN unlock, Wi-Fi UI, LED test) |
| Faces, tracker, config | `models.py` |
| IMU / face math | `mpu6050.py` (leave the DMP blob and fmt guards alone) |
| LEDs | `rgb.py` |
| HTTP / token rotate | `http.py` |
| Wi-Fi STA / SoftAP helpers | `network_helper.py` |
| Credentials / NVS / SoftAP PIN | `credentials.py` |
| Power diagram | `fsm.dot` |
| SoftAP end-user steps / risks | [README SoftAP](./README.md#softap-maintenance-mode), [SECURITY SoftAP](./SECURITY.md#softap-captive-portal-http-pin-wi-fi) |
| Host SoftAP / credential tests | `tests/` |

SoftAP **builder** steps live in the README; this file is for portal / PIN / handoff **code** changes. (Private design notes may exist under `ADR/` locally; that directory is not published.)

Usual life cycle: Boot (Wi-Fi, NTP, config), a short sleep, then Active and Upload when waking from deep sleep. USB face (`back_cutout`) soft-resets into SoftAP via the early gate in `main.py` (no `boot.py`). For small behavior changes on a frozen image, prefer `just put-main`; for DIY full sources use `just diy` / `just upload`.

Pins: search `main.py` for `NP_DATA_PIN` and the neighboring constants.

## Custom frozen builds

Rebuilding a frozen image means a full MicroPython and ESP-IDF tree. Most patches do not need that. `clean_frozen.py` and the release-asset scripts are there if you do.

## License

- Software patches: MIT ([LICENSE](./LICENSE))
- Enclosure, CAD, assembly art: CC BY-NC-SA 4.0 ([LICENSE-HARDWARE](./LICENSE-HARDWARE))

Thanks for reading this, and for any careful work you send back.
