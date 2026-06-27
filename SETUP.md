# SETUP.md — Fello Autonomous Build Instructions

Read `CLAUDE.md` and `FELLO_CONTEXT.md` completely before doing anything else. Then execute the phases in this file in order. Each phase tells you what files to create and what they should contain. Do not ask for confirmation between steps unless a step says PAUSE.

---

## PHASE 0 — Scaffold the Claude Code Infrastructure

Before writing a single line of application code, set up the full Claude Code tooling layer. This is what makes every subsequent phase faster and safer.

Create the following directory structure at the project root:

```
.claude/
  settings.json        ← hooks and permission rules
  agents/              ← subagent definitions
    ui-builder.md
    firestore-architect.md
    security-auditor.md
    adk-integrator.md
    test-runner.md
  skills/
    build-page/
      SKILL.md
    build-component/
      SKILL.md
    add-shadcn/
      SKILL.md
    tenant-safe-query/
      SKILL.md
    new-server-action/
      SKILL.md
    new-skill/
      SKILL.md
    demo-check/
      SKILL.md
  commands/
    build-section.md
    security-audit.md
    run-demo.md
    type-check.md
    handoff.md
```

---

## PHASE 1 — Write All Skill Files

Skills are markdown files with YAML frontmatter that Claude loads automatically when the task matches. Write every skill file now. Skills live in `.claude/skills/<name>/SKILL.md`.

### Skill 1 — build-page

**File:** `.claude/skills/build-page/SKILL.md`

```markdown
---
name: build-page
description: Build a new Next.js App Router page for the Fello frontend. Use when asked to create, scaffold, or implement any page under app/ — including bare layout pages (auth, onboarding) and full app layout pages (events, members, settings, dashboard). Auto-invokes when building a new route.
allowed-tools: Read Grep Glob Bash(pnpm dlx shadcn@latest add *) Bash(mkdir *) Bash(touch *)
---

## Rules for every page

1. Determine the layout — bare (no sidebar) or full app (with sidebar):
   - Bare: auth, setup, waitlist, org/new, org/join → lives under `app/(bare)/`
   - Full app: anything under `/org/[orgId]/` → lives under `app/org/[orgId]/`

2. Read the reference repo pattern before writing any markup:
   !`grep -r "rounded-t-lg\|rounded-b-lg\|rounded-none" ../uni-log-kavindu/components --include="*.tsx" -l 2>/dev/null || echo "Reference repo not mounted — apply pattern from CLAUDE.md Section 3.4"`

3. Color rule check — after writing the file, verify no hardcoded colors:
   !`grep -n "#\|rgb(\|hsl(" $FILE 2>/dev/null || echo "clean"`

4. Every page must have:
   - A `loading.tsx` sibling using shadcn Skeleton to match the page shape
   - An `error.tsx` sibling with a friendly message and retry button calling `reset()`
   - An empty state for every list rendered

5. No `<form>` tags. Use `onClick`/`onChange` with React state.

6. No `any` types. Import types from `lib/types.ts`.

7. After creating the page, run:
   !`pnpm tsc --noEmit 2>&1 | tail -20`
   Fix any type errors before finishing.
```

---

### Skill 2 — build-component

**File:** `.claude/skills/build-component/SKILL.md`

```markdown
---
name: build-component
description: Build a new reusable React component for the Fello frontend. Use when creating a component that will be used in more than one place, or when the task involves building a UI primitive, a feature card, a layout piece, or a shared UI element.
allowed-tools: Read Grep Glob Bash(pnpm dlx shadcn@latest add *)
---

## Component rules

1. Use shadcn primitives exclusively. Check what is already installed:
   !`ls components/ui/`

2. If you need a shadcn component not yet installed, install it first:
   `pnpm dlx shadcn@latest add <component-name>`

3. Border radius pattern for grouped list items (MANDATORY):
   - First item: `rounded-t-lg rounded-b-none border-b-0`
   - Middle items: `rounded-none border-b-0`
   - Last item: `rounded-t-none rounded-b-lg`
   - Single item: `rounded-lg`
   Verify this pattern exists in the reference repo:
   !`grep -A2 "rounded-t-lg" ../uni-log-kavindu/components 2>/dev/null | head -20 || echo "Apply pattern from CLAUDE.md"`

4. No hardcoded colors. Only shadcn CSS variables:
   `bg-background`, `bg-card`, `bg-muted`, `bg-primary`, `bg-secondary`, `bg-accent`, `bg-destructive`,
   `text-foreground`, `text-muted-foreground`, `text-primary-foreground`, `border`, `ring`, `input`

5. Every component must be typed. Import from `lib/types.ts`.

6. After writing the component, verify no color violations:
   !`grep -n "#\|rgb(\|hsl(" components/$COMPONENT_PATH 2>/dev/null || echo "clean"`
```

---

### Skill 3 — add-shadcn

**File:** `.claude/skills/add-shadcn/SKILL.md`

```markdown
---
name: add-shadcn
description: Add a new shadcn/ui component to the project. Use when a page or component needs a shadcn primitive that is not yet installed.
allowed-tools: Bash(pnpm dlx shadcn@latest add *) Read
---

## Steps

1. Check if the component is already installed:
   !`ls components/ui/`

2. If not installed, add it:
   `pnpm dlx shadcn@latest add $ARGUMENTS`

3. Verify it was added:
   !`ls components/ui/ | grep $ARGUMENTS`

4. Never install non-shadcn component libraries. If a UI need cannot be met by shadcn, build it from shadcn primitives.
```

---

### Skill 4 — tenant-safe-query

**File:** `.claude/skills/tenant-safe-query/SKILL.md`

```markdown
---
name: tenant-safe-query
description: Write a Firestore query or server action that is guaranteed to be tenant-safe. Use whenever writing any code that reads from or writes to Firestore. Auto-invokes when writing Firestore queries, server actions, or any database access code.
allowed-tools: Read Grep
---

## Tenant isolation is non-negotiable

Every Firestore query must be scoped to `orgId`. A query without an `orgId` filter is a data breach.

## Pattern for client-side queries (React hooks / real-time listeners)

```typescript
// CORRECT — always filter by orgId
const q = query(
  collection(db, 'organizations', orgId, 'events'),
  where('status', '==', 'active'),
  orderBy('date', 'desc')
);

// WRONG — missing orgId scope
const q = query(collection(db, 'events'), where('status', '==', 'active'));
```

## Pattern for server actions (Admin SDK)

```typescript
// CORRECT
const snapshot = await adminDb
  .collection('organizations')
  .doc(orgId)
  .collection('events')
  .get();

// WRONG
const snapshot = await adminDb.collection('events').get();
```

## Before writing any query, answer these three questions:
1. Is this query scoped to `organizations/{orgId}/...`? If not, fix it.
2. Does the calling code validate that the user's JWT claim `orgId` matches the `orgId` being queried?
3. Is the Firestore security rule for this collection in `firestore.rules`?

## Check current security rules coverage:
!`cat firestore.rules 2>/dev/null | grep -A3 "match /" | head -60 || echo "firestore.rules not found — create it"`
```

---

### Skill 5 — new-server-action

**File:** `.claude/skills/new-server-action/SKILL.md`

```markdown
---
name: new-server-action
description: Write a new Next.js server action for the Fello backend. Use when creating any server-side function — auth actions, Firestore writes, Baileys VM calls, or ADK agent calls.
allowed-tools: Read Grep
---

## Server action template

Every server action must follow this pattern exactly:

```typescript
'use server';

import { adminAuth, adminDb } from '@/lib/firebase-admin';
import type { ActionResult } from '@/lib/types';

export async function myAction(
  param: string,
  orgId: string  // Always receive orgId explicitly — never trust client state
): Promise<ActionResult<ReturnType>> {
  try {
    // 1. Validate inputs
    if (!param || !orgId) {
      return { data: null, error: 'Missing required fields' };
    }

    // 2. Verify orgId matches caller's JWT claim
    // (This is done at the API route level — in server actions called from
    //  authenticated pages, the orgId comes from the session token, not user input)

    // 3. Perform the operation
    const result = await adminDb
      .collection('organizations')
      .doc(orgId)
      .collection('...')
      .add({ ... });

    return { data: { id: result.id }, error: null };

  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    console.error(`[myAction] ${message}`);
    // Return friendly message — never expose raw Firebase errors
    return { data: null, error: 'Something went wrong. Please try again.' };
  }
}
```

## After writing a server action:
1. Check it uses `ActionResult<T>` return type from `lib/types.ts`
2. Check it has a try/catch
3. Check it never returns raw Firebase error codes to the client
4. Run: !`pnpm tsc --noEmit 2>&1 | tail -10`
```

---

### Skill 6 — demo-check

**File:** `.claude/skills/demo-check/SKILL.md`

```markdown
---
name: demo-check
description: Verify the PTI competition demo flow works end to end. Use when asked to check, test, or validate the demo. Also auto-invokes before any git commit that touches lib/agent.ts or the chatbot UI.
allowed-tools: Read Grep Bash(pnpm build) Bash(pnpm tsc --noEmit)
---

## The demo must work regardless of ADK status

The demo fallback in `lib/agent-demo.ts` must respond to these exact trigger phrases:
1. "set up the coordination structure for pti 2025"
2. "what's pending"
3. "remind everyone with overdue tasks"

## Check the fallback exists and has all three responses:
!`grep -c "set up the coordination\|what's pending\|remind everyone" lib/agent-demo.ts 2>/dev/null || echo "MISSING — lib/agent-demo.ts not found or incomplete"`

## Check the agent calls the fallback first:
!`grep -n "getDemoResponse" lib/agent.ts 2>/dev/null || echo "MISSING — getDemoResponse not called in agent.ts"`

## Verify the chatbot page renders:
!`grep -n "sendMessageToAgent\|ChatMessage" app/org/\[orgId\]/page.tsx 2>/dev/null | head -10`

## Run a full build to confirm nothing is broken:
!`pnpm build 2>&1 | tail -20`

## Final checklist output:
- [ ] lib/agent-demo.ts exists with 3 demo responses
- [ ] lib/agent.ts calls getDemoResponse before ADK
- [ ] Chatbot page renders without errors
- [ ] pnpm build passes
- [ ] No hardcoded colors in chatbot components
```

---

### Skill 7 — new-skill (meta-skill)

**File:** `.claude/skills/new-skill/SKILL.md`

```markdown
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
```

---

## PHASE 2 — Write All Subagent Files

Subagents run in isolated context windows. Use them for heavy research tasks (reading many files, auditing the codebase, deep security checks) so the main session stays clean. Lives in `.claude/agents/<name>.md`.

### Subagent 1 — ui-builder

**File:** `.claude/agents/ui-builder.md`

```markdown
---
name: ui-builder
description: Specialist for building Fello UI pages and components. Delegate here for tasks that involve creating or rewriting multiple components or pages at once, when the work would generate large amounts of intermediate markup that doesn't need to stay in the main context. Use for batch UI work across multiple files.
model: claude-sonnet-4-6
allowed-tools: Read Write Edit Glob Grep Bash(pnpm dlx shadcn@latest add *) Bash(pnpm tsc --noEmit) Bash(ls *) Bash(cat *)
skills:
  - build-page
  - build-component
  - add-shadcn
---

You are a specialist UI builder for the Fello frontend — an AI-powered coordination platform for volunteer organizations built with Next.js App Router and shadcn/ui.

## Non-negotiable rules

1. **No hardcoded colors.** Only shadcn CSS variables: `bg-background`, `bg-card`, `bg-muted`, `bg-primary`, `text-foreground`, `text-muted-foreground`, `border`, etc.

2. **No `<form>` tags.** Use `onClick`/`onChange` with React state.

3. **Border radius pattern for grouped lists:**
   - First item: `rounded-t-lg rounded-b-none border-b-0`
   - Middle: `rounded-none border-b-0`
   - Last: `rounded-t-none rounded-b-lg`
   - Single: `rounded-lg`

4. **shadcn only.** Install missing components with `pnpm dlx shadcn@latest add <name>`. Never use other component libraries.

5. **Every page needs** `loading.tsx` (Skeleton), `error.tsx` (Alert + retry), and empty states on all lists.

6. **All types from `lib/types.ts`.** No `any`.

7. After completing all files, run `pnpm tsc --noEmit` and fix every type error before finishing.

## Reference patterns
Read `CLAUDE.md` at the start of every task. The border radius pattern and color rules are in Sections 3.3 and 3.4.
```

---

### Subagent 2 — firestore-architect

**File:** `.claude/agents/firestore-architect.md`

```markdown
---
name: firestore-architect
description: Specialist for Firestore data model design, security rules, and tenant-isolated queries. Delegate here when designing new collections, writing or reviewing firestore.rules, or auditing existing queries for tenant safety. Use for any task that requires deep reasoning about the multi-tenant data architecture.
model: claude-sonnet-4-6
allowed-tools: Read Write Edit Glob Grep Bash(cat firestore.rules) Bash(pnpm tsc --noEmit)
skills:
  - tenant-safe-query
---

You are a Firestore and multi-tenant architecture specialist for Fello.

## Core principle: tenant isolation is the product's primary security guarantee

Fello's differentiation from competitors is that organizations own their data — no cross-tenant access is ever possible. Every data access pattern you write must enforce this at the Firestore security rules level AND at the query level.

## Data hierarchy

```
organizations/{orgId}/
  members/{memberId}
  events/{eventId}/
    tasks/{taskId}
    documents/{docId}
    outreach/{outreachId}
    whatsapp_groups/{groupId}
  settings/{doc}
```

Every document that lives inside this hierarchy must have `orgId` as a top-level field (for security rules) and an `ancestors` array (for hierarchical checks).

## Security rules principles

1. `belongsToOrg(orgId)` — checks `request.auth.token.orgId == orgId`. This is the base check for every read.
2. `isAdmin(orgId)` — extends `belongsToOrg` with role check.
3. No client can ever write to a path outside their `orgId`.
4. Deletes are admin-only or server-only (never client-callable for org-level data).

## Before finishing any task:
1. Read the current `firestore.rules` and verify coverage for any new collections
2. Run: `grep -n "orgId" firestore.rules | wc -l` — if it equals the number of match blocks, you're good
3. Confirm every new query is scoped to `organizations/{orgId}/...`
```

---

### Subagent 3 — security-auditor

**File:** `.claude/agents/security-auditor.md`

```markdown
---
name: security-auditor
description: Security audit specialist. Delegate here when asked to audit the codebase for security issues, review a new feature for vulnerabilities, check for tenant isolation violations, or verify the auth flow is correct. Use before any major feature is considered complete.
model: claude-sonnet-4-6
allowed-tools: Read Grep Glob Bash(grep -r * --include="*.ts" --include="*.tsx") Bash(cat *)
---

You are a security auditor for Fello, focused on multi-tenant isolation and auth correctness.

## What you check

### 1. Hardcoded colors (UI integrity)
```bash
grep -rn "#[0-9a-fA-F]\{3,6\}\|rgb(\|hsl(" app/ components/ --include="*.tsx" --include="*.ts"
```
Any hits are violations. Report file and line number.

### 2. Tenant isolation in Firestore queries
```bash
grep -rn "collection(db," app/ lib/ --include="*.ts" --include="*.tsx"
```
For each hit: verify the collection path goes through `organizations/{orgId}/`. Any direct collection access not scoped to orgId is a critical violation.

### 3. Server actions — check for missing try/catch and raw error exposure
```bash
grep -rn "export async function" lib/actions/ --include="*.ts"
```
For each action: verify it has try/catch and returns `ActionResult<T>` not raw errors.

### 4. Environment variables — check for hardcoded secrets
```bash
grep -rn "AIza\|firebase\|secret\|password\|key=" app/ lib/ --include="*.ts" --include="*.tsx" | grep -v ".env\|process.env\|NEXT_PUBLIC"
```
Any hits are critical violations.

### 5. `<form>` tag violations
```bash
grep -rn "<form" app/ components/ --include="*.tsx"
```
Any hits are violations (we use onClick/onChange instead).

### 6. `any` type usage
```bash
grep -rn ": any\|as any" app/ lib/ components/ --include="*.ts" --include="*.tsx"
```
Report all hits.

## Output format

Return a structured report:
- CRITICAL: things that must be fixed before demo
- WARNING: things that should be fixed but won't break the demo
- PASS: checks that passed

Always end with a count: "X critical issues, Y warnings."
```

---

### Subagent 4 — adk-integrator

**File:** `.claude/agents/adk-integrator.md`

```markdown
---
name: adk-integrator
description: Specialist for the Google ADK + Gemini agent layer integration. Delegate here for tasks involving the AI agent, agent skills (communication/tasks/members/events/documents/outreach), the demo fallback, or the chatbot response format. Use when building or debugging anything in lib/agent.ts or lib/agent-skills/.
model: claude-sonnet-4-6
allowed-tools: Read Write Edit Grep Glob Bash(pnpm tsc --noEmit) Bash(cat lib/agent.ts) Bash(ls lib/agent-skills/)
skills:
  - demo-check
  - new-server-action
  - tenant-safe-query
---

You are the AI agent integration specialist for Fello. You own the layer between the web UI and the Google ADK + Gemini agent.

## Agent architecture

```
User message (web UI or WhatsApp)
  → lib/agent.ts (orchestrator)
    → lib/agent-demo.ts (check fallback FIRST)
    → Google ADK / Gemini (if no fallback match)
      → lib/agent-skills/communication.ts
      → lib/agent-skills/tasks.ts
      → lib/agent-skills/members.ts
      → lib/agent-skills/events.ts
      → lib/agent-skills/documents.ts
      → lib/agent-skills/outreach.ts
```

## The demo fallback is mandatory and must run FIRST

```typescript
// In lib/agent.ts — this check must come before any ADK call
const demoResponse = getDemoResponse(message);
if (demoResponse) return demoResponse;
// Only then call ADK
```

## Agent skills are TypeScript functions, not ADK "skills"

Each file in `lib/agent-skills/` exports typed async functions. The ADK agent calls these as tools. Every function:
- Receives `orgId` as an explicit parameter
- Validates `orgId` is non-empty
- Uses the Firebase Admin SDK (not client SDK)
- Returns `ActionResult<T>`
- Has try/catch with friendly error messages

## Baileys VM calls

All WhatsApp operations call `BAILEYS_API_URL` with `Authorization: Bearer ${BAILEYS_API_SECRET}`.

```typescript
const res = await fetch(`${process.env.BAILEYS_API_URL}/send-message`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${process.env.BAILEYS_API_SECRET}`,
  },
  body: JSON.stringify({ jid, message, orgId }),
});
```

If `BAILEYS_API_URL` is not set, log a warning and return a mock success — don't crash the demo.

## After any change to the agent layer, run demo-check:
Verify the three demo phrases still trigger the fallback correctly.
```

---

### Subagent 5 — test-runner

**File:** `.claude/agents/test-runner.md`

```markdown
---
name: test-runner
description: Runs type checks, build validation, and the demo verification checklist. Delegate here when asked to verify, test, or confirm the project builds correctly. Use after completing any phase of work.
model: claude-haiku-4-5-20251001
allowed-tools: Bash(pnpm tsc --noEmit) Bash(pnpm build) Bash(grep -rn * --include="*.tsx" --include="*.ts") Bash(ls *) Read
skills:
  - demo-check
---

You are the test and validation runner for the Fello project.

## Run these checks in order

1. Type check:
   `pnpm tsc --noEmit 2>&1`
   Report every error. Do not proceed if there are errors — return them to the parent agent.

2. Hardcoded color check:
   `grep -rn "#[0-9a-fA-F]\{3,6\}\|rgb(\|hsl(" app/ components/ --include="*.tsx" 2>/dev/null`
   Any hits = violations. Report them.

3. Form tag check:
   `grep -rn "<form" app/ components/ --include="*.tsx" 2>/dev/null`
   Any hits = violations.

4. Missing loading.tsx check:
   `find app/ -name "page.tsx" | while read f; do dir=$(dirname $f); [ ! -f "$dir/loading.tsx" ] && echo "MISSING loading.tsx: $dir"; done`

5. Missing error.tsx check:
   `find app/ -name "page.tsx" | while read f; do dir=$(dirname $f); [ ! -f "$dir/error.tsx" ] && echo "MISSING error.tsx: $dir"; done`

6. Demo fallback check (from demo-check skill):
   `grep -c "getDemoResponse" lib/agent.ts 2>/dev/null || echo "MISSING"`

7. Build check:
   `pnpm build 2>&1 | tail -30`

## Return a pass/fail summary. If anything fails, list exactly what needs to be fixed.
```

---

## PHASE 3 — Write Slash Commands

Slash commands are single markdown files in `.claude/commands/`. They orchestrate multi-step workflows. Write each one now.

### Command 1 — build-section

**File:** `.claude/commands/build-section.md`

```markdown
Build the Fello frontend section specified in $ARGUMENTS.

Steps:
1. Read CLAUDE.md and identify which routes are in this section.
2. Spawn the ui-builder subagent to build all pages and components for this section.
3. After ui-builder completes, spawn the security-auditor subagent to check the new code.
4. Fix any CRITICAL issues reported by the auditor.
5. Spawn the test-runner subagent to run type check and build.
6. Fix any errors reported by test-runner.
7. Report what was built and confirm it passes all checks.

Valid section names: events-dashboard, event-detail, members, settings, chatbot, auth-flow, onboarding
```

---

### Command 2 — security-audit

**File:** `.claude/commands/security-audit.md`

```markdown
Run a full security audit of the Fello codebase.

Spawn the security-auditor subagent with this prompt:
"Run a complete security audit of the entire codebase. Check all six categories. Report every finding with file name and line number. Classify each as CRITICAL, WARNING, or PASS."

After the subagent returns, present the full report. For each CRITICAL issue, fix it immediately in the main session.
```

---

### Command 3 — run-demo

**File:** `.claude/commands/run-demo.md`

```markdown
Verify the PTI competition demo is ready to run.

1. Spawn the adk-integrator subagent: "Verify the demo fallback is complete and all three PTI demo trigger phrases return hardcoded responses. Report pass or fail for each phrase."

2. Spawn the test-runner subagent: "Run all checks and report pass/fail."

3. If everything passes, print:
   ✅ Demo ready. The following phrases trigger the hardcoded PTI flow:
   - "set up the coordination structure for pti 2025"
   - "what's pending"
   - "remind everyone with overdue tasks"
   
   Quantified automation count: Fello automated 7 coordination actions that would have taken 45 minutes manually.

4. If anything fails, list what needs to be fixed with specific file and line references.
```

---

### Command 4 — type-check

**File:** `.claude/commands/type-check.md`

```markdown
Run a type check and fix all errors.

1. Run: `pnpm tsc --noEmit`
2. For each error, read the file, understand the type error, and fix it.
3. Re-run after fixes.
4. Repeat until `pnpm tsc --noEmit` exits with 0 errors.
5. Report: "Type check passes. 0 errors."
```

---

### Command 5 — handoff

**File:** `.claude/commands/handoff.md`

```markdown
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
```

---

## PHASE 4 — Write `settings.json`

**File:** `.claude/settings.json`

This file configures hooks and pre-approved permissions. Write it exactly as follows:

```json
{
  "permissions": {
    "allow": [
      "Bash(pnpm *)",
      "Bash(mkdir -p *)",
      "Bash(touch *)",
      "Bash(cat *)",
      "Bash(ls *)",
      "Bash(grep -rn *)",
      "Bash(find app/ *)",
      "Bash(find lib/ *)",
      "Bash(find components/ *)",
      "Bash(git status)",
      "Bash(git diff *)",
      "Bash(git add *)",
      "Bash(git log --oneline *)"
    ],
    "deny": [
      "Bash(git push --force*)",
      "Bash(rm -rf *)",
      "Bash(git reset --hard *)",
      "Bash(npm *)",
      "Bash(yarn *)"
    ]
  },
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "FILE=$(echo $CLAUDE_TOOL_INPUT | node -e \"const d=JSON.parse(require('fs').readFileSync('/dev/stdin','utf8')); console.log(d.file_path||d.path||'')\" 2>/dev/null); if [[ \"$FILE\" == *.tsx ]] || [[ \"$FILE\" == *.ts ]]; then grep -n '#[0-9a-fA-F]\\{3,6\\}\\|rgb(\\|hsl(' \"$FILE\" 2>/dev/null && echo \"COLOR VIOLATION in $FILE\" || true; fi"
          }
        ]
      },
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "FILE=$(echo $CLAUDE_TOOL_INPUT | node -e \"const d=JSON.parse(require('fs').readFileSync('/dev/stdin','utf8')); console.log(d.file_path||d.path||'')\" 2>/dev/null); if [[ \"$FILE\" == *.tsx ]]; then grep -n '<form' \"$FILE\" 2>/dev/null && echo \"FORM TAG VIOLATION in $FILE\" || true; fi"
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "echo '=== Fello Session Start ===' && echo 'Reading project state...' && git status 2>/dev/null | head -20 && echo '' && echo 'Type errors:' && pnpm tsc --noEmit 2>&1 | grep 'error TS' | wc -l | xargs -I{} echo '{} type errors' && echo '' && [ -f HANDOFF.md ] && echo '⚠️  HANDOFF.md exists — read it before starting.' || echo 'No handoff document.'"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "ERRORS=$(pnpm tsc --noEmit 2>&1 | grep 'error TS' | wc -l); if [ \"$ERRORS\" -gt 0 ]; then echo \"⚠️  $ERRORS type errors remain. Run /type-check to fix them.\"; fi"
          }
        ]
      }
    ]
  }
}
```

**What these hooks do:**
- `PostToolUse Write|Edit` — After every file write, immediately checks for hardcoded color violations and `<form>` tags. Reports violations in the terminal so they are caught immediately.
- `SessionStart` — On every session start, prints git status and the current type error count so the agent knows the project's health instantly. Also warns if a `HANDOFF.md` exists.
- `Stop` — After each response turn, warns if type errors exist. Keeps type errors visible so they never accumulate unnoticed.

---

## PHASE 5 — Application Code

Now build the actual application. Use the skills and subagents you just created.

### Step 5.1 — Foundation files

Build these in the main session (small, fast, critical):

1. `lib/types.ts` — all TypeScript interfaces (Organization, Member, FelloEvent, Task, Document, OutreachLog, WhatsAppGroup, ChatMessage, AgentCard, ActionButtonsCard, ActionResult, FelloCustomClaims, UserRole, EventStatus, TaskStatus, OutreachStatus). See CLAUDE.md Section 1 for full data model.

2. `.env.example` — all environment variable keys with empty values. See CLAUDE.md Section 16.

3. `lib/firebase-admin.ts` — Firebase Admin SDK singleton (initializeApp with cert, export adminAuth and adminDb).

4. `lib/utils.ts` — ensure cn() from clsx+tailwind-merge exists.

5. `firestore.rules` — full tenant-isolated security rules. See CLAUDE.md Section 2 for the complete rules.

### Step 5.2 — Auth layer

In the main session:

1. Rewrite `lib/actions/auth.ts` with these server actions:
   - `sendWhatsAppOtp(phoneNumber)` → calls Baileys VM → returns `{ sessionId }`
   - `verifyWhatsAppOtp(sessionId, otp, phoneNumber)` → verifies OTP → creates Firebase custom token with `{ orgId, role, tenantId }` claims → returns `{ customToken }`
   - `createOrganization(name, slug, adminUid)` → Firestore write + set admin claims → returns `{ orgId }`
   - `joinOrganization(orgSlug, uid)` → Firestore write + set member claims → returns `{ orgId }`
   - `setCustomClaims(uid, claims)` → Firebase Admin setCustomUserClaims → internal helper

2. Rewrite `hooks/use-auth.ts` to expose `{ user, claims, loading, signOut, refreshToken }`. Listen to `onAuthStateChanged`, call `getIdTokenResult()` to extract custom claims.

### Step 5.3 — Agent layer

Delegate to the **adk-integrator** subagent:

> "Build the complete agent layer for Fello. This includes:
> 1. `lib/agent-demo.ts` — hardcoded PTI demo fallback with responses for the 3 demo phrases
> 2. `lib/agent-skills/communication.ts` — sendWhatsAppMessage, createWhatsAppGroup, addMemberToGroup, broadcastMessage
> 3. `lib/agent-skills/tasks.ts` — createTask, updateTaskStatus, listTasks, assignTask
> 4. `lib/agent-skills/members.ts` — lookupMember, listMembers, getMemberWhatsappJid
> 5. `lib/agent-skills/events.ts` — getEventDetails, updateEventStatus, listUpcomingEvents
> 6. `lib/agent-skills/documents.ts` — createDocumentStub, linkDocument, listDocuments
> 7. `lib/agent-skills/outreach.ts` — draftOutreachMessage, logOutreachAttempt
> 8. `lib/agent.ts` — orchestrator that checks demo fallback first, then calls ADK/Gemini with the skill functions as tools
> All functions must use ActionResult<T> return types from lib/types.ts and scope all Firestore queries to orgId."

### Step 5.4 — Missing routes (batch)

Delegate to the **ui-builder** subagent:

> "Build all missing routes for the Fello frontend. Read CLAUDE.md completely first — especially the UI rules in Section 3. Then build:
>
> 1. `app/org/[orgId]/events/page.tsx` — events dashboard with All/Planning/Active/Completed filter tabs, event list with grouped border radius pattern, New Event Sheet form, loading.tsx, error.tsx, empty state
>
> 2. `app/org/[orgId]/events/[eventId]/page.tsx` — event detail with 6 tabs (Overview, Tasks, Members, WhatsApp Groups, Documents, Outreach). Each tab is a separate component in `app/org/[orgId]/events/[eventId]/components/`. See CLAUDE.md Section 10 for what each tab contains. loading.tsx and error.tsx for the main page.
>
> 3. `app/org/[orgId]/members/page.tsx` — member directory with role badges, invite Sheet, change role, loading.tsx, error.tsx, empty state
>
> 4. `app/org/[orgId]/settings/page.tsx` — org name/slug edit, WhatsApp number section, danger zone with confirmation dialog
>
> After building, run `pnpm tsc --noEmit` and fix all type errors."

### Step 5.5 — Dashboard chatbot

In the main session (this is the primary UI — build it carefully):

Build `/org/[orgId]/page.tsx` as the chatbot dashboard:
- Full height content area, messages scroll upward, input pinned to bottom
- User messages: right-aligned, `bg-primary text-primary-foreground`
- Agent messages: left-aligned, no bubble, supports text + structured cards
- Structured card types: TaskCard, MemberCard, EventCard, ActionButtonsCard — each a separate component in `components/chatbot/`
- Quick action chips when conversation is empty (4 PTI-specific suggestions)
- Connects to `lib/agent.ts` via `sendMessageToAgent()`
- In-memory conversation state (React useState — no localStorage)
- `loading.tsx` and `error.tsx`

### Step 5.6 — Auth pages polish

In the main session:

1. `/sign-in` — 2-step WhatsApp OTP flow (phone entry → OTP entry with 60s resend cooldown)
2. `/setup` — display name entry for new users
3. `/` (org selector) — redirect based on claims: has orgId → dashboard, no orgId → show create/join options, not authed → sign-in
4. `/org/new` — org name + slug with real-time availability check
5. `/org/join` — slug/invite code input

### Step 5.7 — Sidebar update

Update `components/layout/app-sidebar.tsx`:
- Org name at top (from Firestore, real-time listener)
- Nav: Dashboard, Events (with real-time collapsible event list), Members
- Bottom: Settings link
- User section: display name, role badge, sign out
- Active route highlighting via `usePathname()`

### Step 5.8 — Waitlist page polish

Polish `app/(bare)/waitlist/page.tsx`:
- Phone + email capture → Firestore `waitlist/` collection write
- `ShareButton.tsx` — Web Share API with clipboard fallback
- `UserProfile.tsx` — show authed user's info if available
- Success state after submission

---

## PHASE 6 — Final Validation

Run `/run-demo` and `/security-audit` slash commands.

Then run the test-runner subagent:
> "Run all checks. Return a full pass/fail report."

Fix every CRITICAL issue. Fix every type error.

When the test-runner reports zero type errors, zero critical security issues, zero color violations, zero form tag violations, all loading.tsx files present, all error.tsx files present, and the demo fallback verified — the build is complete.

Run `/handoff` to write the session handoff document.

---

## NOTES

- Use subagents for any task that reads many files or generates large intermediate output. This keeps the main context window clean for decision-making.
- The `Stop` hook will warn you after every response if type errors exist. Don't ignore it.
- The `PostToolUse` hook will catch color violations immediately when you write a file. Fix them before moving on.
- The `SessionStart` hook gives you project health at the start of every session. Read it.
- Run `/handoff` at the end of every session, even incomplete ones.
- The demo fallback is the highest-priority deliverable. Everything else can be rough — the demo must be bulletproof.
