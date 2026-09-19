# Scope Freeze

> Effective 2026-09-18. **No additional detection classes will be added before submission.**

## Supported — and only these

Detection classes (5):

1. Month-over-month spend spike (pct + absolute thresholds)
2. Sustained multi-month trend
3. Silent trial-to-paid conversion
4. Zombie subscription (unused >= 45 days while billing)
5. Cost-per-task drift for AI API providers (the canary metric)

Tool surface (13 MCP tools; the original freeze listed 9 - six were added during the security and voice hardening rounds, all within the frozen mission): `spending_overview`, `detect_anomalies`,
`simulate_saving`, `set_budget`, `budget_status`, `list_subscriptions`,
`unit_economics`, `proactive_briefing`, `decision_ledger`.

## Safety invariants

1. The agent never modifies, cancels, or purchases anything. It proposes; the human decides.
2. Missing or insufficient evidence is held and logged — never fabricated into a verdict.
3. A provider with fewer than 3 months of history returns `eligible: false` with a reason, not a guess.
4. All savings figures are labeled "scenario estimate".
5. Suppressed and held decisions are recorded in the ledger with reasons.

## Explicitly out of scope

- Real bank / card / provider API connections (synthetic data + future snapshot import only)
- Persistent monitoring dashboards (the agent pushes cards; there is no chart wall)
- Automatic cancellations, payments, or purchases
- Multi-currency conversion, tax advice, investment advice
- "Supports 50 providers" breadth claims — we do high-confidence detection on a declared surface

---

## Revision 1 (2026-09-18, security hardening — approved deviation)

External security review found that approval was not bound to any
authenticated caller (any MCP client could self-report approver="human").
The following changes deviate from the frozen surface and are SECURITY
FIXES, not scope creep:

- `approve_action` now requires an authenticated web session token; the
  MCP surface refuses approval and logs the refusal. The `approver`
  caller parameter was removed (the TTL caller parameter was removed too:
  expiry is server policy, fixed at 900s).
- Mandates now sign a `proof_hash` (the evidence the human approved) and
  an `approval` block (surface + session fingerprint + challenge).
  Execution re-derives the proof hash and refuses on drift.
- Execution is serialized under a process lock: single-use holds under
  concurrency.
- State is workspace-isolated (per authenticated web session; anonymous
  and MCP workspaces are separate files) and fails closed on corruption
  (corrupt file preserved, never silently reset).
- The ledger is hash-chained (tamper-evident).
- Benchmarks: the 12 cases are honestly labeled PUBLIC REGRESSION
  FIXTURES; a 14-case INDEPENDENT hand-written suite covers decision
  structures the fixtures do not; a 24-case DERIVED INVARIANCE SUITE
  (seeded generator, labels gitignored) proves transformation invariance
  only — never presented as generalization evidence. Tool count unchanged at 13.
