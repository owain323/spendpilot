"""Tests for the mandate-gated action loop (propose -> approve -> execute).

The security invariants are the point: nothing executes without a valid,
in-scope, unexpired, single-use mandate — and every refusal is logged.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from mcp_server import actions, adapters, ledger, store


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("SPENDPILOT_STATE", str(tmp_path / "state.json"))


def _session() -> str:
    """Mint an authenticated web session (the only surface that may approve)."""
    return actions.open_session()["session_token"]


def _propose(action_id: str = "rightsize-ec2") -> dict:
    proposal = actions.propose_action(action_id)
    assert "proposal_id" in proposal
    return proposal


def _approve(proposal: dict, **kwargs) -> dict:
    kwargs.setdefault("session_token", _session())
    mandate = actions.approve_action(proposal["proposal_id"], **kwargs)
    assert "mandate_id" in mandate
    return mandate


class TestPropose:
    def test_proposal_carries_proof_snapshot(self):
        proposal = _propose()
        assert proposal["status"] == "proposed"
        assert proposal["operation"] == "ec2:ModifyInstanceAttribute"
        assert proposal["proof_snapshot"]["monthly_before"] == 181.34
        assert proposal["proof"]["monthly_after"] < proposal["proof"]["monthly_before"]

    def test_propose_is_idempotent_per_action(self):
        first = _propose()
        second = actions.propose_action("rightsize-ec2")
        assert second["proposal_id"] == first["proposal_id"]
        assert "already proposed" in second["note"]

    def test_unknown_action_returns_error_surface(self):
        result = actions.propose_action("no-such-action")
        assert "error" in result and result["known_actions"]

    def test_propose_is_logged(self):
        _propose()
        kinds = [e["kind"] for e in ledger.entries()]
        assert "propose" in kinds


class TestApprove:
    def test_mandate_is_signed_scoped_and_expiring(self):
        mandate = _approve(_propose())
        assert mandate["status"] == "issued"
        assert len(mandate["signature"]) == 64
        assert mandate["scope"]["max_monthly_before"] == 181.34
        expires = datetime.fromisoformat(mandate["expires_at"])
        issued = datetime.fromisoformat(mandate["issued_at"])
        assert (expires - issued).total_seconds() == actions.MANDATE_TTL_SECONDS

    def test_approve_unknown_proposal_refused_and_logged(self):
        result = actions.approve_action("p-deadbeef")
        assert result["refused"] is True
        assert any(e["kind"] == "refuse" for e in ledger.entries())

    def test_double_approval_refused(self):
        proposal = _propose()
        _approve(proposal)
        result = actions.approve_action(proposal["proposal_id"])
        assert result["refused"] is True

    def test_approval_marks_proposal(self):
        proposal = _propose()
        _approve(proposal)
        status = actions.mandate_status()
        assert status["proposals"][0]["status"] == "approved"


class TestExecute:
    def test_full_loop_returns_receipt_and_logs_everything(self):
        mandate = _approve(_propose())
        receipt = actions.execute_action(mandate["mandate_id"])
        assert receipt["simulated"] is True
        assert receipt["adapter"] == "aws"
        assert receipt["monthly_saving"] == 85.14
        assert receipt["mandate_id"] == mandate["mandate_id"]
        assert receipt["changes"] and receipt["rollback"]
        kinds = [e["kind"] for e in ledger.entries()]
        assert kinds == ["propose", "approve", "execute"]

    def test_execute_without_mandate_refused(self):
        result = actions.execute_action("m-deadbeef")
        assert result["refused"] is True
        assert "nothing executes on trust" in result["error"]
        assert any(e["kind"] == "refuse" for e in ledger.entries())

    def test_forged_mandate_refused(self):
        mandate = _approve(_propose())
        # Tamper with the stored payload: raise the scope cap.
        path = store.state_path()
        state = store.load_state(path)
        state["mandates"][mandate["mandate_id"]]["scope"]["max_monthly_before"] = 9999.0
        store.save_state(state, path)
        result = actions.execute_action(mandate["mandate_id"])
        assert result["refused"] is True
        assert "signature" in result["error"]
        # The forged mandate must remain unconsumed and no receipt exists.
        assert actions.mandate_status()["receipts"] == []

    def test_mandate_is_single_use(self):
        mandate = _approve(_propose())
        first = actions.execute_action(mandate["mandate_id"])
        assert first["simulated"] is True
        second = actions.execute_action(mandate["mandate_id"])
        assert second["refused"] is True
        assert "single-use" in second["error"]
        assert len(actions.mandate_status()["receipts"]) == 1

    def test_expired_mandate_refused(self, monkeypatch):
        mandate = _approve(_propose())
        future = datetime.now(timezone.utc) + timedelta(seconds=actions.MANDATE_TTL_SECONDS + 60)
        monkeypatch.setattr(actions, "_now", lambda: future)
        result = actions.execute_action(mandate["mandate_id"])
        assert result["refused"] is True
        assert "expired" in result["error"]
        status = actions.mandate_status()
        assert status["mandates"][0]["status"] == "expired"

    def test_scope_drift_refused(self, monkeypatch):
        """Reality moved after approval — the mandate must refuse. With
        proof hashing, ANY change to the approved evidence (including the
        bill amount) breaks the committed proof hash first."""
        mandate = _approve(_propose())
        # Reality drifted up beyond the approved cap before execution.
        monkeypatch.setitem(
            __import__("mcp_server.sample_data", fromlist=["SAVING_ACTIONS"])
            .SAVING_ACTIONS["rightsize-ec2"], "monthly_before", 250.0)
        result = actions.execute_action(mandate["mandate_id"])
        assert result["refused"] is True
        assert "drifted" in result["error"]
        assert "re-approval required" in result["error"]

    def test_every_refusal_lands_in_ledger(self):
        actions.execute_action("m-nope")
        actions.approve_action("p-nope")
        refuses = [e for e in ledger.entries() if e["kind"] == "refuse"]
        assert len(refuses) == 2
        assert all(e["reason"] for e in refuses)


class TestAdapters:
    def test_all_saving_actions_have_adapters_and_operations(self):
        from mcp_server import sample_data as data
        for action_id in data.SAVING_ACTIONS:
            assert action_id in adapters.ADAPTERS
            assert adapters.operation_for(action_id)

    def test_receipts_are_always_labeled_simulated(self):
        for action_id in adapters.ADAPTERS:
            receipt = adapters.execute(action_id)
            assert receipt["simulated"] is True
            assert receipt["executed_at"]

    def test_unknown_adapter_error_surface(self):
        result = adapters.execute("nope")
        assert "error" in result and result["known_actions"]


class TestMandateStatus:
    def test_counts_track_the_loop(self):
        mandate = _approve(_propose())
        _propose("cancel-figma")
        actions.execute_action(mandate["mandate_id"])
        status = actions.mandate_status()
        assert status["counts"] == {"proposals_open": 1, "mandates_issued": 0, "executed": 1}
        # signatures are never exposed in the status view
        assert all("signature" not in m for m in status["mandates"])
        assert status["mandates"][0]["signature_short"].endswith("...")

    def test_state_roundtrip_through_disk(self):
        mandate = _approve(_propose())
        actions.execute_action(mandate["mandate_id"])
        raw = json.loads(store.state_path().read_text(encoding="utf-8"))
        assert raw["receipts"] and raw["mandate_secret"]
        assert raw["mandates"][mandate["mandate_id"]]["status"] == "executed"


class TestAuthorizationBoundary:
    """Approval is bound to an authenticated web session — the MCP surface
    must never be able to say a human agreed."""

    def test_mcp_surface_cannot_approve(self):
        proposal = _propose()
        result = actions.approve_action(proposal["proposal_id"])  # no token
        assert result["refused"] is True
        assert "authenticated" in result["error"]
        assert any("authenticated" in e["reason"] for e in ledger.entries()
                   if e["kind"] == "refuse")

    def test_bogus_token_cannot_approve(self):
        proposal = _propose()
        result = actions.approve_action(proposal["proposal_id"], session_token="forged")
        assert result["refused"] is True

    def test_approver_is_session_fingerprint_not_a_string(self):
        mandate = _approve(_propose())
        assert mandate["approver"].startswith("web-session:")
        assert mandate["approval"]["surface"] == "web"

    def test_ttl_is_not_caller_controlled(self):
        proposal = _propose()
        with pytest.raises(TypeError):
            actions.approve_action(proposal["proposal_id"], ttl_seconds=360000)

    def test_mandate_signs_the_proof_hash(self):
        proposal = _propose()
        mandate = _approve(proposal)
        assert mandate["proof_hash"] == proposal["proof_hash"]
        assert len(mandate["proof_hash"]) == 64

    def test_proof_drift_since_approval_refused(self, monkeypatch):
        mandate = _approve(_propose())
        sample = __import__("mcp_server.sample_data", fromlist=["SAVING_ACTIONS"])
        monkeypatch.setitem(sample.SAVING_ACTIONS["rightsize-ec2"],
                            "monthly_after", 10.0)
        result = actions.execute_action(mandate["mandate_id"])
        assert result["refused"] is True
        assert "proof drifted" in result["error"]

    def test_single_use_holds_under_concurrency(self):
        mandate = _approve(_propose())
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(
                lambda _: actions.execute_action(mandate["mandate_id"]), range(2)))
        receipts = [r for r in results if r.get("simulated")]
        refusals = [r for r in results if r.get("refused")]
        assert len(receipts) == 1 and len(refusals) == 1
        assert "single-use" in refusals[0]["error"]
