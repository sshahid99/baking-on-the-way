"""The three success measures from the proposal (section 6), computed from the database.

    python checks/measures.py            -> prints a table, writes output/measures.json

1. Profit per morning vs Rosa's rule of thumb (target: at least +15%), ACTUAL (simulated) results.
2. Freshness: share of kolaches delivered < 15 min out of the oven (target: at least 85%).
3. Accuracy: worst planned-vs-actual arrival gap per morning, median over mornings
   (target: <= 5 min after recalibration). Decision 2026-11-18: the plain median gap per stop is
   reported too, but it was already low before learning, so it cannot show the learning.
   "Before" = first 10 mornings (little or no history), "after" = last 20 mornings.
3b. Planning time (decision G4, 2026-11-19): minutes from `clean` starting to Rosa's `approve`, live
   /plan-run mornings only (target: under 5 min; "about 45 by hand" is our proposal estimate, not measured).
   Runs before G4 have no timestamps: they are reconstructed from the trace's "plan written" time to the
   "Run sheet <date>" commit, and labelled so. Nov 9 is left out: it was re-planned after a fix (errors #8).
4. Business view (decisions F1-F3, 2026-11-19): a per-morning profit-and-loss statement for both ways
   (list-price sales, freshness markdowns, spoilage, cost of goods, gross margin, run cost, contribution
   margin, per-kolache figures, break-even) and a yearly projection at config.MORNINGS_PER_YEAR.
"""
import json
import re
import statistics as st
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sqlalchemy import select  # noqa: E402

from bakery import config, db, finance  # noqa: E402


PLANNING_TARGET_MIN = 5          # proposal section 6, measure 3
BY_HAND_ESTIMATE_MIN = 45        # proposal estimate, never measured (G4)
NOT_RECONSTRUCTED = {"2026-11-09": "re-planned after a wording fix, so its plan time is the second try (errors #8)"}


def _minutes(a, b):
    return round((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 60, 1)


def _commit_time(day):
    try:
        out = subprocess.run(["git", "log", "--format=%cI", f"--grep=^Run sheet {day}$"], cwd=ROOT,
                             capture_output=True, text=True, timeout=20).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return None
    return out[-1] if out else None  # oldest matching commit


def planning_times(runs):
    """One row per live /plan-run morning: measured (G4 timestamps) or reconstructed (trace + git)."""
    rows = {}
    for r in runs:
        if r["planner"] == "planner" and r.get("cleaned_at") and r.get("approved_at"):
            rows[r["delivery_date"]] = {"day": r["delivery_date"], "minutes": _minutes(r["cleaned_at"], r["approved_at"]),
                                        "how": "measured: cleaning started -> Rosa approved"}
    for t in sorted((ROOT / "work" / "runs").glob("*-trace.md")):
        day = t.name[:10]
        text = t.read_text(encoding="utf-8")
        if day in rows or "plan-reviewer" not in text:
            continue
        if day in NOT_RECONSTRUCTED:
            rows[day] = {"day": day, "minutes": None, "how": "left out: " + NOT_RECONSTRUCTED[day]}
            continue
        m = re.search(r"Written by `python -m bakery plan` at (\S+?)\.", text)
        end = _commit_time(day)
        if m and end:
            rows[day] = {"day": day, "minutes": _minutes(m.group(1), end),
                         "how": "reconstructed from git: plan written -> 'Run sheet' commit"}
    return [rows[d] for d in sorted(rows)]


def compute():
    with db.engine().connect() as c:
        all_runs = [dict(r) for r in c.execute(select(db.runs)).mappings()]
        runs = [r for r in all_runs if r["status"] == "done"]
        gaps = [dict(r) for r in c.execute(select(db.arrival_gaps)).mappings()]
        all_stops = [dict(r) for r in c.execute(select(db.stops)).mappings()]
        price = {r["customer_id"]: r["contract_price"] for r in c.execute(select(db.customers)).mappings()}
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
    m["business"] = business(plan, old, days, all_stops, price)
    pt = planning_times(all_runs)
    mins = [r["minutes"] for r in pt if r["minutes"] is not None]
    m["planning_time"] = {
        "runs": pt, "counted": len(mins), "measured": sum(1 for r in pt if r["how"].startswith("measured")),
        "median_min": st.median(mins) if mins else None, "slowest_min": max(mins) if mins else None,
        "target_min": PLANNING_TARGET_MIN, "by_hand_estimate_min": BY_HAND_ESTIMATE_MIN,
    }
    m["targets"] = {
        "profit_uplift_at_least_15pct": uplift is not None and uplift >= 0.15,
        "fresh_at_least_85pct": p_fresh >= 0.85,
        "worst_gap_after_at_most_5min": m["worst_gap_after"] is not None and m["worst_gap_after"] <= 5,
        "planning_under_5min": bool(mins) and max(mins) < PLANNING_TARGET_MIN,  # every counted run, not the median
    }
    return m


def business(plan, old, days, all_stops, price):
    """Per-morning P&L for both ways over the same mornings, plus margins and a yearly projection (F1-F3)."""
    by_run = {}
    for s in all_stops:
        by_run.setdefault(s["run_id"], []).append(s)
    out = {}
    for key, runs in (("planner", plan), ("old_rule", old)):
        pnls = [finance.run_pnl(runs[d], by_run.get(runs[d]["id"], []), price) for d in days]
        avg = finance.per_morning(pnls)
        r = finance.ratios(finance.add(pnls))
        r["break_even_kolaches"] = finance.ratios(avg)["break_even_kolaches"]
        out[key] = {"per_morning": {k: round(v, 2) for k, v in avg.items()},
                    "ratios": {k: None if v is None else round(v, 4) for k, v in r.items()},
                    "losing_mornings": sum(1 for p in pnls if p["contribution"] < 0),
                    "worst_morning": round(min(p["contribution"] for p in pnls), 2),
                    "best_morning": round(max(p["contribution"] for p in pnls), 2),
                    "oven_mix": {o: sum(1 for d in days if runs[d]["oven"] == o) for o in config.OVENS}}
    gain = out["planner"]["per_morning"]["contribution"] - out["old_rule"]["per_morning"]["contribution"]
    n = config.MORNINGS_PER_YEAR
    out["per_year"] = {"mornings": n,
                       "planner_contribution": round(out["planner"]["per_morning"]["contribution"] * n),
                       "old_rule_contribution": round(out["old_rule"]["per_morning"]["contribution"] * n),
                       "gain": round(gain * n),
                       "net_sales_gain": round((out["planner"]["per_morning"]["net_sales"] - out["old_rule"]["per_morning"]["net_sales"]) * n),
                       "leakage_saved": round(((out["old_rule"]["per_morning"]["markdowns"] + out["old_rule"]["per_morning"]["spoilage"])
                                               - (out["planner"]["per_morning"]["markdowns"] + out["planner"]["per_morning"]["spoilage"])) * n)}
    return out


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
    p = m["planning_time"]
    if p["counted"]:
        print(f"3b planning time, order sheet to approval: median {p['median_min']:.1f} min, slowest {p['slowest_min']:.1f} min "
              f"over {p['counted']} live runs ({p['measured']} measured, the rest reconstructed)  target < {p['target_min']}: "
              f"{m['targets']['planning_under_5min']}  (by hand: ~{p['by_hand_estimate_min']} min, our estimate, not measured)")
    for r in p["runs"]:
        print(f"   {r['day']}: {'-' if r['minutes'] is None else str(r['minutes']) + ' min'}  ({r['how']})")


if __name__ == "__main__":
    main()
