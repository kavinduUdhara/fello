"""Event management skills. Org scope is enforced from the verified context."""

from __future__ import annotations

from google.adk.tools import ToolContext

import authz
from context import identity, resolve_event_id
from ._firestore import db


def get_event_details(tool_context: ToolContext, event_id: str | None = None) -> dict:
    """Fetch details for an event (defaults to the event in focus). Read-only."""
    actor = identity(tool_context)
    evt = resolve_event_id(tool_context, event_id)
    if not evt:
        return {"event": None, "error": "No event specified."}
    try:
        doc = db().collection("events").document(evt).get()
        if not doc.exists:
            return {"event": None, "error": "Event not found."}
        data = doc.to_dict()
        if data.get("orgId") != actor.org_id:
            return {"event": None, "error": "Event does not belong to this org."}
        return {"event": data}
    except Exception as e:
        return {"event": None, "error": str(e)}


def update_event_status(status: str, tool_context: ToolContext, event_id: str | None = None) -> dict:
    """Update an event's status (active|closed)."""
    valid = {"active", "closed"}
    if status not in valid:
        return {"success": False, "error": f"Invalid status. Must be one of: {', '.join(valid)}"}

    err = authz.require(tool_context, authz.CAP_EVENTS_MANAGE)
    if err:
        return {"success": False, "error": err}

    actor = identity(tool_context)
    evt = resolve_event_id(tool_context, event_id)
    if not evt:
        return {"success": False, "error": "No event specified."}
    try:
        ref = db().collection("events").document(evt)
        snap = ref.get()
        if not snap.exists or snap.to_dict().get("orgId") != actor.org_id:
            return {"success": False, "error": "Event not found or access denied."}
        ref.update({"status": status})
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_upcoming_events(tool_context: ToolContext) -> dict:
    """List all active events for the current org. Read-only."""
    actor = identity(tool_context)
    try:
        docs = (
            db()
            .collection("events")
            .where("orgId", "==", actor.org_id)
            .where("status", "==", "active")
            .stream()
        )
        events = [d.to_dict() for d in docs]
        return {"events": events, "count": len(events)}
    except Exception as e:
        return {"events": [], "error": str(e)}
