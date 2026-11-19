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
| Pieces refused (pantry), planner | (learning effect) | {m['refused_pieces_after']} in last 20 mornings (first 10: {m['refused_pieces_before']}) | – | – |"""


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
    "measures": block_measures, "runs": block_runs, "errors": block_errors, "eval": block_eval,
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
