"""SpendPilot agent backend — bridges the web experience to the tool layer.

Serves the simulated Alexa+ web experience and the chat API. State
(budgets, acknowledgements, session history, decision ledger) persists in
local JSON files, which is what makes cross-session memory real rather than
staged.

Session isolation (2026-09-18): the browser mints an authenticated session
(POST /api/session) and presents its token on every request. Each session
gets its own workspace state file, so judges can never pollute each other's
demo, and ONLY authenticated sessions can approve actions. Requests without
a token run in a shared anonymous workspace that cannot approve anything.
State access is serialized under a process lock — the demo is single
process, and correctness beats concurrency here.

Run:  python -m agent.backend   # serves http://127.0.0.1:8200
"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from mcp_server import actions, store, tools

from . import brain

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="SpendPilot", version="0.4.0")

# One process-wide lock around every state-touching request: workspace
# selection is process-level, so requests must not interleave.
_STATE_LOCK = threading.Lock()


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    session_token: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    cards: list[dict]
    stats: dict | None = None


class SessionResponse(BaseModel):
    session_token: str
    workspace: str


@app.post("/api/session", response_model=SessionResponse)
def create_session() -> SessionResponse:
    """Mint an authenticated web session: its token approves actions and
    pins its own workspace state file."""
    return SessionResponse(**actions.open_session())


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    session_id = req.session_id or uuid.uuid4().hex[:12]
    with _STATE_LOCK:
        store.set_workspace(store.workspace_for_token(req.session_token))
        try:
            store.remember_turn(session_id, "user", req.message)
            result = brain.handle(req.message, session_id, session_token=req.session_token)
            store.remember_turn(session_id, "agent", result["reply"])
        finally:
            store.set_workspace(None)
    return ChatResponse(session_id=session_id, reply=result["reply"], cards=result["cards"])


@app.get("/api/opening", response_model=ChatResponse)
def opening(session_id: str | None = None,
            session_token: str | None = None) -> ChatResponse:
    """Proactive first message; restores context when the session is known."""
    session_id = session_id or uuid.uuid4().hex[:12]
    with _STATE_LOCK:
        store.set_workspace(store.workspace_for_token(session_token))
        try:
            history = store.session_history(session_id)
            if history:
                status = brain.handle("budget", session_id)
                briefing = tools.proactive_briefing()
                return ChatResponse(
                    session_id=session_id,
                    reply="Welcome back. I remember our last conversation — your budgets are still on watch, "
                          "and the ledger kept recording while you were away.",
                    cards=status["cards"],
                    stats={
                        "month": briefing["overview"]["month"],
                        "total": briefing["overview"]["total"],
                        "delta_pct": briefing["overview"]["delta_pct"],
                        "anomalies": len(briefing["anomalies"]),
                        "saving_potential": briefing["total_monthly_saving_potential"],
                    },
                )
            result = brain.opening(session_id)
            store.remember_turn(session_id, "agent", result["reply"])
        finally:
            store.set_workspace(None)
    return ChatResponse(session_id=session_id, reply=result["reply"],
                        cards=result["cards"], stats=result.get("stats"))


@app.get("/api/ledger")
def get_ledger(session_token: str | None = None) -> dict:
    """The full decision ledger — the observability surface."""
    with _STATE_LOCK:
        store.set_workspace(store.workspace_for_token(session_token))
        try:
            return tools.decision_ledger()
        finally:
            store.set_workspace(None)


@app.get("/api/unit-economics")
def get_unit_economics() -> dict:
    return tools.unit_economics()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


def main() -> None:
    import os

    import uvicorn

    uvicorn.run(app, host="127.0.0.1",
                port=int(os.environ.get("SPENDPILOT_WEB_PORT", "8200")))


if __name__ == "__main__":
    main()
