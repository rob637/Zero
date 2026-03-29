"""
FileOrganizer Skill - The first Apex capability

Organizes files in a folder based on user preferences:
- Clean up Downloads
- Sort by type/date
- Remove duplicates
- Archive old files

This is the flagship skill that proves the platform works.
"""

import os
import shutil
from pathlib import Path
from datetime import datetime
import json

from ..core.skill import (
    Skill, 
    ActionPlan, 
    ProposedAction, 
    ActionType,
    register_skill,
)
from ..core.llm import LLMClient, FILE_PLANNING_SYSTEM_PROMPT, create_client_from_env
from ..core.memory import memory


class FileOrganizerSkill(Skill):
    """
    Skill for organizing files in folders.
    
    Capabilities:
    - Analyze folder contents
    - Generate organization plans
    - Move, rename, delete (to Recycle Bin) files
    - Create folder structures
    """
    
    name = "file_organizer"
    description = "Organizes files in folders based on your preferences"
    version = "0.1.0"
    
    trigger_phrases = [
        "clean up",
        "organize",
        "sort files",
        "tidy",
        "declutter",
        "downloads",
        "file",
        "folder",
    ]
    
    permissions = [
        "filesystem.read",
        "filesystem.write",
    ]
    
    def __init__(self, llm_client: LLMClient = None):
        """
        Initialize FileOrganizer skill.
        
        Args:
            llm_client: LLM client to use. Defaults to auto-detected from env.
        """
        self.llm = llm_client or create_client_from_env()
        self._default_folder = self._find_user_folder("Downloads")
    
    async def analyze(self, request: str, context: dict) -> ActionPlan:
        """
        Analyze folder and generate organization plan.
        
        Args:
            request: User's request (e.g., "clean up my downloads")
            context: Additional context from memory
            
        Returns:
            ActionPlan for user approval
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
                summary="Cannot organize this location",
                reasoning=safety_msg,
                warnings=["This is a protected system folder. Choose a different location."],
            )
        
        # Scan folder
        file_list = self._scan_folder(folder)
        warnings = [safety_msg] if safety_msg else []
        
        if not file_list:
            return ActionPlan(
                summary="Folder is empty or contains only hidden files",
                reasoning="Nothing to organize.",
                warnings=warnings,
            )
        
        # Get memory context
        preferences = memory.recall("file organize preference", limit=5)
        pref_text = "\n".join([f"- {p.content}" for p in preferences]) if preferences else "None remembered."
        
        # Generate plan via LLM
        if not self.llm:
            return ActionPlan(
                summary="No LLM configured",
                reasoning="Please set ANTHROPIC_API_KEY or OPENAI_API_KEY environment variable.",
                warnings=["Cannot generate plan without LLM access."],
            )
        
        user_prompt = f"""Here are the files in {folder}:

{file_list}

User preferences from memory:
{pref_text}

User request: "{request}"

Generate a safe, well-organized plan. Output valid JSON only."""

        try:
            response = await self.llm.complete_json(
                system=FILE_PLANNING_SYSTEM_PROMPT,
                user=user_prompt,
            )
            
            return self._parse_llm_response(response, folder)
            
        except Exception as e:
            return ActionPlan(
                summary="Error generating plan",
                reasoning=f"LLM error: {str(e)}",
                warnings=["Please try again or check your API key."],
            )
    
    def _extract_folder(self, request: str) -> Path | None:
        """Extract folder path from request, if specified."""
        request_lower = request.lower()
        
        # Check for drive letters first (C:\, D:\, etc.)
        import re
        drive_match = re.search(r'([A-Za-z]):\\', request)
        if drive_match:
            # Full path provided
            path_match = re.search(r'([A-Za-z]:\\[^\s"\']*)', request)
            if path_match:
                path = Path(path_match.group(1))
                # If just "C:\" or "D:\", return the drive root
                return path
        
        # Check for OneDrive keyword
        if 'onedrive' in request_lower:
            return self._find_onedrive_folder()
        
        # Known folder names to check
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
            # Look for OneDrive folders
            for item in home.iterdir():
                if item.is_dir() and item.name.startswith('OneDrive'):
                    return item
        
        return None
    
    def _is_safe_path(self, path: Path) -> tuple[bool, str]:
        """
        Check if a path is safe to organize.
        Returns (is_safe, reason).
        """
        path_str = str(path).lower()
        
        # Dangerous system paths - NEVER touch these
        dangerous = [
            'windows', 'system32', 'syswow64', 'program files',
            'programdata', '$recycle.bin', 'recovery', 'boot',
            'drivers', 'winsxs', 'assembly'
        ]
        
        for d in dangerous:
            if d in path_str:
                return False, f"Cannot organize system folder: {d}"
        
        # Check if it's a bare drive root - warn but allow
        if len(path.parts) <= 1:
            return True, "Warning: Scanning entire drive may take a while"
        
        return True, ""
    
    def _find_user_folder(self, folder_name: str) -> Path:
        """
        Find a user folder, checking multiple possible locations.
        Handles OneDrive folder redirection on Windows.
        """
        home = Path.home()
        
        # Possible locations in order of preference
        possible_paths = [
            home / folder_name,  # Standard: C:\Users\rob\Downloads
        ]
        
        # Check OneDrive locations (Windows folder redirection)
        if os.name == 'nt':
            # Check for OneDrive folders
            for item in home.iterdir():
                if item.is_dir() and item.name.startswith('OneDrive'):
                    possible_paths.append(item / folder_name)
        
        # Return first existing path
        for path in possible_paths:
            if path.exists():
                return path
        
        # Fallback to standard path (will show "not found" error)
        return home / folder_name
    
    def _scan_folder(self, folder: Path) -> str:
        """Scan folder and return file list as string."""
        files = []
        
        try:
            for item in folder.iterdir():
                # Skip hidden files
                if item.name.startswith('.'):
                    continue
                
                try:
                    stat = item.stat()
                    size_mb = stat.st_size / (1024 * 1024)
                    modified = datetime.fromtimestamp(stat.st_mtime)
                    
                    if item.is_file():
                        files.append(
                            f"- {item.name} ({size_mb:.1f} MB, modified {modified.strftime('%Y-%m-%d')})"
                        )
                    elif item.is_dir():
                        files.append(
                            f"- {item.name}/ (folder, modified {modified.strftime('%Y-%m-%d')})"
                        )
                except (OSError, PermissionError):
                    continue
        
        except PermissionError:
            return "Error: Permission denied"
        
        # Limit to prevent token overflow
        if len(files) > 100:
            files = files[:100]
            files.append(f"... and {len(files) - 100} more files")
        
        return "\n".join(files)
    
    def _parse_llm_response(self, response: dict, folder: Path) -> ActionPlan:
        """Parse LLM JSON response into ActionPlan."""
        actions = []
        
        for action_data in response.get("actions", []):
            action_type_str = action_data.get("type", "")
            
            try:
                action_type = ActionType(action_type_str)
            except ValueError:
                continue  # Skip unknown action types
            
            actions.append(ProposedAction(
                action_type=action_type,
                source=str(folder / action_data.get("source", "")),
                destination=str(folder / action_data.get("destination", "")) if action_data.get("destination") else None,
                reason=action_data.get("reason", ""),
                risk_level="low" if action_type != ActionType.DELETE else "medium",
                reversible=True,
            ))
        
        return ActionPlan(
            summary=response.get("summary", "Plan generated"),
            reasoning=response.get("reasoning", ""),
            actions=actions,
            warnings=response.get("warnings", []),
            affected_files_count=response.get("affected_files_count", len(actions)),
            space_freed_estimate=response.get("space_freed_estimate", "Unknown"),
        )
    
    async def execute(self, plan: ActionPlan, approved_actions: list[int]) -> dict:
        """
        Execute approved actions from the plan.
        
        Args:
            plan: The action plan
            approved_actions: Indices of approved actions
            
        Returns:
            Execution results
        """
        results = {
            "success": [],
            "failed": [],
            "skipped": [],
        }
        
        for i, action in enumerate(plan.actions):
            if i not in approved_actions:
                results["skipped"].append({
                    "action": action.action_type.value,
                    "source": action.source,
                    "reason": "Not approved",
                })
                continue
            
            try:
                if action.action_type == ActionType.MOVE:
                    self._do_move(action)
                elif action.action_type == ActionType.DELETE:
                    self._do_delete(action)
                elif action.action_type == ActionType.CREATE_FOLDER:
                    self._do_create_folder(action)
                elif action.action_type == ActionType.RENAME:
                    self._do_rename(action)
                elif action.action_type == ActionType.COPY:
                    self._do_copy(action)
                
                results["success"].append({
                    "action": action.action_type.value,
                    "source": action.source,
                    "destination": action.destination,
                })
                
            except Exception as e:
                results["failed"].append({
                    "action": action.action_type.value,
                    "source": action.source,
                    "error": str(e),
                })
        
        # Remember this action in history
        memory.remember(
            f"Organized files: {plan.summary}",
            category="history",
            source="action_result",
            metadata={
                "success_count": len(results["success"]),
                "failed_count": len(results["failed"]),
            }
        )
        
        return results
    
    def _do_move(self, action: ProposedAction) -> None:
        """Execute a move action."""
        source = Path(action.source)
        dest = Path(action.destination)
        
        # Create destination directory if needed
        dest.parent.mkdir(parents=True, exist_ok=True)
        
        shutil.move(str(source), str(dest))
    
    def _do_delete(self, action: ProposedAction) -> None:
        """Execute a delete action (move to Recycle Bin)."""
        source = Path(action.source)
        
        # Use send2trash for cross-platform Recycle Bin support
        try:
            from send2trash import send2trash
            send2trash(str(source))
        except ImportError:
            # Fallback: move to a .trash folder
            trash = source.parent / ".apex_trash"
            trash.mkdir(exist_ok=True)
            shutil.move(str(source), str(trash / source.name))
    
    def _do_create_folder(self, action: ProposedAction) -> None:
        """Execute a create folder action."""
        folder = Path(action.source)
        folder.mkdir(parents=True, exist_ok=True)
    
    def _do_rename(self, action: ProposedAction) -> None:
        """Execute a rename action."""
        source = Path(action.source)
        dest = Path(action.destination)
        source.rename(dest)
    
    def _do_copy(self, action: ProposedAction) -> None:
        """Execute a copy action."""
        source = Path(action.source)
        dest = Path(action.destination)
        
        dest.parent.mkdir(parents=True, exist_ok=True)
        
        if source.is_dir():
            shutil.copytree(str(source), str(dest))
        else:
            shutil.copy2(str(source), str(dest))
    
    async def get_context(self) -> dict:
        """Get context for analysis."""
        return memory.get_context_for_skill(self.name)


# Register the skill
file_organizer = FileOrganizerSkill()
register_skill(file_organizer)
