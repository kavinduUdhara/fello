"""Task management skills.

Tenant scope (tenant_id, org_id) is sourced from the verified ToolContext, never
from model-supplied arguments (FELLO_ADK_CAPABILITIES_AND_SECURITY.md). The model
only supplies the *content* of a task (title, who, when) — never *which org*.
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


def create_task(
    title: str,
    description: str,
    assignee_uids: list[str],
    due_date: str | None,
    tool_context: ToolContext,
    event_id: str | None = None,
) -> dict:
    """Create a task for the current event.

    Args:
        title: Short task title.
        description: What needs to be done.
        assignee_uids: Firebase UIDs to assign (empty list for unassigned).
        due_date: ISO date "YYYY-MM-DD" or None.
        event_id: Optional explicit event UUID; defaults to the event in focus.

    Returns:
        dict with task_id on success, or an error string.
    """
    err = authz.require(tool_context, authz.CAP_TASKS_MANAGE)
    if err:
        return {"success": False, "error": err}

    actor = identity(tool_context)
    evt = resolve_event_id(tool_context, event_id)
    if not evt:
        return {"success": False, "error": "No event specified. Which event is this task for?"}

    try:
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        db().collection("tasks").document(task_id).set(
            {
                "id": task_id,
                "orgId": actor.org_id,
                "tenantId": actor.tenant_id,
                "eventId": evt,
                "title": title,
                "description": description,
                "assignedTo": assignee_uids or [],
                "status": "assigned" if assignee_uids else "unassigned",
                "dueDate": due_date,
                "createdBy": actor.user_id or "agent",
                "createdAt": _now(),
                "sourceMessageId": None,
            }
        )
        return {"task_id": task_id, "success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def update_task_status(task_id: str, status: str, tool_context: ToolContext) -> dict:
    """Update a task's status (unassigned|assigned|in_progress|completed|blocked)."""
    valid = {"unassigned", "assigned", "in_progress", "completed", "blocked"}
    if status not in valid:
        return {"success": False, "error": f"Invalid status. Must be one of: {', '.join(valid)}"}

    err = authz.require(tool_context, authz.CAP_TASKS_MANAGE)
    if err:
        return {"success": False, "error": err}

    actor = identity(tool_context)
    try:
        ref = db().collection("tasks").document(task_id)
        snap = ref.get()
        if not snap.exists or snap.to_dict().get("orgId") != actor.org_id:
            return {"success": False, "error": "Task not found or access denied."}
        ref.update({"status": status})
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def assign_task(task_id: str, assignee_uids: list[str], tool_context: ToolContext) -> dict:
    """Assign or reassign a task to one or more members (Firebase UIDs)."""
    err = authz.require(tool_context, authz.CAP_TASKS_MANAGE)
    if err:
        return {"success": False, "error": err}

    actor = identity(tool_context)
    try:
        ref = db().collection("tasks").document(task_id)
        snap = ref.get()
        if not snap.exists or snap.to_dict().get("orgId") != actor.org_id:
            return {"success": False, "error": "Task not found or access denied."}
        ref.update(
            {"assignedTo": assignee_uids, "status": "assigned" if assignee_uids else "unassigned"}
        )
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_tasks(
    tool_context: ToolContext,
    event_id: str | None = None,
    status_filter: str | None = None,
) -> dict:
    """List tasks for an event, optionally filtered by status. Read-only."""
    actor = identity(tool_context)
    evt = resolve_event_id(tool_context, event_id)
    if not evt:
        return {"tasks": [], "error": "No event specified."}
    try:
        q = (
            db()
            .collection("tasks")
            .where("orgId", "==", actor.org_id)
            .where("eventId", "==", evt)
        )
        if status_filter:
            q = q.where("status", "==", status_filter)
        tasks = [d.to_dict() for d in q.stream()]
        return {"tasks": tasks, "count": len(tasks)}
    except Exception as e:
        return {"tasks": [], "error": str(e)}
