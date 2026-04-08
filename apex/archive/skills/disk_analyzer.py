"""
Disk Analyzer Skill - Visualize disk usage and find space hogs

Capabilities:
- Analyze disk/folder usage
- Find largest files and folders
- Identify old/unused files
- Detect common space wasters

Helps users understand where their storage is going.
"""

import os
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

from ..core.skill import (
    Skill, 
    ActionPlan, 
    ProposedAction, 
    ActionType,
    register_skill,
)


# Common space wasters
SPACE_WASTER_PATTERNS = [
    # Build artifacts
    'node_modules', '__pycache__', '.cache', 'dist', 'build',
    '.gradle', '.maven', 'target', '.tox', 'venv', '.venv',
    # IDE
    '.idea', '.vs', '.vscode',
    # System
    '$RECYCLE.BIN', 'Thumbs.db', 
]


def format_size(bytes: int) -> str:
    """Format bytes as human-readable size."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes < 1024:
            return f"{bytes:.1f} {unit}"
        bytes /= 1024
    return f"{bytes:.1f} PB"


class DiskAnalyzerSkill(Skill):
    """
    Skill for analyzing disk usage and finding space hogs.
    
    Can:
    - Show disk usage breakdown
    - Find largest files/folders
    - Identify old files not accessed in years
    - Find common space wasters (node_modules, caches, etc.)
    """
    
    name = "disk_analyzer"
    description = "Analyze disk usage, find large files and space wasters"
    version = "0.1.0"
    
    trigger_phrases = [
        "disk",
        "storage",
        "space",
        "largest",
        "biggest",
        "what's taking",
        "analyze",
        "usage",
        "free up",
        "running out",
    ]
    
    permissions = [
        "filesystem.read",
    ]
    
    async def analyze(self, request: str, context: dict) -> ActionPlan:
        """
        Analyze disk usage request.
        """
        request_lower = request.lower()
        
        # Determine target
        target_folder = Path.home()
        analysis_depth = 2
        
        # Check for specific targets
        if 'download' in request_lower:
            target_folder = Path.home() / 'Downloads'
        elif 'desktop' in request_lower:
            target_folder = Path.home() / 'Desktop'
        elif 'document' in request_lower:
            target_folder = Path.home() / 'Documents'
        elif context.get('target'):
            target = context['target']
            if Path(target).exists():
                target_folder = Path(target)
        
        # Run analysis
        analysis = self._analyze_folder(target_folder, depth=analysis_depth)
        
        # Build summary
        total_size = analysis['total_size']
        largest_files = analysis['largest_files'][:10]  # Top 10
        largest_folders = analysis['largest_folders'][:10]
        old_files = analysis['old_files'][:10]
        space_wasters = analysis['space_wasters']
        
        # Build the report as actions (read-only, for display)
        actions = []
        
        # Space wasters that can be cleaned
        for waster in space_wasters:
            actions.append(ProposedAction(
                action_type=ActionType.DELETE,
                source=str(waster['path']),
                destination="",
                reason=f"Space waster ({waster['type']}): {format_size(waster['size'])}",
            ))
        
        # Old files that might be deletable
        for old_file in old_files:
            actions.append(ProposedAction(
                action_type=ActionType.DELETE,
                source=str(old_file['path']),
                destination="",
                reason=f"Old file (not accessed since {old_file['last_access']}): {format_size(old_file['size'])}",
            ))
        
        # Build detailed summary
        summary_lines = [
            f"Analyzed: {target_folder}",
            f"Total size: {format_size(total_size)}",
            "",
            "**Largest Files:**",
        ]
        
        for f in largest_files[:5]:
            summary_lines.append(f"  - {f['name']}: {format_size(f['size'])}")
        
        if largest_folders:
            summary_lines.append("")
            summary_lines.append("**Largest Folders:**")
            for f in largest_folders[:5]:
                summary_lines.append(f"  - {f['name']}: {format_size(f['size'])}")
        
        if space_wasters:
            summary_lines.append("")
            summary_lines.append(f"**Found {len(space_wasters)} space wasters** (caches, build folders, etc.)")
            total_waster_size = sum(w['size'] for w in space_wasters)
            summary_lines.append(f"  Could free up: {format_size(total_waster_size)}")
        
        return ActionPlan(
            summary=f"Disk analysis of {target_folder.name}",
            reasoning="\n".join(summary_lines),
            actions=actions,
            warnings=[
                "Review each item before deleting - some may be needed",
                "Build folders like node_modules can be reinstalled",
            ] if actions else [],
        )
    
    async def execute(self, plan: ActionPlan, approved_indices: list[int]) -> dict:
        """
        Execute approved cleanup actions.
        """
        import shutil
        
        success = []
        failed = []
        total_freed = 0
        
        for i in approved_indices:
            if i >= len(plan.actions):
                continue
                
            action = plan.actions[i]
            path = Path(action.source)
            
            try:
                if not path.exists():
                    failed.append({
                        "action": "delete",
                        "path": action.source,
                        "error": "Path not found"
                    })
                    continue
                
                # Get size before deletion
                if path.is_file():
                    size = path.stat().st_size
                    path.unlink()
                else:
                    size = self._get_folder_size(path)
                    shutil.rmtree(path)
                
                total_freed += size
                success.append({
                    "action": "deleted",
                    "path": action.source,
                    "freed": format_size(size)
                })
                
            except Exception as e:
                failed.append({
                    "action": "delete",
                    "path": action.source,
                    "error": str(e)
                })
        
        return {
            "success": success,
            "failed": failed,
            "total_freed": format_size(total_freed),
            "message": f"Freed {format_size(total_freed)} from {len(success)} items"
        }
    
    def _analyze_folder(self, folder: Path, depth: int = 2) -> dict:
        """Analyze a folder's contents."""
        total_size = 0
        files = []
        folders = []
        old_files = []
        space_wasters = []
        
        # Cutoff for "old" files (2 years)
        old_cutoff = datetime.now() - timedelta(days=730)
        
        def scan(path: Path, current_depth: int) -> int:
            nonlocal total_size
            
            if current_depth > depth:
                return 0
            
            folder_size = 0
            
            try:
                for item in path.iterdir():
                    try:
                        if item.is_file():
                            size = item.stat().st_size
                            folder_size += size
                            total_size += size
                            
                            files.append({
                                'path': item,
                                'name': item.name,
                                'size': size,
                            })
                            
                            # Check if old
                            try:
                                atime = datetime.fromtimestamp(item.stat().st_atime)
                                if atime < old_cutoff and size > 10 * 1024 * 1024:  # >10MB
                                    old_files.append({
                                        'path': item,
                                        'name': item.name,
                                        'size': size,
                                        'last_access': atime.strftime('%Y-%m-%d'),
                                    })
                            except:
                                pass
                        
                        elif item.is_dir():
                            # Check for space wasters
                            if item.name in SPACE_WASTER_PATTERNS:
                                waster_size = self._get_folder_size(item)
                                if waster_size > 50 * 1024 * 1024:  # >50MB
                                    space_wasters.append({
                                        'path': item,
                                        'type': item.name,
                                        'size': waster_size,
                                    })
                                folder_size += waster_size
                                total_size += waster_size
                            else:
                                sub_size = scan(item, current_depth + 1)
                                folder_size += sub_size
                                
                                if current_depth < depth:
                                    folders.append({
                                        'path': item,
                                        'name': item.name,
                                        'size': sub_size,
                                    })
                    except PermissionError:
                        pass
                    except Exception:
                        pass
            except PermissionError:
                pass
            
            return folder_size
        
        scan(folder, 0)
        
        # Sort by size
        files.sort(key=lambda x: x['size'], reverse=True)
        folders.sort(key=lambda x: x['size'], reverse=True)
        old_files.sort(key=lambda x: x['size'], reverse=True)
        space_wasters.sort(key=lambda x: x['size'], reverse=True)
        
        return {
            'total_size': total_size,
            'largest_files': files,
            'largest_folders': folders,
            'old_files': old_files,
            'space_wasters': space_wasters,
        }
    
    def _get_folder_size(self, folder: Path) -> int:
        """Get total size of a folder."""
        total = 0
        try:
            for item in folder.rglob('*'):
                if item.is_file():
                    try:
                        total += item.stat().st_size
                    except:
                        pass
        except:
            pass
        return total


# Register the skill
disk_analyzer = DiskAnalyzerSkill()
register_skill(disk_analyzer)
