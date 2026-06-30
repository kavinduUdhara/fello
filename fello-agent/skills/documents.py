"""Document stub skills (Firestore). Real file retrieval lives in retrieval.py.

Org scope comes from the verified context; the model never supplies org_id.
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


def create_document_stub(
    title: str,
    doc_type: str,
    tool_context: ToolContext,
    event_id: str | None = None,
) -> dict:
    """Register a document placeholder for an event (e.g. 'agenda', 'budget')."""
    err = authz.require(tool_context, authz.CAP_DOCUMENTS_MANAGE)
    if err:
        return {"success": False, "error": err}

    actor = identity(tool_context)
    evt = resolve_event_id(tool_context, event_id)
    if not evt:
        return {"success": False, "error": "No event specified."}
    try:
        doc_id = f"doc_{uuid.uuid4().hex[:8]}"
        db().collection("event_documents").document(doc_id).set(
            {
                "id": doc_id,
                "orgId": actor.org_id,
                "tenantId": actor.tenant_id,
                "eventId": evt,
                "title": title,
                "type": doc_type,
                "url": None,
                "createdAt": _now(),
                "createdBy": actor.user_id or "agent",
            }
        )
        return {"doc_id": doc_id, "success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def link_document(doc_id: str, url: str, tool_context: ToolContext) -> dict:
    """Link an external URL (Google Drive, etc.) to a document stub."""
    err = authz.require(tool_context, authz.CAP_DOCUMENTS_MANAGE)
    if err:
        return {"success": False, "error": err}

    actor = identity(tool_context)
    try:
        ref = db().collection("event_documents").document(doc_id)
        snap = ref.get()
        if not snap.exists or snap.to_dict().get("orgId") != actor.org_id:
            return {"success": False, "error": "Document not found or access denied."}
        ref.update({"url": url})
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_documents(tool_context: ToolContext, event_id: str | None = None) -> dict:
    """List document stubs for an event. Read-only."""
    actor = identity(tool_context)
    evt = resolve_event_id(tool_context, event_id)
    if not evt:
        return {"documents": [], "error": "No event specified."}
    try:
        docs = (
            db()
            .collection("event_documents")
            .where("orgId", "==", actor.org_id)
            .where("eventId", "==", evt)
            .stream()
        )
        documents = [d.to_dict() for d in docs]
        return {"documents": documents, "count": len(documents)}
    except Exception as e:
        return {"documents": [], "error": str(e)}
