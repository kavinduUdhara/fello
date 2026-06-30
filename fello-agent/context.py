"""Verified identity / tenant-binding layer for the Fello agent.

This is the single most important security file in the agent. Per
FELLO_ADK_CAPABILITIES_AND_SECURITY.md ("Tenant binding on every tool call"),
the tenant and org scoping of every tool call MUST be deterministic and
external to the model's reasoning — never inferred from conversation text,
never trusted from anything the model generates.

We achieve this by sourcing identity exclusively from ADK ``session.state``,
which the *server* populates from the verified JWT (web dashboard) or from the
verified WhatsApp-number -> Firebase user resolution (WhatsApp channel) BEFORE
the agent runs. The model can decide *when* to call a tool; it can never decide
*which tenant* the call runs against.

The orchestrator and every sub-agent share one invocation's ``session.state``
(ADK propagates it to sub-agents via the shared invocation id), so the verified
identity flows through the whole agent tree without being re-sent.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Canonical session.state keys. The invoking server sets these from verified
# context. Tools read them through ToolContext.state — never as model arguments.
STATE_TENANT_ID = "tenant_id"      # full email domain, e.g. "my.sliit.lk"
STATE_ORG_ID = "org_id"            # internal UUID, e.g. "org_8f3k2a9x"
STATE_USER_ID = "user_id"          # Firebase UID of the acting user, or None
STATE_CAPABILITIES = "capabilities"  # list[str] from JWT claims, or None
STATE_EVENT_ID = "event_id"        # current event UUID in focus, or None
STATE_CHANNEL = "channel"          # "dashboard" | "whatsapp"
STATE_AUTOMATION_COUNT = "temp:automation_count"  # demo automation counter


class IdentityError(PermissionError):
    """Raised when a tool is invoked without a verified tenant/org context."""


@dataclass
class FelloIdentity:
    """The verified actor + scope a tool call runs under."""

    tenant_id: str
    org_id: str
    user_id: str | None = None
    capabilities: list[str] | None = None
    event_id: str | None = None
    channel: str = "dashboard"
    extra: dict = field(default_factory=dict)

    @property
    def is_verified_user(self) -> bool:
        """True when a real Firebase identity backs this request.

        Unverified WhatsApp senders (no linked Fello account) have no user_id —
        their messages can be used as conversational context but can never
        trigger a state-changing action. See FELLO_DRIVE_AND_WHATSAPP_SECURITY.md.
        """
        return bool(self.user_id)


def identity_from_state(state) -> FelloIdentity:
    """Build a FelloIdentity from an ADK State / mapping.

    Raises IdentityError if the irreducible tenant boundary (tenant_id + org_id)
    is missing — this fails closed: no verified scope means no data access.
    """
    tenant_id = _get(state, STATE_TENANT_ID)
    org_id = _get(state, STATE_ORG_ID)
    if not tenant_id or not org_id:
        raise IdentityError(
            "No verified tenant/org context in session state. The server must "
            "populate tenant_id and org_id from the verified JWT (or verified "
            "WhatsApp identity) before invoking the agent."
        )
    caps = _get(state, STATE_CAPABILITIES)
    return FelloIdentity(
        tenant_id=tenant_id,
        org_id=org_id,
        user_id=_get(state, STATE_USER_ID),
        capabilities=list(caps) if caps is not None else None,
        event_id=_get(state, STATE_EVENT_ID),
        channel=_get(state, STATE_CHANNEL) or "dashboard",
    )


def identity(tool_context) -> FelloIdentity:
    """Convenience: pull the verified identity from a ToolContext."""
    return identity_from_state(tool_context.state)


def resolve_event_id(tool_context, requested: str | None = None) -> str | None:
    """Pick the event scope for a call.

    Prefers the explicitly-requested event (when the user names one), otherwise
    falls back to the event currently in focus in session state. Org ownership
    of whatever event is chosen is still validated inside each skill against the
    verified org_id — this only resolves *which* event, never *which org*.
    """
    if requested:
        return requested
    return _get(tool_context.state, STATE_EVENT_ID)


def build_session_state(
    *,
    tenant_id: str,
    org_id: str,
    user_id: str | None = None,
    capabilities: list[str] | None = None,
    event_id: str | None = None,
    channel: str = "dashboard",
) -> dict:
    """Helper for the server: build the initial session.state for an invocation.

    Pass the output as ADK's session state (or as a state_delta on each run) so
    the agent always operates under freshly-verified identity.
    """
    state: dict = {
        STATE_TENANT_ID: tenant_id,
        STATE_ORG_ID: org_id,
        STATE_CHANNEL: channel,
    }
    if user_id is not None:
        state[STATE_USER_ID] = user_id
    if capabilities is not None:
        state[STATE_CAPABILITIES] = capabilities
    if event_id is not None:
        state[STATE_EVENT_ID] = event_id
    return state


def _get(state, key):
    """Read a key from an ADK State or a plain dict, tolerating both."""
    try:
        return state.get(key)
    except AttributeError:
        return state[key] if key in state else None
