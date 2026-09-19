# Judge Reproduction Protocol

Zero credentials required. Expected total time: under 5 minutes.
**Any missing condition is a failed reproduction.**

## Steps

```bash
# 1. Python >= 3.11; clone the repo, enter it
pip install -e .          # or: pip install mcp fastapi uvicorn pytest

# 2. Test suite + language gate
python run_checks.py
# PASS criteria: all tests pass; "language gate: OK"

# 3. Sealed benchmark
# three benchmark tiers (public fixtures / derived invariance suite / independent cases)
python benchmarks/run.py              # 12 public regression fixtures
python benchmarks/run.py --derived    # 24 derived-invariance cases (generated on first run:)
python tools/make_derived.py          # <- regenerates benchmarks/derived/ deterministically (seeded, gitignored)
python benchmarks/run.py --independent  # 14 hand-authored independent cases
# PASS criteria: prints BENCHMARK_OK; results/metrics.json shows
#   flag_precision 1.0, flag_recall 1.0 on the 12 shipped cases

# 4. MCP surface (Streamable HTTP, spec 2025-11-25) — one command, real client
python tools/mcp_roundtrip.py
# PASS criteria: prints MCP_ROUNDTRIP_OK after negotiating protocol
#   2025-11-25, listing all 13 tools, calling the read-only surface, running
#   the full propose -> approve -> execute loop over the wire (with bogus and
#   replayed mandates refused), serving the ui:// MCP Apps resource with the
#   mcp-app mime profile, and showing every step in the decision ledger
#   (spawns its own server, zero setup)

# 5. Web experience (simulated Alexa+)
python -m agent.backend         # http://127.0.0.1:8200
#   or drive it headlessly:
python tools/e2e_flow.py        # prints E2E_FLOW_OK after all 9 criteria
```

PASS criteria for the web flow (all reproduced by `tools/e2e_flow.py`):

1. On first open, the agent speaks FIRST (anomaly cards appear unprompted)
2. `prove the saving` returns a before/after card with proof steps, the label
   "scenario estimate", and a proposal id on the table
3. `approve` returns a signed mandate: 64-char hex signature, scope cap equal
   to the current bill, 15-minute expiry
4. `execute` returns a receipt from the simulated provider adapter
5. `execute` again is refused — mandates are single-use, and the refusal is
   logged
6. `set a $300 budget for home` returns a budget card at warn status (82.0%)
7. Closing and reopening the page restores the budget (cross-session memory)
8. `why didn't you tell me` returns the decision ledger with hold/suppress
   entries and reasons; propose/approve/execute entries are present too
9. Anthropic appears as a KEEP card ("do NOT cut it"), never as an anomaly

## Notes for judges

- All data is synthetic; nothing leaves your machine (`data/state.json` only).
- Provider adapters are simulated and labeled `simulated: true` in every
  receipt; the mandate gate around them is real and fully tested.
- The mandate signature is HMAC-SHA256 with a per-installation key — an honest
  local stand-in for AP2 verifiable credentials (same control-flow shape).
- Voice input is a progressive enhancement (Web Speech API); the keyboard path is primary.
