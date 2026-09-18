"""API surface tests (FastAPI TestClient, in-process, offline)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent.backend import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SPENDPILOT_STATE", str(tmp_path / "state.json"))
    return TestClient(app)


class TestOpening:
    def test_agent_speaks_first(self, client):
        res = client.get("/api/opening")
        assert res.status_code == 200
        body = res.json()
        assert "found" in body["reply"]
        assert body["cards"]  # unprompted anomaly cards
        assert body["stats"]["saving_potential"] > 0

    def test_session_id_created_and_stable(self, client):
        first = client.get("/api/opening").json()
        second = client.get("/api/opening", params={"session_id": first["session_id"]}).json()
        assert second["session_id"] == first["session_id"]
        assert "Welcome back" in second["reply"]


class TestChat:
    def test_prove_returns_labeled_estimate(self, client):
        res = client.post("/api/chat", json={"message": "prove the saving"})
        card = res.json()["cards"][0]
        assert card["type"] == "saving"
        assert card["monthly_before"] > card["monthly_after"]
        assert "scenario estimate" in card["estimate_basis"]

    def test_budget_roundtrip_and_memory(self, client):
        sid = client.get("/api/opening").json()["session_id"]
        res = client.post("/api/chat", json={"message": "set a $300 budget for home", "session_id": sid})
        card = res.json()["cards"][0]
        assert card["type"] == "budget"
        assert card["monthly_limit"] == 300.0
        assert card["status"] == "warn"
        # cross-session memory: reopening the same session remembers
        reopen = client.get("/api/opening", params={"session_id": sid}).json()
        assert "Welcome back" in reopen["reply"]
        assert any(c["type"] == "budget" for c in reopen["cards"])

    def test_ledger_intent(self, client):
        client.post("/api/chat", json={"message": "anything unusual?"})
        res = client.post("/api/chat", json={"message": "why didn't you tell me?"})
        # The full trail lives in the side rail now; the chat answer stays
        # light and points there.
        assert "Decision ledger panel" in res.json()["reply"]
        assert res.json()["cards"] == []

    def test_challenge_unknown_seq(self, client):
        res = client.post("/api/chat", json={"message": "challenge #9999"})
        assert "don't have" in res.json()["reply"]

    def test_provider_mention_pins_the_prove_action(self, client):
        """Prove the openai api must prove OPENAI's action - not whoever has
        the largest headline number."""
        res = client.post("/api/chat", json={"message": "prove the openai api"})
        card = res.json()["cards"][0]
        assert card["title"] == "Route short OpenAI classification calls to a smaller model"

    def test_bare_provider_mention_answers_with_numbers(self, client):
        """A single provider mention gets a dedicated trend card, not the
        all-provider overview."""
        res = client.post("/api/chat", json={"message": "how is Anthropic API doing"})
        card = res.json()["cards"][0]
        assert card["type"] == "provider-detail"
        assert card["id"] == "anthropic"
        assert "Anthropic" in res.json()["reply"]
        assert len(card["monthly"]) >= 4  # a real series, not a stub

    def test_unknown_message_gets_help(self, client):
        res = client.post("/api/chat", json={"message": "flibbertigibbet"})
        assert "Try:" in res.json()["reply"]

    def test_unit_economics_intent(self, client):
        res = client.post("/api/chat", json={"message": "cost per task"})
        card = res.json()["cards"][0]
        assert card["type"] == "unit"
        assert any(p["canary"] for p in card["providers"])


class TestLedgerApi:
    def test_ledger_verify_reports_chain_ok(self, client):
        client.post("/api/chat", json={"message": "anything unusual?"})
        v = client.get("/api/ledger/verify").json()
        assert v["ok"] is True and v["entries"] >= 1 and v["broken_at"] is None
    def test_ledger_grows_with_actions(self, client):
        before = client.get("/api/ledger").json()["count"]
        client.post("/api/chat", json={"message": "set a $300 budget for home"})
        after = client.get("/api/ledger").json()["count"]
        assert after > before

    def test_unit_endpoint(self, client):
        body = client.get("/api/unit-economics").json()
        assert body["metric"] == "cost per 1K tasks"


class TestStatic:
    def test_index_served(self, client):
        res = client.get("/")
        assert res.status_code == 200
        assert "SpendPilot" in res.text

    def test_health(self, client):
        assert client.get("/api/health").json() == {"status": "ok"}
