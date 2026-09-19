"""Regenerate every artifact in docs/evidence/ by RUNNING the real thing.

Evidence is captured output, never hand-edited prose. One command refreshes
all of it against the current working tree:

  test-run.txt              pytest tests -q (full suite, real output)
  benchmark-run.txt         benchmarks/run.py over all three tiers
                            (public / independent / derived; the derived
                            suite is regenerated first via make_derived.py)
  derived-metrics.json      copy of benchmarks/results/derived-metrics.json
  independent-metrics.json  copy of benchmarks/results/independent-metrics.json
  mcp-roundtrip.txt         tools/mcp_roundtrip.py (real client, real server)
  mcp-handshake.txt         a real initialize POST against a spawned server
  e2e-flow.txt              tools/e2e_flow.py (real backend, isolated state)

Every file gets a UTC generation header. The CI freshness gate
(tools/check_evidence_freshness.py) fails the build if any evidence file
predates the code it describes — so after changing code, re-run this.

Usage:  python tools/refresh_evidence.py
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Local loopback must bypass any system proxy (see tools/mcp_roundtrip.py).
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "evidence"


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(argv: list[str]) -> str:
    result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True,
                            encoding="utf-8", timeout=300)
    out = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(argv)} failed:\n{out[-3000:]}")
    return result.stdout


def write(name: str, header: str, body: str) -> None:
    text = f"{header.rstrip()}\n\n{body.strip()}\n"
    (EVIDENCE / name).write_text(text, encoding="utf-8", newline="\n")
    print(f"  wrote docs/evidence/{name} ({len(text)} bytes)")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def capture_handshake() -> str:
    """One real initialize POST against a spawned server, SSE frame captured."""
    port = _free_port()
    tmp = Path(tempfile.mkdtemp(prefix="spendlatch-handshake-"))
    try:
        env = {**os.environ, "SPENDLATCH_PORT": str(port),
               "SPENDLATCH_STATE": str(tmp / "state.json")}
        err_path = tmp / "server-stderr.log"
        with open(err_path, "w+b") as err_file:
            proc = subprocess.Popen(
                [sys.executable, "-m", "mcp_server.server"],
                cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=err_file)
            try:
                deadline = time.monotonic() + 25
                while time.monotonic() < deadline:
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                            break
                    except OSError:
                        time.sleep(0.25)
                else:
                    raise TimeoutError("server did not listen within 25s")
                body = json.dumps({
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                               "clientInfo": {"name": "evidence-refresh", "version": "0"}},
                }).encode()
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/mcp", data=body,
                    headers={"Content-Type": "application/json",
                             "Accept": "application/json, text/event-stream"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    raw = resp.read().decode("utf-8", "replace")
                frame = next((l for l in raw.splitlines() if l.startswith("data:")), raw.strip())
                return (f"# POST http://127.0.0.1:{port}/mcp (initialize, SSE frame)\n{frame}")
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
    finally:
        for _ in range(50):
            try:
                shutil.rmtree(tmp)
                break
            except PermissionError:
                time.sleep(0.2)


def main() -> int:
    print("refreshing evidence against the current working tree...")

    ts = stamp()
    out = run([sys.executable, "-m", "pytest", "tests", "-q"])
    write("test-run.txt", f"# pytest run {ts}\n# generator: tools/refresh_evidence.py (pytest tests -q)",
          out[out.find("\n") + 1:] if out.startswith("=") else out)

    ts = stamp()
    run([sys.executable, "tools/make_derived.py"])
    sections = []
    for mode, argv in (("public regression fixtures", [sys.executable, "benchmarks/run.py"]),
                       ("independent hand-written suite", [sys.executable, "benchmarks/run.py", "--independent"]),
                       ("derived invariance suite", [sys.executable, "benchmarks/run.py", "--derived"])):
        sections.append(f"== {mode} ==\n{run(argv).strip()}")
    write("benchmark-run.txt",
          f"# sealed benchmark run {ts}\n# generator: tools/refresh_evidence.py (three tiers, sealed two-phase protocol)",
          "\n\n".join(sections))
    for name in ("derived-metrics.json", "independent-metrics.json"):
        shutil.copyfile(ROOT / "benchmarks" / "results" / name, EVIDENCE / name)
        print(f"  copied docs/evidence/{name}")

    ts = stamp()
    write("mcp-roundtrip.txt",
          f"# MCP roundtrip {ts}\n# generator: tools/refresh_evidence.py (tools/mcp_roundtrip.py, real client over the wire)",
          run([sys.executable, "tools/mcp_roundtrip.py"]))

    ts = stamp()
    write("mcp-handshake.txt",
          f"# MCP initialize handshake over Streamable HTTP\n# captured {ts} by tools/refresh_evidence.py against a spawned server (isolated state)",
          capture_handshake())

    ts = stamp()
    write("e2e-flow.txt",
          f"# End-to-end web flow evidence (JUDGE-REPRODUCTION.md criteria 1-9)\n"
          f"# generated {ts} by tools/e2e_flow.py — reproducible, isolated state\n"
          "# approval model: authenticated web session mints a single-use HMAC mandate;\n"
          "# the MCP surface refuses approval by design (see mcp-roundtrip.txt step 6)",
          run([sys.executable, "tools/e2e_flow.py"]))

    print("EVIDENCE_REFRESH_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
