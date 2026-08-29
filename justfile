# FlipBuddy ESP32 MicroPython firmware
#
# Polished open-source release.
#
# Typical user flow (Super Mini fast track):
#   1. Download frozen .bin from GitHub Releases + verify .sha256
#   2. just flash-firmware esp32_s3_flipbuddy_0.1.5.bin
#   3. just fast-track   # main.py + ap_psk, then hard reset (does NOT upload credentials.json)
#   4. Join FlipBuddy-XXXX with the printed password.
# DIY (stock MicroPython): just flash-firmware <stock.bin> && just diy
# JSON recovery (advanced): just put-credentials
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
device_py := "main.py ap_session.py models.py mpu6050.py rgb.py http.py network_helper.py credentials.py util.py ap_mode.py pairing.py pairing_portal.py"
# AST-stripped modules written by `just clean-frozen` (no main.py — kept full-size / editable)
cleaned_dir := "/tmp/flipbuddy_cleaned"
cleaned_py := "models.py mpu6050.py rgb.py http.py network_helper.py credentials.py util.py ap_mode.py ap_session.py pairing.py pairing_portal.py"

# stderr spinner while a quiet command runs (mpremote cp/exec/reset).
wait_spin := '''
wait_spin() {
  if [[ ! -t 2 ]]; then
    "$@" >/dev/null
    return
  fi
  "$@" >/dev/null &
  local pid=$! i=0 rc=0
  local sp='|/-\'
  while kill -0 "$pid" 2>/dev/null; do
    printf '\r  waiting %s' "${sp:$((i % 4)):1}" >&2
    i=$((i + 1))
    sleep 0.1
  done
  wait "$pid" || rc=$?
  printf '\r\033[K' >&2
  return "$rc"
}
'''

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
    @mpremote connect {{ usb_dev }} cp {{ device_py }} : >/dev/null
    @echo "uploaded device sources"

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
    @mpremote connect {{ usb_dev }} cp main.py : >/dev/null
    @echo "uploaded main.py"

# Print a random SoftAP join password (does not talk to the cube).
# MicroPython will not invent ap_psk at boot. Write this down, then just put-ap-psk.
[group("Device")]
gen-ap-psk:
    python3 scripts/gen_ap_psk.py

# Copy ap_psk.json onto the cube (migrates to NVS on boot). Run after gen-ap-psk.
[group("Device")]
put-ap-psk:
    @test -f ap_psk.json || (echo "ap_psk.json not found. Run: just gen-ap-psk" && exit 1)
    @mpremote connect {{ usb_dev }} cp ap_psk.json : >/dev/null
    @echo "uploaded ap_psk.json"

# Reflash / unpair: BOOT + RST, then erase-flash.
[group("Device")]
bootloader-help:
    @echo "OSS unpair / reflash (NVS is wiped):"
    @echo "  1. Hold BOOT, tap RST, release BOOT (download mode)."
    @echo "  2. just flash-firmware   # erase-flash + write image"
    @echo "  3. just gen-ap-psk && just put-ap-psk"
    @echo "  4. Power-cycle. Pairing SoftAP uses the new password."

# Upload credentials.json (Advanced / recovery). Identity only → NVS on first boot.
# House Wi-Fi in that file is stripped before copy (NVS / pairing SoftAP only).
# Not part of just fast-track / just diy — those would skip pairing SoftAP.
[group("Device")]
put-credentials:
    #!/usr/bin/env bash
    set -euo pipefail
    test -f credentials.json || { echo "credentials.json not found next to justfile"; exit 1; }
    tmp="$(mktemp)"
    python3 -c '
import json, sys
src, dst = sys.argv[1], sys.argv[2]
data = json.load(open(src, encoding="utf-8"))
if not isinstance(data, dict):
    sys.exit("credentials.json is not an object")
data.pop("wifi", None)
data.pop("ssid", None)
data.pop("password", None)
json.dump(data, open(dst, "w", encoding="utf-8"))
' credentials.json "$tmp"
    mpremote connect {{ usb_dev }} cp "$tmp" :credentials.json
    rm -f "$tmp"
    echo "credentials.json uploaded (recovery; house Wi-Fi stripped). Pairing SoftAP will not start."

[group("Device")]
put-credentials-ampy:
    #!/usr/bin/env bash
    set -euo pipefail
    test -f credentials.json || { echo "credentials.json not found next to justfile"; exit 1; }
    tmp="$(mktemp)"
    python3 -c '
import json, sys
src, dst = sys.argv[1], sys.argv[2]
data = json.load(open(src, encoding="utf-8"))
if not isinstance(data, dict):
    sys.exit("credentials.json is not an object")
data.pop("wifi", None)
data.pop("ssid", None)
data.pop("password", None)
json.dump(data, open(dst, "w", encoding="utf-8"))
' credentials.json "$tmp"
    ampy --port {{ usb_dev }} put "$tmp" credentials.json
    rm -f "$tmp"
    echo "credentials.json uploaded (ampy, recovery; house Wi-Fi stripped)."

# Write NVS api_url from a full https:// base (no aliases).
# Optional default: FLIPBUDDY_API_URL in gitignored mise.local.toml.
[group("Device")]
put-api-url api_url:
    #!/usr/bin/env bash
    set -euo pipefail
    {{ wait_spin }}
    raw="{{ api_url }}"
    raw="${raw#"${raw%%[![:space:]]*}"}"
    raw="${raw%"${raw##*[![:space:]]}"}"
    if [[ ! "$raw" =~ ^https://[A-Za-z0-9._~:/=-]+$ ]]; then
      echo "error: pass a full https:// API base (no aliases)" >&2
      exit 1
    fi
    url="${raw%/}/"
    printf '%s\n' "$url" > api_url.txt
    wait_spin mpremote connect "{{ usb_dev }}" cp api_url.txt :
    wait_spin mpremote connect "{{ usb_dev }}" exec "from credentials import load_credentials,_write_to_nvs;u=open('api_url.txt').read().strip().rstrip('/')+'/';d=load_credentials() or {};d['api_url']=u;_write_to_nvs(d)"
    echo "api $url"

# Fast track FS deploy after flashing the frozen Release .bin.
# main.py + SoftAP join password. Does **not** upload credentials.json.
# Optional https API base: just fast-track https://host/v1/api/
[group("Device")]
fast-track api_url=env("FLIPBUDDY_API_URL", ""):
    #!/usr/bin/env bash
    set -euo pipefail
    {{ wait_spin }}
    port="{{ usb_dev }}"
    echo "→ fast-track $port"
    wait_spin mpremote connect "$port" cp main.py :
    python3 scripts/gen_ap_psk.py --ensure --quiet
    wait_spin mpremote connect "$port" cp ap_psk.json :
    if [[ -n "{{ api_url }}" ]]; then
      just put-api-url "{{ api_url }}"
    fi
    # Hard reset (not soft-reset): drops stale USB-face SoftAP mark so pairing runs.
    wait_spin mpremote connect "$port" reset
    echo "reset. Join FlipBuddy-XXXX with the password above."

# DIY FS deploy: all firmware modules + SoftAP PSK (stock MicroPython / full sources).
# Does **not** upload credentials.json. Recovery: just put-credentials.
# Optional https API base: just diy https://host/v1/api/
[group("Device")]
diy api_url=env("FLIPBUDDY_API_URL", ""):
    #!/usr/bin/env bash
    set -euo pipefail
    {{ wait_spin }}
    port="{{ usb_dev }}"
    echo "→ diy $port"
    wait_spin mpremote connect "$port" cp {{ device_py }} :
    python3 scripts/gen_ap_psk.py --ensure --quiet
    wait_spin mpremote connect "$port" cp ap_psk.json :
    if [[ -n "{{ api_url }}" ]]; then
      just put-api-url "{{ api_url }}"
    fi
    # Hard reset (not soft-reset): drops stale USB-face SoftAP mark so pairing runs.
    wait_spin mpremote connect "$port" reset
    echo "reset. Join FlipBuddy-XXXX with the password above."

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
flash-firmware firmware="esp32_s3_flipbuddy_0.1.5.bin":
    # Examples:
    #   just flash-firmware esp32_s3_flipbuddy_0.1.5.bin   # from GitHub Releases
    #   just flash-firmware ESP32_GENERIC_S3-....bin       # stock MicroPython
    #
    # Frozen FlipBuddy images are on GitHub Releases (not committed). Verify .sha256 then flash.
    # After the frozen image: main.py + ap_psk.json on the FS (just fast-track).
    # JSON recovery: just put-credentials. Stock MP: https://micropython.org/download/ESP32_GENERIC_S3/
    @test -f "{{ firmware }}" || (echo "Firmware file not found: {{ firmware }}" && echo "Download the Release asset first (see README / CONTRIBUTING)." && exit 1)
    @echo "!!! This will ERASE the entire flash on {{ usb_dev }}"
    @echo "!!! NVS (token, wifi, ap_psk) is wiped. After flash: just gen-ap-psk && just put-ap-psk"
    @echo "→ Flashing {{ firmware }} ..."
    esptool --chip esp32{{ esp_chip }} --port {{ usb_dev }} erase-flash
    esptool --chip esp32{{ esp_chip }} --port {{ usb_dev }} --baud 460800 write-flash 0 {{ firmware }}

# =============================================================================
# ADVANCED
# =============================================================================
# Tools for building smaller custom frozen firmware (requires full MicroPython + IDF).
# Pairing helpers must be frozen into a Release image so pairing works without
# filesystem pairing_portal.py. This public justfile does not run Docker IDF.

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
# Positional args only: just release-assets esp32_s3_flipbuddy_0.1.3.bin v0.1.3
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
# Positional: just release-publish esp32_s3_flipbuddy_0.1.3.bin v0.1.3
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
