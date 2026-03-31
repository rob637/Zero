"""
AuditLogger - Track all external data transmissions.

Every time data leaves your machine, we log:
- Timestamp
- Destination (which LLM provider)
- What was sent (preview, for review)
- What was received
- Why (which user request triggered it)
- Size in bytes

User can review: "Show me everything I sent to the LLM this week"

This is the foundation of data sovereignty - you can VERIFY that
your data stays home unless you explicitly asked a question.
"""

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import List, Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class TransmissionDirection(Enum):
    """Direction of data transmission."""
    OUTBOUND = "outbound"  # Data leaving your machine
    INBOUND = "inbound"    # Response coming back


class TransmissionDestination(Enum):
    """Known external services."""
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GOOGLE_AI = "google_ai"
    LOCAL_LLM = "local_llm"  # Ollama, llama.cpp - stays local!
    OTHER = "other"


@dataclass
class TransmissionRecord:
    """
    A record of data transmitted externally.
    
    This is your audit trail - proof of what left your machine.
    """
    id: str
    timestamp: datetime
    direction: TransmissionDirection
    destination: TransmissionDestination
    
    # What was sent/received
    content_preview: str      # First N chars for review (not full content)
    content_hash: str         # SHA256 for integrity verification
    content_size_bytes: int
    
    # Why this happened
    triggering_request: str   # The user request that caused this
    request_id: Optional[str] = None  # Link to workflow/task if applicable
    
    # Context
    model: Optional[str] = None        # Which model (claude-3, gpt-4, etc.)
    endpoint: Optional[str] = None     # API endpoint called
    latency_ms: Optional[float] = None # How long the call took
    
    # Privacy flags
    contained_pii: bool = False        # Did redaction engine find PII?
    redactions_applied: int = 0        # How many items were redacted
    
    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "direction": self.direction.value,
            "destination": self.destination.value,
            "content_preview": self.content_preview,
            "content_hash": self.content_hash,
            "content_size_bytes": self.content_size_bytes,
            "triggering_request": self.triggering_request,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "contained_pii": self.contained_pii,
            "redactions_applied": self.redactions_applied,
        }


class AuditLogger:
    """
    Logs all external data transmissions for transparency.
    
    Usage:
        # At startup
        audit = AuditLogger()
        
        # Before calling LLM
        record_id = audit.log_outbound(
            destination=TransmissionDestination.ANTHROPIC,
            content="Summarize this loan: Principal $425k...",
            triggering_request="What's in my loan document?",
            model="claude-3-sonnet",
        )
        
        # After receiving response
        audit.log_inbound(
            destination=TransmissionDestination.ANTHROPIC,
            content="The loan has the following terms...",
            request_id=record_id,
        )
        
        # User reviews audit log
        records = audit.get_transmissions(since=datetime.now() - timedelta(days=7))
        for r in records:
            print(f"{r.timestamp}: {r.direction.value} to {r.destination.value}")
            print(f"  Preview: {r.content_preview[:100]}...")
    """
    
    # How much content to store in preview (for review without storing everything)
    PREVIEW_LENGTH = 500
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize the audit logger.
        
        Args:
            db_path: Path to SQLite database. Defaults to ~/.apex/audit.db
        """
        if db_path is None:
            apex_dir = Path.home() / ".apex"
            apex_dir.mkdir(exist_ok=True)
            db_path = str(apex_dir / "audit.db")
        
        self._db_path = db_path
        self._record_counter = 0
        self._init_db()
        
        logger.info(f"AuditLogger initialized: {db_path}")
    
    def _init_db(self):
        """Initialize the SQLite database."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transmissions (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    content_preview TEXT,
                    content_hash TEXT,
                    content_size_bytes INTEGER,
                    triggering_request TEXT,
                    request_id TEXT,
                    model TEXT,
                    endpoint TEXT,
                    latency_ms REAL,
                    contained_pii INTEGER DEFAULT 0,
                    redactions_applied INTEGER DEFAULT 0,
                    metadata TEXT
                )
            """)
            
            # Index for common queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp 
                ON transmissions(timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_destination 
                ON transmissions(destination)
            """)
            conn.commit()
    
    def _generate_id(self) -> str:
        """Generate unique transmission ID."""
        self._record_counter += 1
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        return f"tx_{timestamp}_{self._record_counter}"
    
    def _hash_content(self, content: str) -> str:
        """Generate SHA256 hash of content for verification."""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    def log_outbound(
        self,
        destination: TransmissionDestination,
        content: str,
        triggering_request: str,
        model: Optional[str] = None,
        endpoint: Optional[str] = None,
        request_id: Optional[str] = None,
        contained_pii: bool = False,
        redactions_applied: int = 0,
        metadata: Optional[Dict] = None,
    ) -> str:
        """
        Log an outbound transmission (data leaving your machine).
        
        Args:
            destination: Where the data is going (Anthropic, OpenAI, etc.)
            content: The full content being sent
            triggering_request: What the user asked that caused this
            model: Which model is being called
            endpoint: API endpoint
            request_id: Link to task/workflow ID
            contained_pii: Did redaction find PII?
            redactions_applied: How many items were redacted
            metadata: Additional context
            
        Returns:
            Record ID for linking response
        """
        record = TransmissionRecord(
            id=self._generate_id(),
            timestamp=datetime.now(),
            direction=TransmissionDirection.OUTBOUND,
            destination=destination,
            content_preview=content[:self.PREVIEW_LENGTH],
            content_hash=self._hash_content(content),
            content_size_bytes=len(content.encode('utf-8')),
            triggering_request=triggering_request[:200],  # Truncate request
            request_id=request_id,
            model=model,
            endpoint=endpoint,
            contained_pii=contained_pii,
            redactions_applied=redactions_applied,
            metadata=metadata or {},
        )
        
        self._save_record(record)
        
        logger.info(
            f"Outbound transmission logged: {record.id} -> {destination.value} "
            f"({record.content_size_bytes} bytes)"
        )
        
        return record.id
    
    def log_inbound(
        self,
        destination: TransmissionDestination,
        content: str,
        request_id: Optional[str] = None,
        latency_ms: Optional[float] = None,
        model: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> str:
        """
        Log an inbound transmission (response from external service).
        
        Args:
            destination: Where the data came from
            content: The response content
            request_id: Link to the outbound request
            latency_ms: How long the request took
            model: Which model responded
            metadata: Additional context
            
        Returns:
            Record ID
        """
        record = TransmissionRecord(
            id=self._generate_id(),
            timestamp=datetime.now(),
            direction=TransmissionDirection.INBOUND,
            destination=destination,
            content_preview=content[:self.PREVIEW_LENGTH],
            content_hash=self._hash_content(content),
            content_size_bytes=len(content.encode('utf-8')),
            triggering_request="",  # Inbound doesn't have a trigger
            request_id=request_id,
            model=model,
            latency_ms=latency_ms,
            metadata=metadata or {},
        )
        
        self._save_record(record)
        
        logger.debug(
            f"Inbound transmission logged: {record.id} <- {destination.value}"
        )
        
        return record.id
    
    def _save_record(self, record: TransmissionRecord):
        """Save a transmission record to the database."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                INSERT INTO transmissions (
                    id, timestamp, direction, destination,
                    content_preview, content_hash, content_size_bytes,
                    triggering_request, request_id,
                    model, endpoint, latency_ms,
                    contained_pii, redactions_applied, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.id,
                record.timestamp.isoformat(),
                record.direction.value,
                record.destination.value,
                record.content_preview,
                record.content_hash,
                record.content_size_bytes,
                record.triggering_request,
                record.request_id,
                record.model,
                record.endpoint,
                record.latency_ms,
                1 if record.contained_pii else 0,
                record.redactions_applied,
                json.dumps(record.metadata),
            ))
            conn.commit()
    
    def get_transmissions(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        destination: Optional[TransmissionDestination] = None,
        direction: Optional[TransmissionDirection] = None,
        limit: int = 100,
    ) -> List[TransmissionRecord]:
        """
        Query transmission history.
        
        Args:
            since: Start time (default: 24 hours ago)
            until: End time (default: now)
            destination: Filter by destination
            direction: Filter by direction (outbound/inbound)
            limit: Maximum records to return
            
        Returns:
            List of transmission records, newest first
        """
        if since is None:
            since = datetime.now() - timedelta(hours=24)
        if until is None:
            until = datetime.now()
        
        query = """
            SELECT * FROM transmissions
            WHERE timestamp >= ? AND timestamp <= ?
        """
        params = [since.isoformat(), until.isoformat()]
        
        if destination:
            query += " AND destination = ?"
            params.append(destination.value)
        
        if direction:
            query += " AND direction = ?"
            params.append(direction.value)
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        records = []
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            
            for row in cursor:
                record = TransmissionRecord(
                    id=row['id'],
                    timestamp=datetime.fromisoformat(row['timestamp']),
                    direction=TransmissionDirection(row['direction']),
                    destination=TransmissionDestination(row['destination']),
                    content_preview=row['content_preview'] or "",
                    content_hash=row['content_hash'] or "",
                    content_size_bytes=row['content_size_bytes'] or 0,
                    triggering_request=row['triggering_request'] or "",
                    request_id=row['request_id'],
                    model=row['model'],
                    endpoint=row['endpoint'],
                    latency_ms=row['latency_ms'],
                    contained_pii=bool(row['contained_pii']),
                    redactions_applied=row['redactions_applied'] or 0,
                    metadata=json.loads(row['metadata']) if row['metadata'] else {},
                )
                records.append(record)
        
        return records
    
    def get_stats(
        self,
        since: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Get transmission statistics.
        
        Args:
            since: Start time (default: 24 hours ago)
            
        Returns:
            Statistics dict with counts, bytes, destinations, etc.
        """
        if since is None:
            since = datetime.now() - timedelta(hours=24)
        
        with sqlite3.connect(self._db_path) as conn:
            # Total counts
            cursor = conn.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN direction = 'outbound' THEN 1 ELSE 0 END) as outbound,
                    SUM(CASE WHEN direction = 'inbound' THEN 1 ELSE 0 END) as inbound,
                    SUM(content_size_bytes) as total_bytes,
                    SUM(CASE WHEN direction = 'outbound' THEN content_size_bytes ELSE 0 END) as bytes_sent,
                    SUM(CASE WHEN contained_pii = 1 THEN 1 ELSE 0 END) as had_pii,
                    SUM(redactions_applied) as total_redactions
                FROM transmissions
                WHERE timestamp >= ?
            """, (since.isoformat(),))
            row = cursor.fetchone()
            
            # By destination
            cursor = conn.execute("""
                SELECT destination, COUNT(*) as count
                FROM transmissions
                WHERE timestamp >= ?
                GROUP BY destination
            """, (since.isoformat(),))
            by_destination = {row[0]: row[1] for row in cursor.fetchall()}
            
            return {
                "since": since.isoformat(),
                "total_transmissions": row[0] or 0,
                "outbound_count": row[1] or 0,
                "inbound_count": row[2] or 0,
                "total_bytes": row[3] or 0,
                "bytes_sent": row[4] or 0,
                "transmissions_with_pii": row[5] or 0,
                "total_redactions": row[6] or 0,
                "by_destination": by_destination,
            }
    
    def get_today_summary(self) -> str:
        """
        Get a human-readable summary of today's transmissions.
        
        Returns:
            Formatted summary string
        """
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        stats = self.get_stats(since=today)
        
        def format_bytes(b: int) -> str:
            if b < 1024:
                return f"{b} bytes"
            elif b < 1024 * 1024:
                return f"{b / 1024:.1f} KB"
            else:
                return f"{b / (1024 * 1024):.1f} MB"
        
        lines = [
            "📊 Today's External Transmissions",
            "─" * 40,
            f"Total calls: {stats['outbound_count']} outbound, {stats['inbound_count']} inbound",
            f"Data sent: {format_bytes(stats['bytes_sent'])}",
        ]
        
        if stats['transmissions_with_pii'] > 0:
            lines.append(f"⚠️  {stats['transmissions_with_pii']} transmissions had PII (redacted)")
            lines.append(f"   {stats['total_redactions']} items redacted")
        else:
            lines.append("✓ No PII detected in transmissions")
        
        if stats['by_destination']:
            lines.append("")
            lines.append("By destination:")
            for dest, count in stats['by_destination'].items():
                lines.append(f"  • {dest}: {count}")
        
        return "\n".join(lines)


# Global instance for convenience
audit_logger = AuditLogger()
