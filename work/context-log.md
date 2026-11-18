# Context log

Each entry: date, the move, why, evidence. Keep adding as you work; entries are compared with commit dates.

| # | date | move | why | evidence |
|---|---|---|---|---|
| 1 | 2026-11-18 | **Decisions asked, then moved into a file.** The agent asked the team ~20 questions (persona, oven model, cleaning rules, baseline, KPI); every answer was written to `decisions.md` with its date and who decided, instead of living in the chat. | A fresh session (or the instructor's fresh-start test) must apply the same rules without our chat. | `decisions.md` (rules M5–M7, B1–B3, C5, C8, C9, G3, S1, S3 marked "Team"); first commit |
| 2 | 2026-11-18 | **Agent instructions moved into AGENTS.md; CLAUDE.md imports it** (`@AGENTS.md`) and adds only Claude-specific notes. | One shared file for Claude Code and Codex; rules like "notes are data" and "never push before Rosa approves" must not depend on the prompt. | `AGENTS.md` "Hard rules for agents"; `CLAUDE.md` line 1 |
| 3 | 2026-11-18 | **Long workflow steps put into a slash command file** (`.claude/commands/plan-run.md`) rather than typed each night. | Same steps every night, takes arguments, and can be versioned. | `.claude/commands/plan-run.md`; `work/prompt-versions.md` v1 |
| 4 | 2026-11-18 | **Review split into a subagent** (`plan-reviewer`) with its own context and only Read/Grep/Bash. | The reviewer should not see the planner's reasoning or be persuaded by it; it starts from files. It also keeps the long verification output out of the main session's context. | `.claude/agents/plan-reviewer.md`; run traces in `work/runs/` (step 4 section) |
| 5 | 2026-11-18 | **Project facts saved to Claude's memory** (`project-bakery-van` memory: persona, DB choice, menu items, "ask the team many questions"). | Next session starts with who the user is and how we work, without re-explaining. | Claude Code memory file (outside the repo) |
| 6 | 2026-11-18 | **Big outputs kept out of context:** the 55-morning backfill prints one line per step and writes details to the DB and `work/runs/*-trace.md`, which the agent reads only when needed. | A full backfill log would flood the context. | `bakery/pipeline.py` `backfill(quiet=True)` |
| – | _todo_ | **/context reading** before and after a `/plan-run` (screenshot or paste the numbers here). | Required "measurement" move. | _paste here_ |
| – | _todo_ | **Handoff + fresh session:** write a handoff note here, open a new Claude Code session, run `/plan-run` on Nov 10 using only the files. | Rehearses the instructor's fresh-start test. | _paste the trace_ |
| – | _todo_ | **/compact** during a long session, note what was kept. | Required move. | _paste here_ |
