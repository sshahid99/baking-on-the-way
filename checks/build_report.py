"""Keep the final report up to date: refresh its numbers, optionally make the PDF.

    python checks/build_report.py          -> refreshes the auto blocks in output/report.md
    python checks/build_report.py --pdf    -> also writes output/Doyle_Shahid_Final.pdf (needs Chrome or Edge)

Only text between  <!-- auto:NAME -->  and  <!-- /auto:NAME -->  is rewritten. Everything else in
report.md is yours and is never touched. Numbers come from the database (checks/measures.py) and
from the files in work/, so the report always matches the evidence.
"""
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
REPORT = ROOT / "output" / "report.md"
PDF = ROOT / "output" / "Doyle_Shahid_Final.pdf"


def block_measures():
    from checks.measures import compute
    m = compute()
    ok = lambda b: "met" if b else "**not met**"  # noqa: E731
    t = m["targets"]
    return f"""_From `checks/measures.py`, {m['mornings']} completed mornings ({m['first_day']} to {m['last_day']}), refreshed {dt.date.today()}._

| Measure (proposal §6) | Target | Planner | Rosa's old rule | Result |
|---|---|---|---|---|
| Profit per morning | +15% | ${m['profit_per_morning_planner']:.0f} | ${m['profit_per_morning_old_rule']:.0f} | +${m['profit_gain_per_morning']:.0f}/morning ({m['profit_uplift']:+.0%}); planner better on {m['mornings_planner_won']}/{m['mornings']}: {ok(t['profit_uplift_at_least_15pct'])} |
| Kolaches delivered < 15 min from the oven | ≥ 85% | {m['fresh_share_planner']:.0%} | {m['fresh_share_old_rule']:.0%} | {ok(t['fresh_at_least_85pct'])} |
| Worst-stop arrival error, last 20 mornings | ≤ 5 min | {m['worst_gap_after']:.1f} min (first 10: {m['worst_gap_before']:.1f}) | – | {ok(t['worst_gap_after_at_most_5min'])} |
| Median stop arrival error (proposal's original measure) | ≤ 5 min | {m['median_gap_after']:.1f} min (first 10: {m['median_gap_before']:.1f}) | – | met, but it was met before any learning (decisions G3) |
| Plan's profit over-promise per morning | (learning effect) | ${m['overpromise_per_morning_after']:.0f} last 20 (first 10: ${m['overpromise_per_morning_before']:.0f}) | – | – |
| Pieces refused (pantry), planner | (learning effect) | {m['refused_pieces_after']} in last 20 mornings (first 10: {m['refused_pieces_before']}) | – | – |
{planning_row(m)}"""


def block_business():
    """An average morning as a profit-and-loss statement, both ways (decisions F1-F3)."""
    from checks.measures import compute
    m = compute()
    b = m["business"]
    P, O, y = b["planner"], b["old_rule"], b["per_year"]
    pm, om = P["per_morning"], O["per_morning"]
    d = lambda v: ("−$" if v < 0 else "$") + f"{abs(v):,.0f}"  # noqa: E731
    pc = lambda v: f"{v:.0%}"  # noqa: E731
    rows = [
        ("Sales at full contract price (list-price sales)", "list_sales", ""),
        ("− Freshness and lateness markdowns (M4, M5)", "markdowns", "−"),
        ("− Spoilage: refused kolaches given to the pantry", "spoilage", "−"),
        ("**= Net sales** (what the cafés paid)", "net_sales", ""),
        ("− Cost of goods sold (ingredients, M8)", "cogs", "−"),
        ("**= Gross profit**", "gross_profit", ""),
        ("− Run cost (van $38/h + oven rental, M1, M2)", "run_cost", "−"),
        ("**= Contribution** (the project's \"profit\")", "contribution", ""),
    ]
    out = [f"_From `checks/measures.py` via `bakery/finance.py`: average of {m['mornings']} completed mornings, same orders and traffic for both. Refreshed {dt.date.today()}._",
           "", "| Average morning | Planner | Rosa's old rule | Planner − old rule |", "|---|---|---|---|"]
    for label, k, sign in rows:
        diff = pm[k] - om[k]
        out.append(f"| {label} | {sign}{d(pm[k])} | {sign}{d(om[k])} | {'+' if diff > 0 else ''}{d(diff)} |")
    R, Q = P["ratios"], O["ratios"]
    ratio_rows = [
        ("Gross margin (gross profit ÷ net sales)", pc(R["gross_margin"]), pc(Q["gross_margin"])),
        ("Contribution (profit) margin (contribution ÷ net sales)", pc(R["contribution_margin"]), pc(Q["contribution_margin"])),
        ("Price realisation (net sales ÷ list-price sales)", pc(R["price_realisation"]), pc(Q["price_realisation"])),
        ("Spoilage rate (kolaches refused)", pc(R["spoilage_rate"]), pc(Q["spoilage_rate"])),
        ("Net sales per kolache", f"${R['sales_per_kolache']:.2f}", f"${Q['sales_per_kolache']:.2f}"),
        ("Full cost per kolache (ingredients + run cost)", f"${R['cost_per_kolache']:.2f}", f"${Q['cost_per_kolache']:.2f}"),
        ("Contribution per kolache", f"${R['contribution_per_kolache']:.2f}", f"${Q['contribution_per_kolache']:.2f}"),
        ("Break-even volume (kolaches to cover the run cost)", f"{R['break_even_kolaches']:.0f} of {pm['pieces']:.0f}", f"{Q['break_even_kolaches']:.0f} of {om['pieces']:.0f}"),
        ("Mornings with a loss", f"{P['losing_mornings']} of {m['mornings']}", f"{O['losing_mornings']} of {m['mornings']}"),
        ("Worst / best morning", f"{d(P['worst_morning'])} / {d(P['best_morning'])}", f"{d(O['worst_morning'])} / {d(O['best_morning'])}"),
        ("Oven mix (small / medium / large)", "/".join(str(P["oven_mix"][o]) for o in ("small", "medium", "large")),
         "/".join(str(O["oven_mix"][o]) for o in ("small", "medium", "large"))),
    ]
    out += ["", "| Ratio | Planner | Rosa's old rule |", "|---|---|---|"] + [f"| {a} | {b_} | {c} |" for a, b_, c in ratio_rows]
    out += ["", f"**Yearly projection** (decisions F3: average morning × {y['mornings']} mornings, Mon–Fri × 50 weeks; simulated data, so a size-of-the-prize estimate, not a forecast): "
            f"contribution {d(y['planner_contribution'])} with the planner vs {d(y['old_rule_contribution'])} the old way, "
            f"**+{d(y['gain'])} a year**; {d(y['leakage_saved'])} of that is markdowns and spoilage no longer lost, and net sales rise {d(y['net_sales_gain'])} on about the same volume."]
    return "\n".join(out)


def planning_row(m):
    p = m["planning_time"]
    if not p["counted"]:
        return "| Planning time, order sheet to Rosa's approval | < 5 min | no live runs timed yet | ~45 min by hand (our estimate, not measured) | – |"
    ok = "met" if m["targets"]["planning_under_5min"] else "**not met**"
    rec = p["counted"] - p["measured"]
    how = f"{p['measured']} measured" + (f", {rec} reconstructed from git, see decisions G4" if rec else "")
    return (f"| Planning time, order sheet to Rosa's approval (live `/plan-run`s) | < 5 min | median {p['median_min']:.1f} min, "
            f"slowest {p['slowest_min']:.1f} min over {p['counted']} runs ({how}) | ~{p['by_hand_estimate_min']} min by hand "
            f"(our estimate, not measured) | {ok} on every run |")


def block_runs():
    rows = ["| Delivery date | How it was run | Result |", "|---|---|---|"]
    for p in sorted((ROOT / "work" / "runs").glob("*-trace.md")):
        text = p.read_text(encoding="utf-8")
        if "## Steps" not in text:
            continue  # backfill nights: no live workflow run
        chosen = re.search(r"\*\*Chosen:\*\* (.+)", text)
        verdict = "PASS" if "PASS" in text.split("## Steps", 1)[1] else "see trace"
        rows.append(f"| {p.name[:10]} | `/plan-run` (reviewer {verdict}) | {chosen.group(1) if chosen else ''} [trace](../work/runs/{p.name}) |")
    return "\n".join(rows)


def block_errors():
    text = (ROOT / "work" / "errors-caught.md").read_text(encoding="utf-8")
    table = [ln for ln in text.splitlines() if ln.startswith("|")]
    return "\n".join(table)


def block_eval():
    text = (ROOT / "work" / "eval-results.md").read_text(encoding="utf-8")
    runs = re.findall(r"## Run ([^\n]+)", text)
    return "\n".join(f"- Run {r}" for r in runs) + "\n\n_Criteria written before the first run: `work/eval-criteria.md`._"


def block_hook():
    p = ROOT / "work" / "hook-log.md"
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    blocked = [ln for ln in lines if "BLOCKED" in ln]
    return (f"The pre-push hook has fired {len(lines)} times: {len(lines) - len(blocked)} passed, "
            f"{len(blocked)} blocked.\n\n" + "\n".join(blocked[-3:]))


def block_commits():
    out = subprocess.run(["git", "log", "--format=%ad|%s", "--date=short"], cwd=ROOT,
                         capture_output=True, text=True).stdout.strip().splitlines()
    days = sorted({ln.split("|")[0] for ln in out})
    return f"{len(out)} commits on {len(days)} day(s) ({days[0]} to {days[-1]})." if out else "no commits"


def block_file(rel):
    """Include a work/ file: drop its own title and push its headings down to fit under the report's."""
    text = (ROOT / rel).read_text(encoding="utf-8").strip()
    text = re.sub(r"\A# .*\n+", "", text)
    return re.sub(r"^(#{1,4}) ", lambda m: "#" * min(len(m.group(1)) + 2, 6) + " ", text, flags=re.M)


BLOCKS = {
    "measures": block_measures, "business": block_business, "runs": block_runs, "errors": block_errors, "eval": block_eval,
    "hook": block_hook, "commits": block_commits,
    "context-log": lambda: block_file("work/context-log.md"),
    "prompt-versions": lambda: block_file("work/prompt-versions.md"),
}


def refresh():
    text = REPORT.read_text(encoding="utf-8")
    for name, fn in BLOCKS.items():
        pat = re.compile(rf"(<!-- auto:{name} -->)(.*?)(<!-- /auto:{name} -->)", re.S)
        if pat.search(text):
            text = pat.sub(lambda m: f"{m.group(1)}\n{fn()}\n{m.group(3)}", text)
    REPORT.write_text(text, encoding="utf-8")
    todo = len(re.findall(r"✍", text))
    words = len(re.sub(r"<!--.*?-->|[#|*_`>-]", " ", text, flags=re.S).split())
    print(f"Refreshed {REPORT.relative_to(ROOT)}: {words} words, {todo} sections still marked ✍ for your own words")


def find_browser():
    for p in [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              "google-chrome", "chromium", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]:
        if Path(p).exists() or shutil.which(p):
            return p
    return None


def pdf():
    import markdown
    body = markdown.markdown(REPORT.read_text(encoding="utf-8"), extensions=["tables", "fenced_code", "toc"])
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Doyle_Shahid_Final</title><style>
    @page {{ size: Letter; margin: 0.8in 0.75in; }}
    body {{ font: 10.5pt/1.45 Georgia, serif; color: #111; }}
    h1 {{ font-size: 20pt; }} h2 {{ font-size: 14pt; page-break-before: always; border-bottom: 1px solid #ccc; }}
    h2:first-of-type {{ page-break-before: avoid; }} h3 {{ font-size: 11.5pt; }}
    table {{ border-collapse: collapse; width: 100%; font: 8.5pt/1.3 system-ui, sans-serif; margin: 6px 0; }}
    th, td {{ border: 1px solid #ccc; padding: 3px 5px; vertical-align: top; text-align: left; }}
    pre, code {{ font: 8.5pt/1.35 Consolas, monospace; }} pre {{ background: #f5f5f2; border: 1px solid #ddd; padding: 8px; white-space: pre-wrap; }}
    img {{ max-width: 100%; }} blockquote {{ color: #555; border-left: 3px solid #ccc; margin-left: 0; padding-left: 10px; }}
    </style></head><body>{body}</body></html>"""
    tmp = ROOT / "output" / "_report.html"
    tmp.write_text(html, encoding="utf-8")
    browser = find_browser()
    if not browser:
        sys.exit(f"No Chrome/Edge found. Open {tmp} in a browser and print it to PDF.")
    subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={PDF}", tmp.resolve().as_uri()], capture_output=True)
    print(f"Wrote {PDF.relative_to(ROOT)}" if PDF.exists() else "PDF was not written; open output/_report.html and print it")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    refresh()
    if "--pdf" in sys.argv:
        pdf()
