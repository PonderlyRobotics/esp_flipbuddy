#!/usr/bin/env python3
"""Host generator for SoftAP join password.

MicroPython will not invent ap_psk at boot. Run from the firmware repo root:

    just gen-ap-psk
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path

ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
PSK_LEN = 8
PSK_FILE = Path("ap_psk.json")


def generate_ap_psk(length: int = PSK_LEN) -> str:
    if length < 8:
        raise ValueError("WPA2 PSK must be at least 8 characters")
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def load_host_psk(root: Path | None = None) -> str | None:
    """Read host SoftAP password from ap_psk.json."""
    root = root or Path(".")
    json_path = root / PSK_FILE.name
    if not json_path.is_file():
        return None
    try:
        data = json.loads(json_path.read_text(encoding="utf-8") or "")
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict) or not data.get("ap_psk"):
        return None
    psk = str(data.get("ap_psk") or "").strip()
    return psk or None


def persist_ap_psk(psk: str, root: Path | None = None) -> Path:
    """Write ap_psk.json only. Never copy the join password into credentials.json."""
    root = root or Path(".")
    psk_path = root / PSK_FILE.name
    psk_path.write_text(json.dumps({"ap_psk": psk}, indent=2) + "\n", encoding="utf-8")
    return psk_path


def banner(psk: str, *, quiet: bool = False) -> str:
    lines = ["SoftAP join password:", "  " + psk]
    if not quiet:
        lines.append("Next: just put-ap-psk")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a host SoftAP join password")
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="password only (used by just fast-track / just diy)",
    )
    parser.add_argument(
        "--ensure",
        action="store_true",
        help="reuse existing ap_psk.json instead of generating",
    )
    args = parser.parse_args(argv)
    psk = load_host_psk() if args.ensure else None
    if not psk:
        psk = generate_ap_psk()
    persist_ap_psk(psk)
    print(banner(psk, quiet=args.quiet))
    return 0


if __name__ == "__main__":
    sys.exit(main())
