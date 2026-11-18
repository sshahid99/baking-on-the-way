"""Business assumptions and paths. Every number here is also recorded in decisions.md.

Times are minutes after midnight (5:35 AM = 335) everywhere inside the code.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
RAW_ORDERS = RAW / "orders"
RAW_LOGS = RAW / "logs"
RAW_ROADS = RAW / "roads"
RAW_PRICES = RAW / "prices"
CUSTOMERS_FILE = RAW / "customers.csv"
OUTPUT = ROOT / "output"
CLEAN_DIR = OUTPUT / "clean"
PLAN_DIR = OUTPUT / "plans"
SITE_DATA = ROOT / "docs" / "data"
RUNS_DIR = ROOT / "work" / "runs"

# --- The van and the oven (proposal section 5, fictional) ---
VAN_RATE_PER_HOUR = 38.0
TRAY_PIECES = 12  # one tray = 12 kolaches; an order of 30 is trays of 12, 12, 6
OVENS = {  # name: (pieces in the oven at the same time, rental $/hour)
    "small": (24, 30.0),
    "medium": (48, 45.0),
    "large": (96, 70.0),
}
BAKE_MIN = 18          # every tray bakes the full 18 minutes
STOP_MIN = 8           # minutes spent at each stop
UNLOAD_BUFFER_MIN = 1  # tray comes out of the oven at least 1 minute before arrival
EARLIEST_START = 4 * 60 + 45  # Rosa approves at 4:30; first tray no earlier than 4:45
BASE_PRICE = 2.75
OLD_RULE_MAX_STOPS = 8  # Rosa's rule today: first come, first served, up to 8 stops

# --- Freshness contract: minutes since the tray left the oven -> share of price paid ---
FRESHNESS_TIERS = [(15, 1.0), (30, 0.8), (45, 0.6)]  # < 15 min full, < 30 -> 20% off, < 45 -> 40% off
# > 45 minutes: cafe may refuse, tray goes to the food pantry (revenue 0, ingredients lost)

# --- Lateness (decision 2026-11-18): up to 15 min after wanted-by allowed, extra 20% off ---
LATE_GRACE_MIN = 15
LATE_DISCOUNT = 0.20   # subtracted from the freshness share (full -> 0.8, 20% off -> 0.6 ...)

# --- Ordering rules ---
CUTOFF_HOUR = 21  # 9 PM the night before; strict (decision 2026-11-18)
SERVICE_RADIUS_KM = 12.0

# --- Ingredients per kolache (assumption, decisions.md) ---
RECIPE = {  # BLS series: (quantity per kolache, unit of the BLS price)
    "APU0000701111": 0.06,       # flour, lb  (BLS price is $/lb)
    "APU0000708111": 0.10 / 12,  # eggs, dozen (0.1 egg per piece)
    "APU0000FS1101": 0.03,       # butter, lb
}
OTHER_COST_PER_PIECE = 0.35  # filling, sugar, yeast, paper: not in BLS, fixed assumption
PRICE_SERIES_NAMES = {
    "APU0000701111": "Flour, white, all purpose ($/lb)",
    "APU0000708111": "Eggs, grade A, large ($/dozen)",
    "APU0000FS1101": "Butter, salted, grade AA, stick ($/lb)",
}

# --- Optimizer loop stop condition (proposal section 4) ---
MIN_ROUND_GAIN = 1.0
MAX_ROUNDS = 20

# --- Drive-time learning ---
BUCKET_MIN = 30      # calibration factor per 30-minute departure bucket
LEG_SHRINK_N = 3     # per-leg adjustment trusted at n/(n+3)
ROAD_FACTOR = 1.3    # fallback: straight-line km x 1.3
FALLBACK_KMH = 40.0  # fallback speed when OSM is unavailable


def hhmm(minutes: float | int | None) -> str:
    if minutes is None:
        return ""
    m = int(round(minutes))
    return f"{m // 60}:{m % 60:02d}"


def parse_hhmm(text: str) -> int | None:
    """'6:45', '06:45', '6:45 AM', '7:45 PM', '2026-10-05 20:41' -> minutes after midnight.
    Raises ValueError if it is not a time (callers decide what that means)."""
    import re
    text = (text or "").strip().upper()
    if not text:
        return None
    m = re.search(r"(\d{1,2}):(\d{2})(?::\d{2})?\s*(AM|PM)?$", text)
    if not m:
        raise ValueError(f"not a time: {text!r}")
    h, mi, ampm = int(m.group(1)), int(m.group(2)), m.group(3)
    if ampm == "PM" and h != 12:
        h += 12
    if ampm == "AM" and h == 12:
        h = 0
    if h > 23 or mi > 59:
        raise ValueError(f"not a time: {text!r}")
    return h * 60 + mi
