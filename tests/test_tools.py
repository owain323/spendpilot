"""Tests for the SpendLatch tool layer (single source of truth)."""

from __future__ import annotations

import pytest

from mcp_server import ledger, sample_data as data, store, tools


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Every test runs against a throwaway state file."""
    monkeypatch.setenv("SPENDPILOT_STATE", str(tmp_path / "state.json"))


def _provider(**overrides):
    base = {
        "id": "x", "name": "X", "category": "saas",
        "monthly": {m: 100.0 for m in data.MONTHS},
        "evidence": {"driver": "seats", "detail": "test fixture", "usage_matches_value": True},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------- overview

class TestSpendingOverview:
    def test_totals_match_line_items(self):
        overview = tools.spending_overview()
        item_sum = sum(p["amount"] for p in overview["providers"])
        assert overview["total"] == pytest.approx(item_sum, abs=0.01)

    def test_month_over_month_delta(self):
        overview = tools.spending_overview()
        assert overview["month"] == "2026-08"
        assert overview["prev_month"] == "2026-07"
        assert overview["total"] == pytest.approx(642.78, abs=0.01)
        assert overview["prev_total"] == pytest.approx(582.47, abs=0.01)
        assert overview["delta_pct"] == pytest.approx(10.4, abs=0.1)

    def test_category_rollup_covers_total(self):
        overview = tools.spending_overview()
        assert sum(overview["by_category"].values()) == pytest.approx(overview["total"], abs=0.01)

    def test_providers_sorted_descending(self):
        amounts = [p["amount"] for p in tools.spending_overview()["providers"]]
        assert amounts == sorted(amounts, reverse=True)

    def test_earlier_month_has_no_prev_fields(self):
        overview = tools.spending_overview("2026-03")
        assert "prev_total" not in overview
        assert overview["total"] == pytest.approx(486.17, abs=0.01)


# --------------------------------------------------------- unit economics

class TestUnitEconomics:
    def test_only_ai_providers_have_task_metrics(self):
        econ = tools.unit_economics()
        assert {r["provider_id"] for r in econ["providers"]} == {"openai", "anthropic"}

    def test_cost_per_1k_tasks_exact(self):
        econ = tools.unit_economics()
        openai = next(r for r in econ["providers"] if r["provider_id"] == "openai")
        latest = openai["points"][-1]
        assert latest["month"] == "2026-08"
        assert latest["cost_per_1k_tasks"] == pytest.approx(47.02 / 12800 * 1000, abs=0.01)

    def test_openai_canary_fires_volume_down(self):
        econ = tools.unit_economics()
        openai = next(r for r in econ["providers"] if r["provider_id"] == "openai")
        assert openai["canary"] is True
        assert openai["drift"]["mom_pct"] >= tools.TASK_DRIFT_PCT

    def test_anthropic_no_canary_scaling_efficiently(self):
        econ = tools.unit_economics()
        anthropic = next(r for r in econ["providers"] if r["provider_id"] == "anthropic")
        assert anthropic["canary"] is False

    def test_drift_since_first_month(self):
        econ = tools.unit_economics()
        openai = next(r for r in econ["providers"] if r["provider_id"] == "openai")
        assert openai["drift"]["since_first_pct"] > openai["drift"]["mom_pct"]  # long drift > monthly


# -------------------------------------------------------- analysis (pure)

class TestAnalyzeDataset:
    def test_real_dataset_finds_expected_set(self):
        findings = tools.analyze_dataset(data.PROVIDERS, data.MONTHS)
        by_id = {f["id"]: f for f in findings}
        assert "spike-aws" in by_id
        assert "trial-figma" in by_id
        assert "taskdrift-openai" in by_id
        assert "keep-anthropic" in by_id
        assert by_id["keep-anthropic"]["verdict"] == "keep"

    def test_pure_function_writes_no_state(self, tmp_path):
        state_file = tmp_path / "state.json"
        import os
        os.environ["SPENDPILOT_STATE"] = str(state_file)
        tools.analyze_dataset(data.PROVIDERS, data.MONTHS)
        assert not state_file.exists()

    def test_every_flag_has_evidence_chain(self):
        for f in tools.analyze_dataset(data.PROVIDERS, data.MONTHS):
            assert f["evidence"], f"{f['id']} has no evidence"
            for e in f["evidence"]:
                assert set(e) == {"signal", "value", "source"}

    def test_confidence_is_computed_not_asserted(self):
        findings = {f["id"]: f for f in tools.analyze_dataset(data.PROVIDERS, data.MONTHS)}
        assert findings["spike-aws"]["confidence"] == "high"       # 2 signals + strong mismatch
        assert findings["taskdrift-openai"]["confidence"] == "high"  # price up + volume down
        assert findings["trial-figma"]["confidence"] == "medium"     # 2 signals, not strong

    def test_spike_threshold_boundary(self):
        evidence = {"driver": "vm", "detail": "idle", "usage_matches_value": False}
        below = _provider(evidence=evidence,
                          monthly={**{m: 100.0 for m in data.MONTHS[:-1]}, data.MONTHS[-1]: 124.9})
        at = _provider(evidence=evidence,
                       monthly={**{m: 100.0 for m in data.MONTHS[:-1]}, data.MONTHS[-1]: 125.0})
        assert tools.analyze_dataset([below], data.MONTHS) == []
        assert tools.analyze_dataset([at], data.MONTHS)[0]["id"] == "spike-x"

    def test_spike_absolute_floor(self):
        # +60% but only $5 — not worth attention
        tiny = _provider(monthly={**{m: 8.0 for m in data.MONTHS[:-1]}, data.MONTHS[-1]: 13.0})
        assert tools.analyze_dataset([tiny], data.MONTHS) == []

    def test_zombie_threshold_boundary(self):
        at = _provider(evidence={"driver": "seats", "detail": "unused", "last_used_days": 45,
                                 "usage_matches_value": True})
        below = _provider(evidence={"driver": "seats", "detail": "unused", "last_used_days": 44,
                                    "usage_matches_value": True})
        assert tools.analyze_dataset([at], data.MONTHS)[0]["kind"] == "zombie"
        assert tools.analyze_dataset([below], data.MONTHS) == []

    def test_insufficient_history_refuses(self):
        new = _provider(id="new", monthly={"2026-07": 30.0, "2026-08": 45.0})
        finding = tools.analyze_dataset([new], data.MONTHS)[0]
        assert finding["verdict"] == "hold"
        assert finding["eligible"] is False
        assert "not enough" in finding["reason"]

    def test_growth_matching_value_is_kept(self):
        growing = _provider(
            id="grow",
            monthly={**{m: 50.0 for m in data.MONTHS[:-1]}, data.MONTHS[-1]: 120.0},
            evidence={"driver": "tokens", "detail": "usage doubled with real launch", "usage_matches_value": True})
        finding = tools.analyze_dataset([growing], data.MONTHS)[0]
        assert finding["verdict"] == "keep"
        assert "do NOT cut" in finding["title"]

    def test_sustained_trend_adds_signal(self):
        trending = _provider(
            id="trend", category="cloud",
            monthly={"2026-03": 100.0, "2026-04": 110.0, "2026-05": 121.0,
                     "2026-06": 133.1, "2026-07": 146.41, "2026-08": 234.26},
            evidence={"driver": "vm", "detail": "idle fleet", "usage_matches_value": False})
        finding = tools.analyze_dataset([trending], data.MONTHS)[0]
        signals = {e["signal"] for e in finding["evidence"]}
        assert {"mom_spike", "sustained_trend", "utilization_mismatch"} <= signals
        assert finding["confidence"] == "high"


# -------------------------------------------------- detection (stateful)

class TestDetectAnomalies:
    def test_first_sweep_surfaces_and_fires(self):
        findings = tools.detect_anomalies()
        ids = [a["id"] for a in findings["anomalies"]]
        assert set(ids) == {"spike-aws", "trial-figma", "taskdrift-openai"}
        assert store.load_state()["alerts_fired"]["spike-aws"] == "2026-08"

    def test_second_sweep_suppresses_repeats(self):
        tools.detect_anomalies()
        second = tools.detect_anomalies(include_previous=False)
        assert second["anomalies"] == []
        kinds = [e["kind"] for e in ledger.entries()]
        assert "suppress" in kinds

    def test_explicit_sweep_shows_without_refiring(self):
        """Answering a direct question is not nagging: explicit sweeps show
        already-fired findings, but never re-fire alerts or spam the ledger."""
        first = tools.detect_anomalies()
        second = tools.detect_anomalies(include_previous=True)
        assert len(second["anomalies"]) == len(first["anomalies"])
        assert all(a["previously_surfaced"] for a in second["anomalies"])
        alerts = [e for e in ledger.entries() if e["kind"] == "alert"]
        assert len(alerts) == len(first["anomalies"])  # no duplicate alerts
        assert not [e for e in ledger.entries() if e["kind"] == "suppress"]

    def test_anthropic_growth_is_kept_not_cut(self):
        findings = tools.detect_anomalies()
        anomaly_ids = [a["id"] for a in findings["anomalies"]]
        kept_ids = [k["id"] for k in findings["kept"]]
        assert "keep-anthropic" not in anomaly_ids
        assert "keep-anthropic" in kept_ids

    def test_acknowledged_anomalies_are_marked(self):
        store.acknowledge("spike-aws")
        findings = tools.detect_anomalies()
        spike = next(a for a in findings["anomalies"] if a["id"] == "spike-aws")
        assert spike["acknowledged"] is True

    def test_challenge_revives_suppressed_finding(self):
        first = tools.detect_anomalies()
        assert first["anomalies"]
        suppress_entry = None
        tools.detect_anomalies(include_previous=False)  # proactive re-sweep: suppressed
        suppress_entry = next(e for e in ledger.entries() if e["kind"] == "suppress")
        ledger.challenge(suppress_entry["seq"], "I actually want this one")
        third = tools.detect_anomalies(include_previous=False)
        assert any(a["provider"] == suppress_entry["subject"] for a in third["anomalies"])

    def test_every_surfaced_alert_is_logged(self):
        findings = tools.detect_anomalies()
        alerts = [e for e in ledger.entries() if e["kind"] == "alert"]
        assert len(alerts) == len(findings["anomalies"])


# ------------------------------------------------------------------ prove

class TestSimulateSaving:
    def test_before_after_and_proof(self):
        proof = tools.simulate_saving("rightsize-ec2")
        assert proof["monthly_before"] > proof["monthly_after"]
        assert proof["expected_saving_pct"] > 0
        assert proof["proof_steps"]
        assert "scenario estimate" in proof["estimate_basis"]

    def test_unknown_action_lists_known_ones(self):
        result = tools.simulate_saving("nonsense-action")
        assert "error" in result
        assert "rightsize-ec2" in result["known_actions"]

    def test_annual_saving_is_12x_monthly(self):
        proof = tools.simulate_saving("cancel-figma")
        assert proof["annual_saving"] == pytest.approx(proof["monthly_saving"] * 12, abs=0.05)

    @pytest.mark.parametrize("action_id", sorted(data.SAVING_ACTIONS))
    def test_every_action_is_provable(self, action_id):
        proof = tools.simulate_saving(action_id)
        assert "error" not in proof
        assert proof["proof_steps"] and proof["risk"] and proof["confidence"] in ("high", "medium", "low")
        assert 0 < proof["expected_saving_pct"] <= 100


# ---------------------------------------------------------------- budgets

class TestBudgets:
    def test_set_budget_persists_across_loads(self):
        tools.set_budget("home", 300.0)
        status = tools.budget_status()
        home = next(b for b in status["budgets"] if b["category"] == "home")
        assert home["monthly_limit"] == 300.0
        assert home["spent"] == pytest.approx(246.03, abs=0.01)
        assert home["used_pct"] == pytest.approx(82.0, abs=0.1)

    def test_status_warn_at_80(self):
        tools.set_budget("home", 300.0)
        home = next(b for b in tools.budget_status()["budgets"] if b["category"] == "home")
        assert home["status"] == "warn"

    def test_status_over_beyond_100(self):
        tools.set_budget("saas", 20.0)
        saas = next(b for b in tools.budget_status()["budgets"] if b["category"] == "saas")
        assert saas["status"] == "over"

    def test_status_ok_below_80(self):
        tools.set_budget("cloud", 500.0)
        cloud = next(b for b in tools.budget_status()["budgets"] if b["category"] == "cloud")
        assert cloud["status"] == "ok"

    def test_budget_change_is_logged(self):
        tools.set_budget("home", 300.0)
        assert any(e["kind"] == "budget" and e["subject"] == "home" for e in ledger.entries())

    @pytest.mark.parametrize("bad", [0, -1, -50.5])
    def test_non_positive_budget_rejected(self, bad):
        with pytest.raises(ValueError):
            tools.set_budget("home", bad)


# ----------------------------------------------------------- subscriptions

class TestSubscriptions:
    def test_zombie_flag(self):
        subs = tools.list_subscriptions()["subscriptions"]
        figma = next(s for s in subs if s["id"] == "figma")
        assert figma["flag"] == "zombie"
        notion = next(s for s in subs if s["id"] == "notion")
        assert notion["flag"] is None

    def test_sorted_by_monthly_desc(self):
        monthly = [s["monthly"] for s in tools.list_subscriptions()["subscriptions"]]
        assert monthly == sorted(monthly, reverse=True)

    def test_threshold_exposed(self):
        assert tools.list_subscriptions()["zombie_threshold_days"] == tools.ZOMBIE_DAYS


# --------------------------------------------------------------- briefing

class TestProactiveBriefing:
    def test_headline_and_previews(self):
        briefing = tools.proactive_briefing()
        assert briefing["anomalies"]
        assert briefing["total_monthly_saving_potential"] > 0
        assert "scenario estimate" in briefing["headline"]

    def test_previews_only_valid_actions(self):
        for preview in tools.proactive_briefing()["saving_previews"]:
            assert "error" not in preview
            assert preview["monthly_saving"] > 0

    def test_total_matches_preview_sum(self):
        briefing = tools.proactive_briefing()
        assert briefing["total_monthly_saving_potential"] == pytest.approx(
            sum(p["monthly_saving"] for p in briefing["saving_previews"]), abs=0.01)


# ------------------------------------------------------------------ ledger

class TestDecisionLedgerView:
    def test_newest_first(self):
        tools.set_budget("home", 300.0)
        tools.detect_anomalies()
        entries = tools.decision_ledger()["entries"]
        seqs = [e["seq"] for e in entries]
        assert seqs == sorted(seqs, reverse=True)
