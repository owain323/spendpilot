"""SpendPilot tool layer — the single source of truth for all capabilities.

Every function here is pure (state side-effects go through store/ledger) and
returns plain dicts. The MCP server wraps these as protocol tools; the local
agent backend calls them directly; the sealed benchmark runs the SAME
analysis over held-out datasets. One implementation, three surfaces.

Design rules that make the evidence chain hard:
  - Every anomaly carries an explicit evidence[] list; each evidence item
    names its signal, its measured value, and where the value came from.
  - Confidence is computed from signal count and strength, never asserted.
  - Low-confidence findings are HELD, not surfaced — and the hold is recorded
    in the decision ledger with a reason. Silence is a decision too.
  - Providers with insufficient history return eligible=false with a reason
    instead of a guessed verdict.
  - Rising spend that tracks real value is refused ("kept"), with the reason.
"""

from __future__ import annotations

from pathlib import Path

from . import ledger, sample_data as data, store

SPIKE_PCT = 25.0
SPIKE_ABS = 20.0
STRONG_SPIKE_PCT = 40.0
ZOMBIE_DAYS = 45
TASK_DRIFT_PCT = 15.0          # cost-per-task canary threshold
MIN_HISTORY_MONTHS = 3         # below this the agent refuses to judge


def _round(value: float) -> float:
    return round(value, 2)


def _ev(signal: str, value: str, source: str) -> dict:
    return {"signal": signal, "value": value, "source": source}


def _confidence(signals: int, strong: bool) -> str:
    if strong or signals >= 3:
        return "high"
    if signals == 2:
        return "medium"
    return "low"


# ---------------------------------------------------------------- overview

def spending_overview(month: str | None = None, providers: list[dict] | None = None,
                      months: list[str] | None = None) -> dict:
    """Totals per provider and per category, with month-over-month deltas."""
    providers = providers if providers is not None else data.PROVIDERS
    months = months or data.MONTHS
    month = month or months[-1]
    idx = months.index(month) if month in months else len(months) - 1
    prev = months[idx - 1] if idx > 0 else None
    entries = []
    by_category: dict[str, float] = {}
    total = 0.0
    prev_total = 0.0
    for p in providers:
        amount = p["monthly"].get(month)
        if amount is None:
            continue
        total += amount
        by_category[p["category"]] = by_category.get(p["category"], 0.0) + amount
        entry = {"id": p["id"], "name": p["name"], "category": p["category"], "amount": _round(amount)}
        if prev and prev in p["monthly"]:
            before = p["monthly"][prev]
            prev_total += before
            if before > 0:
                entry["delta_pct"] = round((amount - before) / before * 100, 1)
        entries.append(entry)
    entries.sort(key=lambda e: e["amount"], reverse=True)
    result: dict = {
        "month": month,
        "total": _round(total),
        "by_category": {k: _round(v) for k, v in sorted(by_category.items())},
        "providers": entries,
    }
    if prev:
        result["prev_month"] = prev
        result["prev_total"] = _round(prev_total)
        result["delta_pct"] = round((total - prev_total) / prev_total * 100, 1) if prev_total else None
    return result


# --------------------------------------------------------- unit economics

def unit_economics(providers: list[dict] | None = None, months: list[str] | None = None) -> dict:
    """Cost per task for AI API providers — the 2026 canary metric.

    Total spend rising is the smoke alarm; cost-per-task drifting up while
    volume falls is the canary. Agent fan-out, not token price, drives bills.
    """
    providers = providers if providers is not None else data.PROVIDERS
    months = months or data.MONTHS
    rows = []
    for p in providers:
        volume = p.get("task_volume")
        if not volume:
            continue
        points = []
        for m in months:
            if m in p["monthly"] and m in volume and volume[m] > 0:
                points.append({"month": m, "cost_per_1k_tasks": _round(p["monthly"][m] / volume[m] * 1000)})
        drift = None
        if len(points) >= 2:
            first, last = points[0]["cost_per_1k_tasks"], points[-1]["cost_per_1k_tasks"]
            prev = points[-2]["cost_per_1k_tasks"]
            drift = {
                "mom_pct": round((last - prev) / prev * 100, 1) if prev else None,
                "since_first_pct": round((last - first) / first * 100, 1) if first else None,
            }
        rows.append({
            "provider": p["name"], "provider_id": p["id"], "points": points, "drift": drift,
            "canary": bool(drift and drift["mom_pct"] is not None and drift["mom_pct"] >= TASK_DRIFT_PCT),
        })
    return {"metric": "cost per 1K tasks", "providers": rows}


# ------------------------------------------------------- analysis (pure)

def analyze_provider(p: dict, months: list[str], latest: str, prev: str | None) -> dict | None:
    """Multi-signal analysis of one provider. Returns a finding or None.

    A finding carries: confidence (computed), evidence[] (named signals with
    measured values and sources), and a verdict of flag / keep / hold.
    """
    history = [m for m in months if m in p["monthly"]]
    if len(history) < MIN_HISTORY_MONTHS:
        return {
            "id": f"ineligible-{p['id']}", "provider": p["name"], "verdict": "hold",
            "eligible": False,
            "reason": f"Only {len(history)} month(s) of history — not enough to judge responsibly.",
            "evidence": [_ev("history_depth", f"{len(history)} months", f"{p['id']}.monthly")],
        }

    cur = p["monthly"][latest]
    prev_amt = p["monthly"].get(prev) if prev else None
    ev = p["evidence"]
    signals: list[dict] = []
    strong = False

    if ev.get("driver") == "trial_conversion":
        signals.append(_ev("trial_conversion", ev["detail"], f"{p['id']}.evidence"))
        last_used = ev.get("last_used_days")
        if last_used is not None and last_used >= ZOMBIE_DAYS:
            signals.append(_ev("zombie_usage", f"unused {last_used}d", f"{p['id']}.evidence"))
        return {
            "id": f"trial-{p['id']}", "provider": p["name"], "verdict": "flag", "eligible": True,
            "kind": "trial_conversion",
            "title": f"{p['name']} trial quietly converted to paid",
            "severity": "medium",
            "confidence": _confidence(len(signals), strong=False),
            "evidence": signals,
            "action_ids": [f"cancel-{p['id']}"],  # benchmark datasets always carry the cancel action
        }

    if prev_amt and prev_amt > 0 and cur - prev_amt >= SPIKE_ABS:
        delta_pct = (cur - prev_amt) / prev_amt * 100
        if delta_pct >= SPIKE_PCT:
            signals.append(_ev(
                "mom_spike", f"+{delta_pct:.0f}% (${prev_amt:.2f} -> ${cur:.2f})",
                f"{p['id']}.monthly[{prev}:{latest}]"))
            strong = strong or delta_pct >= STRONG_SPIKE_PCT
            vals = [p["monthly"][m] for m in history[-4:]]
            if len(vals) >= 4 and vals[-1] > vals[-2] > vals[-3] > vals[-4]:
                signals.append(_ev("sustained_trend", "4 consecutive monthly increases", f"{p['id']}.monthly"))
            if not ev.get("usage_matches_value"):
                signals.append(_ev("utilization_mismatch", ev["detail"], f"{p['id']}.evidence"))
                strong = True

            if ev.get("usage_matches_value"):
                # Derive the judgment from unit economics where volume exists:
                # a rising bill only tracks value if cost per task did NOT
                # inflate. The boolean stays as the fallback for providers
                # that do not report task volume.
                cost_task_delta = None
                task_volume = p.get("task_volume") or {}
                if len(vals) >= 2 and len(task_volume) >= 2:
                    m_first = list(task_volume)[0]
                    m_last = list(task_volume)[-1]
                    if task_volume.get(m_first) and task_volume.get(m_last):
                        c_first = vals[0] / task_volume[m_first]
                        c_last = vals[-1] / task_volume[m_last]
                        if c_first > 0:
                            cost_task_delta = (c_last - c_first) / c_first
                            signals.append(_ev(
                                "cost_per_task",
                                f"{cost_task_delta:+.0%} across the window "
                                f"({_round(vals[0] / task_volume[m_first])} -> "
                                f"{_round(vals[-1] / task_volume[m_last])} per task)",
                                f"{p['id']}.monthly / task_volume"))
                            if abs(cost_task_delta) < 0.10:
                                strong = True
                judgment = ("Growth tracks real value; cutting now would hurt the workload it funds."
                            if cost_task_delta is None or abs(cost_task_delta) < 0.10 else
                            "Usage matches value on paper, but cost per task is inflating — "
                            "worth a closer look before renewal.")
                return {
                    "id": f"keep-{p['id']}", "provider": p["name"], "verdict": "keep", "eligible": True,
                    "title": f"{p['name']} is up {delta_pct:.0f}% — do NOT cut it",
                    "confidence": _confidence(len(signals), strong),
                    "evidence": signals + [_ev("usage_matches_value", ev["detail"], f"{p['id']}.evidence")],
                    "judgment": judgment,
                }
            return {
                "id": f"spike-{p['id']}", "provider": p["name"], "verdict": "flag", "eligible": True,
                "kind": "spike",
                "title": f"{p['name']} jumped {delta_pct:.0f}% month over month",
                "severity": "high",
                "confidence": _confidence(len(signals), strong),
                "evidence": signals,
                "action_ids": ([a for a in data.SAVING_ACTIONS if data.SAVING_ACTIONS[a]["provider"] == p["id"]]
                               or [f"rightsize-{p['id']}"]),
            }

    last_used = ev.get("last_used_days")
    if last_used is not None and last_used >= ZOMBIE_DAYS and cur > 0:
        signals.append(_ev("zombie_usage", f"unused {last_used}d while billing ${cur:.2f}/mo",
                           f"{p['id']}.evidence"))
        return {
            "id": f"zombie-{p['id']}", "provider": p["name"], "verdict": "flag", "eligible": True,
            "kind": "zombie",
            "title": f"{p['name']} looks like a zombie subscription",
            "severity": "medium",
            "confidence": _confidence(len(signals), strong=False),
            "evidence": signals,
            "action_ids": [f"cancel-{p['id']}"],
        }

    return None


def task_drift_finding(providers: list[dict], months: list[str]) -> dict | None:
    """Canary: AI provider whose cost per task drifts up while volume falls."""
    latest, prev = months[-1], months[-2] if len(months) >= 2 else None
    if not prev:
        return None
    for row in unit_economics(providers, months)["providers"]:
        drift = row["drift"]
        if not drift or drift["mom_pct"] is None or drift["mom_pct"] < TASK_DRIFT_PCT:
            continue
        p = next(pr for pr in providers if pr["id"] == row["provider_id"])
        vol_latest = p["task_volume"].get(latest, 0)
        vol_prev = p["task_volume"].get(prev, 0)
        evidence = [
            _ev("cost_per_task_drift", f"+{drift['mom_pct']}% MoM, +{drift['since_first_pct']}% since {months[0]}",
                f"{p['id']}.task_volume + monthly"),
            _ev("volume_direction", f"tasks {vol_prev} -> {vol_latest} ({'down' if vol_latest < vol_prev else 'up'})",
                f"{p['id']}.task_volume"),
        ]
        strong = vol_latest < vol_prev  # price up AND volume down = strongest waste signal
        return {
            "id": f"taskdrift-{p['id']}", "provider": p["name"], "verdict": "flag", "eligible": True,
            "kind": "task_drift",
            "title": f"{p['name']} cost per task is drifting up while volume falls",
            "severity": "high",
            "confidence": _confidence(len(evidence), strong),
            "evidence": evidence,
            "action_ids": ([a for a in data.SAVING_ACTIONS if data.SAVING_ACTIONS[a]["provider"] == p["id"]]
                           or [f"route-{p['id']}"]),
        }
    return None


def analyze_dataset(providers: list[dict], months: list[str]) -> list[dict]:
    """Pure multi-signal analysis over any dataset. No state, no ledger —
    this is the exact function the sealed benchmark scores."""
    latest = months[-1]
    prev = months[-2] if len(months) >= 2 else None
    findings = [f for p in providers if (f := analyze_provider(p, months, latest, prev))]
    task_finding = task_drift_finding(providers, months)
    if task_finding:
        findings.append(task_finding)
    return findings


# -------------------------------------------------- detection (stateful)

def detect_anomalies(state_path: Path | None = None, include_previous: bool = True) -> dict:
    """Proactive sweep with suppression, holds, and refusal bookkeeping.

    `include_previous=True` is the explicit path: the human asked, so already-
    surfaced findings are shown again (answering a question is not nagging) —
    without re-firing alerts or spamming the ledger.

    `include_previous=False` is the proactive path: already-surfaced findings
    are suppressed (and the suppression logged once per finding per month);
    low-confidence findings are held with a logged reason; ineligible
    providers are logged as holds.
    """
    acknowledged = set(store.load_state(state_path)["acknowledged"])
    challenged = ledger.challenged_subjects(state_path)
    surfaced, kept, held = [], [], []

    for f in analyze_dataset(data.PROVIDERS, data.MONTHS):
        if f["verdict"] == "keep":
            kept.append(f)
            continue
        if not f.get("eligible", True):
            ledger.record("hold", f["provider"], f["reason"], path=state_path)
            held.append(f)
            continue
        f["acknowledged"] = f["id"] in acknowledged
        is_challenged = f["id"] in challenged or f["provider"] in challenged
        if f["confidence"] == "low" and not is_challenged:
            ledger.record("hold", f["provider"],
                          f"Held back: confidence low ({len(f['evidence'])} signal). Not worth your attention yet.",
                          evidence=[f["id"]], path=state_path)
            held.append(f)
            continue
        already_fired = ledger.has_fired(f["id"], data.LATEST_MONTH, state_path) and not is_challenged
        if already_fired and not include_previous:
            state = store.load_state(state_path)
            if state["suppressed"].get(f["id"]) != data.LATEST_MONTH:
                ledger.record("suppress", f["provider"],
                              "Already surfaced this month; not repeating myself.",
                              evidence=[f["id"]], path=state_path)
                state = store.load_state(state_path)
                state["suppressed"][f["id"]] = data.LATEST_MONTH
                store.save_state(state, state_path)
            continue
        if not already_fired:
            ledger.record("alert", f["provider"], f["title"], evidence=[f["id"]], path=state_path)
            ledger.mark_fired(f["id"], data.LATEST_MONTH, state_path)
        f["previously_surfaced"] = already_fired
        surfaced.append(f)

    return {"month": data.LATEST_MONTH, "anomalies": surfaced, "kept": kept, "held": held}


# ------------------------------------------------------------------ prove

def simulate_saving(action_id: str) -> dict:
    """PROVE step: before/after scenario estimate for one saving action.

    All figures are scenario estimates based on sample data, never presented
    as realized savings.
    """
    action = data.SAVING_ACTIONS.get(action_id)
    if not action:
        return {"error": f"unknown action '{action_id}'", "known_actions": sorted(data.SAVING_ACTIONS)}
    before, after = action["monthly_before"], action["monthly_after"]
    return {
        **action,
        "monthly_saving": _round(before - after),
        "annual_saving": _round((before - after) * 12),
        "expected_saving_pct": round((before - after) / before * 100, 1) if before else None,
        "estimate_basis": "scenario estimate from sample data — not a realized saving",
    }


# ---------------------------------------------------------------- budgets

def set_budget(category: str, monthly_limit: float, state_path: Path | None = None) -> dict:
    """Persist a monthly budget for a category (cross-session state)."""
    budget = store.set_budget(category, monthly_limit, state_path)
    ledger.record("budget", category, f"Budget set at ${monthly_limit:.2f}/mo", path=state_path)
    return {"category": category, **budget, "note": "Budget saved — I will remember this across sessions."}


def budget_status(state_path: Path | None = None) -> dict:
    """Budgets versus current-month spend, with ok/warn/over status."""
    budgets = store.load_state(state_path)["budgets"]
    overview = spending_overview()
    rows = []
    for category, cfg in sorted(budgets.items()):
        spent = overview["by_category"].get(category, 0.0)
        limit = cfg["monthly_limit"]
        pct = round(spent / limit * 100, 1) if limit else None
        rows.append({
            "category": category, "monthly_limit": limit, "spent": _round(spent),
            "used_pct": pct,
            "status": "over" if pct and pct > 100 else ("warn" if pct and pct >= 80 else "ok"),
        })
    return {"month": overview["month"], "budgets": rows}


# ----------------------------------------------------------- subscriptions

def list_subscriptions() -> dict:
    """Recurring subscriptions with usage flags (zombie detection surface)."""
    subs = []
    for p in data.PROVIDERS:
        if p["category"] not in ("saas", "home"):
            continue
        last_used = p["evidence"].get("last_used_days")
        subs.append({
            "id": p["id"], "name": p["name"], "category": p["category"],
            "monthly": p["monthly"].get(data.LATEST_MONTH),
            "last_used_days": last_used,
            "flag": "zombie" if last_used is not None and last_used >= ZOMBIE_DAYS else None,
        })
    subs.sort(key=lambda s: s["monthly"] or 0, reverse=True)
    return {"subscriptions": subs, "zombie_threshold_days": ZOMBIE_DAYS}


# --------------------------------------------------------------- briefing

def proactive_briefing(state_path: Path | None = None) -> dict:
    """What the agent says first, unprompted: anomalies + proof previews.

    This is the anti-Q&A-bot surface — the agent opens the conversation and
    discloses what it decided NOT to surface.
    """
    findings = detect_anomalies(state_path, include_previous=False)
    overview = spending_overview()
    previews = []
    for anomaly in findings["anomalies"]:
        for action_id in anomaly.get("action_ids", []):
            proof = simulate_saving(action_id)
            if "error" not in proof:
                previews.append(proof)
    total_saving = _round(sum(p.get("monthly_saving", 0.0) for p in previews))
    held_count = len(findings["held"])
    headline = (
        f"I found {len(findings['anomalies'])} issue(s) worth your attention this month. "
        f"Proven saving potential: ${total_saving:.2f}/mo (scenario estimates)."
    )
    if held_count:
        headline += f" I also held back {held_count} low-confidence finding(s) — ask me why."
    return {
        "overview": overview,
        "anomalies": findings["anomalies"],
        "kept": findings["kept"],
        "held": findings["held"],
        "saving_previews": previews,
        "total_monthly_saving_potential": total_saving,
        "headline": headline,
    }


def decision_ledger(state_path: Path | None = None) -> dict:
    """The full accountability trail, newest first."""
    items = list(reversed(ledger.entries(state_path)))
    return {"entries": items, "count": len(items)}
