"""
Proactive Scanner - The "Awareness" that makes Apex a brain

This is what transforms Apex from reactive to proactive:
- Periodically scans for opportunities
- Notices patterns and problems
- Generates suggestions without user asking
- Learns what the user cares about

The scanner runs in the background and populates a suggestion queue.
The UI can poll for new suggestions to show the user.

Examples of proactive intelligence:
- "Your Downloads folder has 847 files. Want me to organize?"
- "I found 2.3GB of duplicate photos in Pictures"
- "You have a flight tomorrow but haven't checked in yet"
- "It's been 2 weeks since your last PC cleanup"
"""

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from enum import Enum
from typing import Callable


class SuggestionPriority(Enum):
    """Priority level for suggestions."""
    LOW = "low"          # Nice to know
    MEDIUM = "medium"    # Worth considering
    HIGH = "high"        # Should act soon
    URGENT = "urgent"    # Needs attention now


class SuggestionCategory(Enum):
    """Category of suggestion."""
    CLEANUP = "cleanup"
    ORGANIZATION = "organization"
    STORAGE = "storage"
    REMINDER = "reminder"
    OPTIMIZATION = "optimization"
    SECURITY = "security"


@dataclass
class Suggestion:
    """A proactive suggestion from Apex."""
    id: str
    title: str
    description: str
    category: SuggestionCategory
    priority: SuggestionPriority
    action_prompt: str  # The prompt to send to chat if user accepts
    skill_hint: str | None = None  # Which skill would handle this
    created_at: str = ""
    expires_at: str | None = None  # Some suggestions expire
    dismissed: bool = False
    acted_on: bool = False
    metadata: dict = field(default_factory=dict)  # Extra data
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
    
    def to_dict(self) -> dict:
        """Convert to dict for API/UI."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "category": self.category.value,
            "priority": self.priority.value,
            "action_prompt": self.action_prompt,
            "skill_hint": self.skill_hint,
            "created_at": self.created_at,
            "dismissed": self.dismissed,
            "acted_on": self.acted_on,
            "metadata": self.metadata,
        }


@dataclass
class ScanResult:
    """Result from a single scan check."""
    should_suggest: bool
    suggestion: Suggestion | None = None


class ProactiveScanner:
    """
    Background scanner that generates proactive suggestions.
    
    The scanner:
    1. Runs periodic checks on user's system
    2. Detects opportunities for improvement
    3. Generates suggestions for the UI to display
    4. Learns from user responses (dismissals, actions)
    
    This is the "awareness" layer that makes Apex feel intelligent.
    """
    
    def __init__(self, memory_engine=None):
        self._suggestions: dict[str, Suggestion] = {}
        self._suggestion_counter = 0
        self._last_scan: datetime | None = None
        self._scan_interval = timedelta(hours=4)  # How often to scan
        self._running = False
        
        # Import memory here to avoid circular imports
        if memory_engine is None:
            from .memory import memory
            self._memory = memory
        else:
            self._memory = memory_engine
        
        # Scan checks - each returns a ScanResult
        self._checks: list[Callable] = [
            self._check_downloads_folder,
            self._check_temp_files,
            self._check_duplicate_potential,
            self._check_disk_space,
            self._check_old_files,
            self._check_last_cleanup,
        ]
    
    def _generate_id(self) -> str:
        """Generate unique suggestion ID."""
        self._suggestion_counter += 1
        return f"sug_{self._suggestion_counter}_{datetime.now().strftime('%H%M%S')}"
    
    async def run_scan(self) -> list[Suggestion]:
        """
        Run all scan checks and collect suggestions.
        
        Returns list of new suggestions generated.
        """
        new_suggestions = []
        
        for check in self._checks:
            try:
                result = await check()
                if result.should_suggest and result.suggestion:
                    # Don't duplicate existing suggestions
                    if not self._has_similar_suggestion(result.suggestion):
                        result.suggestion.id = self._generate_id()
                        self._suggestions[result.suggestion.id] = result.suggestion
                        new_suggestions.append(result.suggestion)
            except Exception as e:
                # Don't crash on individual check failures
                print(f"[Scanner] Check failed: {e}")
        
        self._last_scan = datetime.now()
        return new_suggestions
    
    def _has_similar_suggestion(self, new: Suggestion) -> bool:
        """Check if we already have a similar active suggestion."""
        for existing in self._suggestions.values():
            if (existing.category == new.category and 
                not existing.dismissed and 
                not existing.acted_on):
                # Same category, still active - don't duplicate
                return True
        return False
    
    def get_pending_suggestions(self) -> list[Suggestion]:
        """Get all pending (not dismissed, not acted on) suggestions."""
        now = datetime.now()
        pending = []
        
        for sug in self._suggestions.values():
            if sug.dismissed or sug.acted_on:
                continue
            
            # Check expiration
            if sug.expires_at:
                expires = datetime.fromisoformat(sug.expires_at)
                if now > expires:
                    continue
            
            pending.append(sug)
        
        # Sort by priority
        priority_order = {
            SuggestionPriority.URGENT: 0,
            SuggestionPriority.HIGH: 1,
            SuggestionPriority.MEDIUM: 2,
            SuggestionPriority.LOW: 3,
        }
        pending.sort(key=lambda s: priority_order.get(s.priority, 99))
        
        return pending
    
    def dismiss_suggestion(self, suggestion_id: str) -> bool:
        """Mark a suggestion as dismissed."""
        if suggestion_id in self._suggestions:
            self._suggestions[suggestion_id].dismissed = True
            # TODO: Track dismissal patterns for learning
            return True
        return False
    
    def mark_acted_on(self, suggestion_id: str) -> bool:
        """Mark that user acted on a suggestion."""
        if suggestion_id in self._suggestions:
            self._suggestions[suggestion_id].acted_on = True
            # TODO: Track action patterns for learning
            return True
        return False
    
    # ============================================
    # Individual Scan Checks
    # ============================================
    
    async def _check_downloads_folder(self) -> ScanResult:
        """Check if Downloads folder is cluttered."""
        downloads = Path.home() / "Downloads"
        
        # Check OneDrive on Windows
        if os.name == 'nt':
            for item in Path.home().iterdir():
                if item.is_dir() and item.name.startswith('OneDrive'):
                    od_downloads = item / 'Downloads'
                    if od_downloads.exists():
                        downloads = od_downloads
                        break
        
        if not downloads.exists():
            return ScanResult(should_suggest=False)
        
        try:
            files = list(downloads.iterdir())
            file_count = len([f for f in files if f.is_file()])
            
            if file_count > 100:
                return ScanResult(
                    should_suggest=True,
                    suggestion=Suggestion(
                        id="",
                        title=f"Downloads folder has {file_count} files",
                        description=f"Your Downloads folder is getting cluttered. I can organize these files by type or date.",
                        category=SuggestionCategory.ORGANIZATION,
                        priority=SuggestionPriority.MEDIUM if file_count < 300 else SuggestionPriority.HIGH,
                        action_prompt="Organize my Downloads folder",
                        skill_hint="file_organizer",
                        metadata={"file_count": file_count, "path": str(downloads)},
                    )
                )
        except PermissionError:
            pass
        
        return ScanResult(should_suggest=False)
    
    async def _check_temp_files(self) -> ScanResult:
        """Check temp folder size."""
        temp_paths = []
        
        if os.name == 'nt':
            temp_paths = [
                Path(os.environ.get('TEMP', '')),
                Path(os.environ.get('TMP', '')),
                Path.home() / 'AppData' / 'Local' / 'Temp',
            ]
        else:
            temp_paths = [Path('/tmp'), Path.home() / '.cache']
        
        total_size = 0
        for temp_path in temp_paths:
            if temp_path.exists():
                try:
                    for f in temp_path.rglob('*'):
                        if f.is_file():
                            try:
                                total_size += f.stat().st_size
                            except:
                                pass
                except:
                    pass
        
        # If > 1GB of temp files
        if total_size > 1024 * 1024 * 1024:
            size_gb = total_size / (1024 * 1024 * 1024)
            return ScanResult(
                should_suggest=True,
                suggestion=Suggestion(
                    id="",
                    title=f"Found {size_gb:.1f} GB of temporary files",
                    description="Cleaning these could free up significant disk space.",
                    category=SuggestionCategory.CLEANUP,
                    priority=SuggestionPriority.MEDIUM,
                    action_prompt="Clean up temporary files",
                    skill_hint="temp_cleaner",
                    metadata={"size_bytes": total_size},
                )
            )
        
        return ScanResult(should_suggest=False)
    
    async def _check_duplicate_potential(self) -> ScanResult:
        """Quick heuristic check for potential duplicates."""
        pictures = Path.home() / "Pictures"
        
        # Check OneDrive
        if os.name == 'nt':
            for item in Path.home().iterdir():
                if item.is_dir() and item.name.startswith('OneDrive'):
                    od_pics = item / 'Pictures'
                    if od_pics.exists():
                        pictures = od_pics
                        break
        
        if not pictures.exists():
            return ScanResult(should_suggest=False)
        
        # Count files by size (same size = potential duplicate)
        size_counts: dict[int, int] = {}
        try:
            for f in pictures.rglob('*'):
                if f.is_file() and f.suffix.lower() in {'.jpg', '.jpeg', '.png', '.heic'}:
                    try:
                        size = f.stat().st_size
                        size_counts[size] = size_counts.get(size, 0) + 1
                    except:
                        pass
        except:
            pass
        
        # Count potential duplicates (files with same size)
        potential_dupes = sum(count - 1 for count in size_counts.values() if count > 1)
        
        if potential_dupes > 50:
            return ScanResult(
                should_suggest=True,
                suggestion=Suggestion(
                    id="",
                    title=f"Found ~{potential_dupes} potential duplicate photos",
                    description="I detected files with identical sizes that might be duplicates. Want me to check?",
                    category=SuggestionCategory.STORAGE,
                    priority=SuggestionPriority.LOW,
                    action_prompt="Find duplicate photos in my Pictures folder",
                    skill_hint="duplicate_finder",
                    metadata={"potential_count": potential_dupes},
                )
            )
        
        return ScanResult(should_suggest=False)
    
    async def _check_disk_space(self) -> ScanResult:
        """Check if disk space is running low."""
        try:
            import shutil
            
            # Check the home drive
            total, used, free = shutil.disk_usage(Path.home())
            
            free_gb = free / (1024 ** 3)
            percent_used = (used / total) * 100
            
            if percent_used > 90 or free_gb < 10:
                return ScanResult(
                    should_suggest=True,
                    suggestion=Suggestion(
                        id="",
                        title=f"Disk space is running low ({free_gb:.1f} GB free)",
                        description="Less than 10% of your disk is free. Let me help find what's using space.",
                        category=SuggestionCategory.STORAGE,
                        priority=SuggestionPriority.HIGH if free_gb < 5 else SuggestionPriority.MEDIUM,
                        action_prompt="Analyze what's using my disk space",
                        skill_hint="disk_analyzer",
                        metadata={"free_gb": free_gb, "percent_used": percent_used},
                    )
                )
        except:
            pass
        
        return ScanResult(should_suggest=False)
    
    async def _check_old_files(self) -> ScanResult:
        """Check for very old files in Downloads."""
        downloads = Path.home() / "Downloads"
        
        if os.name == 'nt':
            for item in Path.home().iterdir():
                if item.is_dir() and item.name.startswith('OneDrive'):
                    od_downloads = item / 'Downloads'
                    if od_downloads.exists():
                        downloads = od_downloads
                        break
        
        if not downloads.exists():
            return ScanResult(should_suggest=False)
        
        # Check for files older than 6 months
        cutoff = datetime.now() - timedelta(days=180)
        old_count = 0
        old_size = 0
        
        try:
            for f in downloads.iterdir():
                if f.is_file():
                    try:
                        mtime = datetime.fromtimestamp(f.stat().st_mtime)
                        if mtime < cutoff:
                            old_count += 1
                            old_size += f.stat().st_size
                    except:
                        pass
        except:
            pass
        
        if old_count > 20:
            size_mb = old_size / (1024 * 1024)
            return ScanResult(
                should_suggest=True,
                suggestion=Suggestion(
                    id="",
                    title=f"Found {old_count} old files in Downloads",
                    description=f"These files are over 6 months old ({size_mb:.0f} MB). Consider archiving or deleting.",
                    category=SuggestionCategory.CLEANUP,
                    priority=SuggestionPriority.LOW,
                    action_prompt="Help me clean up old files in Downloads",
                    skill_hint="file_organizer",
                    metadata={"old_count": old_count, "old_size_bytes": old_size},
                )
            )
        
        return ScanResult(should_suggest=False)
    
    async def _check_last_cleanup(self) -> ScanResult:
        """Check when user last ran a cleanup."""
        if not self._memory:
            return ScanResult(should_suggest=False)
        
        # Get last cleanup time from memory
        last_cleanup = self._memory.get_last_cleanup_time()
        
        if last_cleanup is None:
            # Never cleaned up - suggest it
            return ScanResult(
                should_suggest=True,
                suggestion=Suggestion(
                    id="",
                    title="First time? Let's clean up!",
                    description="I haven't helped you clean your PC yet. Want me to scan for things we can tidy up?",
                    category=SuggestionCategory.OPTIMIZATION,
                    priority=SuggestionPriority.MEDIUM,
                    action_prompt="Help me clean up my PC",
                    skill_hint="temp_cleaner",
                    metadata={},
                )
            )
        
        # Check if it's been more than 2 weeks
        days_since = (datetime.now() - last_cleanup).days
        
        if days_since > 14:
            return ScanResult(
                should_suggest=True,
                suggestion=Suggestion(
                    id="",
                    title=f"It's been {days_since} days since your last cleanup",
                    description="Regular maintenance keeps your PC running smoothly. Want me to check for things to clean?",
                    category=SuggestionCategory.OPTIMIZATION,
                    priority=SuggestionPriority.LOW,
                    action_prompt="Run a maintenance check on my PC",
                    skill_hint="temp_cleaner",
                    metadata={"days_since_cleanup": days_since},
                )
            )
        
        return ScanResult(should_suggest=False)


# Global scanner instance
proactive_scanner = ProactiveScanner()
