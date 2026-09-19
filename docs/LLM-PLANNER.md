# LLM Planner (Strands + Bedrock) — design, boundary, smoke path

**Status: landed, OFF by default.** Set `SPENDPILOT_LLM=bedrock` to enable.
Without the flag (and without AWS credentials) the whole product and the
whole test suite run exactly as before — the deterministic router owns the
conversation.

## What it does

Free-form language the deterministic router cannot parse ("increase our AI
build capacity", "buy 200 dollars of API credits for the eval pipeline") is
converted by the planner into a structured **SpendIntent**:

```
merchant · amount · currency · category · scope · rationale
```

The intent re-enters the deterministic brain (`agent/brain.py::route_intent`)
exactly as if the user had typed a routed phrase:

- **amount > 0** — a NEW spend request. The policy gate
  (`mcp_server/actions.py::evaluate_spend_intent`) is **default-deny**: the
  mandate system only covers proven cost-reduction actions, so the request
  is DENIED with the reason, logged as a refusal, and rendered as a denial
  case card. A category budget, when one exists, makes the denial concrete
  ("$X spent + $Y requested vs $Z/mo limit").
- **merchant only** — a question about that provider, routed to the same
  provider-detail answer as a typed mention (alias table first, then the
  provider roster by name).
- **neither** — graceful abstention, never a guess.

## The boundary (constitution)

The planner ONLY produces the intent. It **never approves, never signs,
never executes**. Parsing is strict: malformed JSON, wrong types, unknown
categories/currencies, smuggled keys, or an explicit `ABSTAIN` all degrade
to the deterministic router. An LLM outage degrades the same way. Tests
(`tests/test_planner.py`, 22 tests) assert that no planner path ever mints
a proposal or a mandate.

## Why these choices

- **Strands + Bedrock**: the hackathon's AWS Builder path; Strands keeps the
  agent loop one import deep, Bedrock keeps credentials in the standard
  AWS environment chain (`AWS_ACCESS_KEY_ID` etc.).
- **Haiku-class default model** (`anthropic.claude-3-5-haiku-20241022-v1:0`):
  intent extraction is structured-output work; the cheapest model that meets
  quality is the honest default for a COST tool. Override with
  `SPENDPILOT_BEDROCK_MODEL`. Model ids are region/account specific — verify
  availability in your Bedrock console before the smoke run.
- **Lazy imports**: `strands`/`boto3` load only inside the live call path, so
  `pip install -e .` and CI carry zero AWS dependencies.

## Manual smoke (real Bedrock; billed to your account; kept OUT of CI)

```bash
pip install -e ".[llm]"
export SPENDPILOT_LLM=bedrock            # Windows: set SPENDPILOT_LLM=bedrock
# AWS credentials from the environment / aws sso login
python -c "from mcp_server import planner; \
print(planner.plan('buy 200 dollars of API credits for the eval pipeline'))"

# then the full product path: the same sentence in the web chat
python -m agent.backend                  # http://127.0.0.1:8200
# -> expect: a DENIED case card + a refuse entry in the decision ledger
```

## Verification

| Claim | Evidence |
|---|---|
| Feature off: deterministic router unaffected | `tests/test_planner.py::TestFeatureFlag` |
| 5 natural-language sentences map to correct SpendIntent fields (mocked Bedrock) | `tests/test_planner.py::TestParseIntent` |
| Malformed/abstinent/smuggled output falls back, never crashes | `tests/test_planner.py::TestParseIntent` (parametrized) |
| Spend intent -> DENIED + ledger refusal + zero mandates/proposals | `tests/test_planner.py::TestSpendIntentPolicy` |
| Live Bedrock path | manual smoke above — **unverified in CI by design** (cost) |
