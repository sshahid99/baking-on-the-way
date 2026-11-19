"""Workflow steps. Each one is a CLI command (see __main__.py) so /plan-run and a human
can run the same thing.
"""
import csv
import datetime as dt
import json
import statistics
import sys
from pathlib import Path

from . import calibrate, clean, config, db, geo, logs, prices, simulate
from .model import execute
from .optimize import _evaluate, baseline_plan, optimize


def _orders_by_customer(clean_result):
    return {o["customer_id"]: o for o in clean_result["orders"]}


def _load_clean(day):
    path = config.CLEAN_DIR / f"{day}.json"
    if not path.exists():
        sys.exit(f"STOPPED: no cleaned orders for {day}. Run: python -m bakery clean <order-file>")
    return json.loads(path.read_text(encoding="utf-8"))


def _why_declined(plan, res, cid, orders, drive, price):
    best = None
    for j in range(len(plan["route"]) + 1):
        p = {"oven": plan["oven"], "leave": plan["leave"], "route": list(plan["route"]), "declined": []}
        p["route"].insert(j, cid)
        r = _evaluate(p, orders, drive, price)
        if best is None or r["profit"] > best[1]["profit"]:
            best = (j, r)
    j, r = best
    stop = next(s for s in r["stops"] if s["customer_id"] == cid)
    loss = res["profit"] - r["profit"]
    o = orders[cid]
    if stop["late_min"] > config.LATE_GRACE_MIN:
        why = (f"can't reach it by {config.hhmm(o['wanted_by'])} + 15 min without making other stops late "
               f"(best case {config.hhmm(stop['deliver'])})")
    else:
        why = "fitting it in makes other stops later or staler"
    return f"Taking it would lower profit by ${loss:,.0f}: {why}."


def plan_day(day, verbose=True):
    # Guard G-run1 (2026-11-18): re-planning replaces the stored run, so it would erase what
    # actually happened that morning. Found when a second session drove Nov 9 mid-run.
    if db.run_status(day) == "done":
        sys.exit(f"STOPPED: the morning of {day} has already been driven; re-planning would erase "
                 f"its actual results. Plan the next delivery date instead.")
    clean_result = _load_clean(day)
    orders = _orders_by_customer(clean_result)
    matrix, source = geo.load_matrix()
    missing = [c for c in orders if ("DEPOT", c) not in matrix]
    if missing:
        sys.exit(f"STOPPED: no road times for {missing}. Rebuild the matrix: python -m bakery roads")
    obs = db.observations_before(day)
    drive = calibrate.DriveModel(obs, (matrix, source))
    price_table, price_file = prices.load_all()
    price, months, price_flags = prices.prices_for(dt.date.fromisoformat(day), price_table)
    clean_result["price_flags"] = price_flags

    plan, res, per_oven, rounds = optimize(orders, drive, price)
    declined = {c: _why_declined(plan, res, c, orders, drive, price) for c in plan["declined"]}

    old = baseline_plan(orders, drive)
    old_expected = execute(old, orders, drive, price, loads=old["loads"])  # same drive estimate, fair comparison

    wanted = {c: o["wanted_by"] for c, o in orders.items()}
    extra = dict(rounds=sum(1 for r in rounds if r["round"] > 0), per_oven=per_oven,
                 bls_months=", ".join(sorted(set(months.values()))),
                 drive_source=f"{source}; learned from {drive.n_obs} legs", wanted=wanted)
    db.save_run(day, "planner", plan, res, extra)
    db.save_run(day, "old_rule", old, old_expected, dict(extra, rounds=0, per_oven={}))
    db.save_orders_and_flags(clean_result, declined, rounds)

    out_dir = config.PLAN_DIR / day
    out_dir.mkdir(parents=True, exist_ok=True)
    legs, pos, t = [], "DEPOT", plan["leave"]
    for s in res["stops"]:
        legs.append({"from": pos, "to": s["customer_id"], "depart": round(s["depart_prev"], 2),
                     "minutes": round(s["drive_min"], 3)})
        pos = s["customer_id"]
    last = res["stops"][-1] if res["stops"] else None
    if last:
        t = last["deliver"] + config.STOP_MIN
        legs.append({"from": pos, "to": "DEPOT", "depart": round(t, 2), "minutes": round(drive(pos, "DEPOT", t), 3)})
    plan_doc = {
        "delivery_date": day, "oven": plan["oven"], "leave": plan["leave"], "route": plan["route"],
        "trays": res["trays"], "legs": legs, "declined_by_planner": declined,
        "orders": clean_result["orders"], "ingredient_prices": price, "bls_months": months,
        "claimed": {k: round(res[k], 2) for k in ("profit", "revenue", "van_cost", "oven_cost",
                                                  "ingredient_cost", "fresh_share", "back_at", "shift_start")},
        "old_rule_claimed_profit": round(old_expected["profit"], 2), "per_oven_profit": per_oven,
        "old_rule_plan": {"oven": old["oven"], "leave": old["leave"], "route": old["route"],
                          "loads": old["loads"], "declined": old["declined"]},
        "rounds": rounds,
    }
    (out_dir / "plan.json").write_text(json.dumps(plan_doc, indent=1), encoding="utf-8")
    with open(out_dir / "rounds.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["oven", "round", "move", "gain", "profit", "stop"])
        w.writeheader()
        w.writerows(rounds)
    write_trace(day, clean_result, plan, res, per_oven, rounds, drive, declined)
    if verbose:
        print_run_sheet(day, plan, res, orders, declined, per_oven, old_expected, drive)
        print(f"-> {out_dir / 'plan.json'}  (stored in {db.where()})")
    return plan_doc


def write_trace(day, clean_result, plan, res, per_oven, rounds, drive, declined):
    """work/runs/<day>-trace.md: the steps so far and every optimizer round (committed with the run)."""
    config.RUNS_DIR.mkdir(parents=True, exist_ok=True)
    lines = [f"# Trace: /plan-run for {day}", "",
             f"Written by `python -m bakery plan` at {db.now()}. The reviewer and approval steps are appended below by the workflow.", "",
             "## Step 1 - clean and check (python -m bakery clean)",
             f"- {clean_result['source_file']}: {clean_result['raw_rows']} rows -> {len(clean_result['orders'])} orders to plan, "
             f"{len(clean_result['declined_at_cleaning'])} declined at cleaning, {len(clean_result['flags'])} flags",
             *[f"  - declined [{d['rule']}] {d['customer']}: {d['reason']}" for d in clean_result["declined_at_cleaning"]],
             *[f"  - flag [{f['rule']}] {f['customer']}: {f['text']}" for f in clean_result["flags"]], "",
             "## Step 2 - plan (optimizer loop)",
             f"- drive times: {drive.matrix_source}; learned from {drive.n_obs} observed legs before {day}",
             f"- stop rule: a round adds < ${config.MIN_ROUND_GAIN:.0f} or {config.MAX_ROUNDS} rounds; one loop per oven size", ""]
    for oven in config.OVENS:
        rs = [r for r in rounds if r["oven"] == oven]
        lines.append(f"### {oven} oven: {len([r for r in rs if r['round'] > 0])} rounds, final ${per_oven[oven]:,.2f}")
        lines.append("| round | best move | gain | profit | stop |")
        lines.append("|---|---|---|---|---|")
        lines += [f"| {r['round']} | {r['move']} | {r['gain']:+.2f} | {r['profit']:.2f} | {r.get('stop', '')} |" for r in rs]
        lines.append("")
    lines += [f"**Chosen:** {plan['oven']} oven, leave {config.hhmm(plan['leave'])}, {len(plan['route'])} stops, "
              f"declined {len(declined)}, expected profit ${res['profit']:,.2f}, {res['fresh_share']:.0%} fresh.", ""]
    (config.RUNS_DIR / f"{day}-trace.md").write_text("\n".join(lines), encoding="utf-8")


def print_run_sheet(day, plan, res, orders, declined, per_oven, old, drive):
    print(f"\nRUN SHEET {day}: rent the {plan['oven'].upper()} oven, leave {config.hhmm(plan['leave'])}, "
          f"decline {len(declined)}, expected profit ${res['profit']:,.0f} "
          f"(old rule ${old['profit']:,.0f}); {res['fresh_share']:.0%} fresh")
    print("  oven options: " + ", ".join(f"{k} ${v:,.0f}" for k, v in per_oven.items()))
    events = [(t, f"LOAD {n} tray{'s' if n > 1 else ''} ({q} pcs) for {orders[c]['customer']}")
              for (t, c), (n, q) in group_loads(res["trays"]).items()]
    events.append((plan["leave"], "LEAVE kitchen"))
    for i, s in enumerate(res["stops"], 1):
        o = orders[s["customer_id"]]
        events.append((s["deliver"], f"STOP {i}: {o['customer']} - {s['pieces']} pcs (wanted by {config.hhmm(o['wanted_by'])})"))
    events.append((res["back_at"], "BACK at kitchen"))
    for t, e in sorted(events, key=lambda x: x[0]):
        print(f"  {config.hhmm(t):>5}  {e}")
    for c, why in declined.items():
        print(f"  DECLINE {orders[c]['customer']}: {why}")


def group_loads(trays):
    """{(load minute, customer): (number of trays, pieces)} - how Rosa reads the load list."""
    g = {}
    for t in trays:
        n, q = g.get((t["start"], t["customer_id"]), (0, 0))
        g[(t["start"], t["customer_id"])] = (n + 1, q + t["pieces"])
    return dict(sorted(g.items()))


def ingest_log(path):
    matrix, _ = geo.load_matrix()
    try:
        log = logs.read_log(path, matrix)
    except logs.LogError as e:
        sys.exit(f"STOPPED reading delivery log: {e}")
    db.store_observations(log)
    gaps = [abs(a["actual"] - a["planned"]) for a in log["arrivals"]
            if a["actual"] is not None and a["planned"] is not None and a["customer_id"] != "DEPOT"]
    med = statistics.median(gaps) if gaps else None
    with db.engine().begin() as c:
        c.execute(db.runs.update().where((db.runs.c.delivery_date == log["run_date"]) &
                                         (db.runs.c.planner == "planner")).values(median_gap_min=med))
    print(f"Read {log['source_file']}: {len(log['observations'])} drive legs learned, "
          f"median planned-vs-actual gap {med if med is None else round(med, 1)} min, {len(log['flags'])} flags")
    for f in log["flags"]:
        print(f"  log flag: {f}")
    return log


def drive_morning(day):
    """Simulate the morning for the approved plan (and the old rule, for comparison) and write the van log."""
    status = db.run_status(day)
    if status != "approved":  # Guard G-run2: only a plan Rosa approved is driven, and only once
        sys.exit(f"STOPPED: the plan for {day} is '{status or 'missing'}'. Only an approved plan can be driven"
                 f"{' (it was already driven)' if status == 'done' else ''}.")
    plan_doc = json.loads((config.PLAN_DIR / day / "plan.json").read_text(encoding="utf-8"))
    orders = {o["customer_id"]: o for o in plan_doc["orders"]}
    matrix, _ = geo.load_matrix()
    price = plan_doc["ingredient_prices"]
    plan = {"oven": plan_doc["oven"], "leave": plan_doc["leave"], "route": plan_doc["route"],
            "loads": [t["start"] for t in plan_doc["trays"]]}
    planned = execute(plan, orders, lambda a, c, t: _leg_lookup(plan_doc, a, c), price, loads=plan["loads"])
    actual = simulate.run_actual(plan, orders, matrix, day, price)
    db.save_actual(day, "planner", actual)
    old = plan_doc["old_rule_plan"]
    db.save_actual(day, "old_rule", simulate.run_actual(old, orders, matrix, day, price))
    names = {c: o["customer"] for c, o in orders.items()}
    path = simulate.write_log(day, planned, actual, names)
    print(f"Morning {day} driven: actual profit ${actual['profit']:,.0f} (planned ${plan_doc['claimed']['profit']:,.0f}), "
          f"{actual['fresh_share']:.0%} fresh, {actual['refused_pieces']} refused. Log -> {path}")
    return path


def _leg_lookup(plan_doc, a, c):
    for leg in plan_doc["legs"]:
        if leg["from"] == a and leg["to"] == c:
            return leg["minutes"]
    raise KeyError((a, c))


def setup():
    """Load reference data (customers, prices) into the database."""
    db.store_customers(geo.load_customers())
    db.store_prices(prices.load_all()[0])
    print(f"Customers and BLS prices loaded into {db.where()}")


def clean_step(path):
    return clean.main(path)


def backfill(until=None, quiet=True):
    """Run the whole nightly loop for every order sheet up to and including `until`:
    clean -> plan -> (auto-approve, history only) -> drive -> ingest log."""
    setup()
    files = sorted(config.RAW_ORDERS.glob("orders_*.csv"))
    n = 0
    for f in files:
        day = f.stem.split("_")[1]
        if until and day > until:
            break
        if db.run_status(day) == "done":  # already happened: keep its actual results
            continue
        res = clean.clean_file(f)
        config.CLEAN_DIR.mkdir(parents=True, exist_ok=True)
        (config.CLEAN_DIR / f"{day}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
        plan_day(day, verbose=not quiet)
        db.set_status(day, "approved")
        log_path = drive_morning(day)
        ingest_log(log_path)
        n += 1
    print(f"Backfilled {n} mornings into {db.where()}")
