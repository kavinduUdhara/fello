"""WhatsApp communication skills.

These call the Baileys gateway on the GCE VM via its internal API. When the
gateway is not configured (BAILEYS_API_URL unset), calls degrade gracefully so
the dashboard demo still works. Every send is capability-gated and runs under
the verified org scope.
"""

from __future__ import annotations

from google.adk.tools import ToolContext

import authz
from context import identity
from . import _baileys


def send_whatsapp_message(jid: str, message: str, tool_context: ToolContext) -> dict:
    """Send a WhatsApp message to a group or individual JID."""
    err = authz.require(tool_context, authz.CAP_WHATSAPP_MANAGE)
    if err:
        return {"success": False, "error": err}
    actor = identity(tool_context)
    if not actor.event_id:
        return {
            "success": False,
            "error": "No project is in focus — which project's WhatsApp number should this go through?",
        }
    return _baileys.call(
        "send-message",
        {
            "orgId": actor.org_id,
            "tenantId": actor.tenant_id,
            "projectId": actor.event_id,
            "jid": jid,
            "message": message,
        },
    )


def create_whatsapp_group(name: str, member_jids: list[str], tool_context: ToolContext) -> dict:
    """Create a new WhatsApp group and add members.

    Groups created this way are authenticated by construction
    (FELLO_DRIVE_AND_WHATSAPP_SECURITY.md, Path 1) — the gateway records
    createdByFello=true and no OTP step is required.
    """
    err = authz.require(tool_context, authz.CAP_WHATSAPP_MANAGE)
    if err:
        return {"success": False, "error": err}
    actor = identity(tool_context)
    if not actor.event_id:
        return {
            "success": False,
            "error": "No project is in focus — which project's WhatsApp number should this go through?",
        }
    return _baileys.call(
        "create-group",
        {
            "orgId": actor.org_id,
            "tenantId": actor.tenant_id,
            "eventId": actor.event_id,
            "projectId": actor.event_id,
            "name": name,
            "memberJids": member_jids,
            "createdByFello": True,
        },
    )


def add_member_to_group(group_jid: str, member_jid: str, tool_context: ToolContext) -> dict:
    """Add a member to an existing (authenticated) WhatsApp group."""
    err = authz.require(tool_context, authz.CAP_WHATSAPP_MANAGE)
    if err:
        return {"success": False, "error": err}
    actor = identity(tool_context)
    if not actor.event_id:
        return {
            "success": False,
            "error": "No project is in focus — which project's WhatsApp number should this go through?",
        }
    return _baileys.call(
        "add-member",
        {
            "orgId": actor.org_id,
            "tenantId": actor.tenant_id,
            "projectId": actor.event_id,
            "groupJid": group_jid,
            "memberJid": member_jid,
        },
    )


def broadcast_message(member_jids: list[str], message: str, tool_context: ToolContext) -> dict:
    """Send the same message to multiple individuals."""
    err = authz.require(tool_context, authz.CAP_WHATSAPP_MANAGE)
    if err:
        return {"sent": 0, "failed": len(member_jids), "errors": [err]}
    actor = identity(tool_context)
    if not actor.event_id:
        no_project_err = "No project is in focus — which project's WhatsApp number should this go through?"
        return {"sent": 0, "failed": len(member_jids), "errors": [no_project_err]}
    result = _baileys.call(
        "broadcast",
        {
            "orgId": actor.org_id,
            "tenantId": actor.tenant_id,
            "projectId": actor.event_id,
            "memberJids": member_jids,
            "message": message,
        },
    )
    if not result.get("success"):
        return {
            "sent": result.get("sent", 0),
            "failed": result.get("failed", len(member_jids)),
            "errors": [result.get("error", "Unknown gateway error")],
        }
    return result
