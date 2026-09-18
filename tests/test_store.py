"""Tests for the persistent state layer (cross-session memory)."""

from __future__ import annotations

import pytest

from mcp_server import store


def test_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    store.set_budget("home", 300.0, path)
    loaded = store.load_state(path)
    assert loaded["budgets"]["home"]["monthly_limit"] == 300.0


def test_defaults_when_missing(tmp_path):
    state = store.load_state(tmp_path / "nope.json")
    assert state["budgets"] == {}
    assert state["sessions"] == {}


def test_corrupt_state_fails_closed_and_preserves_file(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="never silently reset"):
        store.load_state(path)
    preserved = list(tmp_path.glob("state.corrupt-*.json"))
    assert len(preserved) == 1  # the broken audit trail is kept, not erased


def test_workspace_isolation(tmp_path, monkeypatch):
    monkeypatch.delenv("SPENDPILOT_STATE", raising=False)
    monkeypatch.setattr(store, "state_path", lambda path=None: path or store.state_path())
    root = tmp_path / "data"
    monkeypatch.setattr(store, "state_path",
                        lambda path=None: path or root / "workspaces" / f"{store.current_workspace() or 'anonymous'}.json")
    store.set_workspace("ws-a")
    store.set_budget("home", 300.0)
    store.set_workspace("ws-b")
    assert store.load_state()["budgets"] == {}
    store.set_workspace("ws-a")
    assert store.load_state()["budgets"]["home"]["monthly_limit"] == 300.0
    store.set_workspace(None)


def test_acknowledge_idempotent(tmp_path):
    path = tmp_path / "state.json"
    store.acknowledge("spike-aws", path)
    store.acknowledge("spike-aws", path)
    assert store.load_state(path)["acknowledged"] == ["spike-aws"]


def test_session_history_bounded(tmp_path):
    path = tmp_path / "state.json"
    for i in range(60):
        store.remember_turn("s1", "user", f"turn {i}", path)
    history = store.session_history("s1", path)
    assert len(history) == 50
    assert history[-1]["text"] == "turn 59"


def test_negative_budget_rejected(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        store.set_budget("home", -1, tmp_path / "state.json")
