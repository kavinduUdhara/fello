"""Member directory skills (read-only). Org scope comes from the verified context."""

from __future__ import annotations

from google.adk.tools import ToolContext

from context import identity
from ._firestore import db


def lookup_member(name_or_phone: str, tool_context: ToolContext) -> dict:
    """Find members of the current org by partial name or phone number."""
    actor = identity(tool_context)
    try:
        docs = db().collection("memberships").where("orgId", "==", actor.org_id).stream()
        query = name_or_phone.lower().strip()
        results = []
        for d in docs:
            m = d.to_dict()
            name = (m.get("displayName") or m.get("name") or "").lower()
            phone = m.get("phoneNumber") or m.get("whatsappNumber") or ""
            if query in name or query in phone:
                results.append(m)
        return {"members": results, "count": len(results)}
    except Exception as e:
        return {"members": [], "error": str(e)}


def list_members(tool_context: ToolContext, role_filter: str | None = None) -> dict:
    """List all members of the current org, optionally filtered by role."""
    actor = identity(tool_context)
    try:
        q = db().collection("memberships").where("orgId", "==", actor.org_id)
        if role_filter:
            q = q.where("role", "==", role_filter)
        members = [d.to_dict() for d in q.stream()]
        return {"members": members, "count": len(members)}
    except Exception as e:
        return {"members": [], "error": str(e)}


def get_member_whatsapp_jid(uid: str, tool_context: ToolContext) -> dict:
    """Resolve a member's Firebase UID to a WhatsApp JID, verifying org membership."""
    actor = identity(tool_context)
    try:
        membership = db().collection("memberships").document(f"{uid}_{actor.org_id}").get()
        if not membership.exists:
            return {"jid": None, "error": "That user is not a member of this org."}
        user_doc = db().collection("users").document(uid).get()
        if not user_doc.exists:
            return {"jid": None, "error": "User not found."}
        data = user_doc.to_dict()
        jid = data.get("whatsappJid") or data.get("phoneNumber")
        if not jid:
            return {"jid": None, "error": "No WhatsApp number on record for this user."}
        return {"jid": jid}
    except Exception as e:
        return {"jid": None, "error": str(e)}
