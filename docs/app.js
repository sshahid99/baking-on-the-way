// Reads data/dashboard.json and data/days/<date>.json (exported by `python -m bakery export`) and draws the page.
"use strict";
window.MAP_VERSION = 6;  // bump together with ?v= in index.html so phones fetch the new script
// Any script error shows on the page instead of failing silently.
window.addEventListener("error", (e) => {
  const box = document.getElementById("map");
  if (box && !box.querySelector(".leaflet-pane")) box.innerHTML = `<p class="fallback">Something went wrong drawing the map: ${String(e.message).replace(/</g, "&lt;")}</p>`;
});
const $ = (id) => document.getElementById(id);
const money = (v) => (v < 0 ? "−$" : "$") + Math.abs(Math.round(v)).toLocaleString("en-US");
const pct = (v) => Math.round(v * 100) + "%";
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const dayName = (iso) => new Date(iso + "T12:00:00").toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric" });
const shortDay = (iso) => new Date(iso + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
const ovenWord = { small: "small", medium: "medium", large: "large" };

// ---------- loading: dashboard.json once (overall sections + calendar), then one file per morning ----------
// The morning shown is in the address (#day=2026-10-05) so the back button and shared links work (decision S10).
let DASH = null;
const dayCache = {};
const loadJSON = (url) => fetch(url, { cache: "no-store" }).then((r) => { if (!r.ok) throw new Error(`${url}: ${r.status}`); return r.json(); });
const loadDay = (iso) => dayCache[iso] || (dayCache[iso] = loadJSON(`data/days/${iso}.json`).catch((e) => { delete dayCache[iso]; throw e; }));
const wantedDay = () => { const m = /day=(\d{4}-\d\d-\d\d)/.exec(location.hash); return m && DASH.calendar.days.some((x) => x.date === m[1]) ? m[1] : DASH.calendar.next; };
// Three tabs (decision S11): run sheet (one morning), the business (all mornings), the old way (how she planned
// before, and the shown morning planned that way). The tab is in the address too: #tab=oldway&day=2026-10-05.
const TABS = ["run", "business", "oldway"];
const wantedTab = () => { const m = /tab=(\w+)/.exec(location.hash); return m && TABS.includes(m[1]) ? m[1] : "run"; };
function setAddress(day, tab) {
  const parts = [];
  if (tab !== "run") parts.push("tab=" + tab);
  if (day && day !== DASH.calendar.next) parts.push("day=" + day);
  if (parts.length) location.hash = parts.join("&");
  else history.pushState(null, "", location.pathname + location.search);  // the next run's sheet has a clean address
}
let tabShown = null;
function showTab() {
  const t = wantedTab();
  if (t === tabShown) return;
  tabShown = t;
  TABS.forEach((k) => {
    $("panel-" + k).hidden = k !== t;
    $("tab-" + k).setAttribute("aria-selected", String(k === t));
    $("tab-" + k).tabIndex = k === t ? 0 : -1;
  });
  document.body.dataset.tab = t;  // the business tab covers all mornings, so the day picker is hidden there (style.css)
  if (t === "business") toggleCalendar(false);
  if (t === "run" && routeState) routeState.refit();  // the map was sized while hidden
}

loadJSON("data/dashboard.json")
  .then((d) => {
    DASH = d;
    renderGlobal(d);
    initCalendar(d.calendar);
    initTabs();
    window.addEventListener("hashchange", () => { showTab(); showWanted(); });
    showTab();
    return showWanted();
  })
  .catch((e) => { $("day").textContent = "Could not load the run sheet"; $("decision").innerHTML = `<p>${esc(e)}. Ask for the workflow to be run again.</p>`; });

let shown = null;
function showWanted() {
  const iso = wantedDay();
  if (iso === shown) return Promise.resolve();
  return loadDay(iso).then((v) => { shown = iso; renderDay(v, DASH); })
    .catch((e) => { $("decision").innerHTML = `<p>Could not load ${esc(dayName(iso))} (${esc(e.message)}).</p>`; });
}
function goToDay(iso) {
  setAddress(iso, wantedTab());
  showWanted();
}
function initTabs() {
  TABS.forEach((k, i) => {
    const b = $("tab-" + k);
    b.addEventListener("click", () => { setAddress(shown, k); showTab(); });
    b.addEventListener("keydown", (e) => {  // arrow keys move between tabs (WAI-ARIA tabs pattern)
      const j = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : null;
      if (j == null) return;
      const n = TABS[(j + TABS.length) % TABS.length];
      setAddress(shown, n); showTab(); $("tab-" + n).focus();
    });
  });
}

// ---------- one morning: the decision, needs your eye, minute by minute, map, how it went ----------
function renderDay(v, d) {
  const rs = v.run_sheet, past = rs.status === "done", out = v.outcome;
  $("day-label").textContent = dayName(rs.delivery_date);
  document.title = `Baking on the way · ${past ? "" : "run sheet "}${shortDay(rs.delivery_date)}`;
  $("eyebrow").textContent = past ? "Baking on the way · a past morning" : "Baking on the way · run sheet";
  const approved = rs.status === "approved" || past;
  $("status").textContent = past ? "Done" : approved ? "Approved" : "Waiting for your OK";
  $("status").className = "status " + (approved ? "ok" : "wait");
  updateDayNav(rs.delivery_date);

  // ---------- 1. the decision (a past morning: what was decided, then how it turned out) ----------
  const gain = rs.expected_profit - rs.old_rule_profit;
  const ovenWhy = Object.entries(rs.per_oven).map(([k, v]) => `${k} ${money(v)}`).join(" · ");
  const said = rs.declined_count ? `${past ? "said" : "say"} no to ${rs.declined_count} order${rs.declined_count > 1 ? "s" : ""}` : past ? "took every order" : "take every order";
  const oldWay = (p) => p < 0 ? "lost " + money(-p) : "made " + money(p);
  const hero = past
    ? `<div class="hero"><span class="num">${money(out.actual_profit)}</span>
      <span class="vs">actual profit · the plan said ${money(out.planned_profit)}<br>${out.old_rule_actual_profit == null ? ""
        : `Your old way would have ${oldWay(out.old_rule_actual_profit)} on this morning (same orders, same traffic).`}</span></div>`
    : `<div class="hero"><span class="num">${money(rs.expected_profit)}</span>
      <span class="vs">expected profit<br>${gain >= 0 ? money(gain) + " more than" : money(-gain) + " less than"} your old way,
        which would have ${oldWay(rs.old_rule_profit)}</span></div>`;
  $("decision").innerHTML = `
    <p class="headline">${past ? "Rented" : "Rent"} the <u>${ovenWord[rs.oven]}</u> oven, ${past ? "left" : "leave"} at ${rs.leave}, ${said}.</p>
    ${hero}
    <div class="facts">
      <div class="fact"><b>${rs.first_load}</b><span>first tray in</span></div>
      <div class="fact"><b>${rs.accepted} stops</b><span>${rs.pieces} kolaches</span></div>
      <div class="fact"><b>${pct(past ? out.actual_fresh : rs.expected_fresh)}</b><span>${past ? "arrived fresh" : "arrive fresh"}</span></div>
      <div class="fact"><b>${past ? hhmm(v.route.morning.back_min) : rs.back}</b><span>back at the kitchen</span></div>
    </div>
    <p class="why">Why this oven? Expected profit with each size: ${ovenWhy}. The ${ovenWord[rs.oven]} oven holds ${rs.oven_pieces} kolaches at once.</p>
    ${past ? `<p class="why">This morning is over. Below is the plan as it was, with what the van's log recorded at each stop.</p>`
      : approved ? "" : `<p class="waiting">Not approved yet. Say "approve" to the planner when you've read this; nothing is sent until you do.</p>`}
    <a class="todo-link" id="todo-link" href="#attention-card" hidden></a>`;

  // ---------- 2. needs your eye (a past morning: what came up, read-only) ----------
  renderAttention(rs, past);

  // ---------- 3. minute by minute (stops here are also the route's stop list) ----------
  renderTimeline(rs, past);

  // ---------- 3b. the route map ----------
  try { showRoute(v.route, v.is_next); } catch (e) { $("map").innerHTML = `<p class="fallback">The map could not be drawn (${esc(e.message)}). The minute-by-minute list above still has every time.</p>`; }
  const c = rs.costs;
  $("money").innerHTML = `<table>
    <tr><td>Sales (after freshness discounts)</td><td class="n">${money(c.revenue)}</td></tr>
    <tr><td>Ingredients (BLS prices, ${esc(rs.bls_months)})</td><td class="n">−${money(c.ingredients)}</td></tr>
    <tr><td>Van (${rs.van_rate_per_hour == null ? "hourly" : "$" + rs.van_rate_per_hour + "/hour"})</td><td class="n">−${money(c.van)}</td></tr>
    <tr><td>Oven rental</td><td class="n">−${money(c.oven)}</td></tr>
    <tr><th>Expected profit</th><th class="n">${money(rs.expected_profit)}</th></tr></table>
    ${c.revenue > c.ingredients && rs.pieces ? `<p class="hint margin-line">Profit margin <b>${pct(rs.expected_profit / c.revenue)}</b> (you keep ${cents(rs.expected_profit / c.revenue)} of every sales dollar) ·
      <b>${dollars2(rs.expected_profit / rs.pieces)}</b> profit per kolache · the van and oven are paid for after about
      <b>${Math.ceil((c.van + c.oven) / ((c.revenue - c.ingredients) / rs.pieces))}</b> of the ${rs.pieces} kolaches.</p>` : ""}`;

  renderOldWay(v);

  // ---------- 4. how a morning went: this one if it is over, otherwise the last finished one ----------
  const lm = past ? out : d.last_morning;
  $("last-card").hidden = !lm;
  if (lm) {
    $("last-title").textContent = past ? `How it went: ${dayName(lm.delivery_date)}` : `Last morning: ${dayName(lm.delivery_date)}`;
    $("last-open").hidden = past;
    $("last-open").href = "#day=" + lm.delivery_date;
    $("last-open").textContent = `Open all of ${shortDay(lm.delivery_date)} (map replay, minute by minute)`;
    $("last-tiles").innerHTML = [
      tile(money(lm.actual_profit), "actual profit", `planned ${money(lm.planned_profit)}`),
      tile(pct(lm.actual_fresh), "delivered fresh", lm.refused_pieces ? `${lm.refused_pieces} went to the pantry` : "none refused"),
      tile(lm.worst_gap_min == null ? "–" : lm.worst_gap_min + " min", "worst arrival vs plan", ""),
    ].join("");
    $("last-table").innerHTML = `<tr><th>Stop</th><th class="n">Planned</th><th class="n">Actual</th><th class="n">Fresh</th></tr>` +
      lm.stops.map((s) => `<tr><td>${esc(s.customer)}</td><td class="n">${s.planned}</td><td class="n">${s.actual || "no GPS"}</td>
      <td class="n">${s.refused ? `<span style="color:var(--critical-text)">${s.refused} refused</span>` : `${s.fresh}/${s.pieces}`}</td></tr>`).join("");
  }
}

// ---------- the overall sections: the same whichever morning is shown ----------
function renderGlobal(d) {
  // ---------- 5. trends ----------
  const w = d.weekly;
  const series2 = [{ key: "planner", label: "With the planner", color: "var(--series-1)" }, { key: "old", label: "Your old way", color: "var(--series-2)" }];
  lineChart($("chart-profit"), w.map((r) => ({ x: r.week, n: r.mornings, planner: r.planner_profit, old: r.old_rule_profit })), series2, money, true);
  lineChart($("chart-fresh"), w.map((r) => ({ x: r.week, n: r.mornings, planner: r.planner_fresh, old: r.old_rule_fresh })), series2, pct, false, [0, 1]);
  lineChart($("chart-margin"), w.map((r) => ({ x: r.week, n: r.mornings, planner: r.planner_margin, old: r.old_rule_margin })), series2, pct, true);
  lineChart($("chart-gap"), w.map((r) => ({ x: r.week, n: r.mornings, gap: r.worst_gap })), [{ key: "gap", label: "Minutes off at the worst stop", color: "var(--series-1)" }], (v) => (Number.isInteger(v) ? v : v.toFixed(1)) + " min", false);
  if (w.length) {
    const lw = w[w.length - 1];
    $("weekly-note").textContent = `The numbers at the right end of each line are the latest week (week of ${shortDay(lw.week)}, ${lw.mornings} morning${lw.mornings === 1 ? "" : "s"} so far). The tiles under "Is it working?" average all ${d.measures ? d.measures.mornings + " " : ""}mornings, so they differ.`;
  }
  $("weekly-table").innerHTML = `<tr><th>Week of</th><th class="n">Mornings</th><th class="n">Profit (planner)</th><th class="n">Profit (old way)</th><th class="n">Fresh (planner)</th><th class="n">Fresh (old)</th><th class="n">Worst gap</th></tr>` +
    w.map((r) => `<tr><td>${shortDay(r.week)}</td><td class="n">${r.mornings}</td><td class="n">${money(r.planner_profit)}</td><td class="n">${money(r.old_rule_profit)}</td><td class="n">${pct(r.planner_fresh)}</td><td class="n">${pct(r.old_rule_fresh)}</td><td class="n">${r.worst_gap ?? "–"}</td></tr>`).join("");

  // ---------- 6. customers ----------
  const custHead = `<tr><th>Customer</th><th class="n">Orders</th><th class="n nowrap">Said no</th><th class="n">Price</th>`;
  const custRow = (r, talk) => `<tr><td>${esc(r.customer)}<br><small class="muted">opens ${r.opens}</small></td><td class="n">${r.orders}</td><td class="n">${r.declined}</td><td class="n">$${r.price.toFixed(2)}</td>${talk ? `<td>${r.advice.map(esc).join("<br>")}</td>` : ""}</tr>`;
  const talk = d.customers.filter((r) => r.advice.length), rest = d.customers.filter((r) => !r.advice.length);
  $("customers").innerHTML = talk.length ? custHead + `<th>Talk about</th></tr>` + talk.map((r) => custRow(r, true)).join("")
    : `<tr><td>Nobody to talk to right now.</td></tr>`;
  $("customers-rest").hidden = !rest.length;
  $("customers-rest-sum").textContent = `The other ${rest.length} customers: nothing to talk about`;
  $("customers-rest-table").innerHTML = custHead + `</tr>` + rest.map((r) => custRow(r, false)).join("");

  // ---------- 7. goals ----------
  const m = d.measures;
  if (m) {
    $("goals").innerHTML = [
      tile("+" + money(m.profit_gain_per_morning), "more profit per morning than your old way", passFail(m.targets.profit_uplift_at_least_15pct, `${money(m.profit_per_morning_planner)} vs ${money(m.profit_per_morning_old_rule)} a morning · goal: at least 15% more`)),
      tile(pct(m.fresh_share_planner), "delivered within 15 min of the oven", passFail(m.targets.fresh_at_least_85pct, `goal: 85% · old way ${pct(m.fresh_share_old_rule)}`)),
      tile(m.worst_gap_after.toFixed(1) + " min", "worst-stop arrival error, last 20 mornings", passFail(m.targets.worst_gap_after_at_most_5min, `goal: ≤ 5 min · was ${m.worst_gap_before.toFixed(1)} at the start`)),
      ...(m.planning_time && m.planning_time.counted ? [tile(m.planning_time.slowest_min.toFixed(1) + " min", "longest night from order sheet to your OK", passFail(m.targets.planning_under_5min, `goal: under ${m.planning_time.target_min} min · by hand about ${m.planning_time.by_hand_estimate_min} (our guess) · ${m.planning_time.counted} nights timed`))] : []),
    ].join("");
  } else { $("goals-card").hidden = true; }
  renderBusiness(m);

  // ---------- footer: freshness of the data and its limits ----------
  const meta = d.meta;
  $("foot").innerHTML = `
    <p><b>Data as of</b> ${new Date(meta.generated_at).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" })} ·
      orders through ${shortDay(meta.orders_through)} · ${meta.mornings_completed} mornings of history ·
      ${meta.drive_legs_learned} drive legs learned · stored in ${esc(meta.database)}.</p>
    <p><b>What this can't tell you:</b> it does not know about road closures, a sick driver or a café that changes its order in the morning.
      Expected profit assumes the café pays the freshness contract exactly. Gas is not included.</p>
    <p>${esc(meta.disclaimer)}</p>
    <p>Road network © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a> (ODbL).
      Ingredient prices: U.S. Bureau of Labor Statistics, Average Price Data (flour, eggs, butter), months ${esc(meta.bls_months)}.</p>`;
}

const cents = (r) => Math.round(r * 100) + "¢";
const dollars2 = (v) => (v < 0 ? "−$" : "$") + Math.abs(v).toFixed(2);

// ---------- the business tab: an average morning as a profit-and-loss statement, both ways (decisions F1-F3) ----------
const PNL_ROWS = [
  ["list_sales", "Sales at full contract price", "", false],
  ["markdowns", "Freshness and lateness discounts", "−", false],
  ["spoilage", "Refused kolaches (to the food pantry)", "−", false],
  ["net_sales", "What the cafés paid (net sales)", "", true],
  ["cogs", "Ingredients (cost of goods)", "−", false],
  ["gross_profit", "Gross profit", "", true],
  ["run_cost", "Van and oven, by the hour", "−", false],
  ["contribution", "Profit (contribution)", "", true],
];
function pnlTable(a, b, headA, headB) {
  const cell = (p, k, sign) => `<td class="n">${sign && Math.round(p[k]) ? sign : ""}${money(p[k])}</td>`;
  const pctRow = (label, k) => `<tr class="ratio"><td>${label}</td><td class="n">${a[k] == null ? "–" : pct(a[k])}</td><td class="n">${b[k] == null ? "–" : pct(b[k])}</td></tr>`;
  return `<tr><th></th><th class="n">${headA}</th><th class="n">${headB}</th></tr>` +
    PNL_ROWS.map(([k, label, sign, bold]) => `<tr${bold ? ' class="sub"' : ""}><td>${label}</td>${cell(a, k, sign)}${cell(b, k, sign)}</tr>`).join("") +
    pctRow("Gross margin (gross profit ÷ net sales)", "gross_margin") +
    pctRow("Profit margin (profit ÷ net sales)", "contribution_margin") +
    pctRow("Share of full price collected", "price_realisation") +
    pctRow("Kolaches refused", "spoilage_rate");
}

function renderBusiness(m) {
  const b = m && m.business;
  ["biz-card", "year-card"].forEach((id) => { $(id).hidden = !b; });
  if (!b) return;
  const P = b.planner, O = b.old_rule, y = b.per_year;
  $("biz-hint").textContent = `${m.mornings} mornings the van drove, ${shortDay(m.first_day)} to ${shortDay(m.last_day)}. Everything on this tab is over those mornings, compared with your old way on the same mornings.`;
  $("biz-tiles").innerHTML = [
    tile(pct(P.ratios.contribution_margin), "profit margin with the planner", `old way ${pct(O.ratios.contribution_margin)}: of each sales dollar you keep ${cents(P.ratios.contribution_margin)}, not ${cents(O.ratios.contribution_margin)}`),
    tile(dollars2(P.ratios.contribution_per_kolache), "profit per kolache", `old way ${dollars2(O.ratios.contribution_per_kolache)} · sells for ${dollars2(P.ratios.sales_per_kolache)}, costs ${dollars2(P.ratios.cost_per_kolache)}`),
    tile(Math.ceil(P.ratios.break_even_kolaches) + " kolaches", "pay for the van and oven (break-even)", `of ${Math.round(P.per_morning.pieces)} a morning · the old way needs ${Math.ceil(O.ratios.break_even_kolaches)} of ${Math.round(O.per_morning.pieces)}`),
    tile(`${O.losing_mornings} of ${m.mornings}`, "mornings the old way lost money", `with the planner: ${P.losing_mornings} · its worst morning still made ${money(P.worst_morning)}`),
  ].join("");
  const pm = (x) => ({ ...x.per_morning, ...x.ratios });
  $("biz-pnl").innerHTML = pnlTable(pm(P), pm(O), "With the planner", "Your old way");
  $("biz-terms").innerHTML = [
    ["Net sales", "what the cafés actually paid, after the freshness contract's discounts and refused trays."],
    ["Cost of goods", "the ingredients in the kolaches you delivered (flour, eggs and butter at BLS prices, plus $0.35 for filling, sugar, yeast and paper)."],
    ["Gross margin", "the share of net sales left after ingredients. It falls when trays are discounted or refused, because the ingredients were paid for anyway."],
    ["Profit (contribution)", "net sales minus ingredients, van and oven. Kitchen rent, insurance and your own pay are not in this model, so this is what is left to cover them, not the bakery's bottom line."],
    ["Profit margin", "profit as a share of net sales: the cents you keep from each dollar the cafés pay."],
    ["Break-even", "how many kolaches it takes to pay for the van and oven hours, at the average a kolache earns after its ingredients."],
    ["Discounts and refused kolaches", "the money lost between full price and what was paid. This is where the old way loses most."],
  ].map(([t, d]) => `<dt>${t}</dt><dd>${d}</dd>`).join("");
  $("year-hint").textContent = `A projection, not a measurement: the average morning above × ${y.mornings} mornings a year (Monday to Friday, 50 weeks). The mornings are simulated, so read it as the size of the prize, not a promise.`;
  $("year-tiles").innerHTML = [
    tile("+" + money(y.gain), "more profit a year than your old way", `${money(y.planner_contribution)} vs ${money(y.old_rule_contribution)}`),
    tile(money(y.leakage_saved), "less lost to discounts and refused trays", "most of the gain"),
    tile("+" + money(y.net_sales_gain), "more net sales", "about the same number of kolaches, sold fresher"),
  ].join("");
}

// ---------- the old way tab: the shown morning, planned with Rosa's rule of thumb (decisions B1, B2) ----------
function renderOldWay(v) {
  const ow = v.old_way, rs = v.run_sheet, past = rs.status === "done";
  const b = DASH.measures && DASH.measures.business, O = b ? b.old_rule : null;
  $("ow-why").innerHTML = [
    `<b>Trays sit too long.</b> Half the trays go in before you leave, so the later stops in that half get kolaches 20 to 40 minutes out of the oven, and those get discounted or refused.${O ? ` Over all mornings the old way's cafés refused ${pct(O.ratios.spoilage_rate)} of its kolaches and it collected only ${pct(O.ratios.price_realisation)} of full price.` : ""}`,
    `<b>Wanted-by order zig-zags.</b> Driving earliest-first criss-crosses Dallas east to west, so the van is out longer (more van and oven hours) and late to the last stops.`,
    `<b>First come is not most profitable.</b> A far café that ordered early gets a yes; a close one that ordered later gets a no.`,
    `<b>Same oven every day.</b> On a light morning the medium oven costs $15 an hour more than the small one.${b ? ` The planner picked the small oven on ${b.planner.oven_mix.small} of ${DASH.measures.mornings} mornings.` : ""}`,
  ].map((t) => `<li>${t}</li>`).join("");
  $("ow-day-card").hidden = !ow;
  if (!ow) return;
  const verb = past ? "would have made" : "would make";
  $("ow-day-title").textContent = `${dayName(rs.delivery_date)}, the old way`;
  $("ow-day-hint").textContent = past
    ? "Same orders, driven through the same morning's traffic as the real van: what the old way would have got."
    : "Your old rule on tomorrow's orders. Expected figures: the morning hasn't happened yet.";
  const planP = past && v.outcome ? v.outcome.actual_profit : rs.expected_profit;
  const diff = planP - ow.profit;
  $("ow-day-tiles").innerHTML = [
    tile(money(ow.profit), `profit the old way ${verb}`, `planner: ${money(planP)}, ${money(Math.abs(diff))} ${diff >= 0 ? "more" : "less"}`),
    tile(pct(ow.fresh), "delivered fresh", `planner: ${pct(past && v.outcome ? v.outcome.actual_fresh : rs.expected_fresh)}`),
    tile(`${ow.preloaded} of ${ow.loads}`, "trays in before leaving", `medium oven, leave ${ow.leave}, back ${ow.back}`),
  ].join("");
  $("ow-day-table").innerHTML = `<tr><th>Stop (wanted-by order)</th><th class="n">Wanted by</th><th class="n">${past ? "Got there" : "Gets there"}</th><th class="n">Oldest tray</th><th class="n">Paid</th></tr>` +
    ow.stops.map((s) => `<tr><td>${s.seq}. ${esc(s.customer)}<br><small class="muted">${s.pieces} kolaches${s.refused ? ` · <span style="color:var(--critical-text)">${s.refused} refused</span>` : s.fresh === s.pieces ? " · all fresh" : ` · ${s.fresh} fresh`}${s.late ? " · late" : ""}</small></td>
      <td class="n">${s.wanted_by}</td><td class="n">${s.arrive || "–"}</td><td class="n">${s.oldest_tray_min} min</td><td class="n">${s.revenue == null ? "–" : money(s.revenue)}</td></tr>`).join("");
  $("ow-day-down").textContent = ow.turned_down.length
    ? `The old way ${past ? "said" : "says"} no to: ${ow.turned_down.join(", ")} (not in the first 8 orders in).`
    : `The old way ${past ? "took" : "takes"} every order this morning.`;
  $("ow-day-pnl").innerHTML = rs.pnl ? pnlTable(rs.pnl, ow.pnl, "With the planner", "Your old way") : "";
}

function tile(v, l, s) { return `<div class="tile"><div class="v">${v}</div><div class="l">${l}</div><div class="s">${s}</div></div>`; }
function passFail(ok, text) { return `<span class="s ${ok ? "pass" : "fail"}">${ok ? "Goal met" : "Goal not met"} · ${text}</span>`; }

// ---------- needs your eye ----------
// The page is static, so it cannot change the plan. What Rosa can do here: copy a ready message for a café
// she is saying no to, and tick each item off. Ticks are kept in this phone's browser (localStorage), per morning.
const tickKey = (day, id) => `bakery:${day}:${id}`;
const getTick = (k) => { try { return localStorage.getItem(k) === "1"; } catch (e) { return false; } };
const setTick = (k, on) => { try { on ? localStorage.setItem(k, "1") : localStorage.removeItem(k); } catch (e) { /* private mode: tick lasts until reload */ } };

function rosaWords(why) {
  return why.replace(/^\[C\d+\] /, "")
    .replace(/can't reach it by (\d+:\d\d) \+ 15 min without making other stops late \(best case (\d+:\d\d)\)/,
      "they want it by $1, and the earliest the van could get there without making other stops late is $2")
    .replace("fitting it in makes other stops later or staler", "fitting it in would make other stops late or their kolaches less fresh");
}

function sayNoMessage(x, day) {
  const weekday = new Date(day + "T12:00:00").toLocaleDateString("en-US", { weekday: "long" });
  const rule = (/^\[(C\d+)\]/.exec(x.why) || [])[1];
  const why = rule === "C4" ? "your address is outside the area the van can reach in time"
    : rule === "C5" ? "the order reached us after our 9 PM cutoff"
    : x.by === "planner" ? "I can't reach you by the time you asked for without making other deliveries late"
    : "I couldn't fit it in this time";
  const next = rule === "C5" ? " Orders in by 9 PM always make the next morning."
    : x.by === "planner" ? " A later wanted-by time would help me fit you in next time." : "";
  return `Hi ${x.customer}, this is Rosa from Baking on the Way. I'm sorry, I can't deliver your kolache order on ${weekday} morning: ${why}.${next}`;
}

function renderAttention(rs, readOnly) {
  const day = rs.delivery_date, list = $("attention");
  $("attention-title").textContent = readOnly ? "What came up that day" : "Needs your eye";
  $("attention-hint").hidden = readOnly;
  if (readOnly) {  // a past morning: nothing left to do, so no ticks and no messages to copy
    const rows = [
      ...rs.declined.map((x) => `<li><span class="icon no" aria-hidden="true">✕</span><div class="body"><b>Said no to ${esc(x.customer)}</b><small>${esc(rosaWords(x.why))}</small></div></li>`),
      ...rs.flags.map((f) => `<li><span class="icon info" aria-hidden="true">!</span><div class="body"><b>${esc(f.customer || "Order sheet")}</b><small>${esc(f.text)}</small></div></li>`),
    ];
    list.innerHTML = rows.join("") || `<li><div>Nothing unusual in that night's orders.</div></li>`;
    return;
  }
  const items = [
    ...rs.declined.map((x) => ({ id: "no:" + x.customer, kind: "no", title: `Say no to ${x.customer}`,
      text: rosaWords(x.why), msg: sayNoMessage(x, day), tick: "Told them" })),
    ...rs.flags.map((f, i) => ({ id: `flag:${f.rule}:${f.customer || ""}:${i}`, kind: "info",
      title: f.customer || "Order sheet", text: f.text, tick: "Seen" })),
  ];
  if (!items.length) {
    list.innerHTML = `<li><div>Nothing unusual in tonight's orders.</div></li>`;
    $("attention-hint").hidden = true;
    return;
  }
  list.innerHTML = items.map((it, i) => `<li data-i="${i}">
      <span class="icon ${it.kind}" aria-hidden="true">${it.kind === "no" ? "✕" : "!"}</span>
      <div class="body"><b>${esc(it.title)}</b><small>${esc(it.text)}</small>
        <div class="actions">
          ${it.msg ? `<button type="button" class="act copy">Copy a message for them</button>` : ""}
          <button type="button" class="act tick" aria-pressed="false">${it.tick}</button>
        </div></div></li>`).join("") +
    (rs.declined.length ? `<li class="note">Want a declined order after all? Ask for tonight's plan to be run again with it; the planner re-checks the whole route.</li>` : "");
  const update = () => {
    let done = 0;
    list.querySelectorAll("li[data-i]").forEach((li) => {
      const it = items[+li.dataset.i], on = getTick(tickKey(day, it.id));
      li.classList.toggle("done", on); done += on;
      const b = li.querySelector(".tick");
      b.setAttribute("aria-pressed", on); b.textContent = on ? `${it.tick} (tap to undo)` : it.tick;
    });
    const link = $("todo-link");
    if (link) {
      link.hidden = false;
      link.textContent = done === items.length ? `All ${items.length} things that needed your eye are handled`
        : `${items.length - done} of ${items.length} things need your eye before you leave ↓`;
      link.classList.toggle("all-done", done === items.length);
    }
  };
  list.querySelectorAll("li[data-i]").forEach((li) => {
    const it = items[+li.dataset.i];
    li.querySelector(".tick").addEventListener("click", () => { setTick(tickKey(day, it.id), !getTick(tickKey(day, it.id))); update(); });
    const copy = li.querySelector(".copy");
    if (copy) copy.addEventListener("click", () => {
      const done = () => { copy.textContent = "Copied. Paste it into a text or email"; setTimeout(() => (copy.textContent = "Copy a message for them"), 4000); };
      if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(it.msg).then(done, () => window.prompt("Copy this message:", it.msg));
      else window.prompt("Copy this message:", it.msg);
    });
  });
  update();
}

// ---------- minute by minute ----------
// Freshness is only called out where something is wrong (old tray or late); fresh stops just show the minutes.
let routeApi = null;  // set by setupRoute so a tap on a stop can move the map
// A past morning shows each stop as planned, then what the van's log recorded (decision S10).
function whatHappened(a) {
  const g = a.gap_min, when = a.curb == null ? "No GPS for this stop"
    : `Van pulled up at ${a.curb}, ${g == null || Math.abs(g) < 1 ? "as planned" : `${Math.round(Math.abs(g))} min ${g > 0 ? "later" : "earlier"} than planned (${a.planned_curb})`}`;
  const fresh = a.refused ? `<span class="warn">${a.refused} kolaches refused, went to the pantry</span>`
    : a.fresh === a.pieces ? ` · all ${a.pieces} fresh` : `<span class="warn">${a.fresh} of ${a.pieces} fresh, the rest sold at a discount</span>`;
  return `<span class="happened">${when}${fresh}${a.late ? `<span class="warn">Handed over after the time they asked for: 20% off</span>` : ""}</span>`;
}
const wentWell = (a) => !a.refused && a.fresh === a.pieces && !a.late;

function renderTimeline(rs, past) {
  const stops = rs.events.filter((e) => e.kind === "stop");
  const problems = past ? stops.filter((e) => !wentWell(e.actual)) : stops.filter((e) => e.oldest_tray_min >= 15 || e.late);
  const name = (e) => e.text.replace(/^Stop \d+: /, "");
  $("timeline-hint").innerHTML = past
    ? "Times on the left are the plan. Under each stop: what the van's log recorded. Tap a stop to see it on the map."
    : "<b>Oven</b> lines: put trays into the van's oven. <b>Stop</b> lines: hand the kolaches over. Tap a stop to see it on the map.";
  $("fresh-summary").innerHTML = past
    ? (problems.length
      ? `<b class="warn-text">${stops.length - problems.length} of ${stops.length} stops got every kolache fresh and on time.</b> Not at ${problems.map((e) => esc(name(e))).join(", ")}.`
      : `<b>All ${stops.length} stops</b> got every kolache fresh and on time.`)
    : problems.length
    ? `<b class="warn-text">${stops.length - problems.length} of ${stops.length} stops get their kolaches fresh and on time.</b> Check ${problems.map((e) => esc(name(e))).join(", ")} below.`
    : `<b>All ${stops.length} stops</b> get their kolaches less than 15 minutes out of the oven, on time.`;
  const row = (cls, time, kind, main, sub, extra = "") =>
    `<li class="${cls}" ${extra}><span class="t">${time}</span><span class="k">${kind}</span><span class="what">${main}${sub ? `<span class="sub">${sub}</span>` : ""}</span></li>`;
  $("timeline").innerHTML = rs.events.map((e) => {
    if (e.kind === "load") {
      const m = /^Load (\d+) trays? \((\d+)\) for (.+)$/.exec(e.text);
      return m ? row("load", e.time, "Oven", `Put ${m[1]} tray${m[1] === "1" ? "" : "s"} in for ${esc(m[3])}`, `${m[2]} kolaches · ready at ${e.out}`, `data-min="${e.min}"`)
        : row("load", e.time, "Oven", esc(e.text), `ready at ${e.out}`, `data-min="${e.min}"`);
    }
    if (e.kind === "stop") {
      const m = /^(\d+) kolaches · wanted by (.+)$/.exec(e.detail);
      const what = !m ? esc(e.detail) : past ? `${m[1]} kolaches · they wanted them by ${m[2]}` : `Hand over ${m[1]} kolaches · they want them by ${m[2]}`;
      const warn = [];
      if (!past && e.oldest_tray_min >= 15) warn.push(`Oldest tray is ${e.oldest_tray_min} min out of the oven, so they pay ${e.oldest_tray_min < 30 ? "80%" : "60%"} of the price`);
      if (!past && e.late) warn.push("Arrives after the time they asked for: 20% off");
      const sub = past ? `${what}<br>${whatHappened(e.actual)}`
        : `${what}<br>out of the oven ${e.oldest_tray_min} min before` + warn.map((w) => `<span class="warn">${w}</span>`).join("");
      const bad = past ? !wentWell(e.actual) : warn.length;
      return row(`stop${bad ? " problem" : ""}`, e.time, `Stop ${e.seq}`, `<b>${esc(name(e))}</b>`, sub,
        `data-seq="${e.seq}" data-min="${e.min}" tabindex="0" role="button" aria-label="Show stop ${e.seq} on the map"`);
    }
    const word = e.kind === "leave" ? "Drive" : e.kind === "back" ? "Done" : "";
    return row(e.kind, e.time, word, esc(e.text), "", `data-min="${e.min}"`);
  }).join("");
  $("timeline").querySelectorAll("li.stop").forEach((li) => {
    const go = () => { if (!routeApi) return; routeApi.showStop(+li.dataset.seq); $("route-card").scrollIntoView({ behavior: "smooth", block: "start" }); };
    li.addEventListener("click", go);
    li.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); go(); } });
  });
}

// ---------- a small SVG line chart: one y-axis, thin 2px lines, legend + direct end labels, crosshair tooltip ----------
function lineChart(el, rows, series, fmt, zeroLine, domain) {
  rows = rows.filter((r) => series.some((s) => r[s.key] != null));
  if (!rows.length) { el.textContent = "Not enough mornings yet."; return; }
  const W = 640, H = 220, m = { t: 12, r: 92, b: 26, l: 48 };
  const vals = rows.flatMap((r) => series.map((s) => r[s.key])).filter((v) => v != null);
  let [lo, hi] = domain || [Math.min(0, ...vals), Math.max(...vals)];
  if (hi === lo) hi = lo + 1;
  let tickStep = (hi - lo) / 4;
  if (!domain) {  // round the axis to 1 / 2 / 2.5 / 5 x 10^k so labels read $100, $200 ... not $241
    const raw = (hi - lo) / 4, mag = Math.pow(10, Math.floor(Math.log10(raw)));
    tickStep = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((s) => s >= raw);
    lo = Math.floor(lo / tickStep) * tickStep; hi = Math.ceil(hi / tickStep) * tickStep;
  }
  const x = (i) => m.l + (rows.length === 1 ? (W - m.l - m.r) / 2 : (i * (W - m.l - m.r)) / (rows.length - 1));
  const y = (v) => m.t + (1 - (v - lo) / (hi - lo)) * (H - m.t - m.b);
  const grid = [];
  for (let v = lo; v <= hi + tickStep / 1000; v += tickStep) {
    grid.push(`<line x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}"/><text x="${m.l - 6}" y="${y(v) + 4}" text-anchor="end">${fmt(v)}</text>`);
  }
  const step = Math.ceil(rows.length / 6);
  const xl = rows.map((r, i) => (i % step === 0 || i === rows.length - 1) ? `<text x="${x(i)}" y="${H - 6}" text-anchor="middle">${shortDay(r.x)}</text>` : "").join("");
  const paths = series.map((s) => {
    let d = "", pen = false;
    rows.forEach((r, i) => { if (r[s.key] == null) { pen = false; return; } d += (pen ? "L" : "M") + x(i).toFixed(1) + "," + y(r[s.key]).toFixed(1); pen = true; });
    const lastI = rows.map((r) => r[s.key]).lastIndexOf(rows.map((r) => r[s.key]).filter((v) => v != null).slice(-1)[0]);
    const lv = rows[lastI][s.key];
    return { s, d, lx: x(lastI), ly: y(lv), lv };
  });
  // nudge end labels apart
  const lbls = paths.map((p) => ({ ...p, ty: p.ly })).sort((a, b) => a.ty - b.ty);
  for (let i = 1; i < lbls.length; i++) if (lbls[i].ty - lbls[i - 1].ty < 28) lbls[i].ty = lbls[i - 1].ty + 28;
  const svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(series.map((s) => s.label).join(" vs "))} by week">
    <g class="grid axis">${grid.join("")}</g>
    ${zeroLine && lo < 0 ? `<line class="zero" x1="${m.l}" x2="${W - m.r}" y1="${y(0)}" y2="${y(0)}"/>` : ""}
    <g class="axis">${xl}</g>
    ${paths.map((p) => `<path d="${p.d}" fill="none" stroke="${p.s.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`).join("")}
    ${paths.map((p) => `<circle cx="${p.lx}" cy="${p.ly}" r="4" fill="${p.s.color}" stroke="var(--surface-1)" stroke-width="2"/>`).join("")}
    ${lbls.map((p) => `<text class="lbl" x="${p.lx + 8}" y="${p.ty + 4}">${esc(fmt(p.lv))}</text><text class="lbl" x="${p.lx + 8}" y="${p.ty + 17}" style="font-weight:400;font-size:11px">${esc(p.s.key === "old" ? "old way" : p.s.key === "planner" ? "planner" : "worst stop")}</text>`).join("")}
    <line class="cross" id="${el.id}-x" y1="${m.t}" y2="${H - m.b}" x1="0" x2="0" visibility="hidden"/>
    <rect x="${m.l}" y="0" width="${W - m.l - m.r}" height="${H}" fill="transparent" class="hit"/>
  </svg>`;
  const legend = series.length > 1 ? `<div class="legend">${series.map((s) => `<span><i style="background:${s.color}"></i>${esc(s.label)}</span>`).join("")}</div>` : "";
  el.innerHTML = legend + svg;
  const svgEl = el.querySelector("svg"), cross = el.querySelector(".cross"), tip = $("tooltip");
  if (!tip.parentElement.classList.contains("viz-root")) $("app").appendChild(tip);
  const move = (ev) => {
    const pt = svgEl.getBoundingClientRect(), cx = ((ev.clientX - pt.left) / pt.width) * W;
    let best = 0; rows.forEach((r, i) => { if (Math.abs(x(i) - cx) < Math.abs(x(best) - cx)) best = i; });
    cross.setAttribute("x1", x(best)); cross.setAttribute("x2", x(best)); cross.setAttribute("visibility", "visible");
    const r = rows[best];
    tip.innerHTML = `<b>Week of ${shortDay(r.x)}</b>${r.n ? ` · ${r.n} morning${r.n === 1 ? "" : "s"}` : ""}<br>` + series.map((s) => `<span style="color:${s.color}">━</span> ${esc(s.label)}: <b>${r[s.key] == null ? "–" : esc(fmt(r[s.key]))}</b>`).join("<br>");
    tip.hidden = false;
    tip.style.left = Math.min(ev.clientX + 12, window.innerWidth - tip.offsetWidth - 8) + "px";
    tip.style.top = ev.clientY - tip.offsetHeight - 12 + "px";
  };
  const hit = el.querySelector(".hit");
  hit.addEventListener("pointermove", move);
  hit.addEventListener("pointerdown", move);
  hit.addEventListener("pointerleave", () => { tip.hidden = true; cross.setAttribute("visibility", "hidden"); });
}

// ---------- route map: Leaflet + OpenStreetMap, the van moves by the clock or by replay ----------
// "Live" is the PLANNED position at the phone's clock time: there is no GPS feed on this static page.
// Demo: add ?now=6:10 to the address to pretend it is the next run's morning at 6:10 (the clock then ticks normally).
const nowMin = () => { const t = new Date(); return t.getHours() * 60 + t.getMinutes() + t.getSeconds() / 60; };
const localISO = () => { const t = new Date(); return new Date(t - t.getTimezoneOffset() * 60000).toISOString().slice(0, 10); };
const hhmm = (m) => { const r = Math.round(m); return Math.floor(r / 60) + ":" + String(r % 60).padStart(2, "0"); };

function routeSegments(r, depot) {
  // Each piece of the morning: either parked somewhere (at) or driving (from -> to), between t0 and t1.
  const segs = [], kitchen = { ...depot, label: "the kitchen" };
  segs.push({ t0: -Infinity, t1: r.leave_min, at: kitchen, text: "Loading trays at the kitchen" });
  let t = r.leave_min, prev = kitchen;
  for (const s of r.stops) {
    if (s.arrive_min == null) continue;  // no GPS for this stop: the van is drawn straight past it
    const here = { ...s, label: `Stop ${s.seq}: ${s.customer}` };
    segs.push({ t0: t, t1: s.arrive_min, from: prev, to: here, text: `Driving to ${here.label}`, stop: s.seq });
    if (s.handoff_min > s.arrive_min + 0.5) segs.push({ t0: s.arrive_min, t1: s.handoff_min, at: here, text: `Parked at ${s.customer}, waiting to hand off`, stop: s.seq });
    segs.push({ t0: s.handoff_min, t1: s.depart_min, at: here, text: `Handing over ${s.pieces} kolaches at ${s.customer}`, stop: s.seq });
    t = s.depart_min; prev = here;
  }
  segs.push({ t0: t, t1: r.back_min, from: prev, to: kitchen, text: "Driving back to the kitchen" });
  segs.push({ t0: r.back_min, t1: Infinity, at: kitchen, text: "Back at the kitchen. Morning done." });
  return segs;
}

function vanAt(segs, m) {
  const s = segs.find((g) => m >= g.t0 && m < g.t1) || segs[segs.length - 1];
  if (s.at) return { lat: s.at.lat, lon: s.at.lon, text: s.text, stop: s.stop };
  const f = Math.max(0, Math.min(1, (m - s.t0) / (s.t1 - s.t0 || 1)));
  return { lat: s.from.lat + (s.to.lat - s.from.lat) * f, lon: s.from.lon + (s.to.lon - s.from.lon) * f, text: s.text, stop: s.stop };
}

// The map is built once; showRoute() redraws it for whichever morning is shown.
// The next run shows the plan (and goes live on its morning); a past morning replays the van's log.
let routeState = null;
function showRoute(R, isNext) {
  if (!R || !R.morning) { $("route-card").hidden = true; return; }
  $("route-card").hidden = false;
  if (!routeState) routeState = setupRoute(R.depot);
  routeState.load(R, isNext);
}

function setupRoute(depot) {
  if (!window.L) $("map").innerHTML = `<p class="fallback">The street map needs an internet connection. The minute-by-minute list above still has every time.</p>`;
  const fake = /^(\d{1,2}):(\d{2})$/.exec(new URLSearchParams(location.search).get("now") || "");
  const fakeOffset = fake ? (+fake[1] * 60 + +fake[2]) - nowMin() : 0;
  const clockNow = () => nowMin() + fakeOffset;

  const seriesColor = getComputedStyle($("app")).getPropertyValue("--series-1").trim();
  let map = null, layer = null, van = null, pins = {}, trailLine = null;
  if (window.L) {
    map = L.map("map", { scrollWheelZoom: false });
    // Standard OpenStreetMap tiles (free, attribution required; dark mode darkens them in CSS).
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
  }

  const state = { isNext: true, t: 0, playing: false, live: false, segs: [], r: null, raf: 0, last: 0 };
  const scrub = $("scrub");
  const isRunDay = () => state.isNext && (!!fake || localISO() === state.r.delivery_date);

  function draw() {
    const r = state.r;
    state.segs = routeSegments(r, depot);
    scrub.min = Math.floor(r.leave_min - 10); scrub.max = Math.ceil(r.back_min + 5); scrub.step = 0.5;
    $("map-note").textContent = r.kind === "planned"
      ? "Planned times. Lines join the stops in order; the van follows real roads between them."
      : "Replay of the van's log: actual arrival times. Tap a pin for planned vs actual; the full table is under How it went.";

    if (map) {
      if (layer) layer.remove();
      layer = L.layerGroup().addTo(map);
      const path = [[depot.lat, depot.lon], ...r.stops.filter((s) => s.arrive_min != null).map((s) => [s.lat, s.lon]), [depot.lat, depot.lon]];
      L.polyline(path, { color: seriesColor, weight: 3, opacity: 0.55, dashArray: "6 7" }).addTo(layer);
      trailLine = L.polyline([], { color: seriesColor, weight: 4, opacity: 0.95 }).addTo(layer);
      L.marker([depot.lat, depot.lon], { icon: L.divIcon({ className: "", html: '<div class="kitchen" aria-label="kitchen"><svg viewBox="0 0 20 20" width="18" height="18"><path d="M2.5 10 10 3l7.5 7v7.5h-5v-5h-5v5h-5z" fill="#fffaf0"/></svg></div>', iconSize: [34, 34], iconAnchor: [17, 17] }) })
        .bindTooltip(esc(depot.name)).addTo(layer);
      pins = {};
      r.stops.forEach((s) => {
        const when = r.kind === "planned" ? "arrive " + s.arrive : s.arrive_min == null ? "no GPS" : `arrived ${s.arrive} (planned ${s.planned_arrive})`;
        pins[s.seq] = L.marker([s.lat, s.lon], { icon: L.divIcon({ className: "", html: `<div class="pin${s.arrive_min == null ? " nogps" : ""}">${s.seq}</div>`, iconSize: [28, 28], iconAnchor: [14, 14] }) })
          .bindTooltip(`${s.seq}. ${esc(s.customer)}<br>${when}`).addTo(layer)
          .on("click", () => jumpToRow(s.seq));
      });
      van = L.marker([depot.lat, depot.lon], { icon: L.divIcon({ className: "", html: '<div class="van" aria-label="van"><svg viewBox="0 0 26 17" width="22" height="15"><path d="M1 2h14v10H1zM16 5h5l4 4v3h-9z" fill="#fff"/><circle cx="6" cy="13" r="2.4" fill="#fff" stroke="#d2456c"/><circle cx="20" cy="13" r="2.4" fill="#fff" stroke="#d2456c"/></svg></div>', iconSize: [38, 38], iconAnchor: [19, 19] }), zIndexOffset: 1000 }).addTo(layer);
      map.fitBounds(L.latLngBounds(path).pad(0.12));
    }
  }

  function setTime(m) {
    const r = state.r;
    state.t = Math.max(+scrub.min, Math.min(+scrub.max, m));
    scrub.value = state.t;
    $("clock").textContent = hhmm(state.t);
    const p = vanAt(state.segs, state.t);
    const label = state.live ? `<span class="live">LIVE · PLANNED POSITION</span>` : `<span class="replay">${r.kind === "planned" ? "PLAN" : "REPLAY"}</span>`;
    $("now-line").innerHTML = `${label}${esc(p.text)}`;
    // a stop is "done" once the van has left it, "now" while the van is there or driving to it
    r.stops.forEach((s) => {
      const st = s.depart_min != null && state.t >= s.depart_min ? "done" : p.stop === s.seq ? "now" : "";
      const el = pins[s.seq] && pins[s.seq].getElement() && pins[s.seq].getElement().querySelector(".pin");
      if (el) el.className = "pin " + st + (s.arrive_min == null ? " nogps" : "");
    });
    markTimeline(p);
    if (van) {
      van.setLatLng([p.lat, p.lon]);
      const trail = [[depot.lat, depot.lon]];
      if (state.t >= r.leave_min) {
        r.stops.forEach((s) => { if (s.arrive_min != null && state.t >= s.arrive_min) trail.push([s.lat, s.lon]); });
        trail.push([p.lat, p.lon]);
      }
      trailLine.setLatLngs(trail);
    }
  }

  // The minute-by-minute list follows the van: past lines fade, the current stop is marked.
  // On a past morning the list shows planned times, so only the current stop is marked (by stop number).
  function markTimeline(p) {
    const planned = state.r.kind === "planned";
    document.querySelectorAll("#timeline li").forEach((li) => {
      const seq = +li.dataset.seq, s = seq ? state.r.stops.find((x) => x.seq === seq) : null;
      const end = s ? s.depart_min : +li.dataset.min;
      li.classList.toggle("past", planned && state.t >= end);
      li.classList.toggle("now", !!seq && p.stop === seq && (end == null || state.t < end));
    });
  }
  function jumpToRow(seq) {
    const li = document.querySelector(`#timeline li[data-seq="${seq}"]`);
    if (!li) return;
    li.scrollIntoView({ behavior: "smooth", block: "center" });
    li.classList.remove("flash"); void li.offsetWidth; li.classList.add("flash");
  }
  routeApi = {
    showStop(seq) {
      const s = state.r.stops.find((x) => x.seq === seq);
      if (!s || s.arrive_min == null) return;
      stopLive(); pause(); setTime(s.arrive_min + 0.5);
      if (map) map.panTo([s.lat, s.lon]);
    },
  };

  // replay: one minute of the morning every 120 ms (a 2-hour run takes about 15 seconds)
  function frame(ts) {
    if (!state.playing) return;
    const dt = state.last ? ts - state.last : 0; state.last = ts;
    setTime(state.t + dt / 120);
    if (state.t >= +scrub.max) { pause(); return; }
    state.raf = requestAnimationFrame(frame);
  }
  function play() {
    stopLive();
    if (state.t >= +scrub.max) setTime(+scrub.min);
    state.playing = true; state.last = 0;
    $("play").textContent = "❚❚"; $("play").setAttribute("aria-label", "Pause");
    state.raf = requestAnimationFrame(frame);
  }
  function pause() { state.playing = false; cancelAnimationFrame(state.raf); $("play").textContent = "▶︎"; $("play").setAttribute("aria-label", "Play"); }

  // live: follow the clock on the morning of the next run
  let liveTimer = 0;
  const canLive = () => isRunDay() && clockNow() >= state.r.leave_min - 45 && clockNow() <= state.r.back_min + 30;
  function goLive() {
    if (!canLive()) return false;
    pause(); state.live = true; $("golive").hidden = true;
    setTime(clockNow());
    clearInterval(liveTimer);
    liveTimer = setInterval(() => { if (state.live) setTime(clockNow()); }, 5000);
    return true;
  }
  function stopLive() { if (!state.live) return; state.live = false; clearInterval(liveTimer); $("golive").hidden = !canLive(); }

  $("play").addEventListener("click", () => (state.playing ? pause() : play()));
  scrub.addEventListener("input", () => { stopLive(); pause(); setTime(+scrub.value); });
  $("golive").addEventListener("click", goLive);

  return {
    refit() { if (map && state.r) { map.invalidateSize(); draw(); setTime(state.t); } },
    load(R, isNext) {
      stopLive(); pause();
      state.isNext = isNext; state.r = R.morning;
      draw();
      if (!goLive()) {
        setTime(+scrub.min);
        if (isRunDay() && clockNow() < state.r.leave_min - 45) $("now-line").innerHTML += ` <small>(goes live at ${hhmm(state.r.leave_min - 45)})</small>`;
      }
      $("golive").hidden = state.live || !canLive();
    },
  };
}

// ---------- the calendar: every morning the van ran, shaded by what it actually made (decision S10) ----------
// One hue, light to dark = less to more profit (sequential; dark mode uses its own steps, see style.css).
// Every square also prints its dollar figure, so the shade is never the only way to read it.
const PROFIT_BINS = [150, 225, 300, 375];
const BIN_LABELS = ["under $150", "$150 to $225", "$225 to $300", "$300 to $375", "$375 or more"];
const binOf = (p) => 1 + PROFIT_BINS.filter((b) => p >= b).length;
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const pad2 = (n) => String(n).padStart(2, "0");
const CAL = { days: [], byDate: {}, month: null, min: null, max: null };

function calText(x) {
  if (x.status !== "done") return `${dayName(x.date)}: the next run. The plan expects ${money(x.planned_profit)}.`;
  return `${dayName(x.date)}: made ${money(x.actual_profit)}, the plan said ${money(x.planned_profit)}` +
    (x.old_rule_actual_profit == null ? "" : `, your old way would have ${x.old_rule_actual_profit < 0 ? "lost " + money(-x.old_rule_actual_profit) : "made " + money(x.old_rule_actual_profit)}`) +
    `. ${pct(x.actual_fresh)} fresh${x.refused_pieces ? `, ${x.refused_pieces} refused` : ""}.`;
}

function initCalendar(cal) {
  CAL.days = cal.days;
  cal.days.forEach((x) => { CAL.byDate[x.date] = x; });
  const ym = (iso) => [+iso.slice(0, 4), +iso.slice(5, 7) - 1];
  CAL.min = ym(cal.days[0].date); CAL.max = ym(cal.days[cal.days.length - 1].date);
  $("cal-legend").innerHTML = BIN_LABELS.map((l, i) => `<span><i class="b${i + 1}"></i>${l}</span>`).join("") +
    `<span><i class="next"></i>next run</span>`;
  $("cal-open").addEventListener("click", () => toggleCalendar());
  $("cal-close").addEventListener("click", () => toggleCalendar(false));
  $("cal-prev").addEventListener("click", () => stepMonth(-1));
  $("cal-next").addEventListener("click", () => stepMonth(1));
  $("prev-day").addEventListener("click", () => stepDay(-1));
  $("next-day").addEventListener("click", () => stepDay(1));
  $("to-next").addEventListener("click", () => goToDay(DASH.calendar.next));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("cal").hidden) { toggleCalendar(false); $("cal-open").focus(); } });
  const grid = $("cal-grid"), tip = $("tooltip");
  grid.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-date]");
    if (!b) return;
    tip.hidden = true;
    toggleCalendar(false);
    goToDay(b.dataset.date);
  });
  grid.addEventListener("pointerover", (e) => {
    const b = e.target.closest("button[data-date]");
    if (!b || e.pointerType === "touch") return;
    tip.innerHTML = esc(calText(CAL.byDate[b.dataset.date]));
    tip.hidden = false;
    const r = b.getBoundingClientRect();
    tip.style.left = Math.max(8, Math.min(r.left, window.innerWidth - tip.offsetWidth - 8)) + "px";
    tip.style.top = r.top - tip.offsetHeight - 8 + "px";
  });
  grid.addEventListener("pointerleave", () => { tip.hidden = true; });
}

function toggleCalendar(open) {
  const cal = $("cal"), show = open ?? cal.hidden;
  cal.hidden = !show;
  $("cal-open").setAttribute("aria-expanded", show);
  if (show) {
    CAL.month = [+shown.slice(0, 4), +shown.slice(5, 7) - 1];
    drawMonth();
    const sel = $("cal-grid").querySelector("[aria-current]");
    if (sel) sel.focus();
  } else { $("tooltip").hidden = true; }
}

function stepMonth(k) {
  let [y, m] = CAL.month;
  m += k; if (m < 0) { m = 11; y--; } if (m > 11) { m = 0; y++; }
  CAL.month = [y, m];
  drawMonth();
}

function stepDay(k) {
  const i = CAL.days.findIndex((x) => x.date === shown), j = i + k;
  if (j >= 0 && j < CAL.days.length) goToDay(CAL.days[j].date);
}

function updateDayNav(iso) {
  const i = CAL.days.findIndex((x) => x.date === iso);
  $("prev-day").disabled = i <= 0;
  $("next-day").disabled = i < 0 || i >= CAL.days.length - 1;
  const prev = CAL.days[i - 1], next = CAL.days[i + 1];
  $("prev-day").setAttribute("aria-label", prev ? `Previous morning: ${dayName(prev.date)}` : "No earlier morning");
  $("next-day").setAttribute("aria-label", next ? `Next morning: ${dayName(next.date)}` : "No later morning");
  $("to-next").hidden = iso === DASH.calendar.next;
  $("cal-open").setAttribute("aria-label", `${dayName(iso)}. Open the calendar to pick another morning`);
  if (!$("cal").hidden) { CAL.month = [+iso.slice(0, 4), +iso.slice(5, 7) - 1]; drawMonth(); }
}

function drawMonth() {
  const [y, m] = CAL.month, cmp = (a, b) => a[0] * 12 + a[1] - (b[0] * 12 + b[1]);
  $("cal-title").textContent = `${MONTHS[m]} ${y}`;
  $("cal-prev").disabled = cmp(CAL.month, CAL.min) <= 0;
  $("cal-next").disabled = cmp(CAL.month, CAL.max) >= 0;
  const lead = (new Date(y, m, 1).getDay() + 6) % 7, n = new Date(y, m + 1, 0).getDate();  // Monday first
  const cells = [];
  for (let i = 0; i < lead; i++) cells.push(`<span class="cell blank" aria-hidden="true"></span>`);
  let ran = 0, total = 0;
  for (let d = 1; d <= n; d++) {
    const iso = `${y}-${pad2(m + 1)}-${pad2(d)}`, x = CAL.byDate[iso];
    if (!x) { cells.push(`<span class="cell off" aria-hidden="true">${d}</span>`); continue; }
    const done = x.status === "done", sel = iso === shown;
    if (done) { ran++; total += x.actual_profit; }
    cells.push(`<button type="button" class="cell run ${done ? "b" + binOf(x.actual_profit) : "next"}${sel ? " sel" : ""}" data-date="${iso}"
      aria-label="${esc(calText(x))}"${sel ? ` aria-current="date"` : ""}><span class="dn">${d}</span><span class="pv">${done ? money(x.actual_profit) : "next"}</span></button>`);
  }
  $("cal-grid").innerHTML = cells.join("");
  $("cal-summary").textContent = ran ? `${ran} morning${ran === 1 ? "" : "s"} this month, ${money(total)} in all, ${money(total / ran)} a morning on average.` : "";
}
