"""Stand-in for the real morning: drive the approved plan through the simulated world (truth.py)
and write the van's delivery log to data/raw/logs/log_<date>.csv.

Rosa follows the planned tray load times exactly; the van waits if a tray is not ready
or a cafe is not open. The log has built-in mess (decisions.md L-rules): GPS gaps, a device
clock that jumps one hour, duplicated rows.
"""
import csv
import random

from . import config, truth
from .model import execute

LOG_FIELDS = ["run_date", "stop_seq", "customer_id", "customer", "planned_arrival", "actual_arrival",
              "actual_departure", "pieces_delivered", "status", "gps"]


def true_drive_fn(matrix, date_iso):
    def drive(a, c, t):
        rng = random.Random(f"{date_iso}|{a}|{c}|{int(t // 30)}")
        return truth.true_drive(matrix[(a, c)], t, a, c, rng)
    return drive


def run_actual(plan, orders, matrix, date_iso, prices):
    return execute(plan, orders, true_drive_fn(matrix, date_iso), prices, loads=plan["loads"])


def write_log(date_iso, planned, actual, names, path=None):
    rng = random.Random(f"log-{date_iso}")
    path = path or config.RAW_LOGS / f"log_{date_iso}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    skew_from = rng.randint(2, max(2, len(actual["stops"]))) if rng.random() < 0.12 else None
    rows = [{"run_date": date_iso, "stop_seq": 0, "customer_id": "DEPOT", "customer": "Kitchen",
             "planned_arrival": "", "actual_arrival": "", "actual_departure": config.hhmm(actual["stops"][0]["depart_prev"]),
             "pieces_delivered": 0, "status": "left kitchen", "gps": "ok"}]
    for i, (p, a) in enumerate(zip(planned["stops"], actual["stops"]), start=1):
        dep = a["deliver"] + config.STOP_MIN
        arr, gps = a["curb"], "ok"
        if skew_from and i >= skew_from:
            arr, dep, gps = arr + 60, dep + 60, "ok"
        row = {"run_date": date_iso, "stop_seq": i, "customer_id": a["customer_id"], "customer": names[a["customer_id"]],
               "planned_arrival": config.hhmm(p["curb"]), "actual_arrival": config.hhmm(arr),
               "actual_departure": config.hhmm(dep), "pieces_delivered": a["pieces"] - a["refused"],
               "status": "refused - pantry" if a["refused"] else "delivered", "gps": gps}
        if rng.random() < 0.06:
            row.update(actual_arrival="", actual_departure="", gps="no signal")
        rows.append(row)
        if rng.random() < 0.03:
            rows.append(dict(row))
    rows.append({"run_date": date_iso, "stop_seq": len(actual["stops"]) + 1, "customer_id": "DEPOT",
                 "customer": "Kitchen", "planned_arrival": config.hhmm(planned["back_at"]),
                 "actual_arrival": config.hhmm(actual["back_at"] + (60 if skew_from else 0)),
                 "actual_departure": "", "pieces_delivered": 0, "status": "back at kitchen", "gps": "ok"})
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return path
