"""Event/project management skills. Org scope is enforced from the verified context.

"Event" and "project" are the same concept in Fello — there is no separate
`events` collection. These skills read/write the `projects` collection; the
`event_id` naming in session state and tool signatures is kept as-is (it's
threaded through context.py/tasks.py/documents.py/communication.py) to avoid
churn, but it always resolves to a `projects/{id}` document.
"""

from __future__ import annotations

from google.adk.tools import ToolContext

import authz
from context import identity, resolve_event_id
from ._firestore import db


def get_event_details(tool_context: ToolContext, event_id: str | None = None) -> dict:
    """Fetch details for a project (defaults to the project in focus). Read-only."""
    actor = identity(tool_context)
    evt = resolve_event_id(tool_context, event_id)
    if not evt:
        return {"event": None, "error": "No project specified."}
    try:
        doc = db().collection("projects").document(evt).get()
        if not doc.exists:
            return {"event": None, "error": "Project not found."}
        data = doc.to_dict()
        if data.get("orgId") != actor.org_id:
            return {"event": None, "error": "Project does not belong to this org."}
        return {"event": data}
    except Exception as e:
        return {"event": None, "error": str(e)}


def update_event_status(status: str, tool_context: ToolContext, event_id: str | None = None) -> dict:
    """Update a project's status (active|closed)."""
    valid = {"active", "closed"}
    if status not in valid:
        return {"success": False, "error": f"Invalid status. Must be one of: {', '.join(valid)}"}

    err = authz.require(tool_context, authz.CAP_EVENTS_MANAGE)
    if err:
        return {"success": False, "error": err}

    actor = identity(tool_context)
    evt = resolve_event_id(tool_context, event_id)
    if not evt:
        return {"success": False, "error": "No project specified."}
    try:
        ref = db().collection("projects").document(evt)
        snap = ref.get()
        if not snap.exists or snap.to_dict().get("orgId") != actor.org_id:
            return {"success": False, "error": "Project not found or access denied."}
        ref.update({"status": status})
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_upcoming_events(tool_context: ToolContext) -> dict:
    """List all active projects for the current org. Read-only."""
    actor = identity(tool_context)
    try:
        docs = (
            db()
            .collection("projects")
            .where("orgId", "==", actor.org_id)
            .where("status", "==", "active")
            .stream()
        )
        events = [d.to_dict() for d in docs]
        return {"events": events, "count": len(events)}
    except Exception as e:
        return {"events": [], "error": str(e)}
