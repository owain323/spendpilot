"""LLM planner — free-form language in, structured SpendIntent out.

The deterministic brain routes everything it can; this planner converts the
unrouted residue ("increase our AI build capacity") into a SpendIntent the
brain can route on. Strands SDK + AWS Bedrock underneath.

HARD BOUNDARY (constitution): the planner ONLY produces the intent. It never
approves, never signs, never executes — the SpendIntent enters the same
deterministic policy gate as a typed phrase, and new spend is default-deny
(see actions.evaluate_spend_intent).

OFF BY DEFAULT: the feature activates only when SPENDLATCH_LLM=bedrock.
Without it (and without AWS credentials) every test passes and the
deterministic router handles everything. Live Bedrock calls stay out of CI.

Manual smoke (real Bedrock, billed to your account):
    pip install -e ".[llm]"
    set SPENDLATCH_LLM=bedrock            # powershell: $env:SPENDLATCH_LLM="bedrock"
    set SPENDLATCH_BEDROCK_MODEL=...      # optional override, see MODEL_ID
    python -c "from mcp_server import planner; print(planner.plan('buy 200 dollars of API credits for the eval pipeline'))"
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

# Haiku-class by default: intent extraction is a structured-output task, and
# the cheapest model that meets quality is the honest choice for a COST tool.
# Override with SPENDLATCH_BEDROCK_MODEL (model ids are region/account
# specific — verify availability in your Bedrock console before smoke runs).
MODEL_ID = os.environ.get("SPENDLATCH_BEDROCK_MODEL",
                          "anthropic.claude-3-5-haiku-20241022-v1:0")

# Categories the deterministic layer knows. "other" lets the model answer
# honestly instead of forcing a wrong bucket; policy still default-denies.
KNOWN_CATEGORIES = {"cloud", "ai-api", "saas", "home", "subscription", "other"}

SYSTEM_PROMPT = """You convert one user sentence into a SpendIntent JSON object.

Output ONLY a JSON object with exactly these keys, or the word ABSTAIN:
  merchant  - string: vendor/provider name, or null if none is named
  amount    - number: money the user wants to SPEND, or null if none
  currency  - string: ISO 4217 code, default "USD"
  category  - one of "cloud", "ai-api", "saas", "home", "subscription", "other"
  scope     - string: what the spend is for (e.g. "eval pipeline"), or null
  rationale - string: one sentence restating the user's goal

Rules: never invent amounts; if the sentence is not about spending or
providers, output ABSTAIN; no prose, no markdown fences."""


@dataclass(frozen=True)
class SpendIntent:
    """The ONLY thing the LLM is allowed to produce. Routing and policy live
    in the deterministic layer; this object is data, not authority."""
    merchant: str | None
    amount: float | None
    currency: str
    category: str
    scope: str | None
    rationale: str

    def as_dict(self) -> dict:
        return {"merchant": self.merchant, "amount": self.amount,
                "currency": self.currency, "category": self.category,
                "scope": self.scope, "rationale": self.rationale}


def enabled() -> bool:
    """Feature flag: OFF unless explicitly opted in."""
    return os.environ.get("SPENDLATCH_LLM") == "bedrock"


def parse_intent(raw: str) -> SpendIntent | None:
    """Strict parse of the model's output. Anything malformed, abstinent, or
    out-of-vocabulary returns None — the caller falls back to the
    deterministic router. The LLM gets no benefit of the doubt."""
    text = raw.strip()
    if not text or text.upper().startswith("ABSTAIN"):
        return None
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if not set(data) <= {"merchant", "amount", "currency", "category", "scope", "rationale"}:
        return None

    merchant = data.get("merchant")
    if merchant is not None and not isinstance(merchant, str):
        return None
    amount = data.get("amount")
    if amount is not None:
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            return None
        if amount < 0:
            return None
        amount = float(amount)
    currency = data.get("currency", "USD")
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        return None
    category = data.get("category", "other")
    if category not in KNOWN_CATEGORIES:
        return None
    scope = data.get("scope")
    if scope is not None and not isinstance(scope, str):
        return None
    rationale = data.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        return None
    return SpendIntent(merchant=merchant, amount=amount, currency=currency,
                       category=category, scope=scope, rationale=rationale.strip())


def _strands_complete(prompt: str) -> str:
    """Real Bedrock call via the Strands SDK. Imported lazily so the repo —
    and CI — runs with zero AWS dependencies when the feature is off."""
    from strands import Agent  # noqa: PLC0415 - optional dependency
    from strands.models import BedrockModel  # noqa: PLC0415

    agent = Agent(model=BedrockModel(model_id=MODEL_ID), system_prompt=SYSTEM_PROMPT,
                  callback_handler=None)
    return str(agent(prompt))


def plan(text: str, llm_fn=None) -> SpendIntent | None:
    """One sentence -> one SpendIntent, or None (fall back to the router).

    `llm_fn` is injectable so tests run a fake Bedrock layer; production
    uses the Strands client. Any exception from the LLM layer also degrades
    to None — a planner outage must never break the deterministic product.
    """
    if not text.strip():
        return None
    complete = llm_fn or _strands_complete
    try:
        raw = complete(text)
    except Exception:
        return None
    return parse_intent(raw)
