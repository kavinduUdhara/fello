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

import base64
from datetime import datetime, timezone

from google.adk.tools import ToolContext

import authz
from context import identity
from ._firestore import db
from ._google import get_access_token

try:
    import httpx
except Exception:  # pragma: no cover
    httpx = None  # type: ignore

_GMAIL_SEND_API = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
_APP_URL = "https://app.fello.live"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _org_name(org_id: str) -> str:
    doc = db().collection("organizations").document(org_id).get()
    return (doc.to_dict() or {}).get("name") if doc.exists else None


def _send_gmail(token: str, to_email: str, subject: str, body: str) -> tuple[bool, str | None]:
    if httpx is None:
        return False, "HTTP client unavailable on the server."
    raw = "\r\n".join(
        [
            f"To: {to_email}",
            f"Subject: {subject}",
            "Content-Type: text/plain; charset=UTF-8",
            "",
            body,
        ]
    )
    encoded = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")
    try:
        res = httpx.post(
            _GMAIL_SEND_API,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"raw": encoded},
            timeout=20.0,
        )
        res.raise_for_status()
        return True, None
    except Exception as e:
        try:
            detail = e.response.text[:300]  # type: ignore[attr-defined]
        except Exception:
            detail = str(e)
        return False, f"Gmail send failed: {detail}"


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


def send_org_invite_email(to_email: str, member_name: str, tool_context: ToolContext) -> dict:
    """Email an invite link to someone who was just invited to join the org.

    Sends from the org's connected Google account (the same one used for
    Drive/Docs/Forms — must have the gmail.send scope granted in Settings).
    The invite link is just the app's home page: Fello resolves the org
    membership automatically the moment this person signs in with this exact
    email address (see `acceptPendingOrgInvites` in org-invites.ts) — no
    token or join code needed, and this works even if the org itself is still
    unverified.

    Args:
        to_email: The invitee's email address (must already have a pending
            `org_invites` record — this tool only sends the notification,
            it does not create the invite).
        member_name: The invitee's display name, for a personal greeting.
    """
    err = authz.require(tool_context, authz.CAP_MEMBERS_MANAGE)
    if err:
        return {"success": False, "error": err}

    actor = identity(tool_context)
    normalized = _normalize_email(to_email)

    token, terr = get_access_token(actor.org_id)
    if terr:
        return {"success": False, "error": terr}

    org_name = _org_name(actor.org_id) or "your organization"
    greeting = f"Hi {member_name}," if member_name else "Hi,"
    subject = f"You're invited to join {org_name} on Fello"
    body = (
        f"{greeting}\n\n"
        f"You've been added to {org_name} on Fello, the coordination platform "
        f"we use to run events and stay organized.\n\n"
        f"Sign in to get started: {_APP_URL}\n\n"
        f"Just sign in with this email address ({normalized}) and {org_name} "
        f"will already be there on your home page — no invite code needed.\n\n"
        f"See you there!"
    )

    sent, serr = _send_gmail(token, normalized, subject, body)
    if not sent:
        return {"success": False, "error": serr}
    return {"success": True, "sent_to": normalized}


def send_org_invite_emails(invites: list[dict], tool_context: ToolContext) -> dict:
    """Email invite links to a batch of newly invited members in one call.

    Use this instead of calling `send_org_invite_email` in a loop when the
    user just imported or approved several invites at once.

    Args:
        invites: A list of `{"email": ..., "name": ...}` objects.
    """
    err = authz.require(tool_context, authz.CAP_MEMBERS_MANAGE)
    if err:
        return {"success": False, "error": err}

    actor = identity(tool_context)
    token, terr = get_access_token(actor.org_id)
    if terr:
        return {"success": False, "error": terr}

    org_name = _org_name(actor.org_id) or "your organization"
    sent: list[str] = []
    failed: list[dict] = []
    for inv in invites:
        email = _normalize_email(inv.get("email") or "")
        name = inv.get("name") or ""
        if not email:
            failed.append({"email": inv.get("email"), "reason": "missing email"})
            continue
        greeting = f"Hi {name}," if name else "Hi,"
        subject = f"You're invited to join {org_name} on Fello"
        body = (
            f"{greeting}\n\n"
            f"You've been added to {org_name} on Fello, the coordination platform "
            f"we use to run events and stay organized.\n\n"
            f"Sign in to get started: {_APP_URL}\n\n"
            f"Just sign in with this email address ({email}) and {org_name} "
            f"will already be there on your home page — no invite code needed.\n\n"
            f"See you there!"
        )
        ok, serr = _send_gmail(token, email, subject, body)
        if ok:
            sent.append(email)
        else:
            failed.append({"email": email, "reason": serr})

    return {"success": True, "sent": sent, "failed": failed, "count": len(sent)}


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
