"""Business view of one morning: a small profit-and-loss statement (decisions F1-F3).

Pure accounting on numbers already in the database; it changes nothing the planner decides.
Used by checks/measures.py (report + "The business" tab) and bakery/export.py (one morning).

Terms (decisions F1):
  list-price sales   every delivered kolache at the café's contract price
  freshness markdowns what the freshness / lateness contract took off (M4, M5)
  spoilage           kolaches refused (> 45 min old or > 15 min late) and given to the pantry
  net sales          what the cafés actually paid
  cost of goods      ingredients (BLS prices + $0.35 other, M8)
  gross profit       net sales - cost of goods
  run cost           van + oven rental, both billed by the hour (M1, M2)
  contribution       net sales - cost of goods - run cost  (= "profit" everywhere else in the project).
                     Kitchen rent, insurance and Rosa's own pay are not modelled, so this is what is
                     left to cover them, not the bakery's bottom line.
"""
import json


def run_pnl(run, stops, unit_price):
    """run: a runs row; stops: its stops rows; unit_price: {customer_id: contract $/piece}.
    A finished morning ("done") uses what the van's log recorded; otherwise the plan's expectation."""
    done = run["status"] == "done" and run["actual_profit"] is not None
    pieces = sum(s["pieces"] for s in stops)
    list_sales = sum(s["pieces"] * unit_price.get(s["customer_id"], 0.0) for s in stops)
    if done:
        net_sales = sum(s["actual_revenue"] or 0.0 for s in stops)
        refused = sum(s["refused"] or 0 for s in stops)
        spoilage = sum((s["refused"] or 0) * unit_price.get(s["customer_id"], 0.0) for s in stops)
        profit = run["actual_profit"]
    else:
        net_sales = sum(s["expected_revenue"] or 0.0 for s in stops)
        refused, spoilage = 0, 0.0
        for s in stops:
            for a in json.loads(s["ages_json"] or "[]"):
                if a["share"] == 0:
                    refused += a["pieces"]
                    spoilage += a["pieces"] * unit_price.get(s["customer_id"], 0.0)
        profit = run["expected_profit"]
    cogs = run["ingredient_cost"] or 0.0
    run_cost = net_sales - cogs - profit  # van + oven for the hours actually driven
    return {
        "basis": "actual" if done else "expected", "pieces": pieces, "refused_pieces": refused,
        "list_sales": list_sales, "markdowns": max(0.0, list_sales - net_sales - spoilage), "spoilage": spoilage,
        "net_sales": net_sales, "cogs": cogs, "gross_profit": net_sales - cogs, "run_cost": run_cost,
        "contribution": profit,
    }


def ratios(p):
    """Margins and per-kolache figures from a run_pnl (or a sum of them)."""
    ns, n = p["net_sales"], p["pieces"]
    unit_contrib = (ns - p["cogs"]) / n if n else 0.0  # what one more kolache adds before van + oven
    return {
        "gross_margin": (ns - p["cogs"]) / ns if ns else None,
        "contribution_margin": p["contribution"] / ns if ns else None,
        "price_realisation": ns / p["list_sales"] if p["list_sales"] else None,  # share of list price collected
        "spoilage_rate": p["refused_pieces"] / n if n else None,
        "sales_per_kolache": ns / n if n else None,
        "cost_per_kolache": (p["cogs"] + p["run_cost"]) / n if n else None,
        "contribution_per_kolache": p["contribution"] / n if n else None,
        "break_even_kolaches": p["run_cost"] / unit_contrib if unit_contrib > 0 else None,
    }


def add(pnls):
    keys = ("pieces", "refused_pieces", "list_sales", "markdowns", "spoilage", "net_sales", "cogs",
            "gross_profit", "run_cost", "contribution")
    return {k: sum(p[k] for p in pnls) for k in keys}


def per_morning(pnls):
    n = len(pnls)
    total = add(pnls)
    return {k: v / n for k, v in total.items()} if n else total
