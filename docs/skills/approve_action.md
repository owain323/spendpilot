# approve_action

> MCP tool `approve_action` — an authenticated web session authorizes; the
> server issues the signed mandate. THE authorization boundary.

## When it activates

- User says "approve" (optionally naming a proposal id) on the web surface,
  or the MCP Apps approval card is confirmed inside a host.

## Flow

1. Verifies the session token (server-minted, workspace-bound); without one
   the call is refused and logged — the MCP surface cannot approve.
2. Rejects unknown or non-`proposed` proposals (double approval refused).
3. Re-derives the proof and refuses if it drifted since the proposal.
4. Issues the mandate: HMAC-SHA256, single-use, scope-capped at the approved
   bill, 15-minute expiry, approver = session fingerprint, proof hash signed
   in. TTL is server policy, never a caller parameter.

## Boundaries & refusal cases

- Unauthenticated surfaces: refused and logged (constitution clause).
- Self-reported approvers are not accepted.
- The mandate records WHO approved and WHICH proof they approved.

## Linked tests

- `tests/test_actions.py::TestApprove`
- `tests/test_actions.py::TestAuthorizationBoundary` (RED LINE — 7 tests)

## Evidence

- `docs/evidence/mcp-roundtrip.txt` step 6 (unauthenticated approve refused
  over the wire); `docs/evidence/e2e-flow.txt` step 3
