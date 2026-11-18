"""The planning loop and Rosa's rule-of-thumb baseline.

optimize(): for each oven size, start from a greedy route (by wanted-by time), then repeat
rounds of local search. Each round tries every move below and keeps the single best one:
    2-opt      reverse a stretch of the route
    relocate   move one stop elsewhere
    decline    drop one order (it earns nothing and costs nothing)
    accept     put a declined order back at its best position
    oven       switch to another oven size (each size also gets its own run of the loop)
    leave      leave 1, 3 or 10 minutes earlier or later
STOP CONDITION: a round adds less than $1 of profit (MIN_ROUND_GAIN) or 20 rounds (MAX_ROUNDS).
Every round is logged so the trace can be shown.
"""
from . import config
from .model import execute, schedule_loads

DEPOT = "DEPOT"


def _evaluate(plan, orders, drive, prices):
    plan["loads"] = schedule_loads(plan, orders, drive)
    return execute(plan, orders, drive, prices)


def _copy(plan):
    return {"oven": plan["oven"], "leave": plan["leave"], "route": list(plan["route"]),
            "declined": list(plan["declined"])}


def _best_leave(plan, orders, drive, prices):
    best = None
    for leave in range(config.EARLIEST_START, 7 * 60 + 31, 5):
        p = _copy(plan)
        p["leave"] = leave
        r = _evaluate(p, orders, drive, prices)
        if best is None or r["profit"] > best[1]["profit"]:
            best = (p, r)
    return best


def greedy_start(oven, orders, drive, prices):
    route = sorted(orders, key=lambda c: (orders[c]["wanted_by"], orders[c]["opens_at"], c))
    plan = {"oven": oven, "leave": 0, "route": route, "declined": []}
    return _best_leave(plan, orders, drive, prices)


def neighbours(plan):
    r, n = plan["route"], len(plan["route"])
    for i in range(n - 1):
        for j in range(i + 1, n):
            p = _copy(plan)
            p["route"][i:j + 1] = reversed(r[i:j + 1])
            yield f"2-opt reverse stops {i + 1}-{j + 1}", p
    for i in range(n):
        for j in range(n):
            if i != j and j != i - 1:
                p = _copy(plan)
                c = p["route"].pop(i)
                p["route"].insert(j, c)
                yield f"move {c} from stop {i + 1} to {j + 1}", p
    for i in range(n):
        p = _copy(plan)
        c = p["route"].pop(i)
        p["declined"].append(c)
        yield f"decline {c}", p
    for c in plan["declined"]:
        for j in range(n + 1):
            p = _copy(plan)
            p["declined"].remove(c)
            p["route"].insert(j, c)
            yield f"accept {c} as stop {j + 1}", p
    for dm in (-10, -3, -1, 1, 3, 10):
        p = _copy(plan)
        p["leave"] = max(config.EARLIEST_START, plan["leave"] + dm)
        if p["leave"] != plan["leave"]:
            yield f"leave {dm:+d} min", p


def improve(plan, result, orders, drive, prices, log):
    for rnd in range(1, config.MAX_ROUNDS + 1):
        best_move, best_plan, best_res = None, None, result
        for move, p in neighbours(plan):
            res = _evaluate(p, orders, drive, prices)
            if res["profit"] > best_res["profit"] + 1e-9:
                best_move, best_plan, best_res = move, p, res
        gain = best_res["profit"] - result["profit"]
        if best_plan is not None:
            plan, result = best_plan, best_res
        log.append({"oven": plan["oven"], "round": rnd, "move": best_move or "(no improving move)",
                    "gain": round(gain, 2), "profit": round(result["profit"], 2)})
        if gain < config.MIN_ROUND_GAIN:
            log[-1]["stop"] = f"gain ${gain:.2f} < ${config.MIN_ROUND_GAIN:.0f}"
            break
    else:
        log[-1]["stop"] = f"reached {config.MAX_ROUNDS} rounds"
    return plan, result


def optimize(orders, drive, prices):
    """Returns (best_plan, best_result, per_oven summary, round log)."""
    log, per_oven, best = [], {}, None
    for oven in config.OVENS:
        plan, res = greedy_start(oven, orders, drive, prices)
        log.append({"oven": oven, "round": 0, "move": "greedy start (by wanted-by time)",
                    "gain": 0.0, "profit": round(res["profit"], 2)})
        plan, res = improve(plan, res, orders, drive, prices, log)
        per_oven[oven] = round(res["profit"], 2)
        if best is None or res["profit"] > best[1]["profit"]:
            best = (plan, res)
    return best[0], best[1], per_oven, log


def baseline_plan(orders, drive):
    """Rosa's rule of thumb today, made fair (decisions 2026-11-18, B1-B2):
      * medium oven every day; first come, first served by submission time, at most 8 stops;
      * drive the stops in wanted-by order; leave so the first stop is reached as it opens,
        using the SAME traffic-aware drive estimate the planner gets (a phone map app);
      * preload: trays for the first half of the stops go in 18 min before leaving (as fast as the
        oven fits them); she reloads for the second half when she reaches the halfway stop."""
    from .model import DAY, _drive_through, _fits, _place, build_trays
    taken = sorted(orders, key=lambda c: (orders[c].get("submitted_at", ""), c))[:config.OLD_RULE_MAX_STOPS]
    route = sorted(taken, key=lambda c: (orders[c]["wanted_by"], orders[c]["opens_at"], c))
    declined = [c for c in orders if c not in taken]
    first = orders[route[0]]
    leave = max(config.EARLIEST_START + config.BAKE_MIN,
                int(first["opens_at"] - drive(DEPOT, route[0], first["opens_at"] - 15)))
    plan = {"oven": "medium", "leave": leave, "route": route, "declined": declined}
    stops, _ = _drive_through(plan, orders, drive)
    half = (len(route) + 1) // 2
    first_half = set(route[:half])
    reload_at = int(stops[half - 1]["deliver"]) if len(route) > 1 else leave
    cap = config.OVENS["medium"][0]
    preload = leave - config.BAKE_MIN
    occ, loads, s = [0] * DAY, [], preload
    for cid, q in build_trays(plan, orders):
        s = max(s, preload if cid in first_half else reload_at)
        while not _fits(occ, s, q, cap):
            s += 1
        _place(occ, s, q)
        loads.append(s)
    plan["loads"] = loads
    return plan
