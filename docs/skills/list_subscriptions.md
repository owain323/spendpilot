# list_subscriptions

> MCP tool `list_subscriptions` — recurring subscriptions with usage flags;
> the zombie-detection surface.

## When it activates

- User asks about "subscriptions", recurring spend, unused seats.

## Flow

1. Selects providers in the recurring categories (saas, home).
2. Attaches `last_used_days` from evidence; flags `zombie` at >= 45 days.
3. Sorts descending by monthly amount; exposes the threshold in the payload
   so the number 45 is never a magic constant to the caller.

## Boundaries & refusal cases

- Read-only; canceling a zombie goes through propose -> approve -> execute,
  never through this tool.
- A subscription used 44 days ago is NOT flagged (threshold is inclusive at
  45; boundary-covered by the independent suite, case i01/i02).

## Linked tests

- `tests/test_tools.py::TestSubscriptions` (zombie flag, sort, threshold
  exposure)
- `benchmarks/independent/cases.json` i01/i02 (threshold boundaries)

## Evidence

- `docs/evidence/mcp-roundtrip.txt` step 4 (zombie present over the wire)
