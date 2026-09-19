# proactive_briefing

> MCP tool `proactive_briefing` — what the agent says FIRST, unprompted:
> anomalies, keep judgments, held findings, and saving proof previews.

## When it activates

- A fresh or returning session opens (`/api/opening` in the web app).
- This is the anti-Q&A-bot surface: the agent opens the conversation.

## Flow

1. Runs `detect_anomalies` on the proactive path (repeats suppressed).
2. Builds saving previews only for flagged findings with valid catalog
   actions — every preview carries the scenario-estimate label.
3. Headline: issue count + proven saving potential + the count of held
   low-confidence findings ("ask me why").

## Boundaries & refusal cases

- Never fabricates a preview for an action that cannot be proven
  (`test_previews_only_valid_actions`).
- The opening in a repeat visit does not re-fire alerts; the reply counts
  what is actually wrong this month, not what the greeting repeated.

## Linked tests

- `tests/test_tools.py::TestProactiveBriefing` (headline, previews,
  total consistency)

## Evidence

- `docs/evidence/e2e-flow.txt` steps 1 and 7 (opening + reopen memory);
  `docs/evidence/mcp-roundtrip.txt` step 4
