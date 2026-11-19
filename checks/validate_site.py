"""Validate docs/data/dashboard.json and docs/data/days/*.json before they are published (GitHub Actions + pre-push hook).

    python checks/validate_site.py      -> exit 0 if valid, 1 with a list of problems
Checks shape and types, and that nothing secret-looking leaked into the public JSON.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = {
    "meta": ["generated_at", "orders_through", "disclaimer", "database"],
    "run_sheet": ["delivery_date", "status", "oven", "leave", "expected_profit", "old_rule_profit",
                  "events", "declined", "flags", "per_oven", "costs"],
}
SECRET = re.compile(r"(mysql|postgres)(\+\w+)?://|password|aivencloud|avnadmin|api[_-]?key", re.I)


def validate(d):
    problems = []
    for section, keys in REQUIRED.items():
        if section not in d:
            problems.append(f"missing section '{section}'")
            continue
        for k in keys:
            if k not in d[section]:
                problems.append(f"{section}.{k} missing")
    problems += validate_run_sheet(d.get("run_sheet", {}), "run_sheet")
    route = d.get("route")
    if route is not None:
        problems += validate_route(route)
    for w in d.get("weekly", []):
        for k in ("planner_fresh", "old_rule_fresh"):
            if not 0 <= w.get(k, -1) <= 1:
                problems.append(f"weekly {w.get('week')} {k} out of 0..1")
    if SECRET.search(json.dumps(d)):
        problems.append("something that looks like a secret or connection string is in the JSON")
    return problems


def validate_run_sheet(rs, where):
    problems = []
    if rs.get("oven") not in ("small", "medium", "large"):
        problems.append(f"{where}.oven is {rs.get('oven')!r}")
    if not isinstance(rs.get("expected_profit"), (int, float)):
        problems.append(f"{where}.expected_profit is not a number")
    if rs.get("status") not in ("planned", "approved", "done"):
        problems.append(f"{where}.status is {rs.get('status')!r}")
    times = [e.get("min") for e in rs.get("events", [])]
    if times != sorted(times):
        problems.append(f"{where}.events are not in time order")
    if not any(e.get("kind") == "stop" for e in rs.get("events", [])):
        problems.append(f"{where} has no stops")
    return problems


def validate_morning(r, where, planned):
    """The map animates the van through these times, so they must exist and never run backwards."""
    problems = []
    num = lambda v: isinstance(v, (int, float))  # noqa: E731
    if not r.get("stops"):
        problems.append(f"{where} has no stops")
    times = [r.get("leave_min")]
    for s in r.get("stops", []):
        if not (num(s.get("lat")) and num(s.get("lon"))):
            problems.append(f"{where} stop {s.get('seq')} has no coordinates")
        if planned and not all(num(s.get(k)) for k in ("arrive_min", "handoff_min", "depart_min")):
            problems.append(f"{where} stop {s.get('seq')} is missing a time")
        times += [s.get("arrive_min"), s.get("handoff_min"), s.get("depart_min")]
    times.append(r.get("back_min"))
    known = [t for t in times if num(t)]
    if any(b < a - 0.01 for a, b in zip(known, known[1:])):
        problems.append(f"{where} times run backwards")
    return problems


def validate_route(route):
    problems = []
    num = lambda v: isinstance(v, (int, float))  # noqa: E731
    dep = route.get("depot") or {}
    if not (num(dep.get("lat")) and num(dep.get("lon"))):
        problems.append("route.depot has no coordinates")
    if route.get("next") is None:
        problems.append("route.next missing")
    else:
        problems += validate_morning(route["next"], "route.next", planned=True)
    if route.get("last") is not None:
        problems += validate_morning(route["last"], "route.last", planned=False)
    return problems


def validate_day(day, v):
    """One morning's file in docs/data/days/ (decision S10): what the calendar opens."""
    where = f"days/{day}.json"
    problems = []
    if v.get("delivery_date") != day:
        problems.append(f"{where} is for {v.get('delivery_date')!r}")
    rs = v.get("run_sheet") or {}
    problems += validate_run_sheet(rs, where)
    m = (v.get("route") or {}).get("morning")
    if m is None:
        problems.append(f"{where} has no route")
    else:
        problems += validate_morning(m, where + " route", planned=m.get("kind") == "planned")
    done = rs.get("status") == "done"
    if done != (v.get("outcome") is not None):
        problems.append(f"{where}: a finished morning needs an outcome, and only a finished one")
    if done and not all("actual" in e for e in rs.get("events", []) if e.get("kind") == "stop"):
        problems.append(f"{where}: a stop has no actual arrival")
    if SECRET.search(json.dumps(v)):
        problems.append(f"{where}: something that looks like a secret is in the JSON")
    return problems


def validate_calendar(cal, day_dir):
    problems = []
    dates = [x.get("date") for x in cal.get("days", [])]
    if not dates:
        return ["calendar has no days"]
    if dates != sorted(set(dates)):
        problems.append("calendar days are not in order, or a day is listed twice")
    if cal.get("next") not in dates:
        problems.append("calendar.next is not one of the calendar days")
    for x in cal["days"]:
        f = day_dir / f"{x['date']}.json"
        if not f.exists():
            problems.append(f"calendar lists {x['date']} but {f.name} is missing")
            continue
        problems += validate_day(x["date"], json.loads(f.read_text(encoding="utf-8")))
        if (x.get("status") == "done") != isinstance(x.get("actual_profit"), (int, float)):
            problems.append(f"calendar {x['date']}: actual profit should be there exactly when the morning is done")
    extra = {f.stem for f in day_dir.glob("*.json")} - set(dates)
    if extra:
        problems.append(f"day files not on the calendar: {', '.join(sorted(extra))}")
    return problems


def main():
    p = ROOT / "docs" / "data" / "dashboard.json"
    if not p.exists():
        print(f"FAIL: {p} not found")
        return 1
    d = json.loads(p.read_text(encoding="utf-8"))
    problems = validate(d)
    if "calendar" in d:
        problems += validate_calendar(d["calendar"], p.parent / "days")
    else:
        problems.append("calendar missing (run `python -m bakery export`)")
    for x in problems:
        print(f"FAIL: {x}")
    if not problems:
        print(f"dashboard.json valid, plus {len(d['calendar']['days'])} day files")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
