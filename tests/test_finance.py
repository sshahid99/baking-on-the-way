"""The business view (decisions F1, F2) must reconcile with the profit the planner and the log report."""
import json

from bakery import finance


def _run(status, **kw):
    base = {"status": status, "actual_profit": None, "expected_profit": 100.0, "ingredient_cost": 50.0}
    base.update(kw)
    return base


def test_pnl_reconciles_expected():
    stops = [{"customer_id": "A", "pieces": 24, "expected_revenue": 26.4, "actual_revenue": None, "refused": None,
              "ages_json": json.dumps([{"pieces": 12, "share": 1.0}, {"pieces": 12, "share": 0.0}])}]
    p = finance.run_pnl(_run("approved"), stops, {"A": 2.75})
    assert p["basis"] == "expected"
    assert p["list_sales"] == 66.0 and p["spoilage"] == 33.0 and p["refused_pieces"] == 12
    assert abs(p["list_sales"] - p["markdowns"] - p["spoilage"] - p["net_sales"]) < 1e-9
    assert abs(p["net_sales"] - p["cogs"] - p["run_cost"] - p["contribution"]) < 1e-9


def test_pnl_uses_actuals_when_done():
    stops = [{"customer_id": "A", "pieces": 24, "expected_revenue": 66.0, "actual_revenue": 52.8, "refused": 0,
              "ages_json": "[]"}]
    p = finance.run_pnl(_run("done", actual_profit=-10.0), stops, {"A": 2.75})
    assert p["basis"] == "actual" and p["net_sales"] == 52.8 and p["contribution"] == -10.0
    assert abs(p["markdowns"] - 13.2) < 1e-9
    r = finance.ratios(p)
    assert r["contribution_margin"] < 0 and abs(r["price_realisation"] - 0.8) < 1e-9
