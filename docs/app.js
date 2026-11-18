// Reads data/dashboard.json (exported from the database by `python -m bakery export`) and draws the page.
"use strict";
const $ = (id) => document.getElementById(id);
const money = (v) => (v < 0 ? "−$" : "$") + Math.abs(Math.round(v)).toLocaleString("en-US");
const pct = (v) => Math.round(v * 100) + "%";
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const dayName = (iso) => new Date(iso + "T12:00:00").toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric" });
const shortDay = (iso) => new Date(iso + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
const ovenWord = { small: "small", medium: "medium", large: "large" };

fetch("data/dashboard.json", { cache: "no-store" })
  .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
  .then(render)
  .catch((e) => { $("day").textContent = "Could not load the run sheet"; $("decision").innerHTML = `<p>${esc(e)}. Ask for the workflow to be run again.</p>`; });

function render(d) {
  const rs = d.run_sheet;
  $("day").textContent = dayName(rs.delivery_date);
  const approved = rs.status === "approved" || rs.status === "done";
  $("status").textContent = approved ? "✓ Approved" : "Waiting for your OK";
  $("status").className = "badge " + (approved ? "ok" : "wait");

  // ---------- 1. the decision ----------
  const gain = rs.expected_profit - rs.old_rule_profit;
  const ovenWhy = Object.entries(rs.per_oven).map(([k, v]) => `${k} ${money(v)}`).join(" · ");
  $("decision").innerHTML = `
    <p class="headline">Rent the <u>${ovenWord[rs.oven]}</u> oven, leave at ${rs.leave},
      ${rs.declined_count ? `say no to ${rs.declined_count} order${rs.declined_count > 1 ? "s" : ""}` : "take every order"}.</p>
    <div class="hero"><span class="num">${money(rs.expected_profit)}</span>
      <span class="vs">expected profit<br>${gain >= 0 ? money(gain) + " more than" : money(-gain) + " less than"} your old way (${money(rs.old_rule_profit)})</span></div>
    <div class="facts">
      <div class="fact"><b>${rs.first_load}</b><span>first tray in</span></div>
      <div class="fact"><b>${rs.accepted} stops</b><span>${rs.pieces} kolaches</span></div>
      <div class="fact"><b>${pct(rs.expected_fresh)}</b><span>arrive &lt; 15 min from oven</span></div>
      <div class="fact"><b>${rs.back}</b><span>back at the kitchen</span></div>
    </div>
    <p class="why">Why this oven? Expected profit with each size: ${ovenWhy}. The ${ovenWord[rs.oven]} oven holds ${rs.oven_pieces} kolaches at once.</p>`;

  // ---------- 2. needs your eye ----------
  const items = [];
  rs.declined.forEach((x) => items.push(`<li><span class="icon no" aria-label="declined">✕</span><div><b>Say no: ${esc(x.customer)}</b><small>${esc(x.why.replace(/^\[C\d+\] /, ""))}</small></div></li>`));
  rs.flags.forEach((f) => items.push(`<li><span class="icon info" aria-label="note">!</span><div>${esc(f.customer ? f.customer + ": " : "")}${esc(f.text)}</div></li>`));
  $("attention").innerHTML = items.length ? items.join("") : `<li><span class="icon info">✓</span><div>Nothing unusual in tonight's orders.</div></li>`;

  // ---------- 3. timeline ----------
  $("timeline").innerHTML = rs.events.map((e) => {
    let sub = "";
    if (e.kind === "load") sub = `<span class="sub">out of the oven ${e.out}</span>`;
    if (e.kind === "stop") {
      const chips = [];
      chips.push(e.oldest_tray_min < 15 ? `<span class="chip fresh">✓ fresh (${e.oldest_tray_min} min)</span>`
        : `<span class="chip stale">oldest tray ${e.oldest_tray_min} min · discount</span>`);
      if (e.late) chips.push(`<span class="chip late">late · 20% off</span>`);
      sub = `<span class="sub">${esc(e.detail)}</span>${chips.join("")}`;
    }
    return `<li class="${e.kind}"><span class="t">${e.time}</span><span class="what">${esc(e.text)}${sub}</span></li>`;
  }).join("");
  const c = rs.costs;
  $("money").innerHTML = `<table>
    <tr><td>Sales (after freshness discounts)</td><td class="n">${money(c.revenue)}</td></tr>
    <tr><td>Van (${"$38"}/hour)</td><td class="n">−${money(c.van)}</td></tr>
    <tr><td>Oven rental</td><td class="n">−${money(c.oven)}</td></tr>
    <tr><td>Ingredients (BLS prices, ${esc(rs.bls_months)})</td><td class="n">−${money(c.ingredients)}</td></tr>
    <tr><th>Expected profit</th><th class="n">${money(rs.expected_profit)}</th></tr></table>`;

  // ---------- 4. last morning ----------
  const lm = d.last_morning;
  if (lm) {
    $("last-title").textContent = `Last morning: ${dayName(lm.delivery_date)}`;
    $("last-tiles").innerHTML = [
      tile(money(lm.actual_profit), "actual profit", `planned ${money(lm.planned_profit)}`),
      tile(pct(lm.actual_fresh), "delivered fresh", lm.refused_pieces ? `${lm.refused_pieces} went to the pantry` : "none refused"),
      tile(lm.worst_gap_min == null ? "–" : lm.worst_gap_min + " min", "worst arrival vs plan", ""),
    ].join("");
    $("last-table").innerHTML = `<tr><th>Stop</th><th class="n">Planned</th><th class="n">Actual</th><th class="n">Fresh</th></tr>` +
      lm.stops.map((s) => `<tr><td>${esc(s.customer)}</td><td class="n">${s.planned}</td><td class="n">${s.actual || "no GPS"}</td>
      <td class="n">${s.refused ? `<span style="color:var(--critical-text)">${s.refused} refused</span>` : `${s.fresh}/${s.pieces}`}</td></tr>`).join("");
  } else { $("last-card").hidden = true; }

  // ---------- 5. trends ----------
  const w = d.weekly;
  const series2 = [{ key: "planner", label: "With the planner", color: "var(--series-1)" }, { key: "old", label: "Your old way", color: "var(--series-2)" }];
  lineChart($("chart-profit"), w.map((r) => ({ x: r.week, planner: r.planner_profit, old: r.old_rule_profit })), series2, money, true);
  lineChart($("chart-fresh"), w.map((r) => ({ x: r.week, planner: r.planner_fresh, old: r.old_rule_fresh })), series2, pct, false, [0, 1]);
  lineChart($("chart-gap"), w.map((r) => ({ x: r.week, gap: r.worst_gap })), [{ key: "gap", label: "Minutes off at the worst stop", color: "var(--series-1)" }], (v) => v.toFixed(1) + " min", true);
  $("weekly-table").innerHTML = `<tr><th>Week of</th><th class="n">Mornings</th><th class="n">Profit (planner)</th><th class="n">Profit (old way)</th><th class="n">Fresh (planner)</th><th class="n">Fresh (old)</th><th class="n">Worst gap</th></tr>` +
    w.map((r) => `<tr><td>${shortDay(r.week)}</td><td class="n">${r.mornings}</td><td class="n">${money(r.planner_profit)}</td><td class="n">${money(r.old_rule_profit)}</td><td class="n">${pct(r.planner_fresh)}</td><td class="n">${pct(r.old_rule_fresh)}</td><td class="n">${r.worst_gap ?? "–"}</td></tr>`).join("");

  // ---------- 6. customers ----------
  $("customers").innerHTML = `<tr><th>Customer</th><th class="n">Orders</th><th class="n">Said no</th><th class="n">Price</th><th>Talk about</th></tr>` +
    d.customers.map((r) => `<tr><td>${esc(r.customer)}<br><small style="color:var(--text-muted)">opens ${r.opens}</small></td><td class="n">${r.orders}</td><td class="n">${r.declined}</td><td class="n">$${r.price.toFixed(2)}</td><td>${r.advice.map(esc).join("<br>") || "<span style='color:var(--text-muted)'>–</span>"}</td></tr>`).join("");

  // ---------- 7. goals ----------
  const m = d.measures;
  if (m) {
    $("goals").innerHTML = [
      tile("+" + money(m.profit_gain_per_morning), "more profit per morning than your old way", passFail(m.targets.profit_uplift_at_least_15pct, `goal: +15% · got ${m.profit_uplift == null ? "n/a" : "+" + Math.round(m.profit_uplift * 100) + "%"}`)),
      tile(pct(m.fresh_share_planner), "delivered within 15 min of the oven", passFail(m.targets.fresh_at_least_85pct, `goal: 85% · old way ${pct(m.fresh_share_old_rule)}`)),
      tile(m.worst_gap_after.toFixed(1) + " min", "worst-stop arrival error, last 20 mornings", passFail(m.targets.worst_gap_after_at_most_5min, `goal: ≤ 5 min · was ${m.worst_gap_before.toFixed(1)} at the start`)),
    ].join("");
  } else { $("goals-card").hidden = true; }

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

function tile(v, l, s) { return `<div class="tile"><div class="v">${v}</div><div class="l">${l}</div><div class="s">${s}</div></div>`; }
function passFail(ok, text) { return `<span class="s ${ok ? "pass" : "fail"}">${ok ? "✓ met" : "✕ not met"} · ${text}</span>`; }

// ---------- a small SVG line chart: one y-axis, thin 2px lines, legend + direct end labels, crosshair tooltip ----------
function lineChart(el, rows, series, fmt, zeroLine, domain) {
  rows = rows.filter((r) => series.some((s) => r[s.key] != null));
  if (!rows.length) { el.textContent = "Not enough mornings yet."; return; }
  const W = 640, H = 220, m = { t: 12, r: 92, b: 26, l: 48 };
  const vals = rows.flatMap((r) => series.map((s) => r[s.key])).filter((v) => v != null);
  let [lo, hi] = domain || [Math.min(0, ...vals), Math.max(...vals)];
  if (hi === lo) hi = lo + 1;
  const pad = (hi - lo) * 0.08; if (!domain) { hi += pad; if (lo < 0) lo -= pad; }
  const x = (i) => m.l + (rows.length === 1 ? (W - m.l - m.r) / 2 : (i * (W - m.l - m.r)) / (rows.length - 1));
  const y = (v) => m.t + (1 - (v - lo) / (hi - lo)) * (H - m.t - m.b);
  const ticks = 4, grid = [];
  for (let k = 0; k <= ticks; k++) {
    const v = lo + ((hi - lo) * k) / ticks;
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
    ${lbls.map((p) => `<text class="lbl" x="${p.lx + 8}" y="${p.ty + 4}">${esc(fmt(p.lv))}</text><text class="lbl" x="${p.lx + 8}" y="${p.ty + 17}" style="font-weight:400;font-size:11px">${esc(p.s.label.split(" ").slice(-2).join(" "))}</text>`).join("")}
    <line class="cross" id="${el.id}-x" y1="${m.t}" y2="${H - m.b}" x1="-10" x2="-10"/>
    <rect x="${m.l}" y="0" width="${W - m.l - m.r}" height="${H}" fill="transparent" class="hit"/>
  </svg>`;
  const legend = series.length > 1 ? `<div class="legend">${series.map((s) => `<span><i style="background:${s.color}"></i>${esc(s.label)}</span>`).join("")}</div>` : "";
  el.innerHTML = legend + svg;
  const svgEl = el.querySelector("svg"), cross = el.querySelector(".cross"), tip = $("tooltip");
  if (!tip.parentElement.classList.contains("viz-root")) $("app").appendChild(tip);
  const move = (ev) => {
    const pt = svgEl.getBoundingClientRect(), cx = ((ev.clientX - pt.left) / pt.width) * W;
    let best = 0; rows.forEach((r, i) => { if (Math.abs(x(i) - cx) < Math.abs(x(best) - cx)) best = i; });
    cross.setAttribute("x1", x(best)); cross.setAttribute("x2", x(best));
    const r = rows[best];
    tip.innerHTML = `<b>Week of ${shortDay(r.x)}</b><br>` + series.map((s) => `<span style="color:${s.color}">━</span> ${esc(s.label)}: <b>${r[s.key] == null ? "–" : esc(fmt(r[s.key]))}</b>`).join("<br>");
    tip.hidden = false;
    tip.style.left = Math.min(ev.clientX + 12, window.innerWidth - tip.offsetWidth - 8) + "px";
    tip.style.top = ev.clientY - tip.offsetHeight - 12 + "px";
  };
  const hit = el.querySelector(".hit");
  hit.addEventListener("pointermove", move);
  hit.addEventListener("pointerdown", move);
  hit.addEventListener("pointerleave", () => { tip.hidden = true; cross.setAttribute("x1", -10); cross.setAttribute("x2", -10); });
}
