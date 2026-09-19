# set_budget

> MCP tool `set_budget` — persist a monthly budget for a category.
> Cross-session state: it survives restarts and page closes.

## When it activates

- User says "set a $300 budget for cloud", "budget 500 for ai-api".

## Flow

1. Validates the limit (non-positive values are rejected).
2. Persists to the workspace state file (atomic write).
3. Records a `budget` event in the decision ledger — state changes are
   decisions too.
4. Confirms with the saved limit; the agent remembers across sessions.

## Boundaries & refusal cases

- Non-positive limits are rejected, not clamped.
- Budgets are per-category; unknown categories are accepted (forward-compat)
  but only known categories show spend in `budget_status`.
- This is the only tool besides `propose_action` that mutates state without
  a mandate — by design: watching a budget moves no money.

## Linked tests

- `tests/test_tools.py::TestBudgets` (persistence, rejection, logging)
- `tests/test_store.py` (state roundtrip)

## Evidence

- `docs/evidence/e2e-flow.txt` step 6 (set -> warn status)
