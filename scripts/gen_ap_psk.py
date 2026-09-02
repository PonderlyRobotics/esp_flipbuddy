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


def compact_ap_psk(psk: str) -> str:
    return "".join(ch.upper() for ch in str(psk or "") if ch.upper() in ALPHABET)


def format_ap_psk_display(psk: str) -> str:
    """XXXX XXXX for reading. Join Wi-Fi without the space."""
    compact = compact_ap_psk(psk)
    if len(compact) == PSK_LEN:
        return f"{compact[:4]} {compact[4:]}"
    return compact or str(psk or "")


def load_host_psk(root: Path | None = None) -> str | None:
    """Read an 8-character host SoftAP password from ap_psk.json.

    Longer leftovers (old generators) are ignored so --ensure can replace them.
    """
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
    compact = compact_ap_psk(str(data.get("ap_psk") or ""))
    if len(compact) != PSK_LEN:
        return None
    return compact


def persist_ap_psk(psk: str, root: Path | None = None) -> Path:
    """Write ap_psk.json only. Never copy the join password into credentials.json."""
    root = root or Path(".")
    psk_path = root / PSK_FILE.name
    psk_path.write_text(json.dumps({"ap_psk": psk}, indent=2) + "\n", encoding="utf-8")
    return psk_path


def banner(psk: str, *, quiet: bool = False) -> str:
    shown = format_ap_psk_display(psk)
    lines = ["SoftAP join password:", "  " + shown, "  Spaces are only for reading."]
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
    parser.add_argument(
        "--length",
        type=int,
        default=PSK_LEN,
        help="password length (default 8, min 8 for WPA2)",
    )
    args = parser.parse_args(argv)
    psk = load_host_psk() if args.ensure else None
    if not psk:
        psk = generate_ap_psk(args.length)
    persist_ap_psk(psk)
    print(banner(psk, quiet=args.quiet))
    return 0


if __name__ == "__main__":
    sys.exit(main())
