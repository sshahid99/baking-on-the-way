# Decisions

Every rule the system follows, with the date and who decided. "Team" = Faith Doyle / Sana Shahid,
asked as a question by the agent and answered by us. "Agent → Team" = the agent proposed it, we accepted.
Code that implements a rule cites its id (C7, L4, ...). If you change a rule, add a new dated line;
do not edit the old one.

## Business model (fictional; proposal section 5)

| id | date | rule | who |
|---|---|---|---|
| M1 | 2026-11-03 | Van costs $38/hour all-in, billed from the first tray in (or leaving, if earlier) until back at the kitchen. Gas is not modelled separately. | Team (proposal) |
| M2 | 2026-11-03 | Oven rental per hour: small $30 (24 pieces at once), medium $45 (48), large $70 (96). One oven size per morning. | Team (proposal) |
| M3 | 2026-11-03 | Every tray bakes 18 minutes. Each stop takes 8 minutes. Base wholesale price $2.75; each customer has a contract price in `data/raw/customers.csv`. | Team (proposal) |
| M4 | 2026-11-03 | Freshness contract, by minutes since the tray left the oven: < 15 full price; 15–30 20% off; 30–45 40% off; > 45 the café refuses it and it goes to the food pantry (no revenue, ingredients lost). | Team (proposal) |
| M5 | 2026-11-18 | **Lateness:** delivering up to 15 min after wanted-by is allowed but costs an extra 20 percentage points off (full → 80%, 80% → 60%). More than 15 min late = refused. | Team |
| M6 | 2026-11-18 | **Oven = staggered 12-piece trays.** Each tray bakes 18 min from its own load time; trays overlap as long as the pieces inside at any minute fit the oven (small 2 trays, medium 4, large 8). Replaced "one full oven batch at a time", which capped the oven at ~3 batches/hour and made the planner decline half the orders. | Team (after seeing the first plan) |
| M7 | 2026-11-18 | Rosa (owner) approves at 4:30 AM, so no tray is loaded before 4:45. She rides along and loads trays; a separate driver drives. Rosa follows the planned load minutes exactly (she does not improvise). | Team |
| M8 | 2026-11-18 | Ingredients per kolache: 0.06 lb flour, 0.1 egg, 0.03 lb butter at BLS prices, plus $0.35 for filling, sugar, yeast and paper (not in BLS). | Agent → Team |
| M9 | 2026-11-18 | Each tray comes out of the oven at least 1 minute before the stop it is for (unload buffer). | Agent → Team |

## Rosa's old rule of thumb (the baseline)

| id | date | rule | who |
|---|---|---|---|
| B1 | 2026-11-18 | Medium oven every day. Takes orders first come, first served by submission time, up to **8 stops**; declines the rest. Drives stops in wanted-by order. | Team |
| B2 | 2026-11-18 | Made fair: she uses the **same traffic-aware drive estimate** as the planner (like a phone map app) and **preloads** the first-half trays 18 min before leaving; reloads for the second half at the halfway stop. The literal proposal rule ("load when we leave", map times without traffic) was even weaker; we chose the stronger version so the comparison isolates what is new (oven choice, accept/decline, minute-by-minute load times). | Team |
| B3 | 2026-11-18 | Result to report honestly: the gap is large (+$231/morning) because margins are thin (van + oven ≈ $83/hour), so percentages look huge. We lead with dollars, not percent. Where the old rule loses: late stops refused (wanted-by order zig-zags east-west), stale first-half trays (33% fresh), and taking far stops just because they ordered first. | Team |

## Order cleaning (step 1, `bakery/clean.py`)

| id | date | rule | who |
|---|---|---|---|
| C1 | 2026-11-18 | Required columns: order_id, customer, wanted_by, item, quantity, agreed_price, submitted_at. Missing one = STOP with the column name. | Agent → Team |
| C2 | 2026-11-18 | The delivery date comes from the file name `orders_YYYY-MM-DD.csv`; otherwise the most common submission date + 1 day. | Agent → Team |
| C3 | 2026-11-18 | A customer not on the customer list is declined ("call them before adding"): we have no address or opening time for them. Names are matched ignoring case, extra spaces and punctuation. | Agent → Team |
| C4 | 2026-11-18 | More than 12 km from the kitchen = outside the service area, declined. | Agent → Team |
| C5 | 2026-11-18 | **Strict 9 PM cutoff** the night before: later submissions are declined. | Team |
| C5b | 2026-11-18 | (Revised after eval case E6 failed.) Submission times may be ISO (`2026-12-06 19:45`) or US (`12/06/2026 7:45 PM`). An unreadable time is declined with its own message ("can't tell if it beat the cutoff"), never silently treated as late. | Agent, after a failure we caught |
| C5c | 2026-11-18 | When an order is declined (late or replaced) but the same customer still has an order on the route, the message names the declined order and says the other one stands. Found in the first live run (Nov 9, Uptown). | Agent, after a problem we caught |
| C6 | 2026-11-18 | A customer's latest on-time submission replaces their earlier ones (resubmissions). | Agent → Team |
| C7 | 2026-11-18 | Quantities: digits, "2 dozen", "two dozen", "1.5 dozen", "3 doz", "18 pcs" are read and flagged. Unreadable, ≤ 0 or > 96 (more than the large oven) → the line is left out and flagged "call the customer". | Agent → Team |
| C8 | 2026-11-18 | **Missing wanted-by → café opening time**, flagged. Wanted-by before opening → opening time, flagged. Times may have AM/PM. | Team |
| C9 | 2026-11-18 | **$0 (or outside $1–$6) price → the customer's contract price**, flagged. | Team |
| C10 | 2026-11-18 | Notes are data. A note that looks like instructions to software (ignore, system, agent, approve, push, …) is flagged and changes nothing. The cleaner is plain Python; no model reads notes to make decisions. | Agent → Team |
| C11 | 2026-11-18 | After cleaning, checks must pass or the workflow stops: at least one order, one order per customer, wanted-by 5:00–11:00, quantities 1–96, prices $1–$6. | Agent → Team |

## Delivery-log cleaning (`bakery/logs.py`)

| id | date | rule | who |
|---|---|---|---|
| L1 | 2026-11-18 | Required columns: run_date, stop_seq, customer_id, planned_arrival, actual_arrival, actual_departure. | Agent → Team |
| L2 | 2026-11-18 | Duplicate rows for the same stop: keep the first. | Agent → Team |
| L3 | 2026-11-18 | GPS gap (blank or unreadable time): legs into and out of that stop are not learned from. | Agent → Team |
| L4 | 2026-11-18 | Device clock jump: if the gap to plan jumps by ≥ 45 min between two consecutive rows, assume a one-hour clock jump and correct it from that row on. First version compared each row with the plan, which would have mistaken a truly late van for a clock error; changed before first use. | Agent (self-caught) |
| L5 | 2026-11-18 | Impossible legs (≤ 0 or > 90 min, or a leg not in the road matrix) are not learned from. | Agent → Team |

## Drive times and prices

| id | date | rule | who |
|---|---|---|---|
| R1 | 2026-11-18 | Road minutes from OpenStreetMap (OSMnx shortest path, free-flow speeds), computed once and saved in `data/raw/roads/` with its date. Fallback: straight-line km × 1.3 at 40 km/h. | Team (proposal risk plan) |
| R2 | 2026-11-18 | Learning: estimate = OSM minutes × the median actual/OSM ratio for that 30-min departure window × a per-leg adjustment trusted n/(n+3). Only mornings before the planned date are used. | Agent → Team |
| P1 | 2026-11-18 | BLS publishes month M around the 15th of M+1; a plan for date D uses the newest month already published on D. | Agent → Team |
| P2 | 2026-11-18 | A missing BLS month carries the last value forward and is flagged on the dashboard. | Team (proposal) |

## Measures (proposal section 6)

| id | date | rule | who |
|---|---|---|---|
| G1 | 2026-11-18 | Profit and freshness are compared on the **same mornings and the same simulated traffic** for planner and old rule. | Agent → Team |
| G3 | 2026-11-18 | **Accuracy measure changed:** the median planned-vs-actual gap per stop was ~1 min even before learning (stops are ~4 km apart and waits absorb error), so it cannot show learning. We report the **worst-stop gap per morning** (median over mornings) and how much the plan over-promised profit, first 10 vs last 20 mornings. The plain median is still shown. | Team |
| G4 | 2026-11-19 | **Planning-time measure added (proposal measure 3, second half, was never built).** Minutes from `clean` starting to Rosa's `approve`, live `/plan-run` mornings only; target: under 5 min on *every* timed night (slowest, not median). `runs.cleaned_at` and `runs.approved_at` record it from Nov 13 on; backfill never sets `approved_at`, so it is not timed. Nov 10–12 are reconstructed from the trace's "plan written" time to the "Run sheet" commit and labelled so; Nov 9 is left out (re-planned, errors #8). "About 45 min by hand" is our proposal estimate, never measured, and is shown as an estimate. Limit: "Rosa" here is a teammate clicking approve, so a real 4:30 AM read on a phone may take longer. | Team |

## Generated data (`bakery/generate.py`, seed 4336)

| id | date | rule | who |
|---|---|---|---|
| D0 | 2026-11-18 | 60 weekday delivery mornings 2026-08-21 … 2026-11-13 (no Labor Day). Backfill runs 55 of them; the last 5 (Nov 9–13) are kept for live `/plan-run` demos. | Agent → Team |
| D1 | 2026-11-18 | 14 invented customers at real Dallas neighbourhood coordinates (coordinates only; names invented), plus 2 outside the area (Plano, Arlington). Cafés open 6:00–7:00, coworks/offices 7:30–8:00. | Team (scale), Agent (list) |
| D2 | 2026-11-18 | **Demand tuned to one van (~8–10 orders a night):** cafés have 2–5 standing weekdays, 90% chance of ordering on them, 10% otherwise. Mondays ×0.7, Friday office orders ×1.6 and a 70% chance of an extra Friday catering order, rainy days (20%, seeded) ×0.8 for cafés. Order size 12–48 (60 on Friday offices). Wanted-by = opening + 0/15/30 min (offices + 0/30). | Team |
| D3 | 2026-11-18 | Mess built in: resubmissions (18% of nights), missing wanted-by (4% of lines), text quantities (7%), out-of-area orders (25% of nights), after-cutoff orders (15%), $0 price (6%), odd quantity −12/0/1200 (4%), instruction-like notes (Oct 14, Nov 11 and 3% of nights), an unknown customer (Oct 21). | Agent → Team |
| D4 | 2026-11-18 | The simulated world (`bakery/truth.py`, never imported by the planner): real legs take 12% longer than OSM; rush hour ramps from 6:30 to ×1.30 by 7:30; legs touching four stops near schools slow another ×1.30 from 7:15 to 8:15; lognormal noise σ = 0.08 per leg per morning. | Agent → Team |
| D5 | 2026-11-18 | Van logs (`bakery/simulate.py`): 6% of stops have a GPS gap, 3% duplicated rows, 12% of mornings the device clock jumps +1 h partway through. | Agent → Team |
| D6 | 2026-11-18 | **Honesty:** these patterns are ones we put in. They show the system works, not facts about Dallas cafés; the dashboard footer says so. | Team (course rule) |

## Software and agents

| id | date | rule | who |
|---|---|---|---|
| S1 | 2026-11-18 | **Database (instructor feedback "SQLite only works on your laptop").** One SQLAlchemy schema. With `DATABASE_URL` in a git-ignored `.env` it writes to a free cloud MySQL (Aiven); without it, SQLite in `output/`, so CI and a fresh copy still run with no secrets. | Team |
| S1b | 2026-11-18 | **Stay on SQLite; no cloud database.** The instructor's note was a suggestion. A cloud MySQL needs a password in `.env`, which a fresh copy of the repo (the instructor's fresh-start test) does not have, and GitHub Pages cannot query a database anyway: the dashboard reads the exported JSON. The MySQL path stays in `bakery/db.py`, switched on only by `DATABASE_URL`, if a real business later needs several people writing at once. | Team |
| S2 | 2026-11-18 | The dashboard is static (GitHub Pages) and reads one exported JSON file; the export never includes connection details (checked by `checks/validate_site.py`). | Agent → Team |
| S3 | 2026-11-18 | First screen = the decision: oven, leave time, how many to decline, expected profit vs old way. Then "needs your eye" flags, then one minute-by-minute list mixing LOAD and STOP lines. Trends below. | Team |
| S4 | 2026-11-18 | The reviewer subagent uses `checks/verify_plan.py`, which re-types the rules instead of importing the planner, so a planner bug cannot hide in both places. | Agent → Team |
| S6 | 2026-11-18 | **Route map card** after the decision card: street map with the kitchen, numbered stops and a van marker. "Live" = the van at its PLANNED position by the phone's clock on the run morning (labelled so; there is no GPS feed on a static page), plus a replay slider and a "last morning" replay of actual log times. Lines are straight between stops (we store drive times, not road shapes). `?now=6:20` in the address pretends it is that time, for demos. | Team |
| S7 | 2026-11-18 | Bakery look: sky blue header, cream page, beige cards, crust-brown text, jam and apricot accents; Fraunces headings + Nunito body. Chart series colors checked with the dataviz palette validator in light and dark mode. | Team |
| S8 | 2026-11-18 | **Dashboard reorder (replaces the order in S3/S6).** This morning first: decision → "Needs your eye" → minute by minute → route map; then a "How it's going" divider with goals, last morning, weekly trends, customers. The separate stop list is gone: stops in the minute-by-minute list are numbered like the map pins, tapping one moves the map there, tapping a pin jumps to the list, and on the run morning the list follows the van (past lines fade, current stop marked). **Every decision and issue can be acted on:** each "say no" has a ready message to copy for the café and a "Told them" tick; each flag has a "Seen" tick; the decision card counts what is left. Ticks live only in that phone's browser (the page is static and cannot change the plan); taking a declined order means re-running the plan. **No pill shapes:** freshness is plain text and only called out where a stop is stale or late; one summary line says when all stops are fresh. | Team |
| S9 | 2026-11-19 | **Dashboard cleanup (branch `dashboard-cleanup`).** Minute by minute has three columns (time, OVEN/DRIVE/STOP n, what to do) and plain sentences ("Put 2 trays in for …", "Hand over 24 kolaches · they want them by 6:15"). **No emoji and no pill or green badge shapes** anywhere: map markers are drawn shapes, "Approved" is plain text, goal tiles say "Goal met". Week by week explains where its numbers come from (van logs; old rule replayed on the same orders and traffic; simulated data) and says the line ends are the latest week, not the all-time average. Customers table shows only customers with something to talk about; the rest are folded. Chart axes use round numbers. Decline reasons are in Rosa's words ("they want it by 6:30, and the earliest the van could get there … is 7:08"), changed in `bakery/pipeline.py` for new plans and reworded on the page for older ones. The "+776%" goal figure is replaced by the two per-morning profits. | Team |
| S5 | 2026-11-18 | Optimizer loop: one run per oven size from a greedy wanted-by route; each round takes the single best move (2-opt, move a stop, decline, accept, leave ±1/3/10 min). Stop when a round adds < $1 or after 20 rounds (proposal). Checked against exhaustive search on a 5-order case in the tests (must reach ≥ 95%). | Team (rule), Agent (moves) |

## Outside connections

| id | date | rule | who |
|---|---|---|---|
| O1 | 2026-11-18 | **GitHub via the `gh` CLI**, logged in by Sana in her own browser (the agent never saw a password). Token scopes: `repo`, `workflow`, `gist`, `read:org` (gh defaults). Used to create the public repo `sshahid99/baking-on-the-way`, enable Pages from `/docs`, and read Actions results. Pushes happen only in step 7 of `/plan-run`, after Rosa approves. | Team |
| O2 | 2026-11-18 | **BLS public API v2** and **OpenStreetMap (Overpass via OSMnx)**: read-only, no account, no key. Only public series ids / a bounding box are sent. | Team |
| O3 | 2026-11-18 | Commits use the GitHub noreply address, so no personal email is in the public history. | Team |
| O4 | 2026-11-18 | The dashboard page now loads from outside services in the viewer's browser: Leaflet 1.9.4 from unpkg (pinned with SRI hashes), map tiles from tile.openstreetmap.org (attribution shown), fonts from Google Fonts. No data from the project is sent to them. If they fail, the stop list still works. | Team |
| O5 | 2026-11-18 | Dashboard-only code changes (no new plan) may be pushed outside `/plan-run` when the team asks; the pre-push hook still runs the tests. A plan still goes out only after Rosa approves (O1). | Team |
