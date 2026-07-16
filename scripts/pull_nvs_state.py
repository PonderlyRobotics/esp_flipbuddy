#!/usr/bin/env python3
"""
Pull Config + Tracker JSON from the ESP32 NVS partition to the host.

Host-only. Does not import project MicroPython modules.

  1. Deinit soft WDT (scheduler_wd / Timer 1)
  2. Write NVS blobs to temp files on the device filesystem
  3. Copy those files to the host with mpremote
  4. Delete the temp files on the device
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Temp names on device FS only (removed after copy). Must match models NVS layout.
REMOTE_FILES = (
    ("config", "cfg", "startup_config.json"),
    ("tracker", "trk", "saved_tracker.json"),
)

# Runs in-memory via `mpremote run` (not installed as a permanent module).
DEVICE_SCRIPT = r"""
from machine import Timer

# main.py: scheduler_wd = Timer(TIMER_NUM) with TIMER_NUM == 1
try:
    import sys as _sys

    for _name in ("__main__", "main"):
        _mod = _sys.modules.get(_name)
        if _mod is not None and hasattr(_mod, "scheduler_wd"):
            _mod.scheduler_wd.deinit()
except Exception:
    pass
try:
    Timer(1).deinit()
except Exception:
    pass

from esp32 import NVS

def dump(namespace, key, path):
    nvs = NVS(namespace)
    buf = bytearray(8192)
    try:
        size = nvs.get_blob(key, buf)
    except OSError:
        size = 0
    with open(path, "w") as f:
        f.write(buf[:size].decode("utf-8") if size else "{}")
    print("wrote", path, size if size else 0, "bytes")

dump("config", "cfg", "startup_config.json")
dump("tracker", "trk", "saved_tracker.json")
"""


def _mpremote() -> list[str]:
    """Console script preferred — `python -m mpremote` breaks on repo-root http.py."""
    sibling = Path(sys.executable).resolve().parent / "mpremote"
    if sibling.is_file() and os.access(sibling, os.X_OK):
        return [str(sibling)]
    which = shutil.which("mpremote")
    if which:
        return [which]
    return [sys.executable, "-m", "mpremote"]


def _run_mpremote(port: str, *args: str) -> subprocess.CompletedProcess[str]:
    cmd = [*_mpremote(), "connect", port, "resume", *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        # Neutral cwd if we ever fall back to `python -m mpremote`
        cwd=tempfile.gettempdir(),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dump config + tracker from device NVS to local JSON."
    )
    parser.add_argument(
        "out_dir",
        nargs="?",
        default=".",
        help="Directory for startup_config.json and saved_tracker.json (default: .)",
    )
    parser.add_argument(
        "--port",
        default=os.environ.get("AMPY_PORT", "/dev/ttyACM0"),
        help="Serial port (default: AMPY_PORT or /dev/ttyACM0)",
    )
    args = parser.parse_args()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        "w", suffix="_flipbuddy_nvs_dump.py", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(DEVICE_SCRIPT)
        script_path = tmp.name

    try:
        print(f"→ dump NVS → device FS on {args.port}")
        dump = _run_mpremote(args.port, "run", script_path)
        if dump.returncode != 0:
            sys.stderr.write(dump.stdout or "")
            sys.stderr.write(dump.stderr or "")
            print(
                f"error: mpremote dump failed (exit {dump.returncode}). "
                "Is the device connected, and is mpremote installed (uv sync)?",
                file=sys.stderr,
            )
            return dump.returncode or 1
        if dump.stdout:
            print(dump.stdout.rstrip())

        for _ns, _key, name in REMOTE_FILES:
            local = out_dir / name
            print(f"→ cp :{name} → {local}")
            cp = _run_mpremote(args.port, "cp", f":{name}", str(local))
            if cp.returncode != 0:
                sys.stderr.write(cp.stdout or "")
                sys.stderr.write(cp.stderr or "")
                print(f"error: failed to copy {name} from device", file=sys.stderr)
                return cp.returncode or 1
    finally:
        # Always try to remove temp dumps from the device
        rm = _run_mpremote(
            args.port,
            "exec",
            "import os\n"
            "for n in ('startup_config.json', 'saved_tracker.json'):\n"
            "    try:\n"
            "        os.remove(n)\n"
            "        print('removed', n)\n"
            "    except OSError:\n"
            "        pass\n",
        )
        if rm.stdout:
            print(rm.stdout.rstrip())
        if rm.returncode != 0:
            sys.stderr.write(rm.stderr or "")
            print("WARN: could not remove temp files on device", file=sys.stderr)
        try:
            os.unlink(script_path)
        except OSError:
            pass

    print("✓ Temp files removed from device FS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
