"""Independent check of a plan, used by the plan-reviewer subagent (step 3 of /plan-run).

    python checks/verify_plan.py 2026-11-10        -> exit 0 PASS, exit 1 FAIL

It deliberately does NOT import bakery.model or bakery.optimize. The rules and prices below are
re-typed from decisions.md, so a bug in the planner cannot hide itself by being in both places.
If someone changes an assumption in bakery/config.py without updating decisions.md and this file,
the profit check fails: that is intended.

Hard rules (decisions.md, "Plan rules"):
  H1 oven never over capacity at any minute     H5 every tray is out before its stop is served
  H2 every tray bakes exactly 18 min, <= 12 pcs H6 no stop more than 15 min after wanted-by
  H3 every accepted piece is on a tray          H7 no tray loaded before 4:45
  H4 no delivery before the cafe opens          H8 every cleaned order is either on the route or declined
Profit: recomputed from the plan's own leg times; must match the claimed profit within $1.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAPACITY = {"small": 24, "medium": 48, "large": 96}
OVEN_RATE = {"small": 30.0, "medium": 45.0, "large": 70.0}
VAN_RATE = 38.0
BAKE, STOP, BUFFER, TRAY_MAX, EARLIEST = 18, 8, 1, 12, 285
RECIPE = {"APU0000701111": 0.06, "APU0000708111": 0.10 / 12, "APU0000FS1101": 0.03}
OTHER = 0.35


def share(age, late):
    if late > 15 or age > 45:
        return 0.0
    s = 1.0 if age < 15 else 0.8 if age < 30 else 0.6
    return s - 0.2 if late > 0 else s


def verify(doc):
    problems, notes = [], []
    orders = {o["customer_id"]: o for o in doc["orders"]}
    trays, route, oven = doc["trays"], doc["route"], doc["oven"]

    # H1 / H2 / H7
    minute_load = {}
    for t in trays:
        if abs((t["end"] - t["start"]) - BAKE) > 1e-6:
            problems.append(f"H2 tray {t['n']} bakes {t['end'] - t['start']} min, not {BAKE}")
        if not 0 < t["pieces"] <= TRAY_MAX:
            problems.append(f"H2 tray {t['n']} has {t['pieces']} pieces")
        if t["start"] < EARLIEST:
            problems.append(f"H7 tray {t['n']} loaded at minute {t['start']} (before 4:45)")
        for m in range(int(t["start"]), int(t["start"]) + BAKE):
            minute_load[m] = minute_load.get(m, 0) + t["pieces"]
    peak = max(minute_load.values()) if minute_load else 0
    if peak > CAPACITY[oven]:
        problems.append(f"H1 oven holds {peak} pieces at once; {oven} holds {CAPACITY[oven]}")

    # H3 / H8
    on_trays = {}
    for t in trays:
        on_trays[t["customer_id"]] = on_trays.get(t["customer_id"], 0) + t["pieces"]
    for c in route:
        if on_trays.get(c, 0) != orders[c]["pieces"]:
            problems.append(f"H3 {orders[c]['customer']}: {on_trays.get(c, 0)} on trays, ordered {orders[c]['pieces']}")
    declined = set(doc["declined_by_planner"])
    for c in orders:
        if (c in route) == (c in declined):
            problems.append(f"H8 {orders[c]['customer']} is {'both routed and declined' if c in route else 'neither routed nor declined'}")
    if set(on_trays) - set(route):
        problems.append(f"H3 trays baked for customers not on the route: {set(on_trays) - set(route)}")

    # Re-drive the route from the plan's own leg minutes
    legs = {(l["from"], l["to"]): l["minutes"] for l in doc["legs"]}
    ready = {}
    for t in trays:
        ready[t["customer_id"]] = max(ready.get(t["customer_id"], 0), t["end"])
    t_now, pos, revenue, pieces, fresh = doc["leave"], "DEPOT", 0.0, 0, 0
    for c in route:
        o = orders[c]
        curb = t_now + legs[(pos, c)]
        deliver = max(curb, o["opens_at"], ready.get(c, 0) + BUFFER)
        if deliver < o["opens_at"]:
            problems.append(f"H4 {o['customer']} served before opening")
        late = deliver - o["wanted_by"]
        if late > 15 + 1e-6:
            problems.append(f"H6 {o['customer']} served {late:.0f} min after wanted-by")
        unit = o["revenue_full"] / o["pieces"]
        for t in trays:
            if t["customer_id"] != c:
                continue
            if t["end"] + BUFFER > deliver + 1e-6:
                problems.append(f"H5 tray {t['n']} not out before {o['customer']} is served")
            age = deliver - t["end"]
            revenue += t["pieces"] * unit * share(age, late)
            pieces += t["pieces"]
            fresh += t["pieces"] if (age < 15 and share(age, late) > 0) else 0
        t_now, pos = deliver + STOP, c
    back = t_now + legs[(pos, "DEPOT")] if route else t_now
    start = min([doc["leave"]] + [t["start"] for t in trays])
    hours = (back - start) / 60
    cost_piece = OTHER + sum(q * doc["ingredient_prices"][s] for s, q in RECIPE.items())
    profit = revenue - hours * (VAN_RATE + OVEN_RATE[oven]) - pieces * cost_piece
    claimed = doc["claimed"]["profit"]
    if abs(profit - claimed) > 1.0:
        problems.append(f"PROFIT recomputed ${profit:,.2f} but plan claims ${claimed:,.2f}")
    notes.append(f"recomputed profit ${profit:,.2f} (claimed ${claimed:,.2f}); "
                 f"{fresh}/{pieces} pieces fresh; oven peak {peak}/{CAPACITY[oven]}; back {int(back)//60}:{int(back)%60:02d}")
    return problems, notes, round(profit, 2)


def main(day):
    path = ROOT / "output" / "plans" / day / "plan.json"
    if not path.exists():
        print(f"FAIL: no plan at {path}")
        return 1
    doc = json.loads(path.read_text(encoding="utf-8"))
    problems, notes, profit = verify(doc)
    verdict = "PASS" if not problems else "FAIL"
    (path.parent / "verify.json").write_text(json.dumps(
        {"verdict": verdict, "problems": problems, "notes": notes, "recomputed_profit": profit}, indent=1))
    print(f"{verdict} {day}")
    for p in problems:
        print(f"  PROBLEM {p}")
    for n in notes:
        print(f"  {n}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
