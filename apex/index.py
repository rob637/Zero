"""
Local Data Index

A structured cache of all connected service data — calendar events, emails,
contacts, tasks, files — normalized into a universal DataObject and stored in
SQLite with full-text search.

This is NOT a knowledge graph (that's intelligence/semantic_memory.py).
This is a fast, queryable mirror of your live service data.

Why it matters:
  - "What's on my calendar today?" → 5ms SQLite query instead of 2s API call
  - "Find that email from John about the budget" → instant FTS5 search
  - "Show my open tasks" → local query, no network
  - Background sync keeps it fresh; stale data triggers live API fallback

Architecture:
  DataObject   — Universal row: one shape for events, emails, contacts, etc.
  SyncState    — Per-source sync tracking (tokens, timestamps, status)
  Index        — SQLite manager: schema, CRUD, search, sync orchestration
  Normalizers  — Connector-specific functions that map API data → DataObject
"""

import asyncio
import hashlib
import json
import sqlite3
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DataObject — the universal row
# ---------------------------------------------------------------------------

class ObjectKind(str, Enum):
    """Normalized type of a DataObject."""
    EVENT = "event"
    EMAIL = "email"
    CONTACT = "contact"
    TASK = "task"
    FILE = "file"
    MESSAGE = "message"       # Slack, Teams, Telegram
    NOTE = "note"             # OneNote, Notion pages
    DOCUMENT = "document"     # Docs, Sheets, Slides, etc.


@dataclass
class DataObject:
    """Universal representation of any service object.

    Every connector's data (CalendarEvent, Email, Contact, …) gets normalized
    into this shape so it can live in one table, one FTS index, and be queried
    with one API.
    """

    # Identity
    source: str            # Connector name: "google_calendar", "gmail", …
    source_id: str         # Original ID from the service
    kind: ObjectKind       # Normalized type

    # Content
    title: str             # Primary text: summary, subject, display name
    body: str = ""         # Secondary text: description, email body, notes

    # Temporal
    timestamp: Optional[datetime] = None      # Primary date: event start, email date, due date
    timestamp_end: Optional[datetime] = None  # Secondary date: event end

    # Relationships
    participants: List[str] = field(default_factory=list)  # Emails/names involved
    location: str = ""     # Physical or virtual location

    # Status
    status: str = ""       # confirmed/tentative/cancelled, read/unread, completed/pending
    labels: List[str] = field(default_factory=list)        # Tags, categories, labels
    url: str = ""          # Link back to original in the service

    # Raw data
    raw: Dict[str, Any] = field(default_factory=dict)      # Full original API response

    # Metadata (set by Index, not by normalizers)
    id: str = ""                                    # Composite key: {source}:{source_id}
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    synced_at: Optional[datetime] = None
    checksum: str = ""                              # Hash of raw for change detection

    def __post_init__(self):
        if not self.id:
            self.id = f"{self.source}:{self.source_id}"
        if isinstance(self.kind, str):
            self.kind = ObjectKind(self.kind)
        if not self.checksum and self.raw:
            self.checksum = _hash_raw(self.raw)


def _hash_raw(raw: Dict[str, Any]) -> str:
    """Deterministic hash of the raw dict for change detection."""
    canonical = json.dumps(raw, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# SyncState — per-source sync tracking
# ---------------------------------------------------------------------------

class SyncStatus(str, Enum):
    IDLE = "idle"
    SYNCING = "syncing"
    ERROR = "error"


@dataclass
class SyncState:
    """Tracks sync progress for each data source."""
    source: str                          # Connector name (primary key)
    last_sync: Optional[datetime] = None
    sync_token: str = ""                 # Google syncToken / Microsoft deltaLink
    status: SyncStatus = SyncStatus.IDLE
    error: str = ""
    item_count: int = 0
    sync_duration_ms: int = 0            # Last sync duration for monitoring


# ---------------------------------------------------------------------------
# Normalizers — convert connector data → DataObject
# ---------------------------------------------------------------------------

def normalize_calendar_event(event: Dict[str, Any], source: str = "google_calendar") -> DataObject:
    """Normalize a calendar event dict to DataObject."""
    start = event.get("start")
    end = event.get("end")
    if isinstance(start, str):
        try:
            start = datetime.fromisoformat(start)
        except (ValueError, TypeError):
            start = None
    if isinstance(end, str):
        try:
            end = datetime.fromisoformat(end)
        except (ValueError, TypeError):
            end = None

    attendees = []
    for a in event.get("attendees", []):
        if isinstance(a, dict):
            attendees.append(a.get("email") or a.get("displayName", ""))
        elif isinstance(a, str):
            attendees.append(a)

    return DataObject(
        source=source,
        source_id=event.get("id", ""),
        kind=ObjectKind.EVENT,
        title=event.get("summary", event.get("title", "")),
        body=event.get("description", ""),
        timestamp=start,
        timestamp_end=end,
        participants=attendees,
        location=event.get("location", ""),
        status=event.get("status", "confirmed"),
        labels=[event.get("calendar_name", "")] if event.get("calendar_name") else [],
        url=event.get("html_link", event.get("htmlLink", "")),
        raw=event,
    )


def normalize_email(msg: Dict[str, Any], source: str = "gmail") -> DataObject:
    """Normalize an email message dict to DataObject."""
    date = msg.get("date")
    if isinstance(date, str):
        try:
            date = datetime.fromisoformat(date)
        except (ValueError, TypeError):
            date = None

    participants = []
    if msg.get("sender"):
        participants.append(msg["sender"])
    for r in msg.get("to", []):
        if isinstance(r, str):
            participants.append(r)

    labels = msg.get("labels", [])
    status = "unread" if "UNREAD" in labels else "read"

    return DataObject(
        source=source,
        source_id=msg.get("id", ""),
        kind=ObjectKind.EMAIL,
        title=msg.get("subject", "(no subject)"),
        body=msg.get("snippet", msg.get("body", "")),
        timestamp=date,
        participants=participants,
        status=status,
        labels=labels,
        url=msg.get("html_link", ""),
        raw=msg,
    )


def normalize_contact(contact: Dict[str, Any], source: str = "google_contacts") -> DataObject:
    """Normalize a contact dict to DataObject."""
    participants = []
    if contact.get("email"):
        participants.append(contact["email"])
    for e in contact.get("other_emails", []):
        participants.append(e)

    body_parts = []
    if contact.get("company"):
        body_parts.append(contact["company"])
    if contact.get("job_title"):
        body_parts.append(contact["job_title"])
    if contact.get("phone"):
        body_parts.append(contact["phone"])

    return DataObject(
        source=source,
        source_id=contact.get("resource_name", contact.get("id", "")),
        kind=ObjectKind.CONTACT,
        title=contact.get("name", contact.get("display_name", "")),
        body=" | ".join(body_parts),
        participants=participants,
        raw=contact,
    )


def normalize_task(task: Dict[str, Any], source: str = "todoist") -> DataObject:
    """Normalize a task dict to DataObject."""
    due = task.get("due_date") or task.get("due")
    if isinstance(due, str):
        try:
            due = datetime.fromisoformat(due)
        except (ValueError, TypeError):
            due = None

    completed = task.get("is_completed") or task.get("completed") or task.get("status") == "completed"
    status = "completed" if completed else "pending"

    return DataObject(
        source=source,
        source_id=task.get("id", ""),
        kind=ObjectKind.TASK,
        title=task.get("title", task.get("content", "")),
        body=task.get("description", task.get("notes", "")),
        timestamp=due,
        status=status,
        labels=task.get("labels", []),
        url=task.get("url", ""),
        raw=task,
    )


def normalize_file(f: Dict[str, Any], source: str = "google_drive") -> DataObject:
    """Normalize a file/document dict to DataObject."""
    modified = f.get("modifiedTime") or f.get("modified_at")
    if isinstance(modified, str):
        try:
            modified = datetime.fromisoformat(modified)
        except (ValueError, TypeError):
            modified = None

    owners = []
    for o in f.get("owners", []):
        if isinstance(o, dict):
            owners.append(o.get("emailAddress", o.get("displayName", "")))
        elif isinstance(o, str):
            owners.append(o)

    return DataObject(
        source=source,
        source_id=f.get("id", ""),
        kind=ObjectKind.FILE,
        title=f.get("name", f.get("title", "")),
        body=f.get("description", ""),
        timestamp=modified,
        participants=owners,
        url=f.get("webViewLink", f.get("url", "")),
        raw=f,
    )


def normalize_message(msg: Dict[str, Any], source: str = "slack") -> DataObject:
    """Normalize a chat message dict to DataObject."""
    ts = msg.get("timestamp") or msg.get("ts")
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            # Slack uses epoch timestamps
            try:
                ts = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            except (ValueError, TypeError):
                ts = None

    participants = []
    if msg.get("user"):
        participants.append(msg["user"])
    if msg.get("sender"):
        participants.append(msg["sender"])

    return DataObject(
        source=source,
        source_id=msg.get("id", msg.get("ts", "")),
        kind=ObjectKind.MESSAGE,
        title=msg.get("channel", msg.get("channel_name", "")),
        body=msg.get("text", msg.get("content", "")),
        timestamp=ts,
        participants=participants,
        raw=msg,
    )


def normalize_notification(item: Dict[str, Any], source: str = "github") -> DataObject:
    """Normalize a notification/issue/PR dict to DataObject."""
    updated = item.get("updated_at") or item.get("timestamp")
    if isinstance(updated, str):
        try:
            updated = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            updated = None

    subject = item.get("subject", {})
    title = subject.get("title", "") if isinstance(subject, dict) else item.get("title", "")
    body = item.get("reason", item.get("body", ""))

    return DataObject(
        source=source,
        source_id=item.get("id", ""),
        kind=ObjectKind.NOTE,
        title=title,
        body=body,
        timestamp=updated,
        url=item.get("url", item.get("html_url", "")),
        raw=item,
    )


def normalize_page(page: Dict[str, Any], source: str = "notion") -> DataObject:
    """Normalize a Notion page dict to DataObject."""
    modified = page.get("last_edited_time") or page.get("modified")
    if isinstance(modified, str):
        try:
            modified = datetime.fromisoformat(modified.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            modified = None

    # Notion title is nested in properties
    title = ""
    props = page.get("properties", {})
    for prop in props.values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            title_arr = prop.get("title", [])
            title = "".join(t.get("plain_text", "") for t in title_arr if isinstance(t, dict))
            break
    if not title:
        title = page.get("title", page.get("name", ""))

    return DataObject(
        source=source,
        source_id=page.get("id", ""),
        kind=ObjectKind.DOCUMENT,
        title=title,
        body=page.get("description", ""),
        timestamp=modified,
        url=page.get("url", ""),
        raw=page,
    )


# Registry of normalizers by source prefix
NORMALIZERS: Dict[str, Callable] = {
    "google_calendar": normalize_calendar_event,
    "outlook_calendar": normalize_calendar_event,
    "gmail": normalize_email,
    "outlook": normalize_email,
    "google_contacts": normalize_contact,
    "microsoft_contacts": normalize_contact,
    "todoist": normalize_task,
    "microsoft_todo": normalize_task,
    "jira": normalize_task,
    "linear": normalize_task,
    "trello": normalize_task,
    "google_drive": normalize_file,
    "onedrive": normalize_file,
    "dropbox": normalize_file,
    "slack": normalize_message,
    "discord": normalize_message,
    "teams": normalize_message,
    "github": normalize_notification,
    "notion": normalize_page,
    "zoom": normalize_calendar_event,  # meetings look like events
    "hubspot": normalize_contact,       # contacts share shape
}


# ---------------------------------------------------------------------------
# Index — SQLite manager
# ---------------------------------------------------------------------------

_SCHEMA = """
-- Core data table: one row per service object
CREATE TABLE IF NOT EXISTS data_objects (
    id             TEXT PRIMARY KEY,        -- {source}:{source_id}
    source         TEXT NOT NULL,           -- connector name
    source_id      TEXT NOT NULL,           -- original service ID
    kind           TEXT NOT NULL,           -- event, email, contact, task, file, …
    title          TEXT NOT NULL DEFAULT '',
    body           TEXT NOT NULL DEFAULT '',
    timestamp      TEXT,                    -- ISO 8601
    timestamp_end  TEXT,                    -- ISO 8601
    participants   TEXT NOT NULL DEFAULT '[]',  -- JSON array
    location       TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT '',
    labels         TEXT NOT NULL DEFAULT '[]',  -- JSON array
    url            TEXT NOT NULL DEFAULT '',
    raw            TEXT NOT NULL DEFAULT '{}',  -- Full JSON
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    synced_at      TEXT NOT NULL,
    checksum       TEXT NOT NULL DEFAULT ''
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_kind_ts
    ON data_objects(kind, timestamp);
CREATE INDEX IF NOT EXISTS idx_source_sid
    ON data_objects(source, source_id);
CREATE INDEX IF NOT EXISTS idx_kind_status
    ON data_objects(kind, status);
CREATE INDEX IF NOT EXISTS idx_source_synced
    ON data_objects(source, synced_at);

-- Full-text search across title + body
CREATE VIRTUAL TABLE IF NOT EXISTS data_objects_fts
    USING fts5(title, body, content='data_objects', content_rowid='rowid');

-- Keep FTS in sync via triggers
CREATE TRIGGER IF NOT EXISTS data_objects_ai AFTER INSERT ON data_objects BEGIN
    INSERT INTO data_objects_fts(rowid, title, body)
    VALUES (new.rowid, new.title, new.body);
END;
CREATE TRIGGER IF NOT EXISTS data_objects_ad AFTER DELETE ON data_objects BEGIN
    INSERT INTO data_objects_fts(data_objects_fts, rowid, title, body)
    VALUES ('delete', old.rowid, old.title, old.body);
END;
CREATE TRIGGER IF NOT EXISTS data_objects_au AFTER UPDATE ON data_objects BEGIN
    INSERT INTO data_objects_fts(data_objects_fts, rowid, title, body)
    VALUES ('delete', old.rowid, old.title, old.body);
    INSERT INTO data_objects_fts(rowid, title, body)
    VALUES (new.rowid, new.title, new.body);
END;

-- Sync state tracking
CREATE TABLE IF NOT EXISTS sync_state (
    source          TEXT PRIMARY KEY,
    last_sync       TEXT,               -- ISO 8601
    sync_token      TEXT DEFAULT '',     -- Service-specific continuation token
    status          TEXT DEFAULT 'idle',
    error           TEXT DEFAULT '',
    item_count      INTEGER DEFAULT 0,
    sync_duration_ms INTEGER DEFAULT 0
);
"""


class Index:
    """Local data index backed by SQLite + FTS5.

    Usage:
        index = Index()              # opens/creates DB at apex/sqlite/index.db
        index.upsert(data_object)    # insert or update a single object
        index.upsert_batch(objects)  # bulk upsert (fast, single transaction)
        results = index.query(kind="event", after=..., before=...)
        results = index.search("budget meeting john")
        state = index.get_sync_state("gmail")
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = str(Path(__file__).parent / "sqlite" / "index.db")
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")    # Concurrent reads
        self._conn.execute("PRAGMA synchronous=NORMAL")  # Safe + fast
        self._conn.execute("PRAGMA cache_size=-8000")    # 8MB cache
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        logger.info(f"Index opened: {db_path}")

    def close(self):
        self._conn.close()

    # -------------------------------------------------------------------
    # Write operations
    # -------------------------------------------------------------------

    def upsert(self, obj: DataObject) -> None:
        """Insert or update a single DataObject."""
        now = datetime.now(timezone.utc).isoformat()
        if not obj.synced_at:
            obj.synced_at = datetime.now(timezone.utc)
        if not obj.checksum and obj.raw:
            obj.checksum = _hash_raw(obj.raw)

        self._conn.execute("""
            INSERT INTO data_objects
                (id, source, source_id, kind, title, body,
                 timestamp, timestamp_end, participants, location,
                 status, labels, url, raw, created_at, updated_at, synced_at, checksum)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title, body=excluded.body,
                timestamp=excluded.timestamp, timestamp_end=excluded.timestamp_end,
                participants=excluded.participants, location=excluded.location,
                status=excluded.status, labels=excluded.labels,
                url=excluded.url, raw=excluded.raw,
                updated_at=excluded.updated_at, synced_at=excluded.synced_at,
                checksum=excluded.checksum
        """, self._obj_to_row(obj, now))
        self._conn.commit()

    def upsert_batch(self, objects: List[DataObject]) -> int:
        """Bulk upsert. Returns count of objects written."""
        if not objects:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for obj in objects:
            if not obj.synced_at:
                obj.synced_at = datetime.now(timezone.utc)
            if not obj.checksum and obj.raw:
                obj.checksum = _hash_raw(obj.raw)
            rows.append(self._obj_to_row(obj, now))

        self._conn.executemany("""
            INSERT INTO data_objects
                (id, source, source_id, kind, title, body,
                 timestamp, timestamp_end, participants, location,
                 status, labels, url, raw, created_at, updated_at, synced_at, checksum)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title, body=excluded.body,
                timestamp=excluded.timestamp, timestamp_end=excluded.timestamp_end,
                participants=excluded.participants, location=excluded.location,
                status=excluded.status, labels=excluded.labels,
                url=excluded.url, raw=excluded.raw,
                updated_at=excluded.updated_at, synced_at=excluded.synced_at,
                checksum=excluded.checksum
        """, rows)
        self._conn.commit()
        return len(rows)

    def delete_by_source(self, source: str) -> int:
        """Remove all objects from a given source. Returns count deleted."""
        cursor = self._conn.execute(
            "DELETE FROM data_objects WHERE source = ?", (source,)
        )
        self._conn.commit()
        return cursor.rowcount

    def delete_stale(self, source: str, before: datetime) -> int:
        """Remove objects from a source that haven't been synced since `before`."""
        cursor = self._conn.execute(
            "DELETE FROM data_objects WHERE source = ? AND synced_at < ?",
            (source, before.isoformat())
        )
        self._conn.commit()
        return cursor.rowcount

    # -------------------------------------------------------------------
    # Read operations
    # -------------------------------------------------------------------

    def query(
        self,
        kind: Optional[str] = None,
        source: Optional[str] = None,
        after: Optional[datetime] = None,
        before: Optional[datetime] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[DataObject]:
        """Structured query against the index.

        Examples:
            index.query(kind="event", after=today_start, before=today_end)
            index.query(kind="task", status="pending")
            index.query(source="gmail", limit=20)
        """
        clauses = []
        params: List[Any] = []

        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if source:
            clauses.append("source = ?")
            params.append(source)
        if after:
            clauses.append("timestamp >= ?")
            params.append(after.isoformat())
        if before:
            clauses.append("timestamp < ?")
            params.append(before.isoformat())
        if status:
            clauses.append("status = ?")
            params.append(status)

        where = " AND ".join(clauses) if clauses else "1=1"
        params.append(limit)

        rows = self._conn.execute(
            f"SELECT * FROM data_objects WHERE {where} ORDER BY timestamp DESC LIMIT ?",
            params
        ).fetchall()
        return [self._row_to_obj(r) for r in rows]

    def search(self, text: str, kind: Optional[str] = None, limit: int = 50) -> List[DataObject]:
        """Full-text search across title and body.

        Uses SQLite FTS5 — supports AND, OR, NOT, prefix*, "exact phrases".
        """
        if not text.strip():
            return []

        if kind:
            rows = self._conn.execute("""
                SELECT d.* FROM data_objects d
                JOIN data_objects_fts f ON d.rowid = f.rowid
                WHERE data_objects_fts MATCH ? AND d.kind = ?
                ORDER BY rank
                LIMIT ?
            """, (text, kind, limit)).fetchall()
        else:
            rows = self._conn.execute("""
                SELECT d.* FROM data_objects d
                JOIN data_objects_fts f ON d.rowid = f.rowid
                WHERE data_objects_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (text, limit)).fetchall()
        return [self._row_to_obj(r) for r in rows]

    def count(self, kind: Optional[str] = None, source: Optional[str] = None) -> int:
        """Count objects, optionally filtered by kind or source."""
        clauses = []
        params: List[Any] = []
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if source:
            clauses.append("source = ?")
            params.append(source)
        where = " AND ".join(clauses) if clauses else "1=1"
        row = self._conn.execute(
            f"SELECT COUNT(*) FROM data_objects WHERE {where}", params
        ).fetchone()
        return row[0]

    def stats(self) -> Dict[str, Any]:
        """Return index statistics: counts by kind and source."""
        kinds = self._conn.execute(
            "SELECT kind, COUNT(*) as cnt FROM data_objects GROUP BY kind"
        ).fetchall()
        sources = self._conn.execute(
            "SELECT source, COUNT(*) as cnt FROM data_objects GROUP BY source"
        ).fetchall()
        total = self._conn.execute(
            "SELECT COUNT(*) FROM data_objects"
        ).fetchone()[0]
        return {
            "total": total,
            "by_kind": {r["kind"]: r["cnt"] for r in kinds},
            "by_source": {r["source"]: r["cnt"] for r in sources},
        }

    def health(self) -> Dict[str, Any]:
        """Comprehensive health check: DB integrity, size, staleness, errors."""
        result = {
            "status": "healthy",
            "checks": {},
        }

        # 1) DB integrity
        try:
            integrity = self._conn.execute("PRAGMA integrity_check").fetchone()[0]
            result["checks"]["integrity"] = integrity
            if integrity != "ok":
                result["status"] = "degraded"
        except Exception as e:
            result["checks"]["integrity"] = str(e)
            result["status"] = "unhealthy"

        # 2) DB file size
        try:
            db_size = Path(self._db_path).stat().st_size
            result["checks"]["db_size_mb"] = round(db_size / (1024 * 1024), 2)
        except Exception:
            result["checks"]["db_size_mb"] = None

        # 3) Total objects
        stats = self.stats()
        result["checks"]["total_objects"] = stats["total"]
        result["checks"]["by_kind"] = stats["by_kind"]
        result["checks"]["by_source"] = stats["by_source"]

        # 4) Sync state health
        sync_states = self.all_sync_states()
        errors = [s for s in sync_states if s.status == SyncStatus.ERROR]
        stale = []
        now = datetime.now(timezone.utc)
        for s in sync_states:
            if s.last_sync and (now - s.last_sync) > timedelta(hours=1):
                stale.append(s.source)

        result["checks"]["sync_sources"] = len(sync_states)
        result["checks"]["sync_errors"] = [{"source": s.source, "error": s.error} for s in errors]
        result["checks"]["stale_sources"] = stale

        if errors:
            result["status"] = "degraded"

        # 5) FTS health
        try:
            fts_count = self._conn.execute(
                "SELECT COUNT(*) FROM data_objects_fts"
            ).fetchone()[0]
            result["checks"]["fts_indexed"] = fts_count
            if fts_count < stats["total"] * 0.9:  # >10% missing from FTS
                result["status"] = "degraded"
                result["checks"]["fts_warning"] = "FTS index may be out of sync"
        except Exception as e:
            result["checks"]["fts_error"] = str(e)
            result["status"] = "degraded"

        return result

    def vacuum(self) -> Dict[str, Any]:
        """Run SQLite VACUUM to reclaim space and optimize."""
        try:
            size_before = Path(self._db_path).stat().st_size
            self._conn.execute("VACUUM")
            size_after = Path(self._db_path).stat().st_size
            saved = size_before - size_after
            return {
                "status": "ok",
                "size_before_mb": round(size_before / (1024 * 1024), 2),
                "size_after_mb": round(size_after / (1024 * 1024), 2),
                "saved_mb": round(saved / (1024 * 1024), 2),
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def rebuild_fts(self) -> Dict[str, Any]:
        """Rebuild the FTS5 index from scratch."""
        try:
            self._conn.execute("INSERT INTO data_objects_fts(data_objects_fts) VALUES('rebuild')")
            self._conn.commit()
            count = self._conn.execute("SELECT COUNT(*) FROM data_objects_fts").fetchone()[0]
            return {"status": "ok", "indexed": count}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # -------------------------------------------------------------------
    # Sync state management
    # -------------------------------------------------------------------

    def get_sync_state(self, source: str) -> Optional[SyncState]:
        """Get sync state for a source."""
        row = self._conn.execute(
            "SELECT * FROM sync_state WHERE source = ?", (source,)
        ).fetchone()
        if not row:
            return None
        return SyncState(
            source=row["source"],
            last_sync=datetime.fromisoformat(row["last_sync"]) if row["last_sync"] else None,
            sync_token=row["sync_token"] or "",
            status=SyncStatus(row["status"]),
            error=row["error"] or "",
            item_count=row["item_count"],
            sync_duration_ms=row["sync_duration_ms"],
        )

    def set_sync_state(self, state: SyncState) -> None:
        """Create or update sync state."""
        self._conn.execute("""
            INSERT INTO sync_state (source, last_sync, sync_token, status, error, item_count, sync_duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source) DO UPDATE SET
                last_sync=excluded.last_sync, sync_token=excluded.sync_token,
                status=excluded.status, error=excluded.error,
                item_count=excluded.item_count, sync_duration_ms=excluded.sync_duration_ms
        """, (
            state.source,
            state.last_sync.isoformat() if state.last_sync else None,
            state.sync_token,
            state.status.value,
            state.error,
            state.item_count,
            state.sync_duration_ms,
        ))
        self._conn.commit()

    def is_stale(self, source: str, max_age: timedelta = timedelta(minutes=5)) -> bool:
        """Check if a source needs re-syncing."""
        state = self.get_sync_state(source)
        if not state or not state.last_sync:
            return True  # Never synced
        age = datetime.now(timezone.utc) - state.last_sync
        return age > max_age

    def all_sync_states(self) -> List[SyncState]:
        """Get sync state for all sources."""
        rows = self._conn.execute("SELECT * FROM sync_state").fetchall()
        return [
            SyncState(
                source=r["source"],
                last_sync=datetime.fromisoformat(r["last_sync"]) if r["last_sync"] else None,
                sync_token=r["sync_token"] or "",
                status=SyncStatus(r["status"]),
                error=r["error"] or "",
                item_count=r["item_count"],
                sync_duration_ms=r["sync_duration_ms"],
            )
            for r in rows
        ]

    # -------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------

    def _obj_to_row(self, obj: DataObject, now: str) -> tuple:
        """Convert DataObject to a tuple for SQL INSERT."""
        return (
            obj.id,
            obj.source,
            obj.source_id,
            obj.kind.value if isinstance(obj.kind, ObjectKind) else obj.kind,
            obj.title,
            obj.body or "",
            obj.timestamp.isoformat() if obj.timestamp else None,
            obj.timestamp_end.isoformat() if obj.timestamp_end else None,
            json.dumps(obj.participants),
            obj.location,
            obj.status,
            json.dumps(obj.labels),
            obj.url,
            json.dumps(obj.raw, default=str),
            obj.created_at.isoformat() if obj.created_at else now,
            now,  # updated_at — always now
            obj.synced_at.isoformat() if obj.synced_at else now,
            obj.checksum,
        )

    def _row_to_obj(self, row: sqlite3.Row) -> DataObject:
        """Convert a database row back to DataObject."""
        return DataObject(
            id=row["id"],
            source=row["source"],
            source_id=row["source_id"],
            kind=ObjectKind(row["kind"]),
            title=row["title"],
            body=row["body"],
            timestamp=datetime.fromisoformat(row["timestamp"]) if row["timestamp"] else None,
            timestamp_end=datetime.fromisoformat(row["timestamp_end"]) if row["timestamp_end"] else None,
            participants=json.loads(row["participants"]),
            location=row["location"],
            status=row["status"],
            labels=json.loads(row["labels"]),
            url=row["url"],
            raw=json.loads(row["raw"]),
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
            synced_at=datetime.fromisoformat(row["synced_at"]) if row["synced_at"] else None,
            checksum=row["checksum"],
        )
