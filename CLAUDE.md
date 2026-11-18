@AGENTS.md

## Claude Code specifics
- Start the nightly workflow with `/plan-run <order-file> [<delivery-log>]`. Follow its steps in order; do not skip the reviewer.
- Step 4 uses the `plan-reviewer` subagent (`.claude/agents/plan-reviewer.md`). Its context stays separate
  on purpose: it should not see the planner's reasoning, only the files.
- A PreToolUse hook (`.claude/hooks/pre_push_check.py`) runs the tests before any `git push` and blocks
  the push if they fail. If it blocks, fix the cause; never bypass it.
- Use AskUserQuestion for Rosa's approval and for any decision that belongs to the team. Record the
  answer in decisions.md with the date.
- Long sessions: when context gets large, write the current state to `work/context-log.md` and hand off,
  rather than relying on chat history. Everything a fresh session needs is in files.
