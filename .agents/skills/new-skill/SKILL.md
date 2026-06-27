---
name: new-skill
description: Create a new Claude Code skill for the Fello project. Use when asked to add a new skill, automate a new workflow, or when a repeated workflow pattern is identified that should be encoded as a skill.
allowed-tools: Read Bash(mkdir -p .claude/skills/*) Bash(touch *)
---

## Skill file structure

```
.claude/skills/<skill-name>/
  SKILL.md        ← required
  references/     ← optional: detailed docs Claude loads on demand
  scripts/        ← optional: bash/python scripts
```

## SKILL.md template

```markdown
---
name: <skill-name>
description: <One sentence of what it does. Then: "Use when..." with specific trigger conditions. Be precise — vague descriptions don't auto-invoke reliably.>
allowed-tools: <List tools this skill needs: Read Grep Glob Bash(...) Write Edit>
---

## Steps

1. ...
2. ...

## Verification

!`<command to verify the skill worked>`
```

## After creating the skill, test it:
Open a new session and describe the situation that should trigger it. If it doesn't auto-invoke, tighten the description with more specific trigger phrases.
