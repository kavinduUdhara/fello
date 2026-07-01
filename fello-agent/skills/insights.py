"""Decision-intelligence skills — the analytics brain behind the Insights agent.

This is what reframes Fello for the "AI for Better Living and Smarter
Communities / Decision Intelligence" theme: instead of only *executing*
coordination actions, the agent can *analyze* an org's own data, surface
patterns and anomalies, and recommend the next decision.

Everything here is read-only and scoped to the verified org. Computations run in
Python over Firestore reads so they work without extra infrastructure; the
returned dicts carry both the raw numbers and a plain-language recommendations
list the agent can speak back to a coordinator.
"""

from __future__ import annotations

from datetime import datetime, timezone

from google.adk.tools import ToolContext

from context import identity, resolve_event_id
from ._firestore import db


def _today() -> datetime:
    return datetime.now(timezone.utc)


def _parse_date(value) -> datetime | None:
    if not value:
        return None
    try:
        if hasattr(value, "isoformat") and not isinstance(value, str):
            # Firestore Timestamp / datetime
            return value if isinstance(value, datetime) else value.to_datetime()  # type: ignore[attr-defined]
        s = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def event_health(tool_context: ToolContext, event_id: str | None = None) -> dict:
    """Compute task-completion health for an event, with recommendations.

    Returns a structured health report: counts by status, % complete, overdue
    and blocked counts, plus a recommendations list the agent can act on.
    """
    actor = identity(tool_context)
    evt = resolve_event_id(tool_context, event_id)
    if not evt:
        return {"error": "No event specified."}

    try:
        tasks = [
            d.to_dict()
            for d in db()
            .collection("tasks")
            .where("orgId", "==", actor.org_id)
            .where("projectId", "==", evt)
            .stream()
        ]
    except Exception as e:
        return {"error": str(e)}

    total = len(tasks)
    by_status: dict[str, int] = {}
    overdue = 0
    blocked = 0
    now = _today()
    for t in tasks:
        st = t.get("status", "unassigned")
        by_status[st] = by_status.get(st, 0) + 1
        if st == "blocked":
            blocked += 1
        due = _parse_date(t.get("dueDate"))
        if due and due < now and st != "completed":
            overdue += 1

    completed = by_status.get("completed", 0)
    pct = round(100 * completed / total) if total else 0

    recs: list[str] = []
    if total == 0:
        recs.append("No tasks created yet — break the event down into tasks so progress can be tracked.")
    if overdue:
        recs.append(f"{overdue} task(s) are past their deadline — follow up with the assignees today.")
    if blocked:
        recs.append(f"{blocked} task(s) are blocked — unblock them before they stall the timeline.")
    if by_status.get("unassigned"):
        recs.append(f"{by_status['unassigned']} task(s) have no owner — assign them so nothing falls through.")
    if total and pct >= 80 and not overdue and not blocked:
        recs.append("This event is in good shape — consider preparing the wrap-up summary.")

    return {
        "event_id": evt,
        "total_tasks": total,
        "by_status": by_status,
        "percent_complete": pct,
        "overdue": overdue,
        "blocked": blocked,
        "recommendations": recs,
    }


def member_engagement(tool_context: ToolContext, event_id: str | None = None) -> dict:
    """Surface workload imbalance: who is overloaded, who is idle.

    Helps a coordinator rebalance work — an anomaly/pattern decision the theme
    rewards. Scoped to one event when in focus, else across the org's tasks.
    """
    actor = identity(tool_context)
    evt = resolve_event_id(tool_context, event_id)

    try:
        q = db().collection("tasks").where("orgId", "==", actor.org_id)
        if evt:
            q = q.where("projectId", "==", evt)
        tasks = [d.to_dict() for d in q.stream()]
        members = [
            d.to_dict()
            for d in db().collection("memberships").where("orgId", "==", actor.org_id).stream()
        ]
    except Exception as e:
        return {"error": str(e)}

    load: dict[str, int] = {}
    for t in tasks:
        if t.get("status") == "completed":
            continue
        for uid in t.get("assignedTo") or []:
            load[uid] = load.get(uid, 0) + 1

    member_uids = {m.get("userId") for m in members if m.get("userId")}
    idle = sorted(uid for uid in member_uids if load.get(uid, 0) == 0)
    overloaded = sorted(
        ((uid, n) for uid, n in load.items() if n >= 4), key=lambda x: -x[1]
    )

    recs: list[str] = []
    if overloaded:
        recs.append(
            f"{len(overloaded)} member(s) are carrying 4+ open tasks — consider redistributing their load."
        )
    if idle and tasks:
        recs.append(f"{len(idle)} member(s) have no open tasks — they have capacity to help.")

    return {
        "open_task_load": load,
        "idle_member_uids": idle,
        "overloaded": [{"uid": u, "open_tasks": n} for u, n in overloaded],
        "recommendations": recs,
    }


def outreach_funnel(tool_context: ToolContext, event_id: str | None = None) -> dict:
    """Conversion funnel over logged outreach (contacted -> confirmed)."""
    actor = identity(tool_context)
    evt = resolve_event_id(tool_context, event_id)
    if not evt:
        return {"error": "No event specified."}
    try:
        items = [
            d.to_dict()
            for d in db()
            .collection("outreach")
            .where("orgId", "==", actor.org_id)
            .where("projectId", "==", evt)
            .stream()
        ]
    except Exception as e:
        return {"error": str(e)}

    by_status: dict[str, int] = {}
    for it in items:
        st = it.get("status", "contacted")
        by_status[st] = by_status.get(st, 0) + 1

    total = len(items)
    confirmed = by_status.get("confirmed", 0)
    no_response = by_status.get("no_response", 0) + by_status.get("contacted", 0)
    conversion = round(100 * confirmed / total) if total else 0

    recs: list[str] = []
    if no_response:
        recs.append(f"{no_response} contact(s) haven't responded — a follow-up nudge usually lifts conversion.")
    if total and conversion < 30:
        recs.append("Conversion is low — consider broadening the outreach list or revising the pitch.")

    return {
        "total_outreach": total,
        "by_status": by_status,
        "confirmed": confirmed,
        "conversion_percent": conversion,
        "recommendations": recs,
    }
