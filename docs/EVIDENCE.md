# Evidence Register

Graded evidence model. Unverified levels are marked unverified — never
blended into verified claims.

| Level | Meaning | Status |
|---|---|---|
| E1 | Unit/integration suite passes locally (tools, ledger, store, actions, API): 100 tests | ✅ verified — `docs/evidence/test-run.txt` |
| E2 | Benchmarks, three tiers: 12 public regression fixtures 12/12; 14 independent hand-written cases 14/14 (public labels in `benchmarks/gold/`); 24-case derived invariance suite 24/24 (labels gitignored; seeded generator; invariance proof, NOT generalization evidence) | ✅ verified — `benchmarks/results/metrics.json`, `benchmarks/results/independent-metrics.json`, `benchmarks/results/derived-metrics.json` |
| E3 | MCP roundtrip over the wire: protocol 2025-11-25 negotiated, 13/13 tools listed and called, state persists over the wire | ✅ verified — `docs/evidence/mcp-roundtrip.txt` (runs inside pytest and the quality gate) |
| E4 | End-to-end web flow, 9 criteria (opening → prove → approve → execute → replay refusal → budget → reopen memory → ledger → KEEP judgment) | ✅ verified — `docs/evidence/e2e-flow.txt`, reproducible via `tools/e2e_flow.py` |
| E5 | Real provider data (bank/card/cloud APIs) | ⬜ **unverified — not claimed.** Demo uses synthetic data only. |
| E6 | AWS-hosted deployment (Bedrock/AgentCore) | ⬜ **unverified — not claimed.** Optional bonus path, pending account access. |
| E7 | Mandate security invariants: forged / expired / replayed / scope-drifted mandates refused, every refusal logged | ✅ verified — `tests/test_actions.py` (20 tests), `docs/evidence/mcp-roundtrip.txt` step 6 |
| E8 | MCP Apps (SEP-1865): ui:// resource served with mcp-app mime profile, tool _meta link, bridge handshake in HTML | ✅ verified at protocol level — `docs/evidence/mcp-roundtrip.txt` step 7. Host-rendered appearance inside Claude/ChatGPT/Goose: ⬜ unverified — not claimed. |

Rule: timings and local measurements describe this one local reproduction
only. They are not production performance claims.
