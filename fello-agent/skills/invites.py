"""Org invite skills (Firestore) — state-changing, kept separate from members.py.

members.py is explicitly read-only; approving and creating invites mutates
Firestore, so it lives here instead. Invite candidates arrive from a Drive
document-scanning flow (see FELLO_DRIVE_AND_WHATSAPP_SECURITY.md) that already
domain-filters candidates to the org's tenant before writing them to
`invite_suggestions`. That upstream filtering is a convenience, not a security
boundary — every write in this module independently re-validates the org and
tenant/domain match against the verified caller identity before creating an
invite, so a stale or tampered suggestion document can never leak an invite
into the wrong tenant.
"""

from __future__ import annotations

from datetime import datetime, timezone

from google.adk.tools import ToolContext

import authz
from context import identity
from ._firestore import db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def invite_org_members(suggestion_ids: list[str], tool_context: ToolContext) -> dict:
    """Approve one or more pending invite suggestions and create org invites.

    For each suggestion id: the suggestion must exist, belong to the caller's
    org, and its email domain must match the caller's tenant — anything that
    fails these checks is skipped (with a reason) rather than invited. Valid
    suggestions produce an `org_invites` document and the source suggestion is
    flipped to status "invited".
    """
    err = authz.require(tool_context, authz.CAP_MEMBERS_MANAGE)
    if err:
        return {"success": False, "error": err}

    actor = identity(tool_context)
    invited: list[str] = []
    skipped: list[dict] = []

    try:
        for suggestion_id in suggestion_ids:
            ref = db().collection("invite_suggestions").document(suggestion_id)
            snap = ref.get()
            if not snap.exists:
                skipped.append({"id": suggestion_id, "reason": "Suggestion not found."})
                continue

            doc = snap.to_dict()
            if doc.get("orgId") != actor.org_id:
                skipped.append({"id": suggestion_id, "reason": "Suggestion belongs to a different org."})
                continue

            email = doc.get("email") or ""
            normalized_email = _normalize_email(email)
            domain = normalized_email.split("@")[-1] if "@" in normalized_email else ""
            if not domain or domain != actor.tenant_id.lower():
                skipped.append({"id": suggestion_id, "reason": "Email domain does not match this org's tenant."})
                continue

            invite_id = f"{normalized_email}_{actor.org_id}"
            db().collection("org_invites").document(invite_id).set(
                {
                    "inviteValue": normalized_email,
                    "orgId": actor.org_id,
                    "tenantId": actor.tenant_id,
                    "invitedBy": actor.user_id or "fello_agent",
                    "invitedAt": _now(),
                    "status": "invited",
                    "access": "team",
                    "capabilities": [],
                    "sourceType": "directory_suggestion",
                    "sourceSuggestionId": suggestion_id,
                }
            )
            ref.update({"status": "invited"})
            invited.append(normalized_email)

        return {
            "success": True,
            "invited": invited,
            "skipped": skipped,
            "count": len(invited),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def list_pending_invite_suggestions(tool_context: ToolContext) -> dict:
    """List pending invite suggestions for the current org. Read-only."""
    actor = identity(tool_context)
    try:
        docs = (
            db()
            .collection("invite_suggestions")
            .where("orgId", "==", actor.org_id)
            .where("status", "==", "pending")
            .stream()
        )
        suggestions = [d.to_dict() for d in docs]
        return {"suggestions": suggestions, "count": len(suggestions)}
    except Exception as e:
        return {"suggestions": [], "error": str(e)}
