"""The simulated real world. ONLY generate.py and simulate.py may import this module.

The planner never sees these factors. It has to learn them from delivery logs,
which is the point of the recalibration step. tests/test_plan_rules.py checks the import rule.

Built-in patterns (all invented, recorded in decisions.md):
  * OSM free-flow speeds are optimistic: real legs take about 12% longer (traffic lights, parking).
  * Morning rush ramps from 6:30 and peaks 7:30-9:00 at about x1.30.
  * Legs touching a stop near a school slow another x1.30 between 7:15 and 8:15.
  * Each leg each morning has random noise (lognormal, sigma 0.08).
"""
import math
import random

SCHOOL_STOPS = {"C04", "C05", "C12", "C02"}  # Lower Greenville, Lakewood, M Streets, Bishop Arts


def true_factor(depart_min: float, from_id: str, to_id: str) -> float:
    f = 1.12
    t = depart_min
    if t >= 390:  # 6:30
        f *= 1.0 + 0.30 * min(1.0, (t - 390) / 60.0)
    if 435 <= t < 495 and (from_id in SCHOOL_STOPS or to_id in SCHOOL_STOPS):
        f *= 1.30
    return f


def true_drive(base_min: float, depart_min: float, from_id: str, to_id: str, rng: random.Random) -> float:
    noise = math.exp(rng.gauss(0.0, 0.08))
    return base_min * true_factor(depart_min, from_id, to_id) * noise


def is_rainy(date_iso: str, seed: int = 4336) -> bool:
    return random.Random(f"rain-{seed}-{date_iso}").random() < 0.2
