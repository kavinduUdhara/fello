"""Fello agent skills (ADK tools) + gateway-side helpers.

Tool functions take a ``tool_context: ToolContext`` that ADK injects — the model
never supplies tenant/org scope. WhatsApp-auth helpers run server-side, before
the agent, and are not exposed to the model as tools.
"""

from .communication import (
    send_whatsapp_message,
    create_whatsapp_group,
    add_member_to_group,
    broadcast_message,
)
from .tasks import (
    create_task,
    update_task_status,
    list_tasks,
    assign_task,
)
from .members import (
    lookup_member,
    list_members,
    get_member_whatsapp_jid,
)
from .events import (
    create_project,
    get_event_details,
    update_event_status,
    list_upcoming_events,
)
from .documents import (
    create_document_stub,
    link_document,
    list_documents,
)
from .outreach import (
    draft_outreach_message,
    log_outreach_attempt,
    list_outreach,
)
from .retrieval import find_document
from .insights import event_health, member_engagement, outreach_funnel
from .google_workspace import (
    create_google_form,
    update_google_form,
    create_google_doc,
    update_google_doc,
    create_google_sheet,
    update_google_sheet,
    create_google_slides,
    update_google_slides,
)
from .invites import (
    invite_member,
    invite_org_members,
    list_pending_invite_suggestions,
    remove_member,
    send_org_invite_email,
    send_org_invite_emails,
)
from . import whatsapp_auth

__all__ = [
    # communication
    "send_whatsapp_message",
    "create_whatsapp_group",
    "add_member_to_group",
    "broadcast_message",
    # tasks
    "create_task",
    "update_task_status",
    "list_tasks",
    "assign_task",
    # members
    "lookup_member",
    "list_members",
    "get_member_whatsapp_jid",
    # events
    "create_project",
    "get_event_details",
    "update_event_status",
    "list_upcoming_events",
    # documents
    "create_document_stub",
    "link_document",
    "list_documents",
    # outreach
    "draft_outreach_message",
    "log_outreach_attempt",
    "list_outreach",
    # retrieval (weighted FTS)
    "find_document",
    # insights (decision intelligence)
    "event_health",
    "member_engagement",
    "outreach_funnel",
    # google workspace
    "create_google_form",
    "update_google_form",
    "create_google_doc",
    "update_google_doc",
    "create_google_sheet",
    "update_google_sheet",
    "create_google_slides",
    "update_google_slides",
    # invites
    "invite_member",
    "invite_org_members",
    "list_pending_invite_suggestions",
    "remove_member",
    "send_org_invite_email",
    "send_org_invite_emails",
    # gateway-side helpers (not model tools)
    "whatsapp_auth",
]
