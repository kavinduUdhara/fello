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
