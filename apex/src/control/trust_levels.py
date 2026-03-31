"""
TrustLevelManager - Control what needs approval.

Trust Levels:
- 🔴 ALWAYS_ASK: Always require explicit approval (emails, deletes, financial)
- 🟡 ASK_ONCE: Ask first time, offer to remember the pattern
- 🟢 AUTO_APPROVE: User has pre-approved this action type (read-only queries)

The manager:
1. Tracks trust levels per action type
2. Learns patterns when user approves "Ask Once" actions
3. Persists settings to disk
4. Provides clear defaults for safety

Default trust levels prioritize SAFETY:
- Anything that SENDS data externally: ALWAYS_ASK
- Anything that DELETES or MODIFIES: ALWAYS_ASK  
- Anything that CREATES new items: ASK_ONCE
- Anything that just READS: AUTO_APPROVE
"""

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, Set
import logging
import hashlib

logger = logging.getLogger(__name__)


class TrustLevel(Enum):
    """
    Trust levels for action approval.
    
    🔴 ALWAYS_ASK - Every instance requires explicit approval
    🟡 ASK_ONCE - Ask once, then remember if user allows
    🟢 AUTO_APPROVE - Execute without asking
    """
    ALWAYS_ASK = "always_ask"        # 🔴 Always confirm
    ASK_ONCE = "ask_once"            # 🟡 Learn pattern
    AUTO_APPROVE = "auto_approve"    # 🟢 Trusted


class ActionCategory(Enum):
    """Categories of actions for trust management."""
    SEND = "send"           # Sending data externally (email, message)
    DELETE = "delete"       # Deleting or moving to trash
    MODIFY = "modify"       # Modifying existing items
    CREATE = "create"       # Creating new items
    READ = "read"           # Reading/searching (no side effects)
    SCHEDULE = "schedule"   # Creating calendar events
    FINANCIAL = "financial" # Anything involving money


@dataclass
class TrustPattern:
    """
    A learned pattern for "Ask Once" actions.
    
    When a user approves an ASK_ONCE action the first time,
    we record the pattern so we can auto-approve similar actions.
    """
    id: str
    action_type: str
    pattern_hash: str  # Hash of the pattern for matching
    pattern_description: str  # Human-readable description
    approved_at: datetime
    approved_by: str  # User ID or "local"
    times_auto_approved: int = 0
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "action_type": self.action_type,
            "pattern_description": self.pattern_description,
            "approved_at": self.approved_at.isoformat(),
            "times_auto_approved": self.times_auto_approved,
        }


class TrustLevelManager:
    """
    Manages trust levels for different action types.
    
    Usage:
        trust = TrustLevelManager()
        
        # Check if action needs approval
        level = trust.get_trust_level("send_email")
        if level == TrustLevel.ALWAYS_ASK:
            # Show approval UI
            pass
        
        # User approves an ASK_ONCE action, remember the pattern
        trust.remember_pattern(
            action_type="create_calendar_event",
            pattern={"recurring": "weekly_team_meeting"},
            description="Weekly team meeting on Tuesday 10am"
        )
        
        # Later, same pattern auto-approves
        level = trust.get_trust_level("create_calendar_event", context={"recurring": "weekly_team_meeting"})
        # Returns AUTO_APPROVE because we learned this pattern
    """
    
    # Default trust levels - SAFETY FIRST
    DEFAULT_LEVELS: Dict[str, TrustLevel] = {
        # 🔴 ALWAYS ASK - High risk actions
        "send_email": TrustLevel.ALWAYS_ASK,
        "send_message": TrustLevel.ALWAYS_ASK,  # Slack, Teams, etc.
        "delete_file": TrustLevel.ALWAYS_ASK,
        "move_to_trash": TrustLevel.ALWAYS_ASK,
        "delete_email": TrustLevel.ALWAYS_ASK,
        "delete_event": TrustLevel.ALWAYS_ASK,
        "delete_task": TrustLevel.ALWAYS_ASK,
        "share_file": TrustLevel.ALWAYS_ASK,
        "share_document": TrustLevel.ALWAYS_ASK,
        "financial_action": TrustLevel.ALWAYS_ASK,
        "submit_form": TrustLevel.ALWAYS_ASK,
        "post_public": TrustLevel.ALWAYS_ASK,  # Social media, etc.
        "create_pr": TrustLevel.ALWAYS_ASK,  # GitHub PR
        "merge_pr": TrustLevel.ALWAYS_ASK,
        
        # 🟡 ASK ONCE - Medium risk, can learn patterns
        "create_calendar_event": TrustLevel.ASK_ONCE,
        "create_task": TrustLevel.ASK_ONCE,
        "create_document": TrustLevel.ASK_ONCE,
        "create_folder": TrustLevel.ASK_ONCE,
        "move_file": TrustLevel.ASK_ONCE,
        "rename_file": TrustLevel.ASK_ONCE,
        "update_task": TrustLevel.ASK_ONCE,
        "update_event": TrustLevel.ASK_ONCE,
        "create_draft": TrustLevel.ASK_ONCE,  # Draft email (not sending)
        "create_issue": TrustLevel.ASK_ONCE,  # GitHub issue
        
        # 🟢 AUTO APPROVE - Low risk, read-only
        "read_file": TrustLevel.AUTO_APPROVE,
        "search_files": TrustLevel.AUTO_APPROVE,
        "search_email": TrustLevel.AUTO_APPROVE,
        "search_calendar": TrustLevel.AUTO_APPROVE,
        "search_contacts": TrustLevel.AUTO_APPROVE,
        "list_directory": TrustLevel.AUTO_APPROVE,
        "get_file_info": TrustLevel.AUTO_APPROVE,
        "calculate": TrustLevel.AUTO_APPROVE,  # Math operations
        "summarize": TrustLevel.AUTO_APPROVE,  # Text summarization
        "search_web": TrustLevel.AUTO_APPROVE,  # Web search (read-only)
    }
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize the trust level manager.
        
        Args:
            db_path: Path to SQLite database. Defaults to ~/.apex/trust.db
        """
        if db_path is None:
            apex_dir = Path.home() / ".apex"
            apex_dir.mkdir(exist_ok=True)
            db_path = str(apex_dir / "trust.db")
        
        self._db_path = db_path
        self._custom_levels: Dict[str, TrustLevel] = {}
        self._patterns: Dict[str, List[TrustPattern]] = {}
        
        self._init_db()
        self._load_settings()
        
        logger.info(f"TrustLevelManager initialized: {db_path}")
    
    def _init_db(self):
        """Initialize the SQLite database."""
        with sqlite3.connect(self._db_path) as conn:
            # Custom trust level overrides
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trust_levels (
                    action_type TEXT PRIMARY KEY,
                    trust_level TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            
            # Learned patterns for ASK_ONCE
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trust_patterns (
                    id TEXT PRIMARY KEY,
                    action_type TEXT NOT NULL,
                    pattern_hash TEXT NOT NULL,
                    pattern_description TEXT,
                    approved_at TEXT NOT NULL,
                    approved_by TEXT DEFAULT 'local',
                    times_auto_approved INTEGER DEFAULT 0
                )
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_patterns_action 
                ON trust_patterns(action_type)
            """)
            
            conn.commit()
    
    def _load_settings(self):
        """Load custom settings from database."""
        with sqlite3.connect(self._db_path) as conn:
            # Load custom trust levels
            cursor = conn.execute("SELECT action_type, trust_level FROM trust_levels")
            for row in cursor:
                try:
                    self._custom_levels[row[0]] = TrustLevel(row[1])
                except ValueError:
                    pass
            
            # Load patterns
            cursor = conn.execute("""
                SELECT id, action_type, pattern_hash, pattern_description, 
                       approved_at, approved_by, times_auto_approved
                FROM trust_patterns
            """)
            for row in cursor:
                pattern = TrustPattern(
                    id=row[0],
                    action_type=row[1],
                    pattern_hash=row[2],
                    pattern_description=row[3] or "",
                    approved_at=datetime.fromisoformat(row[4]),
                    approved_by=row[5] or "local",
                    times_auto_approved=row[6] or 0,
                )
                if pattern.action_type not in self._patterns:
                    self._patterns[pattern.action_type] = []
                self._patterns[pattern.action_type].append(pattern)
        
        logger.debug(f"Loaded {len(self._custom_levels)} custom levels, {sum(len(p) for p in self._patterns.values())} patterns")
    
    def get_trust_level(
        self,
        action_type: str,
        context: Optional[Dict] = None,
    ) -> TrustLevel:
        """
        Get the trust level for an action.
        
        Args:
            action_type: The type of action (e.g., "send_email")
            context: Optional context for pattern matching
            
        Returns:
            TrustLevel indicating how to handle approval
        """
        # Check for custom override first
        if action_type in self._custom_levels:
            custom_level = self._custom_levels[action_type]
            
            # If ASK_ONCE, check for learned patterns
            if custom_level == TrustLevel.ASK_ONCE and context:
                if self._matches_pattern(action_type, context):
                    return TrustLevel.AUTO_APPROVE
            
            return custom_level
        
        # Check default levels
        if action_type in self.DEFAULT_LEVELS:
            default_level = self.DEFAULT_LEVELS[action_type]
            
            # If ASK_ONCE, check for learned patterns
            if default_level == TrustLevel.ASK_ONCE and context:
                if self._matches_pattern(action_type, context):
                    return TrustLevel.AUTO_APPROVE
            
            return default_level
        
        # Unknown action type - default to ASK_ONCE for safety
        logger.warning(f"Unknown action type: {action_type}, defaulting to ASK_ONCE")
        return TrustLevel.ASK_ONCE
    
    def _hash_pattern(self, context: Dict) -> str:
        """Generate a hash for a context pattern."""
        # Sort keys for consistent hashing
        normalized = json.dumps(context, sort_keys=True)
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]
    
    def _matches_pattern(self, action_type: str, context: Dict) -> bool:
        """Check if context matches a learned pattern."""
        if action_type not in self._patterns:
            return False
        
        context_hash = self._hash_pattern(context)
        
        for pattern in self._patterns[action_type]:
            if pattern.pattern_hash == context_hash:
                # Update auto-approval count
                self._increment_pattern_usage(pattern.id)
                return True
        
        return False
    
    def _increment_pattern_usage(self, pattern_id: str):
        """Increment the auto-approval count for a pattern."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                UPDATE trust_patterns 
                SET times_auto_approved = times_auto_approved + 1
                WHERE id = ?
            """, (pattern_id,))
            conn.commit()
    
    def set_trust_level(
        self,
        action_type: str,
        level: TrustLevel,
    ):
        """
        Set a custom trust level for an action type.
        
        Args:
            action_type: The action type to configure
            level: The trust level to set
        """
        self._custom_levels[action_type] = level
        
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO trust_levels (action_type, trust_level, updated_at)
                VALUES (?, ?, ?)
            """, (action_type, level.value, datetime.now().isoformat()))
            conn.commit()
        
        logger.info(f"Set trust level: {action_type} -> {level.value}")
    
    def remember_pattern(
        self,
        action_type: str,
        context: Dict,
        description: str = "",
    ) -> str:
        """
        Remember a pattern for future auto-approval.
        
        Called when user approves an ASK_ONCE action and chooses
        to remember the pattern for next time.
        
        Args:
            action_type: The action type
            context: The context to remember as a pattern
            description: Human-readable description
            
        Returns:
            Pattern ID
        """
        pattern_hash = self._hash_pattern(context)
        pattern_id = f"pat_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{pattern_hash[:8]}"
        
        pattern = TrustPattern(
            id=pattern_id,
            action_type=action_type,
            pattern_hash=pattern_hash,
            pattern_description=description,
            approved_at=datetime.now(),
            approved_by="local",
        )
        
        # Store in memory
        if action_type not in self._patterns:
            self._patterns[action_type] = []
        self._patterns[action_type].append(pattern)
        
        # Persist to database
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                INSERT INTO trust_patterns 
                (id, action_type, pattern_hash, pattern_description, approved_at, approved_by)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                pattern.id,
                pattern.action_type,
                pattern.pattern_hash,
                pattern.pattern_description,
                pattern.approved_at.isoformat(),
                pattern.approved_by,
            ))
            conn.commit()
        
        logger.info(f"Remembered pattern: {action_type} - {description}")
        return pattern_id
    
    def forget_pattern(self, pattern_id: str) -> bool:
        """
        Forget a learned pattern.
        
        Args:
            pattern_id: The pattern ID to forget
            
        Returns:
            True if pattern was found and removed
        """
        # Remove from memory
        for action_type, patterns in self._patterns.items():
            for i, pattern in enumerate(patterns):
                if pattern.id == pattern_id:
                    patterns.pop(i)
                    
                    # Remove from database
                    with sqlite3.connect(self._db_path) as conn:
                        conn.execute("DELETE FROM trust_patterns WHERE id = ?", (pattern_id,))
                        conn.commit()
                    
                    logger.info(f"Forgot pattern: {pattern_id}")
                    return True
        
        return False
    
    def reset_to_defaults(self, action_type: Optional[str] = None):
        """
        Reset trust levels to defaults.
        
        Args:
            action_type: Specific action to reset, or None for all
        """
        with sqlite3.connect(self._db_path) as conn:
            if action_type:
                conn.execute("DELETE FROM trust_levels WHERE action_type = ?", (action_type,))
                self._custom_levels.pop(action_type, None)
            else:
                conn.execute("DELETE FROM trust_levels")
                self._custom_levels.clear()
            conn.commit()
        
        logger.info(f"Reset trust levels: {action_type or 'all'}")
    
    def get_all_levels(self) -> Dict[str, Dict]:
        """
        Get all action types and their trust levels.
        
        Returns:
            Dict mapping action_type to {level, is_custom, patterns}
        """
        result = {}
        
        # Start with defaults
        for action_type, level in self.DEFAULT_LEVELS.items():
            result[action_type] = {
                "level": level.value,
                "is_custom": False,
                "pattern_count": len(self._patterns.get(action_type, [])),
            }
        
        # Override with custom
        for action_type, level in self._custom_levels.items():
            result[action_type] = {
                "level": level.value,
                "is_custom": True,
                "pattern_count": len(self._patterns.get(action_type, [])),
            }
        
        return result
    
    def get_patterns(self, action_type: Optional[str] = None) -> List[TrustPattern]:
        """
        Get learned patterns.
        
        Args:
            action_type: Filter by action type, or None for all
            
        Returns:
            List of TrustPattern objects
        """
        if action_type:
            return self._patterns.get(action_type, [])
        
        all_patterns = []
        for patterns in self._patterns.values():
            all_patterns.extend(patterns)
        return all_patterns
    
    def get_icon(self, level: TrustLevel) -> str:
        """Get the icon for a trust level."""
        return {
            TrustLevel.ALWAYS_ASK: "🔴",
            TrustLevel.ASK_ONCE: "🟡",
            TrustLevel.AUTO_APPROVE: "🟢",
        }.get(level, "⚪")
    
    def explain(self, action_type: str) -> str:
        """
        Get a human-readable explanation of an action's trust level.
        
        Args:
            action_type: The action type to explain
            
        Returns:
            Explanation string
        """
        level = self.get_trust_level(action_type)
        icon = self.get_icon(level)
        is_custom = action_type in self._custom_levels
        patterns = self._patterns.get(action_type, [])
        
        explanations = {
            TrustLevel.ALWAYS_ASK: "Always requires your approval before executing",
            TrustLevel.ASK_ONCE: "Will ask for approval, with option to remember your choice",
            TrustLevel.AUTO_APPROVE: "Pre-approved to execute without asking",
        }
        
        lines = [
            f"{icon} **{action_type}**: {level.value}",
            explanations[level],
        ]
        
        if is_custom:
            lines.append("(Custom setting)")
        
        if patterns:
            lines.append(f"Learned patterns: {len(patterns)}")
            for p in patterns[:3]:  # Show first 3
                lines.append(f"  • {p.pattern_description}")
        
        return "\n".join(lines)


# Global instance for convenience
trust_manager = TrustLevelManager()
