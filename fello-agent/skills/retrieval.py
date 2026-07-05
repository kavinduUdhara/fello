"""Document retrieval — weighted PostgreSQL full-text search, no vector DB.

Implements the retrieval pipeline from FELLO_ADK_CAPABILITIES_AND_SECURITY.md
("Document Retrieval — RAG-Style System Without a Vector Database"). When
someone asks "send the speaker brief" or "find the logo", we run a deterministic
weighted full-text query (filename > AI description > AI summary) scoped to the
verified org and the event in focus — fast, explainable, and tenant-isolated.

The org_id used to scope every query comes from the verified agent context, not
from the user's message (CLAUDE.md §5.3 Cloud SQL row isolation).
"""

from __future__ import annotations

from google.adk.tools import ToolContext

from context import identity, resolve_event_id
from . import _postgres

# Weighted FTS, scoped to org + event. ts_rank exposes *why* a row matched, so a
# result is always explainable — something a black-box vector score cannot give.
_SEARCH_SQL = """
    SELECT file_name, drive_file_id, document_type, description,
           ts_rank(search_vector, plainto_tsquery('english', %s)) AS rank
    FROM documents
    WHERE org_id = %s AND event_id = %s
      AND search_vector @@ plainto_tsquery('english', %s)
    ORDER BY rank DESC
    LIMIT 5;
"""

# Cross-event variant — only used when the user explicitly asks across events.
_SEARCH_SQL_CROSS_EVENT = """
    SELECT file_name, drive_file_id, document_type, description, event_id,
           ts_rank(search_vector, plainto_tsquery('english', %s)) AS rank
    FROM documents
    WHERE org_id = %s
      AND search_vector @@ plainto_tsquery('english', %s)
    ORDER BY rank DESC
    LIMIT 5;
"""


def find_document(
    search_terms: str,
    tool_context: ToolContext,
    event_id: str | None = None,
    across_events: bool = False,
) -> dict:
    """Find an event document by natural-language description.

    Args:
        search_terms: What the user is looking for (e.g. "speaker brief", "logo").
        event_id: Optional explicit event UUID; defaults to the event in focus.
        across_events: Only set True when the user clearly asks across events
            ("show me logos from past events"). Default scopes to one event.

    Returns:
        dict with 'matches' (list) and a 'resolution' hint:
          - "single": exactly one strong match -> agent can send it directly
          - "multiple": ask the user which one
          - "none": say so honestly, don't guess
          - "unavailable": the document index isn't connected
    """
    actor = identity(tool_context)

    if not _postgres.available():
        return {
            "matches": [],
            "resolution": "unavailable",
            "message": "The document index isn't connected yet, so I can't search files right now.",
        }

    try:
        if across_events:
            rows = _postgres.query(
                _SEARCH_SQL_CROSS_EVENT,
                (search_terms, actor.org_id, search_terms),
                org_id=actor.org_id,
            )
        else:
            evt = resolve_event_id(tool_context, event_id)
            if not evt:
                return {"matches": [], "resolution": "none", "message": "Which event's files should I search?"}
            rows = _postgres.query(
                _SEARCH_SQL,
                (search_terms, actor.org_id, evt, search_terms),
                org_id=actor.org_id,
            )
    except Exception as e:
        return {"matches": [], "resolution": "unavailable", "message": f"Search failed: {e}"}

    if not rows:
        return {
            "matches": [],
            "resolution": "none",
            "message": f"I couldn't find anything matching '{search_terms}'. Maybe it was uploaded under a different name?",
        }

    # One clearly-dominant match -> resolve directly. Otherwise ask.
    top = rows[0]
    strong_single = len(rows) == 1 or (
        len(rows) > 1 and float(top["rank"]) >= 2 * float(rows[1]["rank"])
    )
    return {
        "matches": rows,
        "resolution": "single" if strong_single else "multiple",
    }
