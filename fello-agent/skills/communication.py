"""WhatsApp communication skills.

These call the Baileys gateway through fello-backend's agent-facing relay
(see _backend.py) — the gateway itself is not reachable from outside its VM,
only the backend is, so the agent (running remotely on Vertex AI Agent
Engine) goes through the backend rather than hitting the gateway directly.
When the relay isn't configured (BACKEND_API_URL/AGENT_BACKEND_SECRET unset),
calls degrade gracefully so the dashboard demo still works. Every send is
capability-gated and runs under the verified org scope.

Channel resolution: a project (event) in focus gets its own dedicated number
(the raw project id is the gateway session key); with no project in focus,
these fall back to the org-wide shared number (session key ``org_<org_id>``,
matching ``orgSessionKey`` in fello-backend/backend/src/whatsapp-routes.js) —
sending a WhatsApp message from chat should not require a project to be
selected first.
"""

from __future__ import annotations

from google.adk.tools import ToolContext

import authz
from context import identity
from . import _backend


def _channel_key(actor) -> str:
    return actor.event_id if actor.event_id else f"org_{actor.org_id}"


def send_whatsapp_message(jid: str, message: str, tool_context: ToolContext) -> dict:
    """Send a WhatsApp message to a group or individual JID.

    Uses the project's dedicated number if a project is in focus, otherwise
    the org-wide shared number.
    """
    err = authz.require(tool_context, authz.CAP_WHATSAPP_MANAGE)
    if err:
        return {"success": False, "error": err}
    actor = identity(tool_context)
    return _backend.call(f"whatsapp/{_channel_key(actor)}/send", {"jid": jid, "message": message})


def create_whatsapp_group(name: str, member_jids: list[str], tool_context: ToolContext) -> dict:
    """Create a new WhatsApp group and add members.

    Uses the project's dedicated number if a project is in focus, otherwise
    the org-wide shared number. Groups created this way are authenticated by
    construction (FELLO_DRIVE_AND_WHATSAPP_SECURITY.md, Path 1) — the gateway
    records createdByFello=true and no OTP step is required.
    """
    err = authz.require(tool_context, authz.CAP_WHATSAPP_MANAGE)
    if err:
        return {"success": False, "error": err}
    actor = identity(tool_context)
    return _backend.call(
        f"whatsapp/{_channel_key(actor)}/groups",
        {"name": name, "participants": member_jids},
    )


def add_member_to_group(group_jid: str, member_jid: str, tool_context: ToolContext) -> dict:
    """Add a member to an existing (authenticated) WhatsApp group."""
    err = authz.require(tool_context, authz.CAP_WHATSAPP_MANAGE)
    if err:
        return {"success": False, "error": err}
    actor = identity(tool_context)
    return _backend.call(
        f"whatsapp/{_channel_key(actor)}/groups/{group_jid}/participants",
        {"participants": [member_jid], "action": "add"},
    )


def broadcast_message(member_jids: list[str], message: str, tool_context: ToolContext) -> dict:
    """Send the same message to multiple individuals."""
    err = authz.require(tool_context, authz.CAP_WHATSAPP_MANAGE)
    if err:
        return {"sent": 0, "failed": len(member_jids), "errors": [err]}
    actor = identity(tool_context)
    channel_key = _channel_key(actor)

    sent = 0
    errors: list[str] = []
    for jid in member_jids:
        result = _backend.call(f"whatsapp/{channel_key}/send", {"jid": jid, "message": message})
        if result.get("success"):
            sent += 1
        else:
            errors.append(result.get("error", f"failed to send to {jid}"))

    return {"sent": sent, "failed": len(member_jids) - sent, "errors": errors}
