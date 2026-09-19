# execute_action

> MCP tool `execute_action` — the provider adapter runs ONLY through a valid
> mandate. Serialized under a process lock: single-use holds under
> concurrency.

## When it activates

- User says "execute" (optionally naming a mandate id) after approving.

## Flow

Verification order is deliberate; each failure is logged separately:

1. unknown mandate -> refuse
2. forged signature -> refuse (payload tampered)
3. already consumed -> refuse (single-use)
4. expired -> refuse (approval is a decision, not a blank check)
5. proof drifted since signing -> refuse (re-approval required)
6. scope drifted past the approved cap -> refuse (re-approval required)
7. all pass -> the simulated adapter runs; receipt carries mandate id,
   execution id, and a deterministic idempotency key.

## Boundaries & refusal cases

- Nothing executes on trust; bogus/replayed mandates produce structured
  refusals and ledger entries.
- Receipts are always labeled `simulated: true`.
- The check-use-mark sequence runs inside one lock — no TOCTOU race.

## Linked tests

- `tests/test_actions.py::TestExecute` (full loop, no-mandate, forged,
  single-use, expired, scope-drift, refusal logging)
- `tests/test_actions.py::TestAdapters`

## Evidence

- `docs/evidence/e2e-flow.txt` steps 4-5 (execute -> receipt; replay
  refused); `docs/evidence/mcp-roundtrip.txt` step 6
