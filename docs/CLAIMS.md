# Submission Claims Matrix

Every externally visible claim is bound to an evidence artifact and an
approved wording. If a sentence cannot be bound to evidence, it does not ship.

**Do not claim:** production-scale performance, real-provider savings,
"realized" savings (all savings are scenario estimates), arbitrary-provider
coverage, or LLM intelligence we did not measure.
**Do not merge separate runs into one apparent execution.**

| # | Claim | Approved wording | Evidence |
|---|---|---|---|
| C1 | Detection quality | "On 12 public regression fixtures AND on a 24-case hidden holdout (derived by a seeded generator whose labels are kept out of the repo), the detection engine scored flag precision 1.0 and recall 1.0 with keep/hold accuracy 1.0, under a sealed two-phase protocol." | `benchmarks/results/metrics.json`, `benchmarks/results/holdout-metrics.json`, `tools/make_holdout.py` |
| C2 | MCP compliance | "The tool layer is a self-hosted MCP server over Streamable HTTP. A real MCP client roundtrip (official SDK, separate server process) negotiates protocol 2025-11-25, lists all 13 tools, calls the read-only surface with valid structured responses, and verifies state persistence over the wire." | `docs/evidence/mcp-roundtrip.txt`, `tools/mcp_roundtrip.py` |
| C3 | Test suite | "The repository carries 100 automated tests (see `run_checks.py` output); the suite covers tools, ledger, store, actions, benchmark, and API surfaces." | `docs/evidence/test-run.txt` |
| C4 | Proactivity | "The agent opens the conversation with findings; it does not wait to be asked." | demo video, `/api/opening` |
| C5 | Cross-session state | "Budgets, acknowledgements, challenges, mandates, receipts, and the decision ledger persist server-side and survive restarts." | `mcp_server/store.py`, `tests/test_store.py` |
| C6 | Judgment / refusal | "When spend growth tracks real value, the agent refuses to cut it and says why; low-confidence findings are held and logged, not surfaced." | `tests/test_tools.py::TestDetectAnomalies`, decision ledger |
| C7 | Savings figures | "All savings are scenario estimates computed from sample data, labeled as such wherever they appear." | `mcp_server/tools.py::simulate_saving` |
| C8 | Privacy | "The demo runs fully offline on synthetic data; no credentials, no telemetry, nothing leaves the machine." | `README.md` Security & privacy |
| C9 | Benchmark integrity | "Benchmark predictions are sealed to disk before gold labels are read; the holdout labels are not in the public repo (seeded generator only); the protocol is enforced by code structure, not by promise." | `benchmarks/run.py`, `tools/make_holdout.py` |
| C10 | Mandate-gated execution | "Execution requires a signed mandate: HMAC-SHA256, single-use, scope-capped at the bill approved by the human, 15-minute expiry. Unknown, forged, expired, replayed, or scope-drifted mandates are refused with structured errors, and every refusal is logged. The signature is an honest local stand-in for AP2 verifiable credentials." | `tests/test_actions.py` (20 tests), `docs/evidence/mcp-roundtrip.txt` step 6 |
| C11 | MCP Apps surface | "The propose_action tool links an interactive approval card served as a real MCP resource (ui://spendpilot/approval-card, mime text/html;profile=mcp-app per SEP-1865); the card speaks the postMessage JSON-RPC bridge and degrades to a static preview without a host." | `docs/evidence/mcp-roundtrip.txt` step 7, `web/mcp-apps/approval-card.html` |
| C12 | Provider adapters | "Adapters are simulated and labeled simulated: true in every receipt; the mandate gate around them is real." | `mcp_server/adapters.py`, `tests/test_actions.py::TestAdapters` |

*Last verified: 2026-09-18 against the working tree (v0.3.0 — mandate-gated action loop + MCP Apps).*
