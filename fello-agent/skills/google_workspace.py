"""Google Workspace skills — act in the org's connected Google account.

Covers: Google Forms, Docs, Sheets, and Slides.  Each skill uses the org's
(or project's) stored OAuth grant — scoped by the verified org_id from context
— so the agent creates files in the exact Google account the org connected in
Settings, inside the project's dedicated Drive folder.
"""

from __future__ import annotations

from google.adk.tools import ToolContext

import authz
from context import identity, resolve_event_id
from ._google import get_access_token, get_project_access_token, get_project_drive_folder

try:
    import httpx
except Exception:  # pragma: no cover
    httpx = None  # type: ignore

_FORMS_API        = "https://forms.googleapis.com/v1/forms"
_CALENDAR_API     = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
_DOCS_API         = "https://docs.googleapis.com/v1/documents"
_SHEETS_API       = "https://sheets.googleapis.com/v4/spreadsheets"
_SLIDES_API       = "https://slides.googleapis.com/v1/presentations"
_DRIVE_FILES_API  = "https://www.googleapis.com/drive/v3/files"


def create_google_form(
    title: str,
    description: str,
    questions: list[str],
    tool_context: ToolContext,
) -> dict:
    """Create a Google Form in the organization's connected Google account.

    Args:
        title: The form title (e.g. "PTI 2026 Parent Registration").
        description: A short description shown under the title (or "").
        questions: A list of question prompts; each becomes a short-answer field.

    Returns:
        dict with success, responderUri (share link), and editUri, or an error.
    """
    err = authz.require(tool_context, authz.CAP_DOCUMENTS_MANAGE)
    if err:
        return {"success": False, "error": err}
    if httpx is None:
        return {"success": False, "error": "HTTP client unavailable on the server."}

    actor = identity(tool_context)
    token, terr = get_access_token(actor.org_id)
    if terr:
        return {"success": False, "error": terr}

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        # 1. Create the form (the API only accepts the title at creation time).
        created = httpx.post(
            _FORMS_API,
            headers=headers,
            json={"info": {"title": title, "documentTitle": title}},
            timeout=20.0,
        )
        created.raise_for_status()
        form = created.json()
        form_id = form["formId"]

        # 2. Add description + questions in a batch update.
        requests: list[dict] = []
        if description:
            requests.append(
                {
                    "updateFormInfo": {
                        "info": {"description": description},
                        "updateMask": "description",
                    }
                }
            )
        for i, q in enumerate(questions or []):
            requests.append(
                {
                    "createItem": {
                        "item": {
                            "title": q,
                            "questionItem": {
                                "question": {
                                    "required": False,
                                    "textQuestion": {"paragraph": False},
                                }
                            },
                        },
                        "location": {"index": i},
                    }
                }
            )
        if requests:
            upd = httpx.post(
                f"{_FORMS_API}/{form_id}:batchUpdate",
                headers=headers,
                json={"requests": requests},
                timeout=20.0,
            )
            upd.raise_for_status()

        responder = form.get("responderUri") or f"https://docs.google.com/forms/d/{form_id}/viewform"
        return {
            "success": True,
            "form_id": form_id,
            "responderUri": responder,
            "editUri": f"https://docs.google.com/forms/d/{form_id}/edit",
        }
    except Exception as e:
        return {"success": False, "error": f"Google Forms API error: {_detail(e)}"}


def update_google_form(
    form_id: str,
    title: str,
    description: str,
    add_questions: list[str],
    tool_context: ToolContext,
) -> dict:
    """Edit an EXISTING Google Form in the org's connected Google account.

    Use this — never create_google_form — when the user asks to rename, change the
    description of, or add questions to a form they already created. Pass the
    form_id from the earlier create_google_form result (the editUri ends with
    ``/forms/d/<form_id>/edit``). Leave a field empty ("" or []) to keep it as is.

    Args:
        form_id: The id of the form to edit (from a prior create result / edit URL).
        title: New form title, or "" to leave unchanged.
        description: New description, or "" to leave unchanged.
        add_questions: Extra question prompts to append, or [] for none.

    Returns:
        dict with success, responderUri, and editUri, or an error.
    """
    err = authz.require(tool_context, authz.CAP_DOCUMENTS_MANAGE)
    if err:
        return {"success": False, "error": err}
    if httpx is None:
        return {"success": False, "error": "HTTP client unavailable on the server."}
    if not form_id:
        return {"success": False, "error": "form_id is required to edit a form."}

    actor = identity(tool_context)
    token, terr = get_access_token(actor.org_id)
    if terr:
        return {"success": False, "error": terr}

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        # Find the next free index so appended questions go to the end.
        existing = httpx.get(f"{_FORMS_API}/{form_id}", headers=headers, timeout=20.0)
        existing.raise_for_status()
        form = existing.json()
        start = len(form.get("items", []) or [])

        requests: list[dict] = []
        if title:
            requests.append(
                {"updateFormInfo": {"info": {"title": title}, "updateMask": "title"}}
            )
        if description:
            requests.append(
                {
                    "updateFormInfo": {
                        "info": {"description": description},
                        "updateMask": "description",
                    }
                }
            )
        for i, q in enumerate(add_questions or []):
            requests.append(
                {
                    "createItem": {
                        "item": {
                            "title": q,
                            "questionItem": {
                                "question": {
                                    "required": False,
                                    "textQuestion": {"paragraph": False},
                                }
                            },
                        },
                        "location": {"index": start + i},
                    }
                }
            )
        if not requests:
            return {"success": False, "error": "Nothing to update — provide a title, description, or questions."}

        upd = httpx.post(
            f"{_FORMS_API}/{form_id}:batchUpdate",
            headers=headers,
            json={"requests": requests},
            timeout=20.0,
        )
        upd.raise_for_status()

        return {
            "success": True,
            "form_id": form_id,
            "responderUri": form.get("responderUri")
            or f"https://docs.google.com/forms/d/{form_id}/viewform",
            "editUri": f"https://docs.google.com/forms/d/{form_id}/edit",
        }
    except Exception as e:
        return {"success": False, "error": f"Google Forms API error: {_detail(e)}"}


def create_google_doc(title: str, body_text: str, tool_context: ToolContext) -> dict:
    """Create a Google Doc in the project's Drive folder.

    Args:
        title: Document title (e.g. "Partnership Proposal").
        body_text: Initial body content to insert, or "" for a blank document.

    Returns:
        dict with success, doc_id, and url (the edit link), or an error.
    """
    err = authz.require(tool_context, authz.CAP_DOCUMENTS_MANAGE)
    if err:
        return {"success": False, "error": err}
    if httpx is None:
        return {"success": False, "error": "HTTP client unavailable on the server."}

    actor = identity(tool_context)
    project_id = resolve_event_id(tool_context)
    if not project_id:
        return {
            "success": False,
            "error": "Which project is this for? I need a project in focus to know which Drive folder to use.",
        }

    token, terr = get_project_access_token(project_id, actor.org_id)
    if terr:
        return {"success": False, "error": terr}

    folder_id = get_project_drive_folder(project_id)
    hdrs = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        # 1. Create the document.
        created = httpx.post(_DOCS_API, headers=hdrs, json={"title": title}, timeout=20.0)
        created.raise_for_status()
        doc_id = created.json()["documentId"]

        # 2. Insert body text (batchUpdate with insertText at index 1).
        if body_text:
            upd = httpx.post(
                f"{_DOCS_API}/{doc_id}:batchUpdate",
                headers=hdrs,
                json={"requests": [{"insertText": {"location": {"index": 1}, "text": body_text}}]},
                timeout=20.0,
            )
            upd.raise_for_status()

        # 3. Move into the project's Drive folder.
        if folder_id:
            httpx.patch(
                f"{_DRIVE_FILES_API}/{doc_id}",
                headers=hdrs,
                params={"addParents": folder_id, "removeParents": "root"},
                timeout=20.0,
            ).raise_for_status()

        return {
            "success": True,
            "doc_id": doc_id,
            "url": f"https://docs.google.com/document/d/{doc_id}/edit",
        }
    except Exception as e:
        return {"success": False, "error": f"Google Docs API error: {_detail(e)}"}


def update_google_doc(doc_id: str, append_text: str, tool_context: ToolContext) -> dict:
    """Append text to an EXISTING Google Doc.

    Use this — never create_google_doc — when the user asks to add content to a
    document they already created.  Pass the doc_id from the earlier create result
    (the url ends with ``/document/d/<doc_id>/edit``).

    Args:
        doc_id: The id of the document to edit (from a prior create result / URL).
        append_text: Text to append at the end of the document.

    Returns:
        dict with success and url, or an error.
    """
    err = authz.require(tool_context, authz.CAP_DOCUMENTS_MANAGE)
    if err:
        return {"success": False, "error": err}
    if httpx is None:
        return {"success": False, "error": "HTTP client unavailable on the server."}
    if not doc_id:
        return {"success": False, "error": "doc_id is required to update a document."}
    if not append_text:
        return {"success": False, "error": "Nothing to update — provide append_text."}

    actor = identity(tool_context)
    project_id = resolve_event_id(tool_context)
    if project_id:
        token, terr = get_project_access_token(project_id, actor.org_id)
    else:
        token, terr = get_access_token(actor.org_id)
    if terr:
        return {"success": False, "error": terr}

    hdrs = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        existing = httpx.get(f"{_DOCS_API}/{doc_id}", headers=hdrs, timeout=20.0)
        existing.raise_for_status()
        content = existing.json().get("body", {}).get("content", [])
        end_index = (content[-1].get("endIndex", 1) if content else 1) - 1

        httpx.post(
            f"{_DOCS_API}/{doc_id}:batchUpdate",
            headers=hdrs,
            json={"requests": [{"insertText": {"location": {"index": end_index}, "text": "\n" + append_text}}]},
            timeout=20.0,
        ).raise_for_status()

        return {
            "success": True,
            "doc_id": doc_id,
            "url": f"https://docs.google.com/document/d/{doc_id}/edit",
        }
    except Exception as e:
        return {"success": False, "error": f"Google Docs API error: {_detail(e)}"}


def create_google_sheet(
    title: str,
    headers: list[str],
    rows: list[list[str]],
    tool_context: ToolContext,
) -> dict:
    """Create a Google Sheet in the project's Drive folder.

    Args:
        title: Spreadsheet title (e.g. "PTI 2026 Budget").
        headers: Column header row (e.g. ["Item", "Cost", "Status"]), or [].
        rows: Data rows to pre-populate, or [].

    Returns:
        dict with success, sheet_id, and url (the edit link), or an error.
    """
    err = authz.require(tool_context, authz.CAP_DOCUMENTS_MANAGE)
    if err:
        return {"success": False, "error": err}
    if httpx is None:
        return {"success": False, "error": "HTTP client unavailable on the server."}

    actor = identity(tool_context)
    project_id = resolve_event_id(tool_context)
    if not project_id:
        return {
            "success": False,
            "error": "Which project is this for? I need a project in focus to know which Drive folder to use.",
        }

    token, terr = get_project_access_token(project_id, actor.org_id)
    if terr:
        return {"success": False, "error": terr}

    folder_id = get_project_drive_folder(project_id)
    hdrs = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        # 1. Create the spreadsheet.
        created = httpx.post(
            _SHEETS_API,
            headers=hdrs,
            json={"properties": {"title": title}},
            timeout=20.0,
        )
        created.raise_for_status()
        sheet_id = created.json()["spreadsheetId"]

        # 2. Append headers + rows via values.append.
        values = []
        if headers:
            values.append(headers)
        if rows:
            values.extend(rows)
        if values:
            httpx.post(
                f"{_SHEETS_API}/{sheet_id}/values/A1:append",
                headers=hdrs,
                params={"valueInputOption": "RAW"},
                json={"values": values},
                timeout=20.0,
            ).raise_for_status()

        # 3. Move into the project's Drive folder.
        if folder_id:
            httpx.patch(
                f"{_DRIVE_FILES_API}/{sheet_id}",
                headers=hdrs,
                params={"addParents": folder_id, "removeParents": "root"},
                timeout=20.0,
            ).raise_for_status()

        return {
            "success": True,
            "sheet_id": sheet_id,
            "url": f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit",
        }
    except Exception as e:
        return {"success": False, "error": f"Google Sheets API error: {_detail(e)}"}


def update_google_sheet(
    sheet_id: str,
    append_rows: list[list[str]],
    tool_context: ToolContext,
) -> dict:
    """Append rows to an EXISTING Google Sheet.

    Use this — never create_google_sheet — when the user asks to add rows to a
    spreadsheet they already created.  Pass the sheet_id from the earlier create
    result (the url ends with ``/spreadsheets/d/<sheet_id>/edit``).

    Args:
        sheet_id: The spreadsheet id to edit.
        append_rows: Rows of values to append (e.g. [["Banners", "1500", "Paid"]]).

    Returns:
        dict with success and url, or an error.
    """
    err = authz.require(tool_context, authz.CAP_DOCUMENTS_MANAGE)
    if err:
        return {"success": False, "error": err}
    if httpx is None:
        return {"success": False, "error": "HTTP client unavailable on the server."}
    if not sheet_id:
        return {"success": False, "error": "sheet_id is required to update a spreadsheet."}
    if not append_rows:
        return {"success": False, "error": "Nothing to update — provide append_rows."}

    actor = identity(tool_context)
    project_id = resolve_event_id(tool_context)
    if project_id:
        token, terr = get_project_access_token(project_id, actor.org_id)
    else:
        token, terr = get_access_token(actor.org_id)
    if terr:
        return {"success": False, "error": terr}

    hdrs = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        httpx.post(
            f"{_SHEETS_API}/{sheet_id}/values/A1:append",
            headers=hdrs,
            params={"valueInputOption": "RAW"},
            json={"values": append_rows},
            timeout=20.0,
        ).raise_for_status()

        return {
            "success": True,
            "sheet_id": sheet_id,
            "url": f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit",
        }
    except Exception as e:
        return {"success": False, "error": f"Google Sheets API error: {_detail(e)}"}


def create_google_slides(
    title: str,
    slide_titles: list[str],
    tool_context: ToolContext,
) -> dict:
    """Create a Google Slides presentation in the project's Drive folder.

    Args:
        title: Presentation title (e.g. "PTI 2026 Pitch Deck").
        slide_titles: Title for each slide to create beyond the default first slide
            (e.g. ["Agenda", "Team", "Timeline"]), or [].

    Returns:
        dict with success, presentation_id, and url (the edit link), or an error.
    """
    err = authz.require(tool_context, authz.CAP_DOCUMENTS_MANAGE)
    if err:
        return {"success": False, "error": err}
    if httpx is None:
        return {"success": False, "error": "HTTP client unavailable on the server."}

    actor = identity(tool_context)
    project_id = resolve_event_id(tool_context)
    if not project_id:
        return {
            "success": False,
            "error": "Which project is this for? I need a project in focus to know which Drive folder to use.",
        }

    token, terr = get_project_access_token(project_id, actor.org_id)
    if terr:
        return {"success": False, "error": terr}

    folder_id = get_project_drive_folder(project_id)
    hdrs = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        # 1. Create the presentation.
        created = httpx.post(
            _SLIDES_API,
            headers=hdrs,
            json={"title": title},
            timeout=20.0,
        )
        created.raise_for_status()
        pres_id = created.json()["presentationId"]

        # 2. Add one slide per entry in slide_titles.
        if slide_titles:
            requests = [
                {
                    "createSlide": {
                        "insertionIndex": i + 1,
                        "slideLayoutReference": {"predefinedLayout": "TITLE_AND_BODY"},
                    }
                }
                for i in range(len(slide_titles))
            ]
            httpx.post(
                f"{_SLIDES_API}/{pres_id}:batchUpdate",
                headers=hdrs,
                json={"requests": requests},
                timeout=20.0,
            ).raise_for_status()

        # 3. Move into the project's Drive folder.
        if folder_id:
            httpx.patch(
                f"{_DRIVE_FILES_API}/{pres_id}",
                headers=hdrs,
                params={"addParents": folder_id, "removeParents": "root"},
                timeout=20.0,
            ).raise_for_status()

        return {
            "success": True,
            "presentation_id": pres_id,
            "url": f"https://docs.google.com/presentation/d/{pres_id}/edit",
        }
    except Exception as e:
        return {"success": False, "error": f"Google Slides API error: {_detail(e)}"}


def update_google_slides(
    presentation_id: str,
    add_slide_titles: list[str],
    tool_context: ToolContext,
) -> dict:
    """Append slides to an EXISTING Google Slides presentation.

    Use this — never create_google_slides — when the user asks to add slides to a
    presentation they already created.  Pass the presentation_id from the earlier
    create result (the url ends with ``/presentation/d/<presentation_id>/edit``).

    Args:
        presentation_id: The presentation id to edit.
        add_slide_titles: Slide entries to append (one new slide per entry).

    Returns:
        dict with success and url, or an error.
    """
    err = authz.require(tool_context, authz.CAP_DOCUMENTS_MANAGE)
    if err:
        return {"success": False, "error": err}
    if httpx is None:
        return {"success": False, "error": "HTTP client unavailable on the server."}
    if not presentation_id:
        return {"success": False, "error": "presentation_id is required to update a presentation."}
    if not add_slide_titles:
        return {"success": False, "error": "Nothing to update — provide add_slide_titles."}

    actor = identity(tool_context)
    project_id = resolve_event_id(tool_context)
    if project_id:
        token, terr = get_project_access_token(project_id, actor.org_id)
    else:
        token, terr = get_access_token(actor.org_id)
    if terr:
        return {"success": False, "error": terr}

    hdrs = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        existing = httpx.get(f"{_SLIDES_API}/{presentation_id}", headers=hdrs, timeout=20.0)
        existing.raise_for_status()
        slide_count = len(existing.json().get("slides", []))

        requests = [
            {
                "createSlide": {
                    "insertionIndex": slide_count + i,
                    "slideLayoutReference": {"predefinedLayout": "TITLE_AND_BODY"},
                }
            }
            for i in range(len(add_slide_titles))
        ]
        httpx.post(
            f"{_SLIDES_API}/{presentation_id}:batchUpdate",
            headers=hdrs,
            json={"requests": requests},
            timeout=20.0,
        ).raise_for_status()

        return {
            "success": True,
            "presentation_id": presentation_id,
            "url": f"https://docs.google.com/presentation/d/{presentation_id}/edit",
        }
    except Exception as e:
        return {"success": False, "error": f"Google Slides API error: {_detail(e)}"}


def create_calendar_event(
    title: str,
    start: str,
    end: str,
    description: str,
    attendee_emails: list[str],
    tool_context: ToolContext,
) -> dict:
    """Create a Google Calendar event in the org's connected Google account.

    Use for scheduling meetings, interview slots, deadlines-as-events, or any
    "put it on the calendar" request (e.g. volunteer interview time slots).

    Args:
        title: Event title (e.g. "PTI volunteer interview — slot 1").
        start: Start time as ISO 8601 with timezone offset, e.g. "2026-07-12T10:00:00+05:30".
        end: End time in the same format (must be after start).
        description: Optional details shown in the invite (or "").
        attendee_emails: Emails to invite (they get a Google Calendar invite), or [].

    Returns:
        dict with success, event_id, and htmlLink (the calendar link), or an error.
    """
    err = authz.require(tool_context, authz.CAP_EVENTS_MANAGE)
    if err:
        return {"success": False, "error": err}
    if httpx is None:
        return {"success": False, "error": "HTTP client unavailable on the server."}
    if not title or not start or not end:
        return {"success": False, "error": "title, start and end are all required."}

    actor = identity(tool_context)
    token, terr = get_access_token(actor.org_id)
    if terr:
        return {"success": False, "error": terr}

    body: dict = {
        "summary": title,
        "start": {"dateTime": start},
        "end": {"dateTime": end},
    }
    if description:
        body["description"] = description
    if attendee_emails:
        body["attendees"] = [{"email": e} for e in attendee_emails if e and "@" in e]

    hdrs = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        created = httpx.post(
            _CALENDAR_API,
            headers=hdrs,
            params={"sendUpdates": "all"} if attendee_emails else None,
            json=body,
            timeout=20.0,
        )
        created.raise_for_status()
        evt = created.json()
        return {
            "success": True,
            "event_id": evt.get("id"),
            "htmlLink": evt.get("htmlLink"),
            "start": start,
            "end": end,
            "attendees": len(body.get("attendees", [])),
        }
    except Exception as e:
        return {"success": False, "error": f"Google Calendar API error: {_detail(e)}"}


def list_calendar_events(tool_context: ToolContext, time_min: str, time_max: str) -> dict:
    """List upcoming Google Calendar events in the org's connected account. Read-only.

    Args:
        time_min: ISO 8601 lower bound with offset, e.g. "2026-07-05T00:00:00+05:30".
        time_max: ISO 8601 upper bound (e.g. one/two weeks later).

    Returns:
        dict with events: [{title, start, end, htmlLink}], or an error.
    """
    if httpx is None:
        return {"success": False, "error": "HTTP client unavailable on the server."}

    actor = identity(tool_context)
    token, terr = get_access_token(actor.org_id)
    if terr:
        return {"success": False, "error": terr}

    try:
        resp = httpx.get(
            _CALENDAR_API,
            headers={"Authorization": f"Bearer {token}"},
            params={
                "timeMin": time_min,
                "timeMax": time_max,
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": "25",
            },
            timeout=20.0,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        events = [
            {
                "title": it.get("summary"),
                "start": (it.get("start") or {}).get("dateTime") or (it.get("start") or {}).get("date"),
                "end": (it.get("end") or {}).get("dateTime") or (it.get("end") or {}).get("date"),
                "htmlLink": it.get("htmlLink"),
            }
            for it in items
        ]
        return {"success": True, "events": events, "count": len(events)}
    except Exception as e:
        return {"success": False, "error": f"Google Calendar API error: {_detail(e)}"}


def _detail(e: Exception) -> str:
    try:
        return e.response.text[:300]  # type: ignore[attr-defined]
    except Exception:
        return str(e)


def _execute_with_token_fallback(
    tool_context: ToolContext,
    api_call,
) -> dict:
    actor = identity(tool_context)
    project_id = resolve_event_id(tool_context)
    
    tokens = []
    if project_id:
        ptok, _ = get_project_access_token(project_id, actor.org_id)
        if ptok:
            tokens.append(ptok)
            
    otok, _ = get_access_token(actor.org_id)
    if otok and otok not in tokens:
        tokens.append(otok)
        
    if not tokens:
        return {"success": False, "error": "No Google access token available (neither project nor org level)."}

    last_err = None
    for token in tokens:
        try:
            resp = api_call(token)
            resp.raise_for_status()
            return {"success": True, "data": resp.json()}
        except Exception as e:
            last_err = e
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (401, 403, 404):
                continue
            if status == 400:
                err_text = _detail(e).lower()
                if "not a document" in err_text or "not a spreadsheet" in err_text or "not a presentation" in err_text or "not a form" in err_text:
                    return {"success": False, "error": f"API error: This file appears to be a different type. Please use the correct read tool (e.g. read_google_sheet for spreadsheets). Detail: {_detail(e)}"}
                break
            break
            
    return {"success": False, "error": f"Google API error: {_detail(last_err)}"}


def read_google_form(form_id: str, tool_context: ToolContext) -> dict:
    """Read a Google Form.
    
    Args:
        form_id: The ID of the Google Form.
        
    Returns:
        dict with success and form data, or an error.
    """
    err = authz.require(tool_context, authz.CAP_DOCUMENTS_MANAGE)
    if err:
        return {"success": False, "error": err}
    if httpx is None:
        return {"success": False, "error": "HTTP client unavailable on the server."}

    def _call(token: str):
        resp = httpx.get(f"{_FORMS_API}/{form_id}", headers={"Authorization": f"Bearer {token}"}, timeout=20.0)
        resp.raise_for_status()
        form_data = resp.json()
        
        # Try to fetch responses if we have permission
        try:
            resp_data = httpx.get(f"{_FORMS_API}/{form_id}/responses", headers={"Authorization": f"Bearer {token}"}, timeout=20.0)
            if resp_data.status_code == 200:
                form_data["responses"] = resp_data.json().get("responses", [])
        except Exception:
            pass

        class _MockResp:
            def raise_for_status(self): pass
            def json(self): return form_data
            
        return _MockResp()
    
    return _execute_with_token_fallback(tool_context, _call)


def read_google_doc(doc_id: str, tool_context: ToolContext) -> dict:
    """Read a Google Doc.
    
    Args:
        doc_id: The ID of the Google Doc.
        
    Returns:
        dict with success and document data, or an error.
    """
    err = authz.require(tool_context, authz.CAP_DOCUMENTS_MANAGE)
    if err:
        return {"success": False, "error": err}
    if httpx is None:
        return {"success": False, "error": "HTTP client unavailable on the server."}

    def _call(token: str):
        return httpx.get(f"{_DOCS_API}/{doc_id}", headers={"Authorization": f"Bearer {token}"}, timeout=20.0)
    
    res = _execute_with_token_fallback(tool_context, _call)
    if not res.get("success"):
        return res
    
    parts = []
    for el in res.get("data", {}).get("body", {}).get("content", []):
        for elem in (el.get("paragraph") or {}).get("elements", []):
            run = elem.get("textRun")
            if run and run.get("content"):
                parts.append(run["content"])
    text = "".join(parts).strip()
    return {"success": True, "text": text[:15000]}


def read_google_sheet(sheet_id: str, tool_context: ToolContext) -> dict:
    """Read a Google Sheet.
    
    Args:
        sheet_id: The ID of the Google Sheet.
        
    Returns:
        dict with success and spreadsheet data, or an error.
    """
    err = authz.require(tool_context, authz.CAP_DOCUMENTS_MANAGE)
    if err:
        return {"success": False, "error": err}
    if httpx is None:
        return {"success": False, "error": "HTTP client unavailable on the server."}

    def _call(token: str):
        return httpx.get(f"{_SHEETS_API}/{sheet_id}?includeGridData=true", headers={"Authorization": f"Bearer {token}"}, timeout=20.0)
    
    res = _execute_with_token_fallback(tool_context, _call)
    if not res.get("success"):
        return res
        
    parts = []
    for sheet in res.get("data", {}).get("sheets", []):
        for row in sheet.get("data", [{}])[0].get("rowData", []):
            row_vals = []
            for val in row.get("values", []):
                v = val.get("formattedValue")
                if v:
                    row_vals.append(v)
            if row_vals:
                parts.append(" | ".join(row_vals))
    text = "\n".join(parts).strip()
    return {"success": True, "text": text[:15000]}


def read_google_slides(presentation_id: str, tool_context: ToolContext) -> dict:
    """Read a Google Slides presentation.
    
    Args:
        presentation_id: The ID of the Google Slides presentation.
        
    Returns:
        dict with success and presentation data, or an error.
    """
    err = authz.require(tool_context, authz.CAP_DOCUMENTS_MANAGE)
    if err:
        return {"success": False, "error": err}
    if httpx is None:
        return {"success": False, "error": "HTTP client unavailable on the server."}

    def _call(token: str):
        return httpx.get(f"{_SLIDES_API}/{presentation_id}", headers={"Authorization": f"Bearer {token}"}, timeout=20.0)
    
    res = _execute_with_token_fallback(tool_context, _call)
    if not res.get("success"):
        return res
        
    parts = []
    for slide in res.get("data", {}).get("slides", []):
        for element in slide.get("pageElements", []):
            if "shape" in element and "text" in element["shape"]:
                for text_element in element["shape"]["text"].get("textElements", []):
                    if "textRun" in text_element and "content" in text_element["textRun"]:
                        parts.append(text_element["textRun"]["content"])
    text = "".join(parts).strip()
    return {"success": True, "text": text[:15000]}

