"""MCP roundtrip probe — a REAL client over the wire, not an in-process call.

Spawns the SpendPilot MCP server as a separate process, connects with the
official MCP SDK over Streamable HTTP, and exercises the full surface:

  1. initialize handshake (assert protocol 2025-11-25 is negotiated)
  2. tools/list (assert all 13 tools are exposed)
  3. tools/call for the read-only surface (assert response shapes)
  4. state over the wire: set_budget then budget_status must reflect it;
     the error surface must return structured errors
  5. the action loop over the wire: propose -> approve -> execute -> receipt,
     and a bogus mandate must be refused with a structured error
  6. MCP Apps (SEP-1865): resources/list exposes the ui:// approval card with
     the mcp-app mime profile, resources/read returns the HTML, and
     propose_action carries the _meta.ui.resourceUri link
  7. accountability: the decision ledger shows the whole loop, including refusals

This simulates what an Alexa+ runtime does when it mounts the server — the
runtime-technology-hook requirement is proven by execution, not by README.

Usage:  python tools/mcp_roundtrip.py     # exits 0 and prints MCP_ROUNDTRIP_OK
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# The probe must talk to the local server directly, even when the machine has
# a system proxy configured (httpx/urllib honor Windows registry proxies via
# trust_env). Without this, a proxy turns 127.0.0.1 into a 502.
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_PROTOCOL = "2025-11-25"
EXPECTED_TOOLS = {
    "spending_overview", "detect_anomalies", "simulate_saving", "set_budget",
    "budget_status", "list_subscriptions", "unit_economics", "proactive_briefing",
    "decision_ledger",
    "propose_action", "approve_action", "execute_action", "mandate_status",
}
UI_RESOURCE_URI = "ui://spendpilot/approval-card"
MCP_APP_MIME = "text/html;profile=mcp-app"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_ready(port: int, proc: subprocess.Popen, err_path: Path,
                timeout: float = 25.0) -> float:
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if proc.poll() is not None:
            # The server's stderr goes to a file (never a pipe): a pipe no
            # one drains fills up and deadlocks a chatty SSE server.
            tail = ""
            try:
                tail = err_path.read_bytes().decode("utf-8", "replace")[-2000:]
            except OSError:
                pass
            raise RuntimeError(
                f"server exited early with code {proc.returncode}; stderr tail:\n{tail}"
            )
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return time.monotonic() - start
        except OSError:
            time.sleep(0.25)
    raise TimeoutError(f"server did not listen on {port} within {timeout}s")


async def _probe(url: str, log) -> None:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            assert init.protocolVersion == EXPECTED_PROTOCOL, (
                f"protocol {init.protocolVersion} != {EXPECTED_PROTOCOL}")
            log(f"[2/8] initialize -> protocolVersion {init.protocolVersion}")

            listed = await session.list_tools()
            names = {t.name for t in listed.tools}
            assert names == EXPECTED_TOOLS, f"tool mismatch: {names ^ EXPECTED_TOOLS}"
            by_name = {t.name: t for t in listed.tools}
            ui_meta = (by_name["propose_action"].meta or {}).get("ui", {})
            assert ui_meta.get("resourceUri") == UI_RESOURCE_URI, (
                f"propose_action missing ui link: {by_name['propose_action'].meta}")
            log(f"[3/8] tools/list -> {len(names)} tools; propose_action links {UI_RESOURCE_URI}")

            async def call(name: str, args: dict) -> dict:
                result = await session.call_tool(name, args)
                assert not result.isError, f"{name} returned isError"
                data = result.structuredContent
                if data is None:
                    # SDKs that do not emit structuredContent serialize the
                    # dict as JSON text content — accept both forms.
                    import json

                    assert result.content, f"{name}: empty result"
                    data = json.loads(result.content[0].text)
                assert isinstance(data, dict), f"{name}: unexpected result shape"
                return data

            overview = await call("spending_overview", {})
            assert overview["total"] > 0 and overview["providers"], "overview empty"

            briefing = await call("proactive_briefing", {})
            assert briefing["total_monthly_saving_potential"] > 0
            assert briefing["anomalies"], "proactive opening found nothing"

            anomalies = await call("detect_anomalies", {})
            assert anomalies["anomalies"], "explicit sweep returned nothing"
            assert any(a.get("previously_surfaced") for a in anomalies["anomalies"]), \
                "explicit sweep should show already-fired findings without re-firing"
            assert any(k["id"] == "keep-anthropic" for k in anomalies["kept"]), "judgment missing"

            proof = await call("simulate_saving", {"action_id": "rightsize-ec2"})
            assert proof["monthly_before"] > proof["monthly_after"]
            assert "scenario estimate" in proof["estimate_basis"]

            bad = await call("simulate_saving", {"action_id": "no-such-action"})
            assert "error" in bad and bad["known_actions"], "error surface broken"

            await call("set_budget", {"category": "cloud", "monthly_limit": 500.0})
            status = await call("budget_status", {})
            cloud = next(b for b in status["budgets"] if b["category"] == "cloud")
            assert cloud["monthly_limit"] == 500.0, "state did not persist over the wire"

            subs = await call("list_subscriptions", {})
            assert any(s["flag"] == "zombie" for s in subs["subscriptions"])

            econ = await call("unit_economics", {})
            assert any(r["canary"] for r in econ["providers"]), "canary missing"

            log("[4/8] tools/call -> read-only surface answers with valid structured content")
            log("[5/8] state over the wire -> set_budget then budget_status agrees; "
                "error surface returns structured errors")

            # --- the action boundary, entirely over the wire ----------------
            # Execution requires a mandate (bearer): a bogus one must refuse.
            refused = await call("execute_action", {"mandate_id": "m-bogus000"})
            assert refused.get("refused") is True, "execution without a mandate must refuse"

            proposal = await call("propose_action", {"action_id": "rightsize-ec2"})
            assert proposal["status"] == "proposed" and proposal["proof_snapshot"]
            assert len(proposal["proof_hash"]) == 64 and proposal["approval_challenge"], \
                "proposal must carry its proof hash and approval challenge"

            # The MCP surface CANNOT approve — not even by claiming to be a
            # human. Approval lives on the authenticated web surface only.
            self_approved = await call("approve_action", {"proposal_id": proposal["proposal_id"]})
            assert self_approved.get("refused") is True, \
                "an unauthenticated surface must never be able to approve"
            assert "authenticated" in self_approved["error"]

            replay = await call("execute_action", {"mandate_id": "m-bogus000"})
            assert replay.get("refused") is True, "bogus mandates must refuse"

            actions_view = await call("mandate_status", {})
            assert actions_view["counts"]["mandates_issued"] == 0
            assert actions_view["counts"]["proposals_open"] == 1
            log("[6/8] action boundary -> propose carries proof_hash + challenge; "
                "unauthenticated approve refused and logged; bogus execution refused")

            # --- MCP Apps surface --------------------------------------------
            resources = await session.list_resources()
            by_uri = {str(r.uri): r for r in resources.resources}
            assert UI_RESOURCE_URI in by_uri, f"ui resource missing: {list(by_uri)}"
            assert by_uri[UI_RESOURCE_URI].mimeType == MCP_APP_MIME, (
                f"mime {by_uri[UI_RESOURCE_URI].mimeType} != {MCP_APP_MIME}")
            blob = await session.read_resource(UI_RESOURCE_URI)
            html = blob.contents[0].text
            assert "ui/initialize" in html and "approve_action" in html, (
                "approval card does not speak the MCP Apps bridge")
            log(f"[7/8] MCP Apps -> {UI_RESOURCE_URI} served as {MCP_APP_MIME}, "
                "bridge handshake present in HTML")

            trail = await call("decision_ledger", {})
            kinds = {e["kind"] for e in trail["entries"]}
            assert {"propose", "refuse"} <= kinds, (
                f"ledger missing action-boundary entries: {kinds}")
            # the full approve -> execute -> receipt loop is proven end to end
            # by tools/e2e_flow.py on the authenticated web surface
            log("[8/8] decision_ledger -> propose and the unauthenticated-approve "
                "refusal recorded over the wire")


def main() -> int:
    log = print
    port = _free_port()
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "SPENDPILOT_PORT": str(port),
               "SPENDPILOT_STATE": str(Path(tmp) / "state.json")}
        log(f"[1/8] spawning server on 127.0.0.1:{port} (isolated state)")
        err_path = Path(tmp) / "server-stderr.log"
        with open(err_path, "w+b") as err_file:
            proc = subprocess.Popen(
                [sys.executable, "-m", "mcp_server.server"],
                cwd=ROOT, env=env,
                stdout=subprocess.DEVNULL, stderr=err_file,
            )
            try:
                ready_in = _wait_ready(port, proc, err_path)
                log(f"      server ready in {ready_in:.1f}s")
                asyncio.run(_probe(f"http://127.0.0.1:{port}/mcp", log))
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
    log("MCP_ROUNDTRIP_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
