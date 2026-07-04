"""Thin client for fello-backend's agent-facing WhatsApp relay.

The gateway VM only exposes its Baileys HTTP API on localhost — nothing
outside the VM can reach it (CLAUDE.md §7). The agent, running remotely on
Vertex AI Agent Engine, can't call the gateway directly the way the Node
backend does; it goes through the backend's own externally-reachable API
instead, at the /agent/whatsapp/* routes (see
fello-backend/backend/src/agent-whatsapp-routes.js), gated by
AGENT_BACKEND_SECRET rather than BAILEYS_API_SECRET (a separate trust
boundary from both that and the browser's Firebase ID tokens).
"""

from __future__ import annotations

import os

try:
    import httpx
except Exception:  # pragma: no cover
    httpx = None  # type: ignore


def _base() -> str | None:
    return os.environ.get("BACKEND_API_URL") or None


def call(path: str, payload: dict, timeout: float = 15.0) -> dict:
    """POST to the backend's agent-facing relay. Degrades gracefully when unset."""
    base = _base()
    secret = os.environ.get("AGENT_BACKEND_SECRET", "")
    if not base or not secret or httpx is None:
        return {
            "success": False,
            "error": "WhatsApp backend isn't configured for the agent yet — this action will run once it is.",
        }
    url = base.rstrip("/") + "/agent/" + path.lstrip("/")
    try:
        resp = httpx.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {secret}"},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"success": False, "error": f"Backend error: {e}"}
