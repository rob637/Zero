"""Telic Engine — System & Utility Primitives"""

import asyncio
import hashlib
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from .base import Primitive, StepResult

logger = logging.getLogger(__name__)


class FilePrimitive(Primitive):
    """File system operations."""
    
    def __init__(self, allowed_roots: Optional[List[str]] = None):
        import tempfile
        # If no explicit restrictions, allow the user's entire home tree
        # The LLM decides WHERE to search - we just execute
        self._allowed = allowed_roots or [
            str(Path.home()),
            tempfile.gettempdir(),
        ]
        # On Windows, also allow the drives where home lives
        home = Path.home()
        if hasattr(home, 'drive') and home.drive:
            self._allowed.append(home.drive + "\\")
    
    @property
    def name(self) -> str:
        return "FILE"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "search": "Search for files matching pattern",
            "read": "Read file contents",
            "write": "Write content to file",
            "list": "List directory contents",
            "info": "Get file metadata",
            "exists": "Check if file exists",
            "checksum": "Calculate hash/checksum of a file (for duplicate detection)",
            "move": "Move a file to a new location",
            "copy": "Copy a file to a new location",
            "delete": "Delete a file (moves to trash if available)",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "search": {
                "pattern": {"type": "str", "required": True, "description": "Glob pattern (e.g. '*.pdf', '*.docx')"},
                "directory": {"type": "str", "required": False, "description": "Directory to search (default: home)"},
                "recursive": {"type": "bool", "required": False, "description": "Search subdirectories (default true)"},
                "limit": {"type": "int", "required": False, "description": "Max results (default 50)"},
            },
            "read": {
                "path": {"type": "str", "required": True, "description": "File path to read"},
            },
            "write": {
                "path": {"type": "str", "required": True, "description": "File path to write"},
                "content": {"type": "str", "required": True, "description": "Content to write"},
            },
            "list": {
                "directory": {"type": "str", "required": True, "description": "Directory to list"},
            },
            "info": {
                "path": {"type": "str", "required": True, "description": "File path"},
            },
            "exists": {
                "path": {"type": "str", "required": True, "description": "File path to check"},
            },
            "checksum": {
                "path": {"type": "str", "required": True, "description": "File path to hash"},
                "algorithm": {"type": "str", "required": False, "description": "Hash algorithm: md5, sha1, sha256 (default: md5)"},
            },
            "move": {
                "source": {"type": "str", "required": True, "description": "Source file path"},
                "destination": {"type": "str", "required": True, "description": "Destination path"},
            },
            "copy": {
                "source": {"type": "str", "required": True, "description": "Source file path"},
                "destination": {"type": "str", "required": True, "description": "Destination path"},
            },
            "delete": {
                "path": {"type": "str", "required": True, "description": "File path to delete"},
                "permanent": {"type": "bool", "required": False, "description": "Permanently delete (skip trash, default: false)"},
            },
        }
    
    def _is_allowed(self, path: str) -> bool:
        resolved = str(Path(path).expanduser().resolve())
        return any(resolved.startswith(str(Path(a).expanduser().resolve())) for a in self._allowed)
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            if operation == "search":
                pattern = params.get("pattern", "*")
                directory = params.get("directory", str(Path.home()))
                directory = str(Path(directory).expanduser())
                recursive = params.get("recursive", True)
                limit = params.get("limit", 5000)
                
                if not self._is_allowed(directory):
                    return StepResult(False, error=f"Directory not allowed: {directory}")
                
                base = Path(directory)
                if not base.exists():
                    return StepResult(False, error=f"Directory not found: {directory}")
                
                matches = []
                glob_func = base.rglob if recursive else base.glob
                for p in glob_func(pattern):
                    if len(matches) >= limit:
                        break
                    matches.append({
                        "path": str(p),
                        "name": p.name,
                        "is_dir": p.is_dir(),
                        "size": p.stat().st_size if p.is_file() else 0,
                    })
                
                return StepResult(True, data=matches)
            
            elif operation == "read":
                path = str(Path(params.get("path", "")).expanduser())
                if not self._is_allowed(path):
                    return StepResult(False, error=f"Path not allowed: {path}")
                
                if not Path(path).exists():
                    return StepResult(False, error=f"File not found: {path}")
                
                with open(path, "r", errors="ignore") as f:
                    content = f.read()
                
                return StepResult(True, data=content)
            
            elif operation == "write":
                path = str(Path(params.get("path", "")).expanduser())
                content = params.get("content", "")
                
                if not self._is_allowed(path):
                    return StepResult(False, error=f"Path not allowed: {path}")
                
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                with open(path, "w") as f:
                    f.write(content)
                
                return StepResult(True, data={"path": path, "size": len(content)})
            
            elif operation == "list":
                directory = str(Path(params.get("directory", "")).expanduser())
                
                if not self._is_allowed(directory):
                    return StepResult(False, error=f"Directory not allowed: {directory}")
                
                base = Path(directory)
                if not base.exists():
                    return StepResult(False, error=f"Directory not found: {directory}")
                
                items = []
                for p in base.iterdir():
                    items.append({
                        "path": str(p),
                        "name": p.name,
                        "is_dir": p.is_dir(),
                        "size": p.stat().st_size if p.is_file() else 0,
                    })
                
                return StepResult(True, data=items)
            
            elif operation == "info":
                path = str(Path(params.get("path", "")).expanduser())
                if not self._is_allowed(path):
                    return StepResult(False, error=f"Path not allowed: {path}")
                
                p = Path(path)
                if not p.exists():
                    return StepResult(False, error=f"File not found: {path}")
                
                stat = p.stat()
                return StepResult(True, data={
                    "path": str(p),
                    "name": p.name,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "is_dir": p.is_dir(),
                    "extension": p.suffix,
                })
            
            elif operation == "exists":
                path = str(Path(params.get("path", "")).expanduser())
                return StepResult(True, data={"exists": Path(path).exists(), "path": path})
            
            elif operation == "checksum":
                import hashlib
                path = str(Path(params.get("path", "")).expanduser())
                algorithm = params.get("algorithm", "md5").lower()
                
                if not self._is_allowed(path):
                    return StepResult(False, error=f"Path not allowed: {path}")
                if not Path(path).exists():
                    return StepResult(False, error=f"File not found: {path}")
                if Path(path).is_dir():
                    return StepResult(False, error="Cannot hash a directory")
                
                hash_funcs = {"md5": hashlib.md5, "sha1": hashlib.sha1, "sha256": hashlib.sha256}
                if algorithm not in hash_funcs:
                    return StepResult(False, error=f"Unsupported algorithm: {algorithm}. Use md5, sha1, or sha256.")
                
                hasher = hash_funcs[algorithm]()
                with open(path, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        hasher.update(chunk)
                
                return StepResult(True, data={
                    "path": path,
                    "algorithm": algorithm,
                    "checksum": hasher.hexdigest(),
                    "size": Path(path).stat().st_size,
                })
            
            elif operation == "move":
                import shutil
                source = str(Path(params.get("source", "")).expanduser())
                destination = str(Path(params.get("destination", "")).expanduser())
                
                if not self._is_allowed(source):
                    return StepResult(False, error=f"Source not allowed: {source}")
                if not self._is_allowed(destination):
                    return StepResult(False, error=f"Destination not allowed: {destination}")
                if not Path(source).exists():
                    return StepResult(False, error=f"Source not found: {source}")
                
                Path(destination).parent.mkdir(parents=True, exist_ok=True)
                shutil.move(source, destination)
                
                return StepResult(True, data={"source": source, "destination": destination})
            
            elif operation == "copy":
                import shutil
                source = str(Path(params.get("source", "")).expanduser())
                destination = str(Path(params.get("destination", "")).expanduser())
                
                if not self._is_allowed(source):
                    return StepResult(False, error=f"Source not allowed: {source}")
                if not self._is_allowed(destination):
                    return StepResult(False, error=f"Destination not allowed: {destination}")
                if not Path(source).exists():
                    return StepResult(False, error=f"Source not found: {source}")
                
                Path(destination).parent.mkdir(parents=True, exist_ok=True)
                if Path(source).is_dir():
                    shutil.copytree(source, destination)
                else:
                    shutil.copy2(source, destination)
                
                return StepResult(True, data={"source": source, "destination": destination})
            
            elif operation == "delete":
                import shutil
                path = str(Path(params.get("path", "")).expanduser())
                permanent = params.get("permanent", False)
                
                if not self._is_allowed(path):
                    return StepResult(False, error=f"Path not allowed: {path}")
                if not Path(path).exists():
                    return StepResult(False, error=f"File not found: {path}")
                
                if permanent:
                    if Path(path).is_dir():
                        shutil.rmtree(path)
                    else:
                        Path(path).unlink()
                    return StepResult(True, data={"path": path, "deleted": True, "permanent": True})
                else:
                    # Try to move to trash
                    try:
                        from send2trash import send2trash
                        send2trash(path)
                        return StepResult(True, data={"path": path, "deleted": True, "permanent": False, "location": "trash"})
                    except ImportError:
                        # Fallback to permanent delete
                        if Path(path).is_dir():
                            shutil.rmtree(path)
                        else:
                            Path(path).unlink()
                        return StepResult(True, data={"path": path, "deleted": True, "permanent": True, "note": "Install send2trash for trash support"})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
                
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  DOCUMENT PRIMITIVE  
# ============================================================



class ShellPrimitive(Primitive):
    """Execute system commands in a controlled sandbox.
    
    Restricted by default — only allows safe commands.
    The allow list can be expanded per deployment.
    """
    
    def __init__(self, allowed_commands: Optional[List[str]] = None):
        # Default safe commands — no rm, no sudo, no curl piping to bash
        self._allowed = set(allowed_commands or [
            "ls", "dir", "cat", "head", "tail", "wc", "grep", "find",
            "echo", "date", "whoami", "hostname", "pwd", "df", "du",
            "sort", "uniq", "cut", "awk", "sed", "tr", "tee",
            "python", "python3", "node", "pip", "npm",
            "git",
        ])
    
    @property
    def name(self) -> str:
        return "SHELL"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "run": "Run a shell command and return its output",
            "script": "Run a multi-line script (bash)",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "run": {
                "command": {"type": "str", "required": True, "description": "Shell command to execute"},
                "cwd": {"type": "str", "required": False, "description": "Working directory"},
                "timeout": {"type": "int", "required": False, "description": "Timeout in seconds (default 30)"},
            },
            "script": {
                "code": {"type": "str", "required": True, "description": "Bash script content"},
                "cwd": {"type": "str", "required": False, "description": "Working directory"},
                "timeout": {"type": "int", "required": False, "description": "Timeout in seconds (default 30)"},
            },
        }
    
    def _check_command(self, cmd: str) -> Optional[str]:
        """Check if command is allowed. Returns error string or None."""
        # Extract the base command (first word, ignore pipes for now)
        parts = cmd.strip().split()
        if not parts:
            return "Empty command"
        base = parts[0].split("/")[-1]  # Handle /usr/bin/python etc.
        
        # Block dangerous patterns regardless of command
        dangerous = ["rm -rf /", "mkfs", "dd if=", "> /dev/", ":(){ :|:", "fork bomb"]
        for d in dangerous:
            if d in cmd:
                return f"Blocked dangerous pattern: {d}"
        
        if base not in self._allowed:
            return f"Command '{base}' not in allow list. Allowed: {', '.join(sorted(self._allowed))}"
        return None
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        import subprocess
        
        try:
            if operation == "run":
                cmd = params.get("command", "")
                cwd = params.get("cwd")
                timeout = params.get("timeout", 30)
                
                if not cmd:
                    return StepResult(False, error="Missing 'command' parameter")
                
                err = self._check_command(cmd)
                if err:
                    return StepResult(False, error=err)
                
                if cwd:
                    cwd = str(Path(cwd).expanduser())
                
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=cwd,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                
                return StepResult(True, data={
                    "stdout": stdout.decode("utf-8", errors="ignore")[:50000],
                    "stderr": stderr.decode("utf-8", errors="ignore")[:10000],
                    "exit_code": proc.returncode,
                })
            
            elif operation == "script":
                code = params.get("code", "")
                cwd = params.get("cwd")
                timeout = params.get("timeout", 30)
                
                if not code:
                    return StepResult(False, error="Missing 'code' parameter")
                
                # Check each line of the script
                for line in code.strip().split("\n"):
                    line = line.strip()
                    if line and not line.startswith("#"):
                        err = self._check_command(line)
                        if err:
                            return StepResult(False, error=f"Line blocked: {err}")
                
                if cwd:
                    cwd = str(Path(cwd).expanduser())
                
                proc = await asyncio.create_subprocess_exec(
                    "bash", "-c", code,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=cwd,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                
                return StepResult(True, data={
                    "stdout": stdout.decode("utf-8", errors="ignore")[:50000],
                    "stderr": stderr.decode("utf-8", errors="ignore")[:10000],
                    "exit_code": proc.returncode,
                })
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except asyncio.TimeoutError:
            return StepResult(False, error=f"Command timed out after {params.get('timeout', 30)}s")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  DATA PRIMITIVE
# ============================================================



class ClipboardPrimitive(Primitive):
    """System clipboard operations — copy, paste, history.
    
    Works cross-platform via pyperclip when available.
    """
    
    def __init__(self):
        self._history: List[Dict] = []
        self._max_history = 50
    
    @property
    def name(self) -> str:
        return "CLIPBOARD"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "copy": "Copy text to the system clipboard",
            "paste": "Get the current clipboard contents",
            "history": "Get recent clipboard history",
            "clear": "Clear the clipboard",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "copy": {
                "text": {"type": "str", "required": True, "description": "Text to copy to clipboard"},
            },
            "paste": {},
            "history": {
                "limit": {"type": "int", "required": False, "description": "Max items to return (default 10)"},
            },
            "clear": {},
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            # Try to use pyperclip for real clipboard access
            try:
                import pyperclip
                has_pyperclip = True
            except ImportError:
                has_pyperclip = False
            
            if operation == "copy":
                text = params.get("text", "")
                if not text:
                    return StepResult(False, error="Missing 'text' parameter")
                
                if has_pyperclip:
                    pyperclip.copy(text)
                
                # Store in history
                self._history.insert(0, {
                    "text": text[:500],
                    "timestamp": datetime.now().isoformat(),
                    "length": len(text),
                })
                if len(self._history) > self._max_history:
                    self._history = self._history[:self._max_history]
                
                return StepResult(True, data={"copied": True, "length": len(text)})
            
            elif operation == "paste":
                if has_pyperclip:
                    text = pyperclip.paste()
                    return StepResult(True, data={"text": text, "length": len(text)})
                elif self._history:
                    return StepResult(True, data={"text": self._history[0]["text"], "length": self._history[0]["length"]})
                return StepResult(True, data={"text": "", "length": 0})
            
            elif operation == "history":
                limit = params.get("limit", 10)
                return StepResult(True, data=self._history[:limit])
            
            elif operation == "clear":
                if has_pyperclip:
                    pyperclip.copy("")
                return StepResult(True, data={"cleared": True})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  TRANSLATE PRIMITIVE
# ============================================================



class ScreenshotPrimitive(Primitive):
    """System-level screenshots — full screen, window, region.
    
    Uses mss or pillow for capture.
    """
    
    def __init__(self):
        self._default_path = str(Path.home() / "Screenshots")
    
    @property
    def name(self) -> str:
        return "SCREENSHOT"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "capture": "Take a screenshot of the entire screen or a region",
            "window": "Take a screenshot of a specific window",
            "list": "List recently taken screenshots",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "capture": {
                "path": {"type": "str", "required": False, "description": "Save path (default: ~/Screenshots/screenshot_<timestamp>.png)"},
                "region": {"type": "dict", "required": False, "description": "Region to capture: {x, y, width, height}"},
                "monitor": {"type": "int", "required": False, "description": "Monitor number (default: all monitors)"},
            },
            "window": {
                "title": {"type": "str", "required": True, "description": "Window title (partial match)"},
                "path": {"type": "str", "required": False, "description": "Save path"},
            },
            "list": {
                "limit": {"type": "int", "required": False, "description": "Max screenshots to return (default 10)"},
            },
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            if operation == "capture":
                path = params.get("path")
                region = params.get("region")
                monitor = params.get("monitor")
                
                # Ensure screenshots directory exists
                Path(self._default_path).mkdir(parents=True, exist_ok=True)
                
                if not path:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    path = str(Path(self._default_path) / f"screenshot_{timestamp}.png")
                else:
                    path = str(Path(path).expanduser())
                
                try:
                    import mss
                    with mss.mss() as sct:
                        if region:
                            monitor_area = {"left": region.get("x", 0), "top": region.get("y", 0), 
                                          "width": region.get("width", 800), "height": region.get("height", 600)}
                            screenshot = sct.grab(monitor_area)
                        elif monitor:
                            screenshot = sct.grab(sct.monitors[monitor])
                        else:
                            screenshot = sct.grab(sct.monitors[0])  # Primary monitor
                        
                        mss.tools.to_png(screenshot.rgb, screenshot.size, output=path)
                    
                    return StepResult(True, data={"path": path, "size": Path(path).stat().st_size})
                except ImportError:
                    return StepResult(False, error="Install mss for screenshots: pip install mss")
            
            elif operation == "window":
                title = params.get("title", "")
                path = params.get("path")
                
                if not title:
                    return StepResult(False, error="Missing 'title' parameter")
                
                # Window screenshots require platform-specific code
                return StepResult(False, error="Window screenshots not yet implemented. Use capture() with a region instead.")
            
            elif operation == "list":
                limit = params.get("limit", 10)
                
                screenshots_dir = Path(self._default_path)
                if not screenshots_dir.exists():
                    return StepResult(True, data=[])
                
                files = sorted(
                    [f for f in screenshots_dir.iterdir() if f.suffix.lower() in (".png", ".jpg", ".jpeg")],
                    key=lambda f: f.stat().st_mtime,
                    reverse=True,
                )[:limit]
                
                return StepResult(True, data=[
                    {"path": str(f), "name": f.name, "size": f.stat().st_size, 
                     "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat()}
                    for f in files
                ])
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  AUTOMATION PRIMITIVE
# ============================================================



class AutomationPrimitive(Primitive):
    """Task automation — schedules, recurring jobs, workflows.
    
    Stores automation rules locally. In production, would integrate with
    system schedulers (cron, Task Scheduler, etc.)
    """
    
    def __init__(self, storage_path: Optional[str] = None):
        self._storage_path = storage_path or str(Path.home() / ".telic" / "automations.json")
        self._automations: List[Dict] = []
        self._load()
    
    def _load(self):
        if Path(self._storage_path).exists():
            try:
                with open(self._storage_path, "r") as f:
                    self._automations = json.load(f)
            except Exception:
                self._automations = []
    
    def _save(self):
        Path(self._storage_path).parent.mkdir(parents=True, exist_ok=True)
        with open(self._storage_path, "w") as f:
            json.dump(self._automations, f, indent=2)
    
    @property
    def name(self) -> str:
        return "AUTOMATION"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "create": "Create a new automation rule",
            "list": "List all automation rules",
            "enable": "Enable a disabled automation",
            "disable": "Disable an automation without deleting it",
            "delete": "Delete an automation rule",
            "run": "Manually trigger an automation",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "create": {
                "name": {"type": "str", "required": True, "description": "Automation name"},
                "trigger": {"type": "str", "required": True, "description": "Trigger type: schedule, event, webhook"},
                "schedule": {"type": "str", "required": False, "description": "Cron expression or natural language (e.g. 'every monday at 9am')"},
                "action": {"type": "str", "required": True, "description": "Action to perform (natural language task description)"},
                "enabled": {"type": "bool", "required": False, "description": "Whether automation is active (default true)"},
            },
            "list": {
                "status": {"type": "str", "required": False, "description": "Filter: enabled, disabled, all (default all)"},
            },
            "enable": {
                "id": {"type": "str", "required": True, "description": "Automation ID to enable"},
            },
            "disable": {
                "id": {"type": "str", "required": True, "description": "Automation ID to disable"},
            },
            "delete": {
                "id": {"type": "str", "required": True, "description": "Automation ID to delete"},
            },
            "run": {
                "id": {"type": "str", "required": True, "description": "Automation ID to run"},
            },
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            if operation == "create":
                name = params.get("name", "")
                trigger = params.get("trigger", "schedule")
                schedule = params.get("schedule", "")
                action = params.get("action", "")
                enabled = params.get("enabled", True)
                
                if not name or not action:
                    return StepResult(False, error="Missing 'name' and/or 'action' parameter")
                
                automation = {
                    "id": f"auto_{len(self._automations)}_{int(datetime.now().timestamp())}",
                    "name": name,
                    "trigger": trigger,
                    "schedule": schedule,
                    "action": action,
                    "enabled": enabled,
                    "created": datetime.now().isoformat(),
                    "last_run": None,
                    "run_count": 0,
                }
                self._automations.append(automation)
                self._save()
                
                return StepResult(True, data=automation)
            
            elif operation == "list":
                status = params.get("status", "all")
                if status == "enabled":
                    items = [a for a in self._automations if a.get("enabled", True)]
                elif status == "disabled":
                    items = [a for a in self._automations if not a.get("enabled", True)]
                else:
                    items = self._automations
                return StepResult(True, data=items)
            
            elif operation == "enable":
                auto_id = params.get("id", "")
                for a in self._automations:
                    if a["id"] == auto_id:
                        a["enabled"] = True
                        self._save()
                        return StepResult(True, data=a)
                return StepResult(False, error=f"Automation not found: {auto_id}")
            
            elif operation == "disable":
                auto_id = params.get("id", "")
                for a in self._automations:
                    if a["id"] == auto_id:
                        a["enabled"] = False
                        self._save()
                        return StepResult(True, data=a)
                return StepResult(False, error=f"Automation not found: {auto_id}")
            
            elif operation == "delete":
                auto_id = params.get("id", "")
                for i, a in enumerate(self._automations):
                    if a["id"] == auto_id:
                        deleted = self._automations.pop(i)
                        self._save()
                        return StepResult(True, data={"deleted": deleted["name"]})
                return StepResult(False, error=f"Automation not found: {auto_id}")
            
            elif operation == "run":
                auto_id = params.get("id", "")
                for a in self._automations:
                    if a["id"] == auto_id:
                        a["last_run"] = datetime.now().isoformat()
                        a["run_count"] = a.get("run_count", 0) + 1
                        self._save()
                        # In production, this would trigger the actual action
                        return StepResult(True, data={
                            "triggered": a["name"],
                            "action": a["action"],
                            "status": "queued",
                        })
                return StepResult(False, error=f"Automation not found: {auto_id}")
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  SEARCH PRIMITIVE
# ============================================================



class SearchPrimitive(Primitive):
    """Universal search — searches across all available primitives AND the semantic index.
    
    Two modes:
      - 'all': Dynamically searches across all primitives with a 'search' operation
      - 'semantic': Cross-service semantic search using vector embeddings
        Finds things like "that budget spreadsheet John mentioned" across email, calendar, drive, etc.
    """
    
    def __init__(self, primitives: Optional[Dict[str, 'Primitive']] = None):
        self._primitives = primitives or {}
    
    def set_primitives(self, primitives: Dict[str, 'Primitive']):
        """Set the primitives dict after construction (for circular dependency)."""
        self._primitives = primitives
    
    @property
    def name(self) -> str:
        return "SEARCH"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "all": "Search across all available sources (files, email, calendar, tasks, contacts, messages, etc.)",
            "semantic": "Cross-service semantic search using AI — finds things by meaning, not just keywords. "
                        "Use for vague queries like 'that thing John mentioned about the budget' or "
                        "'the spreadsheet from last week'. Searches across ALL services at once.",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "all": {
                "query": {"type": "str", "required": True, "description": "Search query"},
                "limit": {"type": "int", "required": False, "description": "Max results per source (default 5)"},
            },
            "semantic": {
                "query": {"type": "str", "required": True, "description": "Natural language search query — can be vague or descriptive"},
                "kind": {"type": "str", "required": False, "description": "Filter by type: event, email, contact, task, file, message, note, document"},
                "limit": {"type": "int", "required": False, "description": "Max results (default 10)"},
            },
        }
    
    def _find_searchable(self) -> Dict[str, tuple]:
        """Discover all primitives that support search/recall operations."""
        searchable = {}
        for name, prim in self._primitives.items():
            if name == "SEARCH":
                continue  # Don't recurse into ourselves
            ops = prim.get_operations()
            if "search" in ops:
                searchable[name.lower()] = (prim, "search")
            elif "recall" in ops:
                searchable[name.lower()] = (prim, "recall")
        return searchable
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            query = params.get("query", "")
            
            if not query:
                return StepResult(False, error="Missing 'query' parameter")
            
            if operation == "semantic":
                return await self._execute_semantic(params)
            
            elif operation == "all":
                limit = params.get("limit", 5)
                results = {"query": query, "sources": {}}
                searchable = self._find_searchable()
                
                for source_name, (prim, op) in searchable.items():
                    try:
                        result = await prim.execute(op, {"query": query, "limit": limit})
                        if result.success and result.data:
                            results["sources"][source_name] = result.data
                    except Exception:
                        pass
                
                return StepResult(True, data=results)
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))
    
    async def _execute_semantic(self, params: Dict[str, Any]) -> StepResult:
        """Cross-service semantic search using vector embeddings."""
        query = params["query"]
        kind = params.get("kind")
        limit = params.get("limit", 10)
        
        # Get semantic search from global
        ss = _get_semantic_search()
        if not ss or not ss.ready:
            # Fall back to the 'all' operation if semantic search isn't available
            return await self.execute("all", params)
        
        results = await ss.search(query, kind=kind, limit=limit)
        
        if not results:
            return StepResult(True, data={
                "query": query,
                "count": 0,
                "results": [],
                "note": "No semantic matches found. Try the 'all' search for keyword-based results.",
            })
        
        formatted = []
        for obj, score in results:
            item = {
                "kind": obj.kind.value,
                "source": obj.source,
                "title": obj.title,
                "relevance": f"{score:.0%}",
            }
            if obj.body:
                item["preview"] = obj.body[:300]
            if obj.timestamp:
                item["date"] = obj.timestamp.isoformat()
            if obj.participants:
                item["participants"] = obj.participants[:5]
            if obj.url:
                item["url"] = obj.url
            if obj.location:
                item["location"] = obj.location
            formatted.append(item)
        
        return StepResult(True, data={
            "query": query,
            "count": len(formatted),
            "results": formatted,
        })


# Global accessor for semantic search (set from server.py startup)
_semantic_search_instance = None

def set_semantic_search(ss):
    global _semantic_search_instance
    _semantic_search_instance = ss

def _get_semantic_search():
    return _semantic_search_instance


# CHAT primitive removed — duplicates MESSAGE (same providers: Slack, Teams, Discord)
# MEETING primitive removed — duplicates ZOOM (which has real Zoom API integration)


# ============================================================
#  SMS PRIMITIVE - Text messaging
# ============================================================



class NotifyPrimitive(Primitive):
    """Notifications, reminders, and alerts.
    
    Stores reminders locally. Can be wired to push notifications,
    desktop alerts, Slack, etc. via provider functions.
    """
    
    def __init__(
        self,
        storage_path: Optional[str] = None,
        send_func: Optional[Callable] = None,
    ):
        self._reminders: List[Dict] = []
        self._storage_path = storage_path
        self._send_func = send_func
        if storage_path and Path(storage_path).exists():
            try:
                with open(storage_path, "r") as f:
                    self._reminders = json.load(f)
            except Exception:
                pass
    
    @property
    def name(self) -> str:
        return "NOTIFY"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "alert": "Show an immediate notification/alert to the user",
            "remind": "Set a reminder for a specific time",
            "list": "List pending reminders",
            "cancel": "Cancel a pending reminder",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "alert": {
                "title": {"type": "str", "required": True, "description": "Alert title"},
                "message": {"type": "str", "required": True, "description": "Alert message"},
                "urgency": {"type": "str", "required": False, "description": "low, normal, or high (default normal)"},
            },
            "remind": {
                "message": {"type": "str", "required": True, "description": "Reminder message"},
                "when": {"type": "str", "required": True, "description": "When to remind (ISO datetime or relative like 'in 30 minutes', 'tomorrow 9am')"},
                "repeat": {"type": "str", "required": False, "description": "Repeat interval: daily, weekly, monthly, or none"},
            },
            "list": {
                "status": {"type": "str", "required": False, "description": "Filter: pending, triggered, all (default pending)"},
            },
            "cancel": {
                "id": {"type": "str", "required": True, "description": "Reminder ID to cancel"},
            },
        }
    
    def _save(self):
        if self._storage_path:
            Path(self._storage_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self._storage_path, "w") as f:
                json.dump(self._reminders, f, indent=2)
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            if operation == "alert":
                title = params.get("title", "Alert")
                message = params.get("message", "")
                urgency = params.get("urgency", "normal")
                
                if self._send_func:
                    result = await self._send_func(title=title, message=message, urgency=urgency)
                    return StepResult(True, data=result)
                
                # Local-only: store and return (UI layer polls/reads these)
                alert = {
                    "id": f"alert_{int(datetime.now().timestamp())}",
                    "title": title,
                    "message": message,
                    "urgency": urgency,
                    "timestamp": datetime.now().isoformat(),
                    "type": "alert",
                }
                return StepResult(True, data=alert)
            
            elif operation == "remind":
                message = params.get("message", "")
                when = params.get("when", "")
                repeat = params.get("repeat", "none")
                
                reminder = {
                    "id": f"rem_{len(self._reminders)}_{int(datetime.now().timestamp())}",
                    "message": message,
                    "when": when,
                    "repeat": repeat,
                    "status": "pending",
                    "created": datetime.now().isoformat(),
                }
                self._reminders.append(reminder)
                self._save()
                return StepResult(True, data=reminder)
            
            elif operation == "list":
                status = params.get("status", "pending")
                if status == "all":
                    return StepResult(True, data=self._reminders)
                filtered = [r for r in self._reminders if r.get("status") == status]
                return StepResult(True, data=filtered)
            
            elif operation == "cancel":
                rid = params.get("id")
                for r in self._reminders:
                    if r.get("id") == rid:
                        r["status"] = "cancelled"
                self._save()
                return StepResult(True, data={"cancelled": rid})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  TASK PRIMITIVE
# ============================================================


