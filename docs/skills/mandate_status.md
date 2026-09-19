# mandate_status

> MCP tool `mandate_status` — the action accountability view: all proposals,
> mandates, and receipts, with counts.

## When it activates

- User asks "receipts", "what did you do", "mandate status".
- The web action rail and the mandates card read it.

## Flow

1. Loads proposals, mandates, receipts from state.
2. Mandates are returned with the signature redacted to `signature_short`
   (the full signature never leaves the action record over this view).
3. Issued-but-expired mandates are labeled "expired (pending sweep)".
4. Counts: proposals open / mandates issued and unused / executions done.

## Boundaries & refusal cases

- Read-only. It cannot approve, execute, or mutate — it only reports.
- Counts are derived from records, never cached counters that could drift.

## Linked tests

- `tests/test_actions.py::TestMandateStatus` (counts track the loop, state
  roundtrip)

## Evidence

- `docs/evidence/mcp-roundtrip.txt` step 6 (counts asserted over the wire:
  zero mandates issued while an unauthenticated approve was refused)
