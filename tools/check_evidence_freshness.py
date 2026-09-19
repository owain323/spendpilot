"""Evidence freshness gate — evidence must not predate the code it describes.

Every artifact in docs/evidence/ claims to show the behavior of specific
code. If that code changed AFTER the evidence was generated, the evidence
is stale and the claim is unproven. This gate compares git commit
timestamps: an evidence file's last commit must be at least as recent as
the last commit touching any of its declared source paths.

Fix a failure by re-running:  python tools/refresh_evidence.py
then committing the refreshed artifacts together with (or after) the code.

Usage:  python tools/check_evidence_freshness.py     # exit 1 when stale
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# evidence artifact -> code paths whose change invalidates it. Scoped to the
# code that actually produces the artifact: benchmark metrics depend on the
# analysis function and the datasets, not on unrelated mcp_server modules.
ANALYSIS = ["benchmarks", "mcp_server/tools.py", "mcp_server/sample_data.py"]
SOURCES = {
    "docs/evidence/test-run.txt": ["tests", "mcp_server", "agent", "benchmarks", "tools"],
    "docs/evidence/benchmark-run.txt": ANALYSIS + ["tools/make_derived.py"],
    "docs/evidence/derived-metrics.json": ANALYSIS + ["tools/make_derived.py"],
    "docs/evidence/independent-metrics.json": ANALYSIS,
    "docs/evidence/mcp-roundtrip.txt": ["tools/mcp_roundtrip.py", "mcp_server"],
    "docs/evidence/mcp-handshake.txt": ["mcp_server/server.py"],
    "docs/evidence/e2e-flow.txt": ["tools/e2e_flow.py", "agent", "mcp_server", "web"],
}


def last_commit_ts(path: str) -> int | None:
    out = subprocess.run(
        ["git", "log", "-1", "--format=%ct", "--", path],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout.strip()
    return int(out) if out else None


def main() -> int:
    stale = []
    for evidence, sources in SOURCES.items():
        ev_ts = last_commit_ts(evidence)
        if ev_ts is None:
            stale.append(f"{evidence}: not committed (run tools/refresh_evidence.py and commit)")
            continue
        newest_src = 0
        newest_path = ""
        for src in sources:
            ts = last_commit_ts(src)
            if ts and ts > newest_src:
                newest_src, newest_path = ts, src
        if newest_src > ev_ts:
            stale.append(f"{evidence}: predates {newest_path} (evidence is stale — "
                         "re-run tools/refresh_evidence.py)")
    if stale:
        print("EVIDENCE FRESHNESS GATE FAILED:")
        print("\n".join(f"  {s}" for s in stale))
        return 1
    print(f"evidence freshness gate: OK ({len(SOURCES)} artifacts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
