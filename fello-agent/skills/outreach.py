"""Outreach skills — drafting messages and logging sponsor/speaker outreach.

Replaces the manual spreadsheet workflow. Org scope from the verified context.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from google.adk.tools import ToolContext

import authz
from context import identity, resolve_event_id
from ._firestore import db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def draft_outreach_message(context: str, recipient_type: str, tool_context: ToolContext) -> dict:
    """Draft an outreach message for a sponsor, speaker, vendor, or volunteer.

    Args:
        context: Brief context (e.g. "IEEE PTI 2026, need a keynote speaker").
        recipient_type: 'sponsor' | 'speaker' | 'vendor' | 'volunteer'.
    """
    # Read-only generation; no capability gate, but requires a verified org scope.
    identity(tool_context)
    templates = {
        "sponsor": (
            "Dear [Name],\n\n"
            "I hope this message finds you well. I am reaching out on behalf of [Organization] "
            f"regarding our upcoming event. {context}\n\n"
            "We believe your organization would be an excellent partner for this initiative, "
            "and we would love to explore a mutually beneficial sponsorship opportunity.\n\n"
            "Would you be available for a brief call this week to discuss the details?\n\n"
            "Best regards,\n[Your Name]"
        ),
        "speaker": (
            "Dear [Name],\n\n"
            "I am writing on behalf of [Organization] to invite you as a speaker for our upcoming event. "
            f"{context}\n\n"
            "Your expertise and insights would be incredibly valuable to our audience. "
            "We would be honored to have you join us.\n\n"
            "Please let me know your availability and any requirements you may have.\n\n"
            "Warm regards,\n[Your Name]"
        ),
        "vendor": (
            "Hi [Name],\n\n"
            f"We are organising an event and are looking for vendors. {context}\n\n"
            "Could you share your availability and pricing?\n\n"
            "Thanks,\n[Your Name]"
        ),
        "volunteer": (
            "Hi [Name],\n\n"
            f"We are looking for volunteers for our upcoming event. {context}\n\n"
            "If you are interested, please reply with your preferred role and availability.\n\n"
            "Thank you!"
        ),
    }
    draft = templates.get(recipient_type, templates["sponsor"])
    return {"draft": draft, "recipient_type": recipient_type}


def log_outreach_attempt(
    recipient_name: str,
    recipient_contact: str,
    channel: str,
    status: str,
    tool_context: ToolContext,
    notes: str = "",
    event_id: str | None = None,
) -> dict:
    """Log an outreach attempt to Firestore (replaces the spreadsheet workflow).

    Args:
        recipient_name: Person or organization contacted.
        recipient_contact: Email, phone, or WhatsApp.
        channel: 'email' | 'whatsapp' | 'phone' | 'linkedin'.
        status: 'contacted' | 'responded' | 'confirmed' | 'declined' | 'no_response'.
        notes: Optional notes.
        event_id: Optional explicit event UUID; defaults to the event in focus.
    """
    valid_statuses = {"contacted", "responded", "confirmed", "declined", "no_response"}
    if status not in valid_statuses:
        return {"success": False, "error": f"Invalid status. Must be one of: {', '.join(valid_statuses)}"}

    err = authz.require(tool_context, authz.CAP_OUTREACH_MANAGE)
    if err:
        return {"success": False, "error": err}

    actor = identity(tool_context)
    evt = resolve_event_id(tool_context, event_id)
    if not evt:
        return {"success": False, "error": "No event specified."}
    try:
        outreach_id = f"out_{uuid.uuid4().hex[:8]}"
        db().collection("outreach").document(outreach_id).set(
            {
                "id": outreach_id,
                "orgId": actor.org_id,
                "tenantId": actor.tenant_id,
                "eventId": evt,
                "recipientName": recipient_name,
                "recipientContact": recipient_contact,
                "channel": channel,
                "status": status,
                "notes": notes,
                "loggedBy": actor.user_id or "agent",
                "createdAt": _now(),
                "updatedAt": _now(),
            }
        )
        return {"outreach_id": outreach_id, "success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_outreach(
    tool_context: ToolContext,
    event_id: str | None = None,
    status_filter: str | None = None,
) -> dict:
    """List outreach attempts for an event, optionally filtered by status. Read-only."""
    actor = identity(tool_context)
    evt = resolve_event_id(tool_context, event_id)
    if not evt:
        return {"outreach": [], "error": "No event specified."}
    try:
        q = (
            db()
            .collection("outreach")
            .where("orgId", "==", actor.org_id)
            .where("eventId", "==", evt)
        )
        if status_filter:
            q = q.where("status", "==", status_filter)
        items = [d.to_dict() for d in q.stream()]
        return {"outreach": items, "count": len(items)}
    except Exception as e:
        return {"outreach": [], "error": str(e)}
