# Figures checked by hand (course requirement: at least two)

Do these with a calculator and the files named, then fill in who checked and the result.

## H-1: one stop's revenue (plan for 2026-11-09)
From `output/plans/2026-11-09/plan.json`, pick one stop (for example the one in `route[0]`).
1. Tray end times: the `trays` with that `customer_id` (`end` = load minute + 18).
2. Delivery minute = max(leave + leg minutes from `legs`, the café's `opens_at`, last tray end + 1).
3. Tray age = delivery − tray end. Price share: < 15 → 1.0, < 30 → 0.8, ≤ 45 → 0.6 (decisions.md M4);
   if delivery > wanted_by, subtract 0.2 (M5).
4. Revenue = pieces × agreed price × share. Compare with the dashboard's stop revenue.

| checked by | date | stop | my number | system's number | match? |
|---|---|---|---|---|---|
| | | | | | |

## H-2: one morning's costs (same plan)
Hours = (`claimed.back_at` − `claimed.shift_start`) / 60. Van = hours × $38. Oven = hours × the rate
for `oven` ($30/$45/$70). Ingredients = pieces × (0.06 × flour + 0.1/12 × eggs + 0.03 × butter + 0.35)
using `ingredient_prices`. Compare with `claimed.van_cost`, `oven_cost`, `ingredient_cost`.

| checked by | date | my van / oven / ingredients | system's | match? |
|---|---|---|---|---|
| | | | | |

## H-3 (optional): one BLS price
Look up flour APU0000701111 for the month in `bls_months` on https://data.bls.gov/timeseries/APU0000701111
and compare with `data/raw/prices/bls_prices_2026-11-18.csv`.
