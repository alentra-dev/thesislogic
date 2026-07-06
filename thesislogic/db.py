"""SQLite storage layer.

Two databases:
  - app.sqlite3: users, sessions, matters, documents, saved results, style
    profiles, audit events.
  - <pack>/authorities.sqlite3: per-jurisdiction authority index (built by
    thesislogic.packs).
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

_lock = threading.Lock()
_connections: dict[str, sqlite3.Connection] = {}

APP_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'attorney',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    matter_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS matters (
    matter_id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    practice_area TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS matter_members (
    matter_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    added_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (matter_id, user_id)
);

CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    extraction_path TEXT NOT NULL,
    status TEXT NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    facts_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_documents_matter ON documents (matter_id);

CREATE TABLE IF NOT EXISTS results (
    result_id TEXT PRIMARY KEY,
    matter_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    workflow TEXT NOT NULL,
    question TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_results_matter ON results (matter_id);

CREATE TABLE IF NOT EXISTS style_profiles (
    profile_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'private',      -- private | firm
    status TEXT NOT NULL DEFAULT 'draft',       -- draft | published | archived
    directives_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    user_id TEXT NOT NULL DEFAULT '',
    matter_id TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_audit_matter ON audit_events (matter_id);
CREATE INDEX IF NOT EXISTS idx_audit_request ON audit_events (request_id);
"""


def connect(path: Path) -> sqlite3.Connection:
    """Return a cached, thread-safe connection for the given database path."""
    key = str(path)
    with _lock:
        conn = _connections.get(key)
        if conn is None:
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(key, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=10000")
            _connections[key] = conn
        return conn


def app_db(data_dir: Path) -> sqlite3.Connection:
    conn = connect(data_dir / "app.sqlite3")
    conn.executescript(APP_SCHEMA)
    return conn


def close_all() -> None:
    with _lock:
        for conn in _connections.values():
            conn.close()
        _connections.clear()
