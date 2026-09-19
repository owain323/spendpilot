"""Agent brain: deterministic intent routing over the tool layer.

The demo must never depend on an LLM being available, so intent routing is
deterministic and offline-safe. An optional Strands + Ollama loop can be
layered on later (see README); the tool calls underneath stay identical.

Every route that surfaces or withholds information flows through the decision
ledger — the agent can always answer "why did you (not) tell me".
"""

from __future__ import annotations

import re

from mcp_server import actions, crossfoot, ledger, tools


def _fmt_money(value: float) -> str:
    return f"${value:,.2f}"


# Provider aliases: free-form mentions ("prove the openai api", "how is
# anthropic doing") must resolve to the right provider instead of falling
# through to the generic fallback.
PROVIDER_ALIASES = {
    "aws": "aws", "ec2": "aws", "amazon": "aws",
    "openai": "openai", "gpt": "openai",
    "anthropic": "anthropic", "claude": "anthropic",
    "figma": "figma",
    "zoom": "zoom",
}


def mentioned_providers(text: str) -> list[str]:
    """Distinct provider ids mentioned in the message, in order of appearance."""
    seen = []
    for alias, pid in PROVIDER_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", text) and pid not in seen:
            seen.append(pid)
    return seen


def handle(message: str, session_id: str, session_token: str | None = None) -> dict:
    """Route one user message to tools and shape the reply + cards payload.

    `session_token` authenticates the web surface; only requests carrying a
    valid token can approve actions (the mandate records the session
    fingerprint as the approver)."""
    text = message.strip().lower()
    mentioned = mentioned_providers(text)

    # --- "why didn't you tell me" / decision ledger -----------------------
    if any(k in text for k in ("why didn't you", "why did you not", "not tell me",
                               "held back", "ledger", "decisions", "what did you decide")):
        trail = tools.decision_ledger()
        held = [e for e in trail["entries"] if e["kind"] in ("hold", "suppress")]
        reply = ("Here is every decision I made, including the ones where I stayed quiet: "
                 f"{len(held)} thing(s) I deliberately did NOT bother you with. "
                 "The full trail - with the tamper-evidence check - lives in the "
                 "Decision ledger panel on the right.")
        return {"reply": reply, "cards": []}

    # --- human challenge (overrule flows back as context) ------------------
    challenge_match = re.search(r"(?:challenge|overrule|disagree)\s+#?(\d+)", text)
    if challenge_match:
        seq = int(challenge_match.group(1))
        try:
            record = ledger.challenge(seq, "overruled via chat")
        except KeyError:
            return {"reply": f"I don't have a decision #{seq} in my ledger.", "cards": []}
        return {
            "reply": (
                f"Noted and recorded — you overruled my call on \"{record['subject']}\". "
                "I won't suppress it the same way again."
            ),
            "cards": [],
        }

    # --- approve: human authorization issues a signed mandate ---------------
    if any(k in text for k in ("approve", "authorized", "go ahead", "yes, do")):
        status = actions.mandate_status()
        open_proposals = [p for p in status["proposals"] if p["status"] == "proposed"]
        id_match = re.search(r"(p-[0-9a-f]{8})", text)
        if id_match:
            target = next((p for p in open_proposals if p["proposal_id"] == id_match.group(1)), None)
            if target is None:
                return {"reply": f"I don't have an open proposal {id_match.group(1)}. "
                                 "Ask for 'mandate status' to see what is on the table.", "cards": []}
        elif open_proposals:
            target = open_proposals[0]  # newest first
        else:
            return {"reply": "There is nothing on the table to approve. Ask me to "
                             "\"prove the saving\" first — I only act on proven actions.",
                    "cards": []}
        mandate = actions.approve_action(target["proposal_id"], session_token=session_token)
        if mandate.get("refused"):
            hint = (" Reload the page to re-authenticate your session, then approve again."
                    if "authenticated" in mandate["error"] else "")
            return {"reply": f"I refused: {mandate['error']} (logged as ledger "
                             f"#{mandate['ledger_seq']}).{hint}", "cards": []}
        return {
            "reply": (
                f"Approved. I issued signed mandate {mandate['mandate_id']} — single-use, "
                f"scoped to {mandate['scope']['operation']} with a hard cap of "
                f"{_fmt_money(mandate['scope']['max_monthly_before'])}/mo, expiring at "
                f"{mandate['expires_at'][11:19]} UTC. Say \"execute\" and I will run it."
            ),
            "cards": [{"type": "mandate", **mandate}],
        }

    # --- execute: the adapter runs only through a valid mandate -------------
    if any(k in text for k in ("execute", "carry it out", "run it", "do it")):
        status = actions.mandate_status()
        issued = [m for m in status["mandates"] if m["status"] == "issued"]
        id_match = re.search(r"(m-[0-9a-f]{8})", text)
        if id_match:
            target = next((m for m in issued if m["mandate_id"] == id_match.group(1)), None)
            if target is None:
                return {"reply": f"No executable mandate {id_match.group(1)} — it may be "
                                 "consumed or expired. Ask for 'mandate status'.", "cards": []}
        elif issued:
            target = issued[0]
        else:
            open_proposals = [p for p in status["proposals"] if p["status"] == "proposed"]
            hint = (f" Proposal {open_proposals[0]['proposal_id']} is still waiting for your "
                    "\"approve\"." if open_proposals else
                    " Ask me to \"prove the saving\", then \"approve\" — nothing executes on trust.")
            return {"reply": "I hold no valid mandate, so I will not act." + hint, "cards": []}
        receipt = actions.execute_action(target["mandate_id"])
        if receipt.get("refused"):
            return {"reply": f"Refused — {receipt['error']} (ledger #{receipt['ledger_seq']}).",
                    "cards": []}
        return {
            "reply": (
                f"Done. {receipt['operation']} ran through the {receipt['adapter']} adapter "
                f"(simulated), mandated by {receipt['mandate_id']}. Scenario saving: "
                f"{_fmt_money(receipt['monthly_saving'])}/mo. The receipt is in the ledger."
            ),
            "cards": [{"type": "receipt", **receipt}],
        }

    # --- receipts / mandate status ------------------------------------------
    if any(k in text for k in ("receipt", "what did you do", "mandate", "what have you done")):
        status = actions.mandate_status()
        c = status["counts"]
        reply = (f"Action trail: {c['proposals_open']} proposal(s) awaiting approval, "
                 f"{c['mandates_issued']} mandate(s) issued and unused, "
                 f"{c['executed']} execution(s) completed.")
        if not any(c.values()):
            reply = "No actions yet. The loop is: prove -> approve -> execute -> receipt."
        return {"reply": reply, "cards": [{"type": "mandates", **status}]}

    # --- bill crossfoot (the numbers must reconcile) ------------------------
    if any(k in text for k in ("crossfoot", "cross-foot", "do the numbers add up",
                               "check the numbers", "reconcile")):
        result = crossfoot.bill_crossfoot()
        if result["ok"]:
            reply = (f"Every number reconciles: {result['lines_checked']} line items across "
                     f"{result['bills_checked']} bills, both rules pass. "
                     "Quantity times unit cost equals each line, and the lines sum to each bill.")
        else:
            reply = (f"Reconciliation FAILED on {len(result['failures'])} check(s) - "
                     f"details: {result['failures'][:2]}.")
        return {"reply": reply, "cards": [{"type": "crossfoot", **result}]}

    # --- unit economics (the 2026 canary) ----------------------------------
    if any(k in text for k in ("unit", "per task", "per-task", "canary", "economics")):
        econ = tools.unit_economics()
        canaries = [r for r in econ["providers"] if r["canary"]]
        reply = "Cost per 1K tasks, per AI provider:"
        if canaries:
            names = ", ".join(r["provider"] for r in canaries)
            reply += f" Canary is singing for {names} — unit cost is drifting up."
        return {"reply": reply, "cards": [{"type": "unit", "providers": econ["providers"]}]}

    # --- budgets ------------------------------------------------------------
    budget_match = re.search(r"budget.*?(\$?\d+(?:\.\d+)?).*?(?:for|on)\s+([a-z\-]+)", text)
    if budget_match or ("set" in text and "budget" in text):
        amount = float(budget_match.group(1).lstrip("$")) if budget_match else 300.0
        category = budget_match.group(2) if budget_match else "home"
        result = tools.set_budget(category, amount)
        return {
            "reply": (
                f"Done — {_fmt_money(result['monthly_limit'])}/mo budget for "
                f"{category} is saved and logged. I'll keep watching it, even after you close this page."
            ),
            "cards": [{"type": "budget", **row} for row in tools.budget_status()["budgets"]],
        }

    if "budget" in text:
        status = tools.budget_status()
        if not status["budgets"]:
            return {"reply": "No budgets yet. Try: \"set a $300 budget for home\".", "cards": []}
        return {
            "reply": f"Here is where your budgets stand for {status['month']}:",
            "cards": [{"type": "budget", **row} for row in status["budgets"]],
        }

    # --- subscriptions -------------------------------------------------------
    if "subscription" in text:
        subs = tools.list_subscriptions()["subscriptions"]
        zombies = [s for s in subs if s["flag"] == "zombie"]
        reply = f"You have {len(subs)} recurring subscriptions."
        if zombies:
            reply += f" {len(zombies)} look(s) unused — worth a decision."
        return {"reply": reply, "cards": [{"type": "subscriptions", "items": subs}]}

    # --- proof ---------------------------------------------------------------
    save_match = re.search(r"(rightsize-ec2|cancel-figma|annual-zoom|route-haiku)", text)
    if save_match or any(k in text for k in ("prove", "saving", "save", "optimize")):
        action_id = save_match.group(1) if save_match else None
        if not action_id and mentioned:
            # "prove the openai api" must prove OPENAI's action, not whoever
            # happens to have the largest headline number.
            from mcp_server import sample_data as sd
            action_id = next((a for a in sd.SAVING_ACTIONS
                              if sd.SAVING_ACTIONS[a]["provider"] in mentioned), None)
        if not action_id:
            # Pure analysis (no ledger side effects): proof must be available
            # even when the anomaly was already surfaced and suppressed.
            from mcp_server import sample_data as sd

            findings = tools.analyze_dataset(sd.PROVIDERS, sd.MONTHS)
            valid = [aid for f in findings if f["verdict"] == "flag"
                     for aid in f.get("action_ids", []) if aid in sd.SAVING_ACTIONS]
            if valid:
                action_id = max(valid, key=lambda i: sd.SAVING_ACTIONS[i]["monthly_before"]
                                - sd.SAVING_ACTIONS[i]["monthly_after"])
        if action_id:
            proof = tools.simulate_saving(action_id)
            if "error" in proof:
                return {"reply": f"I can't prove that action: {proof['error']}.", "cards": []}
            # Proof is read-only; proposing is a logged decision. The proposal
            # is what makes the action executable — after human approval.
            proposal = actions.propose_action(action_id)
            card = {"type": "saving", **proof}
            reply = (
                f"Proof for \"{proof['title']}\": {_fmt_money(proof['monthly_before'])}/mo before, "
                f"{_fmt_money(proof['monthly_after'])}/mo after — expected saving "
                f"{proof['expected_saving_pct']}% ({proof['estimate_basis']})."
            )
            if "proposal_id" in proposal:
                card["proposal_id"] = proposal["proposal_id"]
                reply += (f" I put it on the table as proposal {proposal['proposal_id']} — "
                          "say \"approve\" to authorize it, and I will issue a signed mandate.")
            return {"reply": reply, "cards": [card]}

    # --- anomalies -------------------------------------------------------------
    if any(k in text for k in ("anomal", "alert", "unusual", "wrong", "issue", "sweep")):
        findings = tools.detect_anomalies()
        cards = [{"type": "anomaly", **a} for a in findings["anomalies"]]
        cards += [{"type": "kept", **k} for k in findings["kept"]]
        reply = f"Here is what needs your attention for {findings['month']}:"
        if findings["held"]:
            reply += f" ({len(findings['held'])} low-confidence item(s) held back — ask me why.)"
        return {"reply": reply, "cards": cards}

    # --- overview --------------------------------------------------------------
    if any(k in text for k in ("overview", "spend", "total", "summary", "how much")):
        overview = tools.spending_overview()
        return {
            "reply": (
                f"In {overview['month']} you spent {_fmt_money(overview['total'])} total "
                f"({overview['delta_pct']:+.1f}% vs {overview['prev_month']}). "
                "Breakdown is on the cards."
            ),
            "cards": [{"type": "overview", **overview}],
        }

    if mentioned:
        # A bare provider mention is a question about that provider - answer
        # with a dedicated trend card (one provider) or the overview (several).
        overview = tools.spending_overview()
        line = next((p for p in overview["providers"]
                     if p["id"] in mentioned), None)
        if line:
            cards = [{"type": "overview", **overview}]
            if len(mentioned) == 1:
                from mcp_server import sample_data as sd
                prov = next((q for q in sd.PROVIDERS if q["id"] == line["id"]), None)
                if prov and prov.get("monthly"):
                    cards = [{
                        "type": "provider-detail",
                        "id": line["id"],
                        "name": line["name"],
                        "monthly": prov["monthly"],
                        "latest": line["amount"],
                        "delta_pct": line.get("delta_pct"),
                        "month": overview["month"],
                        "prev_month": overview["prev_month"],
                    }]
            delta_txt = ""
            if line.get("delta_pct") is not None:
                d = line["delta_pct"]
                delta_txt = f" ({'+' if d > 0 else ''}{d}% vs {overview['prev_month']})"
            return {
                "reply": (
                    f"{line['name']} spent {_fmt_money(line['amount'])} in {overview['month']}{delta_txt}. "
                    "Ask me to \"prove the saving\" for anything that looks off."
                ),
                "cards": cards,
            }
    return {
        "reply": (
            "I watch your bills across providers, prove savings before proposing them, and — "
            "with your signed mandate — I execute them and hand you the receipt. "
            "Try: \"anything unusual?\", \"prove the saving\", \"approve\", \"execute\", "
            "\"cost per task\", \"set a $300 budget for home\", or \"why didn't you tell me?\""
        ),
        "cards": [],
    }


def opening(session_id: str) -> dict:
    """The agent speaks first on a fresh session — the anti-Q&A-bot surface."""
    briefing = tools.proactive_briefing()
    cards = [{"type": "anomaly", **a} for a in briefing["anomalies"]]
    cards += [{"type": "kept", **k} for k in briefing["kept"]]
    # "Needs attention" counts what is ACTUALLY wrong this month, not what
    # this particular greeting chose to repeat: in a repeat visit the
    # proactive path suppresses already-surfaced findings, and reporting 0
    # while the ledger holds three alerts would contradict the sweep.
    month = briefing["overview"]["month"]
    alerted = {e["subject"] for e in tools.decision_ledger()["entries"]
               if e["kind"] == "alert"}
    return {"reply": briefing["headline"], "cards": cards, "stats": {
        "month": month,
        "total": briefing["overview"]["total"],
        "delta_pct": briefing["overview"]["delta_pct"],
        "anomalies": len(briefing["anomalies"]) or len(alerted),
        "saving_potential": briefing["total_monthly_saving_potential"],
    }}
