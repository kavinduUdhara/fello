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
from ._firestore import db


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

    Some invitees can't be added directly (WhatsApp privacy settings) — the
    gateway detects that automatically and DMs them a WhatsApp invite link
    instead, reported in the result's `invited` list. Report that accurately:
    "sent them an invite link", never claim they were added directly.
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
    """Add a member to an existing (authenticated) WhatsApp group.

    Some people can't be added directly — WhatsApp privacy settings ("who can
    add me to groups") block it. When that happens the gateway detects it and
    automatically DMs that person a WhatsApp invite link to join themselves
    instead, reported back in the result's `invited` list (each entry has
    `jid` and whether the invite DM itself went through). Report this
    accurately — say "sent them an invite link" for anyone in `invited`,
    never claim they were added directly.
    """
    err = authz.require(tool_context, authz.CAP_WHATSAPP_MANAGE)
    if err:
        return {"success": False, "error": err}
    actor = identity(tool_context)
    return _backend.call(
        f"whatsapp/{_channel_key(actor)}/groups/{group_jid}/participants",
        {"participants": [member_jid], "action": "add"},
    )


def update_whatsapp_group(
    group_jid: str,
    tool_context: ToolContext,
    name: str | None = None,
    use_organization_branding: bool = False,
) -> dict:
    """Rename a WhatsApp group and/or change its icon.

    Set `use_organization_branding=True` — instead of passing `name` — when
    the user asks to make the group match "the organization's" name/picture;
    this pulls the org's own name and logo automatically. Pass `name`
    explicitly for any other rename. At least one of `name` or
    `use_organization_branding` is required.
    """
    err = authz.require(tool_context, authz.CAP_WHATSAPP_MANAGE)
    if err:
        return {"success": False, "error": err}
    actor = identity(tool_context)
    channel_key = _channel_key(actor)

    subject = name
    image_url = None
    if use_organization_branding:
        org = db().collection("organizations").document(actor.org_id).get().to_dict() or {}
        subject = subject or org.get("name")
        image_url = org.get("logo")

    if not subject and not image_url:
        return {"success": False, "error": "Nothing to update — provide a name, or set use_organization_branding=True."}

    results: dict = {}
    if subject:
        results["subject"] = _backend.call(f"whatsapp/{channel_key}/groups/{group_jid}/subject", {"subject": subject})
    if image_url:
        results["picture"] = _backend.call(f"whatsapp/{channel_key}/groups/{group_jid}/picture", {"imageUrl": image_url})

    return {"success": all(r.get("success") for r in results.values()), "results": results}


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
