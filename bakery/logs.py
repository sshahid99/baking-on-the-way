"""Read and clean a van delivery log into drive-time observations (rules L1-L5 in decisions.md).

Each observation is one leg: from the previous stop's departure to this stop's arrival.
"""
import csv
import re
from pathlib import Path

from . import config

REQUIRED = ["run_date", "stop_seq", "customer_id", "planned_arrival", "actual_arrival", "actual_departure"]


class LogError(Exception):
    pass


def read_log(path, matrix):
    path = Path(path)
    if not path.exists():
        raise LogError(f"Delivery log not found: {path}")
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = [{k.strip(): (v or "").strip() for k, v in r.items() if k} for r in reader]
        header = reader.fieldnames or []
    missing = [c for c in REQUIRED if c not in header]
    if missing:  # L1
        raise LogError(f"{path.name} is missing column(s): {', '.join(missing)}")
    m = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
    run_date = m.group(1) if m else (rows[0]["run_date"] if rows else None)
    if not run_date:
        raise LogError(f"Cannot tell which morning {path.name} is for.")

    flags, seen, clean = [], set(), []
    for r in rows:  # L2 duplicates
        key = r["stop_seq"]
        if key in seen:
            flags.append(f"stop {key}: duplicate row dropped")
            continue
        seen.add(key)
        clean.append(r)
    clean.sort(key=lambda r: int(r["stop_seq"]))

    def t(s):
        try:
            return config.parse_hhmm(s) if s else None
        except ValueError:  # unreadable time -> treat like a GPS gap (L3)
            return None

    # L4 clock skew: the gap to plan jumps by about an hour between two consecutive rows.
    # (A van that is simply late drifts slowly; a device clock jumps all at once.)
    shift, prev_gap = 0, None
    for r in clean:
        arr, plan = t(r["actual_arrival"]), t(r["planned_arrival"])
        r["_arr"], r["_dep"] = arr, t(r["actual_departure"])
        if arr is None or plan is None:
            if shift and r["_dep"] is not None:
                r["_dep"] -= shift
            continue
        gap = arr - plan
        if prev_gap is not None and abs(gap - shift - prev_gap) >= 45:
            jump = gap - shift - prev_gap
            shift += 60 if jump > 0 else -60
            flags.append(f"stop {r['stop_seq']}: clock jumped about {jump:+.0f} min; times from here corrected by {-shift:+d}")
        if shift:
            r["_arr"] -= shift
            if r["_dep"] is not None:
                r["_dep"] -= shift
        prev_gap = gap - shift

    obs = []
    for prev, cur in zip(clean, clean[1:]):
        if prev["_dep"] is None or cur["_arr"] is None:  # L3 GPS gap
            if cur["_arr"] is None and cur.get("gps", "ok") != "ok":
                flags.append(f"stop {cur['stop_seq']}: GPS gap; legs touching it not used")
            continue
        drive = cur["_arr"] - prev["_dep"]
        key = (prev["customer_id"], cur["customer_id"])
        if drive <= 0 or drive > 90 or key not in matrix:  # L5 impossible legs
            flags.append(f"leg {key[0]}->{key[1]}: {drive} min is impossible; not used")
            continue
        obs.append({"run_date": run_date, "from_id": key[0], "to_id": key[1], "depart_min": prev["_dep"],
                    "actual_min": float(drive), "base_min": matrix[key]})

    arrivals = [{"customer_id": r["customer_id"], "planned": t(r["planned_arrival"]), "actual": r["_arr"]}
                for r in clean if r["customer_id"] != "DEPOT" or r["planned_arrival"]]
    return {"run_date": run_date, "observations": obs, "arrivals": arrivals, "flags": flags,
            "rows": len(rows), "source_file": path.name}
