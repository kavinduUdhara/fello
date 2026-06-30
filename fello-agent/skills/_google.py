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

    # Use the stored access token if it's still valid.
    access = integ.get("accessToken")
    if access and not _expired(integ.get("expiresAt")):
        return access, None

    refresh = integ.get("refreshToken")
    if not refresh:
        if access:
            return access, None
        return None, "The connected Google account needs to be reconnected in Settings."

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
        return None, f"Couldn't refresh Google access: {e}"


def has_scope(org_id: str, scope_substring: str) -> bool:
    integ = get_integration(org_id) or {}
    scopes = integ.get("scopes") or []
    joined = " ".join(scopes) if isinstance(scopes, list) else str(scopes)
    return scope_substring in joined
