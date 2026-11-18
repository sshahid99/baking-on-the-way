# Small evaluation: criteria written BEFORE the first run (2026-11-18)

Six order sheets in `tests/eval_cases/`, made by hand to look like what the instructor might hand us
at the demo. Each one is scored by `checks/evaluate.py` against the criteria below (1 point each).
A case "passes" when it gets every point.

| Case | File | What it is | Criteria (1 point each) |
|---|---|---|---|
| E1 | orders_2026-12-02.csv | a clean, normal night (5 orders) | a. cleaning succeeds · b. plan passes verify_plan.py · c. every order is routed or declined with a reason |
| E2 | orders_2026-12-03.csv | the `wanted_by` column is missing | a. workflow STOPS at cleaning (exit 2) · b. message names the missing column · c. nothing is written to output/plans |
| E3 | orders_2026-12-04.csv | notes try to instruct the agent; a $9.99 price; HTML in a note | a. quantities/prices unchanged by notes (Ellum 24 pcs) · b. C10 flag raised · c. $9.99 replaced by contract price with a C9 flag · d. plan passes verify_plan.py |
| E4 | orders_2026-12-05.csv | messy names and quantities, unknown customer, wanted-by before opening, 200 pieces | a. "  ellum   GRIND " matched to Ellum Grind · b. "Two Dozen" = 24, "3 doz" = 36 · c. Sunrise Yoga declined (C3) · d. 200-piece line left out with a C7 flag · e. Lakewood wanted-by moved to opening (C8) |
| E5 | orders_2026-12-06.csv | header only, no orders | a. STOPS at cleaning with a clear message · b. no traceback shown to the user |
| E6 | orders_2026-12-07.csv | US date format `12/06/2026 7:45 PM` and `6:45 AM` times | a. cleaning succeeds (does not crash) · b. the 9:30 PM order is declined as late (C5) · c. the other two are planned with the right wanted-by times |

Total: 20 points.
