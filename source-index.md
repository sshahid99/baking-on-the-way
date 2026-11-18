# Source index

## Open data

| Source | Link | Downloaded | Licence / terms | Used for | File |
|---|---|---|---|---|---|
| OpenStreetMap, Dallas drive network via OSMnx 2.2 (`graph_from_bbox`, free-flow `travel_time`) | https://www.openstreetmap.org | 2026-11-18 | ODbL 1.0. Attribution "© OpenStreetMap contributors" with link to https://www.openstreetmap.org/copyright on the dashboard footer | Minutes between the kitchen and every customer (210 legs) | `data/raw/roads/travel_matrix_2026-11-18.csv` |
| U.S. Bureau of Labor Statistics, Average Price Data, U.S. city average: flour APU0000701111, eggs APU0000708111, butter APU0000FS1101 | https://www.bls.gov/cpi/additional-resources/average-price-publication-list.htm ; API https://api.bls.gov/publicAPI/v2/timeseries/data/ | 2026-11-18 | U.S. government work, public domain; cited to BLS | Ingredient cost per kolache by month | `data/raw/prices/bls_prices_2026-11-18.csv` |

Neighbourhood coordinates for the fictional customers were chosen by hand from public maps
(coordinates only); the businesses are invented.

## Generated data

| What | Script | Seed | Patterns and assumptions |
|---|---|---|---|
| Customers + 60 nightly order sheets | `bakery/generate.py` (`python -m bakery generate`) | 4336 | decisions.md D0–D3 |
| Van delivery logs | `bakery/simulate.py` (written by `python -m bakery drive <date>`) | per date (`log-<date>`) | decisions.md D4–D5 |
| Evaluation order sheets | hand-made, `tests/eval_cases/` | – | `work/eval-criteria.md` |
