"""SpendPilot MCP server — self-hosted, Streamable HTTP transport.

Implements the Model Context Protocol over Streamable HTTP as required by the
Alexa+ track (minimum MCP spec 2025-11-25). Run:

    python -m mcp_server.server          # listens on 127.0.0.1:8101/mcp

The tools exposed here are the same pure functions in `mcp_server.tools`
that the local web agent uses — one implementation, two surfaces.
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from . import actions, tools

MCP_APPS_DIR = Path(__file__).resolve().parent.parent / "web" / "mcp-apps"
APPROVAL_CARD_URI = "ui://spendpilot/approval-card"

# The server binds to loopback and sits behind a reverse proxy in
# production, which forwards the original Host (the public domain).
# Local probes talk to it directly on loopback. Keep DNS-rebinding
# protection ON with an explicit allowlist covering both faces.
_TRANSPORT_SECURITY = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=[
        "spendpilot.owain32380.cn",
        "127.0.0.1:*",
        "localhost:*",
    ],
    allowed_origins=[
        "https://spendpilot.owain32380.cn",
        "http://127.0.0.1:*",
        "http://localhost:*",
    ],
)

mcp = FastMCP(
    "spendpilot",
    instructions=(
        "Agentic spend-remediation copilot for AI and cloud teams. Watches "
        "multi-provider bills, proves savings before proposing them, remembers "
        "budgets across sessions, and — with a signed mandate issued only to an "
        "authenticated web session — executes the approved action through "
        "provider adapters and returns a receipt. Every decision, including "
        "holds, refusals, and executions, is recorded in a hash-chained ledger."
    ),
    host=os.environ.get("SPENDPILOT_HOST", "127.0.0.1"),
    port=int(os.environ.get("SPENDPILOT_PORT", "8101")),
    transport_security=_TRANSPORT_SECURITY,
)


@mcp.tool()
def spending_overview(month: str | None = None) -> dict:
    """Totals per provider and per category for a month, with month-over-month deltas."""
    return tools.spending_overview(month)


@mcp.tool()
def detect_anomalies(include_previous: bool = True) -> dict:
    """Find spend spikes, trial conversions, zombie subscriptions, and
    cost-per-task drift. Confidence is computed from named evidence signals;
    low-confidence findings are held (and logged), not surfaced. Rising spend
    that tracks real value is returned under `kept` with a do-not-cut judgment.

    include_previous=False applies proactive suppression: findings already
    surfaced this month are withheld (and the suppression is logged)."""
    return tools.detect_anomalies(include_previous=include_previous)


@mcp.tool()
def simulate_saving(action_id: str) -> dict:
    """Prove a saving action before proposing it: before/after scenario estimate,
    confidence, risk, and the evidence chain. Not a realized saving."""
    return tools.simulate_saving(action_id)


@mcp.tool()
def set_budget(category: str, monthly_limit: float) -> dict:
    """Persist a monthly budget for a category. Survives across sessions."""
    return tools.set_budget(category, monthly_limit)


@mcp.tool()
def budget_status() -> dict:
    """All budgets versus current-month spend with ok/warn/over status."""
    return tools.budget_status()


@mcp.tool()
def list_subscriptions() -> dict:
    """Recurring subscriptions with usage flags (zombie detection)."""
    return tools.list_subscriptions()


@mcp.tool()
def unit_economics() -> dict:
    """Cost per 1K tasks per AI provider with drift detection — the canary metric
    (cost-per-task drift warns before the total-spend smoke alarm)."""
    return tools.unit_economics()


@mcp.tool()
def proactive_briefing() -> dict:
    """The agent's unprompted opening: anomalies, proof previews, saving potential,
    and a disclosure of what it deliberately held back."""
    return tools.proactive_briefing()


@mcp.tool()
def decision_ledger() -> dict:
    """The full decision trail: every alert, suppression, hold, refusal, budget
    change, and human challenge — with one-line reasons. Silence is auditable."""
    return tools.decision_ledger()


# ------------------------------------------------------------- action loop
# The 2026 agentic-payments discipline (AP2/ACP/x402 converge on this shape):
# an agent that touches money carries proof of human authorization, bounded
# in scope and time, and leaves an audit trail. propose -> approve (signed
# mandate) -> execute (adapter runs only through a valid mandate).

@mcp.tool(meta={"ui": {"resourceUri": APPROVAL_CARD_URI}})
def propose_action(action_id: str) -> dict:
    """Put a proven saving action on the table as a bounded proposal.
    Hosts that implement MCP Apps render the linked approval card
    (ui://spendpilot/approval-card) for this tool."""
    return actions.propose_action(action_id)


@mcp.tool()
def approve_action(proposal_id: str) -> dict:
    """Refuses, by design: approval requires an authenticated web session.

    This MCP surface cannot approve actions and does not accept self-reported
    approvers — a caller saying "approver=human" proves nothing. The refusal
    is structured and logged in the ledger. Approve in the web demo, which
    authenticates the session; the mandate it issues is signed, single-use,
    scope-capped, and records the approving session fingerprint."""
    return actions.approve_action(proposal_id)


@mcp.tool()
def execute_action(mandate_id: str) -> dict:
    """Run the provider adapter ONLY through a valid mandate: signature,
    expiry, single-use, and scope drift are all verified; every refusal is
    logged. Returns a receipt (simulated adapter, clearly labeled)."""
    return actions.execute_action(mandate_id)


@mcp.tool()
def mandate_status() -> dict:
    """All proposals, mandates, and receipts — the action accountability view."""
    return actions.mandate_status()


# ---------------------------------------------------------------- MCP Apps
# SEP-1865 (2026-01-26): tools may return interactive UI as sandboxed ui://
# resources. Served here as a real MCP resource with the mcp-app profile
# mime type, so hosts (Claude, ChatGPT, Goose, VS Code) can render the
# approval flow inline instead of as plain text.

@mcp.resource(
    APPROVAL_CARD_URI,
    name="approval-card",
    title="SpendPilot Approval Card",
    description="Interactive approve-and-issue-mandate card for proposed saving actions.",
    mime_type="text/html;profile=mcp-app",
    meta={"ui": {"csp": {"resourceDomains": [], "connectDomains": []}}},
)
def approval_card_app() -> str:
    return (MCP_APPS_DIR / "approval-card.html").read_text(encoding="utf-8")


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
