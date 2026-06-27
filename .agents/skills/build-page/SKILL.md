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
