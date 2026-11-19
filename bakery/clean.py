"""Step 1 of /plan-run: clean and check one raw order sheet.

Rules are numbered as in decisions.md (C1..C11). The raw file is never modified;
the cleaned result goes to output/clean/<delivery-date>.json.

Notes are DATA. Nothing written in the notes field can change a quantity, price,
acceptance or the workflow (rule C10).
"""
import csv
import datetime as dt
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from . import config, geo

REQUIRED = ["order_id", "customer", "wanted_by", "item", "quantity", "agreed_price", "submitted_at"]
WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "half": 0.5}
INSTRUCTION_RE = re.compile(
    r"ignore|instruction|system|\bai\b|agent|approve|push|skip|you are|assistant|prompt|override",
    re.IGNORECASE)


DATETIME_FORMATS = ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S",
                    "%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M", "%m/%d/%y %I:%M %p", "%m/%d/%y %H:%M"]


def parse_submitted(text):
    """Submission timestamp in ISO or US format (rule C5, revised 2026-11-18 after eval case E6). None if unreadable."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    for fmt in DATETIME_FORMATS:
        try:
            return dt.datetime.strptime(t, fmt)
        except ValueError:
            pass
    return None


class CleaningError(Exception):
    """A check failed: the workflow must stop and show this message."""


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", (name or "").lower())).strip()


def parse_quantity(text: str):
    """'24' -> 24, '2 dozen' -> 24, 'two dozen' -> 24, '1.5 dozen' -> 18, '18 pcs' -> 18. None if unreadable."""
    t = (text or "").strip().lower().replace(",", "")
    if re.fullmatch(r"-?\d+", t):
        return int(t)
    m = re.fullmatch(r"(\d+(?:\.\d+)?|[a-z]+)\s*(dozen|doz|dz)", t)
    if m:
        n = m.group(1)
        n = float(n) if n[0].isdigit() else WORDS.get(n)
        return None if n is None else int(round(n * 12))
    m = re.fullmatch(r"(\d+)\s*(pcs|pc|pieces|piece|ea)", t)
    if m:
        return int(m.group(1))
    return None


def delivery_date_for(path: Path, rows) -> dt.date:
    m = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
    if m:
        return dt.date.fromisoformat(m.group(1))
    days = defaultdict(int)
    for r in rows:
        sub = parse_submitted(r["submitted_at"])
        if sub:
            days[sub.date()] += 1
    if not days:
        raise CleaningError("Cannot tell which morning this order sheet is for: the file name has no "
                            "date (orders_YYYY-MM-DD.csv) and no submitted_at dates are readable.")
    return max(days, key=days.get) + dt.timedelta(days=1)


def clean_file(path) -> dict:
    path = Path(path)
    if not path.exists():
        raise CleaningError(f"Order file not found: {path}")
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        header = [h.strip() for h in (reader.fieldnames or [])]
        rows = [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in reader]
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        raise CleaningError(f"{path.name} is missing required column(s): {', '.join(missing)}. "
                            f"Expected: {', '.join(REQUIRED)} (+ address, notes).")
    if not rows:
        raise CleaningError(f"{path.name} has a header but no orders.")

    day = delivery_date_for(path, rows)
    cutoff = dt.datetime.combine(day - dt.timedelta(days=1), dt.time(config.CUTOFF_HOUR, 0))
    customers = {norm(c["name"]): c for c in geo.load_customers()}
    flags, declined = [], []

    def flag(order_id, customer, rule, text):
        flags.append({"order_id": order_id, "customer": customer, "rule": rule, "text": text})

    # C10 notes: flag, never act on
    for r in rows:
        if r.get("notes") and INSTRUCTION_RE.search(r["notes"]):
            flag(r["order_id"], r["customer"], "C10",
                 "Note looks like instructions to the software. Ignored; only Rosa changes orders.")

    # group lines by order_id
    orders = defaultdict(list)
    for r in rows:
        orders[r["order_id"] or f"(no id) {r['customer']}"].append(r)

    by_customer = defaultdict(list)
    for oid, lines in orders.items():
        first = lines[0]
        c = customers.get(norm(first["customer"]))
        sub = parse_submitted(first["submitted_at"])
        if c is None:  # C3
            declined.append({"order_id": oid, "customer": first["customer"], "rule": "C3",
                             "reason": "Not on the customer list (no address on file). Call them before adding."})
            continue
        if c["km_from_depot"] > config.SERVICE_RADIUS_KM:  # C4
            declined.append({"order_id": oid, "customer": c["name"], "rule": "C4",
                             "reason": f"Outside the service area ({c['km_from_depot']:.0f} km from the kitchen; "
                                       f"limit {config.SERVICE_RADIUS_KM:.0f} km)."})
            continue
        if sub is None:  # C5: unreadable is not the same as late - say so
            declined.append({"order_id": oid, "customer": c["name"], "rule": "C5",
                             "reason": f"Submission time '{first['submitted_at']}' is unreadable, so we can't "
                                       f"tell if it beat the 9 PM cutoff. Check with the customer."})
            continue
        if sub > cutoff:  # C5
            what = ", ".join(f"{ln['quantity']} {ln['item']}" for ln in lines)
            declined.append({"order_id": oid, "customer": c["name"], "rule": "C5", "customer_id": c["customer_id"],
                             "reason": f"Order {oid} ({what}) was submitted at "
                                       f"{sub.strftime('%I:%M %p').lstrip('0')}, after the 9 PM cutoff."})
            continue
        by_customer[c["customer_id"]].append((sub, oid, lines, c))

    accepted = []
    for cid, subs in by_customer.items():
        subs.sort(key=lambda s: (s[0], s[1]))
        for sub, oid, _, c in subs[:-1]:  # C6 latest on-time submission replaces earlier ones
            declined.append({"order_id": oid, "customer": c["name"], "rule": "C6", "customer_id": c["customer_id"],
                             "reason": f"Replaced by a later submission ({subs[-1][1]})."})  # customer_id: C5c below
        sub, oid, lines, c = subs[-1]
        out_lines = []
        for ln in lines:
            q = parse_quantity(ln["quantity"])  # C7
            if q is None or q <= 0 or q > config.OVENS["large"][0]:
                flag(oid, c["name"], "C7", f"Quantity '{ln['quantity']}' for {ln['item']} is unreadable or "
                     f"implausible (allowed 1-96). Line left out; call the customer.")
                continue
            if not ln["quantity"].isdigit():
                flag(oid, c["name"], "C7", f"Quantity '{ln['quantity']}' read as {q}.")
            try:
                price = float(ln["agreed_price"].replace("$", ""))
            except ValueError:
                price = 0.0
            if not 1.0 <= price <= 6.0:  # C9
                flag(oid, c["name"], "C9", f"Price '{ln['agreed_price']}' replaced with contract price "
                     f"${c['contract_price']:.2f}.")
                price = c["contract_price"]
            out_lines.append({"item": ln["item"], "qty": q, "price": round(price, 2)})
        if not out_lines:
            declined.append({"order_id": oid, "customer": c["name"], "rule": "C7",
                             "reason": "No readable lines left after cleaning."})
            continue
        wanted = None
        try:
            wanted = config.parse_hhmm(lines[0]["wanted_by"])
        except (ValueError, IndexError):
            wanted = None
        if wanted is None:  # C8
            wanted = c["opens_at"]
            flag(oid, c["name"], "C8", f"No wanted-by time. Assumed opening time {config.hhmm(wanted)}.")
        elif wanted < c["opens_at"]:
            flag(oid, c["name"], "C8", f"Wanted by {config.hhmm(wanted)} is before the cafe opens; "
                 f"using opening time {config.hhmm(c['opens_at'])}.")
            wanted = c["opens_at"]
        accepted.append({
            "order_id": oid, "customer_id": c["customer_id"], "customer": c["name"],
            "opens_at": c["opens_at"], "wanted_by": wanted, "lines": out_lines,
            "submitted_at": sub.isoformat(sep=" ", timespec="minutes"),
            "pieces": sum(x["qty"] for x in out_lines),
            "revenue_full": round(sum(x["qty"] * x["price"] for x in out_lines), 2),
        })

    # C5c (2026-11-18, found in the first live /plan-run): if the same customer still has an on-time
    # order on the sheet, say so - "say no to Uptown" must not read as "Uptown is off the route".
    on_route = {o["customer_id"]: o for o in accepted}
    for d in declined:
        o = on_route.get(d.pop("customer_id", None))
        if o and d["rule"] in ("C5", "C6"):
            d["reason"] += (f" Only this order is declined: their order {o['order_id']} "
                            f"({o['pieces']} pcs) is still on the route.")
    result = {"delivery_date": day.isoformat(), "source_file": path.name,
              "raw_rows": len(rows), "orders": sorted(accepted, key=lambda o: o["customer_id"]),
              "declined_at_cleaning": declined, "flags": flags}
    check_clean(result)
    return result


def check_clean(result):
    """Data checks after cleaning. Any failure stops the workflow (exit code 2)."""
    orders = result["orders"]
    if not orders:
        reasons = sorted({d["rule"] for d in result["declined_at_cleaning"]})
        raise CleaningError("No orders survived cleaning, so there is nothing to plan. "
                            f"Rules that declined them: {', '.join(reasons) or 'none'}. "
                            "Check the file and the messages above.")
    ids = [o["customer_id"] for o in orders]
    if len(ids) != len(set(ids)):
        raise CleaningError("Check failed: more than one accepted order for the same customer.")
    for o in orders:
        if not (5 * 60 <= o["wanted_by"] <= 11 * 60):
            raise CleaningError(f"Check failed: {o['customer']} wanted-by {config.hhmm(o['wanted_by'])} "
                                f"is outside 5:00-11:00.")
        if not all(1 <= ln["qty"] <= 96 and 1 <= ln["price"] <= 6 for ln in o["lines"]):
            raise CleaningError(f"Check failed: {o['customer']} has a quantity or price out of range.")


def main(path):
    started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")  # G4: planning-time clock starts here
    try:
        result = clean_file(path)
    except CleaningError as e:
        print(f"STOPPED at cleaning: {e}", file=sys.stderr)
        sys.exit(2)
    result["cleaned_at"] = started
    config.CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    out = config.CLEAN_DIR / f"{result['delivery_date']}.json"
    out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(f"Cleaned {result['source_file']}: {result['raw_rows']} rows -> {len(result['orders'])} orders "
          f"to plan, {len(result['declined_at_cleaning'])} declined at cleaning, {len(result['flags'])} flags")
    for d in result["declined_at_cleaning"]:
        print(f"  declined [{d['rule']}] {d['customer']}: {d['reason']}")
    for fl in result["flags"]:
        print(f"  flag     [{fl['rule']}] {fl['customer']}: {fl['text']}")
    print(f"-> {out}")
    return out
