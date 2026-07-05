"""Lazy PostgreSQL (Cloud SQL) connection for document retrieval.

Used only by retrieval.py for the weighted full-text document search described
in FELLO_ADK_CAPABILITIES_AND_SECURITY.md. When DATABASE_URL is unset, callers
degrade gracefully — the dashboard demo never depends on Cloud SQL being up.

Every query that touches this connection MUST be scoped by org_id sourced from
the verified agent context (never from the user's message), matching the
Cloud SQL row-level isolation rule in CLAUDE.md §5.3.
"""

from __future__ import annotations

import os
import threading

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except Exception:  # pragma: no cover - optional dependency
    psycopg2 = None  # type: ignore
    RealDictCursor = None  # type: ignore

_lock = threading.Lock()
_conn = None


def available() -> bool:
    return bool(os.environ.get("DATABASE_URL")) and psycopg2 is not None


def _connect():
    global _conn
    with _lock:
        if _conn is not None and not getattr(_conn, "closed", 1):
            return _conn
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
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # is_local=false: session-scoped (autocommit means there is no
            # transaction to scope to); overwritten on every call so the shared
            # connection never carries a stale org between tools.
            cur.execute("SELECT set_config('app.org_id', %s, false)", (org_id or "",))
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
