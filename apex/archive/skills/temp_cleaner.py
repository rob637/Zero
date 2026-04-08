"""
TempCleaner Skill - Clean temporary files and caches

Scans and cleans:
- Windows Temp folders
- Browser caches
- Software caches
- Old log files
"""

import os
import shutil
from pathlib import Path
from datetime import datetime, timedelta

from ..core.skill import (
    Skill, 
    ActionPlan, 
    ProposedAction, 
    ActionType,
    register_skill,
)


def format_size(size_bytes: int) -> str:
    """Format file size in human readable format."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def get_folder_size(folder: Path) -> int:
    """Calculate total size of a folder."""
    total = 0
    try:
        for item in folder.rglob('*'):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except (OSError, PermissionError):
                    pass
    except (OSError, PermissionError):
        pass
    return total


class TempCleanerSkill(Skill):
    """
    Skill for cleaning temporary files and caches.
    
    Capabilities:
    - Scan Windows temp folders
    - Find browser caches
    - Identify old/stale files
    - Safe deletion with summaries
    """
    
    name = "temp_cleaner"
    description = "Clean up temporary files and caches to free space"
    version = "0.1.0"
    
    trigger_phrases = [
        "temp",
        "temporary",
        "cache",
        "cleanup",
        "clear cache",
        "free space",
        "junk",
    ]
    
    permissions = [
        "filesystem.read",
        "filesystem.write",
    ]
    
    # Known safe-to-delete temp locations
    TEMP_LOCATIONS = {
        "Windows Temp": lambda: Path(os.environ.get('TEMP', '')),
        "User Temp": lambda: Path.home() / "AppData" / "Local" / "Temp",
        "Windows Prefetch": lambda: Path("C:/Windows/Prefetch"),
        "Recent Items": lambda: Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Recent",
    }
    
    BROWSER_CACHES = {
        "Chrome Cache": lambda: Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data" / "Default" / "Cache",
        "Chrome Code Cache": lambda: Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data" / "Default" / "Code Cache",
        "Edge Cache": lambda: Path.home() / "AppData" / "Local" / "Microsoft" / "Edge" / "User Data" / "Default" / "Cache",
        "Firefox Cache": lambda: Path.home() / "AppData" / "Local" / "Mozilla" / "Firefox" / "Profiles",
    }
    
    def __init__(self):
        """Initialize TempCleaner skill."""
        pass
    
    async def analyze(self, request: str, context: dict) -> ActionPlan:
        """
        Scan system for cleanable temp files and caches.
        
        Args:
            request: User's request
            context: Additional context
            
        Returns:
            ActionPlan with cleanup suggestions
        """
        actions = []
        total_size = 0
        warnings = []
        
        # Scan temp locations
        for name, path_fn in self.TEMP_LOCATIONS.items():
            try:
                path = path_fn()
                if path and path.exists():
                    size = get_folder_size(path)
                    if size > 0:
                        total_size += size
                        actions.append(ProposedAction(
                            action_type=ActionType.DELETE,
                            source=str(path),
                            reason=f"{name} - {format_size(size)} of temporary files",
                        ))
            except Exception:
                pass
        
        # Scan browser caches
        for name, path_fn in self.BROWSER_CACHES.items():
            try:
                path = path_fn()
                if path and path.exists():
                    size = get_folder_size(path)
                    if size > 10 * 1024 * 1024:  # Only if > 10MB
                        total_size += size
                        actions.append(ProposedAction(
                            action_type=ActionType.DELETE,
                            source=str(path),
                            reason=f"{name} - {format_size(size)}",
                        ))
            except Exception:
                pass
        
        # Scan Recycle Bin (informational)
        recycle_bin = Path("C:/$Recycle.Bin")
        if recycle_bin.exists():
            try:
                size = get_folder_size(recycle_bin)
                if size > 0:
                    warnings.append(f"Recycle Bin contains {format_size(size)} - empty via Windows to recover space")
            except:
                pass
        
        if not actions:
            return ActionPlan(
                summary="System is already clean!",
                reasoning="No significant temporary files or caches found.",
                warnings=warnings,
                affected_files_count=0,
                space_freed_estimate="0 MB"
            )
        
        # Add safety warnings
        warnings.extend([
            "Browser caches may need to be rebuilt after clearing",
            "Some temp files may be in use - those will be skipped",
        ])
        
        return ActionPlan(
            summary=f"Found {format_size(total_size)} of cleanable files",
            reasoning=f"Identified {len(actions)} locations with temporary files and caches.",
            actions=actions,
            warnings=warnings,
            affected_files_count=len(actions),
            space_freed_estimate=format_size(total_size)
        )
    
    async def execute(self, plan: ActionPlan, approved_indices: list[int]) -> dict:
        """
        Execute approved temp file cleanup.
        
        Args:
            plan: The ActionPlan from analyze()
            approved_indices: List of action indices user approved
            
        Returns:
            Execution result dict
        """
        if not plan.actions:
            return {"success": [], "failed": [], "message": "No actions to execute"}
        
        success = []
        failed = []
        space_freed = 0
        
        for idx in approved_indices:
            if idx < 0 or idx >= len(plan.actions):
                continue
                
            action = plan.actions[idx]
            
            try:
                if action.type == ActionType.DELETE:
                    path = Path(action.source)
                    if path.exists():
                        # Get size before deletion
                        size = get_folder_size(path) if path.is_dir() else path.stat().st_size
                        
                        # Clean folder contents but not folder itself
                        deleted = self._clean_folder(path)
                        
                        if deleted > 0:
                            space_freed += deleted
                            success.append({
                                "action": "cleaned",
                                "path": str(path),
                                "size": format_size(deleted)
                            })
                        else:
                            failed.append({
                                "action": "clean",
                                "path": str(path),
                                "error": "No files could be deleted (may be in use)"
                            })
                    else:
                        failed.append({
                            "action": "clean",
                            "path": str(path),
                            "error": "Path no longer exists"
                        })
                        
            except Exception as e:
                failed.append({
                    "action": action.type.value,
                    "path": action.source,
                    "error": str(e)
                })
        
        return {
            "success": success,
            "failed": failed,
            "space_freed": format_size(space_freed),
            "message": f"Cleaned {len(success)} locations, freed {format_size(space_freed)}"
        }
    
    def _clean_folder(self, folder: Path) -> int:
        """
        Delete contents of a folder (not the folder itself).
        Returns bytes freed.
        """
        freed = 0
        
        if folder.is_file():
            try:
                size = folder.stat().st_size
                folder.unlink()
                return size
            except:
                return 0
        
        # Delete files and subdirectories
        for item in list(folder.iterdir()):
            try:
                if item.is_file():
                    size = item.stat().st_size
                    item.unlink()
                    freed += size
                elif item.is_dir():
                    size = get_folder_size(item)
                    shutil.rmtree(item, ignore_errors=True)
                    # Verify it's gone
                    if not item.exists():
                        freed += size
            except (PermissionError, OSError):
                # File in use or protected - skip
                pass
        
        return freed


# Register the skill
temp_cleaner = TempCleanerSkill()
register_skill(temp_cleaner)
