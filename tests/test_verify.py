"""Tests for the proof export + offline consistency checker."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from mcp_server import actions, tools as _tools  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("SPENDLATCH_STATE", str(tmp_path / "state.json"))


def _executed_bundle(tmp_path) -> Path:
    session = actions.open_session()["session_token"]
    proposal = actions.propose_action("rightsize-ec2")
    mandate = actions.approve_action(proposal["proposal_id"], session_token=session)
    actions.execute_action(mandate["mandate_id"])
    bundle = actions.export_proof(mandate["mandate_id"])
    path = tmp_path / "proof.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    return path


def _run_verify(bundle: Path, state: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / "verify_proof.py"), str(bundle),
         "--state", str(state)],
        capture_output=True, text=True)


def test_full_loop_proof_verifies(tmp_path):
    bundle = _executed_bundle(tmp_path)
    state = Path(__import__("os").environ["SPENDLATCH_STATE"])
    result = _run_verify(bundle, state)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("✓") == 7


def test_receipt_carries_transaction_identity(tmp_path):
    session = actions.open_session()["session_token"]
    proposal = actions.propose_action("rightsize-ec2")
    mandate = actions.approve_action(proposal["proposal_id"], session_token=session)
    receipt = actions.execute_action(mandate["mandate_id"])
    assert receipt["request_id"] == proposal["proposal_id"]
    assert receipt["execution_id"].startswith("e-")
    assert len(receipt["idempotency_key"]) == 24


def test_tampered_mandate_digest_fails(tmp_path):
    bundle_path = _executed_bundle(tmp_path)
    bundle = json.loads(bundle_path.read_text())
    bundle["mandate_digest"] = "f" * 64
    bundle_path.write_text(json.dumps(bundle))
    state = Path(__import__("os").environ["SPENDLATCH_STATE"])
    result = _run_verify(bundle_path, state)
    assert result.returncode == 1
    assert "mandate signature" in result.stdout


def test_tampered_receipt_fails_binding(tmp_path):
    bundle_path = _executed_bundle(tmp_path)
    bundle = json.loads(bundle_path.read_text())
    bundle["execution_receipt"]["amount"] = 9999.99
    bundle["execution_receipt"]["idempotency_key"] = "forged"
    bundle_path.write_text(json.dumps(bundle))
    state = Path(__import__("os").environ["SPENDLATCH_STATE"])
    result = _run_verify(bundle_path, state)
    assert result.returncode == 1
