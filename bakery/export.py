"""Step 4a: database -> docs/data/dashboard.json + docs/data/days/<date>.json (all the dashboard reads).

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
from .geo import DEPOT


def _rows(conn, table, *where):
    q = select(table)
    for w in where:
        q = q.where(w)
    return [dict(r) for r in conn.execute(q).mappings()]


def week_of(day):
    d = dt.date.fromisoformat(day)
    return (d - dt.timedelta(days=d.weekday())).isoformat()


def build():
    """Everything the page reads: (dashboard, {date: one morning}). dashboard.json holds the overall
    sections and the calendar; docs/data/days/<date>.json holds one morning each (decision S10)."""
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
        day_stops = {d: _rows(c, db.stops, db.stops.c.run_id == r["id"]) for d, r in planner_runs.items()}
        day_trays = {d: _rows(c, db.tray_loads, db.tray_loads.c.run_id == r["id"]) for d, r in planner_runs.items()}
    next_day = max(planner_runs)
    done = sorted(d for d, r in planner_runs.items() if r["status"] == "done")
    last = done[-1] if done else None

    name = lambda cid: customers.get(cid, {}).get("name", cid)  # noqa: E731
    hh = config.hhmm
    r1 = lambda v: None if v is None else round(v, 1)  # noqa: E731

    # ---- one morning's run sheet (a finished morning also carries what the log says happened) ----
    def run_sheet_for(day):
        nr, stops, trays = planner_runs[day], day_stops[day], day_trays[day]
        is_done = nr["status"] == "done"
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
            e = {"min": s["planned_deliver"], "time": hh(s["planned_deliver"]), "kind": "stop",
                 "seq": s["seq"], "text": f"Stop {s['seq']}: {name(s['customer_id'])}",
                 "detail": f"{s['pieces']} kolaches · wanted by {hh(s['wanted_by'])}",
                 "fresh": s["expected_fresh"] == s["pieces"], "oldest_tray_min": round(worst),
                 "late": s["planned_deliver"] > s["wanted_by"] + 0.5,
                 "revenue": round(s["expected_revenue"], 2)}
            if is_done:
                e["actual"] = {"planned_curb": hh(s["planned_curb"]), "curb": hh(s["actual_curb"]),
                               "gap_min": None if s["actual_curb"] is None else round(s["actual_curb"] - s["planned_curb"], 1),
                               "late": s["actual_deliver"] is not None and s["actual_deliver"] > s["wanted_by"] + 0.5,
                               "pieces": s["pieces"], "fresh": s["actual_fresh"], "refused": s["refused"] or 0,
                               "revenue": None if s["actual_revenue"] is None else round(s["actual_revenue"], 2)}
            events.append(e)
        events.append({"min": nr["back_at"], "time": hh(nr["back_at"]), "kind": "back", "text": "Back at the kitchen"})
        kind_order = {"load": 0, "leave": 1, "stop": 2, "back": 3}
        events.sort(key=lambda e: (e["min"], kind_order[e["kind"]]))

        day_orders = [o for o in orders if o["delivery_date"] == day]
        declined = [{"customer": o["customer"], "why": o["reason"],
                     "by": "planner" if o["status"] == "declined_planner" else "order check"}
                    for o in day_orders if o["status"] != "accepted"]
        day_flags = [{"customer": f["customer"], "text": f["text"], "rule": f["rule"]}
                     for f in flags if f["delivery_date"] == day and f["source"] in ("orders", "prices")]
        old = old_runs.get(day, {})
        return {
            "delivery_date": day, "status": nr["status"],
            "oven": nr["oven"], "oven_pieces": config.OVENS[nr["oven"]][0],
            "leave": hh(nr["leave_min"]), "first_load": hh(nr["shift_start"]), "back": hh(nr["back_at"]),
            "accepted": len(stops), "declined_count": len(declined), "pieces": nr["pieces"],
            "expected_profit": round(nr["expected_profit"], 2), "expected_fresh": round(nr["expected_fresh"], 3),
            "old_rule_profit": round(old.get("expected_profit", 0) or 0, 2),
            "costs": {"van": round(nr["van_cost"], 2), "oven": round(nr["oven_cost"], 2),
                      "ingredients": round(nr["ingredient_cost"], 2), "revenue": round(nr["expected_revenue"], 2)},
            "per_oven": json.loads(nr["per_oven_json"] or "{}"), "events": events, "declined": declined,
            "flags": day_flags,
            "optimizer_rounds": len([r for r in rounds if r["delivery_date"] == day and r["round"] > 0]),
            "bls_months": planner_runs[next_day]["bls_months"], "van_rate_per_hour": config.VAN_RATE_PER_HOUR,
        }

    # ---- route map: where the van is at each minute ----
    # Times are minutes after midnight. The van drives to the curb (arrive), may wait for the café to
    # open or a tray to finish (handoff), then spends STOP_MIN there (depart). Same rule as model.py.
    def route_stops(rows, curb_key, deliver_key):
        out = []
        for s in sorted(rows, key=lambda s: s["seq"]):
            c = customers.get(s["customer_id"], {})
            curb, deliver = s[curb_key], s[deliver_key]
            depart = None if deliver is None else deliver + config.STOP_MIN
            out.append({"seq": s["seq"], "customer": name(s["customer_id"]),
                        "lat": c.get("lat"), "lon": c.get("lon"), "pieces": s["pieces"],
                        "arrive_min": r1(curb), "handoff_min": r1(deliver), "depart_min": r1(depart),
                        "arrive": hh(curb), "handoff": hh(deliver), "depart": hh(depart),
                        "planned_arrive": hh(s["planned_curb"])})
        return out

    def morning_route(day):
        """A finished morning replays what the van's log recorded; a planned one shows the plan."""
        r = planner_runs[day]
        if r["status"] == "done":
            return {"delivery_date": day, "kind": "actual", "leave_min": r["leave_min"],
                    "back_min": r["actual_back_at"] or r["back_at"],
                    "stops": route_stops(day_stops[day], "actual_curb", "actual_deliver")}
        return {"delivery_date": day, "kind": "planned", "leave_min": r["leave_min"], "back_min": r["back_at"],
                "stops": route_stops(day_stops[day], "planned_curb", "planned_deliver")}

    depot = {"name": DEPOT["name"], "lat": DEPOT["lat"], "lon": DEPOT["lon"]}

    # ---- how a finished morning went ----
    def outcome_for(day):
        lr, stops = planner_runs[day], day_stops[day]
        if lr["status"] != "done":
            return None
        g = [abs(s["actual_curb"] - s["planned_curb"]) for s in stops if s["actual_curb"] is not None]
        o = old_runs.get(day)
        return {
            "delivery_date": day, "planned_profit": round(lr["expected_profit"], 2),
            "actual_profit": round(lr["actual_profit"], 2), "actual_fresh": round(lr["actual_fresh"], 3),
            "refused_pieces": lr["refused_pieces"], "worst_gap_min": round(max(g), 1) if g else None,
            "old_rule_actual_profit": round(o["actual_profit"], 2) if o and o["actual_profit"] is not None else None,
            "stops": [{"customer": name(s["customer_id"]), "planned": hh(s["planned_curb"]),
                       "actual": hh(s["actual_curb"]), "fresh": s["actual_fresh"], "pieces": s["pieces"],
                       "refused": s["refused"]} for s in sorted(stops, key=lambda s: s["seq"])],
        }

    days = {d: {"delivery_date": d, "is_next": d == next_day, "run_sheet": run_sheet_for(d),
                "route": {"depot": depot, "morning": morning_route(d)}, "outcome": outcome_for(d)}
            for d in sorted(planner_runs)}

    run_sheet = days[next_day]["run_sheet"]
    route = {"depot": depot, "next": morning_route(next_day), "last": morning_route(last) if last else None}
    last_morning = days[last]["outcome"] if last else None

    # ---- the calendar: one square per morning, shaded by actual profit (decision S10) ----
    calendar = {"first": min(days), "next": next_day, "last": last, "days": []}
    for d, v in days.items():
        o = v["outcome"]
        calendar["days"].append({"date": d, "status": v["run_sheet"]["status"],
                                 "planned_profit": v["run_sheet"]["expected_profit"],
                                 "actual_profit": o["actual_profit"] if o else None,
                                 "old_rule_actual_profit": o["old_rule_actual_profit"] if o else None,
                                 "actual_fresh": o["actual_fresh"] if o else None,
                                 "refused_pieces": o["refused_pieces"] if o else None})

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
            "drive_legs_learned": len(n_obs), "bls_months": planner_runs[next_day]["bls_months"],
            "disclaimer": ("Demo data. The bakery, customers and orders are invented by a seeded script; the demand "
                           "patterns are ones we built in. Road times come from OpenStreetMap and ingredient prices "
                           "from the U.S. Bureau of Labor Statistics. 'Old rule' results are simulated on the same mornings."),
        },
        "run_sheet": run_sheet, "route": route, "last_morning": last_morning, "weekly": weekly,
        "customers": customers_out, "measures": measures, "calendar": calendar,
    }, days


def main():
    data, days = build()
    config.SITE_DATA.mkdir(parents=True, exist_ok=True)
    out = config.SITE_DATA / "dashboard.json"
    out.write_text(json.dumps(data, indent=1), encoding="utf-8")
    day_dir = config.SITE_DATA / "days"
    day_dir.mkdir(exist_ok=True)
    for old in day_dir.glob("*.json"):  # a morning no longer in the database must not linger on the site
        if old.stem not in days:
            old.unlink()
    for d, v in days.items():
        (day_dir / f"{d}.json").write_text(json.dumps(v, separators=(",", ":")), encoding="utf-8")
    rs = data["run_sheet"]
    print(f"Exported {out} : run sheet {rs['delivery_date']} ({rs['status']}), "
          f"{len(data['weekly'])} weeks of trends, {len(data['customers'])} customers, "
          f"{len(days)} mornings in {day_dir.relative_to(config.ROOT).as_posix()}/")
