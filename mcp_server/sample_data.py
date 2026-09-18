"""Synthetic multi-provider billing data for SpendPilot.

All figures are fictional sample data. Nothing here touches a real account,
credential, or network resource.

Six months of history (2026-03 .. 2026-08) so trend signals have real depth.
AI API providers carry task volumes so unit economics (cost per task) can be
computed — in 2026 the bill problem is agent fan-out, not per-token price.

The dataset deliberately contains the stories the agent should find:
  - an idle EC2 instance (waste, provable),
  - a quiet trial-to-paid conversion (Figma),
  - a zombie subscription (unused 61 days),
  - cost-per-task drift on OpenAI (the canary, not the smoke alarm),
  - and one honest DO-NOT-CUT case: Anthropic spend doubling because a real
    launch doubled real usage — the agent must refuse to cut it.
"""

from __future__ import annotations

MONTHS: list[str] = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
LATEST_MONTH = "2026-08"
PREVIOUS_MONTH = "2026-07"

PROVIDERS: list[dict] = [
    {
        "id": "aws",
        "name": "AWS",
        "category": "cloud",
        "monthly": {
            "2026-03": 112.40, "2026-04": 115.90, "2026-05": 118.20,
            "2026-06": 118.20, "2026-07": 126.80, "2026-08": 181.34,
        },
        "evidence": {
            "driver": "ec2",
            "detail": "EC2 instance i-0f3a9c21 ran 744h with 3% avg CPU for 19 days",
            "usage_matches_value": False,
        },
    },
    {
        "id": "openai",
        "name": "OpenAI API",
        "category": "ai-api",
        # Total spend creeps up gently, but cost PER TASK drifts hard — the canary.
        "monthly": {
            "2026-03": 38.90, "2026-04": 39.80, "2026-05": 41.20,
            "2026-06": 42.10, "2026-07": 45.60, "2026-08": 47.02,
        },
        "task_volume": {
            "2026-03": 15200, "2026-04": 15800, "2026-05": 16500,
            "2026-06": 17100, "2026-07": 15900, "2026-08": 12800,
        },
        "evidence": {
            "driver": "tokens",
            "detail": "82% of calls are short classification tasks; cost per task rose while volume fell",
            "usage_matches_value": False,
        },
    },
    {
        "id": "anthropic",
        "name": "Anthropic API",
        "category": "ai-api",
        "monthly": {
            "2026-03": 22.50, "2026-04": 24.00, "2026-05": 26.10,
            "2026-06": 30.00, "2026-07": 61.50, "2026-08": 128.40,
        },
        "task_volume": {
            "2026-03": 4100, "2026-04": 4400, "2026-05": 4800,
            "2026-06": 5500, "2026-07": 11300, "2026-08": 23600,
        },
        "evidence": {
            "driver": "tokens",
            "detail": "Token volume doubled twice; tracks the launch traffic of the new project 1:1",
            "usage_matches_value": True,  # growth is real value -> the agent must refuse to cut
        },
    },
    {
        "id": "figma",
        "name": "Figma",
        "category": "saas",
        "monthly": {
            "2026-03": 0.00, "2026-04": 0.00, "2026-05": 0.00,
            "2026-06": 0.00, "2026-07": 0.00, "2026-08": 15.00,
        },
        "evidence": {
            "driver": "trial_conversion",
            "detail": "Free trial ended 2026-08-03 and silently converted to a paid seat",
            "trial_end": "2026-08-03",
            "last_used_days": 61,
            "usage_matches_value": False,
        },
    },
    {
        "id": "notion",
        "name": "Notion",
        "category": "saas",
        "monthly": {
            "2026-03": 10.00, "2026-04": 10.00, "2026-05": 10.00,
            "2026-06": 10.00, "2026-07": 10.00, "2026-08": 10.00,
        },
        "evidence": {"driver": "seats", "detail": "2 seats, both active weekly", "last_used_days": 2, "usage_matches_value": True},
    },
    {
        "id": "zoom",
        "name": "Zoom",
        "category": "saas",
        "monthly": {
            "2026-03": 14.99, "2026-04": 14.99, "2026-05": 14.99,
            "2026-06": 14.99, "2026-07": 14.99, "2026-08": 14.99,
        },
        "evidence": {
            "driver": "seats",
            "detail": "Monthly plan; annual plan would be $12.49/mo equivalent",
            "last_used_days": 4,
            "usage_matches_value": True,
        },
    },
    {
        "id": "netflix",
        "name": "Netflix",
        "category": "home",
        "monthly": {
            "2026-03": 15.49, "2026-04": 15.49, "2026-05": 15.49,
            "2026-06": 15.49, "2026-07": 15.49, "2026-08": 15.49,
        },
        "evidence": {"driver": "subscription", "detail": "Household streaming, in active use", "last_used_days": 1, "usage_matches_value": True},
    },
    {
        "id": "spotify",
        "name": "Spotify Family",
        "category": "home",
        "monthly": {
            "2026-03": 16.99, "2026-04": 16.99, "2026-05": 16.99,
            "2026-06": 16.99, "2026-07": 16.99, "2026-08": 16.99,
        },
        "evidence": {"driver": "subscription", "detail": "Family plan, 4 of 6 slots used", "last_used_days": 1, "usage_matches_value": True},
    },
    {
        "id": "grocery",
        "name": "Groceries (card rollup)",
        "category": "home",
        "monthly": {
            "2026-03": 254.90, "2026-04": 261.30, "2026-05": 248.75,
            "2026-06": 268.40, "2026-07": 291.10, "2026-08": 213.55,
        },
        "evidence": {"driver": "card", "detail": "Card statement rollup; August dipped after a travel month", "usage_matches_value": True},
    },
]

# Saving actions the agent can prove before proposing. before/after are monthly
# scenario estimates, labeled as such everywhere they surface.
SAVING_ACTIONS: dict[str, dict] = {
    "rightsize-ec2": {
        "id": "rightsize-ec2",
        "title": "Rightsize the idle EC2 instance",
        "provider": "aws",
        "monthly_before": 181.34,
        "monthly_after": 96.20,
        "confidence": "high",
        "proof_detail": {
            "resource": "i-0f3a2 (t3.2xlarge, us-east-1)",
            "observations": ["CPU: P50 3.1% / P95 7.4% across 19 consecutive days", "Network I/O flat at ~12 MB/s (no traffic spikes)", "Zero burst-credit consumption in the last 30 days"],
            "assumptions": ["Same workload envelope and schedule after downsizing", "Attached storage and availability requirements unchanged"],
            "pricing_basis": "AWS on-demand pricing, us-east-1, sampled 2026-09-15",
        },
        "risk": "Low — the instance ran at 3% CPU for 19 days; a smaller class keeps headroom.",
        "proof_steps": [
            "CPU utilization < 5% for 19 consecutive days",
            "No burst pattern in the last 30 days of sample telemetry",
            "Downsize to t3.large keeps 2x observed peak headroom",
        ],
    },
    "cancel-figma": {
        "id": "cancel-figma",
        "title": "Cancel the unused Figma seat",
        "provider": "figma",
        "monthly_before": 15.00,
        "monthly_after": 0.00,
        "confidence": "medium",
        "proof_detail": {
            "resource": "seat 7/12 (editor, team Acme Studio)",
            "observations": ["Last document open: 61 days ago", "Zero comments or edits in the last 90 days", "Converted from a free trial on 2026-08-03 without an explicit upgrade"],
            "assumptions": ["No upcoming project requires this seat"],
            "pricing_basis": "Figma Organization per-editor seat list price",
        },
        "risk": "Medium — confirm with the designer on the team before canceling.",
        "proof_steps": [
            "Seat unused for 61 days",
            "Converted from a free trial on 2026-08-03 without an explicit upgrade",
        ],
    },
    "annual-zoom": {
        "id": "annual-zoom",
        "title": "Switch Zoom to the annual plan",
        "provider": "zoom",
        "monthly_before": 14.99,
        "monthly_after": 12.49,
        "confidence": "high",
        "proof_detail": {
            "resource": "license 3/8 (Pro, billed monthly)",
            "observations": ["4.3 meetings/week average across 3 sampled months", "Peak concurrent participants: 6 (well under plan limits)"],
            "assumptions": ["Usage stays steady quarter over quarter", "No mid-year downgrade penalty applies"],
            "pricing_basis": "Zoom list price: $14.99 monthly vs $12.49 annual, per license/month",
        },
        "risk": "Low — 12-month commitment; usage is steady at 4+ meetings/week.",
        "proof_steps": ["Steady weekly usage for 3 sampled months", "Annual pricing saves 16.7%"],
    },
    "route-haiku": {
        "id": "route-haiku",
        "title": "Route short OpenAI classification calls to a smaller model",
        "provider": "openai",
        "monthly_before": 47.02,
        "monthly_after": 18.90,
        "confidence": "medium",
        "proof_detail": {
            "resource": "gpt-5-mini routing policy (classification queue only)",
            "observations": ["82% of calls are short classification prompts (under 400 tokens)", "Cost per task rose 43% in two months while task volume fell 24%", "Classification eval-set accuracy baseline: 96.2%"],
            "assumptions": ["Prompt-context growth is not workload growth", "Quality is re-validated on the eval set before the switch sticks"],
            "pricing_basis": "Provider list prices per 1K tasks, sampled 2026-09-15",
        },
        "risk": "Medium — quality must be re-validated on the classification eval set first.",
        "proof_steps": [
            "82% of calls are short classification prompts (< 400 tokens)",
            "Cost per task rose 43% in two months while task volume fell 24%",
            "Scenario estimate only — realized saving depends on retry rates",
        ],
    },
}
