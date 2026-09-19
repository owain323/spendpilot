"""Quality gate: tests, sealed benchmark, repo integrity, language scan.

Everything that ships to the hackathon — code, comments, README — must be
pure English. One stray CJK character fails the gate.

Usage:  python run_checks.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCAN_SUFFIXES = {".py", ".md", ".html", ".css", ".js", ".toml", ".txt", ".json"}
SKIP_DIRS = {".git", ".venv", "__pycache__", "data", ".pytest_cache", ".mypy_cache", "results", "evidence"}


def is_cjk(ch: str) -> bool:
    code = ord(ch)
    return 0x3040 <= code <= 0x30FF or 0x4E00 <= code <= 0x9FFF or 0xAC00 <= code <= 0xD7AF


# Emoji + typographic punctuation + ASCII-art box drawing used in docs/UI copy.
ALLOWED_NON_ASCII = set("🎙⚠️🚨⚡🔍📉🎯🤫—–·’'““”│▼▲─├└┐┌┘┤┬┴┼≥→≤✅⬜✓🎤🔊🔇✗")


def check_language() -> bool:
    failures = []
    for path in sorted(ROOT.rglob("*")):
        if path.is_dir() or path.suffix not in SCAN_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            if any(is_cjk(c) for c in line):
                failures.append(f"{path.relative_to(ROOT)}:{lineno}: CJK character found")
            bad = {c for c in line if ord(c) > 127 and c not in ALLOWED_NON_ASCII}
            if bad:
                failures.append(f"{path.relative_to(ROOT)}:{lineno}: non-ASCII {sorted(bad)}")
    if failures:
        print("LANGUAGE GATE FAILED:")
        print("\n".join(f"  {f}" for f in failures))
        return False
    print("language gate: OK (pure English)")
    return True


def run(step: str, argv: list[str]) -> bool:
    print(f"== {step} ==")
    return subprocess.run(argv, cwd=ROOT).returncode == 0


def main() -> int:
    steps = [
        ("pytest", [sys.executable, "-m", "pytest", "tests", "-q", "--ignore=tests/test_mcp_roundtrip.py"]),
        ("sealed benchmark", [sys.executable, "benchmarks/run.py"]),
        ("MCP roundtrip over the wire", [sys.executable, "tools/mcp_roundtrip.py"]),
        ("integrity manifest", [sys.executable, "tools/make_sha256sums.py", "--check"]),
    ]
    for step, argv in steps:
        if not run(step, argv):
            print(f"GATE FAILED at: {step}")
            return 1
    print("== language gate ==")
    if not check_language():
        return 1
    print("ALL GATES GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
