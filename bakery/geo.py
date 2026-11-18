"""Locations and the drive-time matrix.

build_matrix() tries OpenStreetMap (OSMnx) first and saves the result in data/raw/roads/
with the download date. If OSMnx fails, it falls back to straight-line km x 1.3 at 40 km/h.
The planner only ever reads the saved matrix file.
"""
import csv
import datetime as dt
import math
import sys

from . import config

DEPOT = {"customer_id": "DEPOT", "name": "Commissary kitchen (Design District)",
         "lat": 32.7935, "lon": -96.8205}


def haversine_km(a, b):
    r = 6371.0
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp = p2 - p1
    dl = math.radians(b["lon"] - a["lon"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def load_customers():
    with open(config.CUSTOMERS_FILE, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["lat"], r["lon"] = float(r["lat"]), float(r["lon"])
        r["opens_at"] = config.parse_hhmm(r["opens_at"])
        r["contract_price"] = float(r["contract_price"])
        r["km_from_depot"] = haversine_km(DEPOT, r)
    return rows


def latest_matrix_file():
    files = sorted(config.RAW_ROADS.glob("travel_matrix_*.csv"))
    return files[-1] if files else None


def load_matrix():
    """Returns ({(from_id, to_id): minutes}, source description)."""
    path = latest_matrix_file()
    if path is None:
        raise FileNotFoundError("No road matrix in data/raw/roads/. Run: python -m bakery roads")
    m, source = {}, ""
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            m[(r["from_id"], r["to_id"])] = float(r["minutes"])
            source = r["source"]
    return m, f"{path.name} ({source})"


def _osm_minutes(points):
    import osmnx as ox
    import networkx as nx
    lats = [p["lat"] for p in points]
    lons = [p["lon"] for p in points]
    pad = 0.02
    bbox = (min(lons) - pad, min(lats) - pad, max(lons) + pad, max(lats) + pad)  # left,bottom,right,top
    G = ox.graph_from_bbox(bbox, network_type="drive")
    G = ox.add_edge_speeds(G)
    G = ox.add_edge_travel_times(G)
    nodes = ox.distance.nearest_nodes(G, lons, lats)
    out = {}
    for i, a in enumerate(points):
        lengths = nx.single_source_dijkstra_path_length(G, nodes[i], weight="travel_time")
        for j, b in enumerate(points):
            if i != j:
                out[(a["customer_id"], b["customer_id"])] = lengths[nodes[j]] / 60.0
    return out


def build_matrix(force_fallback=False):
    customers = [c for c in load_customers() if c["km_from_depot"] <= config.SERVICE_RADIUS_KM]
    points = [DEPOT] + customers
    source = "OpenStreetMap via OSMnx, free-flow speeds"
    minutes = None
    if not force_fallback:
        try:
            minutes = _osm_minutes(points)
        except Exception as e:  # noqa: BLE001 - any failure means use the fallback
            print(f"OSMnx failed ({e!r}); using straight-line x {config.ROAD_FACTOR}", file=sys.stderr)
    if minutes is None:
        source = f"fallback: straight-line km x {config.ROAD_FACTOR} at {config.FALLBACK_KMH} km/h"
        minutes = {(a["customer_id"], b["customer_id"]):
                   haversine_km(a, b) * config.ROAD_FACTOR / config.FALLBACK_KMH * 60
                   for a in points for b in points if a is not b}
    config.RAW_ROADS.mkdir(parents=True, exist_ok=True)
    path = config.RAW_ROADS / f"travel_matrix_{dt.date.today().isoformat()}.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["from_id", "to_id", "minutes", "source"])
        for (a, b), v in sorted(minutes.items()):
            w.writerow([a, b, f"{v:.2f}", source])
    print(f"Wrote {path} ({len(minutes)} legs, {source})")
    return path
