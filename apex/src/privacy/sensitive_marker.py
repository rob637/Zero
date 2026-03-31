"""
SensitiveMarker - Mark files/folders as "never send to LLM"

Some data should NEVER leave your machine, even in summarized form.
This module lets you mark paths as sensitive:
- Individual files: ~/Documents/passwords.txt
- Folders: ~/Documents/Financial/
- Patterns: **/*.key, **/*.pem, **/secrets/**

When any service tries to access sensitive content for LLM context,
the marker blocks it and logs the attempt.

Usage:
    marker = SensitiveMarker()
    
    # Mark a file as sensitive
    marker.mark("/home/user/passwords.txt", reason="Contains passwords")
    
    # Mark a folder (all contents)
    marker.mark("/home/user/Financial/", reason="Tax documents")
    
    # Mark by pattern
    marker.mark_pattern("**/*.key", reason="Private keys")
    marker.mark_pattern("**/secrets/**", reason="Secrets folder")
    
    # Check before accessing
    if marker.is_sensitive("/home/user/passwords.txt"):
        # Don't send to LLM!
        pass
    
    # Review marked items
    for item in marker.list_marked():
        print(f"{item.path}: {item.reason}")
"""

import fnmatch
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set
import logging
import re

logger = logging.getLogger(__name__)


class SensitivityLevel(Enum):
    """How sensitive is this content?"""
    NORMAL = "normal"           # Can send to LLM
    SENSITIVE = "sensitive"     # Don't send content, summaries OK
    PRIVATE = "private"         # Don't send anything, not even mentions
    BLOCKED = "blocked"         # Completely inaccessible to Apex


@dataclass
class SensitiveItem:
    """A marked sensitive item."""
    id: str
    path: str                    # Absolute path or pattern
    is_pattern: bool             # True if path is a glob pattern
    level: SensitivityLevel
    reason: str
    marked_at: datetime
    marked_by: str = "user"      # Who marked it (user, auto-detect, etc.)
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "path": self.path,
            "is_pattern": self.is_pattern,
            "level": self.level.value,
            "reason": self.reason,
            "marked_at": self.marked_at.isoformat(),
            "marked_by": self.marked_by,
        }


# Default sensitive patterns (always blocked)
DEFAULT_SENSITIVE_PATTERNS = [
    # Private keys and certificates
    ("**/*.pem", "Private key/certificate", SensitivityLevel.BLOCKED),
    ("**/*.key", "Private key", SensitivityLevel.BLOCKED),
    ("**/*.p12", "PKCS12 certificate", SensitivityLevel.BLOCKED),
    ("**/*.pfx", "PKCS12 certificate", SensitivityLevel.BLOCKED),
    ("**/id_rsa", "SSH private key", SensitivityLevel.BLOCKED),
    ("**/id_ed25519", "SSH private key", SensitivityLevel.BLOCKED),
    ("**/.ssh/**", "SSH directory", SensitivityLevel.BLOCKED),
    
    # Credentials and secrets
    ("**/.env", "Environment variables (may contain secrets)", SensitivityLevel.PRIVATE),
    ("**/.env.*", "Environment variables", SensitivityLevel.PRIVATE),
    ("**/secrets/**", "Secrets directory", SensitivityLevel.PRIVATE),
    ("**/*password*", "Password file", SensitivityLevel.SENSITIVE),
    ("**/*credential*", "Credentials file", SensitivityLevel.SENSITIVE),
    ("**/*.kdbx", "KeePass database", SensitivityLevel.BLOCKED),
    
    # Cloud config (often contains tokens)
    ("**/.aws/**", "AWS credentials", SensitivityLevel.BLOCKED),
    ("**/.gcloud/**", "Google Cloud credentials", SensitivityLevel.BLOCKED),
    ("**/.azure/**", "Azure credentials", SensitivityLevel.BLOCKED),
    
    # Git credentials
    ("**/.git-credentials", "Git credentials", SensitivityLevel.BLOCKED),
    ("**/.netrc", "Network credentials", SensitivityLevel.BLOCKED),
    
    # Browser data
    ("**/Login Data", "Browser saved passwords", SensitivityLevel.BLOCKED),
    ("**/Cookies", "Browser cookies", SensitivityLevel.BLOCKED),
]


class SensitiveMarker:
    """
    Manages sensitive file/folder markers.
    
    Files marked as sensitive are protected from being sent to LLMs,
    even in summarized or extracted form.
    """
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize the sensitive marker.
        
        Args:
            db_path: Path to SQLite database. Defaults to ~/.apex/sensitive.db
        """
        if db_path is None:
            apex_dir = Path.home() / ".apex"
            apex_dir.mkdir(exist_ok=True)
            db_path = str(apex_dir / "sensitive.db")
        
        self._db_path = db_path
        self._cache: Dict[str, SensitiveItem] = {}  # path -> item
        self._patterns: List[SensitiveItem] = []    # Glob patterns
        self._counter = 0
        
        self._init_db()
        self._load_defaults()
        self._load_user_marks()
        
        logger.info(f"SensitiveMarker initialized: {db_path}")
    
    def _init_db(self):
        """Initialize the SQLite database."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sensitive_items (
                    id TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    is_pattern INTEGER NOT NULL,
                    level TEXT NOT NULL,
                    reason TEXT,
                    marked_at TEXT NOT NULL,
                    marked_by TEXT DEFAULT 'user'
                )
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sensitive_path 
                ON sensitive_items(path)
            """)
            
            # Access attempts log
            conn.execute("""
                CREATE TABLE IF NOT EXISTS access_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    blocked INTEGER NOT NULL,
                    reason TEXT,
                    caller TEXT
                )
            """)
            
            conn.commit()
    
    def _generate_id(self) -> str:
        """Generate unique ID."""
        self._counter += 1
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        return f"sens_{timestamp}_{self._counter}"
    
    def _load_defaults(self):
        """Load default sensitive patterns."""
        for pattern, reason, level in DEFAULT_SENSITIVE_PATTERNS:
            item = SensitiveItem(
                id=f"default_{pattern}",
                path=pattern,
                is_pattern=True,
                level=level,
                reason=reason,
                marked_at=datetime.now(),
                marked_by="system",
            )
            self._patterns.append(item)
        
        logger.debug(f"Loaded {len(DEFAULT_SENSITIVE_PATTERNS)} default sensitive patterns")
    
    def _load_user_marks(self):
        """Load user-marked items from database."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute("""
                SELECT id, path, is_pattern, level, reason, marked_at, marked_by
                FROM sensitive_items
            """)
            
            for row in cursor:
                item = SensitiveItem(
                    id=row[0],
                    path=row[1],
                    is_pattern=bool(row[2]),
                    level=SensitivityLevel(row[3]),
                    reason=row[4] or "",
                    marked_at=datetime.fromisoformat(row[5]),
                    marked_by=row[6] or "user",
                )
                
                if item.is_pattern:
                    self._patterns.append(item)
                else:
                    self._cache[item.path] = item
        
        logger.debug(
            f"Loaded {len(self._cache)} marked paths, "
            f"{len(self._patterns)} patterns from database"
        )
    
    def mark(
        self,
        path: str,
        level: SensitivityLevel = SensitivityLevel.SENSITIVE,
        reason: str = "",
    ) -> SensitiveItem:
        """
        Mark a file or folder as sensitive.
        
        Args:
            path: Absolute path to file or folder
            level: Sensitivity level
            reason: Why it's marked (for user reference)
            
        Returns:
            The created SensitiveItem
        """
        # Normalize path
        path = str(Path(path).expanduser().resolve())
        
        item = SensitiveItem(
            id=self._generate_id(),
            path=path,
            is_pattern=False,
            level=level,
            reason=reason,
            marked_at=datetime.now(),
            marked_by="user",
        )
        
        # Save to DB
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO sensitive_items
                (id, path, is_pattern, level, reason, marked_at, marked_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                item.id, item.path, int(item.is_pattern),
                item.level.value, item.reason,
                item.marked_at.isoformat(), item.marked_by
            ))
            conn.commit()
        
        # Update cache
        self._cache[path] = item
        
        logger.info(f"Marked as {level.value}: {path}")
        return item
    
    def mark_pattern(
        self,
        pattern: str,
        level: SensitivityLevel = SensitivityLevel.SENSITIVE,
        reason: str = "",
    ) -> SensitiveItem:
        """
        Mark a glob pattern as sensitive.
        
        Args:
            pattern: Glob pattern (e.g., "**/*.key", "**/secrets/**")
            level: Sensitivity level
            reason: Why it's marked
            
        Returns:
            The created SensitiveItem
        """
        item = SensitiveItem(
            id=self._generate_id(),
            path=pattern,
            is_pattern=True,
            level=level,
            reason=reason,
            marked_at=datetime.now(),
            marked_by="user",
        )
        
        # Save to DB
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO sensitive_items
                (id, path, is_pattern, level, reason, marked_at, marked_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                item.id, item.path, int(item.is_pattern),
                item.level.value, item.reason,
                item.marked_at.isoformat(), item.marked_by
            ))
            conn.commit()
        
        # Update patterns list
        self._patterns.append(item)
        
        logger.info(f"Marked pattern as {level.value}: {pattern}")
        return item
    
    def unmark(self, path_or_id: str) -> bool:
        """
        Remove a sensitive marker.
        
        Args:
            path_or_id: Path or item ID to unmark
            
        Returns:
            True if item was found and removed
        """
        # Try as path first
        if path_or_id in self._cache:
            item = self._cache.pop(path_or_id)
            item_id = item.id
        else:
            # Try as ID
            item_id = path_or_id
            # Remove from cache
            self._cache = {k: v for k, v in self._cache.items() if v.id != item_id}
            # Remove from patterns
            self._patterns = [p for p in self._patterns if p.id != item_id]
        
        # Remove from DB
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM sensitive_items WHERE id = ? OR path = ?",
                (item_id, path_or_id)
            )
            conn.commit()
            
            if cursor.rowcount > 0:
                logger.info(f"Unmarked: {path_or_id}")
                return True
        
        return False
    
    def is_sensitive(self, path: str, log_attempt: bool = True) -> bool:
        """
        Check if a path is marked as sensitive.
        
        Args:
            path: Path to check
            log_attempt: Whether to log this access attempt
            
        Returns:
            True if path is sensitive (any level above NORMAL)
        """
        level = self.get_sensitivity_level(path, log_attempt)
        return level != SensitivityLevel.NORMAL
    
    def get_sensitivity_level(
        self,
        path: str,
        log_attempt: bool = True,
    ) -> SensitivityLevel:
        """
        Get the sensitivity level of a path.
        
        Args:
            path: Path to check
            log_attempt: Whether to log this access attempt
            
        Returns:
            SensitivityLevel
        """
        # Normalize path
        try:
            normalized = str(Path(path).expanduser().resolve())
        except Exception:
            normalized = path
        
        # Check direct cache first
        if normalized in self._cache:
            item = self._cache[normalized]
            if log_attempt:
                self._log_access(normalized, blocked=True, reason=item.reason)
            return item.level
        
        # Check if path is under a marked folder
        for cached_path, item in self._cache.items():
            if normalized.startswith(cached_path + "/") or normalized == cached_path:
                if log_attempt:
                    self._log_access(normalized, blocked=True, reason=f"Under {cached_path}")
                return item.level
        
        # Check patterns
        for pattern_item in self._patterns:
            if self._matches_pattern(normalized, pattern_item.path):
                if log_attempt:
                    self._log_access(
                        normalized, blocked=True,
                        reason=f"Matches pattern: {pattern_item.path}"
                    )
                return pattern_item.level
        
        # Not sensitive
        if log_attempt:
            self._log_access(normalized, blocked=False)
        return SensitivityLevel.NORMAL
    
    def _matches_pattern(self, path: str, pattern: str) -> bool:
        """Check if path matches a glob pattern."""
        # Handle ** for recursive matching
        # Convert glob to regex
        if "**" in pattern:
            # ** matches any number of directories
            regex = pattern.replace("**", ".*")
            regex = regex.replace("*", "[^/]*")
            regex = regex.replace("?", ".")
            regex = f"^.*{regex}$"
            return bool(re.match(regex, path, re.IGNORECASE))
        else:
            # Simple glob
            return fnmatch.fnmatch(path.lower(), pattern.lower())
    
    def _log_access(
        self,
        path: str,
        blocked: bool,
        reason: str = None,
        caller: str = None,
    ):
        """Log an access attempt."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                INSERT INTO access_attempts
                (path, timestamp, blocked, reason, caller)
                VALUES (?, ?, ?, ?, ?)
            """, (
                path,
                datetime.now().isoformat(),
                int(blocked),
                reason,
                caller,
            ))
            conn.commit()
    
    def list_marked(
        self,
        include_defaults: bool = False,
    ) -> List[SensitiveItem]:
        """
        List all marked items.
        
        Args:
            include_defaults: Include system default patterns
            
        Returns:
            List of SensitiveItem
        """
        items = list(self._cache.values())
        
        for pattern in self._patterns:
            if include_defaults or pattern.marked_by != "system":
                items.append(pattern)
        
        return items
    
    def get_access_log(self, limit: int = 50) -> List[Dict]:
        """
        Get recent access attempts.
        
        Returns:
            List of access attempts (most recent first)
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute("""
                SELECT path, timestamp, blocked, reason, caller
                FROM access_attempts
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,))
            
            return [
                {
                    "path": row[0],
                    "timestamp": row[1],
                    "blocked": bool(row[2]),
                    "reason": row[3],
                    "caller": row[4],
                }
                for row in cursor.fetchall()
            ]
    
    def get_stats(self) -> Dict:
        """Get statistics about sensitive items and access attempts."""
        with sqlite3.connect(self._db_path) as conn:
            # Count by level
            cursor = conn.execute("""
                SELECT level, COUNT(*) 
                FROM sensitive_items 
                GROUP BY level
            """)
            by_level = {row[0]: row[1] for row in cursor.fetchall()}
            
            # Count access attempts
            cursor = conn.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(blocked) as blocked
                FROM access_attempts
                WHERE timestamp >= datetime('now', '-24 hours')
            """)
            row = cursor.fetchone()
            
            return {
                "marked_items": len(self._cache),
                "patterns": len([p for p in self._patterns if p.marked_by != "system"]),
                "default_patterns": len([p for p in self._patterns if p.marked_by == "system"]),
                "by_level": by_level,
                "access_attempts_24h": row[0] or 0,
                "blocked_24h": row[1] or 0,
            }


# Global instance
sensitive_marker = SensitiveMarker()
