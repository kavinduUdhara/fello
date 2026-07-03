"""Event/project management skills. Org scope is enforced from the verified context.

"Event" and "project" are the same concept in Fello — there is no separate
`events` collection. These skills read/write the `projects` collection; the
`event_id` naming in session state and tool signatures is kept as-is (it's
threaded through context.py/tasks.py/documents.py/communication.py) to avoid
churn, but it always resolves to a `projects/{id}` document.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from google.adk.tools import ToolContext

import authz
from context import identity, resolve_event_id
from ._firestore import db

# Matches the frontend's status options exactly (projects/new/page.tsx,
# projects/[projectId]/page.tsx statusOptions) — keep these in sync.
_VALID_STATUSES = {"planning", "active", "completed", "closed"}
# "Ongoing" = anything not finished yet. New projects default to "planning",
# so list_upcoming_events must include it or newly created projects are
# permanently invisible to the agent.
_ONGOING_STATUSES = ["planning", "active"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_project(
    name: str,
    description: str,
    tool_context: ToolContext,
    date: str | None = None,
) -> dict:
    """Create a new project (a.k.a. event) for the current org.

    Args:
        name: Project/event name.
        description: What it's about.
        date: Optional ISO date "YYYY-MM-DD" for the project's start date.

    Returns:
        dict with project_id on success, or an error string.
    """
    err = authz.require(tool_context, authz.CAP_EVENTS_MANAGE)
    if err:
        return {"success": False, "error": err}

    actor = identity(tool_context)
    try:
        project_id = f"proj_{uuid.uuid4().hex[:8]}"
        db().collection("projects").document(project_id).set(
            {
                "id": project_id,
                "orgId": actor.org_id,
                "tenantId": actor.tenant_id,
                "eventId": project_id,
                "name": name,
                "description": description,
                "type": "event",
                "status": "planning",
                "date": date,
                "dueDate": None,
                "icon": "",
                "iconUrl": "",
                "driveAccountType": "org",
                "driveGrantRef": "org",
                "driveRootFolderId": None,
                "whatsappGatewayNumber": None,
                "whatsappStatus": "not_connected",
                "coordinators": [actor.user_id] if actor.user_id else [],
                "createdBy": actor.user_id or "agent",
                "createdAt": _now(),
            }
        )
        return {"project_id": project_id, "success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


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
    """Update a project's status (planning|active|completed|closed)."""
    if status not in _VALID_STATUSES:
        return {"success": False, "error": f"Invalid status. Must be one of: {', '.join(sorted(_VALID_STATUSES))}"}

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
    """List all ongoing projects (status planning or active) for the current org. Read-only."""
    actor = identity(tool_context)
    try:
        docs = (
            db()
            .collection("projects")
            .where("orgId", "==", actor.org_id)
            .where("status", "in", _ONGOING_STATUSES)
            .stream()
        )
        events = [d.to_dict() for d in docs]
        return {"events": events, "count": len(events)}
    except Exception as e:
        return {"events": [], "error": str(e)}
