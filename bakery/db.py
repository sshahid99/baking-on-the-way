"""The database: one schema, two homes (decision D1, 2026-11-18).

* DATABASE_URL set (in .env, never committed) -> cloud MySQL (Aiven free tier), e.g.
      DATABASE_URL=mysql://avnadmin:PASSWORD@HOST:PORT/defaultdb?ssl-mode=REQUIRED
      DB_SSL_CA=path/to/aiven-ca.pem          (optional; verifies the server certificate)
* not set -> SQLite file output/bakery.db, so CI and a fresh copy of the repo still run.

Every store is idempotent: re-running a date replaces that date's rows.
"""
import json
import os
from datetime import datetime, timezone

from sqlalchemy import (Column, Float, Integer, MetaData, String, Table, Text, create_engine,
                        delete, insert, inspect, select, text)

from . import config

meta = MetaData()

customers = Table("customers", meta,
    Column("customer_id", String(16), primary_key=True), Column("name", String(120)),
    Column("address", String(200)), Column("lat", Float), Column("lon", Float),
    Column("opens_at", Integer), Column("contract_price", Float), Column("type", String(16)))

orders = Table("orders", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("delivery_date", String(10), index=True), Column("order_id", String(32)),
    Column("customer_id", String(16)), Column("customer", String(120)), Column("wanted_by", Integer),
    Column("pieces", Integer), Column("revenue_full", Float),
    Column("status", String(16)),  # accepted | declined_cleaning | declined_planner
    Column("reason", String(300)))

flags = Table("flags", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("delivery_date", String(10), index=True), Column("source", String(16)),
    Column("rule", String(8)), Column("customer", String(120)), Column("text", String(400)))

runs = Table("runs", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("delivery_date", String(10), index=True), Column("planner", String(16)),  # planner | old_rule
    Column("status", String(16)),  # planned | approved | done
    Column("oven", String(8)), Column("leave_min", Float), Column("shift_start", Float),
    Column("back_at", Float), Column("expected_profit", Float), Column("expected_fresh", Float),
    Column("expected_revenue", Float), Column("van_cost", Float), Column("oven_cost", Float),
    Column("ingredient_cost", Float), Column("pieces", Integer),
    Column("actual_profit", Float), Column("actual_fresh", Float), Column("actual_back_at", Float),
    Column("refused_pieces", Integer), Column("median_gap_min", Float),
    Column("rounds", Integer), Column("per_oven_json", Text), Column("bls_months", String(80)),
    Column("drive_source", String(200)), Column("created_at", String(32)),
    # Planning time (decision G4, 2026-11-19): clock starts when `clean` starts, stops at Rosa's `approve`.
    Column("cleaned_at", String(32)), Column("approved_at", String(32)))

# Columns added after the first release: create_all() does not add columns to an existing table.
_ADDED_COLUMNS = {"runs": ["cleaned_at", "approved_at"]}

stops = Table("stops", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", Integer, index=True), Column("seq", Integer), Column("customer_id", String(16)),
    Column("planned_curb", Float), Column("planned_deliver", Float), Column("wanted_by", Integer),
    Column("pieces", Integer), Column("expected_revenue", Float), Column("expected_fresh", Integer),
    Column("actual_curb", Float), Column("actual_deliver", Float), Column("actual_revenue", Float),
    Column("actual_fresh", Integer), Column("refused", Integer), Column("ages_json", Text))

tray_loads = Table("tray_loads", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", Integer, index=True), Column("tray_no", Integer), Column("load_min", Float),
    Column("out_min", Float), Column("pieces_json", Text))

drive_observations = Table("drive_observations", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_date", String(10), index=True), Column("from_id", String(16)), Column("to_id", String(16)),
    Column("depart_min", Float), Column("actual_min", Float), Column("base_min", Float))

arrival_gaps = Table("arrival_gaps", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_date", String(10), index=True), Column("customer_id", String(16)),
    Column("planned", Float), Column("actual", Float))

ingredient_prices = Table("ingredient_prices", meta,
    Column("series_id", String(16), primary_key=True), Column("year", Integer, primary_key=True),
    Column("month", Integer, primary_key=True), Column("value", Float))

optimizer_rounds = Table("optimizer_rounds", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("delivery_date", String(10), index=True), Column("oven", String(8)), Column("round", Integer),
    Column("move", String(120)), Column("gain", Float), Column("profit", Float), Column("stop", String(60)))


def _load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv(config.ROOT / ".env")
    except ImportError:
        pass


_engine = None


def engine():
    global _engine
    if _engine is None:
        _load_env()
        url = os.environ.get("DATABASE_URL", "").strip()
        if url:
            url = url.replace("mysql://", "mysql+pymysql://", 1).split("?")[0]
            ssl = {"ca": os.environ["DB_SSL_CA"]} if os.environ.get("DB_SSL_CA") else {"check_hostname": False}
            _engine = create_engine(url, connect_args={"ssl": ssl}, pool_pre_ping=True)
        else:
            config.OUTPUT.mkdir(parents=True, exist_ok=True)
            path = os.environ.get("BAKERY_SQLITE") or str(config.OUTPUT / "bakery.db")  # evaluate.py uses a temp file
            _engine = create_engine(f"sqlite:///{path}")
        meta.create_all(_engine)
        _add_missing_columns(_engine)
    return _engine


def _add_missing_columns(e):
    insp = inspect(e)
    for table, cols in _ADDED_COLUMNS.items():
        have = {c["name"] for c in insp.get_columns(table)}
        for col in cols:
            if col not in have:
                with e.begin() as c:
                    c.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} VARCHAR(32)"))


def where():
    e = engine()
    return "cloud MySQL" if e.dialect.name == "mysql" else f"local SQLite ({config.OUTPUT.name}/bakery.db)"


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def store_customers(rows):
    with engine().begin() as c:
        c.execute(delete(customers))
        c.execute(insert(customers), [{k: r[k] for k in ("customer_id", "name", "address", "lat", "lon",
                                       "opens_at", "contract_price", "type")} for r in rows])


def store_prices(table):
    with engine().begin() as c:
        c.execute(delete(ingredient_prices))
        c.execute(insert(ingredient_prices), [{"series_id": s, "year": y, "month": m, "value": v}
                                              for (s, y, m), v in table.items()])


def store_observations(log):
    with engine().begin() as c:
        c.execute(delete(drive_observations).where(drive_observations.c.run_date == log["run_date"]))
        c.execute(delete(arrival_gaps).where(arrival_gaps.c.run_date == log["run_date"]))
        c.execute(delete(flags).where((flags.c.delivery_date == log["run_date"]) & (flags.c.source == "log")))
        if log["observations"]:
            c.execute(insert(drive_observations), log["observations"])
        gaps = [dict(run_date=log["run_date"], **a) for a in log["arrivals"] if a["planned"] is not None]
        if gaps:
            c.execute(insert(arrival_gaps), gaps)
        if log["flags"]:
            c.execute(insert(flags), [{"delivery_date": log["run_date"], "source": "log", "rule": "L",
                                       "customer": "", "text": f} for f in log["flags"]])


def observations_before(day_iso):
    with engine().connect() as c:
        rows = c.execute(select(drive_observations).where(drive_observations.c.run_date < day_iso)).mappings()
        return [dict(r) for r in rows]


def save_run(day, planner, plan, res, extra):
    """Replace the run for (day, planner) with this plan. Returns run id."""
    with engine().begin() as c:
        old = [r.id for r in c.execute(select(runs.c.id).where(
            (runs.c.delivery_date == day) & (runs.c.planner == planner)))]
        for rid in old:
            c.execute(delete(stops).where(stops.c.run_id == rid))
            c.execute(delete(tray_loads).where(tray_loads.c.run_id == rid))
            c.execute(delete(runs).where(runs.c.id == rid))
        rid = c.execute(insert(runs).values(
            delivery_date=day, planner=planner, status=extra.get("status", "planned"), oven=plan["oven"],
            leave_min=plan["leave"], shift_start=res["shift_start"], back_at=res["back_at"],
            expected_profit=res["profit"], expected_fresh=res["fresh_share"], expected_revenue=res["revenue"],
            van_cost=res["van_cost"], oven_cost=res["oven_cost"], ingredient_cost=res["ingredient_cost"],
            pieces=res["pieces"], rounds=extra.get("rounds"), per_oven_json=json.dumps(extra.get("per_oven", {})),
            bls_months=extra.get("bls_months", ""), drive_source=extra.get("drive_source", ""),
            created_at=now(), cleaned_at=extra.get("cleaned_at"))).inserted_primary_key[0]
        c.execute(insert(stops), [{
            "run_id": rid, "seq": i + 1, "customer_id": s["customer_id"], "planned_curb": s["curb"],
            "planned_deliver": s["deliver"], "wanted_by": extra["wanted"][s["customer_id"]], "pieces": s["pieces"],
            "expected_revenue": s["revenue"], "expected_fresh": s["fresh"], "ages_json": json.dumps(s["ages"])}
            for i, s in enumerate(res["stops"])])
        if res["trays"]:
            c.execute(insert(tray_loads), [{"run_id": rid, "tray_no": t["n"], "load_min": t["start"],
                                            "out_min": t["end"], "pieces_json": json.dumps({t["customer_id"]: t["pieces"]})}
                                           for t in res["trays"]])
        return rid


def save_actual(day, planner, actual, median_gap=None):
    with engine().begin() as c:
        rid = c.execute(select(runs.c.id).where((runs.c.delivery_date == day) & (runs.c.planner == planner))).scalar()
        if rid is None:
            raise LookupError(f"No {planner} run stored for {day}")
        c.execute(runs.update().where(runs.c.id == rid).values(
            status="done", actual_profit=actual["profit"], actual_fresh=actual["fresh_share"],
            actual_back_at=actual["back_at"], refused_pieces=actual["refused_pieces"], median_gap_min=median_gap))
        for i, s in enumerate(actual["stops"]):
            c.execute(stops.update().where((stops.c.run_id == rid) & (stops.c.seq == i + 1)).values(
                actual_curb=s["curb"], actual_deliver=s["deliver"], actual_revenue=s["revenue"],
                actual_fresh=s["fresh"], refused=s["refused"]))


def save_orders_and_flags(clean, plan_declined, rounds_log):
    day = clean["delivery_date"]
    with engine().begin() as c:
        for t in (orders, optimizer_rounds):
            c.execute(delete(t).where(t.c.delivery_date == day))
        c.execute(delete(flags).where((flags.c.delivery_date == day) & (flags.c.source != "log")))
        rows = []
        for o in clean["orders"]:
            dec = plan_declined.get(o["customer_id"])
            rows.append({"delivery_date": day, "order_id": o["order_id"], "customer_id": o["customer_id"],
                         "customer": o["customer"], "wanted_by": o["wanted_by"], "pieces": o["pieces"],
                         "revenue_full": o["revenue_full"], "status": "declined_planner" if dec else "accepted",
                         "reason": dec or ""})
        for d in clean["declined_at_cleaning"]:
            rows.append({"delivery_date": day, "order_id": d["order_id"], "customer_id": "",
                         "customer": d["customer"], "wanted_by": None, "pieces": None, "revenue_full": None,
                         "status": "declined_cleaning", "reason": f"[{d['rule']}] {d['reason']}"})
        c.execute(insert(orders), rows)
        fl = [{"delivery_date": day, "source": "orders", "rule": f["rule"], "customer": f["customer"],
               "text": f["text"][:400]} for f in clean["flags"]]
        fl += [{"delivery_date": day, "source": "prices", "rule": "P2", "customer": "", "text": t}
               for t in clean.get("price_flags", [])]
        if fl:
            c.execute(insert(flags), fl)
        if rounds_log:
            c.execute(insert(optimizer_rounds), [dict(delivery_date=day, stop=r.get("stop"), **{
                k: r[k] for k in ("oven", "round", "move", "gain", "profit")}) for r in rounds_log])


def run_status(day, planner="planner"):
    with engine().connect() as c:
        return c.execute(select(runs.c.status).where((runs.c.delivery_date == day) & (runs.c.planner == planner))).scalar()


def set_status(day, status):
    """Never downgrades a morning that already happened ('done')."""
    with engine().begin() as c:
        c.execute(runs.update().where((runs.c.delivery_date == day) & (runs.c.planner == "planner")
                                      & (runs.c.status != "done")).values(status=status))


def mark_approved_by_rosa(day):
    """`python -m bakery approve`: status approved + the time she approved (G4). Backfill does not call
    this, so only real approvals are timed. Returns minutes from cleaning to approval, or None."""
    stamp = now()
    with engine().begin() as c:
        c.execute(runs.update().where((runs.c.delivery_date == day) & (runs.c.planner == "planner")
                                      & (runs.c.status != "done")).values(status="approved", approved_at=stamp))
        start = c.execute(select(runs.c.cleaned_at).where(
            (runs.c.delivery_date == day) & (runs.c.planner == "planner"))).scalar()
    if not start:
        return None
    return (datetime.fromisoformat(stamp) - datetime.fromisoformat(start)).total_seconds() / 60
