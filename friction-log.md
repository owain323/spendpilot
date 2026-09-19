# Friction Log — SpendLatch build

> Format per entry: task attempted / steps / expected vs actual / severity / workaround / actionable suggestion.
> This log feeds the hackathon's Friction Log bonus (up to 10%).

| Date | Task | Expected vs actual | Severity | Workaround | Suggestion |
|---|---|---|---|---|---|
| 2026-09-18 | Bootstrap MCP server over Streamable HTTP | Expected: client negotiates 2025-11-25 on first connect. Actual: the probe inherited the OS system proxy, which routed 127.0.0.1 through it and returned 502 | High | Force NO_PROXY=127.0.0.1,localhost inside the probe before any HTTP client builds its trust_env | SDK HTTP clients should exempt loopback by default; document proxy behavior in FastMCP transport docs |
| 2026-09-18 | Capture MCP server stderr in a probe | Expected: subprocess.PIPE captures startup errors. Actual: an SSE server logs continuously; the undrained pipe filled and deadlocked the server mid-probe (hung 5 minutes) | High | Redirect child stderr to a temp file, read only on failure; never hold an undrained pipe on a chatty server | Python docs should warn that PIPE + long-lived servers = deadlock; a drain thread or file is mandatory |
| 2026-09-18 | Repo-wide SHA256 manifest on Windows | Expected: manifest hashes match a fresh clone. Actual: 8 files had CRLF on disk (editor + shell-redirect artifacts) while git stores LF — CI integrity gate went red on bytes no clone could reproduce | High | Normalize everything to LF; add a CRLF hard-gate to the manifest tool that skips binaries (PNGs legitimately contain 0x0D0A) | Byte-stable reproducibility needs .gitattributes AND a generator that refuses CRLF, not just editor discipline |
| 2026-09-18 | CI installed mcp 2.2.0 (pinned >=1.12) | Expected: latest SDK is compatible. Actual: 2.x is a breaking major release — FastMCP server exited at boot, and the probe's discarded stderr made it undiagnosable for one CI cycle | High | Pin mcp>=1.12,<2; surface child stderr tail in probe failures | Major-version floats on a security-sensitive dependency are a reproducibility hazard; pin the line |
| 2026-09-18 | Bind approval to an authenticated session | Expected: token->workspace registry could live inside the token's own workspace file. Actual: approve looked up the registry in the wrong file twice (anonymous workspace, then wrong lookup order) — two rounds of chicken-and-egg | Medium | Move the registry to a neutral file (data/auth-sessions.json) that is readable before any workspace is known | Identity/lookup tables must exist outside the resource they grant access to; document the resolution order |
| 2026-09-18 | Hidden holdout generator for the benchmark | Expected: rescaling amounts preserves judgment structure. Actual: per-month random jitter on task_volume destroyed the cost-per-task drift shape one case is built on (23/24 on first run) | Medium | One scale factor per provider so trend SHAPE survives transformation | Derived-benchmark generators must transform levels, not trends — trend shape IS the label |


## Amazon-ecosystem entries (Alexa+ track / MCP / Devpost)

These follow the hackathon's friction-log template field by field.

### 2026-09-19 — Alexa+ track: authorization model vs. the simulated experience

- **What we tried:** Mapping the Alexa+ track's "agent acts for the user"
  model onto SpendLatch's action loop: agent proposes, a signed mandate
  gates execution, every refusal is logged.
- **What worked:** The track rubric rewards exactly the shape we froze —
  proof of human authorization, bounded scope, audit trail. Building the
  approval as a stand-in for Alexa+ account linking (authenticated web
  session mints a single-use HMAC mandate) kept the demo zero-credential
  while keeping the authorization semantics real.
- **What failed:** The first approval design let the chat surface approve
  by self-reporting ("approver=human"). On the MCP surface that proves
  nothing — an unauthenticated caller can claim anything. We had to
  invert it: the MCP surface refuses approval by design; only the
  authenticated web session can sign.
- **What surprised us:** The refusal path became the demo's strongest
  moment. Judges (and our own probes) trusted the system more after
  watching it say no than after watching it execute.
- **What we want changed:** A public Alexa+ account-linking sandbox (or
  AP2 verifiable-credential test harness) so hackathon projects can bind
  mandates to a real identity provider instead of an honest local stand-in.
- **Would we use it again:** Yes — the simulate-the-surface, keep-the-
  semantics-real approach is how we will prototype any assistant-track
  project from now on.

### 2026-09-19 — MCP protocol versioning on the Alexa+ runtime hook

- **What we tried:** Serving the tool layer as MCP over Streamable HTTP,
  negotiating protocol 2025-11-25 (the track minimum), plus an MCP Apps
  (SEP-1865) approval card as a ui:// resource.
- **What worked:** Pinning `mcp>=1.12,<2` and asserting the negotiated
  protocol version in an over-the-wire probe (`tools/mcp_roundtrip.py`)
  inside both pytest and CI — the runtime hook is proven by execution,
  not by README.
- **What failed:** A floating `>=` pin pulled mcp 2.2.0 in CI, where
  `mcp.server.fastmcp` no longer exists; the server died at boot and the
  probe's discarded stderr hid the cause for one cycle. (Also see the
  table entries above for the proxy-502 and stderr-deadlock traps.)
- **What surprised us:** SEP-1865 hosts disagree on what "support" means —
  serving the resource with the right mime profile is verifiable, but
  host-rendered appearance is not. We graded that claim unverified in
  EVIDENCE.md rather than imply it.
- **What we want changed:** A published protocol-compatibility matrix per
  host (Claude / ChatGPT / Goose / Alexa+) with a reference client, so
  "works over MCP" stops meaning "works on the one host we tried".
- **Would we use it again:** Yes, with the pin and the wire probe from
  day one. The 2026-07-28 MCP revision (stateless model, MCPServer
  rename) is scheduled post-hackathon; the legacy negotiation path is a
  safety valve, not a permanent home.

### 2026-09-19 — Devpost submission flow (and the evidence behind it)

- **What we tried:** Treating the submission page as a claims matrix:
  every sentence on Devpost must bind to a runnable artifact
  (`docs/CLAIMS.md`), and every artifact must be reproducible by a judge
  in 5 minutes with zero credentials (`docs/JUDGE-REPRODUCTION.md`).
- **What worked:** Writing the claims matrix BEFORE the submission text.
  Three claims died at the matrix stage (a "hidden holdout" that was
  really a derived invariance suite; an "independent verifier" that was
  really a same-secret consistency check; an "independent bill
  reconciliation" whose line items are derived by the same module) —
  downgrading them before submission is cheaper than being caught.
- **What failed:** Evidence files drifted stale within a day of behavior
  changes (the e2e transcript still described the old approval model).
  Nothing in the flow forces evidence to be re-generated when code moves;
  we added a CI freshness gate for exactly this.
- **What surprised us:** Demo-video scope creep. Recording early froze
  claims we later downgraded; re-recording cost more than the matrix did.
- **What we want changed:** A structured "evidence links" field in the
  Devpost form (per claim, not one links blob) — it would push every team
  toward claim-to-evidence binding.
- **Would we use it again:** Yes. The claims-matrix-first order is now
  our default for any judged submission.

> Related follow-up (separate work order, not implemented here): the AWS
> Builder path — an optional LLM planner layer via Bedrock + Strands on the
> same 13 tool calls, with AgentCore as the deployment target. Its friction
> entries land with that work order; this project references it only as
> planned scope in README's roadmap.

### 2026-09-19 — AWS Builder path: Strands + Bedrock LLM planner

- **What we tried:** An optional LLM planner (Strands SDK + Bedrock) that
  converts free-form language into a structured SpendIntent for the
  deterministic brain to route — the LLM never approves, signs, or executes.
- **What worked:** The OFF-by-default flag (`SPENDLATCH_LLM=bedrock`) plus
  lazy Strands/Bedrock imports: CI and judges run with zero AWS dependencies,
  and the 22 mocked-layer tests prove intent mapping and fallback without a
  billable call. Strands' `Agent(model=BedrockModel(...))` kept the live
  path to three lines.
- **What failed:** Structured-output discipline was the whole game. The
  model will eventually emit fenced JSON, prose around the JSON, stringly
  amounts, or a key you never asked for (our mock suite includes an
  `"execute": true` smuggle attempt). Every one of those must parse to
  "abstain and fall back" — a permissive parser here is an authority leak.
- **What surprised us:** The most valuable planner output was a DENIAL. A
  default-deny policy gate turned "buy $200 of API credits" into the demo's
  clearest ten-second story: the agent understands the request perfectly and
  still refuses, with a logged reason. Understanding without authority reads
  as safety, not weakness.
- **What we want changed:** Bedrock model ids are region/account-specific
  and there is no cheap "is this model id live?" preflight short of calling
  it — a lightweight availability check (or an alias like "sonnet-latest")
  would make smoke instructions reproducible across accounts. Also: a
  Strands mock client in the SDK itself; everyone writing tests currently
  hand-rolls the fake.
- **Would we use it again:** Yes — Strands + Bedrock is the fastest path
  from "python function" to "managed agent loop" we have used, and the
  pay-per-call cost model fits hackathon scale. Next step in this repo:
  AgentCore deployment of the same planner, post-hackathon.
