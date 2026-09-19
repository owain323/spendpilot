"""Mandate-gated action loop — the step from "watching bills" to "acting".

This is SpendPilot's answer to the 2026 agentic-payments discipline (AP2 /
ACP / x402 all converge on the same shape): an agent that touches money must
carry PROOF OF HUMAN AUTHORIZATION, bounded in scope and time, and leave an
audit trail.

Authorization model (hardened 2026-09-18 — the previous build let any MCP
caller self-report approver="human", which proved nothing):

  propose  -> the agent attaches its proof to a concrete, bounded action and
              mints an approval challenge bound to that proposal
  approve  -> ONLY an authenticated web session can approve (the server
              mints session tokens; the browser presents one). The MCP
              surface REFUSES to approve and logs the refusal — an
              unauthenticated surface must never be able to say "a human
              agreed". The issued mandate records WHO approved (session
              fingerprint) and WHICH proof they approved (proof_hash).
  execute  -> the provider adapter runs ONLY if the mandate verifies:
              signature valid, not expired, not already consumed, the proof
              still hashes to what was approved, and the real-world scope
              has not drifted past the cap. Execution is serialized under a
              process lock, so single-use holds under concurrency.

Every step — including every refusal — is recorded in a hash-chained ledger.
An agent that can act must be MORE auditable than one that only advises.

Honesty boundary: the session token is a bearer credential minted by this
demo's own server — it binds approval to a browser session, not to a
federated identity. Production binds this to Alexa+ account linking (OAuth
2.1 + PKCE) or AP2 verifiable credentials; the control flow is identical.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import adapters, ledger, store, tools

MANDATE_TTL_SECONDS = 900  # 15 minutes: approval is a decision, not a blank check
# The TTL is NOT a caller-supplied parameter — exposing it let a client mint
# a 100-hour "15-minute" mandate. Policy belongs to the server.

# Exactly these fields are signed. Status and execution metadata live OUTSIDE
# the signed payload, so bookkeeping mutations can never invalidate (or fake)
# a signature.
SIGNED_FIELDS = ("mandate_id", "proposal_id", "action_id", "scope",
                 "issued_at", "expires_at", "approver", "nonce",
                 "proof_hash", "approval")

# One process, one state file, one execution at a time. Without this, two
# concurrent calls can both observe status="issued" and both execute —
# the classic TOCTOU hole in check-use-mark.
_EXECUTE_LOCK = threading.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _secret(state: dict) -> str:
    """Per-installation HMAC secret, generated once and persisted in state."""
    if not state.get("mandate_secret"):
        state["mandate_secret"] = secrets.token_hex(32)
    return state["mandate_secret"]


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sign(payload: dict, secret: str) -> str:
    return hmac.new(secret.encode(), _canonical(payload), hashlib.sha256).hexdigest()


def proof_hash(proof: dict) -> str:
    """Stable hash over the material facts the human is shown when approving."""
    material = {
        "title": proof.get("title"),
        "provider": proof.get("provider"),
        "monthly_before": proof.get("monthly_before"),
        "monthly_after": proof.get("monthly_after"),
        "expected_saving_pct": proof.get("expected_saving_pct"),
        "estimate_basis": proof.get("estimate_basis"),
        "evidence": proof.get("evidence", []),
    }
    return hashlib.sha256(_canonical(material)).hexdigest()


def _session_fingerprint(session_token: str) -> str:
    digest = hashlib.sha256(session_token.encode("utf-8")).hexdigest()
    return digest[:12]


def _refuse(subject: str, reason: str, state_path: Path | None, **extra) -> dict:
    """A refusal is a first-class decision: logged, structured, returned."""
    entry = ledger.record("refuse", subject, reason, path=state_path)
    return {"refused": True, "error": reason, "ledger_seq": entry["seq"], **extra}


def open_session() -> dict:
    """Mint an authenticated web session (token + its own workspace)."""
    return store.open_auth_session()


# ------------------------------------------------------------------ propose

def propose_action(action_id: str, state_path: Path | None = None) -> dict:
    """Attach the proof to a concrete, bounded action and put it on the table.

    Idempotent per action: re-proposing an already-open proposal returns the
    existing one instead of duplicating. Each proposal carries a proof_hash
    (what the human will see when approving) and an approval challenge.
    """
    proof = tools.simulate_saving(action_id)
    if "error" in proof:
        return proof
    state = store.load_state(state_path)
    for proposal in state["proposals"].values():
        if proposal["action_id"] == action_id and proposal["status"] == "proposed":
            return {**proposal, "proof": proof, "note": "already proposed — awaiting approval"}

    proposal_id = f"p-{secrets.token_hex(4)}"
    operation = adapters.operation_for(action_id)
    if operation is None:
        return {"error": f"action '{action_id}' has no provider adapter; refusing to propose"}
    proposal = {
        "proposal_id": proposal_id,
        "action_id": action_id,
        "title": proof["title"],
        "provider": proof["provider"],
        "operation": operation,
        "status": "proposed",
        "created_at": _iso(_now()),
        "proof_hash": proof_hash(proof),
        "approval_challenge": secrets.token_hex(16),
        "proof_snapshot": {
            "monthly_before": proof["monthly_before"],
            "monthly_after": proof["monthly_after"],
            "expected_saving_pct": proof["expected_saving_pct"],
        },
    }
    state["proposals"][proposal_id] = proposal
    store.save_state(state, state_path)
    ledger.record(
        "propose", proof["provider"],
        f"Proposed '{proof['title']}' ({proof['expected_saving_pct']}% scenario saving, "
        f"proof attached) — awaiting approval from an authenticated session.",
        evidence=[action_id, proposal_id], path=state_path,
    )
    return {**proposal, "proof": proof}


# ------------------------------------------------------------------ approve

def approve_action(proposal_id: str, session_token: str | None = None,
                   state_path: Path | None = None) -> dict:
    """An authenticated web session authorizes; the server issues the mandate.

    The mandate's scope is captured from a FRESH proof at approval time, the
    proof_hash of that proof is signed INTO the mandate (execution re-derives
    it and refuses if the evidence changed), and the approver is the session
    fingerprint — never a caller-supplied string. Requests without a valid
    session token are refused and logged; that is the boundary between "the
    agent proposes" and "a human decided".
    """
    state = store.load_state(state_path)
    if not store.token_is_authenticated(session_token):
        return _refuse(
            proposal_id,
            "approval requires an authenticated web session — this surface "
            "cannot approve actions, and self-reported approvers are not "
            "accepted; open the web demo to approve",
            state_path)
    fingerprint = _session_fingerprint(session_token)

    proposal = state["proposals"].get(proposal_id)
    if proposal is None:
        return _refuse(proposal_id, f"unknown proposal '{proposal_id}'", state_path)
    if proposal["status"] != "proposed":
        return _refuse(proposal["title"],
                       f"proposal is '{proposal['status']}', not 'proposed' — cannot approve again",
                       state_path)

    proof = tools.simulate_saving(proposal["action_id"])
    if "error" in proof:
        return _refuse(proposal["title"], "proof can no longer be produced; approval refused",
                       state_path)
    current_hash = proof_hash(proof)
    if current_hash != proposal["proof_hash"]:
        return _refuse(proposal["title"],
                       "the proof changed since the proposal was minted — "
                       "re-propose so the human approves what is true now",
                       state_path)

    issued = _now()
    payload = {
        "mandate_id": f"m-{secrets.token_hex(4)}",
        "proposal_id": proposal_id,
        "action_id": proposal["action_id"],
        "scope": {
            "provider": proposal["provider"],
            "operation": proposal["operation"],
            "max_monthly_before": proof["monthly_before"],  # hard cap: refuse if reality drifted up
            "expected_saving_pct": proof["expected_saving_pct"],
        },
        "issued_at": _iso(issued),
        "expires_at": _iso(issued + timedelta(seconds=MANDATE_TTL_SECONDS)),
        "approver": f"web-session:{fingerprint}",
        "nonce": secrets.token_hex(8),
        "proof_hash": current_hash,
        "approval": {
            "surface": "web",
            "session": fingerprint,
            "challenge": proposal["approval_challenge"],
        },
    }
    secret = _secret(state)
    mandate = {**payload, "signature": _sign(payload, secret), "status": "issued"}
    state["mandates"][payload["mandate_id"]] = mandate
    proposal["status"] = "approved"
    store.save_state(state, state_path)
    ledger.record(
        "approve", proposal["provider"],
        f"web-session:{fingerprint} approved '{proposal['title']}'; mandate "
        f"{payload['mandate_id']} scoped to {proposal['operation']} "
        f"(cap ${proof['monthly_before']:.2f}/mo), proof {current_hash[:12]}, "
        f"expires in {MANDATE_TTL_SECONDS}s.",
        evidence=[payload["mandate_id"], proposal_id], path=state_path,
    )
    return {k: v for k, v in mandate.items()}  # full record incl. signature (local demo)


# ------------------------------------------------------------------ execute

def execute_action(mandate_id: str, state_path: Path | None = None) -> dict:
    """Execute through the provider adapter — only through a valid mandate.

    Serialized under the process lock, so single-use holds even when two
    callers race. Verification order is deliberate and each failure is
    logged separately:
    unknown -> forged -> consumed -> expired -> proof drifted -> scope
    drifted -> execute.
    """
    with _EXECUTE_LOCK:
        return _execute_locked(mandate_id, state_path)


def _execute_locked(mandate_id: str, state_path: Path | None) -> dict:
    state = store.load_state(state_path)
    mandate = state["mandates"].get(mandate_id)
    if mandate is None:
        return _refuse(mandate_id, f"unknown mandate '{mandate_id}' — nothing executes on trust",
                       state_path)

    secret = _secret(state)
    payload = {k: mandate[k] for k in SIGNED_FIELDS}
    if not hmac.compare_digest(_sign(payload, secret), mandate["signature"]):
        return _refuse(mandate["scope"]["provider"],
                       f"mandate {mandate_id} failed signature verification — "
                       "payload was tampered with; execution refused and logged",
                       state_path, mandate_id=mandate_id)

    if mandate["status"] == "executed":
        return _refuse(mandate["scope"]["provider"],
                       f"mandate {mandate_id} was already consumed — mandates are single-use",
                       state_path, mandate_id=mandate_id)
    if mandate["status"] != "issued":
        return _refuse(mandate["scope"]["provider"],
                       f"mandate {mandate_id} is '{mandate['status']}' — not executable",
                       state_path, mandate_id=mandate_id)

    if _now() > datetime.fromisoformat(mandate["expires_at"]):
        mandate["status"] = "expired"
        store.save_state(state, state_path)
        return _refuse(mandate["scope"]["provider"],
                       f"mandate {mandate_id} expired at {mandate['expires_at']} — "
                       "approval is a decision, not a blank check",
                       state_path, mandate_id=mandate_id)

    proof = tools.simulate_saving(mandate["action_id"])
    if "error" in proof:
        return _refuse(mandate["scope"]["provider"],
                       "the action's proof disappeared since approval; execution refused",
                       state_path, mandate_id=mandate_id)

    # The evidence the human approved must still be the evidence on the table.
    current_hash = proof_hash(proof)
    if current_hash != mandate["proof_hash"]:
        return _refuse(mandate["scope"]["provider"],
                       "proof drifted: the evidence changed since the mandate was signed "
                       f"(approved {mandate['proof_hash'][:12]}, now {current_hash[:12]}) — "
                       "re-approval required",
                       state_path, mandate_id=mandate_id)

    cap = mandate["scope"]["max_monthly_before"]
    if proof["monthly_before"] > cap + 1e-9:
        return _refuse(
            mandate["scope"]["provider"],
            f"scope drifted: bill is now ${proof['monthly_before']:.2f}/mo, above the approved "
            f"cap of ${cap:.2f}/mo — re-approval required",
            state_path, mandate_id=mandate_id)

    receipt = adapters.execute(mandate["action_id"])
    if "error" in receipt:
        return _refuse(mandate["scope"]["provider"], receipt["error"], state_path,
                       mandate_id=mandate_id)

    mandate["status"] = "executed"
    mandate["executed_at"] = receipt["executed_at"]
    receipt["mandate_id"] = mandate_id
    receipt["approver"] = mandate["approver"]
    # Transaction identity: replay-safe means every execution carries its own
    # id and a deterministic idempotency key derived from the mandate nonce.
    receipt["request_id"] = mandate["proposal_id"]
    receipt["execution_id"] = f"e-{secrets.token_hex(4)}"
    receipt["idempotency_key"] = hashlib.sha256(
        f"{mandate_id}:{mandate['nonce']}".encode()).hexdigest()[:24]
    state["receipts"].append(receipt)
    store.save_state(state, state_path)
    ledger.record(
        "execute", mandate["scope"]["provider"],
        f"Executed '{receipt['operation']}' via the {receipt['adapter']} adapter (simulated); "
        f"mandate {mandate_id} consumed. Monthly scenario saving ${receipt['monthly_saving']:.2f}.",
        evidence=[mandate_id, mandate["action_id"]], path=state_path,
    )
    return receipt


# ------------------------------------------------------------ proof export

POLICY_VERSION = "1.0"


def export_proof(mandate_id: str, state_path: Path | None = None) -> dict:
    """Export one authorization event as a self-contained proof bundle.

    The bundle travels: it can be verified OFFLINE by `tools/verify_proof.py`
    against a state file, without trusting the server that produced it.
    Fields follow the verifiable-proof contract:
    request / policy_version / mandate_digest / decision / approval /
    execution_receipt / previous_ledger_hash / current_ledger_hash /
    signer_key_id.
    """
    state = store.load_state(state_path)
    mandate = state["mandates"].get(mandate_id)
    if mandate is None:
        return {"error": f"unknown mandate '{mandate_id}'"}
    receipt = next((r for r in state["receipts"] if r.get("mandate_id") == mandate_id), None)
    chain = state["ledger"]
    last = chain[-1] if chain and "hash" in chain[-1] else {"prev_hash": None, "hash": None}
    payload = {k: mandate[k] for k in SIGNED_FIELDS}
    return {
        "request": payload,
        "policy_version": POLICY_VERSION,
        "mandate_digest": hashlib.sha256(_canonical(mandate)).hexdigest(),
        "decision": "APPROVED" if receipt else mandate["status"].upper(),
        "approval": mandate["approval"],
        "execution_receipt": receipt,
        "previous_ledger_hash": last["prev_hash"],
        "current_ledger_hash": last["hash"],
        "signer_key_id": "hmac-sha256#1",
    }


# ------------------------------------------------------- spend-intent policy

def evaluate_spend_intent(intent: dict, state_path: Path | None = None) -> dict:
    """Policy gate for NEW spend requests parsed by the LLM planner.

    Default-deny, and that is the product: the mandate system only covers
    proven cost-REDUCTION actions from the saving catalog. A request to
    spend money ("buy $200 of API credits") has no adapter, no proof, and no
    mandate path — so the honest answer is a logged, structured DENIAL with
    the reason, never a silent ignore and never a hallucinated execution.
    The planner only produced the intent; this deterministic gate decides.
    """
    merchant = intent.get("merchant") or "unresolved merchant"
    amount = intent.get("amount") or 0.0
    category = intent.get("category") or "other"
    reasons = [
        "new spend is outside the mandate action catalog — only proven "
        "cost-reduction actions can be proposed, approved, and executed",
    ]
    evidence = f"policy v{POLICY_VERSION}: default-deny for new spend"
    # A budget line makes the denial concrete when the category has one.
    if category != "other":
        status = tools.budget_status(state_path)
        row = next((b for b in status["budgets"] if b["category"] == category), None)
        if row and amount > 0:
            projected = row["spent"] + amount
            verdict = "exceeds" if projected > row["monthly_limit"] else "stays within"
            evidence = (f"{category} budget: ${row['spent']:.2f} spent + ${amount:.2f} "
                        f"requested = ${projected:.2f} vs ${row['monthly_limit']:.2f}/mo "
                        f"limit — {verdict}")
            if projected > row["monthly_limit"]:
                reasons.append(
                    f"the {category} budget would be exceeded ({evidence})")
    entry = ledger.record(
        "refuse", merchant,
        f"DENIED new spend of ${amount:.2f} ({category})"
        + (f" for {intent['scope']}" if intent.get("scope") else "")
        + f": {reasons[0]}",
        evidence=[evidence], path=state_path)
    return {"decision": "DENIED", "reasons": reasons, "evidence": evidence,
            "policy_limit": "mandate action catalog: cost-reduction only",
            "ledger_seq": entry["seq"]}


# ------------------------------------------------------------------- status

def mandate_status(state_path: Path | None = None) -> dict:
    """All proposals, mandates, and receipts — the action accountability view."""
    state = store.load_state(state_path)
    now = _now()
    mandates = []
    for m in state["mandates"].values():
        row = {k: v for k, v in m.items() if k != "signature"}
        row["signature_short"] = m["signature"][:12] + "..."
        if m["status"] == "issued" and now > datetime.fromisoformat(m["expires_at"]):
            row["status"] = "expired (pending sweep)"
        mandates.append(row)
    mandates.sort(key=lambda m: m["issued_at"], reverse=True)
    proposals = sorted(state["proposals"].values(), key=lambda p: p["created_at"], reverse=True)
    return {
        "proposals": proposals,
        "mandates": mandates,
        "receipts": list(reversed(state["receipts"])),
        "counts": {
            "proposals_open": sum(1 for p in proposals if p["status"] == "proposed"),
            "mandates_issued": sum(1 for m in mandates if m["status"] == "issued"),
            "executed": len(state["receipts"]),
        },
    }
