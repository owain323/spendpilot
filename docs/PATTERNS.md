# Reusable Patterns — what this repo got right, and where to steal it from

This project solved five problems that almost every agentic demo will hit.
Each pattern is implemented here, tested here, and small enough to lift into
the next project. Read this file before reusing anything — the value is in
the invariants, not the code volume.

## 1. Session-bound authorization boundary

**Problem it solves**: an agent that can execute actions must not accept
self-reported identity. Any surface that lets a caller say
`approver="human"` proves nothing.

**The pattern**:
- The trusted surface (browser) mints a session: server returns a bearer
  token, stores only its hash, and maps hash → workspace id in a registry
  file that lives OUTSIDE every workspace state file.
- Destructive verbs (approve) require a valid token; unauthenticated
  surfaces refuse — loudly, structurally, and in the audit trail.
- The artifact (mandate) signs WHO approved (session fingerprint) and WHAT
  was approved (proof hash), so the audit answers both questions forever.
- Identity/lookup tables must be readable BEFORE the resource they grant
  access to is known. This bit us twice (see friction-log) — put the
  registry in a neutral file, not inside a resource it grants access to.

**Where**: `mcp_server/store.py` (`open_auth_session`, `workspace_for_token`),
`mcp_server/actions.py` (`approve_action`), `agent/backend.py` (`/api/session`).
**Tests**: `tests/test_actions.py::TestAuthorizationBoundary`.

## 2. Workspace-isolated state

**Problem it solves**: a public demo with one shared state file gets
polluted by the first visitor; judges see each other's sessions.

**The pattern**: `state_path()` resolves to `data/workspaces/<id>.json`
per authenticated session; anonymous and machine surfaces get their own
files. A process-wide `set_workspace()` under a request lock keeps
tool-layer signatures unchanged (no path threading).

**Where**: `mcp_server/store.py`, `agent/backend.py`.
**Tests**: `tests/test_store.py::test_workspace_isolation`.

## 3. Hash-chained audit ledger

**Problem it solves**: "the agent logs everything" is worthless if the log
is a mutable JSON array.

**The pattern**: each entry carries `prev_hash` and its own
`sha256(prev_hash + canonical body)`; `verify_chain()` re-derives the whole
retained window and reports the first broken seq. Honest scope: the chain
anchors at the earliest surviving entry (the log is capped), which proves
"nothing in the window was altered" — exactly what an audit trail can claim.

**Where**: `mcp_server/ledger.py` (`record`, `verify_chain`).
**Tests**: `tests/test_ledger.py::TestHashChain`.

## 4. Fail-closed persistence

**Problem it solves**: `except JSONDecodeError: load defaults` silently
erases the audit trail — the exact opposite of what an accountability
product promises.

**The pattern**: a corrupt state file is preserved under a
`.corrupt-<timestamp>` sibling and an error is raised. Repair is a human
decision, never a silent reset.

**Where**: `mcp_server/store.py::load_state`.
**Tests**: `tests/test_store.py::test_corrupt_state_fails_closed_and_preserves_file`.

## 5. Honest three-tier benchmark

**Problem it solves**: gold labels shipped in a public repo can only prove
"the engine matches its own fixtures" — claiming held-out precision from
them is a credibility killer. But a generator-derived "hidden holdout"
overclaims in the opposite direction: its decision structures are identical
to the fixtures by construction, so it can never prove generalization.

**The pattern**: three evaluation tiers, each named for exactly what it proves —
1. **Public regression fixtures** (seeded, labeled, in-repo): prove the
   engine matches its regression cases. Name them exactly that.
2. **Independent hand-written suite**: cases authored by hand against the
   decision rules — threshold boundaries on both sides, split verdicts on
   identical curves, cross-rule interactions. Not generator output. Labels
   are public; the honesty comes from the authoring trail (each case note
   states the decision structure it isolates), not from secrecy.
3. **Derived invariance suite**: mechanical rescale/rename/time-shift of
   the public fixtures by a seeded generator; labels gitignored so anyone
   can reproduce the cases but the answers are not sitting in the tree.
   Presented strictly as INVARIANCE evidence — never as generalization.
   Aggregate metrics are published; per-case labels are not.

**Transformation discipline**: perturb LEVELS, never trend SHAPES — a
per-month jitter on task volume destroys the cost-per-task drift one case
is built on (this bit us: first run was 23/24, the miss was pure generator
bug, and it was worth catching).

**Where**: `benchmarks/run.py` (default / `--independent` / `--derived`),
`tools/make_derived.py`, `.gitignore` (`benchmarks/derived/`),
`docs/evidence/independent-metrics.json`, `docs/evidence/derived-metrics.json`.

## Probe discipline (applies to all of the above)

Two probes guard the whole system, and both encode the same lessons:

- `tools/mcp_roundtrip.py` — protocol truth: a real MCP client over
  Streamable HTTP against a spawned server subprocess, asserting the
  security boundary (unauthenticated approve → structured refusal).
- `tools/e2e_flow.py` — product truth: session mint → prove → approve →
  execute → receipt → replay-refused → cross-session memory, over the web
  API an actual browser uses.

**Subprocess rules the hard way**: force `NO_PROXY` for loopback before
any HTTP client builds its trust_env; never hold an undrained pipe on a
chatty server (temp file, read on failure); `kill()` then `wait()` before
closing the stderr handle on Windows; pin the SDK line (mcp 2.x broke
FastMCP boot) and surface the child's stderr tail in the failure message.
