"""Per-tenant observability + a central tool-call security guard.

FELLO_ADK_CAPABILITIES_AND_SECURITY.md ("Per-tenant observability from day one")
recommends wrapping every tool registration so that tenantId, orgId and the
acting userId are logged alongside every tool invocation — cheap to build now,
expensive to retrofit. We do this once, centrally, via ADK's
``before_tool_callback`` / ``after_tool_callback`` rather than wrapping each of
the ~25 skill functions by hand.

``before_tool`` also acts as the last-line security guard: if a tool is ever
reached without a verified tenant/org in session state, it short-circuits the
call (returning a dict from before_tool_callback replaces the tool result) so a
misconfigured invocation can never run an unscoped data access.

``after_tool`` increments the demo automation counter (CLAUDE.md §8.4) on each
successful state-changing action, so the demo can end on a quantified number.
"""

from __future__ import annotations

import json
import logging
import time

from context import (
    STATE_TENANT_ID,
    STATE_ORG_ID,
    STATE_USER_ID,
    STATE_CHANNEL,
    STATE_AUTOMATION_COUNT,
)

log = logging.getLogger("fello.agent")
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(_h)
    log.setLevel(logging.INFO)

# Tools whose success counts as an automated coordination action for the demo
# counter. Read-only lookups (list_*, lookup_*, get_*, find_*) are excluded.
STATE_CHANGING_TOOLS = {
    "send_whatsapp_message",
    "create_whatsapp_group",
    "add_member_to_group",
    "broadcast_message",
    "create_task",
    "update_task_status",
    "assign_task",
    "update_event_status",
    "create_document_stub",
    "link_document",
    "log_outreach_attempt",
}


def _tool_name(tool) -> str:
    return getattr(tool, "name", None) or getattr(tool, "__name__", str(tool))


def _scope(state) -> dict:
    return {
        "tenantId": _safe(state, STATE_TENANT_ID),
        "orgId": _safe(state, STATE_ORG_ID),
        "userId": _safe(state, STATE_USER_ID),
        "channel": _safe(state, STATE_CHANNEL),
    }


def before_tool(tool, args, tool_context):
    """Log + guard every tool call. Return a dict to short-circuit the tool."""
    name = _tool_name(tool)
    scope = _scope(tool_context.state)
    log.info(json.dumps({"event": "tool_call", "tool": name, **scope}))

    if not scope["tenantId"] or not scope["orgId"]:
        # Fail closed: never let a tool run without a verified scope.
        log.warning(json.dumps({"event": "tool_blocked", "tool": name, "reason": "no_scope"}))
        return {
            "success": False,
            "error": "No verified organization context for this request.",
        }
    return None


def after_tool(tool, args, tool_context, tool_response):
    """Log the outcome and bump the demo automation counter on success."""
    name = _tool_name(tool)
    ok = _is_ok(tool_response)
    log.info(
        json.dumps(
            {"event": "tool_result", "tool": name, "ok": ok, **_scope(tool_context.state)}
        )
    )

    if ok and name in STATE_CHANGING_TOOLS:
        try:
            current = tool_context.state.get(STATE_AUTOMATION_COUNT) or 0
            tool_context.state[STATE_AUTOMATION_COUNT] = current + 1
        except Exception:  # state is best-effort for the counter; never break a tool
            pass
    return None


def _is_ok(resp) -> bool:
    if not isinstance(resp, dict):
        return True
    if "error" in resp and resp["error"]:
        return False
    if "success" in resp:
        return bool(resp["success"])
    return True


def _safe(state, key):
    try:
        return state.get(key)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Lightweight per-call tracing for skills that want to log their own spans.
# ---------------------------------------------------------------------------

def trace(event: str, **fields):
    """Emit a structured log line. Use sparingly inside skills for key events."""
    log.info(json.dumps({"event": event, "ts": time.time(), **fields}))
