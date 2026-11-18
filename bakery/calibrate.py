"""Drive-time estimate that learns from delivery logs.

estimate(from, to, t) = OSM minutes x bucket factor(t) x leg adjustment
  bucket factor   median of (actual / OSM minutes) over every observed leg that left in the same
                  30-minute window; 1.0 until we have observations (that is the "before" state).
  leg adjustment  how much slower this particular leg runs than the bucket says (school zones),
                  trusted n/(n+3) after n observations of that leg in that window.
Observations come from the drive_observations table (see db.py), only from mornings BEFORE the
delivery date being planned, so a plan never peeks at its own future.
"""
from collections import defaultdict
from statistics import median

from . import config, geo


def bucket(minute: float) -> int:
    return int(minute // config.BUCKET_MIN) * config.BUCKET_MIN


class DriveModel:
    def __init__(self, observations=(), matrix=None):
        self.matrix, self.matrix_source = matrix if matrix else geo.load_matrix()
        ratios = defaultdict(list)
        legs = defaultdict(list)
        for ob in observations:
            if ob["base_min"] <= 0:
                continue
            r = ob["actual_min"] / ob["base_min"]
            b = bucket(ob["depart_min"])
            ratios[b].append(r)
            legs[(ob["from_id"], ob["to_id"], b)].append(r)
        self.factor = {b: median(v) for b, v in ratios.items()}
        self.counts = {b: len(v) for b, v in ratios.items()}
        self.leg_adj = {}
        for (a, c, b), v in legs.items():
            raw = median(v) / self.factor[b]
            w = len(v) / (len(v) + config.LEG_SHRINK_N)
            self.leg_adj[(a, c, b)] = 1.0 + w * (raw - 1.0)
        self.n_obs = sum(self.counts.values())

    def bucket_factor(self, t):
        if not self.factor:
            return 1.0
        b = bucket(t)
        if b in self.factor:
            return self.factor[b]
        nearest = min(self.factor, key=lambda k: abs(k - b))
        return self.factor[nearest]

    def base(self, a, c):
        return self.matrix[(a, c)]

    def __call__(self, a, c, t):
        b = bucket(t)
        return self.base(a, c) * self.bucket_factor(t) * self.leg_adj.get((a, c, b), 1.0)

    def summary(self):
        return [{"window": config.hhmm(b), "factor": round(self.factor[b], 3), "legs_seen": self.counts[b]}
                for b in sorted(self.factor)]


def base_only(matrix=None):
    """Drive model with no learning: OSM minutes as-is (what a route app assumes)."""
    return DriveModel([], matrix)
