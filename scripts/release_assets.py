#!/usr/bin/env python3
"""
Prepare frozen firmware assets for a GitHub Release (host-only).

Does NOT upload anything. Does NOT commit .bin files.

  1. SHA-256 the given .bin (and optional extra files)
  2. Write <name>.bin.sha256 next to each file
  3. Write/update SHA256SUMS in the same directory
  4. Print verify steps + suggested `gh release create` / tag commands

Usage:
  python3 scripts/release_assets.py esp32_s3_flipbuddy_0.1.1.bin
  python3 scripts/release_assets.py esp32_s3_flipbuddy_0.1.1.bin --tag v0.1.1
  python3 scripts/release_assets.py dist/*.bin --tag v0.1.1 --notes-file RELEASE_NOTES.md
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def write_sidecar(path: Path, digest: str) -> Path:
    side = path.with_name(path.name + ".sha256")
    # GNU coreutils style: "<hash>  <filename>" (two spaces)
    side.write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    return side


def write_sums(directory: Path, entries: list[tuple[str, str]]) -> Path:
    """entries: list of (digest, basename)"""
    sums = directory / "SHA256SUMS"
    lines = [f"{d}  {name}\n" for d, name in sorted(entries, key=lambda x: x[1])]
    sums.write_text("".join(lines), encoding="utf-8")
    return sums


def git_remote_https() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(ROOT), "remote", "get-url", "origin"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    if not out:
        return None
    # git@github.com:owner/repo.git → https://github.com/owner/repo
    if out.startswith("git@github.com:"):
        path = out.removeprefix("git@github.com:").removesuffix(".git")
        return f"https://github.com/{path}"
    if out.startswith("https://github.com/"):
        return out.removesuffix(".git")
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hash firmware .bin files for GitHub Releases (no git commit)."
    )
    parser.add_argument(
        "bins",
        nargs="+",
        type=Path,
        help="Path(s) to firmware .bin files (must exist; not committed to git)",
    )
    parser.add_argument(
        "--tag",
        default="",
        help="Release tag for suggested commands (e.g. v0.1.1)",
    )
    parser.add_argument(
        "--title",
        default="",
        help="Release title (default: derived from tag)",
    )
    parser.add_argument(
        "--notes-file",
        type=Path,
        default=None,
        help="Optional release notes markdown for gh release create",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Only print digests; do not write .sha256 / SHA256SUMS",
    )
    args = parser.parse_args()

    bins: list[Path] = []
    for p in args.bins:
        path = p.expanduser().resolve()
        if not path.is_file():
            print(f"error: not a file: {path}", file=sys.stderr)
            return 1
        if path.suffix.lower() != ".bin":
            print(f"WARN: expected .bin extension: {path.name}", file=sys.stderr)
        bins.append(path)

    entries: list[tuple[str, str]] = []
    print("SHA-256 digests")
    print("---------------")
    for path in bins:
        digest = sha256_file(path)
        entries.append((digest, path.name))
        print(f"{digest}  {path}")
        if not args.print_only:
            side = write_sidecar(path, digest)
            print(f"  → wrote {side}")

    # SHA256SUMS next to first bin (common case: all in same dir)
    dirs = {p.parent for p in bins}
    if not args.print_only:
        for d in dirs:
            dir_entries = [(dig, name) for dig, name in entries if (d / name).is_file()]
            sums = write_sums(d, dir_entries)
            print(f"  → wrote {sums}")

    print()
    print("Verify (after download):")
    for dig, name in entries:
        print(f"  sha256sum -c {name}.sha256")
    print("  # or: sha256sum -c SHA256SUMS")

    print()
    print("Do NOT commit .bin files. Attach them to a GitHub Release instead.")
    print("  just release-check")
    tag = args.tag.strip()
    if not tag:
        # try infer vX.Y.Z from first filename
        name = bins[0].stem  # esp32_s3_flipbuddy_0.1.1
        parts = name.split("_")
        if parts and parts[-1][0].isdigit():
            tag = "v" + parts[-1]
        else:
            tag = "vX.Y.Z"
    title = args.title.strip() or f"{tag} — ESP32-S3 frozen firmware"
    remote = git_remote_https() or "https://github.com/<this-repo>"

    print()
    print("Suggested tag (source that built this image):")
    print(f"  git tag -a {tag} -m \"FlipBuddy firmware {tag}\"")
    print(f"  git push origin {tag}")

    assets = []
    for path in bins:
        assets.append(str(path))
        if not args.print_only:
            assets.append(str(path.with_name(path.name + ".sha256")))
    for d in dirs:
        sums = d / "SHA256SUMS"
        if sums.is_file() and str(sums) not in assets:
            assets.append(str(sums))

    notes = ""
    if args.notes_file:
        notes = f' --notes-file "{args.notes_file}"'
    else:
        notes = f' --notes "Frozen ESP32-S3 image. Verify with the attached .sha256 / SHA256SUMS."'

    print()
    print("Suggested GitHub Release (requires gh auth):")
    print(
        "  gh release create "
        + tag
        + f' --title "{title}"'
        + notes
        + " "
        + " ".join(f'"{a}"' for a in assets)
    )

    print()
    print("Download URL pattern:")
    print(f"  {remote}/releases/download/{tag}/<asset-name>")
    print(f"  Releases page: {remote}/releases")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
