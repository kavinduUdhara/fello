"""Google Workspace skills — act in the org's connected Google account.

Currently: create a Google Form. Uses the org's stored OAuth grant (scoped by
the verified org_id from context), so the agent creates the form in the exact
Google account the org connected in Settings.
"""

from __future__ import annotations

from google.adk.tools import ToolContext

import authz
from context import identity
from ._google import get_access_token

try:
    import httpx
except Exception:  # pragma: no cover
    httpx = None  # type: ignore

_FORMS_API = "https://forms.googleapis.com/v1/forms"


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
        detail = ""
        try:
            detail = e.response.text[:300]  # type: ignore[attr-defined]
        except Exception:
            detail = str(e)
        return {"success": False, "error": f"Google Forms API error: {detail}"}
