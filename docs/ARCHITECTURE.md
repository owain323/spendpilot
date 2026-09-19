# Architecture — annotated walkthrough

Three figures, one story: **one tool layer, three surfaces, one mandate gate.**
Every component below says what it is, why it exists, where it lives, and what
proves it works. Figures follow the AGC chart spec v1.1 (800px logical canvas,
8px grid, semantic palette, evidence badge).

> Badge legend: the cyan MACHINE-VERIFIED pill on each figure means the
> figure's content is exercised by runnable checks (`run_checks.py`), not
> asserted by hand.

---

## Figure 1 — System architecture

![One tool layer, three surfaces, one mandate gate](diagrams/fig1-architecture.png)

[SVG master](diagrams/fig1-architecture.svg) · [alt text](diagrams/fig1-architecture.alt.txt) ·
regenerate: `python tools/make_diagrams.py`

### EXPERIENCE lane

- **Web experience** (`web/` + `agent/backend.py`) — the simulated Alexa+
  surface: voice-first chat (progressive enhancement, keyboard primary),
  evidence-chain cards, mandate and receipt cards, decision-ledger panel.
  Talks to the agent over `HTTPS /api/chat`.
- **MCP Apps hosts** (Claude · ChatGPT · Goose) — external hosts render our
  `ui://spendlatch/approval-card` resource inline when a tool carries the
  `_meta.ui.resourceUri` link (SEP-1865). Verified at protocol level by the
  wire probe (step 7); host-rendered appearance is honestly marked unverified
  in `docs/EVIDENCE.md` (E8).

### ACCESS lane — one implementation, two surfaces

- **Intent routing** (`agent/brain.py`) — deterministic, offline-safe intent
  routing. The demo never depends on an LLM being available; an LLM loop can
  be layered on top without changing a single tool call.
- **MCP server** (`mcp_server/server.py`) — Streamable HTTP, protocol
  2025-11-25, 13 tools, plus the `ui://` MCP Apps resource. This is the same
  code the Alexa+ runtime would mount.

### CORE lane — single source of truth

- **Pure analysis** (`mcp_server/tools.py`) — detect anomalies, prove savings,
  budgets, unit economics. No state side effects; the sealed benchmark scores
  this exact function.
- **Mandate gate** (`mcp_server/actions.py`, the dark node) — the only path
  from advice to action. `propose → approve → execute`; the five gates
  (known · signature · unexpired · single-use · scope cap) are spelled out in
  Figure 2.
- **Provider adapters** (`mcp_server/adapters.py`) — simulated AWS / Figma /
  Zoom / OpenAI operations. Every receipt is labeled `simulated: true`;
  adapters know nothing about mandates, the gate knows nothing about
  providers — that is what makes the gate independently testable.

### STATE lane

- **State** (`store.py`) — budgets, proposals, mandates, receipts, sessions in
  one local JSON file; atomic writes; `SPENDLATCH_STATE` env override for
  tests.
- **Decision ledger** (`ledger.py`) — every alert, hold, suppression, refusal,
  approval, and execution with a one-line reason. Silence is auditable.

### VERIFICATION lane

- **Sealed benchmark** (`benchmarks/run.py`) — three honestly-labeled tiers:
  12 public regression fixtures, 14 independent hand-written cases, and a
  24-case derived invariance suite (mechanical transformations — invariance,
  not generalization). Predictions written to disk before gold labels are
  opened. Reuses the same `analyze_dataset` the product runs.
- **Quality gates** (`run_checks.py`) — one command: pytest (100) + sealed
  benchmark + MCP wire roundtrip + SHA256 integrity + language gate.

---

## Figure 2 — The mandate loop (the part most demos skip)

![Nothing executes on trust — five gates to execution](diagrams/fig2-mandate-loop.png)

[SVG master](diagrams/fig2-mandate-loop.svg) · [alt text](diagrams/fig2-mandate-loop.alt.txt)

Reading order: left to right, top row, then the 180-degree wrap into row two.

1. **Propose** — the agent attaches its proof (before/after scenario estimate,
   evidence chain, computed confidence) to a bounded action: one provider,
   one operation, a dollar cap. Idempotent per action.
2. **Approve** — the human authorizes; the server issues a signed mandate:
   HMAC-SHA256 over a canonical payload (fixed `SIGNED_FIELDS` whitelist, so
   bookkeeping fields can never invalidate or fake a signature), single-use,
   scope-capped at the current bill, 15-minute expiry, random nonce. An honest
   local stand-in for AP2 verifiable credentials — same control-flow shape.
3. **Mandate valid?** — the five gates, each verified separately and each
   logging its own refusal: known mandate → signature match → unexpired →
   single-use → scope cap (the live bill must not exceed what was approved).
4. **Execute → Receipt** — only through all five gates does the adapter run;
   the receipt (changes, rollback path, `simulated: true`) lands in the
   ledger and on screen.
5. **Refuse** — any gate fails: structured error, ledger sequence number, no
   side effects. Verified by 20 tests in `tests/test_actions.py`, including
   forged-signature, expired, replayed, and scope-drifted mandates.

---

## Figure 3 — Claims-to-evidence map

![Every claim is one command away from reproduction](diagrams/fig3-evidence-map.png)

[SVG master](diagrams/fig3-evidence-map.svg) · [alt text](diagrams/fig3-evidence-map.alt.txt)

Five representative claims from `docs/CLAIMS.md` (full matrix: C1–C12), each
linked by its reproduction command to the artifact that proves it:

| Claim | Command | Artifact |
|---|---|---|
| Detection quality (12 sealed cases, P/R 1.0) | `python benchmarks/run.py` | `benchmarks/results/metrics.json` |
| Action-loop security (4 attack classes refused) | `pytest -q` | `tests/test_actions.py` |
| MCP wire compliance (13 tools, spec 2025-11-25) | `python tools/mcp_roundtrip.py` | `docs/evidence/mcp-roundtrip.txt` |
| MCP Apps surface (ui:// resource + tool link) | roundtrip step 7 | `web/mcp-apps/approval-card.html` |
| End-to-end web flow (9 judge criteria) | `python tools/e2e_flow.py` | `docs/evidence/e2e-flow.txt` |

The rule: **nothing ships without both sides** — a claim without a runnable
proof is deleted from the claims matrix, and a proof without a claim is
scope creep.

---

## Design invariants (what future changes must not break)

1. `tools.py` stays pure; all side effects flow through `store.py`/`ledger.py`.
2. Every execution passes the mandate gate; adapters never see an unverified
   request.
3. Signing covers exactly `SIGNED_FIELDS`; status and bookkeeping live outside
   the signed payload.
4. Every refusal is a ledger entry with a reason — silence is a decision.
5. Savings figures are scenario estimates and are labeled as such everywhere.
6. One implementation, three surfaces (MCP, web agent, sealed benchmark) —
   never fork the analysis.
