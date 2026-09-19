# decision_ledger

> MCP tool `decision_ledger` — the full accountability trail, newest first:
> alerts, holds, suppressions, refusals, approvals, executions. Silence is
> auditable.

## When it activates

- User asks "why didn't you tell me?", "what did you decide", "ledger".
- The web side rail and audit overlay read it continuously.

## Flow

1. Reads the append-only ledger from the workspace state file.
2. Returns entries newest-first with kind, subject, one-line reason,
   evidence references, and the hash-chain fields.
3. `GET /api/ledger/verify` re-verifies the chain (tamper-evidence).

## Boundaries & refusal cases

- Read-only over the wire; entries are written by the tools themselves,
  never by callers.
- Every refusal is an entry — the ledger is where "no" is recorded with the
  same dignity as "yes".
- Chain verification lives in `mcp_server/ledger.py`; a broken link names
  the entry where tampering starts.

## Linked tests

- `tests/test_tools.py::TestDecisionLedgerView`
- `tests/test_ledger.py` (append, hash chain, challenge/overrule)

## Evidence

- `docs/evidence/mcp-roundtrip.txt` step 8; `docs/evidence/e2e-flow.txt`
  step 8 (propose/approve/execute/refuse all present)
