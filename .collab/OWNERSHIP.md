# File Ownership

## Claude Code owns (write access)
- app/org/[orgId]/events/**
- app/org/[orgId]/members/**
- app/org/[orgId]/settings/**
- components/layout/app-sidebar.tsx
- components/chatbot/**
- app/org/[orgId]/page.tsx (chatbot dashboard)

## Antigravity owns (write access)
- app/(bare)/sign-in/**
- app/(bare)/setup/**
- app/(bare)/org/new/**
- app/(bare)/org/join/**
- lib/actions/auth.ts
- lib/agent.ts
- lib/agent-skills/**
- lib/agent-demo.ts

## Shared (read‑only for both — changes go through main branch only)
- lib/types.ts
- firestore.rules
- CLAUDE.md
- .collab/OWNERSHIP.md

## Message bus
- .collab/MESSAGES.md  ← both agents append here, never overwrite
- .collab/STATUS.md    ← each agent updates only their own section
