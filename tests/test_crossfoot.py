"""Tests for the bill crossfoot verifier (CHRONOS-style reconciliation)."""

from __future__ import annotations

from mcp_server import crossfoot


def test_every_bill_reconciles():
    result = crossfoot.bill_crossfoot()
    assert result["ok"] is True, result["failures"]
    assert result["bills_checked"] >= 40  # 9 providers x 6 months
    assert result["lines_checked"] > result["bills_checked"]


def test_line_identity_holds_for_every_line():
    for provider in crossfoot.data.PROVIDERS:
        for month in provider["monthly"]:
            for line in crossfoot.invoice_lines(provider, month):
                recomputed = round(line["quantity"] * line["unit_cost"], 2)
                assert abs(recomputed - line["amount"]) <= crossfoot.TOLERANCE_LINE


def test_bad_invoice_lines_are_detected(monkeypatch):
    """The verifier catches a bad invoice line (e.g. a provider bill whose
    line no longer matches its own arithmetic) - both rules fire."""
    provider = crossfoot.data.PROVIDERS[0]
    month = next(iter(provider["monthly"]))
    bad = [{"item": "EC2 on-demand", "quantity": 744, "unit_cost": 0.20, "amount": 999.99}]
    original_lines = crossfoot.invoice_lines
    monkeypatch.setattr(
        crossfoot, "invoice_lines",
        lambda p, m: bad if (p["id"] == provider["id"] and m == month)
        else original_lines(p, m))
    result = crossfoot.bill_crossfoot()
    assert result["ok"] is False
    rules = {f["rule"] for f in result["failures"]}
    assert "line_identity" in rules   # 744 x 0.20 != 999.99
    assert "invoice_total" in rules   # 999.99 != the monthly bill
