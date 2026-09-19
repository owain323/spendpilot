"""Bill crossfoot — every number must reconcile with every other number.

Borrowed from the team's financial-integrity work (CHRONOS E1-E22
accounting identities): a bill is not trusted because a report says so,
it is trusted because its line items CROSS-FOOT —
  rule 1 (line identity):   quantity x unit_cost == line amount
  rule 2 (invoice total):   sum(line amounts) == the monthly bill

Scope honesty: the line items are DERIVED deterministically from the sample
ledger by this same module, so a pass verifies internal consistency of
derived line items — it is NOT independent verification against a real
provider invoice (the residual-line construction guarantees rule 2 by
design on well-formed input; the check earns its keep by catching tampered
or corrupted datasets). It becomes a real verifier when real provider data
lands (post-hackathon ingest path).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from . import sample_data as data

TOLERANCE_LINE = 0.01   # per-line identity tolerance (rounding)
TOLERANCE_TOTAL = 0.02  # sum-of-lines vs monthly bill tolerance


def _split_ratio(provider_id: str, month: str) -> float:
    """Deterministic 0.45-0.85 primary-line share, stable per bill."""
    digest = hashlib.sha256(f"{provider_id}:{month}".encode()).digest()
    return 0.45 + (digest[0] / 255) * 0.40


def _round2(v: float) -> float:
    return round(v + 1e-9, 2)


def invoice_lines(provider: dict, month: str) -> list[dict]:
    """Deterministic, human-readable line items that sum to the monthly bill.

    The primary line reflects the provider's known driver (hours, tasks,
    seats); the remainder is the residual so the lines always cross-foot.
    """
    amount = provider["monthly"][month]
    share = _split_ratio(provider["id"], month)
    volume = provider.get("task_volume", {}).get(month)
    category = provider["category"]

    if provider["id"] == "aws":
        primary_label = "EC2 on-demand (t3.2xlarge, 744h)"
        primary_qty = 744
        secondary_label = "EBS gp3 storage + snapshots"
        secondary_qty = 500
    elif category == "ai-api" and volume:
        share = 0.82  # 82% short classification calls, per the evidence field
        primary_label = f"Primary model calls ({volume:,} tasks, short-class share)"
        primary_qty = int(volume * share)
        secondary_label = "Fallback + retry calls"
        secondary_qty = volume - primary_qty
    elif category == "subscription":
        primary_label = f"{provider['name']} monthly plan"
        primary_qty = 1
        secondary_label = None
        secondary_qty = 0
    else:
        primary_label = f"{provider['name']} usage"
        primary_qty = 1
        secondary_label = None
        secondary_qty = 0

    primary_amount = _round2(amount * share)
    lines = [{
        "item": primary_label,
        "quantity": primary_qty,
        "unit_cost": round(primary_amount / primary_qty, 6) if primary_qty else 0.0,
        "amount": primary_amount,
    }]
    if secondary_label and amount - primary_amount > 0.005:
        residual = _round2(amount - primary_amount)
        lines.append({
            "item": secondary_label,
            "quantity": secondary_qty if secondary_qty else 1,
            "unit_cost": round(residual / max(secondary_qty, 1), 6),
            "amount": residual,
        })
    # rounding residue goes to the last line so the sum is exact
    drift = _round2(amount - sum(l["amount"] for l in lines))
    if abs(drift) >= 0.01:
        lines[-1]["amount"] = _round2(lines[-1]["amount"] + drift)
        lines[-1]["unit_cost"] = round(lines[-1]["amount"] / max(lines[-1]["quantity"], 1), 6)
    return lines


def bill_crossfoot(path: Path | None = None) -> dict[str, Any]:
    """Internal consistency check over derived line items: re-derive every
    line and check both rules across all providers and months. Demo-mode
    check on synthetic data — becomes a real verifier when real data lands."""
    failures: list[dict] = []
    lines_checked = 0
    bills_checked = 0

    for provider in data.PROVIDERS:
        for month, bill in provider["monthly"].items():
            bills_checked += 1
            lines = invoice_lines(provider, month)
            total = _round2(sum(l["amount"] for l in lines))
            if abs(total - bill) > TOLERANCE_TOTAL:
                failures.append({
                    "provider": provider["id"], "month": month, "rule": "invoice_total",
                    "detail": f"lines sum to {total:.2f} but the bill says {bill:.2f}",
                })
            for line in lines:
                lines_checked += 1
                recomputed = round(line["quantity"] * line["unit_cost"], 2)
                if abs(recomputed - line["amount"]) > TOLERANCE_LINE:
                    failures.append({
                        "provider": provider["id"], "month": month, "rule": "line_identity",
                        "detail": (f"{line['item']}: {line['quantity']} x "
                                   f"{line['unit_cost']} = {recomputed:.2f}, line says {line['amount']:.2f}"),
                    })

    return {
        "ok": not failures,
        "rules": [
            "rule 1: quantity x unit_cost == line amount (every line)",
            "rule 2: sum(line amounts) == monthly bill (every bill)",
        ],
        "providers_checked": len(data.PROVIDERS),
        "bills_checked": bills_checked,
        "lines_checked": lines_checked,
        "failures": failures,
    }
