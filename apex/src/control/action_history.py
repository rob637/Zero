"""
ActionHistoryDB - Complete audit trail of all actions taken by Telic.

Every action - approved, rejected, auto-executed, undone - is recorded here.
This provides:
1. Full audit trail for compliance
2. Input for undo/rollback operations
3. Learning data for trust level adjustments
4. User review: "What has Apex done this week?"

Schema:
- action_id: Unique identifier
- action_type: send_email, create_file, delete_file, etc.
- status: pending, approved, rejected, completed, failed, undone
- payload: JSON of action parameters
- result: JSON of action result (if completed)
- checkpoint: Serialized state for undo (if applicable)
- timestamps: created, decided, completed
- user context: who triggered, who approved
"""

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging
import hashlib

logger = logging.getLogger(__name__)


class ActionStatus(Enum):
    """Status of an action in the history."""
    PENDING = "pending"           # Awaiting user decision
    APPROVED = "approved"         # User approved, executing
    AUTO_APPROVED = "auto_approved"  # Auto-approved by trust level
    REJECTED = "rejected"         # User rejected
    COMPLETED = "completed"       # Successfully executed
    FAILED = "failed"             # Execution failed
    UNDONE = "undone"             # Action was rolled back
    EXPIRED = "expired"           # Pending action timed out


class ActionCategory(Enum):
    """Categories for grouping actions."""
    EMAIL = "email"
    CALENDAR = "calendar"
    FILE = "file"
    DOCUMENT = "document"
    CONTACT = "contact"
    TASK = "task"
    DEVTOOLS = "devtools"
    SYSTEM = "system"
    OTHER = "other"


@dataclass
class ActionRecord:
    """A single action in the history."""
    id: str
    action_type: str              # e.g., "send_email", "delete_file"
    category: ActionCategory
    status: ActionStatus
    
    # Action details
    payload: Dict[str, Any]       # Input parameters
    preview: Dict[str, Any]       # What was shown to user
    result: Optional[Dict[str, Any]] = None  # Output/result
    error: Optional[str] = None   # Error message if failed
    
    # Undo support
    checkpoint_id: Optional[str] = None  # Reference to undo checkpoint
    is_undoable: bool = False
    undo_deadline: Optional[datetime] = None
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    decided_at: Optional[datetime] = None  # When approved/rejected
    completed_at: Optional[datetime] = None
    
    # User context
    triggered_by: str = "user"    # user, proactive, scheduled
    decided_by: Optional[str] = None  # user, auto, system
    session_id: Optional[str] = None
    
    # Relations
    parent_action_id: Optional[str] = None  # For multi-step workflows
    request_text: Optional[str] = None  # Original user request
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "action_type": self.action_type,
            "category": self.category.value,
            "status": self.status.value,
            "payload": self.payload,
            "preview": self.preview,
            "result": self.result,
            "error": self.error,
            "checkpoint_id": self.checkpoint_id,
            "is_undoable": self.is_undoable,
            "undo_deadline": self.undo_deadline.isoformat() if self.undo_deadline else None,
            "created_at": self.created_at.isoformat(),
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "triggered_by": self.triggered_by,
            "decided_by": self.decided_by,
            "session_id": self.session_id,
            "parent_action_id": self.parent_action_id,
            "request_text": self.request_text,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "ActionRecord":
        return cls(
            id=data["id"],
            action_type=data["action_type"],
            category=ActionCategory(data["category"]),
            status=ActionStatus(data["status"]),
            payload=data["payload"],
            preview=data["preview"],
            result=data.get("result"),
            error=data.get("error"),
            checkpoint_id=data.get("checkpoint_id"),
            is_undoable=data.get("is_undoable", False),
            undo_deadline=datetime.fromisoformat(data["undo_deadline"]) if data.get("undo_deadline") else None,
            created_at=datetime.fromisoformat(data["created_at"]),
            decided_at=datetime.fromisoformat(data["decided_at"]) if data.get("decided_at") else None,
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            triggered_by=data.get("triggered_by", "user"),
            decided_by=data.get("decided_by"),
            session_id=data.get("session_id"),
            parent_action_id=data.get("parent_action_id"),
            request_text=data.get("request_text"),
        )


# Map action types to categories
ACTION_CATEGORIES = {
    "send_email": ActionCategory.EMAIL,
    "draft_email": ActionCategory.EMAIL,
    "search_email": ActionCategory.EMAIL,
    "delete_email": ActionCategory.EMAIL,
    
    "create_event": ActionCategory.CALENDAR,
    "update_event": ActionCategory.CALENDAR,
    "delete_event": ActionCategory.CALENDAR,
    "find_free_time": ActionCategory.CALENDAR,
    
    "read_file": ActionCategory.FILE,
    "write_file": ActionCategory.FILE,
    "delete_file": ActionCategory.FILE,
    "move_file": ActionCategory.FILE,
    "copy_file": ActionCategory.FILE,
    "search_files": ActionCategory.FILE,
    
    "create_document": ActionCategory.DOCUMENT,
    "parse_document": ActionCategory.DOCUMENT,
    
    "search_contacts": ActionCategory.CONTACT,
    "create_contact": ActionCategory.CONTACT,
    
    "create_task": ActionCategory.TASK,
    "complete_task": ActionCategory.TASK,
    "update_task": ActionCategory.TASK,
    
    "create_issue": ActionCategory.DEVTOOLS,
    "update_issue": ActionCategory.DEVTOOLS,
    "create_pr": ActionCategory.DEVTOOLS,
    "send_slack": ActionCategory.DEVTOOLS,
}


class ActionHistoryDB:
    """
    Persistent storage for all action history.
    
    Provides full audit trail + undo support + compliance reporting.
    """
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize action history database.
        
        Args:
            db_path: Path to SQLite database. Defaults to ~/.apex/action_history.db
        """
        if db_path is None:
            apex_dir = Path.home() / ".apex"
            apex_dir.mkdir(exist_ok=True)
            db_path = str(apex_dir / "action_history.db")
        
        self._db_path = db_path
        self._counter = 0
        self._init_db()
        
        logger.info(f"ActionHistoryDB initialized: {db_path}")
    
    def _init_db(self):
        """Initialize database schema."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS actions (
                    id TEXT PRIMARY KEY,
                    action_type TEXT NOT NULL,
                    category TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    preview TEXT NOT NULL,
                    result TEXT,
                    error TEXT,
                    checkpoint_id TEXT,
                    is_undoable INTEGER DEFAULT 0,
                    undo_deadline TEXT,
                    created_at TEXT NOT NULL,
                    decided_at TEXT,
                    completed_at TEXT,
                    triggered_by TEXT DEFAULT 'user',
                    decided_by TEXT,
                    session_id TEXT,
                    parent_action_id TEXT,
                    request_text TEXT
                )
            """)
            
            # Indexes for common queries
            conn.execute("CREATE INDEX IF NOT EXISTS idx_actions_status ON actions(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_actions_type ON actions(action_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_actions_category ON actions(category)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_actions_created ON actions(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_actions_session ON actions(session_id)")
            
            conn.commit()
    
    def _generate_id(self) -> str:
        """Generate unique action ID."""
        self._counter += 1
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        return f"act_{timestamp}_{self._counter}"
    
    def record_action(
        self,
        action_type: str,
        payload: Dict[str, Any],
        preview: Dict[str, Any],
        status: ActionStatus = ActionStatus.PENDING,
        triggered_by: str = "user",
        session_id: Optional[str] = None,
        parent_action_id: Optional[str] = None,
        request_text: Optional[str] = None,
        is_undoable: bool = False,
        undo_window_minutes: int = 30,
    ) -> ActionRecord:
        """
        Record a new action in history.
        
        Args:
            action_type: Type of action (e.g., "send_email")
            payload: Action parameters
            preview: What was shown to user
            status: Initial status
            triggered_by: Who initiated (user, proactive, scheduled)
            session_id: Current session identifier
            parent_action_id: Parent action for multi-step workflows
            request_text: Original user request text
            is_undoable: Whether action can be undone
            undo_window_minutes: How long undo is available
            
        Returns:
            The created ActionRecord
        """
        category = ACTION_CATEGORIES.get(action_type, ActionCategory.OTHER)
        
        undo_deadline = None
        if is_undoable:
            undo_deadline = datetime.now() + timedelta(minutes=undo_window_minutes)
        
        record = ActionRecord(
            id=self._generate_id(),
            action_type=action_type,
            category=category,
            status=status,
            payload=payload,
            preview=preview,
            triggered_by=triggered_by,
            session_id=session_id,
            parent_action_id=parent_action_id,
            request_text=request_text,
            is_undoable=is_undoable,
            undo_deadline=undo_deadline,
        )
        
        self._save_record(record)
        logger.info(f"Recorded action: {record.id} ({action_type})")
        
        return record
    
    def update_status(
        self,
        action_id: str,
        status: ActionStatus,
        decided_by: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        checkpoint_id: Optional[str] = None,
    ) -> Optional[ActionRecord]:
        """
        Update action status.
        
        Args:
            action_id: Action to update
            status: New status
            decided_by: Who made the decision
            result: Result data (if completed)
            error: Error message (if failed)
            checkpoint_id: Undo checkpoint reference
            
        Returns:
            Updated record or None if not found
        """
        record = self.get_action(action_id)
        if not record:
            return None
        
        record.status = status
        
        if decided_by:
            record.decided_by = decided_by
            record.decided_at = datetime.now()
        
        if status in (ActionStatus.COMPLETED, ActionStatus.FAILED, ActionStatus.UNDONE):
            record.completed_at = datetime.now()
        
        if result:
            record.result = result
        if error:
            record.error = error
        if checkpoint_id:
            record.checkpoint_id = checkpoint_id
        
        self._save_record(record)
        logger.info(f"Updated action {action_id} -> {status.value}")
        
        return record
    
    def mark_approved(
        self,
        action_id: str,
        decided_by: str = "user",
    ) -> Optional[ActionRecord]:
        """Mark action as approved."""
        return self.update_status(action_id, ActionStatus.APPROVED, decided_by=decided_by)
    
    def mark_rejected(
        self,
        action_id: str,
        decided_by: str = "user",
    ) -> Optional[ActionRecord]:
        """Mark action as rejected."""
        return self.update_status(action_id, ActionStatus.REJECTED, decided_by=decided_by)
    
    def mark_completed(
        self,
        action_id: str,
        result: Optional[Dict[str, Any]] = None,
        checkpoint_id: Optional[str] = None,
    ) -> Optional[ActionRecord]:
        """Mark action as successfully completed."""
        return self.update_status(
            action_id, ActionStatus.COMPLETED,
            result=result, checkpoint_id=checkpoint_id
        )
    
    def mark_failed(
        self,
        action_id: str,
        error: str,
    ) -> Optional[ActionRecord]:
        """Mark action as failed."""
        return self.update_status(action_id, ActionStatus.FAILED, error=error)
    
    def mark_undone(
        self,
        action_id: str,
    ) -> Optional[ActionRecord]:
        """Mark action as undone/rolled back."""
        return self.update_status(action_id, ActionStatus.UNDONE)
    
    def get_action(self, action_id: str) -> Optional[ActionRecord]:
        """Get a single action by ID."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                "SELECT * FROM actions WHERE id = ?",
                (action_id,)
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_record(row)
        return None
    
    def get_recent(
        self,
        limit: int = 50,
        status: Optional[ActionStatus] = None,
        category: Optional[ActionCategory] = None,
        since: Optional[datetime] = None,
    ) -> List[ActionRecord]:
        """
        Get recent actions with optional filters.
        
        Args:
            limit: Maximum records to return
            status: Filter by status
            category: Filter by category
            since: Only actions after this time
            
        Returns:
            List of ActionRecords (most recent first)
        """
        query = "SELECT * FROM actions WHERE 1=1"
        params: List[Any] = []
        
        if status:
            query += " AND status = ?"
            params.append(status.value)
        
        if category:
            query += " AND category = ?"
            params.append(category.value)
        
        if since:
            query += " AND created_at >= ?"
            params.append(since.isoformat())
        
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(query, params)
            return [self._row_to_record(row) for row in cursor.fetchall()]
    
    def get_pending(self) -> List[ActionRecord]:
        """Get all pending actions awaiting decision."""
        return self.get_recent(limit=100, status=ActionStatus.PENDING)
    
    def get_undoable(self) -> List[ActionRecord]:
        """Get all actions that can still be undone."""
        now = datetime.now().isoformat()
        
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute("""
                SELECT * FROM actions 
                WHERE is_undoable = 1 
                AND status = 'completed'
                AND undo_deadline >= ?
                ORDER BY completed_at DESC
            """, (now,))
            return [self._row_to_record(row) for row in cursor.fetchall()]
    
    def get_by_session(self, session_id: str) -> List[ActionRecord]:
        """Get all actions for a session."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                "SELECT * FROM actions WHERE session_id = ? ORDER BY created_at",
                (session_id,)
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]
    
    def get_workflow(self, parent_action_id: str) -> List[ActionRecord]:
        """Get all actions in a multi-step workflow."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                "SELECT * FROM actions WHERE parent_action_id = ? ORDER BY created_at",
                (parent_action_id,)
            )
            return [self._row_to_record(row) for row in cursor.fetchall()]
    
    def get_stats(
        self,
        since: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Get statistics about actions.
        
        Args:
            since: Only count actions after this time
            
        Returns:
            Dictionary with counts and breakdowns
        """
        if since is None:
            since = datetime.now() - timedelta(days=7)
        
        with sqlite3.connect(self._db_path) as conn:
            # Total counts by status
            cursor = conn.execute("""
                SELECT status, COUNT(*) FROM actions 
                WHERE created_at >= ?
                GROUP BY status
            """, (since.isoformat(),))
            status_counts = dict(cursor.fetchall())
            
            # Counts by category
            cursor = conn.execute("""
                SELECT category, COUNT(*) FROM actions 
                WHERE created_at >= ?
                GROUP BY category
            """, (since.isoformat(),))
            category_counts = dict(cursor.fetchall())
            
            # Top action types
            cursor = conn.execute("""
                SELECT action_type, COUNT(*) as cnt FROM actions 
                WHERE created_at >= ?
                GROUP BY action_type
                ORDER BY cnt DESC
                LIMIT 10
            """, (since.isoformat(),))
            top_types = dict(cursor.fetchall())
            
            # Undo stats
            cursor = conn.execute("""
                SELECT COUNT(*) FROM actions 
                WHERE status = 'undone' AND created_at >= ?
            """, (since.isoformat(),))
            undone_count = cursor.fetchone()[0]
            
            # Rejection rate
            total = sum(status_counts.values())
            rejected = status_counts.get("rejected", 0)
            rejection_rate = (rejected / total * 100) if total > 0 else 0
        
        return {
            "period_start": since.isoformat(),
            "total_actions": total,
            "by_status": status_counts,
            "by_category": category_counts,
            "top_action_types": top_types,
            "undone_count": undone_count,
            "rejection_rate": round(rejection_rate, 1),
        }
    
    def get_daily_summary(self, date: Optional[datetime] = None) -> Dict[str, Any]:
        """Get summary for a specific day."""
        if date is None:
            date = datetime.now()
        
        start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute("""
                SELECT COUNT(*) FROM actions 
                WHERE created_at >= ? AND created_at < ?
            """, (start.isoformat(), end.isoformat()))
            total = cursor.fetchone()[0]
            
            cursor = conn.execute("""
                SELECT status, COUNT(*) FROM actions 
                WHERE created_at >= ? AND created_at < ?
                GROUP BY status
            """, (start.isoformat(), end.isoformat()))
            by_status = dict(cursor.fetchall())
            
            cursor = conn.execute("""
                SELECT category, COUNT(*) FROM actions 
                WHERE created_at >= ? AND created_at < ?
                GROUP BY category
            """, (start.isoformat(), end.isoformat()))
            by_category = dict(cursor.fetchall())
        
        return {
            "date": start.date().isoformat(),
            "total": total,
            "completed": by_status.get("completed", 0),
            "rejected": by_status.get("rejected", 0),
            "failed": by_status.get("failed", 0),
            "by_category": by_category,
        }
    
    def search(
        self,
        query: str,
        limit: int = 50,
    ) -> List[ActionRecord]:
        """
        Search actions by request text or payload content.
        
        Args:
            query: Search string
            limit: Maximum results
            
        Returns:
            Matching records
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute("""
                SELECT * FROM actions 
                WHERE request_text LIKE ? 
                   OR payload LIKE ?
                   OR action_type LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (f"%{query}%", f"%{query}%", f"%{query}%", limit))
            return [self._row_to_record(row) for row in cursor.fetchall()]
    
    def cleanup_old(self, days: int = 90) -> int:
        """
        Remove actions older than specified days.
        
        Args:
            days: Delete actions older than this
            
        Returns:
            Number of deleted records
        """
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM actions WHERE created_at < ?",
                (cutoff,)
            )
            conn.commit()
            deleted = cursor.rowcount
        
        logger.info(f"Cleaned up {deleted} old action records")
        return deleted
    
    def _save_record(self, record: ActionRecord):
        """Save record to database."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO actions
                (id, action_type, category, status, payload, preview, result, error,
                 checkpoint_id, is_undoable, undo_deadline, created_at, decided_at,
                 completed_at, triggered_by, decided_by, session_id, parent_action_id,
                 request_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.id,
                record.action_type,
                record.category.value,
                record.status.value,
                json.dumps(record.payload),
                json.dumps(record.preview),
                json.dumps(record.result) if record.result else None,
                record.error,
                record.checkpoint_id,
                int(record.is_undoable),
                record.undo_deadline.isoformat() if record.undo_deadline else None,
                record.created_at.isoformat(),
                record.decided_at.isoformat() if record.decided_at else None,
                record.completed_at.isoformat() if record.completed_at else None,
                record.triggered_by,
                record.decided_by,
                record.session_id,
                record.parent_action_id,
                record.request_text,
            ))
            conn.commit()
    
    def _row_to_record(self, row: tuple) -> ActionRecord:
        """Convert database row to ActionRecord."""
        return ActionRecord(
            id=row[0],
            action_type=row[1],
            category=ActionCategory(row[2]),
            status=ActionStatus(row[3]),
            payload=json.loads(row[4]),
            preview=json.loads(row[5]),
            result=json.loads(row[6]) if row[6] else None,
            error=row[7],
            checkpoint_id=row[8],
            is_undoable=bool(row[9]),
            undo_deadline=datetime.fromisoformat(row[10]) if row[10] else None,
            created_at=datetime.fromisoformat(row[11]),
            decided_at=datetime.fromisoformat(row[12]) if row[12] else None,
            completed_at=datetime.fromisoformat(row[13]) if row[13] else None,
            triggered_by=row[14],
            decided_by=row[15],
            session_id=row[16],
            parent_action_id=row[17],
            request_text=row[18],
        )


# Global instance
action_history = ActionHistoryDB()
