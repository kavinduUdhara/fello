# Fello Agent — Multi-Agent Coordination + Decision Intelligence

Built on **Google ADK**. Models run on **NVIDIA NIM** (GLM primary, MiniMax
fallback) via LiteLlm. This is the "brain" of Fello: it executes coordination
work *and* analyzes an org's own data to recommend the next decision.

## Architecture

```
fello_coordinator (orchestrator — lean, demo-critical action tools)
  ├── extract_structured_items  → fello_extraction  (messy WhatsApp chat → tasks)
  ├── generate_event_summary    → fello_summary     (event wrap-ups)
  └── community_insights        → fello_insights    (patterns, risks, next-best-action)
```

**Why multi-agent.** A single agent past ~10–15 tools suffers context
degradation — it starts calling the wrong tool or hallucinating parameters
(`FELLO_ADK_CAPABILITIES_AND_SECURITY.md`). The orchestrator keeps only the
high-frequency coordination actions; specialized, high-volume cognition is pushed
into sub-agents exposed as tools. Sub-agents share the orchestrator's invocation
`session.state`, so verified identity flows through without being re-sent.

## Security model (the moat)

Tenant/org scope is **bound from `session.state`, never from model output.** The
server populates `tenant_id`, `org_id`, `user_id`, `capabilities` from the
verified JWT (dashboard) or verified WhatsApp identity *before* the agent runs.

| Layer | File | Guarantee |
|---|---|---|
| Identity binding | `context.py` | Tools read scope from context; missing scope fails closed |
| Capability gating | `authz.py` | Same JWT capabilities as the web app gate every write |
| Tool guard + logging | `observability.py` | `before_tool_callback` blocks unscoped calls; every call logs `tenantId`/`orgId`/`userId` |
| Query scoping | `skills/*.py` | Every Firestore/Postgres read filters by `org_id` from context |

A prompt-injected message **cannot** make the agent cross tenants — it never sees
or supplies the org id. See `authz.require()` for the per-capability checks.

## Skills

- **Coordination:** tasks, members, events, communication (Baileys gateway),
  outreach, document stubs.
- **Retrieval (`retrieval.py`):** weighted PostgreSQL full-text search
  (filename > AI description > AI summary), scoped by org + event. No vector DB —
  fast, explainable, tenant-isolated.
- **Decision intelligence (`insights.py`):** `event_health`,
  `member_engagement`, `outreach_funnel` — each returns raw numbers **plus** a
  plain-language recommendations list. This is the "Decision Intelligence" theme
  hook for the competition.
- **WhatsApp auth (`whatsapp_auth.py`):** gateway-side helpers implementing the
  three-category message gate and two-path group authentication from
  `FELLO_DRIVE_AND_WHATSAPP_SECURITY.md`. Not exposed to the model.

## Demo

`demo_fallback.py` provides a deterministic scripted PTI flow (CLAUDE.md §8.4)
the server can switch to if the live agent errors or is slow, ending on a
quantified automation count.

## Server integration

Before invoking the agent, build the session state from verified context:

```python
from context import build_session_state

state = build_session_state(
    tenant_id=claims["tenantId"],
    org_id=internal_org_id,                 # from the verified JWT, never the URL/body
    user_id=uid,
    capabilities=claims["orgs"][internal_org_id]["capabilities"],
    event_id=current_event_id,              # optional
    channel="dashboard",                    # or "whatsapp"
)
# pass `state` as the ADK session state / state_delta for the run
```

Use `DatabaseSessionService` (not `InMemorySessionService`) in production so
conversation state survives Cloud Run restarts.

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env && # fill in keys
adk run            # or: python -c "from agent import root_agent"
```

## Deploy

```bash
python deploy.py   # → Vertex AI Agent Engine; prints AGENT_ENGINE_RESOURCE_NAME
```
