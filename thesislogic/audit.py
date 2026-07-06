"""Append-only audit trail.

Every AI-relevant action is recorded with a request id so a firm can answer,
for any output: what model produced it, from what evidence, whether the proof
gate passed it, and whether live output was downgraded to the deterministic
fallback. This is the accountability backbone required in regulated practice.
"""

from __future__ import annotations

import json
import sqlite3
import uuid


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def record(db: sqlite3.Connection, request_id: str, event_type: str, *,
           user_id: str = "", matter_id: str = "", detail: dict | None = None) -> None:
    db.execute(
        "INSERT INTO audit_events (request_id, user_id, matter_id, event_type, detail_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (request_id, user_id, matter_id, event_type, json.dumps(detail or {}, sort_keys=True)),
    )
    db.commit()


def query(db: sqlite3.Connection, *, matter_id: str = "", request_id: str = "",
          limit: int = 100) -> list[dict]:
    sql = "SELECT * FROM audit_events WHERE 1=1"
    params: list = []
    if matter_id:
        sql += " AND matter_id = ?"
        params.append(matter_id)
    if request_id:
        sql += " AND request_id = ?"
        params.append(request_id)
    sql += " ORDER BY event_id DESC LIMIT ?"
    params.append(max(1, min(limit, 1000)))
    rows = db.execute(sql, params).fetchall()
    return [
        {
            "event_id": r["event_id"],
            "request_id": r["request_id"],
            "created_at": r["created_at"],
            "user_id": r["user_id"],
            "matter_id": r["matter_id"],
            "event_type": r["event_type"],
            "detail": json.loads(r["detail_json"]),
        }
        for r in rows
    ]
