"""Document retrieval — weighted PostgreSQL full-text search over the indexed
`documents` table, falling back to a live Google Drive search when the index
has nothing.

Implements the retrieval pipeline from FELLO_ADK_CAPABILITIES_AND_SECURITY.md
("Document Retrieval — RAG-Style System Without a Vector Database"). When
someone asks "send the speaker brief" or "find the logo", we run a deterministic
weighted full-text query (filename > AI description > AI summary) scoped to the
verified org and the event in focus — fast, explainable, and tenant-isolated.

The Postgres index is only as fresh as the last drive-sync run, so it can miss
files uploaded directly to Drive since then. `find_document` checks the index
first; only if that comes back with zero rows does it call
`_search_drive_live` — a live Drive `files.list` search scoped to the relevant
Drive folder (using the org's connected Google account — see `_google.py`).
If the strongest match is a Google Doc, its live text is fetched via the Docs
API so the agent can quote the actual current content instead of a
possibly-stale AI-generated summary.

The org_id used to scope every query comes from the verified agent context, not
from the user's message (CLAUDE.md §5.3 Cloud SQL row isolation).
"""

from __future__ import annotations

from google.adk.tools import ToolContext

from context import identity, resolve_event_id
from . import _postgres
from ._google import (
    get_access_token,
    get_org_drive_folder,
    get_project_access_token,
    get_project_drive_folder,
)

try:
    import httpx
except Exception:  # pragma: no cover
    httpx = None  # type: ignore

_DRIVE_FILES_API = "https://www.googleapis.com/drive/v3/files"
_DOCS_API = "https://docs.googleapis.com/v1/documents"
_SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"
_GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
_GOOGLE_SHEET_MIME = "application/vnd.google-apps.spreadsheet"
_DOC_CONTENT_MAX_CHARS = 4000

# Sentinel event_id drive-sync.js assigns to files at the top of the org's
# Drive root that don't match any active event's name (see walkFolderTree in
# fello-backend/backend/src/drive-sync.js) — i.e. organization-level files.
# Same `documents` table, no separate storage: this is just the event_id an
# org-level file gets. When no event is in focus and the caller doesn't name
# one, this is what "search the org's documents" means.
_ORG_LEVEL = "org_root"

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


_DRIVE_STOPWORDS = {
    "a", "an", "the", "of", "for", "and", "or", "in", "on", "to", "doc",
    "docs", "document", "documents", "file", "files", "find", "search",
}


_FOLDER_MIME = "application/vnd.google-apps.folder"
# Bounds the recursive folder walk below — a typical org tree (root -> event
# -> team node, per drive-sync.js's KNOWN_TEAM_NODES) is only 2-3 levels deep
# with a handful of folders per level, so this is generous headroom, not a
# realistic ceiling to hit.
_MAX_SUBFOLDERS = 50


def _escape_drive_term(term: str) -> str:
    return term.replace("\\", "\\\\").replace("'", "\\'")


def _list_all_subfolder_ids(token: str, root_folder_id: str) -> list[str]:
    """BFS every subfolder under root_folder_id, mirroring drive-sync.js's
    walkFolderTree. Drive's `'X' in parents` query only matches DIRECT
    children of X, so without this a file nested in any subfolder (which is
    how real org/event folders are structured) would never be found live.
    """
    ids = [root_folder_id]
    queue = [root_folder_id]
    while queue and len(ids) < _MAX_SUBFOLDERS:
        current = queue.pop(0)
        try:
            resp = httpx.get(
                _DRIVE_FILES_API,
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "q": f"'{current}' in parents and trashed = false and mimeType = '{_FOLDER_MIME}'",
                    "fields": "files(id)",
                    "pageSize": 100,
                    "corpora": "allDrives",
                    "includeItemsFromAllDrives": "true",
                    "supportsAllDrives": "true",
                },
                timeout=15.0,
            )
            resp.raise_for_status()
            for f in resp.json().get("files", []):
                fid = f["id"]
                if fid not in ids and len(ids) < _MAX_SUBFOLDERS:
                    ids.append(fid)
                    queue.append(fid)
        except Exception:
            break  # partial tree beats none — search whatever we found so far
    return ids


def _drive_search_call(token: str, folder_ids: list[str], q: str, page_size: int = 5) -> list[dict]:
    """One Drive `files.list` call, scoped to a set of folders (root + every
    subfolder under it). Shared Drives enabled (`corpora=allDrives`) since an
    org's connected folder may live in one, not just "My Drive" — the default
    search otherwise silently finds nothing there.
    """
    parents_clause = " or ".join(f"'{fid}' in parents" for fid in folder_ids)
    resp = httpx.get(
        _DRIVE_FILES_API,
        headers={"Authorization": f"Bearer {token}"},
        params={
            "q": f"({parents_clause}) and trashed = false and ({q})",
            "fields": "files(id,name,mimeType,webViewLink,modifiedTime)",
            "pageSize": page_size,
            "orderBy": "modifiedTime desc",
            "corpora": "allDrives",
            "includeItemsFromAllDrives": "true",
            "supportsAllDrives": "true",
        },
        timeout=20.0,
    )
    resp.raise_for_status()
    return resp.json().get("files", [])


def _search_drive_live(token: str, folder_id: str, search_terms: str) -> list[dict]:
    """Live Drive search under one folder (recursively) — the fallback used
    only when the Postgres index has nothing (see find_document). Best-effort:
    any failure (expired grant, API hiccup) just yields no live results, never
    an error surfaced to the user — the "index came up empty" message already
    covers it.

    Uses Drive's advanced search grammar in two passes: an exact-phrase match
    first (precise), then — only if that finds nothing — a broader pass that
    ORs the individual significant words together, so a loosely-worded query
    like "excom doc" still has a shot at matching a file named "Executive
    Committee List" via shared words, instead of requiring a literal substring.
    """
    if httpx is None or not folder_id:
        return []
    try:
        folder_ids = _list_all_subfolder_ids(token, folder_id)
        safe_phrase = _escape_drive_term(search_terms)
        exact = _drive_search_call(
            token, folder_ids,
            f"name contains '{safe_phrase}' or fullText contains '{safe_phrase}'",
        )
        if exact:
            return exact

        words = [w for w in search_terms.lower().split() if len(w) > 2 and w not in _DRIVE_STOPWORDS]
        if not words:
            return []
        clauses = [f"name contains '{_escape_drive_term(w)}' or fullText contains '{_escape_drive_term(w)}'" for w in words]
        return _drive_search_call(token, folder_ids, " or ".join(clauses), page_size=8)
    except Exception:
        return []


def _read_google_doc_text(token: str, doc_id: str) -> str | None:
    """Fetch a Google Doc's current plain-text body via the Docs API."""
    if httpx is None:
        return None
    try:
        resp = httpx.get(
            f"{_DOCS_API}/{doc_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=20.0,
        )
        resp.raise_for_status()
        parts: list[str] = []
        for el in resp.json().get("body", {}).get("content", []):
            for elem in (el.get("paragraph") or {}).get("elements", []):
                run = elem.get("textRun")
                if run and run.get("content"):
                    parts.append(run["content"])
        text = "".join(parts).strip()
        return text[:_DOC_CONTENT_MAX_CHARS] if text else None
    except Exception:
        return None


def _read_google_sheet_text(token: str, sheet_id: str) -> str | None:
    """Fetch a Google Sheet's current text via the Sheets API."""
    if httpx is None:
        return None
    try:
        resp = httpx.get(
            f"{_SHEETS_API}/{sheet_id}?includeGridData=true",
            headers={"Authorization": f"Bearer {token}"},
            timeout=20.0,
        )
        resp.raise_for_status()
        data = resp.json()
        parts = []
        for sheet in data.get("sheets", []):
            for row in sheet.get("data", [{}])[0].get("rowData", []):
                row_vals = []
                for val in row.get("values", []):
                    v = val.get("formattedValue")
                    if v:
                        row_vals.append(v)
                if row_vals:
                    parts.append(" | ".join(row_vals))
        text = "\n".join(parts).strip()
        return text[:_DOC_CONTENT_MAX_CHARS] if text else None
    except Exception:
        return None


def _token_and_folder(evt: str, org_id: str) -> tuple[str | None, str | None]:
    """Resolve (access_token, drive_folder_id) for one search scope.

    Uses the main organization's Google grant for access.
    """
    token, _terr = get_access_token(org_id)
    if evt == _ORG_LEVEL:
        folder_id = get_org_drive_folder(org_id) if token else None
    else:
        folder_id = get_project_drive_folder(evt) if token else None
    return token, folder_id


def find_document(
    search_terms: str,
    tool_context: ToolContext,
    event_id: str | None = None,
    across_events: bool = False,
) -> dict:
    """Find a document by natural-language description.

    Searches the indexed document table first (fast, ranked, explainable).
    Only if that finds nothing does it fall back to a live Google Drive search
    (with a broader keyword-OR pass if an exact-phrase Drive search also comes
    up empty) inside the relevant Drive folder — this catches anything
    uploaded since the last index sync. If the strongest match is a Google
    Doc, its current text is fetched via the Docs API and returned in
    `content_excerpt` so you can quote or summarize it directly instead of
    just linking to it.

    When no event is in focus and none is given, this searches the
    organization's own top-level documents (not tied to any event) — do NOT
    ask the user which event first; only ask if this returns nothing and they
    might have meant a specific event's files.

    Args:
        search_terms: What the user is looking for (e.g. "speaker brief", "logo").
        event_id: Optional explicit event UUID; defaults to the event in focus,
            or the organization's own documents if none is in focus.
        across_events: Only set True when the user clearly asks across every
            event AND the org's own files ("show me logos from past events").
            The live Drive supplement is skipped in this case — it spans too
            many folders to search live — so this relies on the index alone.

    Returns:
        dict with 'matches' (list), a 'resolution' hint, and optionally
        'content_excerpt' (live text of the top match, if it's a Google Doc):
          - "single": exactly one strong match -> agent can send it directly
          - "multiple": ask the user which one
          - "none": say so honestly, don't guess — never invent a title or link
          - "unavailable": neither the document index nor Drive are reachable
    """
    actor = identity(tool_context)

    indexed_rows: list[dict] = []
    index_error: str | None = None
    # Falls back to the org-level bucket, never blocks on "which event?" —
    # a document search with no event in focus almost always means the org's
    # own top-level files.
    evt: str | None = None if across_events else (resolve_event_id(tool_context, event_id) or _ORG_LEVEL)

    if across_events:
        if _postgres.available():
            try:
                indexed_rows = _postgres.query(
                    _SEARCH_SQL_CROSS_EVENT,
                    (search_terms, actor.org_id, search_terms),
                    org_id=actor.org_id,
                )
            except Exception as e:
                index_error = str(e)
    else:
        if _postgres.available():
            try:
                indexed_rows = _postgres.query(
                    _SEARCH_SQL,
                    (search_terms, actor.org_id, evt, search_terms),
                    org_id=actor.org_id,
                )
            except Exception as e:
                index_error = str(e)

    # Live Drive fallback — ONLY when the index came back with nothing. If the
    # index already found matches, trust it and skip the extra API round-trip;
    # a live search never runs for the cross-event case either (it spans every
    # event's folder, no single folder to search).
    matches: list[dict] = list(indexed_rows)
    if not matches and not across_events and evt:
        token, folder_id = _token_and_folder(evt, actor.org_id)
        if token and folder_id:
            for f in _search_drive_live(token, folder_id, search_terms):
                matches.append(
                    {
                        "file_name": f.get("name"),
                        "drive_file_id": f.get("id"),
                        "document_type": "google_doc" if f.get("mimeType") == _GOOGLE_DOC_MIME else ("google_sheet" if f.get("mimeType") == _GOOGLE_SHEET_MIME else None),
                        "description": None,
                        "url": f.get("webViewLink"),
                        "rank": None,  # live results aren't ranked against the FTS score
                        "source": "drive_live",
                    }
                )

    if not matches:
        if index_error:
            return {
                "matches": [],
                "resolution": "unavailable",
                "message": "Couldn't search files right now — the document index and Drive are both unreachable.",
            }
        return {
            "matches": [],
            "resolution": "none",
            "message": f"I couldn't find anything matching '{search_terms}'. Maybe it was uploaded under a different name?",
        }

    # One clearly-dominant ranked match -> resolve directly. A single live-only
    # match with no ranked competitor also counts as strong. Otherwise ask.
    ranked = [m for m in matches if m.get("rank") is not None]
    if len(matches) == 1:
        strong_single = True
    elif len(ranked) >= 2:
        top_rank, next_rank = float(ranked[0]["rank"]), float(ranked[1]["rank"])
        strong_single = top_rank >= 2 * next_rank
    else:
        strong_single = False

    result: dict = {
        "matches": matches,
        "resolution": "single" if strong_single else "multiple",
    }

    # For the top match, try fetching live Google Doc/Sheet content so the agent
    # can quote/summarize the actual current text. We don't reliably know the mime
    # type for indexed (Postgres) rows, so just attempt both — a non-Doc/Sheet file
    # cheaply fails via the APIs.
    if strong_single:
        doc_id = matches[0].get("drive_file_id")
        doc_type = matches[0].get("document_type")
        if doc_id and evt:
            token, _folder_id = _token_and_folder(evt, actor.org_id)
            if token:
                excerpt = None
                if doc_type == "google_doc":
                    excerpt = _read_google_doc_text(token, doc_id)
                elif doc_type == "google_sheet":
                    excerpt = _read_google_sheet_text(token, doc_id)
                else:
                    excerpt = _read_google_doc_text(token, doc_id)
                    if not excerpt:
                        excerpt = _read_google_sheet_text(token, doc_id)
                if excerpt:
                    result["content_excerpt"] = excerpt

    return result
