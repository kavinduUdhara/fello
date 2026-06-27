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
