"""Session history storage using SQLite."""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

DB_PATH = Path(__file__).parent / "sqlite" / "sessions.db"


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            messages TEXT NOT NULL DEFAULT '[]'
        )
    """)
    conn.commit()
    return conn


def new_session_id() -> str:
    return str(uuid.uuid4())


def save_session(session_id: str, title: str, messages: List[Dict]) -> Dict:
    """Save or update a session."""
    conn = _get_conn()
    now = datetime.utcnow().isoformat()

    # Check if session exists to preserve created_at
    existing = conn.execute(
        "SELECT created_at FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    created_at = existing["created_at"] if existing else now

    conn.execute("""
        INSERT INTO sessions (id, title, created_at, updated_at, messages)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title = excluded.title,
            updated_at = excluded.updated_at,
            messages = excluded.messages
    """, (session_id, title, created_at, now, json.dumps(messages)))
    conn.commit()
    conn.close()
    return {"id": session_id, "title": title, "created_at": created_at, "updated_at": now}


def list_sessions(limit: int = 50) -> List[Dict]:
    """List sessions, most recent first."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, title, created_at, updated_at FROM sessions ORDER BY updated_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_session(session_id: str) -> Optional[Dict]:
    """Get a session with its messages."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, title, created_at, updated_at, messages FROM sessions WHERE id = ?",
        (session_id,)
    ).fetchone()
    conn.close()
    if row:
        result = dict(row)
        result["messages"] = json.loads(result["messages"])
        return result
    return None


def delete_session(session_id: str) -> bool:
    """Delete a session. Returns True if it existed."""
    conn = _get_conn()
    cursor = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()
    return cursor.rowcount > 0
