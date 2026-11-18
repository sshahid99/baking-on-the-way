"""Small evaluation: run the clean -> plan -> verify steps on the six hand-made cases in
tests/eval_cases/ and score them against work/eval-criteria.md (written before the first run).

    python checks/evaluate.py          -> prints the score table, appends it to work/eval-results.md
Uses a throw-away SQLite database so it never touches the real one.
"""
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "tests" / "eval_cases"
PY = sys.executable


def run(*args, env=None):
    r = subprocess.run([PY, *args], cwd=ROOT, capture_output=True, text=True, env=env)
    return r.returncode, r.stdout + r.stderr


def clean_json(day):
    p = ROOT / "output" / "clean" / f"{day}.json"
    return json.loads(p.read_text()) if p.exists() else None


def plan_case(day, env):
    code, out = run("-m", "bakery", "plan", day, env=env)
    if code != 0:
        return False, out
    code, out = run("checks/verify_plan.py", day, env=env)
    return code == 0, out


def main():
    tmp = tempfile.mkdtemp()
    env = dict(os.environ, DATABASE_URL="")  # empty -> SQLite; point it at a temp copy below
    env["PYTHONPATH"] = str(ROOT)
    # isolate: a temporary SQLite file via a tiny shim
    env["BAKERY_SQLITE"] = str(Path(tmp) / "eval.db")
    for day in ("2026-12-02", "2026-12-03", "2026-12-04", "2026-12-05", "2026-12-06", "2026-12-07"):
        for p in (ROOT / "output" / "clean" / f"{day}.json", ROOT / "output" / "plans" / day):
            if p.is_dir():
                shutil.rmtree(p)
            elif p.exists():
                p.unlink()
    run("-m", "bakery", "setup", env=env)
    score = {}

    # E1
    code, out = run("-m", "bakery", "clean", str(CASES / "orders_2026-12-02.csv"), env=env)
    ok_plan, _ = plan_case("2026-12-02", env) if code == 0 else (False, "")
    c = clean_json("2026-12-02")
    plan = json.loads((ROOT / "output/plans/2026-12-02/plan.json").read_text()) if ok_plan else None
    accounted = bool(plan) and set(plan["route"]) | set(plan["declined_by_planner"]) == {o["customer_id"] for o in c["orders"]}
    score["E1"] = [code == 0, ok_plan, accounted]

    # E2
    code, out = run("-m", "bakery", "clean", str(CASES / "orders_2026-12-03.csv"), env=env)
    score["E2"] = [code == 2, "wanted_by" in out, not (ROOT / "output/plans/2026-12-03").exists()]

    # E3
    code, out = run("-m", "bakery", "clean", str(CASES / "orders_2026-12-04.csv"), env=env)
    c = clean_json("2026-12-04") if code == 0 else None
    ok_plan, _ = plan_case("2026-12-04", env) if c else (False, "")
    ellum = next((o for o in (c or {}).get("orders", []) if o["customer"] == "Ellum Grind"), None)
    green = next((o for o in (c or {}).get("orders", []) if o["customer"] == "Greenville Grounds"), None)
    rules = [f["rule"] for f in (c or {}).get("flags", [])]
    score["E3"] = [bool(ellum) and ellum["pieces"] == 24 and ellum["lines"][0]["price"] == 2.75,
                   "C10" in rules, bool(green) and green["lines"][0]["price"] == 2.75 and "C9" in rules, ok_plan]

    # E4
    code, out = run("-m", "bakery", "clean", str(CASES / "orders_2026-12-05.csv"), env=env)
    c = clean_json("2026-12-05") if code == 0 else {"orders": [], "flags": [], "declined_at_cleaning": []}
    by = {o["customer"]: o for o in c["orders"]}
    dec = {d["customer"]: d["rule"] for d in c["declined_at_cleaning"]}
    score["E4"] = ["Ellum Grind" in by,
                   by.get("Ellum Grind", {}).get("pieces") == 24 and by.get("Lakewood Perk", {}).get("pieces") == 36,
                   dec.get("Sunrise Yoga Studio") == "C3",
                   any(f["rule"] == "C7" and "200" in f["text"] for f in c["flags"]),
                   by.get("Lakewood Perk", {}).get("wanted_by") == 360 and any(f["rule"] == "C8" for f in c["flags"])]

    # E5
    code, out = run("-m", "bakery", "clean", str(CASES / "orders_2026-12-06.csv"), env=env)
    score["E5"] = [code == 2 and "STOPPED" in out, "Traceback" not in out]

    # E6
    code, out = run("-m", "bakery", "clean", str(CASES / "orders_2026-12-07.csv"), env=env)
    c = clean_json("2026-12-07") if code == 0 else None
    by = {o["customer"]: o for o in (c or {}).get("orders", [])}
    dec = {d["customer"]: d["rule"] for d in (c or {}).get("declined_at_cleaning", [])}
    ok_plan, _ = plan_case("2026-12-07", env) if c else (False, "")
    score["E6"] = [code == 0 and "Traceback" not in out, dec.get("Knox Kettle") == "C5",
                   by.get("Ellum Grind", {}).get("wanted_by") == 405 and by.get("Lakewood Perk", {}).get("wanted_by") == 375 and ok_plan]

    total = sum(sum(v) for v in score.values())
    n = sum(len(v) for v in score.values())
    lines = [f"## Run {dt.datetime.now().isoformat(timespec='minutes')}: {total}/{n} points, "
             f"{sum(all(v) for v in score.values())}/{len(score)} cases pass", "",
             "| case | points | detail |", "|---|---|---|"]
    for k, v in score.items():
        lines.append(f"| {k} | {sum(v)}/{len(v)} | {' '.join('ok' if x else 'MISS' for x in v)} |")
    text = "\n".join(lines) + "\n\n"
    print(text)
    with open(ROOT / "work" / "eval-results.md", "a", encoding="utf-8") as f:
        f.write(text)
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
