"""End-to-end web flow probe — spawns the real backend, drives the chat.

Reproduces the judge criteria over HTTP against a real server process with
isolated state: proactive opening, proof, the propose -> approve -> execute
action loop (including a refused replay), budgets, cross-session memory, and
the decision ledger. Prints a transcript and exits non-zero on any failure.

Usage:  python tools/e2e_flow.py      # exits 0 and prints E2E_FLOW_OK
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
from pathlib import Path

# Local loopback must bypass any system proxy (urllib/httpx honor Windows
# registry proxies via trust_env; a proxy turns 127.0.0.1 into a 502).
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"

ROOT = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_ready(port: int, proc: subprocess.Popen, err_path: Path,
                timeout: float = 25.0) -> None:
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if proc.poll() is not None:
            # Backend stderr goes to a file (never a pipe): an undrained
            # pipe fills up and deadlocks a chatty server.
            tail = ""
            try:
                tail = err_path.read_bytes().decode("utf-8", "replace")[-2000:]
            except OSError:
                pass
            raise RuntimeError(
                f"backend exited early with code {proc.returncode}; stderr tail:\n{tail}"
            )
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.5):
                return
        except OSError:
            time.sleep(0.25)
    raise TimeoutError(f"backend did not listen on {port} within {timeout}s")


def main() -> int:
    port = _free_port()
    # mkdtemp + retrying cleanup instead of TemporaryDirectory: on Windows the
    # killed backend's inherited stderr handle is released a few hundred ms
    # after wait() returns, so an immediate rmtree races it (PermissionError).
    tmp = Path(tempfile.mkdtemp(prefix="spendpilot-e2e-"))
    try:
        env = {**os.environ, "SPENDPILOT_STATE": str(tmp / "state.json"),
               "SPENDPILOT_WEB_PORT": str(port)}
        print(f"# spawning backend on 127.0.0.1:{port} (isolated state)")
        err_path = Path(tmp) / "backend-stderr.log"
        with open(err_path, "w+b") as err_file:
            proc = subprocess.Popen(
                [sys.executable, "-m", "agent.backend"],
                cwd=ROOT, env=env,
                stdout=subprocess.DEVNULL, stderr=err_file,
            )
            try:
                _wait_ready(port, proc, err_path)
            except Exception:
                proc.kill()
                proc.wait(timeout=5)  # let Windows release the stderr handle
                raise
        base = f"http://127.0.0.1:{port}"

        session = json.loads(urllib.request.urlopen(
            urllib.request.Request(f"{base}/api/session", data=b"{}",
                                   headers={"Content-Type": "application/json"}),
            timeout=15).read())
        token = session["session_token"]
        print(f"## 0. authenticated session minted (workspace {session['workspace']})")

        def post(msg: str, sid: str | None) -> dict:
            req = urllib.request.Request(
                f"{base}/api/chat",
                data=json.dumps({"message": msg, "session_id": sid,
                                  "session_token": token}).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())

        try:
            # 1. agent speaks first (unprompted)
            with urllib.request.urlopen(f"{base}/api/opening?session_token={token}", timeout=15) as r:
                opening = json.loads(r.read())
            sid = opening["session_id"]
            print("## 1. agent speaks first (unprompted)")
            print("reply:", opening["reply"])
            print("cards:", [c["type"] for c in opening["cards"]])
            assert opening["cards"], "proactive opening produced no cards"

            # 2. prove the saving -> scenario label + proposal on the table
            d = post("prove the saving", sid)
            card = d["cards"][0]
            print("\n## 2. prove the saving")
            print(f"before: {card['monthly_before']} after: {card['monthly_after']} "
                  f"label: {card['estimate_basis']}")
            assert "scenario estimate" in card["estimate_basis"]
            assert card.get("proposal_id"), "proof did not put a proposal on the table"
            print("proposal:", card["proposal_id"])

            # 3. approve -> signed mandate
            d = post("approve", sid)
            mandate = d["cards"][0]
            print("\n## 3. approve -> signed mandate")
            print("reply:", d["reply"])
            assert mandate["type"] == "mandate" and len(mandate["signature"]) == 64
            assert mandate["scope"]["max_monthly_before"] == card["monthly_before"]

            # 4. execute -> receipt; 5. replay -> refused
            d = post("execute", sid)
            receipt = d["cards"][0]
            print("\n## 4. execute -> receipt")
            print("reply:", d["reply"])
            assert receipt["type"] == "receipt" and receipt["simulated"] is True

            d = post("execute", sid)
            print("\n## 5. execute again -> refused (nothing executes twice on one mandate)")
            print("reply:", d["reply"])
            assert "will not act" in d["reply"] or "refused" in d["reply"].lower()

            # 6. budget
            d = post("set a $300 budget for home", sid)
            row = next(c for c in d["cards"] if c["category"] == "home")
            print("\n## 6. set budget -> warn")
            print("status:", row["status"], "used_pct:", row["used_pct"])
            assert row["status"] == "warn"

            # 7. reopen session -> memory
            with urllib.request.urlopen(f"{base}/api/opening?session_id={sid}&session_token={token}", timeout=15) as r:
                reopen = json.loads(r.read())
            print("\n## 7. reopen session -> memory")
            print("reply:", reopen["reply"])
            assert "remember" in reopen["reply"].lower()

            # 8. decision ledger shows the whole loop
            with urllib.request.urlopen(f"{base}/api/ledger?session_token={token}", timeout=15) as r:
                trail = json.loads(r.read())
            kinds = [e["kind"] for e in trail["entries"]]
            print("\n## 8. decision ledger")
            print("ledger count:", trail["count"])
            for e in trail["entries"]:
                if e["kind"] in ("propose", "approve", "execute", "refuse"):
                    print(f"  {e['kind']} - {e['subject']} - {e['reason'][:90]}")
            assert {"propose", "approve", "execute"} <= set(kinds)

            # 9. Anthropic is KEEP, never anomaly
            d = post("anything unusual?", sid)
            kept = [c["provider"] for c in d["cards"] if c["type"] == "kept"]
            print("\n## 9. Anthropic is KEEP, never anomaly")
            print("kept:", kept)
            assert kept == ["Anthropic API"]
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
        else:
            print(f"      warning: temp dir {tmp} still locked; left for the OS to reclaim")
    print("\nE2E_FLOW_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
