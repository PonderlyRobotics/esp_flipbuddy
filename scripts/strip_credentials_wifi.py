#!/usr/bin/env python3
"""Strip house Wi-Fi from recovery credentials.json (identity only).

Used by `just put-credentials` so SSID/password never land on cube flash.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def strip_house_wifi(data: object) -> dict:
    if not isinstance(data, dict):
        raise ValueError("credentials.json is not an object")
    out = dict(data)
    out.pop("wifi", None)
    out.pop("ssid", None)
    out.pop("password", None)
    return out


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: strip_credentials_wifi.py IN.json OUT.json", file=sys.stderr)
        return 2
    src, dst = Path(args[0]), Path(args[1])
    data = json.loads(src.read_text(encoding="utf-8"))
    out = strip_house_wifi(data)
    dst.write_text(json.dumps(out) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
