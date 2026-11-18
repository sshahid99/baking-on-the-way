"""Step 4a: database -> docs/data/dashboard.json (the only file the dashboard reads).

GitHub Pages is static, so the page cannot query the database; this export is the bridge.
Nothing secret goes in the JSON: no DATABASE_URL, no host names, only business figures.
"""
import datetime as dt
import json
import statistics as st
import sys
from collections import defaultdict

from sqlalchemy import select

from . import config, db


def _rows(conn, table, *where):
    q = select(table)
    for w in where:
        q = q.where(w)
    return [dict(r) for r in conn.execute(q).mappings()]


def week_of(day):
    d = dt.date.fromisoformat(day)
    return (d - dt.timedelta(days=d.weekday())).isoformat()


def build():
    with db.engine().connect() as c:
        runs = _rows(c, db.runs)
        customers = {r["customer_id"]: r for r in _rows(c, db.customers)}
        orders = _rows(c, db.orders)
        flags = _rows(c, db.flags)
        gaps = _rows(c, db.arrival_gaps)
        rounds = _rows(c, db.optimizer_rounds)
        n_obs = c.execute(select(db.drive_observations.c.id)).all()
        planner_runs = {r["delivery_date"]: r for r in runs if r["planner"] == "planner"}
        old_runs = {r["delivery_date"]: r for r in runs if r["planner"] == "old_rule"}
        if not planner_runs:
            sys.exit("STOPPED: nothing in the database to export. Run the workflow first.")
        next_day = max(planner_runs)
        nr = planner_runs[next_day]
        stops = _rows(c, db.stops, db.stops.c.run_id == nr["id"])
        trays = _rows(c, db.tray_loads, db.tray_loads.c.run_id == nr["id"])
        done = sorted(d for d, r in planner_runs.items() if r["status"] == "done")
        last = done[-1] if done else None
        last_stops = _rows(c, db.stops, db.stops.c.run_id == planner_runs[last]["id"]) if last else []

    name = lambda cid: customers.get(cid, {}).get("name", cid)  # noqa: E731
    hh = config.hhmm

    # ---- tomorrow's run sheet ----
    events, grouped = [], defaultdict(lambda: [0, 0])
    for t in trays:
        cid, q = next(iter(json.loads(t["pieces_json"]).items()))
        g = grouped[(t["load_min"], cid)]
        g[0] += 1
        g[1] += q
    for (m, cid), (n, q) in sorted(grouped.items()):
        events.append({"min": m, "time": hh(m), "kind": "load",
                       "text": f"Load {n} tray{'s' if n > 1 else ''} ({q}) for {name(cid)}",
                       "out": hh(m + config.BAKE_MIN)})
    events.append({"min": nr["leave_min"], "time": hh(nr["leave_min"]), "kind": "leave", "text": "Leave the kitchen"})
    for s in sorted(stops, key=lambda s: s["seq"]):
        ages = json.loads(s["ages_json"])
        worst = max(a["age"] for a in ages) if ages else 0
        events.append({"min": s["planned_deliver"], "time": hh(s["planned_deliver"]), "kind": "stop",
                       "seq": s["seq"], "text": f"Stop {s['seq']}: {name(s['customer_id'])}",
                       "detail": f"{s['pieces']} kolaches · wanted by {hh(s['wanted_by'])}",
                       "fresh": s["expected_fresh"] == s["pieces"], "oldest_tray_min": round(worst),
                       "late": s["planned_deliver"] > s["wanted_by"] + 0.5,
                       "revenue": round(s["expected_revenue"], 2)})
    events.append({"min": nr["back_at"], "time": hh(nr["back_at"]), "kind": "back", "text": "Back at the kitchen"})
    kind_order = {"load": 0, "leave": 1, "stop": 2, "back": 3}
    events.sort(key=lambda e: (e["min"], kind_order[e["kind"]]))

    day_orders = [o for o in orders if o["delivery_date"] == next_day]
    declined = [{"customer": o["customer"], "why": o["reason"],
                 "by": "planner" if o["status"] == "declined_planner" else "order check"}
                for o in day_orders if o["status"] != "accepted"]
    day_flags = [{"customer": f["customer"], "text": f["text"], "rule": f["rule"]}
                 for f in flags if f["delivery_date"] == next_day and f["source"] in ("orders", "prices")]
    old = old_runs.get(next_day, {})
    per_oven = json.loads(nr["per_oven_json"] or "{}")
    day_rounds = [r for r in rounds if r["delivery_date"] == next_day]

    run_sheet = {
        "delivery_date": next_day, "status": nr["status"],
        "oven": nr["oven"], "oven_pieces": config.OVENS[nr["oven"]][0],
        "leave": hh(nr["leave_min"]), "first_load": hh(nr["shift_start"]), "back": hh(nr["back_at"]),
        "accepted": len(stops), "declined_count": len(declined), "pieces": nr["pieces"],
        "expected_profit": round(nr["expected_profit"], 2), "expected_fresh": round(nr["expected_fresh"], 3),
        "old_rule_profit": round(old.get("expected_profit", 0) or 0, 2),
        "costs": {"van": round(nr["van_cost"], 2), "oven": round(nr["oven_cost"], 2),
                  "ingredients": round(nr["ingredient_cost"], 2), "revenue": round(nr["expected_revenue"], 2)},
        "per_oven": per_oven, "events": events, "declined": declined, "flags": day_flags,
        "optimizer_rounds": len([r for r in day_rounds if r["round"] > 0]),
        "bls_months": nr["bls_months"],
    }

    # ---- last completed morning ----
    last_morning = None
    if last:
        lr = planner_runs[last]
        g = [abs(s["actual_curb"] - s["planned_curb"]) for s in last_stops if s["actual_curb"] is not None]
        last_morning = {
            "delivery_date": last, "planned_profit": round(lr["expected_profit"], 2),
            "actual_profit": round(lr["actual_profit"], 2), "actual_fresh": round(lr["actual_fresh"], 3),
            "refused_pieces": lr["refused_pieces"], "worst_gap_min": round(max(g), 1) if g else None,
            "old_rule_actual_profit": round(old_runs[last]["actual_profit"], 2) if last in old_runs and old_runs[last]["actual_profit"] is not None else None,
            "stops": [{"customer": name(s["customer_id"]), "planned": hh(s["planned_curb"]),
                       "actual": hh(s["actual_curb"]), "fresh": s["actual_fresh"], "pieces": s["pieces"],
                       "refused": s["refused"]} for s in sorted(last_stops, key=lambda s: s["seq"])],
        }

    # ---- weekly trends (completed mornings only) ----
    gap_by_day = defaultdict(list)
    for gp in gaps:
        if gp["actual"] is not None and gp["planned"] is not None and gp["customer_id"] != "DEPOT":
            gap_by_day[gp["run_date"]].append(abs(gp["actual"] - gp["planned"]))
    weeks = defaultdict(list)
    for d in done:
        if d in old_runs and old_runs[d]["actual_profit"] is not None:
            weeks[week_of(d)].append(d)
    weekly = []
    for w in sorted(weeks):
        ds = weeks[w]
        pp = sum(planner_runs[d]["pieces"] for d in ds)
        op = sum(old_runs[d]["pieces"] for d in ds)
        weekly.append({
            "week": w, "mornings": len(ds),
            "planner_profit": round(st.mean(planner_runs[d]["actual_profit"] for d in ds), 2),
            "old_rule_profit": round(st.mean(old_runs[d]["actual_profit"] for d in ds), 2),
            "planner_fresh": round(sum(planner_runs[d]["actual_fresh"] * planner_runs[d]["pieces"] for d in ds) / pp, 3),
            "old_rule_fresh": round(sum(old_runs[d]["actual_fresh"] * old_runs[d]["pieces"] for d in ds) / op, 3),
            "worst_gap": round(st.median(max(gap_by_day[d]) for d in ds if gap_by_day[d]), 1) if any(gap_by_day[d] for d in ds) else None,
            "overpromise": round(st.mean(planner_runs[d]["expected_profit"] - planner_runs[d]["actual_profit"] for d in ds), 2),
        })

    # ---- customers to talk to ----
    cust = defaultdict(lambda: {"orders": 0, "declined": 0, "pieces": 0, "revenue_full": 0.0})
    for o in orders:
        if o["status"] in ("accepted", "declined_planner") and o["delivery_date"] in done:
            k = cust[o["customer_id"]]
            k["orders"] += 1
            k["pieces"] += o["pieces"] or 0
            k["revenue_full"] += o["revenue_full"] or 0
            if o["status"] == "declined_planner":
                k["declined"] += 1
    customers_out = []
    for cid, k in cust.items():
        cinfo = customers.get(cid, {})
        price = cinfo.get("contract_price", config.BASE_PRICE)
        advice = []
        if k["orders"] and k["declined"] / k["orders"] >= 0.25:
            advice.append("Often doesn't fit the route: ask for a later wanted-by time")
        if price < config.BASE_PRICE:
            advice.append(f"Pays ${price:.2f}, below the ${config.BASE_PRICE:.2f} base price")
        customers_out.append({"customer": cinfo.get("name", cid), "type": cinfo.get("type", ""),
                              "orders": k["orders"], "declined": k["declined"],
                              "avg_pieces": round(k["pieces"] / k["orders"]) if k["orders"] else 0,
                              "price": price, "opens": config.hhmm(cinfo.get("opens_at")), "advice": advice})
    customers_out.sort(key=lambda r: (-len(r["advice"]), -r["declined"], r["customer"]))

    try:
        sys.path.insert(0, str(config.ROOT))
        from checks.measures import compute
        measures = compute()
    except SystemExit:
        measures = None

    return {
        "meta": {
            "generated_at": db.now(), "database": "cloud MySQL" if db.engine().dialect.name == "mysql" else "SQLite",
            "orders_through": next_day, "mornings_completed": len(done),
            "drive_legs_learned": len(n_obs), "bls_months": nr["bls_months"],
            "disclaimer": ("Demo data. The bakery, customers and orders are invented by a seeded script; the demand "
                           "patterns are ones we built in. Road times come from OpenStreetMap and ingredient prices "
                           "from the U.S. Bureau of Labor Statistics. 'Old rule' results are simulated on the same mornings."),
        },
        "run_sheet": run_sheet, "last_morning": last_morning, "weekly": weekly,
        "customers": customers_out, "measures": measures,
    }


def main():
    data = build()
    config.SITE_DATA.mkdir(parents=True, exist_ok=True)
    out = config.SITE_DATA / "dashboard.json"
    out.write_text(json.dumps(data, indent=1), encoding="utf-8")
    rs = data["run_sheet"]
    print(f"Exported {out} : run sheet {rs['delivery_date']} ({rs['status']}), "
          f"{len(data['weekly'])} weeks of trends, {len(data['customers'])} customers")
