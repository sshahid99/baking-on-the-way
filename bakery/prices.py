"""BLS average prices: fetch (outside connection) and look up the month a plan should use.

Fetch: python -m bakery prices  -> data/raw/prices/bls_prices_<today>.csv
  Public BLS API v2, read-only GET/POST, no API key, no account. Nothing is ever sent but the
  three public series ids and a year range.
Lookup rule (decisions.md P1): BLS publishes month M around the 15th of month M+1, so a plan for
  date D uses the newest month already published by D. A missing month carries the last value
  forward and is flagged (P2).
"""
import csv
import datetime as dt
import json

from . import config

API = "https://api.bls.gov/publicAPI/v2/timeseries/data/"


def fetch(start_year=2025, end_year=None):
    import requests
    end_year = end_year or dt.date.today().year
    body = {"seriesid": list(config.RECIPE), "startyear": str(start_year), "endyear": str(end_year)}
    r = requests.post(API, json=body, timeout=60, headers={"User-Agent": "course-project-bakery-planner"})
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS API said: {data.get('status')} {data.get('message')}")
    config.RAW_PRICES.mkdir(parents=True, exist_ok=True)
    path = config.RAW_PRICES / f"bls_prices_{dt.date.today().isoformat()}.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["series_id", "year", "month", "value"])
        for s in data["Results"]["series"]:
            for p in s["data"]:
                if p["period"].startswith("M") and p["period"] != "M13":
                    w.writerow([s["seriesID"], p["year"], int(p["period"][1:]), p["value"]])
    print(f"Wrote {path}")
    return path


def load_all():
    files = sorted(config.RAW_PRICES.glob("bls_prices_*.csv"))
    if not files:
        raise FileNotFoundError("No BLS price file in data/raw/prices/. Run: python -m bakery prices")
    out = {}
    with open(files[-1], newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                v = float(r["value"])
            except ValueError:  # BLS uses '-' for unavailable
                continue
            out[(r["series_id"], int(r["year"]), int(r["month"]))] = v
    return out, files[-1].name


def published_month(day: dt.date):
    y, m = day.year, day.month - 1
    if day.day < 15:
        m -= 1
    while m < 1:
        m += 12
        y -= 1
    return y, m


def prices_for(day: dt.date, table=None):
    """Returns ({series: $}, {series: 'YYYY-MM'}, [flags])."""
    table = table or load_all()[0]
    y, m = published_month(day)
    prices, months, flags = {}, {}, []
    for s in config.RECIPE:
        yy, mm, tries = y, m, 0
        while (s, yy, mm) not in table and tries < 24:
            mm -= 1
            tries += 1
            if mm < 1:
                mm, yy = 12, yy - 1
        if (s, yy, mm) not in table:
            raise RuntimeError(f"No BLS price at all for {s} in the 24 months before {day}")
        prices[s], months[s] = table[(s, yy, mm)], f"{yy}-{mm:02d}"
        if (yy, mm) != (y, m):
            flags.append(f"{config.PRICE_SERIES_NAMES[s]}: {y}-{m:02d} missing, carried forward {yy}-{mm:02d}")
    return prices, months, flags


if __name__ == "__main__":
    print(json.dumps(prices_for(dt.date.today()), indent=1))
