# unit_economics

> MCP tool `unit_economics` — cost per 1K tasks per AI provider. Total spend
> is the smoke alarm; cost per task is the canary.

## When it activates

- User asks "cost per task", "unit economics", "canary".
- `analyze_dataset` reuses it internally for the task-drift finding.

## Flow

1. Selects providers that report `task_volume` (AI API providers).
2. Computes cost per 1K tasks per month where both bill and volume exist.
3. Computes drift: month-over-month and since the first month.
4. Marks `canary` when MoM drift >= 15% — unit cost inflating.

## Boundaries & refusal cases

- Providers without task_volume are omitted, never estimated.
- Canary fires on drift alone; volume direction only modulates confidence
  (price up + volume down is the strongest waste signal).
- The 15% threshold is inclusive (independent suite case i13).

## Linked tests

- `tests/test_tools.py::TestUnitEconomics` (exact math, canary fires on
  volume-down, no canary when scaling efficiently, drift window)

## Evidence

- `docs/evidence/mcp-roundtrip.txt` step 4; `docs/evidence/e2e-flow.txt`
  ("cost per task" criterion)
