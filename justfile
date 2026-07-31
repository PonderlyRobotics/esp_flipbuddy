# FlipBuddy ESP32 MicroPython firmware
#
# Polished open-source release.
#
# Typical user flow (Super Mini fast track):
#   1. Download frozen .bin from GitHub Releases + verify .sha256
#   2. just flash-firmware esp32_s3_flipbuddy_0.1.2.bin
#   3. just fast-track   # main.py + credentials.json
#   4. Power cycle the device.
# DIY (stock MicroPython): just flash-firmware <stock.bin> && just diy
#
# Device recipes default to mpremote. Legacy ampy: just upload-ampy / put-credentials-ampy.
#
# This justfile deliberately does **not** require building MicroPython
# from source or running the frozen-module size optimization by default.
# Those steps are heavy and only relevant for custom production firmware builds.

set unstable := true
set shell := ["bash", "-uc"]

# Board / serial defaults (ESP32-S3 Super Mini class). Change for other hardware — see README.
usb_dev := env("AMPY_PORT", "/dev/ttyACM0")  # or: export AMPY_PORT=/dev/ttyUSB0
esp_chip := "s3"                             # esptool --chip esp32{{ esp_chip }}  (s3 → esp32s3)
esp_flash_size := "4MB"                      # document your module flash; shown by `just env`

# Firmware modules for the ESP only (not host tools: test_fsm.py, clean_frozen.py, scripts/)
device_py := "main.py ap_session.py models.py mpu6050.py rgb.py http.py network_helper.py credentials.py util.py ap_mode.py"
# AST-stripped modules written by `just clean-frozen` (no main.py — kept full-size / editable)
cleaned_dir := "/tmp/flipbuddy_cleaned"
cleaned_py := "models.py mpu6050.py rgb.py http.py network_helper.py credentials.py util.py ap_mode.py ap_session.py"

[private]
default:
    @just --list

# =============================================================================
# DEVICE
# =============================================================================
# Commands for day-to-day interaction with the ESP32 (upload, flash, console, etc.)

# Open serial console
[group("Device")]
shell:
    picocom {{ usb_dev }} -b115200

# List files currently on the device
[group("Device")]
ls:
    mpremote connect {{ usb_dev }} ls

# Upload firmware Python sources (DIY / full source path — not needed on frozen fast track)
[group("Device")]
upload:
    mpremote connect {{ usb_dev }} cp {{ device_py }} :
    @echo "Upload complete. Reset the ESP32 to run the new code."

# Legacy ampy upload
[group("Device")]
upload-ampy:
    @echo "→ Uploading source files to {{ usb_dev }} (ampy) ..."
    @for f in {{ device_py }}; do \
        echo "   + $f"; ampy --port {{ usb_dev }} put "$f"; \
    done
    @echo "Upload complete. Reset the ESP32 to run the new code."

# Alias kept for older docs
[group("Device")]
upload-mp: upload

# Remove runtime state files (tracker + cached config) from the device
[group("Device")]
reset-state:
    -mpremote connect {{ usb_dev }} rm :saved_tracker.json
    -mpremote connect {{ usb_dev }} rm :startup_config.json
    @echo "Runtime state files removed from device (ignore errors if missing)."

# Upload main.py only (frozen image path — do not mass-upload other modules)
[group("Device")]
put-main:
    mpremote connect {{ usb_dev }} cp main.py :
    @echo "main.py uploaded."

# Upload credentials.json (will be migrated to NVS on first boot)
[group("Device")]
put-credentials:
    @test -f credentials.json || (echo "credentials.json not found next to justfile" && exit 1)
    mpremote connect {{ usb_dev }} cp credentials.json :
    @echo "credentials.json uploaded."

[group("Device")]
put-credentials-ampy:
    @test -f credentials.json || (echo "credentials.json not found next to justfile" && exit 1)
    ampy --port {{ usb_dev }} put credentials.json
    @echo "credentials.json uploaded (ampy)."

# Fast track FS deploy: main.py + credentials (after flashing the frozen Release .bin)
[group("Device")]
fast-track:
    @echo "→ Fast track: main.py + credentials.json on {{ usb_dev }}"
    just put-main
    just put-credentials
    @echo "✓ Fast track upload done. Power-cycle the ESP32."

# DIY FS deploy: all firmware modules + credentials (stock MicroPython / full sources)
[group("Device")]
diy:
    @echo "→ DIY: full device_py + credentials.json on {{ usb_dev }}"
    just upload
    just put-credentials
    @echo "✓ DIY upload done. Power-cycle the ESP32."

# Dump config + tracker from device NVS → local JSON (stops scheduler_wd first; NVS left intact)
[group("Device")]
pull-nvs-state out=".":
    #!/usr/bin/env bash
    set -euo pipefail
    # Prefer repo .venv so mpremote is available after `uv sync`
    if [[ -x .venv/bin/python ]]; then
      PY=.venv/bin/python
    else
      PY=python3
    fi
    "$PY" scripts/pull_nvs_state.py "{{ out }}" --port {{ usb_dev }}

# Full erase + flash a firmware .bin (download frozen images from GitHub Releases first)
[group("Device")]
flash-firmware firmware="esp32_s3_flipbuddy_0.1.0.bin":
    # Examples:
    #   just flash-firmware esp32_s3_flipbuddy_0.1.0.bin   # from GitHub Releases
    #   just flash-firmware ESP32_GENERIC_S3-....bin       # stock MicroPython
    #
    # Frozen FlipBuddy images are on GitHub Releases (not committed). Verify .sha256 then flash.
    # After the frozen image: main.py + credentials.json only on the FS.
    # Stock MicroPython builds: https://micropython.org/download/ESP32_GENERIC_S3/
    @test -f "{{ firmware }}" || (echo "Firmware file not found: {{ firmware }}" && echo "Download the Release asset first (see README / CONTRIBUTING)." && exit 1)
    @echo "!!! This will ERASE the entire flash on {{ usb_dev }}"
    @echo "→ Flashing {{ firmware }} ..."
    esptool --chip esp32{{ esp_chip }} --port {{ usb_dev }} erase-flash
    esptool --chip esp32{{ esp_chip }} --port {{ usb_dev }} --baud 460800 write-flash 0 {{ firmware }}

# =============================================================================
# ADVANCED
# =============================================================================
# Tools for building smaller custom frozen firmware (requires full MicroPython + IDF)

# Strip docstrings, prints and comments from sources using AST → cleaned_dir
# Used by upload-clean / upload-mp-clean and custom frozen image builds.
[group("Advanced")]
clean-frozen:
    @echo "Running AST cleaner (docstrings, prints, comments)..."
    rm -rf {{ cleaned_dir }}
    mkdir -p {{ cleaned_dir }}
    python3 clean_frozen.py . {{ cleaned_dir }}
    @echo "Cleaned files are in {{ cleaned_dir }}/"
    @ls -lh {{ cleaned_dir }}/

# Compare original vs cleaned file sizes
[group("Advanced")]
inspect-clean:
    @echo "Original vs cleaned sizes (requires clean-frozen to have run):"
    -du -h *.py {{ cleaned_dir }}/*.py 2>/dev/null | sort

# Run clean-frozen, then upload AST-stripped modules from cleaned_dir (+ full main.py)
[group("Advanced")]
upload-clean:
    #!/usr/bin/env bash
    set -euo pipefail
    just clean-frozen
    echo "→ Uploading cleaned modules from {{ cleaned_dir }} to {{ usb_dev }} ..."
    for f in {{ cleaned_py }}; do
      src="{{ cleaned_dir }}/$f"
      test -f "$src" || { echo "missing $src (clean-frozen failed?)"; exit 1; }
      echo "   + $f (cleaned)"
      mpremote connect {{ usb_dev }} cp "$src" ":$f"
    done
    echo "   + main.py (repo source, not stripped)"
    mpremote connect {{ usb_dev }} cp main.py :
    echo "Upload complete. Reset the ESP32 to run the new code."

# =============================================================================
# UTILS
# =============================================================================

# Print current target configuration (port, chip, etc.)
[group("Utils")]
env:
    @echo "AMPY_PORT = {{ usb_dev }}"
    @echo "Target chip = esp32{{ esp_chip }} (flash {{ esp_flash_size }})"

# Host tests (CONTRIBUTING.md): SoftAP helpers via pytest, FSM suite via test_fsm runner.
# Prefer project .venv after `uv sync`. test_fsm.py keeps its own MicroPython mocks and
# asyncio runner so it does not fight tests/conftest.py shims under one pytest process.
[group("Utils")]
test:
    #!/usr/bin/env bash
    set -euo pipefail
    if [[ -x .venv/bin/python ]]; then
      PY=.venv/bin/python
    else
      PY=python3
    fi
    echo "→ SoftAP / credentials host tests (tests/)"
    if "$PY" -c "import pytest" 2>/dev/null; then
      "$PY" -m pytest tests -q --tb=short
    else
      echo "pytest missing — run: uv sync" >&2
      exit 1
    fi
    echo "→ FSM host suite (test_fsm.py)"
    "$PY" test_fsm.py

# Full pre-release safety audit (secrets, personal paths, credentials on disk, history)
# Maintainers/contributors only — see CONTRIBUTING.md. Run before a public push/tag.
# Install commit hooks once with: just hooks
[group("Utils")]
release-check:
    @echo "→ FlipBuddy release safety check (scripts/release_check.py --full)..."
    python3 scripts/release_check.py --full
    @echo ""
    @echo "→ pre-commit security hooks..."
    pre-commit run flipbuddy-safety --all-files
    pre-commit run detect-private-key --all-files
    pre-commit run gitleaks --all-files
    @echo ""
    @echo "✓ release-check passed. Review any warnings above before publishing."

# Hash a frozen .bin for GitHub Releases (writes .sha256 + SHA256SUMS; does not upload)
# Positional args only: just release-assets esp32_s3_flipbuddy_0.1.2.bin v0.1.2
[group("Utils")]
release-assets firmware tag="":
    #!/usr/bin/env bash
    set -euo pipefail
    if [[ ! -f "{{ firmware }}" ]]; then
      echo "Firmware file not found: {{ firmware }}"
      echo "Build the frozen image first, then run this from the directory that contains it."
      exit 1
    fi
    args=(scripts/release_assets.py "{{ firmware }}")
    if [[ -n "{{ tag }}" ]]; then
      args+=(--tag "{{ tag }}")
    fi
    python3 "${args[@]}"

# Create GitHub Release + upload .bin and checksums (requires: gh auth login)
# Positional: just release-publish esp32_s3_flipbuddy_0.1.2.bin v0.1.2
[group("Utils")]
release-publish firmware tag:
    #!/usr/bin/env bash
    set -euo pipefail
    command -v gh >/dev/null || { echo "gh CLI not found — install GitHub CLI and run: gh auth login"; exit 1; }
    test -f "{{ firmware }}" || { echo "Firmware file not found: {{ firmware }}"; exit 1; }
    just release-check
    just release-assets "{{ firmware }}" "{{ tag }}"
    side="{{ firmware }}.sha256"
    sums="$(dirname "{{ firmware }}")/SHA256SUMS"
    title="{{ tag }} — ESP32-S3 frozen firmware"
    notes="Frozen MicroPython image for ESP32-S3 Super Mini–class boards. Verify with the attached .sha256 or SHA256SUMS before flashing."
    assets=("{{ firmware }}" "$side")
    [[ -f "$sums" ]] && assets+=("$sums")
    echo "→ gh release create {{ tag }} ..."
    gh release create "{{ tag }}" \
      --title "$title" \
      --notes "$notes" \
      "${assets[@]}"
    echo "✓ Release {{ tag }} published. Update README download links if needed."

# Install git pre-commit hooks for this repo (host only; see CONTRIBUTING.md)
[group("Utils")]
hooks:
    pre-commit install
    @echo "pre-commit hooks installed. Commits will run gitleaks + FlipBuddy safety checks."
    @echo "Also run: just release-check   before a public release."
    @echo "Docs: CONTRIBUTING.md (builders: README.md only)."

# Run a basic syntax / compile check on the Python sources
[group("Utils")]
check:
    #!/usr/bin/env bash
    set -euo pipefail
    if [[ -x .venv/bin/ruff ]]; then
      .venv/bin/ruff check *.py
    elif command -v ruff >/dev/null 2>&1; then
      ruff check *.py
    elif [[ -x .venv/bin/python ]]; then
      .venv/bin/python -m py_compile *.py
    else
      python3 -m py_compile *.py
    fi

# Auto-fix lint issues + format with ruff (mpu6050.py:45-190 protected by fmt: off)
[group("Utils")]
fix:
    #!/usr/bin/env bash
    set -euo pipefail
    RUFF=ruff
    [[ -x .venv/bin/ruff ]] && RUFF=.venv/bin/ruff
    "$RUFF" check --fix *.py --ignore E501
    "$RUFF" format *.py
    echo "Ruff auto-fix + format complete (protected blocks were left untouched)"

# Format with ruff (respects # fmt: off for mpu6050.py lines 45-190)
[group("Utils")]
fmt:
    #!/usr/bin/env bash
    set -euo pipefail
    RUFF=ruff
    [[ -x .venv/bin/ruff ]] && RUFF=.venv/bin/ruff
    "$RUFF" format *.py
    echo "Ruff format complete (protected blocks were left untouched)"
