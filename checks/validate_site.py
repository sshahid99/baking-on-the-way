"""Validate docs/data/dashboard.json before it is published (GitHub Actions + pre-push hook).

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
    rs = d.get("run_sheet", {})
    if rs.get("oven") not in ("small", "medium", "large"):
        problems.append(f"run_sheet.oven is {rs.get('oven')!r}")
    if not isinstance(rs.get("expected_profit"), (int, float)):
        problems.append("run_sheet.expected_profit is not a number")
    if rs.get("status") not in ("planned", "approved", "done"):
        problems.append(f"run_sheet.status is {rs.get('status')!r}")
    times = [e.get("min") for e in rs.get("events", [])]
    if times != sorted(times):
        problems.append("run_sheet.events are not in time order")
    if not any(e.get("kind") == "stop" for e in rs.get("events", [])):
        problems.append("run_sheet has no stops")
    for w in d.get("weekly", []):
        for k in ("planner_fresh", "old_rule_fresh"):
            if not 0 <= w.get(k, -1) <= 1:
                problems.append(f"weekly {w.get('week')} {k} out of 0..1")
    if SECRET.search(json.dumps(d)):
        problems.append("something that looks like a secret or connection string is in the JSON")
    return problems


def main():
    p = ROOT / "docs" / "data" / "dashboard.json"
    if not p.exists():
        print(f"FAIL: {p} not found")
        return 1
    problems = validate(json.loads(p.read_text(encoding="utf-8")))
    for x in problems:
        print(f"FAIL: {x}")
    if not problems:
        print("dashboard.json valid")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
