# spending_overview

> MCP tool `spending_overview` — totals per provider and per category for one
> month, with month-over-month deltas. Pure read; no state, no ledger writes.

## When it activates

- User asks "overview", "how much", "total", "summary", "spend".
- A bare provider mention resolves here for the multi-provider answer.
- `proactive_briefing` embeds it as the opening context block.

## Flow

1. Defaults to the latest month in the dataset; an explicit `month` is honored
   when present in the window, otherwise the latest is used.
2. Sums each provider's monthly amount; rolls up by category; sorts providers
   descending by amount.
3. Computes `delta_pct` per provider and overall versus the previous month.

## Boundaries & refusal cases

- Providers with no entry for the month are skipped, never zero-filled.
- The first month of a dataset carries no `prev_*` fields (no invented deltas).
- Read-only: it cannot set budgets, propose actions, or write the ledger.

## Linked tests

- `tests/test_tools.py::TestSpendingOverview` (totals, deltas, category
  rollup, sort order, first-month edge)

## Evidence

- `docs/evidence/mcp-roundtrip.txt` step 4 (called over the wire)
