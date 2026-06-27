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
