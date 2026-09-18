"""Persistent JSON state for SpendPilot.

This is the cross-session memory of the product: budgets, acknowledged
alerts, and per-session conversation bookmarks survive restarts. State
lives in local JSON files; nothing leaves the machine.

Workspace isolation (2026-09-18): every authenticated web session gets
its own state file, so two judges playing with the public demo can never
see — or pollute — each other's budgets, mandates, or ledger. Requests
without a session token land in a shared anonymous workspace. The MCP
surface runs in its own workspace too (it cannot approve actions, but it
can still hold budgets).

Fail-closed on corruption (2026-09-18): a state file that no longer
parses is PRESERVED under a .corrupt-<ts> name and an error is raised.
Silently starting from defaults would erase the audit trail — the one
thing this product promises never to lose.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_STATE: dict = {
    "budgets": {},          # category -> {"monthly_limit": float}
    "acknowledged": [],     # anomaly ids the human has already seen
    "sessions": {},         # session_id -> {"history": [...], "created": str}
    "auth_sessions": {},    # token_hash -> {"workspace": str, "created": str}
    "ledger": [],           # decision event stream (see ledger.py; hash-chained)
    "alerts_fired": {},     # anomaly_id -> month last surfaced (suppression)
    "suppressed": {},       # anomaly_id -> month a suppression was logged
    "challenges": [],       # human overrules, fed back as context
    "proposals": {},        # proposal_id -> bounded action awaiting approval
    "mandates": {},         # mandate_id -> signed, scoped, expiring authorization
    "receipts": [],         # execution receipts (adapter reports)
    "mandate_secret": None, # per-installation HMAC key, generated on first approval
}

_ENV_KEY = "SPENDPILOT_STATE"
_ANONYMOUS_WORKSPACE = "anonymous"

# Process-level current workspace. The web backend sets this per request
# under its global state lock; tests and probes never touch it (they use
# SPENDPILOT_STATE, which takes priority below).
_current_workspace: str | None = None


def set_workspace(workspace: str | None) -> None:
    global _current_workspace
    _current_workspace = workspace


def current_workspace() -> str | None:
    return _current_workspace


def state_path(path: Path | None = None) -> Path:
    """Resolve the state file location.

    Priority: explicit `path` argument > SPENDPILOT_STATE env (tests and
    probes use single-file mode) > workspace file (per-session isolation).
    """
    if path is not None:
        return path
    raw = os.environ.get(_ENV_KEY)
    if raw:
        return Path(raw)
    workspace = _current_workspace or _ANONYMOUS_WORKSPACE
    # workspace ids are hex fingerprints minted by this module; sanitize anyway
    safe = "".join(c for c in workspace if c.isalnum() or c == "-")[:64] or "anonymous"
    return Path(__file__).resolve().parent.parent / "data" / "workspaces" / f"{safe}.json"


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _auth_file() -> Path:
    """The token->workspace registry. It must live OUTSIDE every workspace
    file: a request has to resolve the registry BEFORE it can know which
    workspace file to open. Single-file test mode folds it into the same
    file (SPENDPILOT_STATE)."""
    raw = os.environ.get(_ENV_KEY)
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parent.parent / "data" / "auth-sessions.json"


def _auth_map() -> dict:
    return load_state(_auth_file()).get("auth_sessions", {})


def open_auth_session() -> dict:
    """Mint a fresh authenticated session.

    The server keeps only the token HASH; the browser holds the token and
    presents it on approve. The registry maps the hash to the workspace id
    (derived from the hash), so later requests resolve their own workspace.
    """
    token = secrets.token_hex(32)
    h = _token_hash(token)
    workspace = h[:12]
    auth_path = _auth_file()
    auth = load_state(auth_path)
    auth["auth_sessions"][h] = {
        "workspace": workspace,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    save_state(auth, auth_path)
    return {"session_token": token, "workspace": workspace}


def workspace_for_token(token: str | None) -> str:
    """Workspace id for a presented token; anonymous when missing/unknown."""
    if not token:
        return _ANONYMOUS_WORKSPACE
    record = _auth_map().get(_token_hash(token))
    return record["workspace"] if record else _ANONYMOUS_WORKSPACE


def token_is_authenticated(token: str | None) -> bool:
    if not token:
        return False
    return _token_hash(token) in _auth_map()


def load_state(path: Path | None = None) -> dict:
    """Load state, filling defaults for any missing key.

    Fail-closed on corruption: the unreadable file is preserved under a
    .corrupt-<timestamp> sibling and RuntimeError is raised — silently
    starting from defaults would destroy the audit trail.
    """
    resolved = path or state_path()
    state = json.loads(json.dumps(DEFAULT_STATE))
    if resolved.exists():
        try:
            stored = json.loads(resolved.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            preserved = resolved.with_suffix(f".corrupt-{stamp}.json")
            os.replace(resolved, preserved)
            raise RuntimeError(
                f"state file {resolved} is corrupt and was preserved at {preserved}; "
                "repair or delete it — the audit trail is never silently reset"
            ) from exc
        if isinstance(stored, dict):
            state.update(stored)
    return state


def save_state(state: dict, path: Path | None = None) -> None:
    """Atomically persist state (write-temp-then-replace)."""
    resolved = path or state_path()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=resolved.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, resolved)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def set_budget(category: str, monthly_limit: float, path: Path | None = None) -> dict:
    if monthly_limit <= 0:
        raise ValueError("monthly_limit must be positive")
    state = load_state(path)
    state["budgets"][category] = {"monthly_limit": round(float(monthly_limit), 2)}
    save_state(state, path)
    return state["budgets"][category]


def acknowledge(anomaly_id: str, path: Path | None = None) -> None:
    state = load_state(path)
    if anomaly_id not in state["acknowledged"]:
        state["acknowledged"].append(anomaly_id)
        save_state(state, path)


def remember_turn(session_id: str, role: str, text: str, path: Path | None = None) -> None:
    """Append one conversation turn to a session (cross-session memory)."""
    state = load_state(path)
    session = state["sessions"].setdefault(session_id, {"history": []})
    session["history"].append({"role": role, "text": text})
    session["history"] = session["history"][-50:]  # bound growth
    save_state(state, path)


def session_history(session_id: str, path: Path | None = None) -> list[dict]:
    return load_state(path)["sessions"].get(session_id, {}).get("history", [])
