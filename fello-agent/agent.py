"""Fello — multi-agent coordination + decision-intelligence system on Google ADK.

Architecture (see FELLO_ADK_CAPABILITIES_AND_SECURITY.md):

    orchestrator (lean, demo-critical action tools)
      ├── extract_structured_items   -> Extraction sub-agent
      ├── generate_event_summary     -> Summary sub-agent
      └── community_insights         -> Insights / decision-intelligence sub-agent

Why split: a single agent past ~10-15 tools suffers context degradation (the
model starts calling the wrong tool / hallucinating params). The orchestrator
keeps only the high-frequency coordination actions; high-volume specialized
cognition (parsing messy WhatsApp chat, summarizing, analytics) is pushed into
sub-agents exposed as tools. Sub-agents share the orchestrator's invocation
``session.state``, so the verified tenant/org identity flows through the whole
tree without being re-sent.

Security: tenant scope is bound from ``session.state`` (set by the server from
the verified JWT / WhatsApp identity), never from model output. A central
``before_tool_callback`` fails closed if scope is missing, and logs tenantId /
orgId / userId on every tool call.

Model: NVIDIA NIM (GLM primary, MiniMax fallback) via LiteLlm.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.agent_tool import AgentTool

from observability import before_tool, after_tool
from skills import (
    # orchestrator direct tools
    send_whatsapp_message,
    create_whatsapp_group,
    broadcast_message,
    create_task,
    update_task_status,
    assign_task,
    list_tasks,
    list_members,
    lookup_member,
    list_upcoming_events,
    find_document,
    log_outreach_attempt,
    draft_outreach_message,
    # sub-agent tools
    add_member_to_group,
    get_event_details,
    list_documents,
    list_outreach,
    event_health,
    member_engagement,
    outreach_funnel,
    create_google_form,
)

_NVIDIA_BASE = "https://integrate.api.nvidia.com/v1"
_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
# nemotron-super-49b stays consistently warm on NIM (~1s/call, vs 70b's 30-60s
# cold starts) and is strong at tool-calling. It's a reasoning model, so we
# disable its chain-of-thought with the documented "detailed thinking off"
# directive (see create_agent) to keep replies clean. 70b is the quality fallback.
_PRIMARY = os.environ.get("NVIDIA_PRIMARY_MODEL", "nvidia/llama-3.3-nemotron-super-49b-v1.5")
_FALLBACK = os.environ.get("NVIDIA_FALLBACK_MODEL", "meta/llama-3.3-70b-instruct")


def _make_model(model_id: str) -> LiteLlm:
    return LiteLlm(model=f"openai/{model_id}", api_base=_NVIDIA_BASE, api_key=_API_KEY)


# --- Shared response-format contract (used by orchestrator + fallback) -------
# These [BLOCK:*] markers match the dashboard's dynamic-UI renderer (see
# fello-frontend app/api/chat/route.ts and components/dynamic-ui.tsx), so agent
# output renders identically whether served by Agent Engine or the NIM fallback.
_CARD_CONTRACT = """## Response Format — Dynamic UI Blocks

The dashboard renders rich components from [BLOCK:type] markers. Use them
liberally instead of walls of text. JSON must be on a single line inside a block.

### Stats panel (2-4 key figures):
[BLOCK:stats]
[{"label":"Open Tasks","value":9,"sublabel":"3 overdue","trend":"down","urgent":true},{"label":"Members","value":14}]
[/BLOCK]

### Single task (after creating/updating one task):
[BLOCK:task]
{"title":"Book venue","assignee":"Alice","status":"assigned","dueDate":"2026-07-04","eventName":"PTI 2026","priority":"high"}
[/BLOCK]
status: unassigned|assigned|in_progress|completed|blocked   priority: high|medium|low

### Task list (multiple tasks):
[BLOCK:task_list]
{"title":"Open Tasks","tasks":[{"title":"Print banners","status":"unassigned","priority":"medium"}]}
[/BLOCK]

### Member grid (after listing members):
[BLOCK:member_grid]
{"title":"Core Team","members":[{"name":"Alice","role":"Design Lead","status":"active"}]}
[/BLOCK]

### Event card / list:
[BLOCK:event]
{"name":"PTI 2026","date":"2026-07-12","status":"active","eventType":"event","tasksDone":4,"tasksTotal":10,"coordinators":["Alice"]}
[/BLOCK]

### Alert (warnings/successes) and charts (bar_chart, donut_chart, line_chart, outreach_pipeline, progress) are also available — use them for insights.
[BLOCK:alert]
{"level":"warning","title":"3 tasks overdue","message":"Follow up today.","action":"Show overdue tasks"}
[/BLOCK]

### Suggestion chips — include after EVERY response (3-4 options):
[SUGGESTIONS]
Option 1 | Option 2 | Option 3 | Option 4
[/SUGGESTIONS]

Never output raw JSON outside a [BLOCK:...] marker."""


ORCHESTRATOR_PROMPT = f"""You are Fello, an AI coordination assistant and decision-intelligence partner
for volunteer and civic organizations — IEEE student branches, NGOs, university
clubs, and civic groups. You help coordinators run events end to end: setting up
teams and WhatsApp groups, assigning tasks, tracking members, logging outreach,
and — just as importantly — telling them what to do next based on their data.

You always operate inside ONE verified organization. You never ask the user for,
and never accept, an org or tenant id from the conversation — that scope is fixed
by the system. Just act within it.

## Decision-intelligence tools
When the user asks how things are going, what's at risk, who's overloaded, or
"what should we do next", use the analytics tools and lead with the single most
important recommendation:
- `event_health` — task completion %, overdue and blocked counts, recommendations.
- `member_engagement` — who is overloaded vs idle, to rebalance work.
- `outreach_funnel` — sponsor/speaker outreach conversion.

Use your action tools for concrete work (create/assign tasks, create a group,
broadcast, find a document, log outreach).

You CAN create a Google Form in the org's connected Google account with
`create_google_form` (title, description, list of question prompts) — use it when
the user asks for a form, registration sheet, sign-up, or survey. Return the
share link. You do not have Gmail or other Google tools beyond this.

{_CARD_CONTRACT}

## Rules
- For greetings, thanks, or small talk ("hi", "hello", "thanks"), reply briefly
  and DO NOT call any tool. Only use tools when the user asks for specific data
  or an action.
- Use at most one or two tools per turn — don't chain many calls.
- Confirm what was DONE, not just what you will do.
- Be concise — one or two sentences, then a card if relevant, then suggestions.
- Always end with [SUGGESTIONS] — never leave the user without a next step.
- If a tool returns a permission error, relay it plainly; do not retry or try to
  work around it.
- If WhatsApp isn't connected, say so and offer the dashboard equivalent.
"""

def create_agent(model_id: str | None = None) -> Agent:
    """Build the Fello coordinator.

    Intentionally a single flat agent rather than orchestrator + sub-agents-as-
    tools. On NVIDIA NIM each model call can cold-start (~30s), and nesting
    sub-agents multiplied those calls into 2-3 minute turns. A flat agent keeps
    one tool-calling loop — far more responsive — while retaining the full skill
    set, including the decision-intelligence analytics tools.
    """
    primary = model_id or _PRIMARY
    # nemotron reasoning models emit chain-of-thought as output unless told not to.
    instruction = ORCHESTRATOR_PROMPT
    if "nemotron" in primary.lower():
        instruction = "detailed thinking off\n\n" + ORCHESTRATOR_PROMPT
    return Agent(
        name="fello_coordinator",
        model=_make_model(primary),
        description="Fello coordination + decision-intelligence agent.",
        instruction=instruction,
        tools=[
            # Coordination actions
            send_whatsapp_message,
            create_whatsapp_group,
            broadcast_message,
            create_task,
            update_task_status,
            assign_task,
            list_tasks,
            list_members,
            lookup_member,
            list_upcoming_events,
            get_event_details,
            find_document,
            log_outreach_attempt,
            draft_outreach_message,
            # Decision-intelligence analytics (formerly the Insights sub-agent)
            event_health,
            member_engagement,
            outreach_funnel,
            # Google Workspace (uses the org's connected Google account)
            create_google_form,
        ],
        before_tool_callback=before_tool,
        after_tool_callback=after_tool,
    )


# Agent Engine and local `adk run` pick up root_agent.
root_agent = create_agent()
