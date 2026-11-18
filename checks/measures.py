"""The three success measures from the proposal (section 6), computed from the database.

    python checks/measures.py            -> prints a table, writes output/measures.json

1. Profit per morning vs Rosa's rule of thumb (target: at least +15%), ACTUAL (simulated) results.
2. Freshness: share of kolaches delivered < 15 min out of the oven (target: at least 85%).
3. Accuracy: worst planned-vs-actual arrival gap per morning, median over mornings
   (target: <= 5 min after recalibration). Decision 2026-11-18: the plain median gap per stop is
   reported too, but it was already low before learning, so it cannot show the learning.
   "Before" = first 10 mornings (little or no history), "after" = last 20 mornings.
"""
import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sqlalchemy import select  # noqa: E402

from bakery import db  # noqa: E402


def compute():
    with db.engine().connect() as c:
        runs = [dict(r) for r in c.execute(select(db.runs).where(db.runs.c.status == "done")).mappings()]
        gaps = [dict(r) for r in c.execute(select(db.arrival_gaps)).mappings()]
    plan = {r["delivery_date"]: r for r in runs if r["planner"] == "planner"}
    old = {r["delivery_date"]: r for r in runs if r["planner"] == "old_rule"}
    days = sorted(set(plan) & set(old))
    if not days:
        raise SystemExit("No completed mornings in the database yet.")
    p_profit = [plan[d]["actual_profit"] for d in days]
    o_profit = [old[d]["actual_profit"] for d in days]
    p_fresh = sum(plan[d]["actual_fresh"] * plan[d]["pieces"] for d in days) / sum(plan[d]["pieces"] for d in days)
    o_fresh = sum(old[d]["actual_fresh"] * old[d]["pieces"] for d in days) / sum(old[d]["pieces"] for d in days)

    by_day = {}
    for g in gaps:
        if g["actual"] is not None and g["planned"] is not None and g["customer_id"] != "DEPOT":
            by_day.setdefault(g["run_date"], []).append(abs(g["actual"] - g["planned"]))
    gdays = sorted(d for d in by_day if d in plan)
    before, after = gdays[:10], gdays[-20:]

    def worst(ds):
        return st.median(max(by_day[d]) for d in ds) if ds else None

    def med(ds):
        return st.median(x for d in ds for x in by_day[d]) if ds else None

    uplift = sum(p_profit) / sum(o_profit) - 1 if sum(o_profit) > 0 else None
    m = {
        "mornings": len(days), "first_day": days[0], "last_day": days[-1],
        "profit_per_morning_planner": round(st.mean(p_profit), 2),
        "profit_per_morning_old_rule": round(st.mean(o_profit), 2),
        "profit_uplift": round(uplift, 4) if uplift is not None else None,
        "mornings_planner_won": sum(1 for a, b in zip(p_profit, o_profit) if a > b),
        "fresh_share_planner": round(p_fresh, 4), "fresh_share_old_rule": round(o_fresh, 4),
        "worst_gap_before": worst(before), "worst_gap_after": worst(after),
        "median_gap_before": med(before), "median_gap_after": med(after),
        "planned_vs_actual_profit": round(sum(plan[d]["expected_profit"] for d in days) - sum(p_profit), 2),
        "overpromise_per_morning_before": round(st.mean(plan[d]["expected_profit"] - plan[d]["actual_profit"] for d in days[:10]), 2),
        "overpromise_per_morning_after": round(st.mean(plan[d]["expected_profit"] - plan[d]["actual_profit"] for d in days[-20:]), 2),
        "refused_pieces_before": sum(plan[d]["refused_pieces"] for d in days[:10]),
        "refused_pieces_after": sum(plan[d]["refused_pieces"] for d in days[-20:]),
        "profit_gain_per_morning": round(st.mean(p_profit) - st.mean(o_profit), 2),
    }
    m["targets"] = {
        "profit_uplift_at_least_15pct": uplift is not None and uplift >= 0.15,
        "fresh_at_least_85pct": p_fresh >= 0.85,
        "worst_gap_after_at_most_5min": m["worst_gap_after"] is not None and m["worst_gap_after"] <= 5,
    }
    return m


def main():
    m = compute()
    out = ROOT / "output" / "measures.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(m, indent=1))
    print(f"{m['mornings']} mornings {m['first_day']}..{m['last_day']}")
    print(f"1 profit/morning: +${m['profit_gain_per_morning']:.0f}; planner ${m['profit_per_morning_planner']:.0f} vs old rule "
          f"${m['profit_per_morning_old_rule']:.0f} -> {m['profit_uplift']:+.0%} "
          f"(planner better on {m['mornings_planner_won']}/{m['mornings']})  target >= +15%: {m['targets']['profit_uplift_at_least_15pct']}")
    print(f"2 fresh (<15 min): planner {m['fresh_share_planner']:.0%} vs old rule {m['fresh_share_old_rule']:.0%}"
          f"  target >= 85%: {m['targets']['fresh_at_least_85pct']}")
    print(f"3 worst-stop gap: first 10 mornings {m['worst_gap_before']:.1f} min -> last 20 {m['worst_gap_after']:.1f} min"
          f"  (median stop gap {m['median_gap_before']:.1f} -> {m['median_gap_after']:.1f})  target <= 5: "
          f"{m['targets']['worst_gap_after_at_most_5min']}")
    print(f"  learning: plan over-promised ${m['overpromise_per_morning_before']:.0f}/morning (first 10) -> "
          f"${m['overpromise_per_morning_after']:.0f} (last 20); pieces refused {m['refused_pieces_before']} -> {m['refused_pieces_after']}")


if __name__ == "__main__":
    main()
