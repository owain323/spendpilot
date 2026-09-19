"""Fail-closed CJK guard for SpendLatch.

The public repository must contain zero CJK characters (Chinese, Japanese
syllabaries, Hangul, and CJK compatibility forms). Any match fails the gate.

Usage:
    python check_no_cjk.py --staged   # pre-commit: scan files staged for commit
    python check_no_cjk.py --all      # pre-push: scan every git-tracked file

Fail-closed: if git or python misbehave, the gate refuses (non-zero exit),
never silently passes.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Hiragana/Katakana, CJK Extension A, CJK Unified, Hangul, CJK Compatibility.
CJK_RANGES = (
    (0x3040, 0x30FF),
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xAC00, 0xD7AF),
    (0xF900, 0xFAFF),
)


def is_cjk(ch: str) -> bool:
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in CJK_RANGES)


def git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, encoding="utf-8"
    )
    if proc.returncode != 0:
        print(f"check_no_cjk: git {' '.join(args)} failed:\n{proc.stderr}", file=sys.stderr)
        raise SystemExit(1)  # fail closed
    return proc.stdout


def files_to_scan(mode: str) -> list[str]:
    if mode == "--staged":
        out = git("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    else:
        out = git("ls-files")
    return [line for line in out.splitlines() if line.strip()]


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in ("--staged", "--all"):
        print("usage: python check_no_cjk.py --staged|--all", file=sys.stderr)
        return 1

    failures: list[str] = []
    scanned = 0
    for rel in files_to_scan(mode):
        path = REPO / rel
        if not path.is_file():
            continue
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue  # binary asset, nothing to scan
        scanned += 1
        for lineno, line in enumerate(text.splitlines(), 1):
            if any(is_cjk(c) for c in line):
                failures.append(f"{rel}:{lineno}: CJK character found")

    if failures:
        print("CJK GATE FAILED — the public repo must stay pure English:")
        print("\n".join(f"  {f}" for f in failures[:50]))
        if len(failures) > 50:
            print(f"  ... and {len(failures) - 50} more")
        return 1

    print(f"cjk gate: OK ({scanned} files scanned, mode={mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
