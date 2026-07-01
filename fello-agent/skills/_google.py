"""Helper to use an org's connected Google account from the agent.

The web app stores each org's Google OAuth grant in Firestore at
`google_integrations/{orgId}` (accessToken, refreshToken, expiresAt, scopes),
written when an admin connects Google in Settings. The agent reads that grant —
scoped to the verified org_id — and exchanges the refresh token for a fresh
access token to call Google APIs (Forms, Docs, etc.) as that org.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

try:
    import httpx
except Exception:  # pragma: no cover
    httpx = None  # type: ignore

from ._firestore import db

_TOKEN_URL = "https://oauth2.googleapis.com/token"


def get_integration(org_id: str) -> dict | None:
    doc = db().collection("google_integrations").document(org_id).get()
    return doc.to_dict() if doc.exists else None


def _expired(expires_at) -> bool:
    if not expires_at:
        return True
    try:
        if isinstance(expires_at, (int, float)):
            return time.time() >= float(expires_at) - 60
        dt = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        return datetime.now(timezone.utc) >= dt
    except Exception:
        return True


def _exchange_refresh_token(integ: dict, label: str) -> tuple[str | None, str | None]:
    """Exchange the refresh_token in ``integ`` for a fresh access_token.

    Returns ``(access_token, error)``.  ``label`` is used only in error
    messages so the caller can distinguish org-level vs. per-project grants.
    """
    access = integ.get("accessToken")
    if access and not _expired(integ.get("expiresAt")):
        return access, None

    refresh = integ.get("refreshToken")
    if not refresh:
        if access:
            return access, None
        return None, (
            f"The connected Google account ({label}) needs to be reconnected in Settings."
        )

    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None, "Google OAuth client is not configured on the server."

    try:
        resp = httpx.post(
            _TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json()["access_token"], None
    except Exception as e:
        return None, f"Couldn't refresh Google access ({label}): {e}"


def get_access_token(org_id: str) -> tuple[str | None, str | None]:
    """Return (access_token, error). Refreshes via the org's refresh token."""
    if httpx is None:
        return None, "HTTP client unavailable on the server."

    integ = get_integration(org_id)
    if not integ or not integ.get("connected"):
        return None, (
            "No Google account is connected for this organization yet. "
            "An admin can connect one in Settings."
        )

    return _exchange_refresh_token(integ, "org")


def get_project_access_token(
    project_id: str, org_id: str
) -> tuple[str | None, str | None]:
    """Return (access_token, error) for the Google account backing this project.

    Reads ``projects/{project_id}``.  If its ``driveGrantRef`` field is ``"org"``
    or unset, delegates to :func:`get_access_token` (the org's shared grant).
    Otherwise reads ``project_google_integrations/{project_id}`` — a dedicated
    per-project OAuth grant with the same shape as ``google_integrations/{orgId}``
    (connected, accessToken, refreshToken, expiresAt, scopes) — and runs the
    identical refresh-token exchange logic.
    """
    if httpx is None:
        return None, "HTTP client unavailable on the server."

    proj_doc = db().collection("projects").document(project_id).get()
    if not proj_doc.exists:
        return None, f"Project '{project_id}' not found."

    drive_grant_ref = (proj_doc.to_dict() or {}).get("driveGrantRef", "org")
    if not drive_grant_ref or drive_grant_ref == "org":
        return get_access_token(org_id)

    # Per-project grant path.
    integ_doc = db().collection("project_google_integrations").document(project_id).get()
    if not integ_doc.exists or not (integ_doc.to_dict() or {}).get("connected"):
        # No dedicated grant — fall back to the org-level grant.
        return get_access_token(org_id)

    return _exchange_refresh_token(integ_doc.to_dict(), f"project:{project_id}")


def get_project_drive_folder(project_id: str) -> str | None:
    """Return ``projects/{project_id}.driveRootFolderId``, or None if not set."""
    doc = db().collection("projects").document(project_id).get()
    if not doc.exists:
        return None
    return (doc.to_dict() or {}).get("driveRootFolderId")


def has_scope(org_id: str, scope_substring: str) -> bool:
    integ = get_integration(org_id) or {}
    scopes = integ.get("scopes") or []
    joined = " ".join(scopes) if isinstance(scopes, list) else str(scopes)
    return scope_substring in joined
