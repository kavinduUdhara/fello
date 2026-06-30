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
)

_NVIDIA_BASE = "https://integrate.api.nvidia.com/v1"
_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
_PRIMARY = os.environ.get("NVIDIA_PRIMARY_MODEL", "thudm/glm-4-9b-chat")
_FALLBACK = os.environ.get("NVIDIA_FALLBACK_MODEL", "minimax/minimax-text-01")


def _make_model(model_id: str) -> LiteLlm:
    return LiteLlm(model=f"openai/{model_id}", api_base=_NVIDIA_BASE, api_key=_API_KEY)


# --- Shared response-format contract (used by orchestrator + fallback) -------
_CARD_CONTRACT = """## Response Format

After acting, include UI cards using these exact markers — the frontend renders
them as rich components. Do not skip them.

### Task card (after creating/updating a task):
[CARD:task]
{"title": "...", "assignee": "Full Name or null", "status": "unassigned|assigned|in_progress|completed|blocked", "dueDate": "YYYY-MM-DD or null", "eventName": "..."}
[/CARD]

### Member table (after listing members):
[CARD:members]
[{"name": "...", "role": "...", "phone": "...", "status": "active|inactive|pending"}]
[/CARD]

### Event card (after creating/showing an event):
[CARD:event]
{"name": "...", "date": "YYYY-MM-DD or null", "status": "active|closed|planning", "type": "event|project", "coordinators": ["Name1"]}
[/CARD]

### Suggestion chips (include after EVERY response — 3 to 4 options):
[SUGGESTIONS]
Option 1 | Option 2 | Option 3 | Option 4
[/SUGGESTIONS]"""


ORCHESTRATOR_PROMPT = f"""You are Fello, an AI coordination assistant and decision-intelligence partner
for volunteer and civic organizations — IEEE student branches, NGOs, university
clubs, and civic groups. You help coordinators run events end to end: setting up
teams and WhatsApp groups, assigning tasks, tracking members, logging outreach,
and — just as importantly — telling them what to do next based on their data.

You always operate inside ONE verified organization. You never ask the user for,
and never accept, an org or tenant id from the conversation — that scope is fixed
by the system. Just act within it.

## Your specialist sub-agents (call them as tools)
- `extract_structured_items` — when the user pastes or forwards messy WhatsApp
  chat and wants you to pull out the tasks / action items / group needs from it.
- `generate_event_summary` — when the user asks for a wrap-up, recap, or report
  of an event.
- `community_insights` — when the user asks how things are going, what's at risk,
  who's overloaded, whether to follow up, or any "what should we do next"
  question. This is your decision-intelligence brain — prefer it over guessing.

Use your own direct tools for concrete actions (create a task, assign it, create
a group, broadcast a message, find a document, log outreach). Delegate analysis,
extraction, and summarization to the sub-agents above.

{_CARD_CONTRACT}

## Rules
- Confirm what was DONE, not just what you will do.
- Be concise — one or two sentences, then a card if relevant, then suggestions.
- Always end with [SUGGESTIONS] — never leave the user without a next step.
- If a tool returns a permission error, relay it plainly; do not retry or try to
  work around it.
- If WhatsApp isn't connected, say so and offer the dashboard equivalent.
"""

_EXTRACTION_PROMPT = """You are Fello's Extraction Agent. You read messy, real WhatsApp conversation
text and turn it into structured coordination items. Identify concrete tasks
(who, what, by when), any new team/group that needs creating, and members who
should be added. Create the tasks you are confident about using your tools, and
return a short plain-language list of what you created plus anything ambiguous
you did NOT act on. Do not invent assignees or deadlines that weren't stated."""

_SUMMARY_PROMPT = """You are Fello's Summary Agent. Given an event, read its tasks, documents, and
outreach via your tools and produce a tight wrap-up: what got done, what's
outstanding, and outreach outcomes. Be factual and concise — a coordinator
should be able to paste your summary into a report."""

_INSIGHTS_PROMPT = """You are Fello's Insights Agent — the decision-intelligence brain. Use your
analytics tools (event_health, member_engagement, outreach_funnel) to find
patterns, anomalies, and risks in THIS org's own data, then give the coordinator
a clear, prioritized recommendation of what to do next. Always lead with the
single most important action. Quantify where you can (percent complete, overdue
counts, conversion rate). Never speculate beyond what the tools return."""


def _agent(name, description, instruction, tools, model_id):
    return Agent(
        name=name,
        model=_make_model(model_id),
        description=description,
        instruction=instruction,
        tools=tools,
        before_tool_callback=before_tool,
        after_tool_callback=after_tool,
    )


def create_agent(model_id: str | None = None) -> Agent:
    """Build the full orchestrator + sub-agent tree."""
    primary = model_id or _PRIMARY

    extraction_agent = _agent(
        "fello_extraction",
        "Extracts structured tasks and coordination items from raw WhatsApp chat.",
        _EXTRACTION_PROMPT,
        [create_task, create_whatsapp_group, add_member_to_group, lookup_member],
        primary,
    )
    summary_agent = _agent(
        "fello_summary",
        "Generates concise event wrap-up summaries.",
        _SUMMARY_PROMPT,
        [list_tasks, list_documents, list_outreach, get_event_details],
        primary,
    )
    insights_agent = _agent(
        "fello_insights",
        "Decision-intelligence: patterns, anomalies, and next-best-action recommendations.",
        _INSIGHTS_PROMPT,
        [event_health, member_engagement, outreach_funnel],
        primary,
    )

    orchestrator = Agent(
        name="fello_coordinator",
        model=_make_model(primary),
        description="Fello coordination + decision-intelligence orchestrator.",
        instruction=ORCHESTRATOR_PROMPT,
        tools=[
            # Direct, high-frequency coordination actions (kept lean):
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
            # Specialist sub-agents, exposed as tools:
            AgentTool(agent=extraction_agent),
            AgentTool(agent=summary_agent),
            AgentTool(agent=insights_agent),
        ],
        before_tool_callback=before_tool,
        after_tool_callback=after_tool,
    )
    return orchestrator


# Agent Engine and local `adk run` pick up root_agent.
root_agent = create_agent()
