"""Lazy PostgreSQL (Cloud SQL) connection for document retrieval.

Used only by retrieval.py for the weighted full-text document search described
in FELLO_ADK_CAPABILITIES_AND_SECURITY.md. When DATABASE_URL is unset, callers
degrade gracefully — the dashboard demo never depends on Cloud SQL being up.

Every query that touches this connection MUST be scoped by org_id sourced from
the verified agent context (never from the user's message), matching the
Cloud SQL row-level isolation rule in CLAUDE.md §5.3.

Two connection paths, depending on where this code runs:
  - The backend VM (fello-gateway) connects straight through DATABASE_URL via
    its local Cloud SQL Auth Proxy (127.0.0.1) — see WHATSAPP_INTEGRATION.md §4.2.
  - This agent runs on Vertex AI Agent Engine, a serverless environment with no
    stable egress IP to add to Cloud SQL's authorized-networks allowlist, so a
    raw TCP connection to the public IP is unreliable. When INSTANCE_CONNECTION_NAME
    is set (only on Agent Engine — see deploy.py), we connect via the Cloud SQL
    Python Connector instead (pg8000 driver — the connector doesn't support
    psycopg2), which authenticates over IAM rather than IP allowlisting.
    user/password/db are still read out of DATABASE_URL so there's only one
    place secrets live. `query()` builds rows from cursor.description instead
    of psycopg2's RealDictCursor so it works identically for both drivers.
"""

from __future__ import annotations

import os
import threading
from urllib.parse import urlparse

try:
    import psycopg2
except Exception:  # pragma: no cover - optional dependency
    psycopg2 = None  # type: ignore

try:
    from google.cloud.sql.connector import Connector
except Exception:  # pragma: no cover - optional dependency
    Connector = None  # type: ignore

_lock = threading.Lock()
_conn = None
_connector = None

_INSTANCE_CONNECTION_NAME = os.environ.get("INSTANCE_CONNECTION_NAME")


def available() -> bool:
    return bool(os.environ.get("DATABASE_URL")) and psycopg2 is not None


def _connect():
    global _conn, _connector
    with _lock:
        if _conn is not None and not getattr(_conn, "closed", 1):
            return _conn

        if _INSTANCE_CONNECTION_NAME and Connector is not None:
            parsed = urlparse(os.environ["DATABASE_URL"])
            if _connector is None:
                _connector = Connector()
            _conn = _connector.connect(
                _INSTANCE_CONNECTION_NAME,
                "pg8000",
                user=parsed.username,
                password=parsed.password,
                db=(parsed.path or "/fello").lstrip("/"),
            )
        else:
            _conn = psycopg2.connect(os.environ["DATABASE_URL"])
        _conn.autocommit = True
        return _conn


def query(sql: str, params: tuple, org_id: str | None = None) -> list[dict]:
    """Run a parameterized read query and return a list of dict rows.

    ``org_id`` (the verified org from agent context) is set as the ``app.org_id``
    GUC on the connection so the RLS policies in db/migrations/003 scope every
    row to that org at the database layer — a second isolation layer on top of
    the explicit ``WHERE org_id = ...`` in each query. Without it, RLS matches
    no rows (fail closed).

    Raises RuntimeError if Postgres is not configured — callers should check
    :func:`available` first and return a graceful message to the user.
    """
    if not available():
        raise RuntimeError("Document index (Cloud SQL) is not configured.")
    conn = _connect()
    with _lock:
        cur = conn.cursor()
        try:
            # is_local=false: session-scoped (autocommit means there is no
            # transaction to scope to); overwritten on every call so the shared
            # connection never carries a stale org between tools.
            cur.execute("SELECT set_config('app.org_id', %s, false)", (org_id or "",))
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            cur.close()
