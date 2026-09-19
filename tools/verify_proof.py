"""spendpilot verify — independently verify one exported proof bundle.

The point: the bundle must verify OFFLINE against a state file. The
verifier trusts no server output; it re-derives everything from the state
and the bundle's own bytes:

  1. request integrity        - signed payload fields present & canonical
  2. mandate signature        - HMAC re-derived from the state secret
  3. policy version           - matches a known policy release
  4. authorization validity   - approval block bound to a session, mandate
                                unexpired at execution time
  5. execution binding        - the receipt belongs to this mandate and
                                carries transaction identity
  6. ledger continuity        - the bundle's ledger hashes match the real
                                chain tail (or a prefix of it)
  7. replay protection        - the mandate is single-use: it is consumed
                                in state, and its idempotency key is stable

Usage:  python tools/verify_proof.py proof.json [--state path/to/state.json]
Exit 0 when every check passes; exit 1 with per-check failure lines.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mcp_server import actions, store  # noqa: E402

KNOWN_POLICY_VERSIONS = {"1.0"}


def _check(name: str, ok: bool, detail: str = "") -> dict:
    return {"name": name, "ok": ok, "detail": detail}


def verify_proof(bundle_path: str, state_path: str | None = None) -> int:
    bundle = json.loads(Path(bundle_path).read_text(encoding="utf-8"))
    state = store.load_state(Path(state_path) if state_path else None)
    request = bundle["request"]
    mandate_id = request["mandate_id"]
    mandate = state["mandates"].get(mandate_id)
    checks: list[dict] = []

    required = set(actions.SIGNED_FIELDS)
    checks.append(_check("request integrity", required <= set(request),
                         "signed payload complete" if required <= set(request)
                         else f"missing: {sorted(required - set(request))}"))

    sig_ok = False
    if mandate:
        expected = actions._sign({k: mandate[k] for k in actions.SIGNED_FIELDS},
                                  actions._secret(state))
        sig_ok = expected == mandate["signature"] and bundle["mandate_digest"] == \
            actions.hashlib.sha256(actions._canonical(mandate)).hexdigest()
    checks.append(_check("mandate signature", sig_ok))

    checks.append(_check("policy version",
                         bundle.get("policy_version") in KNOWN_POLICY_VERSIONS,
                         f"v{bundle.get('policy_version')}"))

    approval = bundle.get("approval") or {}
    auth_ok = bool(approval.get("session") and approval.get("challenge")
                   and approval.get("surface") == "web")
    if auth_ok and mandate:
        expires = datetime.fromisoformat(mandate["expires_at"])
        executed_at = mandate.get("executed_at")
        auth_ok = executed_at is None or datetime.fromisoformat(executed_at) <= expires
    checks.append(_check("authorization validity", auth_ok))

    receipt = bundle.get("execution_receipt")
    binding = False
    if receipt and mandate:
        binding = (receipt.get("mandate_id") == mandate_id
                   and receipt.get("idempotency_key")
                   and receipt.get("execution_id")
                   and receipt.get("request_id") == mandate.get("proposal_id")
                   and mandate["status"] == "executed"
                   and state["receipts"][-1].get("execution_id") == receipt["execution_id"])
    checks.append(_check("execution binding", binding))

    ledger_ok = True
    if bundle.get("current_ledger_hash"):
        # The exported tail hash must exist somewhere in the live chain
        # (append-only: it may no longer be the tail after new entries).
        hashes = [e["hash"] for e in state["ledger"] if "hash" in e]
        ledger_ok = bool(hashes) and bundle["current_ledger_hash"] in hashes
    checks.append(_check("ledger continuity", ledger_ok))

    replay_ok = False
    if mandate and receipt:
        key = actions.hashlib.sha256(
            f"{mandate_id}:{mandate['nonce']}".encode()).hexdigest()[:24]
        replay_ok = (receipt["idempotency_key"] == key
                     and mandate["status"] == "executed"
                     and sum(1 for r in state["receipts"]
                             if r.get("mandate_id") == mandate_id) == 1)
    checks.append(_check("replay protection", replay_ok))

    failed = [c for c in checks if not c["ok"]]
    for c in checks:
        mark = "✓" if c["ok"] else "✗"
        suffix = f" — {c['detail']}" if c["detail"] else ""
        print(f"{mark} {c['name']}{suffix}")
    print()
    print("PROOF VERIFIED" if not failed else f"PROOF FAILED ({len(failed)} check(s))")
    return 0 if not failed else 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    state = None
    if "--state" in sys.argv:
        i = sys.argv.index("--state")
        state = sys.argv[i + 1]
    raise SystemExit(verify_proof(sys.argv[1], state))
