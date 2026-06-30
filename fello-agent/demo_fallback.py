"""Scripted PTI demo fallback (CLAUDE.md §8.4).

If the live agent errors or is too slow during the competition demo, the server
can call :func:`scripted_response` to drive the same PTI coordination narrative
deterministically — including the closing quantified automation count.

This is intentionally dumb (keyword routing, canned cards) so it cannot fail. It
emits the same [CARD:*] / [SUGGESTIONS] markers the real agent does, so the
frontend renders it identically.
"""

from __future__ import annotations

# Ordered (keywords, response) rules. First match wins.
_SCRIPT: list[tuple[tuple[str, ...], str]] = [
    (
        ("pti", "parents", "teacher", "create event", "new event"),
        "Done — I've set up **PTI 2026** as an active event and spun up the core "
        "coordination structure for it.\n\n"
        "[CARD:event]\n"
        '{"name": "PTI 2026", "date": "2026-07-12", "status": "active", "type": "event", "coordinators": ["Kavindu"]}\n'
        "[/CARD]\n"
        "[SUGGESTIONS]\n"
        "Create the team WhatsApp groups | Assign coordinators | Draft the parent invite | Add tasks\n"
        "[/SUGGESTIONS]",
    ),
    (
        ("group", "whatsapp", "create the team"),
        "Created 3 WhatsApp groups and added the right members from your directory — "
        "**PTI Design**, **PTI Logistics**, and **PTI Outreach**.\n\n"
        "[CARD:task]\n"
        '{"title": "Confirm venue & schedule", "assignee": "Logistics Lead", "status": "assigned", "dueDate": "2026-07-02", "eventName": "PTI 2026"}\n'
        "[/CARD]\n"
        "[SUGGESTIONS]\n"
        "Broadcast the kickoff message | Assign design tasks | Draft sponsor outreach | Show event health\n"
        "[/SUGGESTIONS]",
    ),
    (
        ("task", "assign"),
        "Assigned the design and logistics tasks and notified each owner in their group.\n\n"
        "[CARD:task]\n"
        '{"title": "Design the PTI poster", "assignee": "Design Lead", "status": "in_progress", "dueDate": "2026-07-05", "eventName": "PTI 2026"}\n'
        "[/CARD]\n"
        "[SUGGESTIONS]\n"
        "Show event health | Draft sponsor outreach | Broadcast a reminder | Wrap-up summary\n"
        "[/SUGGESTIONS]",
    ),
    (
        ("sponsor", "outreach", "speaker"),
        "Drafted a sponsor outreach message and logged the first three contacts.\n\n"
        "[SUGGESTIONS]\n"
        "Send to all sponsors | Log a response | Show outreach funnel | Show event health\n"
        "[/SUGGESTIONS]",
    ),
    (
        ("health", "insight", "status", "how are we", "summary", "wrap"),
        "Here's where PTI 2026 stands: **78% of tasks complete**, 1 overdue, 0 blocked. "
        "Outreach is converting at 40%. My recommendation: nudge the 1 overdue task today "
        "and you're clear to prep the wrap-up.\n\n"
        "[SUGGESTIONS]\n"
        "Nudge the overdue owner | Generate wrap-up | Show member workload | Close the event\n"
        "[/SUGGESTIONS]",
    ),
]

_CLOSER = (
    "\n\n— In this session Fello automated **{n} coordination actions** that would "
    "have taken a coordinator roughly **{mins} minutes** by hand."
)


def scripted_response(user_message: str, automation_count: int = 7) -> str:
    """Return a deterministic scripted reply for the PTI demo.

    Args:
        user_message: The user's latest message.
        automation_count: Number of automated actions to quote in the closer.
    """
    text = (user_message or "").lower()
    for keywords, response in _SCRIPT:
        if any(k in text for k in keywords):
            return response
    # Default opener
    return (
        "I'm Fello — I coordinate your events end to end. Tell me about the event "
        "you're running and I'll set up the teams, groups, and tasks for you.\n\n"
        "[SUGGESTIONS]\n"
        "Set up the PTI event | Show my events | Draft sponsor outreach | What can you do?\n"
        "[/SUGGESTIONS]"
    )


def closing_line(automation_count: int) -> str:
    """The quantified automation closer to end the demo on (CLAUDE.md §8.4)."""
    return _CLOSER.format(n=automation_count, mins=automation_count * 6)
