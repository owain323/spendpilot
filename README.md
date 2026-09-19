# SpendPilot

[![CI](https://github.com/owain323/spendpilot/actions/workflows/ci.yml/badge.svg)](https://github.com/owain323/spendpilot/actions/workflows/ci.yml)

**Live demo:** https://spendpilot.owain32380.cn — the web experience and the
MCP endpoint (`/mcp`, Streamable HTTP) are both served publicly. All
providers are simulated; no credentials exist anywhere.

**MCP protocol & compatibility**

| | |
|---|---|
| Protocol | MCP 2025-11-25 (the track minimum) over Streamable HTTP |
| SDK | mcp>=1.12,<2 - pinned: mcp-sdk 2.0.0 removed mcp.server.fastmcp (upgrade = boot failure) |
| Verified | against our own Alexa+ integration round-trip probe (tools/mcp_roundtrip.py) |
| Upgrade path | 2026-07-28 revision (MCPServer rename, stateless model) planned post-hackathon - the legacy negotiation path is a safety valve, not a permanent home |

**An agentic spend-remediation copilot for AI and cloud teams — it watches your bills across providers, proves the next move before proposing it, and executes only inside a mandate signed by an authenticated human session. Every decision, including every refusal, is recorded.**

> It doesn't wait for you to ask. It proves before it proposes. And it never moves a cent without your signed authorization.

Built for the Amazon *Build, Ship, Shape* Hackathon (Alexa+ track). The tool
layer is a self-hosted **MCP server over Streamable HTTP** (spec 2025-11-25)
with an **MCP Apps** approval surface (SEP-1865); the web app is a
**simulated Alexa+ experience** — voice-first conversation, rich cards and
carousels, and state that survives across sessions.

---

## Why 2026 needs this

Token prices fell ~280x in two years, yet AI bills kept climbing — agents fan
out into 10-200 metered calls per task. The bill problem is no longer per-token
price; it is **usage patterns and unit economics**. SpendPilot watches cost per
task (the canary), not just total spend (the smoke alarm) — and it does the same
for the rest of the household stack: cloud, SaaS seats, trials, subscriptions.

And in 2026 the bar for agents moved again: agentic-payment protocols (AP2,
ACP, x402) all converged on the same shape — an agent that touches money must
carry **proof of human authorization, bounded in scope and time, with an audit
trail**. SpendPilot implements that shape end to end.

## The action loop — the part most demos skip

```
detect -> prove -> propose -> [human approves] -> signed mandate -> execute -> receipt
```

- **propose** — the agent attaches its proof to a concrete, bounded action
  (one provider, one operation, a dollar cap).
- **approve** — authorization is bound to an authenticated web session:
  the browser mints a session token, and ONLY a request carrying it can
  approve. The MCP surface refuses approval by design (an unauthenticated
  caller self-reporting "approver=human" proves nothing), and the refusal
  is logged. The mandate — HMAC-SHA256, single-use, scope-capped,
  15-minute expiry — records the approving session fingerprint and the
  proof hash of exactly what was approved. This is a local stand-in for
  Alexa+ account linking / AP2 verifiable credentials.
- **execute** — the provider adapter runs ONLY if the mandate verifies:
  signature, expiry, single-use under concurrency (process lock), proof
  hash still matching the approved evidence, and scope drift (if reality
  moved past the cap, execution is refused and re-approval is required).
- **receipt** — the adapter's report lands in the decision ledger.
- **every refusal is logged** — unknown, forged, expired, replayed, or
  drifted mandates all produce structured refusals with ledger entries.
  Nothing executes on trust.

## Why it is not another expense tracker

- **Proactive, not reactive** — open the app and the agent speaks first: it has
  already swept your providers and found what needs attention.
- **Proof before proposals** — every saving suggestion ships with a
  before/after scenario estimate, a computed confidence level, a risk note, and
  the evidence chain. Estimates are never presented as realized savings.
- **Judgment, including refusal** — when spend growth tracks real value (API
  costs scaling with a launch), the agent says *do not cut this* and shows why.
- **Silence is auditable** — low-confidence findings are held, repeats are
  suppressed, and **every decision is logged with a reason** in the decision
  ledger. Ask "why didn't you tell me?" and get a real answer. Overrule any
  entry (`challenge #3`) and your overrule becomes context.
- **Cross-session memory** — budgets, acknowledgements, challenges, mandates,
  receipts, and the ledger persist server-side. Close the page, come back
  tomorrow: it remembers.
- **MCP Apps native** — `propose_action` links an interactive approval card
  (`ui://spendpilot/approval-card`, `text/html;profile=mcp-app`) that hosts
  render inline; the same HTML speaks the postMessage JSON-RPC bridge.
- **The MCP server is the product** — 13 typed tools, 100 tests, a sealed
  benchmark; not a thin wrapper around an existing API.

## Architecture

```
web/ (simulated Alexa+ experience)
  │  voice-first chat UI · evidence-chain cards · mandate/receipt cards · ledger panel
  ▼
agent/backend.py (FastAPI)  +  agent/brain.py (deterministic intent routing;
  │                                        LLM loop is an optional layer)
  ▼
mcp_server/server.py — MCP over Streamable HTTP (spec 2025-11-25, 13 tools)
  │                   + MCP Apps resource ui://spendpilot/approval-card (SEP-1865)
  ▼
mcp_server/tools.py (pure analysis — single source of truth)
  ├── sample_data.py  synthetic multi-provider bills, 6 months + task volumes
  ├── store.py        local JSON persistence = cross-session state
  ├── ledger.py       decision event stream (alert / suppress / hold / refuse / ...)
  ├── actions.py      mandate-gated loop: propose -> approve -> execute
  └── adapters.py     simulated provider adapters (aws / figma / zoom / openai)

benchmarks/           two-phase evaluation (predictions sealed before gold
                      labels are opened): 12 public regression fixtures + a
                      24-case hidden holdout (labels kept out of the repo)
docs/                 CLAIMS.md · SCOPE-FREEZE.md · JUDGE-REPRODUCTION.md · EVIDENCE.md
                      THREAT-MODEL.md (T1-T10 threats, defense, proof pointers)
                      PATTERNS.md (reusable modules for the next project)
SHA256SUMS.txt        whole-repo integrity manifest
```

`tools.py` is implemented once and exposed three ways: over MCP, in-process
for the web agent, and inside the sealed benchmark. One implementation, three
surfaces.

Annotated walkthrough with figures: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
(system diagram, the mandate loop, and the claims-to-evidence map).

## Interface notes

- Icons: [Lucide](https://lucide.dev) (ISC license), inlined as SVG — no
  icon font, no build step, no npm. The app itself is three static files.
- Voice input is deliberately not surfaced in the UI: Web Speech API
  support varies by browser, and a control that only works sometimes is
  worse than no control. The keyboard is the primary path (the demo
  video shows voice running in Chrome).

## Quickstart

Requires Python ≥ 3.11. Zero credentials needed.

```bash
pip install -e .            # or: pip install mcp fastapi uvicorn pytest
python run_checks.py        # tests + sealed benchmark + MCP wire roundtrip + integrity + language

# Surface 1: the MCP server (Streamable HTTP)
python -m mcp_server.server          # http://127.0.0.1:8101/mcp
python tools/mcp_roundtrip.py        # or let a real MCP client prove it end to end

# Surface 2: the simulated Alexa+ web experience
python -m agent.backend              # http://127.0.0.1:8200
python tools/e2e_flow.py             # or let the probe drive the full flow
```

Open http://127.0.0.1:8200 — the agent opens the conversation. Try:

- `anything unusual?`
- `prove the saving` — then `approve` — then `execute`
- `execute` again — watch the replay get refused and logged
- `cost per task`
- `set a $300 budget for home`
- close the tab, reopen it — your budget is still there
- `why didn't you tell me?`

Judges: see [docs/JUDGE-REPRODUCTION.md](docs/JUDGE-REPRODUCTION.md) for the
5-minute, zero-credential reproduction protocol with pass criteria.

## Verification status

| Claim | Evidence |
|---|---|
| 100 automated tests pass (tools, ledger, store, actions, benchmark, API, MCP wire) | `docs/evidence/test-run.txt` |
| Detection: public regression 12/12 + hidden holdout 24/24 (flag P/R 1.0, keep/hold 1.0) | `benchmarks/results/metrics.json`, `benchmarks/results/holdout-metrics.json` |
| Real MCP client roundtrip: protocol 2025-11-25, 13/13 tools, action loop + ui:// resource over the wire | `docs/evidence/mcp-roundtrip.txt` |
| End-to-end web flow (9 criteria, incl. mandate replay refusal) | `docs/evidence/e2e-flow.txt` |

Full claim-to-evidence binding: [docs/CLAIMS.md](docs/CLAIMS.md).
Graded evidence register (what is NOT verified is marked so): [docs/EVIDENCE.md](docs/EVIDENCE.md).

## Security & privacy

- All billing data is **synthetic sample data**; no real accounts, credentials,
  or network calls to providers. Adapters are labeled `simulated: true`.
- State lives in one local JSON file (`data/state.json`, overridable via the
  `SPENDPILOT_STATE` env var). Nothing leaves your machine.
- The agent proposes; the human decides. Execution requires a signed,
  single-use, scope-capped, expiring mandate — and every refusal is logged.

## Roadmap (post-hackathon)

- Optional LLM loop (Strands + a local model) layered on the same tool calls
- Import real usage snapshots (CSV / provider exports) behind an explicit,
  local-only ingest path
- Production mandate signing bound to device keys / AP2 verifiable credentials,
  and real provider adapters behind the same mandate gate

## License

MIT — see [LICENSE](LICENSE).
