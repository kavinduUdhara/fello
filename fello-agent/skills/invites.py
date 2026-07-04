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
from firebase_admin import auth as _fb_auth

import authz
from context import identity
from ._firestore import db
from ._google import get_access_token
from . import _backend

try:
    import httpx
except Exception:  # pragma: no cover
    httpx = None  # type: ignore

_GMAIL_SEND_API = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
_APP_URL = "https://app.fello.live"


def _to_jid(phone: str) -> str | None:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(digits) < 8:
        return None
    return f"{digits}@s.whatsapp.net"


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
                    "inviteeName": doc.get("name") or None,
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


def invite_member(name: str, email: str, phone: str, tool_context: ToolContext) -> dict:
    """Invite one specific person to join the organization by name/email/phone.

    Use this for "add <name> to the org", "invite <email>" style requests —
    a single person named directly in conversation, as opposed to
    `invite_org_members` (approving Drive-sourced suggestions in bulk) or a
    file import. Creates the `org_invites` record directly (email domain must
    match this org's tenant), emails them an invite via the org's connected
    Google account, and — if a phone number is given — also sends a short
    WhatsApp nudge through the org's shared number. Works even if this org is
    still unverified; the person can sign in right away.

    Args:
        name: The invitee's display name.
        email: The invitee's email address — must be on this org's tenant domain.
        phone: The invitee's WhatsApp/phone number, or "" if not known.
    """
    err = authz.require(tool_context, authz.CAP_MEMBERS_MANAGE)
    if err:
        return {"success": False, "error": err}

    actor = identity(tool_context)
    normalized_email = _normalize_email(email)
    domain = normalized_email.split("@")[-1] if "@" in normalized_email else ""
    if not domain or domain != actor.tenant_id.lower():
        return {
            "success": False,
            "error": f"{email} isn't on this org's tenant domain ({actor.tenant_id}) — I can't invite it.",
        }

    invite_id = f"{normalized_email}_{actor.org_id}"
    try:
        existing = db().collection("org_invites").document(invite_id).get()
        if existing.exists and existing.to_dict().get("status") != "revoked":
            return {"success": False, "error": f"{normalized_email} is already invited or a member."}

        db().collection("org_invites").document(invite_id).set(
            {
                "inviteValue": normalized_email,
                "inviteeName": name or None,
                "orgId": actor.org_id,
                "tenantId": actor.tenant_id,
                "invitedBy": actor.user_id or "fello_agent",
                "invitedAt": _now(),
                "status": "invited",
                "access": "team",
                "capabilities": [],
                "sourceType": "manual",
                "sourceSuggestionId": None,
            }
        )
    except Exception as e:
        return {"success": False, "error": str(e)}

    result: dict = {"success": True, "invited": normalized_email, "name": name}

    token, terr = get_access_token(actor.org_id)
    if terr:
        result["email_error"] = terr
    else:
        org_name = _org_name(actor.org_id) or "your organization"
        greeting = f"Hi {name}," if name else "Hi,"
        subject = f"You're invited to join {org_name} on Fello"
        body = (
            f"{greeting}\n\n"
            f"You've been added to {org_name} on Fello, the coordination platform "
            f"we use to run events and stay organized.\n\n"
            f"Sign in to get started: {_APP_URL}\n\n"
            f"Just sign in with this email address ({normalized_email}) and {org_name} "
            f"will already be there on your home page — no invite code needed.\n\n"
            f"See you there!"
        )
        sent, serr = _send_gmail(token, normalized_email, subject, body)
        result["emailed"] = sent
        if not sent:
            result["email_error"] = serr

    if phone:
        jid = _to_jid(phone)
        if not jid:
            result["whatsapp_error"] = f"'{phone}' doesn't look like a valid phone number."
        else:
            org_name = _org_name(actor.org_id) or "your organization"
            channel_key = f"org_{actor.org_id}"
            wa_result = _backend.call(
                f"whatsapp/{channel_key}/send",
                {
                    "jid": jid,
                    "message": f"Someone invited you to join {org_name} on Fello. Go to {_APP_URL} to join.",
                },
            )
            result["whatsapp_sent"] = bool(wa_result.get("success"))
            if not wa_result.get("success"):
                result["whatsapp_error"] = wa_result.get("error", "WhatsApp send failed.")

    return result


def _bake_custom_claims(uid: str) -> str | None:
    """Rebuild this user's Firebase custom claims from Firestore membership data.

    Python port of `bakeCustomClaims` in fello-frontend/lib/actions/claims.ts —
    keep both in sync. Must run after any `memberships`/`project_memberships`
    write for this uid, so the JWT (the only thing permission checks read)
    reflects reality. Returns an error string, or None on success.
    """
    try:
        user_snap = db().collection("users").document(uid).get()
        user_data = user_snap.to_dict() or {}
        tenant_id = user_data.get("tenantId") or user_data.get("domain") or ""

        orgs: dict = {}
        for doc in db().collection("memberships").where("userId", "==", uid).stream():
            m = doc.to_dict() or {}
            if not m.get("orgId"):
                continue
            orgs[m["orgId"]] = {
                "access": m.get("access") or m.get("role") or "team",
                "nodeId": m.get("nodeId"),
                "capabilities": m.get("capabilities") or [],
                "via": m.get("via"),
            }

        projects: dict = {}
        for doc in (
            db()
            .collection("project_memberships")
            .where("contactId", "==", uid)
            .where("status", "==", "active")
            .stream()
        ):
            pm = doc.to_dict() or {}
            if not pm.get("projectId") or not pm.get("orgId"):
                continue
            if pm["orgId"] in orgs:
                continue
            projects[pm["projectId"]] = {"access": "event_only", "orgId": pm["orgId"]}

        existing_claims = (_fb_auth.get_user(uid).custom_claims or {}) or {}
        claims_version = (existing_claims.get("claimsVersion") or 0) + 1

        _fb_auth.set_custom_user_claims(
            uid,
            {
                "tenantId": tenant_id,
                "orgs": orgs,
                "projects": projects,
                "whatsappVerified": bool(user_data.get("whatsappVerified")),
                "claimsVersion": claims_version,
            },
        )
        return None
    except Exception as e:
        return str(e)


def remove_member(email: str, tool_context: ToolContext) -> dict:
    """Remove someone from the organization, or revoke their pending invite.

    Use this for "remove <name/email>", "take X off the team" style requests.
    If they haven't signed in yet, this just revokes their pending invite. If
    they're already a member, this deletes their org membership and rebakes
    their Firebase custom claims immediately, so access is revoked right away
    rather than waiting for their token to naturally expire.

    Args:
        email: The person's email address.
    """
    err = authz.require(tool_context, authz.CAP_MEMBERS_MANAGE)
    if err:
        return {"success": False, "error": err}

    actor = identity(tool_context)
    normalized_email = _normalize_email(email)

    invite_ref = db().collection("org_invites").document(f"{normalized_email}_{actor.org_id}")
    invite_snap = invite_ref.get()
    if invite_snap.exists and (invite_snap.to_dict() or {}).get("status") == "invited":
        invite_ref.update({"status": "revoked"})
        return {"success": True, "action": "invite_revoked", "email": normalized_email}

    try:
        user_record = _fb_auth.get_user_by_email(normalized_email)
    except Exception:
        return {"success": False, "error": f"No member or pending invite found for {normalized_email}."}

    membership_ref = db().collection("memberships").document(f"{user_record.uid}_{actor.org_id}")
    membership_snap = membership_ref.get()
    if not membership_snap.exists:
        return {"success": False, "error": f"{normalized_email} is not a member of this org."}

    membership_ref.delete()
    claims_err = _bake_custom_claims(user_record.uid)
    if claims_err:
        return {
            "success": True,
            "action": "removed",
            "email": normalized_email,
            "warning": f"Membership removed, but refreshing their permissions failed: {claims_err}",
        }
    return {"success": True, "action": "removed", "email": normalized_email}


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
