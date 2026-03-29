"""
DuplicateFinder Skill - Find and remove duplicate files

Scans a folder (recursively) to find files with identical content
using hash comparison. Presents duplicates for user to decide which to keep.
"""

import os
import hashlib
from pathlib import Path
from collections import defaultdict
from datetime import datetime

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


def hash_file(filepath: Path, chunk_size: int = 8192) -> str:
    """Calculate MD5 hash of a file."""
    hasher = hashlib.md5()
    try:
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(chunk_size), b''):
                hasher.update(chunk)
        return hasher.hexdigest()
    except (OSError, PermissionError):
        return None


class DuplicateFinderSkill(Skill):
    """
    Skill for finding and removing duplicate files.
    
    Capabilities:
    - Scan folder recursively for duplicates
    - Hash-based comparison (identical content)
    - Group duplicates for user selection
    - Safe deletion with original preservation
    """
    
    name = "duplicate_finder"
    description = "Find and remove duplicate files to free up space"
    version = "0.1.0"
    
    trigger_phrases = [
        "duplicate",
        "duplicates",
        "find duplicate",
        "remove duplicate",
        "same file",
        "identical",
    ]
    
    permissions = [
        "filesystem.read",
        "filesystem.write",
    ]
    
    def __init__(self):
        """Initialize DuplicateFinder skill."""
        self._default_folder = self._find_user_folder("Downloads")
    
    async def analyze(self, request: str, context: dict) -> ActionPlan:
        """
        Scan folder for duplicates and generate cleanup plan.
        
        Args:
            request: User's request (e.g., "find duplicates in Downloads")
            context: Additional context
            
        Returns:
            ActionPlan with duplicate removal suggestions
        """
        # Determine target folder
        folder = self._extract_folder(request) or self._default_folder
        
        if not folder.exists():
            return ActionPlan(
                summary=f"Folder not found: {folder}",
                reasoning="The specified folder doesn't exist.",
                warnings=["Please check the folder path and try again."],
            )
        
        # Safety check
        is_safe, safety_msg = self._is_safe_path(folder)
        if not is_safe:
            return ActionPlan(
                summary="Cannot scan this location",
                reasoning=safety_msg,
                warnings=["This is a protected system folder."],
            )
        
        # Find duplicates
        duplicates, total_scanned, error_count = self._find_duplicates(folder)
        
        if not duplicates:
            return ActionPlan(
                summary=f"No duplicates found in {folder.name}",
                reasoning=f"Scanned {total_scanned} files. All files are unique.",
                warnings=[],
                affected_files_count=total_scanned,
                space_freed_estimate="0 MB"
            )
        
        # Calculate savings and build actions
        total_savings = 0
        actions = []
        
        for file_hash, file_list in duplicates.items():
            # Sort by modification time (keep oldest) and path depth
            file_list.sort(key=lambda p: (p.stat().st_mtime, len(p.parts)))
            
            # Keep first (original), suggest deleting rest
            original = file_list[0]
            duplicates_to_delete = file_list[1:]
            
            for dup in duplicates_to_delete:
                size = dup.stat().st_size
                total_savings += size
                
                actions.append(ProposedAction(
                    action_type=ActionType.DELETE,
                    source=str(dup),
                    reason=f"Duplicate of {original.name} ({format_size(size)})",
                ))
        
        return ActionPlan(
            summary=f"Found {len(actions)} duplicate files ({format_size(total_savings)} recoverable)",
            reasoning=f"Scanned {total_scanned} files. Found {len(duplicates)} groups of duplicates.",
            actions=actions,
            warnings=[
                f"Files will be moved to Recycle Bin (recoverable)",
                "Original copies (oldest) will be kept"
            ] if actions else [],
            affected_files_count=len(actions),
            space_freed_estimate=format_size(total_savings)
        )
    
    async def execute(self, plan: ActionPlan, approved_indices: list[int]) -> dict:
        """
        Execute approved duplicate deletions.
        
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
                        size = path.stat().st_size
                        # Move to trash (send2trash) or delete
                        try:
                            import send2trash
                            send2trash.send2trash(str(path))
                        except ImportError:
                            path.unlink()
                        
                        space_freed += size
                        success.append({
                            "action": "deleted",
                            "path": str(path),
                            "size": format_size(size)
                        })
                    else:
                        failed.append({
                            "action": "delete",
                            "path": str(path),
                            "error": "File no longer exists"
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
            "message": f"Deleted {len(success)} duplicate files, freed {format_size(space_freed)}"
        }
    
    def _extract_folder(self, request: str) -> Path | None:
        """Extract folder path from request."""
        request_lower = request.lower()
        
        # Check for drive letters first (C:\, D:\, etc.)
        import re
        drive_match = re.search(r'([A-Za-z]):\\', request)
        if drive_match:
            path_match = re.search(r'([A-Za-z]:\\[^\s"\']*)', request)
            if path_match:
                return Path(path_match.group(1))
        
        # Check for OneDrive keyword
        if 'onedrive' in request_lower:
            return self._find_onedrive_folder()
        
        folder_keywords = {
            "downloads": "Downloads",
            "documents": "Documents", 
            "desktop": "Desktop",
            "pictures": "Pictures",
            "videos": "Videos",
            "music": "Music",
        }
        
        for keyword, folder_name in folder_keywords.items():
            if keyword in request_lower:
                return self._find_user_folder(folder_name)
        
        return None
    
    def _find_onedrive_folder(self) -> Path | None:
        """Find the user's OneDrive folder."""
        home = Path.home()
        if os.name == 'nt':
            for item in home.iterdir():
                if item.is_dir() and item.name.startswith('OneDrive'):
                    return item
        return None
    
    def _is_safe_path(self, path: Path) -> tuple[bool, str]:
        """Check if a path is safe to scan."""
        path_str = str(path).lower()
        dangerous = ['windows', 'system32', 'syswow64', 'program files', 'programdata', '$recycle.bin']
        for d in dangerous:
            if d in path_str:
                return False, f"Cannot scan system folder: {d}"
        return True, ""
    
    def _find_user_folder(self, folder_name: str) -> Path:
        """Find a user folder, handling OneDrive redirection."""
        home = Path.home()
        
        possible_paths = [home / folder_name]
        
        if os.name == 'nt':
            for item in home.iterdir():
                if item.is_dir() and item.name.startswith('OneDrive'):
                    possible_paths.append(item / folder_name)
        
        for path in possible_paths:
            if path.exists():
                return path
        
        return home / folder_name
    
    def _find_duplicates(self, folder: Path, max_files: int = 5000) -> tuple:
        """
        Find duplicate files by hash.
        
        Returns:
            Tuple of (duplicates_dict, files_scanned, errors)
        """
        # First pass: group by file size (quick filter)
        size_groups = defaultdict(list)
        files_scanned = 0
        error_count = 0
        
        for path in self._iter_files(folder, max_files):
            try:
                size = path.stat().st_size
                # Skip tiny files (< 1KB) - not worth checking
                if size >= 1024:
                    size_groups[size].append(path)
                files_scanned += 1
            except (OSError, PermissionError):
                error_count += 1
        
        # Second pass: hash files with same size
        hash_groups = defaultdict(list)
        
        for size, paths in size_groups.items():
            if len(paths) < 2:
                continue  # No possible duplicates
            
            for path in paths:
                file_hash = hash_file(path)
                if file_hash:
                    hash_groups[(size, file_hash)].append(path)
        
        # Keep only actual duplicates
        duplicates = {
            k: v for k, v in hash_groups.items() 
            if len(v) > 1
        }
        
        return duplicates, files_scanned, error_count
    
    def _iter_files(self, folder: Path, max_files: int):
        """Iterate through files recursively."""
        count = 0
        
        try:
            for item in folder.rglob('*'):
                if count >= max_files:
                    break
                if item.is_file() and not item.name.startswith('.'):
                    yield item
                    count += 1
        except (PermissionError, OSError):
            pass


# Register the skill
duplicate_finder = DuplicateFinderSkill()
register_skill(duplicate_finder)
