#!/usr/bin/env python3
"""
FlipBuddy repo safety checks for public release.

Modes:
  pre-commit (default): scan paths given as CLI args (staged files).
  --full:               full pre-release audit of tracked tree + history hints.

This script is host-only. It must not import project MicroPython modules
(project-root http.py would shadow the stdlib).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Filenames that must never be committed
FORBIDDEN_NAME_RE = re.compile(
    r"(?i)("
    r"^credentials\.json$|"
    r"^credentials[_-].*\.json$|"
    r".*credentials.*\.json$|"
    r"^\.env$|"
    r"^\.env\..+|"
    r".*\.pem$|"
    r"^id_rsa|"
    r"^secrets\."
    r")"
)

# Personal absolute home paths in tracked content
HOME_PATH_RE = re.compile(
    r"(?i)(/home/[a-z_][a-z0-9_-]{0,31}|/Users/[A-Za-z0-9._-]+|C:\\Users\\[A-Za-z0-9._-]+)"
)

# High-signal secret-ish patterns (conservative; gitleaks covers more)
SECRET_LINE_RES: list[tuple[str, re.Pattern[str]]] = [
    (
        "private-key",
        re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----"),
    ),
    (
        "aws-access-key",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    ),
    (
        "github-token",
        re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
    ),
    (
        "generic-bearer",
        re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*\b"),
    ),
    (
        "device_token_assignment",
        re.compile(
            r"""(?i)device_token["']?\s*[:=]\s*["']([A-Za-z0-9_\-]{32,})["']"""
        ),
    ),
    (
        "wifi_password_assignment",
        re.compile(
            r"""(?i)(?:password|wifi_password|passwd)\s*[:=]\s*["']([^"']{8,})["']"""
        ),
    ),
]

# Paths / snippets allowed even if they match soft patterns
ALLOW_PATH_SUBSTR = (
    "test_fsm.py",
    "README.md",
    "scripts/release_check.py",
    ".pre-commit-config.yaml",
    "LICENSE",
)

PLACEHOLDER_PASSWORDS = {
    "secret",
    "password",
    "yourpassword",
    "changeme",
    "example",
    "xxxxxxxx",
    "...",
}

TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".toml",
    ".yaml",
    ".yml",
    ".dot",
    ".just",
    "",  # justfile has no suffix
}
TEXT_NAMES = {
    "justfile",
    "Justfile",
    "LICENSE",
    "LICENSE-HARDWARE",
    ".gitignore",
    ".pre-commit-config.yaml",
    "mise.toml",
    "pyproject.toml",
    "fsm.dot",
}


def _run(cmd: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


def git_ls_files() -> list[Path]:
    cp = _run(["git", "ls-files", "-z"])
    if cp.returncode != 0:
        print("ERROR: git ls-files failed:", cp.stderr.strip(), file=sys.stderr)
        sys.exit(2)
    parts = [p for p in cp.stdout.split("\0") if p]
    return [ROOT / p for p in parts]


def git_staged_files() -> list[Path]:
    cp = _run(["git", "diff", "--cached", "--name-only", "-z"])
    if cp.returncode != 0:
        return []
    parts = [p for p in cp.stdout.split("\0") if p]
    return [ROOT / p for p in parts]


def is_textish(path: Path) -> bool:
    name = path.name
    if name in TEXT_NAMES:
        return True
    if path.suffix.lower() in TEXT_SUFFIXES:
        return True
    # allow extensionless small text files
    return path.suffix == "" and path.is_file() and path.stat().st_size < 200_000


def allowed_path(path: Path) -> bool:
    rel = str(path.relative_to(ROOT)).replace("\\", "/")
    return any(a in rel for a in ALLOW_PATH_SUBSTR)


def read_text(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError as e:
        print(f"WARN: cannot read {path}: {e}", file=sys.stderr)
        return None
    if b"\0" in data[:4096]:
        return None  # binary
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return data.decode("latin-1")
        except UnicodeDecodeError:
            return None


def check_forbidden_names(paths: list[Path], findings: list[str]) -> None:
    for path in paths:
        try:
            rel = path.resolve().relative_to(ROOT.resolve())
        except ValueError:
            rel = Path(path.name)
        name = path.name
        if FORBIDDEN_NAME_RE.match(name):
            findings.append(
                f"FORBIDDEN file name staged/tracked: {rel} "
                f"(credentials / env / keys must never be committed)"
            )


def check_text_content(paths: list[Path], findings: list[str]) -> None:
    for path in paths:
        if not path.is_file() or not is_textish(path):
            continue
        text = read_text(path)
        if text is None:
            continue
        rel = path.relative_to(ROOT)
        allow = allowed_path(path)

        for m in HOME_PATH_RE.finditer(text):
            line_no = text.count("\n", 0, m.start()) + 1
            findings.append(
                f"personal home path in {rel}:{line_no}: {m.group(0)!r} "
                f"(use portable paths before public release)"
            )

        if allow:
            continue

        for label, cre in SECRET_LINE_RES:
            for m in cre.finditer(text):
                # Soften wifi/password false positives on placeholders
                if label == "wifi_password_assignment":
                    val = m.group(1).strip().lower()
                    if val in PLACEHOLDER_PASSWORDS or val.startswith("your"):
                        continue
                if label == "device_token_assignment":
                    val = m.group(1)
                    if val in {"tok456", "test123", "dev123"} or set(val) <= {"x", "0", "."}:
                        continue
                line_no = text.count("\n", 0, m.start()) + 1
                findings.append(
                    f"possible secret ({label}) in {rel}:{line_no}"
                )


def check_ondisk_secret_files(findings: list[str], warnings: list[str]) -> None:
    """Warn about real credential files sitting in the worktree (should stay ignored)."""
    suspects = sorted(ROOT.glob("credentials*.json")) + sorted(ROOT.glob(".env*"))
    for path in suspects:
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        # Ensure git ignores them
        cp = _run(["git", "check-ignore", "-q", str(rel)])
        if cp.returncode == 0:
            warnings.append(
                f"local secret file present but ignored (OK if not force-added): {rel}"
            )
        else:
            findings.append(
                f"local secret file is NOT ignored by git: {rel} — add to .gitignore immediately"
            )


def check_prod_secrets_not_in_tracked(findings: list[str]) -> None:
    """If a local credentials*.json exists, ensure its values are not in tracked files."""
    tracked = git_ls_files()
    tracked_bytes: list[tuple[Path, bytes]] = []
    for p in tracked:
        if not p.is_file():
            continue
        try:
            tracked_bytes.append((p, p.read_bytes()))
        except OSError:
            continue

    for cred_path in sorted(ROOT.glob("credentials*.json")):
        try:
            data = json.loads(cred_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        needles: list[tuple[str, str]] = []
        for key in ("device_token", "device_id"):
            val = data.get(key)
            if isinstance(val, str) and len(val) >= 16:
                needles.append((key, val))
        wifi = data.get("wifi") or {}
        if isinstance(wifi, dict):
            for _name, cfg in wifi.items():
                if not isinstance(cfg, dict):
                    continue
                for k in ("ssid", "password"):
                    val = cfg.get(k)
                    if isinstance(val, str) and len(val) >= 4:
                        needles.append((f"wifi.{k}", val))

        for label, val in needles:
            raw = val.encode("utf-8")
            for path, blob in tracked_bytes:
                if raw in blob:
                    findings.append(
                        f"value from local {cred_path.name} ({label}) found in tracked "
                        f"{path.relative_to(ROOT)} — DO NOT RELEASE"
                    )


def check_history_home_paths(findings: list[str], warnings: list[str]) -> None:
    """Scan git history for personal home paths (release-time concern)."""
    cp = _run(
        [
            "git",
            "log",
            "-p",
            "--all",
            "-G",
            r"/home/[a-zA-Z]|/Users/[A-Za-z]|C:\\\\Users\\\\",
            "--",
            ".",
        ]
    )
    if cp.returncode != 0:
        warnings.append("could not scan git history for home paths")
        return
    # Only look at added lines in diffs for current warning
    hits: set[str] = set()
    for line in cp.stdout.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        m = HOME_PATH_RE.search(line)
        if m:
            hits.add(m.group(0))
    if hits:
        warnings.append(
            "git history still contains personal home path(s): "
            + ", ".join(sorted(hits))
            + " — consider squash/filter before first public push"
        )


def run_gitleaks(full: bool, warnings: list[str], findings: list[str]) -> None:
    gitleaks = _run(["bash", "-lc", "command -v gitleaks"])
    if gitleaks.returncode != 0 or not gitleaks.stdout.strip():
        warnings.append(
            "gitleaks not installed on PATH — skipped CLI scan "
            "(pre-commit hook still installs its own binary when hooks run)"
        )
        return

    config = ROOT / ".gitleaks.toml"
    cmd = ["gitleaks", "detect", "--no-banner", "--redact", "-v"]
    if config.is_file():
        cmd.extend(["--config", str(config)])
    if full:
        cmd.append("--source")
        cmd.append(str(ROOT))
    else:
        # staged changes only
        cmd.append("--source")
        cmd.append(str(ROOT))
        cmd.append("--log-opts=--cached")

    cp = _run(cmd)
    if cp.returncode == 0:
        return
    if cp.returncode == 1:
        # leaks found
        out = (cp.stdout or "") + (cp.stderr or "")
        findings.append("gitleaks reported possible secrets:\n" + out.strip())
    else:
        warnings.append(
            f"gitleaks exited {cp.returncode}: {(cp.stderr or cp.stdout).strip()}"
        )


def print_report(findings: list[str], warnings: list[str], title: str) -> int:
    print(f"=== {title} ===")
    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(f"  ⚠  {w}")
    if findings:
        print("\nFailures:")
        for f in findings:
            print(f"  ✗  {f}")
        print(f"\n{len(findings)} failure(s). Do not release/commit until fixed.")
        return 1
    print("\n✓ No blocking issues found.")
    if warnings:
        print(f"  ({len(warnings)} warning(s) — review before public release)")
    return 0


def mode_pre_commit(paths: list[str]) -> int:
    findings: list[str] = []
    warnings: list[str] = []
    files = [Path(p).resolve() for p in paths]
    # Only consider paths under repo
    files = [p for p in files if str(p).startswith(str(ROOT)) and p.exists()]
    check_forbidden_names(files, findings)
    check_text_content(files, findings)
    return print_report(findings, warnings, "pre-commit safety check")


def mode_full() -> int:
    findings: list[str] = []
    warnings: list[str] = []

    tracked = git_ls_files()
    staged = git_staged_files()

    print(f"Tracked files: {len(tracked)}")
    print(f"Staged files:  {len(staged)}")

    check_forbidden_names(tracked + staged, findings)
    check_text_content(tracked, findings)
    check_ondisk_secret_files(findings, warnings)
    check_prod_secrets_not_in_tracked(findings)
    check_history_home_paths(findings, warnings)
    run_gitleaks(full=True, warnings=warnings, findings=findings)

    # Release hygiene notes
    if not (ROOT / "LICENSE").is_file():
        findings.append("missing LICENSE")
    if not (ROOT / "LICENSE-HARDWARE").is_file():
        warnings.append("LICENSE-HARDWARE not found")
    bins = list(ROOT.glob("esp32_s3_flipbuddy_*.bin"))
    if not bins:
        warnings.append(
            "no local esp32_s3_flipbuddy_*.bin (OK — publish via GitHub Releases, not git)"
        )

    return print_report(findings, warnings, "full release safety check")


def main(argv: list[str] | None = None) -> int:
    # Keep project root off sys.path[0] weirdness: run from scripts/
    os.chdir(ROOT)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--full",
        action="store_true",
        help="Full pre-release audit (tracked tree, history, local secrets)",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Paths to check (pre-commit passes staged files here)",
    )
    args = parser.parse_args(argv)

    if args.full:
        return mode_full()
    if not args.paths:
        # If no paths, check staged files (handy for manual runs)
        staged = git_staged_files()
        if not staged:
            print("No paths given and nothing staged — nothing to check.")
            return 0
        return mode_pre_commit([str(p) for p in staged])
    return mode_pre_commit(args.paths)


if __name__ == "__main__":
    sys.exit(main())
