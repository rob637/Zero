"""Session history storage using SQLite."""

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional


def _resolve_db_path() -> Path:
    """Return the primary session DB path (outside the repo)."""
    telic_home = Path(os.environ.get("TELIC_HOME", "~/.telic")).expanduser()
    return telic_home / "db" / "sessions.db"


DB_PATH = _resolve_db_path()
LEGACY_DB_PATH = Path(__file__).parent / "sqlite" / "sessions.db"

# Persistent connection with thread-safety via a lock.
# SQLite in WAL mode supports concurrent reads while writes are serialised.
_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            messages TEXT NOT NULL DEFAULT '[]'
        )
    """)


def _migrate_legacy_sessions(conn: sqlite3.Connection) -> None:
    """Import sessions from the old repo-local DB path when present."""
    try:
        if LEGACY_DB_PATH.resolve() == DB_PATH.resolve() or not LEGACY_DB_PATH.exists():
            return
    except Exception:
        if not LEGACY_DB_PATH.exists():
            return

    try:
        legacy = sqlite3.connect(str(LEGACY_DB_PATH))
        legacy.row_factory = sqlite3.Row
        try:
            rows = legacy.execute(
                "SELECT id, title, created_at, updated_at, messages FROM sessions"
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        finally:
            legacy.close()

        if not rows:
            return

        conn.executemany(
            """
            INSERT INTO sessions (id, title, created_at, updated_at, messages)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = CASE
                    WHEN excluded.updated_at > sessions.updated_at THEN excluded.title
                    ELSE sessions.title
                END,
                updated_at = CASE
                    WHEN excluded.updated_at > sessions.updated_at THEN excluded.updated_at
                    ELSE sessions.updated_at
                END,
                messages = CASE
                    WHEN excluded.updated_at > sessions.updated_at THEN excluded.messages
                    ELSE sessions.messages
                END
            """,
            [(r["id"], r["title"], r["created_at"], r["updated_at"], r["messages"]) for r in rows],
        )
        conn.commit()
    except Exception:
        # Non-fatal: startup should continue even if migration fails.
        pass


def _get_conn() -> sqlite3.Connection:
    """Return the persistent connection, creating it on first use."""
    global _conn
    if _conn is not None:
        return _conn
    with _lock:
        if _conn is not None:
            return _conn
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _create_schema(_conn)
        _migrate_legacy_sessions(_conn)
        _conn.commit()
    return _conn


def new_session_id() -> str:
    return str(uuid.uuid4())


def save_session(session_id: str, title: str, messages: List[Dict]) -> Dict:
    """Save or update a session."""
    conn = _get_conn()
    now = datetime.utcnow().isoformat()

    with _lock:
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
    return {"id": session_id, "title": title, "created_at": created_at, "updated_at": now}


def list_sessions(limit: int = 50) -> List[Dict]:
    """List sessions, most recent first."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, title, created_at, updated_at FROM sessions ORDER BY updated_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_session(session_id: str) -> Optional[Dict]:
    """Get a session with its messages."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, title, created_at, updated_at, messages FROM sessions WHERE id = ?",
        (session_id,)
    ).fetchone()
    if row:
        result = dict(row)
        result["messages"] = json.loads(result["messages"])
        return result
    return None


def delete_session(session_id: str) -> bool:
    """Delete a session. Returns True if it existed."""
    conn = _get_conn()
    with _lock:
        cursor = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
    return cursor.rowcount > 0
