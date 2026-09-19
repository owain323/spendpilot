"""Integration test: the MCP roundtrip probe as a gated test.

Spawns the real server subprocess and drives it with the official MCP client
over Streamable HTTP — the runtime-technology-hook proof runs inside pytest.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_mcp_roundtrip_over_the_wire():
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "mcp_roundtrip.py")],
        capture_output=True, text=True, cwd=ROOT, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "MCP_ROUNDTRIP_OK" in result.stdout
    # the protocol hook must be the version the Alexa+ track requires
    assert "2025-11-25" in result.stdout
    # all 13 tools must be listed over the wire
    assert "13 tools" in result.stdout
    # the MCP Apps ui:// resource must be served with the mcp-app profile
    assert "ui://spendlatch/approval-card" in result.stdout
    assert "text/html;profile=mcp-app" in result.stdout


def test_mcp_roundtrip_output_is_auditable():
    """Every probe step announces itself — silent success is not evidence."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "mcp_roundtrip.py")],
        capture_output=True, text=True, cwd=ROOT, timeout=120,
    )
    for step in ("[1/8]", "[2/8]", "[3/8]", "[4/8]", "[5/8]", "[6/8]", "[7/8]", "[8/8]"):
        assert step in result.stdout, f"missing probe step {step}"
