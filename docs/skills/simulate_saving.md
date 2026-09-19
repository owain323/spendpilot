# simulate_saving

> MCP tool `simulate_saving` — the PROVE step: a before/after scenario
> estimate for one saving action. Read-only; proposing is a separate act.

## When it activates

- User says "prove the saving", "save", "optimize", or names an action
  (`rightsize-ec2`, `cancel-figma`, `annual-zoom`, `route-haiku`).
- `propose_action` calls it internally to attach proof to a proposal.

## Flow

1. Looks the action up in the saving catalog (`sample_data.SAVING_ACTIONS`).
2. Computes monthly/annual deltas and expected saving percentage.
3. Returns the full proof: before/after, evidence, risk, and the label
   "scenario estimate from sample data — not a realized saving".

## Boundaries & refusal cases

- Unknown action id: returns `error` plus the list of known actions —
  a structured error surface, never a guess.
- All figures are scenario estimates; the wording is contract-tested so the
  demo can never present them as realized savings.
- Pure function: no state writes, no ledger entries.

## Linked tests

- `tests/test_tools.py::TestSimulateSaving` (before/after, unknown-action
  surface, 12x annualization, every action provable)

## Evidence

- `docs/evidence/mcp-roundtrip.txt` steps 4-5 (valid + error paths over
  the wire)
