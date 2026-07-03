"""WhatsApp group authentication + per-sender authorization.

Implements FELLO_DRIVE_AND_WHATSAPP_SECURITY.md, Part B. These are *gateway /
server-side* helpers, not ADK tools — they run BEFORE the agent is invoked, to
decide whether a message should be processed at all and, if it requests an
action, whether the sender is allowed to trigger it. They take org_id / event_id
explicitly from the server's trusted context, never from the message body.

Pipeline (summary from the doc):
    personal DM            -> discard (never stored, never answered)
    unauthenticated group  -> discard
    authenticated group    -> process; attribute actions to verified senders only
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone

from ._firestore import db

OTP_TTL_MINUTES = 10


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Gateway-layer message gate (Categories 1-3)
# ---------------------------------------------------------------------------

def should_process_message(remote_jid: str | None) -> bool:
    """Gateway gate: only group messages (``@g.us``) are eligible for processing.

    Personal DMs to the gateway number are discarded immediately — not stored,
    not answered (Category 1). Mirror of the TS guard on the Baileys VM.
    """
    return bool(remote_jid) and remote_jid.endswith("@g.us")


def is_group_authenticated(group_jid: str) -> dict:
    """Return the authentication state for a group JID.

    Returns {"authenticated": bool, "orgId": ..., "eventId": ..., "tenantId": ...}.
    Unknown or unauthenticated groups -> authenticated False (Category 2: discard).
    """
    try:
        docs = list(
            db().collection("whatsapp_groups").where("jid", "==", group_jid).limit(1).stream()
        )
        if not docs:
            return {"authenticated": False, "reason": "unknown_group"}
        g = docs[0].to_dict()
        return {
            "authenticated": bool(g.get("authenticated")),
            "orgId": g.get("orgId"),
            "tenantId": g.get("tenantId"),
            "eventId": g.get("eventId"),
            "type": g.get("type"),
        }
    except Exception as e:
        return {"authenticated": False, "reason": f"error: {e}"}


# ---------------------------------------------------------------------------
# Path 2 authentication: pre-existing group, Fello added afterward (OTP)
# ---------------------------------------------------------------------------

def begin_group_authentication(
    group_jid: str, org_id: str, tenant_id: str, event_id: str, group_name: str = ""
) -> dict:
    """Create a pending whatsapp_groups record with a one-time 6-digit code.

    The caller (server) then has the gateway post the code *into the group*. One
    code authenticates exactly one group for one event — never bulk.
    """
    try:
        code = f"{random.randint(0, 999999):06d}"
        internal_id = f"wag_{uuid.uuid4().hex[:8]}"
        db().collection("whatsapp_groups").document(internal_id).set(
            {
                "id": internal_id,
                "orgId": org_id,
                "tenantId": tenant_id,
                "eventId": event_id,
                "jid": group_jid,
                "name": group_name,
                "createdByFello": False,
                "authenticated": False,
                "authenticationMethod": "otp_verification",
                "authenticationCode": code,
                "authenticationExpiresAt": (_now() + timedelta(minutes=OTP_TTL_MINUTES)).isoformat(),
                "authenticatedBy": None,
                "authenticatedAt": None,
                "createdAt": _now().isoformat(),
            }
        )
        return {"success": True, "internal_id": internal_id, "code": code, "ttl_minutes": OTP_TTL_MINUTES}
    except Exception as e:
        return {"success": False, "error": str(e)}


def verify_group_authentication(group_jid: str, code: str, sender_whatsapp_number: str) -> dict:
    """Verify an OTP reply in a group and mark it authenticated if valid.

    Requires: code matches and unexpired, sender has a verified Fello account,
    and that account has admin/coordinator-level access on the group's org.
    """
    try:
        docs = list(
            db()
            .collection("whatsapp_groups")
            .where("jid", "==", group_jid)
            .where("authenticated", "==", False)
            .stream()
        )
        if not docs:
            return {"success": False, "error": "No pending authentication for this group."}
        ref = docs[0].reference
        g = docs[0].to_dict()

        if (g.get("authenticationCode") or "") != code.strip():
            return {"success": False, "error": "Incorrect code."}
        exp = g.get("authenticationExpiresAt")
        if exp and datetime.fromisoformat(str(exp).replace("Z", "+00:00")) < _now():
            return {"success": False, "error": "That code has expired. Request a new one."}

        sender = resolve_sender_identity(sender_whatsapp_number)
        if not sender.get("user_id"):
            return {"success": False, "error": "Only a verified Fello member can authenticate a group."}

        access = (sender.get("orgs") or {}).get(g.get("orgId"), {})
        if access.get("access") not in {"full", "coordinator"}:
            return {"success": False, "error": "You need admin or coordinator access to authenticate this group."}

        ref.update(
            {
                "authenticated": True,
                "authenticatedBy": sender["user_id"],
                "authenticatedAt": _now().isoformat(),
                "authenticationCode": None,
            }
        )
        return {"success": True, "orgId": g.get("orgId"), "eventId": g.get("eventId")}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Per-sender authorization inside an authenticated group
# ---------------------------------------------------------------------------

def resolve_sender_identity(whatsapp_number: str) -> dict:
    """Resolve a verified WhatsApp number to a Fello user + their org claims.

    Returns {"user_id": uid|None, "orgs": {...}, "capabilities_by_org": {...}}.
    An unverified number resolves to user_id=None — usable as context only,
    never as an actor for state-changing actions.
    """
    try:
        users = list(
            db()
            .collection("users")
            .where("whatsappNumber", "==", whatsapp_number)
            .where("whatsappVerified", "==", True)
            .limit(1)
            .stream()
        )
        if not users:
            return {"user_id": None, "orgs": {}}
        u = users[0].to_dict()
        return {
            "user_id": users[0].id,
            "orgs": u.get("orgs") or {},
            "displayName": u.get("displayName"),
        }
    except Exception:
        return {"user_id": None, "orgs": {}}


def can_take_action(whatsapp_number: str, org_id: str, required_capability: str) -> bool:
    """Same JWT-capability model as the web app, for a WhatsApp sender.

    Mirrors the canTakeAction() example in the security doc: resolve number ->
    user -> org access -> capabilities, and require the capability to be present.
    """
    sender = resolve_sender_identity(whatsapp_number)
    if not sender.get("user_id"):
        return False
    access = (sender.get("orgs") or {}).get(org_id)
    if not access:
        return False
    caps = access.get("capabilities") or []
    return required_capability in caps or "*" in caps
