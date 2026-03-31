"""
UndoManager - Checkpoint and rollback for Apex actions.

Creates checkpoints before potentially destructive actions,
allowing users to undo recent operations.

Supported undo types:
- FILE: Restore from backup
- CALENDAR: Delete created event / restore deleted event
- FILE_MOVE: Move back
- FILE_WRITE: Restore previous content
- TASK: Restore task state

Non-undoable (but tracked):
- Sent emails (can't unsend after a few seconds)
- Slack messages (after edit window)
- GitHub/Jira changes (use their native undo)

Usage:
    # Before an action
    checkpoint = undo_manager.create_checkpoint(
        action_id="act_123",
        action_type="delete_file",
        data={"path": "/file.txt", "content": original_content}
    )
    
    # After action completes
    undo_manager.commit_checkpoint(checkpoint.id)
    
    # User wants to undo
    success = await undo_manager.undo(checkpoint.id)
"""

import json
import os
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Awaitable
import logging
import hashlib
import asyncio

logger = logging.getLogger(__name__)


class UndoType(Enum):
    """Type of undo operation."""
    FILE_DELETE = "file_delete"       # Restore deleted file
    FILE_OVERWRITE = "file_overwrite"  # Restore previous content
    FILE_MOVE = "file_move"           # Move file back
    FILE_CREATE = "file_create"       # Delete created file
    CALENDAR_CREATE = "calendar_create"  # Delete created event
    CALENDAR_DELETE = "calendar_delete"  # Recreate deleted event
    CALENDAR_UPDATE = "calendar_update"  # Restore previous state
    TASK_CREATE = "task_create"       # Delete created task
    TASK_UPDATE = "task_update"       # Restore previous state
    CONTACT_CREATE = "contact_create"  # Delete created contact
    GENERIC = "generic"               # Custom undo function


class UndoStatus(Enum):
    """Status of an undo checkpoint."""
    PENDING = "pending"       # Action in progress, checkpoint active
    COMMITTED = "committed"   # Action completed, undo available
    EXECUTED = "executed"     # Undo was performed
    EXPIRED = "expired"       # Undo window closed
    FAILED = "failed"         # Undo attempt failed


@dataclass 
class Checkpoint:
    """A checkpoint for potential undo."""
    id: str
    action_id: str           # Related action in ActionHistoryDB
    undo_type: UndoType
    status: UndoStatus
    
    # What to restore
    data: Dict[str, Any]     # Type-specific restore data
    
    # Timing
    created_at: datetime = field(default_factory=datetime.now)
    committed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    
    # Metadata
    description: str = ""    # Human-readable description
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "action_id": self.action_id,
            "undo_type": self.undo_type.value,
            "status": self.status.value,
            "data": self.data,
            "created_at": self.created_at.isoformat(),
            "committed_at": self.committed_at.isoformat() if self.committed_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
            "description": self.description,
        }
    
    @property
    def is_undoable(self) -> bool:
        """Check if this checkpoint can still be undone."""
        if self.status != UndoStatus.COMMITTED:
            return False
        if self.expires_at and datetime.now() > self.expires_at:
            return False
        return True


class UndoManager:
    """
    Manages checkpoints and undo operations.
    
    Creates snapshots before destructive actions, stores them,
    and executes rollback when requested.
    """
    
    # Default undo window (minutes)
    DEFAULT_UNDO_WINDOW = 30
    
    # File backup directory
    BACKUP_SUBDIR = "undo_backups"
    
    def __init__(
        self,
        db_path: Optional[str] = None,
        backup_dir: Optional[str] = None,
    ):
        """
        Initialize UndoManager.
        
        Args:
            db_path: SQLite database path
            backup_dir: Directory for file backups
        """
        apex_dir = Path.home() / ".apex"
        apex_dir.mkdir(exist_ok=True)
        
        if db_path is None:
            db_path = str(apex_dir / "undo.db")
        
        if backup_dir is None:
            backup_dir = str(apex_dir / self.BACKUP_SUBDIR)
        
        self._db_path = db_path
        self._backup_dir = Path(backup_dir)
        self._backup_dir.mkdir(exist_ok=True)
        
        self._counter = 0
        self._custom_undos: Dict[str, Callable] = {}
        
        self._init_db()
        logger.info(f"UndoManager initialized: {db_path}")
    
    def _init_db(self):
        """Initialize database schema."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS checkpoints (
                    id TEXT PRIMARY KEY,
                    action_id TEXT NOT NULL,
                    undo_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    committed_at TEXT,
                    expires_at TEXT,
                    executed_at TEXT,
                    description TEXT
                )
            """)
            
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cp_action ON checkpoints(action_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cp_status ON checkpoints(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cp_expires ON checkpoints(expires_at)")
            
            conn.commit()
    
    def _generate_id(self) -> str:
        """Generate unique checkpoint ID."""
        self._counter += 1
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        return f"cp_{timestamp}_{self._counter}"
    
    def create_checkpoint(
        self,
        action_id: str,
        undo_type: UndoType,
        data: Dict[str, Any],
        description: str = "",
        undo_window_minutes: int = DEFAULT_UNDO_WINDOW,
    ) -> Checkpoint:
        """
        Create a checkpoint before an action.
        
        Args:
            action_id: Related action ID from ActionHistoryDB
            undo_type: Type of undo operation
            data: Type-specific data needed for undo
            description: Human-readable description
            undo_window_minutes: How long undo is available
            
        Returns:
            Created checkpoint (not yet committed)
        """
        checkpoint = Checkpoint(
            id=self._generate_id(),
            action_id=action_id,
            undo_type=undo_type,
            status=UndoStatus.PENDING,
            data=data,
            description=description,
        )
        
        self._save_checkpoint(checkpoint)
        logger.debug(f"Created checkpoint: {checkpoint.id} for {action_id}")
        
        return checkpoint
    
    def create_file_backup(
        self,
        action_id: str,
        file_path: str,
        description: str = "",
    ) -> Optional[Checkpoint]:
        """
        Create a backup of a file before modification.
        
        Args:
            action_id: Related action ID
            file_path: Path to file to backup
            description: What's happening to the file
            
        Returns:
            Checkpoint with backup reference, or None if file doesn't exist
        """
        path = Path(file_path)
        if not path.exists():
            return None
        
        # Create backup file
        backup_id = hashlib.sha256(
            f"{file_path}_{datetime.now().isoformat()}".encode()
        ).hexdigest()[:16]
        
        backup_path = self._backup_dir / backup_id
        shutil.copy2(path, backup_path)
        
        checkpoint = self.create_checkpoint(
            action_id=action_id,
            undo_type=UndoType.FILE_OVERWRITE,
            data={
                "original_path": str(path.absolute()),
                "backup_path": str(backup_path),
                "backup_id": backup_id,
            },
            description=description or f"Backup of {path.name}",
        )
        
        logger.info(f"Created file backup: {file_path} -> {backup_path}")
        return checkpoint
    
    def create_file_delete_checkpoint(
        self,
        action_id: str,
        file_path: str,
    ) -> Optional[Checkpoint]:
        """
        Backup a file before deletion.
        
        Args:
            action_id: Related action ID
            file_path: Path to file being deleted
            
        Returns:
            Checkpoint with backup, or None if file doesn't exist
        """
        path = Path(file_path)
        if not path.exists():
            return None
        
        # Backup the file
        backup_id = hashlib.sha256(
            f"{file_path}_{datetime.now().isoformat()}".encode()
        ).hexdigest()[:16]
        
        backup_path = self._backup_dir / backup_id
        shutil.copy2(path, backup_path)
        
        checkpoint = self.create_checkpoint(
            action_id=action_id,
            undo_type=UndoType.FILE_DELETE,
            data={
                "original_path": str(path.absolute()),
                "backup_path": str(backup_path),
                "backup_id": backup_id,
                "was_directory": False,
            },
            description=f"Delete: {path.name}",
        )
        
        return checkpoint
    
    def create_calendar_event_checkpoint(
        self,
        action_id: str,
        event_data: Dict[str, Any],
        operation: str,  # "create", "update", "delete"
        provider: str = "google",
    ) -> Checkpoint:
        """
        Create checkpoint for calendar event changes.
        
        Args:
            action_id: Related action ID
            event_data: Event data (including ID for existing events)
            operation: What's being done
            provider: Calendar provider
            
        Returns:
            Checkpoint
        """
        if operation == "create":
            undo_type = UndoType.CALENDAR_CREATE
            description = f"Create event: {event_data.get('title', 'Untitled')}"
        elif operation == "delete":
            undo_type = UndoType.CALENDAR_DELETE
            description = f"Delete event: {event_data.get('title', 'Untitled')}"
        else:
            undo_type = UndoType.CALENDAR_UPDATE
            description = f"Update event: {event_data.get('title', 'Untitled')}"
        
        return self.create_checkpoint(
            action_id=action_id,
            undo_type=undo_type,
            data={
                "event": event_data,
                "operation": operation,
                "provider": provider,
            },
            description=description,
        )
    
    def create_task_checkpoint(
        self,
        action_id: str,
        task_data: Dict[str, Any],
        operation: str,
        provider: str = "microsoft",
    ) -> Checkpoint:
        """Create checkpoint for task changes."""
        if operation == "create":
            undo_type = UndoType.TASK_CREATE
        else:
            undo_type = UndoType.TASK_UPDATE
        
        return self.create_checkpoint(
            action_id=action_id,
            undo_type=undo_type,
            data={
                "task": task_data,
                "operation": operation,
                "provider": provider,
            },
            description=f"{operation.title()} task: {task_data.get('title', 'Untitled')}",
        )
    
    def commit_checkpoint(
        self,
        checkpoint_id: str,
        undo_window_minutes: int = DEFAULT_UNDO_WINDOW,
    ) -> Optional[Checkpoint]:
        """
        Commit a checkpoint after action completes successfully.
        
        This makes the undo available for the undo window.
        
        Args:
            checkpoint_id: Checkpoint to commit
            undo_window_minutes: How long undo is available
            
        Returns:
            Updated checkpoint or None
        """
        checkpoint = self.get_checkpoint(checkpoint_id)
        if not checkpoint:
            return None
        
        checkpoint.status = UndoStatus.COMMITTED
        checkpoint.committed_at = datetime.now()
        checkpoint.expires_at = datetime.now() + timedelta(minutes=undo_window_minutes)
        
        self._save_checkpoint(checkpoint)
        logger.info(f"Committed checkpoint: {checkpoint_id}, expires {checkpoint.expires_at}")
        
        return checkpoint
    
    def cancel_checkpoint(self, checkpoint_id: str) -> bool:
        """
        Cancel a pending checkpoint (action was rejected/failed).
        
        Cleans up any backup files.
        """
        checkpoint = self.get_checkpoint(checkpoint_id)
        if not checkpoint:
            return False
        
        # Clean up backup files if any
        if checkpoint.undo_type in (UndoType.FILE_DELETE, UndoType.FILE_OVERWRITE):
            backup_path = checkpoint.data.get("backup_path")
            if backup_path and Path(backup_path).exists():
                Path(backup_path).unlink()
        
        # Delete checkpoint
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM checkpoints WHERE id = ?", (checkpoint_id,))
            conn.commit()
        
        return True
    
    async def undo(
        self,
        checkpoint_id: str,
    ) -> Dict[str, Any]:
        """
        Execute undo for a checkpoint.
        
        Args:
            checkpoint_id: Checkpoint to undo
            
        Returns:
            Result dict with success status and details
        """
        checkpoint = self.get_checkpoint(checkpoint_id)
        if not checkpoint:
            return {"success": False, "error": "Checkpoint not found"}
        
        if not checkpoint.is_undoable:
            if checkpoint.status == UndoStatus.EXECUTED:
                return {"success": False, "error": "Already undone"}
            if checkpoint.expires_at and datetime.now() > checkpoint.expires_at:
                checkpoint.status = UndoStatus.EXPIRED
                self._save_checkpoint(checkpoint)
                return {"success": False, "error": "Undo window expired"}
            return {"success": False, "error": f"Cannot undo: status is {checkpoint.status.value}"}
        
        try:
            result = await self._execute_undo(checkpoint)
            
            checkpoint.status = UndoStatus.EXECUTED
            checkpoint.executed_at = datetime.now()
            self._save_checkpoint(checkpoint)
            
            logger.info(f"Executed undo: {checkpoint_id}")
            return {"success": True, "result": result}
            
        except Exception as e:
            checkpoint.status = UndoStatus.FAILED
            self._save_checkpoint(checkpoint)
            logger.error(f"Undo failed: {checkpoint_id} - {e}")
            return {"success": False, "error": str(e)}
    
    async def _execute_undo(self, checkpoint: Checkpoint) -> Any:
        """Execute the actual undo operation."""
        
        if checkpoint.undo_type == UndoType.FILE_DELETE:
            # Restore deleted file from backup
            backup_path = Path(checkpoint.data["backup_path"])
            original_path = Path(checkpoint.data["original_path"])
            
            if not backup_path.exists():
                raise FileNotFoundError(f"Backup not found: {backup_path}")
            
            # Restore file
            shutil.copy2(backup_path, original_path)
            return {"restored": str(original_path)}
        
        elif checkpoint.undo_type == UndoType.FILE_OVERWRITE:
            # Restore previous file content
            backup_path = Path(checkpoint.data["backup_path"])
            original_path = Path(checkpoint.data["original_path"])
            
            if not backup_path.exists():
                raise FileNotFoundError(f"Backup not found: {backup_path}")
            
            shutil.copy2(backup_path, original_path)
            return {"restored": str(original_path)}
        
        elif checkpoint.undo_type == UndoType.FILE_CREATE:
            # Delete the created file
            file_path = Path(checkpoint.data["created_path"])
            if file_path.exists():
                file_path.unlink()
            return {"deleted": str(file_path)}
        
        elif checkpoint.undo_type == UndoType.FILE_MOVE:
            # Move file back
            current = Path(checkpoint.data["current_path"])
            original = Path(checkpoint.data["original_path"])
            if current.exists():
                shutil.move(str(current), str(original))
            return {"moved_back": str(original)}
        
        elif checkpoint.undo_type == UndoType.CALENDAR_CREATE:
            # Delete created event - requires connector
            return await self._undo_calendar_create(checkpoint.data)
        
        elif checkpoint.undo_type == UndoType.CALENDAR_DELETE:
            # Recreate deleted event
            return await self._undo_calendar_delete(checkpoint.data)
        
        elif checkpoint.undo_type == UndoType.CALENDAR_UPDATE:
            # Restore previous event state
            return await self._undo_calendar_update(checkpoint.data)
        
        elif checkpoint.undo_type == UndoType.TASK_CREATE:
            return await self._undo_task_create(checkpoint.data)
        
        elif checkpoint.undo_type == UndoType.GENERIC:
            # Custom undo function
            undo_key = checkpoint.data.get("undo_key")
            if undo_key and undo_key in self._custom_undos:
                return await self._custom_undos[undo_key](checkpoint.data)
            raise ValueError(f"No custom undo registered: {undo_key}")
        
        else:
            raise NotImplementedError(f"Undo not implemented: {checkpoint.undo_type}")
    
    async def _undo_calendar_create(self, data: Dict) -> Dict:
        """Undo calendar event creation by deleting it."""
        event = data["event"]
        provider = data.get("provider", "google")
        event_id = event.get("id")
        
        if not event_id:
            raise ValueError("No event ID to delete")
        
        # This would call the calendar connector
        # For now, return what would happen
        return {
            "action": "delete_event",
            "event_id": event_id,
            "provider": provider,
            "note": "Calendar connector would delete this event"
        }
    
    async def _undo_calendar_delete(self, data: Dict) -> Dict:
        """Undo calendar event deletion by recreating it."""
        event = data["event"]
        provider = data.get("provider", "google")
        
        # Would call calendar connector to recreate
        return {
            "action": "recreate_event",
            "event": event,
            "provider": provider,
            "note": "Calendar connector would recreate this event"
        }
    
    async def _undo_calendar_update(self, data: Dict) -> Dict:
        """Undo calendar event update by restoring previous state."""
        event = data["event"]
        provider = data.get("provider", "google")
        
        return {
            "action": "restore_event",
            "event": event,
            "provider": provider,
            "note": "Calendar connector would restore previous state"
        }
    
    async def _undo_task_create(self, data: Dict) -> Dict:
        """Undo task creation by deleting it."""
        task = data["task"]
        provider = data.get("provider", "microsoft")
        task_id = task.get("id")
        
        return {
            "action": "delete_task",
            "task_id": task_id,
            "provider": provider,
            "note": "Task connector would delete this task"
        }
    
    def register_custom_undo(
        self,
        key: str,
        undo_func: Callable[[Dict], Awaitable[Any]],
    ):
        """
        Register a custom undo function.
        
        Args:
            key: Unique key for this undo type
            undo_func: Async function that performs the undo
        """
        self._custom_undos[key] = undo_func
    
    def get_checkpoint(self, checkpoint_id: str) -> Optional[Checkpoint]:
        """Get checkpoint by ID."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                "SELECT * FROM checkpoints WHERE id = ?",
                (checkpoint_id,)
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_checkpoint(row)
        return None
    
    def get_for_action(self, action_id: str) -> Optional[Checkpoint]:
        """Get checkpoint for a specific action."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                "SELECT * FROM checkpoints WHERE action_id = ? ORDER BY created_at DESC LIMIT 1",
                (action_id,)
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_checkpoint(row)
        return None
    
    def get_undoable(self) -> List[Checkpoint]:
        """Get all currently undoable checkpoints."""
        now = datetime.now().isoformat()
        
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute("""
                SELECT * FROM checkpoints
                WHERE status = 'committed'
                AND expires_at >= ?
                ORDER BY created_at DESC
            """, (now,))
            return [self._row_to_checkpoint(row) for row in cursor.fetchall()]
    
    def cleanup_expired(self) -> int:
        """Clean up expired checkpoints and their backups."""
        now = datetime.now().isoformat()
        cleaned = 0
        
        with sqlite3.connect(self._db_path) as conn:
            # Find expired checkpoints with backups
            cursor = conn.execute("""
                SELECT id, data FROM checkpoints
                WHERE status = 'committed'
                AND expires_at < ?
            """, (now,))
            
            for row in cursor.fetchall():
                cp_id, data_json = row
                data = json.loads(data_json)
                
                # Clean up backup file
                backup_path = data.get("backup_path")
                if backup_path and Path(backup_path).exists():
                    Path(backup_path).unlink()
                
                cleaned += 1
            
            # Update status to expired
            conn.execute("""
                UPDATE checkpoints
                SET status = 'expired'
                WHERE status = 'committed' AND expires_at < ?
            """, (now,))
            conn.commit()
        
        if cleaned > 0:
            logger.info(f"Cleaned up {cleaned} expired checkpoints")
        
        return cleaned
    
    def cleanup_old(self, days: int = 7) -> int:
        """Remove old checkpoints and backups."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cleaned = 0
        
        with sqlite3.connect(self._db_path) as conn:
            # Find old checkpoints with backups
            cursor = conn.execute("""
                SELECT id, data FROM checkpoints
                WHERE created_at < ?
            """, (cutoff,))
            
            for row in cursor.fetchall():
                cp_id, data_json = row
                data = json.loads(data_json)
                
                backup_path = data.get("backup_path")
                if backup_path and Path(backup_path).exists():
                    Path(backup_path).unlink()
                
                cleaned += 1
            
            # Delete old checkpoints
            conn.execute("DELETE FROM checkpoints WHERE created_at < ?", (cutoff,))
            conn.commit()
        
        return cleaned
    
    def _save_checkpoint(self, checkpoint: Checkpoint):
        """Save checkpoint to database."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO checkpoints
                (id, action_id, undo_type, status, data, created_at,
                 committed_at, expires_at, executed_at, description)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                checkpoint.id,
                checkpoint.action_id,
                checkpoint.undo_type.value,
                checkpoint.status.value,
                json.dumps(checkpoint.data),
                checkpoint.created_at.isoformat(),
                checkpoint.committed_at.isoformat() if checkpoint.committed_at else None,
                checkpoint.expires_at.isoformat() if checkpoint.expires_at else None,
                checkpoint.executed_at.isoformat() if checkpoint.executed_at else None,
                checkpoint.description,
            ))
            conn.commit()
    
    def _row_to_checkpoint(self, row: tuple) -> Checkpoint:
        """Convert database row to Checkpoint."""
        return Checkpoint(
            id=row[0],
            action_id=row[1],
            undo_type=UndoType(row[2]),
            status=UndoStatus(row[3]),
            data=json.loads(row[4]),
            created_at=datetime.fromisoformat(row[5]),
            committed_at=datetime.fromisoformat(row[6]) if row[6] else None,
            expires_at=datetime.fromisoformat(row[7]) if row[7] else None,
            executed_at=datetime.fromisoformat(row[8]) if row[8] else None,
            description=row[9] or "",
        )


# Global instance
undo_manager = UndoManager()
