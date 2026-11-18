"""The run model: one place that turns a plan into times, freshness and dollars.

A plan is:
    oven      "small" | "medium" | "large"   (24 / 48 / 96 pieces in the oven at once)
    leave     minute the van leaves the kitchen
    route     list of customer_ids in stop order (accepted orders only)
    loads     optional list of tray load minutes (one per tray, in tray order). If missing,
              schedule_loads() back-calculates them.

Trays: each stop's pieces go on 12-piece trays (30 pieces -> 12, 12, 6). A tray bakes 18 minutes
from the minute it is loaded. Trays overlap in the oven as long as the pieces inside at any
minute fit the oven (decision 2026-11-18, "staggered trays").

execute(plan, orders, drive) drives the route with any drive-time function:
    drive(from_id, to_id, depart_minute) -> minutes
Use the planner's estimate for the expected result, or the simulated world for the actual one.
The van waits if it is early for the cafe opening or if a tray for the stop is not out yet.
"""
import math

from . import config

DEPOT_ID = "DEPOT"
DAY = 24 * 60


def freshness_share(age_min: float, late_min: float) -> float:
    """Share of the agreed price the cafe pays. 0 means refused (food pantry)."""
    if late_min > config.LATE_GRACE_MIN or age_min > 45:
        return 0.0
    share = 0.6
    for limit, s in config.FRESHNESS_TIERS:
        if age_min < limit:
            share = s
            break
    if late_min > 0:
        share -= config.LATE_DISCOUNT
    return max(round(share, 4), 0.0)


def build_trays(plan, orders):
    """[(customer_id, pieces), ...] in route order."""
    trays = []
    for cid in plan["route"]:
        q = orders[cid]["pieces"]
        while q > 0:
            take = min(q, config.TRAY_PIECES)
            trays.append((cid, take))
            q -= take
    return trays


def _drive_through(plan, orders, drive, ready=None):
    """Forward pass. ready: customer_id -> minute its last tray is out. Returns (stops, back_at)."""
    t, pos, stops = plan["leave"], DEPOT_ID, []
    for cid in plan["route"]:
        o = orders[cid]
        d = drive(pos, cid, t)
        curb = t + d
        deliver = max(curb, o["opens_at"])
        if ready is not None:
            deliver = max(deliver, ready.get(cid, 0) + config.UNLOAD_BUFFER_MIN)
        stops.append({"customer_id": cid, "depart_prev": t, "drive_min": d, "curb": curb, "deliver": deliver})
        t, pos = deliver + config.STOP_MIN, cid
    back = drive(pos, DEPOT_ID, t) if plan["route"] else 0.0
    return stops, t + back


def _fits(occ, start, q, cap):
    return start >= 0 and start + config.BAKE_MIN <= DAY and max(occ[start:start + config.BAKE_MIN]) + q <= cap


def _place(occ, start, q):
    for m in range(start, start + config.BAKE_MIN):
        occ[m] += q


def schedule_loads(plan, orders, drive):
    """Back-calculate load minutes: each tray comes out just before its stop, as late as the oven's
    capacity allows, never before 4:45. Trays for later stops are placed first."""
    cap = config.OVENS[plan["oven"]][0]
    trays = build_trays(plan, orders)
    stops, _ = _drive_through(plan, orders, drive)
    arrive = {s["customer_id"]: s["deliver"] for s in stops}
    occ = [0] * DAY
    loads = [None] * len(trays)
    for k in sorted(range(len(trays)), key=lambda k: -arrive[trays[k][0]]):
        cid, q = trays[k]
        latest = math.floor(arrive[cid] - config.UNLOAD_BUFFER_MIN - config.BAKE_MIN)
        s = latest
        while s >= config.EARLIEST_START and not _fits(occ, s, q, cap):
            s -= 1
        if s < config.EARLIEST_START:  # no room early enough: first slot after, the van will wait
            s = max(config.EARLIEST_START, latest)
            while not _fits(occ, s, q, cap):
                s += 1
        _place(occ, s, q)
        loads[k] = s
    return loads


def oven_peak(trays, loads):
    occ = [0] * DAY
    for (cid, q), s in zip(trays, loads):
        _place(occ, int(s), q)
    return max(occ) if trays else 0


def ingredient_cost_per_piece(prices: dict) -> float:
    return config.OTHER_COST_PER_PIECE + sum(q * prices[s] for s, q in config.RECIPE.items())


def execute(plan, orders, drive, prices, loads=None):
    """Run the plan. Returns a result dict with stops, trays, money and freshness."""
    trays = build_trays(plan, orders)
    loads = loads if loads is not None else plan.get("loads")
    if loads is None:
        loads = schedule_loads(plan, orders, drive)
    ready = {}
    for (cid, q), s in zip(trays, loads):
        ready[cid] = max(ready.get(cid, 0), s + config.BAKE_MIN)
    stops, back_at = _drive_through(plan, orders, drive, ready)
    at = {s["customer_id"]: s for s in stops}
    for s in stops:
        s.update(pieces=0, revenue=0.0, fresh=0, refused=0, ages=[])
    for k, ((cid, q), start) in enumerate(zip(trays, loads)):
        s, o = at[cid], orders[cid]
        age = s["deliver"] - (start + config.BAKE_MIN)
        late = s["deliver"] - o["wanted_by"]
        share = freshness_share(age, late)
        s["pieces"] += q
        s["revenue"] += q * (o["revenue_full"] / o["pieces"]) * share
        s["ages"].append({"tray": k + 1, "pieces": q, "age": round(age, 1), "share": share})
        if age < 15 and share > 0:
            s["fresh"] += q
        if share == 0:
            s["refused"] += q
    revenue = 0.0
    for s in stops:
        s["late_min"] = max(0.0, s["deliver"] - orders[s["customer_id"]]["wanted_by"])
        revenue += s["revenue"]
        s["revenue"] = round(s["revenue"], 2)

    pieces = sum(s["pieces"] for s in stops)
    fresh = sum(s["fresh"] for s in stops)
    refused = sum(s["refused"] for s in stops)
    shift_start = min([plan["leave"]] + list(loads))
    hours = (back_at - shift_start) / 60.0 if plan["route"] else 0.0
    van = config.VAN_RATE_PER_HOUR * hours
    oven = config.OVENS[plan["oven"]][1] * hours
    ingredients = ingredient_cost_per_piece(prices) * pieces
    return {
        "stops": stops,
        "trays": [{"n": k + 1, "customer_id": cid, "pieces": q, "start": s, "end": s + config.BAKE_MIN}
                  for k, ((cid, q), s) in enumerate(zip(trays, loads))],
        "loads": list(loads), "shift_start": shift_start, "back_at": back_at, "hours": hours,
        "revenue": revenue, "van_cost": van, "oven_cost": oven, "ingredient_cost": ingredients,
        "profit": revenue - van - oven - ingredients, "pieces": pieces, "fresh_pieces": fresh,
        "refused_pieces": refused, "fresh_share": fresh / pieces if pieces else 0.0,
        "oven_peak": oven_peak(trays, loads),
    }
