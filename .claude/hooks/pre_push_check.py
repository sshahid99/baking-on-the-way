"""PreToolUse hook (Bash): before any `git push`, run the plan-rule tests and the dashboard JSON check.

Exit 2 blocks the tool call and shows stderr to Claude; exit 0 lets it through.
Every firing is appended to work/hook-log.md as evidence.
"""
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def python():
    for p in (ROOT / ".venv" / "Scripts" / "python.exe", ROOT / ".venv" / "bin" / "python"):
        if p.exists():
            return str(p)
    return sys.executable


def main():
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    cmd = (event.get("tool_input") or {}).get("command", "")
    if "git push" not in cmd:
        return 0
    checks = [[python(), "-m", "pytest", "-q", "tests"], [python(), "checks/validate_site.py"]]
    failed = []
    for c in checks:
        r = subprocess.run(c, cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            failed.append((" ".join(c[1:]), (r.stdout + r.stderr)[-1500:]))
    log = ROOT / "work" / "hook-log.md"
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"- {dt.datetime.now().isoformat(timespec='seconds')} pre-push hook on `{cmd[:80]}`: "
                f"{'BLOCKED - ' + ', '.join(n for n, _ in failed) if failed else 'passed'}\n")
    if failed:
        msg = "\n\n".join(f"{n} FAILED:\n{out}" for n, out in failed)
        print(f"Push blocked by pre-push hook: fix these first.\n{msg}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
