"""Capability gating for state-changing agent actions.

Per FELLO_DRIVE_AND_WHATSAPP_SECURITY.md ("Authorization level inside a group —
same JWT model as the web app"), there is no separate, weaker permission system
for the agent. Every state-changing action is gated by the SAME capability list
that the web dashboard uses, resolved from the actor's JWT custom claims and
placed into session.state by the server before the agent runs.

The check is deliberately external to the model: a skill calls ``require()`` at
its top and refuses the action if the capability is absent. The model cannot
talk its way past this — it only ever sees the returned error string.
"""

from __future__ import annotations

from context import identity, IdentityError

# Capability constants. These mirror the `capabilities` array baked into the JWT
# custom claims (CLAUDE.md §4.3). Keep names stable — they are a security
# contract shared with the web app, not free text.
CAP_EVENTS_MANAGE = "events.manage"
CAP_TASKS_MANAGE = "tasks.manage"
CAP_MEMBERS_MANAGE = "members.manage"
CAP_OUTREACH_MANAGE = "outreach.manage"
CAP_DOCUMENTS_MANAGE = "documents.manage"
CAP_WHATSAPP_MANAGE = "whatsapp.manage"

# Wildcard capability — "full" access roles carry this.
CAP_WILDCARD = "*"


def require(tool_context, capability: str) -> str | None:
    """Return None if the actor may perform ``capability``, else an error string.

    Skills use it as a guard:

        err = authz.require(tool_context, authz.CAP_TASKS_MANAGE)
        if err:
            return {"success": False, "error": err}

    Rules, in order:
    1. No verified tenant/org context           -> deny (fail closed).
    2. No verified user identity (e.g. an
       unverified WhatsApp sender)               -> deny, ask them to verify.
    3. capabilities not provided by the server   -> allow (the dashboard route
       already authorized the actor; this is the back-compat / web path).
    4. capability present (or wildcard)          -> allow.
    5. otherwise                                  -> deny.
    """
    try:
        actor = identity(tool_context)
    except IdentityError as e:
        return str(e)

    if not actor.is_verified_user:
        return (
            "I can't do that yet — your WhatsApp number isn't linked to a "
            "verified Fello account. Please verify it first, then ask again."
        )

    caps = actor.capabilities
    if caps is None:
        # Server did not attach an explicit capability set. On the dashboard the
        # route itself already gated this actor, so we trust that and allow.
        return None

    if capability in caps or CAP_WILDCARD in caps:
        return None

    return (
        f"You don't have permission for this action ({capability}). "
        "Ask an org admin or coordinator if you need access."
    )


def can(tool_context, capability: str) -> bool:
    """Boolean form of :func:`require`, for non-tool internal checks."""
    return require(tool_context, capability) is None
