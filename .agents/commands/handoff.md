Create a session handoff document so the next Claude Code session can pick up exactly where this one left off.

1. Read the current state of:
   - app/ directory structure
   - lib/ directory structure
   - .claude/agents/ and .claude/skills/
   - Any uncommitted changes: `git status` and `git diff --stat`

2. Run the test-runner subagent to get current pass/fail status.

3. Write a file called `HANDOFF.md` in the project root with:
   - What was completed in this session
   - What is currently broken or incomplete
   - The next 3 tasks to tackle in priority order
   - Current test-runner output
   - Any decisions made or tradeoffs taken

4. Confirm: "Handoff document written to HANDOFF.md. Next session should start by reading CLAUDE.md, FELLO_CONTEXT.md, and HANDOFF.md."
