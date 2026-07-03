"""Thin client for the Baileys WhatsApp gateway running on the GCE VM.

The agent never talks to WhatsApp directly — it calls the gateway's internal
API (BACKEND/CLAUDE.md §7). When BAILEYS_API_URL is unset (local dev, demo
without a live number), calls degrade gracefully to a clear "not connected"
result instead of raising, so the dashboard demo keeps working.
"""

from __future__ import annotations

import os

try:  # httpx is optional at import time; only needed when the gateway is live
    import httpx
except Exception:  # pragma: no cover
    httpx = None  # type: ignore


def _base() -> str | None:
    return os.environ.get("BAILEYS_API_URL") or None


def configured() -> bool:
    return bool(_base()) and httpx is not None


def call(path: str, payload: dict, timeout: float = 15.0) -> dict:
    """POST to the gateway. Returns {"connected": False, ...} when not configured."""
    base = _base()
    if not base or httpx is None:
        return {
            "connected": False,
            "success": False,
            "error": "WhatsApp gateway not connected yet — this action will run once a number is linked.",
        }
    secret = os.environ.get("BAILEYS_API_SECRET", "")
    url = base.rstrip("/") + "/" + path.lstrip("/")
    try:
        resp = httpx.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {secret}"} if secret else {},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        data.setdefault("connected", True)
        data.setdefault("success", True)
        return data
    except Exception as e:  # network / gateway errors surface as a clean result
        return {"connected": True, "success": False, "error": f"Gateway error: {e}"}
