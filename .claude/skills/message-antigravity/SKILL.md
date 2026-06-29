---
name: message-antigravity
description: Send a message from Claude Code to Antigravity. Use when you need to tell Antigravity about a completed file, a new type, or a blocker.
allowed-tools: Bash(node *) Read
---

## How to send a message
Run this command, replacing `YOUR_MESSAGE_HERE` with the actual text:

```bash
node -e "
const fs = require('fs');
const msg = `[${new Date().toISOString()}] [CLAUDE → ANTIGRAVITY] YOUR_MESSAGE_HERE\n`;
fs.appendFileSync('.collab/MESSAGES.md', msg);
console.log('Message sent:', msg.trim());
"
```

## When to use
- After finishing a UI component that Antigravity will call.
- When you add or modify a type in `lib/types.ts`.
- To report a blocker or ask a question.
- To signal that a shared file (`firestore.rules`, `CLAUDE.md`) has been updated.

## Message format rules
- One line per message.
- Do not edit existing lines.
- Keep it concise but descriptive.
