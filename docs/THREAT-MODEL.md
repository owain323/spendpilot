# Threat Model — SpendLatch

Who attacks an agent that can spend? What does SpendLatch actually defend,
and with which mechanism? This document states both, with pointers to the
code and the tests that prove each defense.

**Scope**: the authorization boundary of the demo's action loop. Provider
adapters are simulated, so this model governs the mandate protocol, not
real money movement.

## Attackers

- **A misaligned or compromised agent** that proposes spend beyond its
  delegated authority (bug, drift, or prompt injection upstream)
- **An attacker with MCP access** to the public surface (the demo exposes
  MCP over Streamable HTTP on the internet)
- **A replay/race attacker** exploiting retries, timeouts, and duplicate
  tool calls — the natural failure mode of agent systems
- **A tamperer** rewriting requests, mandates, evidence, or history

## Threats and defenses

| # | Threat | Primary defense | Proof it works |
|---|---|---|---|
| T1 | Malicious/misaligned agent proposes beyond authority | **Deterministic policy decides — the LLM never owns authorization.** The agent can propose, never approve. | `actions.approve_action` refuses without an authenticated session |
| T2 | Prompt injection rewrites the intended action | Canonical spend intent: the proof the human approves is hashed into the mandate; evidence drift rejects execution | `proof_hash` in `SIGNED_FIELDS`; `test_proof_drift_since_approval_refused` |
| T3 | Tampered spend request | Canonical digest of the material facts signed at approval time; any change breaks the hash | same mechanism as T2 |
| T4 | Forged/modified mandate | HMAC-SHA256 over exactly the signed fields; bookkeeping fields live outside the signature | `test_forged_mandate_refused` |
| T5 | Replay of a valid mandate | Single-use under a process lock + nonce + idempotency key on the receipt | `test_single_use_holds_under_concurrency` |
| T6 | Stale authorization after policy/time change | TTL is server policy (900s, not caller-supplied); expired mandates refuse and log | `test_expired_mandate_refused` |
| T7 | Untrusted surface claims "a human approved" | Surface isolation: only the authenticated web session can approve; the MCP surface refuses and logs | `test_mcp_surface_cannot_approve` |
| T8 | Duplicate execution after timeout/retry | Transaction identity: every receipt carries request_id / execution_id / idempotency_key derived from mandate+nonce | `test_receipt_carries_transaction_identity` |
| T9 | Tampered decision history | Hash-chained ledger: every entry commits to content and predecessor | `TestHashChain` |
| T10 | Silent state corruption | Fail-closed persistence: corrupt file preserved, never silently reset | `test_corrupt_state_fails_closed_and_preserves_file` |

## integrity vs authenticity — stated precisely

The hash chain proves **integrity** (nothing in the retained window was
altered). It does NOT by itself prove **authenticity** (who authorized what).
Authenticity lives in the proof bundle: intent + policy version + mandate +
signature + execution receipt + ledger link — verifiable offline:

```
python tools/verify_proof.py proof.json --state data/workspaces/<ws>.json
```

## Out of scope (explicit)

- Real money movement, payment rails, card networks, merchant integrations
- Credential handling (the demo holds no provider credentials by design)
- Byzantine/multiple-signer scenarios (single trust domain; asymmetric
  signatures, key rotation, and third-party verification are the v2 lane)
