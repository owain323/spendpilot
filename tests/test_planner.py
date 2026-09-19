"""Tests for the LLM planner: strict intent parsing, default-OFF behavior,
fallback on malformed/abstinent output, and the default-deny spend gate.

No AWS account, no network: the Bedrock layer is injected as a fake.
The constitution holds throughout — the planner never approves, signs, or
executes; these tests prove the boundary by asserting zero mandates and
zero proposals come out of any planner path.
"""

from __future__ import annotations

import json

import pytest

from agent import brain
from mcp_server import actions, planner, store, tools


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("SPENDLATCH_STATE", str(tmp_path / "state.json"))
    monkeypatch.delenv("SPENDLATCH_LLM", raising=False)


def fake_llm(mapping: dict[str, object]):
    return lambda prompt: mapping.get(prompt, "ABSTAIN")


FIVE_SENTENCES = {
    "buy 200 dollars of API credits for the eval pipeline": {
        "merchant": None, "amount": 200, "currency": "USD",
        "category": "ai-api", "scope": "eval pipeline",
        "rationale": "Purchase API credits for evaluation runs."},
    "increase our AI build capacity": {
        "merchant": None, "amount": None, "currency": "USD",
        "category": "ai-api", "scope": "build capacity",
        "rationale": "Raise AI build throughput."},
    "how much did OpenAI cost us last month": {
        "merchant": "openai", "amount": None, "currency": "USD",
        "category": "ai-api", "scope": None,
        "rationale": "Question about OpenAI spend."},
    "add a second Figma seat for the contractor": {
        "merchant": "figma", "amount": None, "currency": "USD",
        "category": "saas", "scope": "contractor seat",
        "rationale": "Expand Figma seats by one."},
    "we need 500 euros of extra cloud storage before Friday": {
        "merchant": None, "amount": 500, "currency": "EUR",
        "category": "cloud", "scope": "extra storage",
        "rationale": "Buy cloud storage capacity urgently."},
}


class TestParseIntent:
    def test_five_sentences_map_to_correct_fields(self):
        for sentence, expected in FIVE_SENTENCES.items():
            intent = planner.plan(sentence, llm_fn=lambda p, j=expected: json.dumps(j))
            assert intent is not None, sentence
            assert intent.merchant == expected["merchant"]
            assert intent.amount == (float(expected["amount"]) if expected["amount"] is not None else None)
            assert intent.currency == expected["currency"]
            assert intent.category == expected["category"]
            assert intent.scope == expected["scope"]
            assert intent.rationale == expected["rationale"]

    def test_json_fence_is_accepted(self):
        raw = "```json\n" + json.dumps(FIVE_SENTENCES["increase our AI build capacity"]) + "\n```"
        assert planner.parse_intent(raw) is not None

    @pytest.mark.parametrize("raw", [
        "ABSTAIN",
        "abstain - not spend related",
        "not json at all",
        '{"merchant": "openai", "amount": "lots"}',           # amount must be a number
        '{"amount": -50, "rationale": "refund scheme"}',      # negative spend
        '{"amount": 10, "currency": "usd", "rationale": "x"}',  # currency must be ISO uppercase
        '{"amount": 10, "currency": "USD", "category": "crypto", "rationale": "x"}',  # unknown category
        '{"amount": 10, "currency": "USD"}',                  # rationale is required
        '{"amount": 10, "currency": "USD", "rationale": "x", "execute": true}',  # smuggled key
        '["buy", "stuff"]',                                   # not an object
        "",
    ])
    def test_malformed_or_smuggled_output_falls_back(self, raw):
        assert planner.parse_intent(raw) is None

    def test_llm_outage_degrades_to_none(self):
        def boom(prompt):
            raise RuntimeError("bedrock unreachable")
        assert planner.plan("buy everything", llm_fn=boom) is None


class TestFeatureFlag:
    def test_off_by_default(self):
        assert planner.enabled() is False

    def test_off_means_brain_never_calls_planner(self, monkeypatch):
        def forbidden(text, llm_fn=None):
            raise AssertionError("planner must not run while the flag is off")
        monkeypatch.setattr(planner, "plan", forbidden)
        out = brain.handle("buy 200 dollars of API credits", session_id="s1")
        assert "cards" in out and not any(c.get("type") == "denied" for c in out["cards"])


class TestSpendIntentPolicy:
    def _enabled_brain(self, monkeypatch, intent_dict):
        monkeypatch.setenv("SPENDLATCH_LLM", "bedrock")
        monkeypatch.setattr(planner, "plan",
                            lambda text, llm_fn=None: planner.parse_intent(json.dumps(intent_dict)))

    def test_spend_request_is_denied_and_logged(self, monkeypatch):
        self._enabled_brain(monkeypatch, FIVE_SENTENCES["buy 200 dollars of API credits for the eval pipeline"])
        out = brain.handle("buy 200 dollars of API credits for the eval pipeline", session_id="s1")
        card = out["cards"][0]
        assert card["type"] == "denied" and card["decision"] == "DENIED"
        assert card["amount"] == 200.0 and card["currency"] == "USD"
        assert card["category"] == "ai-api" and card["scope"] == "eval pipeline"
        assert card["policy_limit"] and card["evidence"] and card["reasons"]
        kinds = [e["kind"] for e in tools.decision_ledger()["entries"]]
        assert "refuse" in kinds
        # the constitution: no planner path may mint proposals or mandates
        counts = actions.mandate_status()["counts"]
        assert counts == {"proposals_open": 0, "mandates_issued": 0, "executed": 0}

    def test_budget_line_makes_the_denial_concrete(self, monkeypatch):
        tools.set_budget("ai-api", 50.0)
        self._enabled_brain(monkeypatch, FIVE_SENTENCES["buy 200 dollars of API credits for the eval pipeline"])
        out = brain.handle("buy 200 dollars of API credits", session_id="s1")
        card = out["cards"][0]
        assert "ai-api budget" in card["evidence"]
        assert any("budget would be exceeded" in r for r in card["reasons"])

    def test_query_intent_routes_to_provider(self, monkeypatch):
        # merchant resolves by provider NAME (no alias-table entry), and the
        # message itself hits no deterministic route — the planner path is
        # the only way this answer exists.
        self._enabled_brain(monkeypatch, {
            "merchant": "Notion", "amount": None, "currency": "USD",
            "category": "saas", "scope": None,
            "rationale": "Question about Notion spend."})
        out = brain.handle("our vendor situation is confusing", session_id="s1")
        assert out["cards"][0]["type"] == "provider-detail"
        assert out["cards"][0]["id"] == "notion"

    def test_unroutable_intent_abstains_gracefully(self, monkeypatch):
        self._enabled_brain(monkeypatch, {
            "merchant": None, "amount": None, "currency": "USD",
            "category": "other", "scope": None,
            "rationale": "A vague musing about the weather."})
        out = brain.handle("a vague musing", session_id="s1")
        assert out["cards"] == [] and "leaving it unanswered" in out["reply"]


class TestEvaluateSpendIntent:
    def test_default_deny_always(self):
        verdict = actions.evaluate_spend_intent(
            {"merchant": "acme", "amount": 10.0, "category": "saas", "scope": "trial"})
        assert verdict["decision"] == "DENIED"
        assert verdict["reasons"] and "cost-reduction" in verdict["reasons"][0]
        assert verdict["ledger_seq"] >= 1

    def test_denial_is_workspace_isolated(self, tmp_path):
        other = tmp_path / "other.json"
        actions.evaluate_spend_intent({"merchant": "acme", "amount": 5.0,
                                       "category": "saas", "scope": None},
                                      state_path=other)
        assert tools.decision_ledger()["count"] == 0
        assert tools.decision_ledger(other)["count"] == 1
