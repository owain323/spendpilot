# budget_status

> MCP tool `budget_status` — budgets versus current-month spend, with
> ok / warn / over status per category.

## When it activates

- User asks "budget", "where do my budgets stand".
- The LLM-planner spend gate reads it to make denials concrete.

## Flow

1. Loads persisted budgets from state.
2. Joins with `spending_overview` current-month category spend.
3. Computes used percentage; status is `over` past 100%, `warn` from 80%,
   otherwise `ok`.

## Boundaries & refusal cases

- Read-only.
- A category with a budget but no spend reports 0%, not an error.
- Zero/negative limits cannot exist (rejected at `set_budget`).

## Linked tests

- `tests/test_tools.py::TestBudgets` (`test_status_warn_at_80`,
  `test_status_over_beyond_100`, `test_status_ok_below_80`)

## Evidence

- `docs/evidence/e2e-flow.txt` step 6; `docs/evidence/mcp-roundtrip.txt`
  step 5 (state persists over the wire)
