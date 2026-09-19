# propose_action

> MCP tool `propose_action` — attach the proof to a concrete, bounded action
> and put it on the table. The first step of the mandate loop.

## When it activates

- After a proof exists: user says "prove the saving" (brain proposes
  automatically), or a caller proposes a catalog action id directly.

## Flow

1. Re-derives the proof via `simulate_saving` (unknown action -> error).
2. Idempotent per action: an already-open proposal is returned, not
   duplicated.
3. Mints the proposal with `proof_hash` (what the human will approve) and an
   `approval_challenge`, bound to the provider adapter's operation.
4. Logs a `propose` entry. Status: `proposed` — awaiting an authenticated
   approval.

## Boundaries & refusal cases

- Actions without a provider adapter are refused at propose time.
- A proposal is inert: it cannot execute anything. Authority appears only
  at approve time, from an authenticated web session.
- Carries the MCP Apps link (`_meta.ui.resourceUri`) to the approval card.

## Linked tests

- `tests/test_actions.py::TestPropose` (proof snapshot, idempotency,
  unknown-action surface, logging)

## Evidence

- `docs/evidence/mcp-roundtrip.txt` step 6 (proof_hash + challenge over
  the wire)
