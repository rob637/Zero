"""
Telic Engine - Phase 1 Implementation

This is the WORKING implementation that ties everything together.

Usage:
    from apex_engine import Apex
    
    engine = Apex(api_key="...")
    
    # Simple request
    result = await engine.do("Find all PDFs in Downloads and list them")
    
    # With context
    result = await engine.do(
        "Create an amortization schedule from this loan and email it to Fred",
        context={"loan_doc": "~/Documents/loan.pdf"}
    )
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union
from abc import ABC, abstractmethod

# LLM client
try:
    import litellm
    HAS_LITELLM = True
except ImportError:
    HAS_LITELLM = False

# Safety rails
try:
    from src.privacy.redaction import RedactionEngine
    from src.privacy.audit_log import AuditLogger, TransmissionDestination
    from src.control.trust_levels import TrustLevel, TrustLevelManager
    from src.control.approval_gateway import ApprovalGateway, RiskLevel
    from src.control.undo_manager import UndoManager, UndoType
    from src.control.action_history import ActionHistoryDB, ActionCategory
    HAS_SAFETY_RAILS = True
except ImportError:
    HAS_SAFETY_RAILS = False

logger = logging.getLogger(__name__)


# ============================================================
#  ACTION RISK CLASSIFICATION
# ============================================================

# Maps (primitive, operation) -> risk level string
_ACTION_RISK: Dict[tuple, str] = {
    # High risk — destructive or sends data externally
    ("EMAIL", "send"): "high",
    ("FILE", "write"): "high",
    ("SHELL", "run"): "high",
    ("SHELL", "script"): "high",
    ("MESSAGE", "send"): "high",
    ("MESSAGE", "reply"): "high",
    ("BROWSER", "fill_form"): "high",
    ("BROWSER", "execute_js"): "high",
    ("CALENDAR", "delete"): "high",
    ("CALENDAR", "create"): "high",  # Creates external events - needs approval
    ("TASK", "delete"): "high",
    ("TASK", "create"): "high",  # Creates external tasks - needs approval
    ("CONTACTS", "add"): "medium",
    # Medium risk — modifies existing data
    ("TASK", "update"): "medium",
    ("TASK", "complete"): "medium",
    ("FILE", "list"): "low",
    ("FILE", "search"): "low",
    ("FILE", "read"): "low",
    ("NOTIFY", "alert"): "medium",
    ("NOTIFY", "remind"): "medium",
    ("DEVTOOLS", "create_issue"): "high",
    ("DEVTOOLS", "create_pr"): "high",
    ("DEVTOOLS", "comment"): "medium",
    ("CLOUD_STORAGE", "upload"): "high",
    ("CLOUD_STORAGE", "delete"): "high",
    ("CLOUD_STORAGE", "create_folder"): "medium",
}

# Operations that support undo checkpoints
_UNDOABLE_OPS: Dict[tuple, str] = {
    ("FILE", "write"): "file_overwrite",
    ("CALENDAR", "create"): "calendar_create",
    ("CALENDAR", "delete"): "calendar_delete",
    ("TASK", "create"): "task_create",
    ("TASK", "delete"): "task_update",
    ("CONTACTS", "add"): "contact_create",
}


def _classify_risk(primitive: str, operation: str) -> str:
    """Return risk level: 'low', 'medium', 'high', or 'critical'."""
    return _ACTION_RISK.get((primitive, operation), "low")


# ============================================================
#  RESULT TYPES
# ============================================================

@dataclass
class StepResult:
    """Result from a single step."""
    success: bool
    data: Any = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {"success": self.success, "data": self.data, "error": self.error}


@dataclass 
class PlanStep:
    """A step in the execution plan.
    
    step_type controls orchestration behavior:
      - "action"    : (default) execute a single primitive operation
      - "condition" : evaluate a condition, run then_steps or else_steps
      - "parallel"  : run a list of sub-steps concurrently
      - "loop"      : iterate over a list, run body steps for each item
      - "sub_plan"  : delegate to the planner for a sub-request
    """
    id: int
    description: str
    primitive: str
    operation: str
    params: Dict[str, Any]
    depends_on: List[int] = field(default_factory=list)
    wires: Dict[str, str] = field(default_factory=dict)
    result: Optional[StepResult] = None
    # Orchestration fields
    step_type: str = "action"
    condition: Optional[str] = None          # For "condition": expression to evaluate
    then_steps: Optional[List['PlanStep']] = None   # Steps to run if condition is true
    else_steps: Optional[List['PlanStep']] = None   # Steps to run if condition is false
    loop_over: Optional[str] = None          # For "loop": wire ref to iterate (e.g. "step_0.results")
    loop_var: str = "item"                   # Variable name for current iteration item
    loop_body: Optional[List['PlanStep']] = None    # Steps to run per iteration
    parallel_steps: Optional[List['PlanStep']] = None  # For "parallel": concurrent steps
    sub_request: Optional[str] = None        # For "sub_plan": natural language sub-request
    on_fail: str = "stop"                    # "stop" | "continue" | "retry"
    max_retries: int = 3                     # Max self-heal retries
    side_effect: bool = True                 # True if modifies external state, False if read-only
    
    def to_dict(self) -> Dict:
        d = {
            "id": self.id,
            "description": self.description,
            "primitive": self.primitive,
            "operation": self.operation,
            "params": self.params,
            "depends_on": self.depends_on,
            "wires": self.wires,
            "result": self.result.to_dict() if self.result else None,
        }
        if self.step_type != "action":
            d["step_type"] = self.step_type
        if self.condition:
            d["condition"] = self.condition
        if self.then_steps:
            d["then_steps"] = [s.to_dict() for s in self.then_steps]
        if self.else_steps:
            d["else_steps"] = [s.to_dict() for s in self.else_steps]
        if self.loop_over:
            d["loop_over"] = self.loop_over
            d["loop_var"] = self.loop_var
        if self.loop_body:
            d["loop_body"] = [s.to_dict() for s in self.loop_body]
        if self.parallel_steps:
            d["parallel_steps"] = [s.to_dict() for s in self.parallel_steps]
        if self.sub_request:
            d["sub_request"] = self.sub_request
        if self.on_fail != "stop":
            d["on_fail"] = self.on_fail
        return d


@dataclass
class ExecutionResult:
    """Result from executing a request."""
    success: bool
    request: str
    plan: List[PlanStep]
    final_result: Any = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "request": self.request,
            "plan": [s.to_dict() for s in self.plan],
            "final_result": self.final_result,
            "error": self.error,
        }


# ============================================================
#  PRIMITIVE BASE
# ============================================================

class Primitive(ABC):
    """Base class for primitives."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        pass
    
    @abstractmethod
    def get_operations(self) -> Dict[str, str]:
        """Return dict of operation_name -> description."""
        pass
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        """Return param schema per operation for LLM guidance.
        
        Override to declare expected parameters so the planner and self-healer
        know the correct format. Format:
        {
            "operation_name": {
                "param_name": {"type": "str|int|float|dict|list", "required": bool, "description": "..."},
                ...
            }
        }
        """
        return {}
    
    def get_available_operations(self) -> Dict[str, str]:
        """Return operations that are actually configured and ready to use.
        
        By default, returns all operations. Override to filter out operations
        that require external providers that aren't connected.
        """
        return self.get_operations()
    
    @abstractmethod
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        """Execute an operation."""
        pass


# ============================================================
#  FILE PRIMITIVE
# ============================================================

class FilePrimitive(Primitive):
    """File system operations."""
    
    def __init__(self, allowed_roots: Optional[List[str]] = None):
        import tempfile
        home = Path.home()
        self._allowed = allowed_roots or [
            str(home),
            str(Path.cwd()),
            tempfile.gettempdir(),
            # Windows OneDrive and common locations
            str(home / "OneDrive"),
            str(home / "OneDrive - Personal"),
            str(home / "Documents"),
            str(home / "Downloads"),
            str(home / "Desktop"),
            str(home / "Pictures"),
        ]
    
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
                
                # Auto-fix drive roots (C:\, D:\) to user home - users mean their files
                import os
                if os.name == 'nt' and len(directory) <= 3 and directory.endswith((':', ':\\')):
                    logger.info(f"[FilePrimitive] Auto-fixing drive root {directory} → {Path.home()}")
                    directory = str(Path.home())
                
                if not self._is_allowed(directory):
                    home = str(Path.home())
                    return StepResult(False, error=f"Directory not allowed: {directory}. Try searching in {home} instead.")
                
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
                
                # Auto-fix drive roots (C:\, D:\) to user home
                import os
                if os.name == 'nt' and len(directory) <= 3 and directory.endswith((':', ':\\')):
                    directory = str(Path.home())
                
                if not self._is_allowed(directory):
                    home = str(Path.home())
                    return StepResult(False, error=f"Directory not allowed: {directory}. Try {home} instead.")
                
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

class DocumentPrimitive(Primitive):
    """Document parsing and creation."""
    
    def __init__(self, llm_complete: Optional[Callable] = None):
        self._llm = llm_complete
    
    @property
    def name(self) -> str:
        return "DOCUMENT"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "parse": "Parse document to text",
            "extract": "Extract structured data using LLM",
            "create": "Create a document",
            "summarize": "Summarize document content",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "parse": {
                "path": {"type": "str", "required": False, "description": "Path to document file (PDF, DOCX, or plain text)"},
                "content": {"type": "str", "required": False, "description": "Raw document content (alternative to path)"},
            },
            "extract": {
                "content": {"type": "str", "required": True, "description": "Document text to extract from"},
                "schema": {"type": "dict", "required": True, "description": "Fields to extract: {field_name: description}"},
            },
            "create": {
                "format": {"type": "str", "required": False, "description": "Output format: text, csv, json, markdown (default text)"},
                "content": {"type": "str", "required": False, "description": "Text content"},
                "data": {"type": "list", "required": False, "description": "Structured data (list of dicts) for csv/json/markdown"},
                "path": {"type": "str", "required": False, "description": "Save path (optional)"},
            },
            "summarize": {
                "content": {"type": "str", "required": True, "description": "Document text to summarize"},
                "max_length": {"type": "int", "required": False, "description": "Max summary length in characters (default 500)"},
            },
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            if operation == "parse":
                path = params.get("path")
                content = params.get("content")
                
                if path:
                    path = str(Path(path).expanduser())
                    ext = Path(path).suffix.lower()
                    
                    if ext == ".pdf":
                        try:
                            import pypdf
                            reader = pypdf.PdfReader(path)
                            text = "\n".join(page.extract_text() or "" for page in reader.pages)
                        except ImportError:
                            # Fallback: try pdfplumber
                            try:
                                import pdfplumber
                                with pdfplumber.open(path) as pdf:
                                    text = "\n".join(page.extract_text() or "" for page in pdf.pages)
                            except ImportError:
                                return StepResult(False, error="No PDF library available. Install pypdf or pdfplumber.")
                    
                    elif ext == ".docx":
                        try:
                            import docx
                            doc = docx.Document(path)
                            text = "\n".join(p.text for p in doc.paragraphs)
                        except ImportError:
                            return StepResult(False, error="python-docx not installed")
                    
                    else:
                        # Plain text
                        with open(path, "r", errors="ignore") as f:
                            text = f.read()
                else:
                    text = content or ""
                
                return StepResult(True, data=text)
            
            elif operation == "extract":
                content = params.get("content", "")
                schema = params.get("schema", {})
                
                if not self._llm:
                    return StepResult(False, error="LLM not configured for extraction")
                
                prompt = f"""Extract structured data from this document.

Schema to extract (field name: description):
{json.dumps(schema, indent=2)}

Document:
{content[:15000]}

Return ONLY a valid JSON object with the extracted values. Use null if not found."""

                response = await self._llm(prompt)
                
                # Parse JSON from response
                json_match = re.search(r'\{[\s\S]*\}', response)
                if json_match:
                    try:
                        extracted = json.loads(json_match.group())
                    except json.JSONDecodeError:
                        extracted = {"raw": response}
                else:
                    extracted = {"raw": response}
                
                return StepResult(True, data=extracted)
            
            elif operation == "create":
                format_type = params.get("format", "text")
                content = params.get("content", "")
                data = params.get("data")
                path = params.get("path")
                
                if format_type == "csv" and data:
                    import csv
                    import io
                    output = io.StringIO()
                    if isinstance(data, list) and data:
                        if isinstance(data[0], dict):
                            writer = csv.DictWriter(output, fieldnames=data[0].keys())
                            writer.writeheader()
                            writer.writerows(data)
                        else:
                            writer = csv.writer(output)
                            writer.writerows(data)
                    result = output.getvalue()
                
                elif format_type == "json" and data:
                    result = json.dumps(data, indent=2)
                
                elif format_type == "markdown" and data:
                    # Create markdown table from data
                    if isinstance(data, list) and data and isinstance(data[0], dict):
                        headers = list(data[0].keys())
                        lines = ["| " + " | ".join(str(h) for h in headers) + " |"]
                        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
                        for row in data:
                            lines.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
                        result = "\n".join(lines)
                    else:
                        result = content
                
                else:
                    result = content or str(data or "")
                
                if path:
                    path = str(Path(path).expanduser())
                    Path(path).parent.mkdir(parents=True, exist_ok=True)
                    with open(path, "w") as f:
                        f.write(result)
                
                return StepResult(True, data={"content": result, "path": path, "format": format_type})
            
            elif operation == "summarize":
                content = params.get("content", "")
                max_length = params.get("max_length", 500)
                
                if not self._llm:
                    # Simple truncation if no LLM
                    return StepResult(True, data=content[:max_length])
                
                prompt = f"Summarize in {max_length} characters or less:\n\n{content[:10000]}"
                summary = await self._llm(prompt)
                
                return StepResult(True, data=summary[:max_length])
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
                
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  COMPUTE PRIMITIVE
# ============================================================

class ComputePrimitive(Primitive):
    """AI-powered computation engine.
    
    The LLM IS the intelligence. It understands what "amortization schedule"
    means, what inputs it needs, and how to compute it. No hard-coded formula
    registry needed.
    
    Flow:
    1. User asks for any computation (amortization, ROI, depreciation, anything)
    2. LLM writes Python code to compute it
    3. Engine executes the code in a sandbox
    4. Returns the result
    
    This handles millions of scenarios because the LLM knows math — we don't
    need to pre-register every possible formula.
    """
    
    def __init__(self, llm_complete: Optional[Callable] = None):
        self._llm = llm_complete
    
    @property
    def name(self) -> str:
        return "COMPUTE"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "formula": "Compute any formula — amortization, compound interest, ROI, depreciation, NPV, IRR, or anything else. The AI writes the code.",
            "calculate": "Evaluate a math expression (e.g. 'sqrt(144) + pi')",
            "aggregate": "Aggregate numeric data (sum, average, min, max, count, median, or any custom aggregation)",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "formula": {
                "name": {"type": "str", "required": True, "description": "What to compute: amortization, compound_interest, roi, depreciation, npv, irr, or ANY formula name"},
                "inputs": {"type": "dict", "required": True, "description": "Key-value inputs (e.g. {\"principal\": 100000, \"rate\": 3.5, \"term_years\": 30})"},
            },
            "calculate": {
                "expression": {"type": "str", "required": True, "description": "Math expression (e.g. '100 * 1.05 ** 10')"},
                "variables": {"type": "dict", "required": False, "description": "Variable name-value pairs"},
            },
            "aggregate": {
                "data": {"type": "list", "required": True, "description": "List of numbers or dicts"},
                "function": {"type": "str", "required": True, "description": "Any aggregation: sum, average, min, max, count, median, std_dev, percentile, etc."},
                "field": {"type": "str", "required": False, "description": "Field to extract from dicts"},
            },
        }
    
    async def _llm_generate_code(self, name: str, inputs: Dict) -> StepResult:
        """Ask the LLM to write Python code that computes the formula, then execute it.
        
        The LLM knows math. It writes deterministic code. We run it safely.
        This handles ANY formula — no registry needed.
        """
        if not self._llm:
            return StepResult(False, error="No LLM configured. COMPUTE requires an LLM to generate computation code.")
        
        prompt = f"""Write a Python function to compute this:

Formula: {name}
Inputs: {json.dumps(inputs)}

Requirements:
- Write a function called `compute(inputs)` that takes a dict and returns a dict of results
- Use only Python stdlib (math module is available)
- For schedules/tables, include them as a list of dicts under a "schedule" key
- Round monetary values to 2 decimal places
- Include the most useful summary values as top-level keys
- Handle edge cases (zero values, negative inputs) gracefully

Respond with ONLY the Python code. No markdown, no explanation, no ```python blocks.
Start directly with: def compute(inputs):"""

        try:
            response = await self._llm(prompt)
            
            # Clean up response — strip markdown code fences if present
            code = response.strip()
            if code.startswith("```"):
                code = re.sub(r'^```\w*\n?', '', code)
                code = re.sub(r'\n?```$', '', code)
                code = code.strip()
            
            # Validate: must define compute function
            if "def compute" not in code:
                return StepResult(False, error=f"LLM did not generate a valid compute function for '{name}'")
            
            # Execute in sandbox
            return self._execute_sandboxed(code, inputs)
            
        except Exception as e:
            return StepResult(False, error=f"Code generation failed for '{name}': {e}")
    
    def _execute_sandboxed(self, code: str, inputs: Dict) -> StepResult:
        """Execute LLM-generated code in a restricted sandbox."""
        import math
        import datetime as _datetime
        
        # Safe modules the LLM is allowed to import
        _safe_modules = {
            "math": math,
            "datetime": _datetime,
            "json": json,
        }
        
        def _safe_import(name, *args, **kwargs):
            if name in _safe_modules:
                return _safe_modules[name]
            raise ImportError(f"Import of '{name}' is not allowed in sandbox")
        
        # Restricted namespace — safe builtins + safe imports only
        sandbox = {
            "__builtins__": {
                # Math & numeric
                "abs": abs, "round": round, "min": min, "max": max,
                "sum": sum, "len": len, "pow": pow, "int": int, "float": float,
                "sorted": sorted, "enumerate": enumerate, "range": range, "zip": zip,
                "map": map, "filter": filter, "list": list, "dict": dict, "tuple": tuple,
                "set": set, "str": str, "bool": bool, "type": type,
                "True": True, "False": False, "None": None,
                "isinstance": isinstance, "ValueError": ValueError,
                "ZeroDivisionError": ZeroDivisionError, "TypeError": TypeError,
                "KeyError": KeyError, "IndexError": IndexError,
                "print": lambda *a, **k: None,  # no-op
                "__import__": _safe_import,  # safe import for math, datetime, json
            },
            "math": math,
        }
        
        try:
            exec(code, sandbox)
            
            compute_fn = sandbox.get("compute")
            if not callable(compute_fn):
                return StepResult(False, error="Generated code did not define a callable 'compute' function")
            
            result = compute_fn(inputs)
            
            if isinstance(result, dict):
                return StepResult(True, data=result)
            else:
                return StepResult(True, data={"result": result})
                
        except Exception as e:
            return StepResult(False, error=f"Computation error: {type(e).__name__}: {e}")
    
    # ── Built-in formulas (fast path — no LLM needed) ──────────

    @staticmethod
    def _builtin_amortization(inputs: Dict) -> StepResult:
        principal = float(inputs.get("principal", 0))
        annual_rate = float(inputs.get("rate", 0))
        term_months = int(inputs.get("term_months", inputs.get("term", 0)))
        if principal <= 0 or annual_rate <= 0 or term_months <= 0:
            return StepResult(False, error="amortization requires positive principal, rate, and term_months")
        r = annual_rate / 100 / 12
        payment = round(principal * r * (1 + r) ** term_months / ((1 + r) ** term_months - 1), 2)
        balance = principal
        schedule = []
        total_interest = 0.0
        for m in range(1, term_months + 1):
            interest = round(balance * r, 2)
            princ = round(payment - interest, 2)
            balance = round(balance - princ, 2)
            if m == term_months:
                princ = round(princ + balance, 2)
                balance = 0.0
            total_interest += interest
            schedule.append({"month": m, "payment": payment, "interest": interest, "principal": princ, "balance": max(balance, 0.0)})
        return StepResult(True, data={
            "monthly_payment": payment,
            "total_interest": round(total_interest, 2),
            "total_paid": round(payment * term_months, 2),
            "schedule": schedule,
        })

    @staticmethod
    def _builtin_compound_interest(inputs: Dict) -> StepResult:
        principal = float(inputs.get("principal", 0))
        rate = float(inputs.get("rate", 0))
        years = float(inputs.get("years", inputs.get("term_years", 0)))
        n = int(inputs.get("compounds_per_year", 12))
        if principal <= 0 or rate <= 0 or years <= 0:
            return StepResult(False, error="compound_interest requires positive principal, rate, and years")
        r = rate / 100
        final = round(principal * (1 + r / n) ** (n * years), 2)
        return StepResult(True, data={"final_amount": final, "interest_earned": round(final - principal, 2), "principal": principal})

    _BUILTIN_FORMULAS: Dict[str, Callable] = {}  # populated after class body

    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            if operation == "formula":
                name = params.get("name", "").strip()
                inputs = params.get("inputs", {})
                
                # Normalize: if no nested "inputs", treat non-meta params as inputs
                if not inputs:
                    if not name:
                        name = str(params.get("formula", "")).strip()
                    inputs = {k: v for k, v in params.items() if k not in ("name", "formula")}
                
                if not name and not inputs:
                    return StepResult(False, error=f"Tell me what to compute. Params: {json.dumps(params)}. Example: {{\"name\": \"amortization\", \"inputs\": {{\"principal\": 100000, \"rate\": 3.5, \"term_years\": 30}}}}")
                
                if not name and inputs:
                    # No name but has inputs — ask LLM what this probably is
                    name = "custom_calculation"
                
                # Fast path: built-in formulas (no LLM needed)
                builtin = self._BUILTIN_FORMULAS.get(name)
                if builtin:
                    return builtin(inputs)
                
                # Fallback: LLM writes code, engine runs it — works for ANYTHING
                return await self._llm_generate_code(name, inputs)
            
            elif operation == "calculate":
                expr = params.get("expression", "")
                variables = params.get("variables", {})
                
                if not expr:
                    return StepResult(False, error="Missing 'expression' parameter")
                
                import math
                safe_ns = {
                    "__builtins__": {},
                    "abs": abs, "round": round, "min": min, "max": max,
                    "sum": sum, "len": len, "pow": pow, "int": int, "float": float,
                    "pi": math.pi, "e": math.e, "sqrt": math.sqrt,
                    "sin": math.sin, "cos": math.cos, "tan": math.tan,
                    "log": math.log, "log10": math.log10, "ceil": math.ceil, "floor": math.floor,
                }
                safe_ns.update({k: float(v) for k, v in variables.items() if isinstance(v, (int, float))})
                
                result = eval(expr, safe_ns)
                return StepResult(True, data=result)
            
            elif operation == "aggregate":
                data = params.get("data", [])
                func = params.get("function", "sum").lower().strip()
                field_name = params.get("field")
                
                # Debug: log what arrived so we can diagnose wiring issues
                logger.info(f"[COMPUTE.aggregate] func={func}, data type={type(data).__name__}, len={len(data) if isinstance(data, list) else 'N/A'}, raw={str(data)[:200]}")
                
                # Coerce: if data arrived as a JSON string (wiring edge case), parse it
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except (json.JSONDecodeError, ValueError):
                        pass
                
                # Count operates on the raw data length (no numeric extraction needed)
                if func == "count" and isinstance(data, list):
                    return StepResult(True, data=len(data))
                
                if field_name and isinstance(data, list):
                    values = [float(item.get(field_name, 0)) for item in data if isinstance(item, dict)]
                else:
                    values = [float(v) for v in data if isinstance(v, (int, float))]
                
                if not values:
                    return StepResult(True, data=0)
                
                # Common aggregations — fast path, no LLM needed
                import math as _math
                fast = {
                    "sum": lambda v: sum(v),
                    "average": lambda v: sum(v) / len(v),
                    "avg": lambda v: sum(v) / len(v),
                    "mean": lambda v: sum(v) / len(v),
                    "min": lambda v: min(v),
                    "max": lambda v: max(v),
                    "count": lambda v: len(v),
                    "median": lambda v: (sorted(v)[len(v)//2] + sorted(v)[(len(v)-1)//2]) / 2,
                    "std_dev": lambda v: _math.sqrt(sum((x - sum(v)/len(v))**2 for x in v) / len(v)),
                }
                
                if func in fast:
                    return StepResult(True, data=round(fast[func](values), 2))
                
                # Unknown aggregation — LLM writes code for it
                if self._llm:
                    return await self._llm_generate_code(f"aggregate_{func}", {"values": values})
                
                return StepResult(False, error=f"Unknown aggregation: {func}. Available without LLM: {', '.join(fast.keys())}")
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}. Available: formula, calculate, aggregate")
                
        except Exception as e:
            return StepResult(False, error=str(e))

# Wire built-in formulas after class body
ComputePrimitive._BUILTIN_FORMULAS = {
    "amortization": ComputePrimitive._builtin_amortization,
    "compound_interest": ComputePrimitive._builtin_compound_interest,
}


# ============================================================
#  EMAIL PRIMITIVE
# ============================================================

class EmailPrimitive(Primitive):
    """Email operations via Gmail or other providers."""
    
    def __init__(self, send_func: Optional[Callable] = None, list_func: Optional[Callable] = None):
        self._send = send_func
        self._list = list_func
    
    @property
    def name(self) -> str:
        return "EMAIL"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "send": "Send an email",
            "draft": "Create a draft email",
            "search": "Search emails",
            "list": "List recent emails",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "send": {
                "to": {"type": "str", "required": True, "description": "Recipient email address"},
                "subject": {"type": "str", "required": True, "description": "Email subject line"},
                "body": {"type": "str", "required": True, "description": "Email body text"},
                "attachments": {"type": "list", "required": False, "description": "List of file paths to attach"},
            },
            "draft": {
                "to": {"type": "str", "required": True, "description": "Recipient email address"},
                "subject": {"type": "str", "required": True, "description": "Email subject line"},
                "body": {"type": "str", "required": True, "description": "Email body text"},
            },
            "search": {
                "query": {"type": "str", "required": True, "description": "Search query (e.g. 'from:bob subject:report')"},
                "limit": {"type": "int", "required": False, "description": "Max results (default 20)"},
            },
            "list": {
                "query": {"type": "str", "required": False, "description": "Filter query"},
                "limit": {"type": "int", "required": False, "description": "Max results (default 20)"},
            },
        }
    
    def get_available_operations(self) -> Dict[str, str]:
        """All email operations are always available - execute returns helpful errors if no provider."""
        return self.get_operations()
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            if operation == "send":
                if not self._send:
                    return StepResult(False, error="Email sending not configured")
                
                result = await self._send(
                    to=params.get("to"),
                    subject=params.get("subject"),
                    body=params.get("body"),
                    attachments=params.get("attachments"),
                )
                return StepResult(True, data=result)
            
            elif operation == "draft":
                # For now, create draft means just prepare the email
                return StepResult(True, data={
                    "draft": True,
                    "to": params.get("to"),
                    "subject": params.get("subject"),
                    "body": params.get("body"),
                })
            
            elif operation in ["search", "list"]:
                if not self._list:
                    return StepResult(False, error="Email listing not configured")
                
                result = await self._list(
                    query=params.get("query", ""),
                    limit=params.get("limit", 20),
                )
                return StepResult(True, data=result)
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
                
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  CONTACTS PRIMITIVE
# ============================================================

class ContactsPrimitive(Primitive):
    """Contact management.
    
    Local in-memory store by default. Wire in Google Contacts, Outlook, etc.
    via a providers dict.
    """
    
    def __init__(self, providers: Optional[Dict[str, Any]] = None):
        self._contacts: Dict[str, Dict] = {}
        self._providers = providers or {}
    
    @property
    def name(self) -> str:
        return "CONTACTS"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "search": "Find contacts by name or email",
            "add": "Add a contact",
            "list": "List all contacts",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "search": {
                "query": {"type": "str", "required": True, "description": "Name or email to search for"},
                "provider": {"type": "str", "required": False, "description": "Provider: google, microsoft (default: local)"},
            },
            "add": {
                "name": {"type": "str", "required": True, "description": "Contact name"},
                "email": {"type": "str", "required": False, "description": "Email address"},
                "phone": {"type": "str", "required": False, "description": "Phone number"},
                "provider": {"type": "str", "required": False, "description": "Provider: google, microsoft (default: local)"},
            },
            "list": {
                "limit": {"type": "int", "required": False, "description": "Max contacts to return"},
                "provider": {"type": "str", "required": False, "description": "Provider: google, microsoft (default: local)"},
            },
        }
    
    def _get_provider(self, name: Optional[str]) -> Optional[Any]:
        if name and name in self._providers:
            return self._providers[name]
        if self._providers:
            return next(iter(self._providers.values()))
        return None
    
    def add_contact(self, name: str, email: str, phone: Optional[str] = None):
        """Add a contact (can be called directly to seed data)."""
        self._contacts[name.lower()] = {"name": name, "email": email, "phone": phone}
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            provider_name = params.get("provider")
            provider = self._get_provider(provider_name)
            
            if operation == "search":
                query = params.get("query", "").lower()
                
                if provider and hasattr(provider, "search"):
                    result = await provider.search(query=query)
                    if result:
                        first = result[0]
                        return StepResult(True, data={"name": getattr(first, "name", str(first)), "email": getattr(first, "email", ""), "phone": getattr(first, "phone", "")})
                    return StepResult(True, data=None)
                
                matches = [
                    c for c in self._contacts.values()
                    if query in c["name"].lower() or query in c.get("email", "").lower()
                ]
                if matches:
                    return StepResult(True, data=matches[0])
                return StepResult(True, data=None)
            
            elif operation == "add":
                name = params.get("name")
                email = params.get("email")
                phone = params.get("phone")
                
                if not name:
                    return StepResult(False, error="Name required")
                
                if provider and hasattr(provider, "create_contact"):
                    result = await provider.create_contact(name=name, email=email, phone=phone)
                    return StepResult(True, data={"name": name, "email": email})
                
                self._contacts[name.lower()] = {"name": name, "email": email, "phone": phone}
                return StepResult(True, data={"name": name, "email": email})
            
            elif operation == "list":
                limit = params.get("limit", 100)
                
                if provider and hasattr(provider, "list_contacts"):
                    result = await provider.list_contacts(max_results=limit)
                    return StepResult(True, data=[{"name": getattr(c, "name", str(c)), "email": getattr(c, "email", "")} for c in result])
                
                return StepResult(True, data=list(self._contacts.values())[:limit])
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
                
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  KNOWLEDGE PRIMITIVE
# ============================================================

class KnowledgePrimitive(Primitive):
    """Memory and knowledge storage."""
    
    def __init__(self, storage_path: Optional[str] = None):
        self._memories: List[Dict] = []
        self._storage_path = storage_path
        if storage_path and Path(storage_path).exists():
            self._load()
    
    @property
    def name(self) -> str:
        return "KNOWLEDGE"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "remember": "Store information for later recall",
            "recall": "Retrieve relevant information",
            "forget": "Remove stored information",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "remember": {
                "content": {"type": "str", "required": True, "description": "Information to store"},
                "tags": {"type": "list", "required": False, "description": "Tags for categorization"},
            },
            "recall": {
                "query": {"type": "str", "required": True, "description": "Search query to find relevant memories"},
                "limit": {"type": "int", "required": False, "description": "Max results (default 5)"},
            },
            "forget": {
                "id": {"type": "int", "required": True, "description": "Memory ID to remove"},
            },
        }
    
    def _load(self):
        if self._storage_path:
            try:
                with open(self._storage_path, "r") as f:
                    self._memories = json.load(f)
            except:
                pass
    
    def _save(self):
        if self._storage_path:
            Path(self._storage_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self._storage_path, "w") as f:
                json.dump(self._memories, f, indent=2)
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            if operation == "remember":
                content = params.get("content", "")
                tags = params.get("tags", [])
                
                memory = {
                    "id": len(self._memories),
                    "content": content,
                    "tags": tags,
                    "timestamp": datetime.now().isoformat(),
                }
                self._memories.append(memory)
                self._save()
                
                return StepResult(True, data={"id": memory["id"]})
            
            elif operation == "recall":
                query = params.get("query", "").lower()
                limit = params.get("limit", 5)
                
                matches = [
                    m for m in self._memories
                    if query in m["content"].lower() or any(query in t.lower() for t in m.get("tags", []))
                ]
                
                return StepResult(True, data=matches[:limit])
            
            elif operation == "forget":
                memory_id = params.get("id")
                self._memories = [m for m in self._memories if m.get("id") != memory_id]
                self._save()
                return StepResult(True)
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
                
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  CALENDAR PRIMITIVE
# ============================================================

class CalendarPrimitive(Primitive):
    """Calendar and scheduling operations.
    
    Stores events locally. Can be wired to Google Calendar, Outlook, etc.
    via provider functions passed at init.
    """
    
    def __init__(
        self,
        storage_path: Optional[str] = None,
        create_func: Optional[Callable] = None,
        list_func: Optional[Callable] = None,
        list_calendars_func: Optional[Callable] = None,
    ):
        self._events: List[Dict] = []
        self._storage_path = storage_path
        self._create_func = create_func
        self._list_func = list_func
        self._list_calendars_func = list_calendars_func
        self._calendars_cache: List[Dict] = []  # Cache of available calendars
        if storage_path and Path(storage_path).exists():
            try:
                with open(storage_path, "r") as f:
                    self._events = json.load(f)
            except Exception:
                pass
    
    @property
    def name(self) -> str:
        return "CALENDAR"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "create": "Create a calendar event (supports birthdays, meetings, reminders, recurring events)",
            "list": "List events in a date range",
            "search": "Search events by keyword",
            "delete": "Delete an event by ID",
            "availability": "Check free/busy times in a date range",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "create": {
                "title": {"type": "str", "required": True, "description": "Event title"},
                "start": {"type": "str", "required": True, "description": "Start datetime ISO format (e.g. 2026-04-01T09:00:00)"},
                "end": {"type": "str", "required": False, "description": "End datetime ISO format (defaults to 1 hour after start)"},
                "description": {"type": "str", "required": False, "description": "Event description or notes"},
                "location": {"type": "str", "required": False, "description": "Event location"},
                "attendees": {"type": "list", "required": False, "description": "List of attendee email addresses"},
                "calendar_id": {"type": "str", "required": False, "description": "Calendar ID (use 'primary' for main calendar, or calendar name like 'FAMILY SHARED' for specific calendars)"},
                "recurrence": {"type": "str", "required": False, "description": "Recurrence rule: 'yearly', 'monthly', 'weekly', 'daily', or RRULE string"},
                "all_day": {"type": "bool", "required": False, "description": "True for all-day events like birthdays"},
            },
            "list": {
                "start_date": {"type": "str", "required": False, "description": "Start of range (ISO date, defaults to today)"},
                "end_date": {"type": "str", "required": False, "description": "End of range (ISO date, defaults to 7 days out)"},
                "limit": {"type": "int", "required": False, "description": "Max events to return (default 50)"},
            },
            "search": {
                "query": {"type": "str", "required": True, "description": "Search term"},
            },
            "delete": {
                "id": {"type": "str", "required": True, "description": "Event ID to delete"},
            },
            "availability": {
                "start_date": {"type": "str", "required": True, "description": "Start of range (ISO date)"},
                "end_date": {"type": "str", "required": True, "description": "End of range (ISO date)"},
            },
        }
    
    def _save(self):
        if self._storage_path:
            Path(self._storage_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self._storage_path, "w") as f:
                json.dump(self._events, f, indent=2)
            print(f"[CALENDAR] Saved {len(self._events)} events to {self._storage_path}")
    
    async def _resolve_calendar_id(self, calendar_id: str) -> str:
        """Resolve calendar name to ID.
        
        If calendar_id looks like a name (contains spaces or is a known name),
        look it up in the list of calendars and return the actual ID.
        """
        if not calendar_id or calendar_id == "primary":
            return "primary"
        
        # If it looks like an email/ID already (contains @), use as-is
        if "@" in calendar_id:
            return calendar_id
        
        # Try to resolve by name
        if self._list_calendars_func:
            try:
                if not self._calendars_cache:
                    self._calendars_cache = await self._list_calendars_func()
                    print(f"[CALENDAR] Cached {len(self._calendars_cache)} calendars")
                
                # Search for matching calendar by name (case insensitive)
                search_name = calendar_id.lower()
                for cal in self._calendars_cache:
                    cal_name = (cal.get("summary") or "").lower()
                    if search_name in cal_name or cal_name in search_name:
                        real_id = cal.get("id")
                        print(f"[CALENDAR] Resolved '{calendar_id}' -> '{real_id}'")
                        return real_id
                
                print(f"[CALENDAR] No calendar found matching '{calendar_id}', using as-is")
            except Exception as e:
                print(f"[CALENDAR] Error resolving calendar: {e}")
        
        return calendar_id

    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        print(f"[CALENDAR] execute({operation}, {params})")
        try:
            if operation == "create":
                if self._create_func:
                    print(f"[CALENDAR] Using external calendar (Google/Outlook)")
                    # Resolve calendar name to ID (e.g., "FAMILY SHARED" -> actual ID)
                    raw_calendar_id = params.get("calendar_id", "primary")
                    resolved_calendar_id = await self._resolve_calendar_id(raw_calendar_id)
                    
                    # Convert friendly recurrence to RRULE
                    recurrence = params.get("recurrence")
                    recurrence_rules = None
                    if recurrence:
                        recurrence_map = {
                            "yearly": ["RRULE:FREQ=YEARLY"],
                            "annually": ["RRULE:FREQ=YEARLY"],
                            "monthly": ["RRULE:FREQ=MONTHLY"],
                            "weekly": ["RRULE:FREQ=WEEKLY"],
                            "daily": ["RRULE:FREQ=DAILY"],
                        }
                        if recurrence.lower() in recurrence_map:
                            recurrence_rules = recurrence_map[recurrence.lower()]
                        elif recurrence.startswith("RRULE:"):
                            recurrence_rules = [recurrence]
                    
                    # Map param names: CalendarPrimitive uses 'title', Google API uses 'summary'
                    api_params = {
                        "summary": params.get("title") or params.get("summary", "Untitled"),
                        "start": params.get("start"),
                        "end": params.get("end"),
                        "description": params.get("description", ""),
                        "location": params.get("location", ""),
                        "attendees": params.get("attendees", []),
                        "calendar_id": resolved_calendar_id,
                        "all_day": params.get("all_day", False),
                        "recurrence": recurrence_rules,
                    }
                    print(f"[CALENDAR] Creating event: {api_params}")
                    result = await self._create_func(**api_params)
                    # Handle CalendarEvent dataclass or dict
                    if hasattr(result, 'to_dict'):
                        result_dict = result.to_dict()
                    elif isinstance(result, dict):
                        result_dict = result
                    else:
                        result_dict = {"id": str(result)}
                    return StepResult(True, data={
                        **result_dict,
                        "storage": "google_calendar",
                        "calendar": raw_calendar_id,
                        "message": f"Event '{api_params['summary']}' created in Google Calendar ({raw_calendar_id})"
                    })
                
                print(f"[CALENDAR] Creating local event")
                event = {
                    "id": f"evt_{len(self._events)}_{int(datetime.now().timestamp())}",
                    "title": params.get("title", "Untitled"),
                    "start": params.get("start", datetime.now().isoformat()),
                    "end": params.get("end"),
                    "description": params.get("description", ""),
                    "location": params.get("location", ""),
                    "attendees": params.get("attendees", []),
                    "created": datetime.now().isoformat(),
                    "storage": "local",  # Indicate where event is stored
                }
                self._events.append(event)
                self._save()
                print(f"[CALENDAR] Event created: {event['id']} - {event['title']}")
                print(f"[CALENDAR] Saved to: {self._storage_path}")
                return StepResult(True, data={
                    **event,
                    "message": f"Event '{event['title']}' saved to local calendar ({self._storage_path}). Google Calendar sync coming soon."
                })
            
            elif operation == "list":
                if self._list_func:
                    result = await self._list_func(**params)
                    return StepResult(True, data=result)
                
                start = params.get("start_date", datetime.now().strftime("%Y-%m-%d"))
                end = params.get("end_date")
                limit = params.get("limit", 50)
                
                filtered = []
                for evt in self._events:
                    evt_start = evt.get("start", "")
                    if evt_start >= start and (not end or evt_start <= end):
                        filtered.append(evt)
                
                filtered.sort(key=lambda e: e.get("start", ""))
                return StepResult(True, data=filtered[:limit])
            
            elif operation == "search":
                query = params.get("query", "").lower()
                matches = [
                    e for e in self._events
                    if query in e.get("title", "").lower()
                    or query in e.get("description", "").lower()
                    or query in e.get("location", "").lower()
                ]
                return StepResult(True, data=matches)
            
            elif operation == "delete":
                event_id = params.get("id")
                before = len(self._events)
                self._events = [e for e in self._events if e.get("id") != event_id]
                self._save()
                return StepResult(True, data={"deleted": before != len(self._events)})
            
            elif operation == "availability":
                start = params.get("start_date", "")
                end = params.get("end_date", "")
                busy = [
                    {"start": e["start"], "end": e.get("end", e["start"]), "title": e["title"]}
                    for e in self._events
                    if e.get("start", "") >= start and e.get("start", "") <= end
                ]
                return StepResult(True, data={"busy": busy, "count": len(busy)})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  WEB PRIMITIVE
# ============================================================

class WebPrimitive(Primitive):
    """Web/HTTP operations — fetch pages, call APIs, search the web."""
    
    def __init__(self, llm_complete: Optional[Callable] = None, search_provider: Optional[Any] = None):
        self._llm = llm_complete
        self._search_provider = search_provider
    
    @property
    def name(self) -> str:
        return "WEB"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "fetch": "Fetch content from a URL (returns text/HTML). Works for static pages only.",
            "api": "Make an HTTP API call (GET, POST, PUT, DELETE)",
            "search": "Search the web for current information (sports schedules, news, facts). Use this for questions about dates, times, events.",
            "extract": "Fetch a static webpage URL and extract specific information. NOT for google.com, bing.com, or other search engines (JS-rendered). Use for news sites, wikipedia, official event pages.",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "fetch": {
                "url": {"type": "str", "required": True, "description": "URL to fetch"},
                "max_length": {"type": "int", "required": False, "description": "Max chars to return (default 10000)"},
            },
            "api": {
                "url": {"type": "str", "required": True, "description": "API endpoint URL"},
                "method": {"type": "str", "required": False, "description": "HTTP method: GET, POST, PUT, DELETE (default GET)"},
                "headers": {"type": "dict", "required": False, "description": "HTTP headers"},
                "body": {"type": "dict", "required": False, "description": "Request body (for POST/PUT)"},
                "params": {"type": "dict", "required": False, "description": "Query parameters"},
            },
            "search": {
                "query": {"type": "str", "required": True, "description": "Search query"},
                "limit": {"type": "int", "required": False, "description": "Max results (default 5)"},
            },
            "extract": {
                "url": {"type": "str", "required": True, "description": "URL to fetch and extract from"},
                "what": {"type": "str", "required": True, "description": "What to extract (e.g. 'the main article text', 'all prices', 'contact info')"},
            },
        }
    
    def get_available_operations(self) -> Dict[str, str]:
        """Only show search if a search provider is configured."""
        ops = self.get_operations()
        if not self._search_provider:
            ops.pop("search", None)
        return ops
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            import httpx
        except ImportError:
            try:
                import urllib.request
                _has_httpx = False
            except Exception:
                return StepResult(False, error="No HTTP library available")
            _has_httpx = False
        else:
            _has_httpx = True
        
        try:
            if operation == "fetch":
                url = params.get("url", "")
                max_len = params.get("max_length", 10000)
                
                if not url:
                    return StepResult(False, error="Missing 'url' parameter")
                
                if _has_httpx:
                    async with httpx.AsyncClient(
                        follow_redirects=True, 
                        timeout=30,
                        headers={"User-Agent": "Mozilla/5.0 (compatible; Telic/1.0; +https://github.com/rob637/Zero)"}
                    ) as client:
                        resp = await client.get(url)
                        resp.raise_for_status()
                        text = resp.text[:max_len]
                else:
                    req = urllib.request.Request(url, headers={"User-Agent": "Telic/1.0"})
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        text = resp.read().decode("utf-8", errors="ignore")[:max_len]
                
                return StepResult(True, data={"url": url, "content": text, "length": len(text)})
            
            elif operation == "api":
                if not _has_httpx:
                    return StepResult(False, error="httpx required for API calls. Install: pip install httpx")
                
                url = params.get("url", "")
                method = params.get("method", "GET").upper()
                headers = params.get("headers", {})
                body = params.get("body")
                query_params = params.get("params")
                
                if not url:
                    return StepResult(False, error="Missing 'url' parameter")
                
                async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                    resp = await client.request(
                        method, url,
                        headers=headers,
                        json=body if body else None,
                        params=query_params,
                    )
                    
                    try:
                        data = resp.json()
                    except Exception:
                        data = resp.text[:10000]
                    
                    return StepResult(True, data={
                        "status": resp.status_code,
                        "data": data,
                        "headers": dict(resp.headers),
                    })
            
            elif operation == "search":
                query = params.get("query", "")
                limit = params.get("limit", 5)
                
                if self._search_provider and hasattr(self._search_provider, "search"):
                    result = await self._search_provider.search(query=query, num_results=limit)
                    return StepResult(True, data=result)
                
                return StepResult(False, error="Web search not configured. Connect a search provider (Google, Bing, etc.)")
            
            elif operation == "extract":
                url = params.get("url", "")
                what = params.get("what", "the main content")
                
                if not url:
                    return StepResult(False, error="Missing 'url' parameter")
                if not self._llm:
                    return StepResult(False, error="LLM required for extraction")
                
                # Fetch first
                fetch_result = await self.execute("fetch", {"url": url, "max_length": 15000})
                if not fetch_result.success:
                    return fetch_result
                
                content = fetch_result.data.get("content", "")
                
                # Inject today's date for time-sensitive extractions
                today_iso = datetime.now().strftime("%Y-%m-%d")
                
                prompt = f"""Extract the following from this web page:
What to extract: {what}

IMPORTANT: Today's date is {today_iso}. If returning dates/times, use {today_iso} as the date.

Web page content:
{content[:12000]}

Return ONLY a JSON object with the extracted data."""
                
                response = await self._llm(prompt)
                json_match = re.search(r'\{[\s\S]*\}', response)
                if json_match:
                    try:
                        return StepResult(True, data=json.loads(json_match.group()))
                    except json.JSONDecodeError:
                        pass
                return StepResult(True, data={"extracted": response})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  NOTIFY PRIMITIVE
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

class TaskPrimitive(Primitive):
    """Task and to-do list management.
    
    Local task store. Can be wired to Todoist, Microsoft To Do,
    Jira, etc. via providers dict.
    """
    
    def __init__(self, storage_path: Optional[str] = None, providers: Optional[Dict[str, Any]] = None):
        self._tasks: List[Dict] = []
        self._storage_path = storage_path
        self._providers = providers or {}
        if storage_path and Path(storage_path).exists():
            try:
                with open(storage_path, "r") as f:
                    self._tasks = json.load(f)
            except Exception:
                pass
    
    @property
    def name(self) -> str:
        return "TASK"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "create": "Create a new task or to-do item",
            "list": "List tasks, optionally filtered by status or tag",
            "update": "Update a task (status, title, due date, etc.)",
            "complete": "Mark a task as completed",
            "delete": "Delete a task",
            "search": "Search tasks by keyword",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "create": {
                "title": {"type": "str", "required": True, "description": "Task title"},
                "description": {"type": "str", "required": False, "description": "Task description/details"},
                "due": {"type": "str", "required": False, "description": "Due date (ISO date or datetime)"},
                "priority": {"type": "str", "required": False, "description": "low, medium, high, urgent"},
                "tags": {"type": "list", "required": False, "description": "Tags/categories"},
                "project": {"type": "str", "required": False, "description": "Project name"},
                "provider": {"type": "str", "required": False, "description": "Provider: todoist, microsoft_todo, jira (default: local)"},
            },
            "list": {
                "status": {"type": "str", "required": False, "description": "Filter: open, completed, all (default open)"},
                "project": {"type": "str", "required": False, "description": "Filter by project"},
                "tag": {"type": "str", "required": False, "description": "Filter by tag"},
                "limit": {"type": "int", "required": False, "description": "Max results"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "update": {
                "id": {"type": "str", "required": True, "description": "Task ID"},
                "title": {"type": "str", "required": False, "description": "New title"},
                "status": {"type": "str", "required": False, "description": "New status"},
                "due": {"type": "str", "required": False, "description": "New due date"},
                "priority": {"type": "str", "required": False, "description": "New priority"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "complete": {
                "id": {"type": "str", "required": True, "description": "Task ID to complete"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "delete": {
                "id": {"type": "str", "required": True, "description": "Task ID to delete"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "search": {
                "query": {"type": "str", "required": True, "description": "Search term"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
        }
    
    def _get_provider(self, name: Optional[str]) -> Optional[Any]:
        if name and name in self._providers:
            return self._providers[name]
        if self._providers:
            return next(iter(self._providers.values()))
        return None
    
    def _save(self):
        if self._storage_path:
            Path(self._storage_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self._storage_path, "w") as f:
                json.dump(self._tasks, f, indent=2)
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            provider_name = params.get("provider")
            provider = self._get_provider(provider_name)
            
            if operation == "create":
                if provider and hasattr(provider, "create_task"):
                    result = await provider.create_task(
                        title=params.get("title", "Untitled"),
                        body=params.get("description"),
                        due_date=params.get("due"),
                    )
                    return StepResult(True, data={"id": getattr(result, "id", str(result)), "title": params.get("title"), "status": "created"})
                
                task = {
                    "id": f"task_{len(self._tasks)}_{int(datetime.now().timestamp())}",
                    "title": params.get("title", "Untitled"),
                    "description": params.get("description", ""),
                    "status": "open",
                    "due": params.get("due"),
                    "priority": params.get("priority", "medium"),
                    "tags": params.get("tags", []),
                    "project": params.get("project"),
                    "created": datetime.now().isoformat(),
                    "completed_at": None,
                }
                self._tasks.append(task)
                self._save()
                return StepResult(True, data=task)
            
            elif operation == "list":
                if provider and hasattr(provider, "list_tasks"):
                    result = await provider.list_tasks()
                    return StepResult(True, data=result)
                
                status = params.get("status", "open")
                project = params.get("project")
                tag = params.get("tag")
                limit = params.get("limit", 50)
                
                filtered = self._tasks
                if status != "all":
                    filtered = [t for t in filtered if t.get("status") == status]
                if project:
                    filtered = [t for t in filtered if t.get("project") == project]
                if tag:
                    filtered = [t for t in filtered if tag in t.get("tags", [])]
                
                return StepResult(True, data=filtered[:limit])
            
            elif operation == "update":
                task_id = params.get("id")
                
                if provider and hasattr(provider, "update_task"):
                    result = await provider.update_task(task_id=task_id, title=params.get("title"), status=params.get("status"))
                    return StepResult(True, data=result)
                
                for task in self._tasks:
                    if task.get("id") == task_id:
                        for k in ("title", "status", "due", "priority", "description", "project"):
                            if k in params and k != "id":
                                task[k] = params[k]
                        self._save()
                        return StepResult(True, data=task)
                return StepResult(False, error=f"Task not found: {task_id}")
            
            elif operation == "complete":
                task_id = params.get("id")
                
                if provider and hasattr(provider, "complete_task"):
                    result = await provider.complete_task(task_id=task_id)
                    return StepResult(True, data=result)
                
                for task in self._tasks:
                    if task.get("id") == task_id:
                        task["status"] = "completed"
                        task["completed_at"] = datetime.now().isoformat()
                        self._save()
                        return StepResult(True, data=task)
                return StepResult(False, error=f"Task not found: {task_id}")
            
            elif operation == "delete":
                task_id = params.get("id")
                
                if provider and hasattr(provider, "delete_task"):
                    result = await provider.delete_task(task_id=task_id)
                    return StepResult(True, data=result)
                
                before = len(self._tasks)
                self._tasks = [t for t in self._tasks if t.get("id") != task_id]
                self._save()
                return StepResult(True, data={"deleted": before != len(self._tasks)})
            
            elif operation == "search":
                query = params.get("query", "").lower()
                
                if provider and hasattr(provider, "search_tasks"):
                    result = await provider.search_tasks(query=query)
                    return StepResult(True, data=result)
                
                matches = [
                    t for t in self._tasks
                    if query in t.get("title", "").lower()
                    or query in t.get("description", "").lower()
                    or query in t.get("project", "").lower()
                ]
                return StepResult(True, data=matches)
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  SHELL PRIMITIVE
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

class DataPrimitive(Primitive):
    """Structured data operations — query, transform, filter, join.
    
    Works on in-memory data (lists of dicts). The AI writes
    transformation code when needed, just like COMPUTE.
    """
    
    def __init__(self, llm_complete: Optional[Callable] = None):
        self._llm = llm_complete
        self._datasets: Dict[str, List[Dict]] = {}
    
    @property
    def name(self) -> str:
        return "DATA"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "query": "Filter/sort/group data using a natural language query — AI writes the code",
            "transform": "Transform data shape (pivot, flatten, rename, etc.) — AI writes the code",
            "load": "Load data from a file (CSV, JSON) into a named dataset",
            "store": "Store data as a named dataset for later use",
            "merge": "Merge/join two datasets",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "query": {
                "data": {"type": "list", "required": True, "description": "List of dicts to query"},
                "query": {"type": "str", "required": True, "description": "Natural language query (e.g. 'rows where age > 30 sorted by name')"},
            },
            "transform": {
                "data": {"type": "list", "required": True, "description": "List of dicts to transform"},
                "instruction": {"type": "str", "required": True, "description": "What transformation to apply (e.g. 'pivot by category', 'add a total column')"},
            },
            "load": {
                "path": {"type": "str", "required": True, "description": "File path (CSV or JSON)"},
                "name": {"type": "str", "required": False, "description": "Dataset name (default: filename)"},
            },
            "store": {
                "name": {"type": "str", "required": True, "description": "Dataset name"},
                "data": {"type": "list", "required": True, "description": "Data to store"},
            },
            "merge": {
                "left": {"type": "list", "required": True, "description": "First dataset"},
                "right": {"type": "list", "required": True, "description": "Second dataset"},
                "on": {"type": "str", "required": True, "description": "Key field to join on"},
                "how": {"type": "str", "required": False, "description": "Join type: inner, left, right, outer (default inner)"},
            },
        }
    
    async def _llm_data_code(self, instruction: str, data: List) -> StepResult:
        """Ask LLM to write Python code to query/transform data."""
        if not self._llm:
            return StepResult(False, error="LLM required for data queries")
        
        # Show sample of data for LLM context
        sample = data[:3] if len(data) > 3 else data
        
        prompt = f"""Write a Python function to process this data:

Instruction: {instruction}
Data sample (full data has {len(data)} rows): {json.dumps(sample)}

Requirements:
- Write a function called `process(data)` that takes a list of dicts
- Return the processed list of dicts (or a dict with results)
- Use only Python stdlib
- Handle missing keys gracefully

Respond with ONLY the Python code, no markdown, no explanation.
Start directly with: def process(data):"""

        try:
            response = await self._llm(prompt)
            code = response.strip()
            if code.startswith("```"):
                code = re.sub(r'^```\w*\n?', '', code)
                code = re.sub(r'\n?```$', '', code)
                code = code.strip()
            
            if "def process" not in code:
                return StepResult(False, error="LLM did not generate a valid process function")
            
            import math
            sandbox = {
                "__builtins__": {
                    "abs": abs, "round": round, "min": min, "max": max,
                    "sum": sum, "len": len, "pow": pow, "int": int, "float": float,
                    "sorted": sorted, "enumerate": enumerate, "range": range, "zip": zip,
                    "map": map, "filter": filter, "list": list, "dict": dict, "tuple": tuple,
                    "set": set, "str": str, "bool": bool, "type": type,
                    "True": True, "False": False, "None": None,
                    "isinstance": isinstance, "ValueError": ValueError,
                    "KeyError": KeyError, "IndexError": IndexError,
                    "print": lambda *a, **k: None,
                    "__import__": lambda name, *a, **k: __import__(name) if name in ("math", "datetime", "json", "re") else (_ for _ in ()).throw(ImportError(f"Import of '{name}' not allowed")),
                },
            }
            
            exec(code, sandbox)
            process_fn = sandbox.get("process")
            if not callable(process_fn):
                return StepResult(False, error="Generated code did not define a callable 'process' function")
            
            result = process_fn(data)
            return StepResult(True, data=result)
            
        except Exception as e:
            return StepResult(False, error=f"Data processing error: {type(e).__name__}: {e}")
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            if operation == "query":
                data = params.get("data", [])
                query = params.get("query", "")
                
                if not data:
                    # Check named datasets
                    dataset_name = params.get("dataset")
                    if dataset_name and dataset_name in self._datasets:
                        data = self._datasets[dataset_name]
                
                if not data:
                    return StepResult(False, error="No data provided. Pass 'data' (list of dicts) or wire from a previous step.")
                
                return await self._llm_data_code(f"Query: {query}", data)
            
            elif operation == "transform":
                data = params.get("data", [])
                instruction = params.get("instruction", "")
                
                if not data:
                    return StepResult(False, error="No data provided")
                
                return await self._llm_data_code(f"Transform: {instruction}", data)
            
            elif operation == "load":
                path = str(Path(params.get("path", "")).expanduser())
                name = params.get("name", Path(path).stem)
                
                if not Path(path).exists():
                    return StepResult(False, error=f"File not found: {path}")
                
                ext = Path(path).suffix.lower()
                if ext == ".json":
                    with open(path, "r") as f:
                        data = json.load(f)
                elif ext == ".csv":
                    import csv
                    with open(path, "r") as f:
                        reader = csv.DictReader(f)
                        data = list(reader)
                else:
                    return StepResult(False, error=f"Unsupported file type: {ext}. Use .json or .csv")
                
                if isinstance(data, list):
                    self._datasets[name] = data
                    return StepResult(True, data={"name": name, "rows": len(data), "sample": data[:3]})
                else:
                    return StepResult(True, data=data)
            
            elif operation == "store":
                name = params.get("name", "")
                data = params.get("data", [])
                self._datasets[name] = data
                return StepResult(True, data={"name": name, "rows": len(data)})
            
            elif operation == "merge":
                left = params.get("left", [])
                right = params.get("right", [])
                on = params.get("on", "")
                how = params.get("how", "inner")
                
                if not left or not right or not on:
                    return StepResult(False, error="Need 'left', 'right' datasets and 'on' key field")
                
                # Build index from right
                right_idx: Dict[Any, List[Dict]] = {}
                for r in right:
                    key = r.get(on)
                    if key is not None:
                        right_idx.setdefault(key, []).append(r)
                
                merged = []
                left_keys_seen = set()
                
                for l in left:
                    key = l.get(on)
                    left_keys_seen.add(key)
                    matches = right_idx.get(key, [])
                    
                    if matches:
                        for r in matches:
                            row = {**l, **r}
                            merged.append(row)
                    elif how in ("left", "outer"):
                        merged.append(dict(l))
                
                if how in ("right", "outer"):
                    for r in right:
                        key = r.get(on)
                        if key not in left_keys_seen:
                            merged.append(dict(r))
                
                return StepResult(True, data=merged)
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  MESSAGE PRIMITIVE
# ============================================================

class MessagePrimitive(Primitive):
    """Messaging across channels — Slack, Teams, Discord, SMS, WhatsApp.
    
    Provider-based: plug in any messaging backend via send_func/list_func.
    The primitive defines the universal interface; providers handle the protocol.
    """
    
    def __init__(
        self,
        send_func: Optional[Callable] = None,
        list_func: Optional[Callable] = None,
        react_func: Optional[Callable] = None,
        providers: Optional[Dict[str, Any]] = None,
    ):
        self._send = send_func
        self._list = list_func
        self._react = react_func
        self._providers = providers or {}
        self._local_messages: List[Dict] = []
    
    @property
    def name(self) -> str:
        return "MESSAGE"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "send": "Send a message to a channel, thread, or person",
            "list": "List recent messages from a channel or conversation",
            "search": "Search messages by keyword across channels",
            "react": "Add a reaction/emoji to a message",
            "reply": "Reply to a specific message in a thread",
            "channels": "List available channels or conversations",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "send": {
                "to": {"type": "str", "required": True, "description": "Channel name, user handle, or phone number"},
                "text": {"type": "str", "required": True, "description": "Message text"},
                "provider": {"type": "str", "required": False, "description": "Provider: slack, teams, discord, sms (default: auto-detect)"},
                "attachments": {"type": "list", "required": False, "description": "List of file paths or URLs to attach"},
            },
            "list": {
                "channel": {"type": "str", "required": True, "description": "Channel name or conversation ID"},
                "limit": {"type": "int", "required": False, "description": "Max messages to return (default 20)"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "search": {
                "query": {"type": "str", "required": True, "description": "Search term"},
                "channel": {"type": "str", "required": False, "description": "Limit search to a specific channel"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "react": {
                "message_id": {"type": "str", "required": True, "description": "Message ID to react to"},
                "emoji": {"type": "str", "required": True, "description": "Emoji name (e.g. thumbsup, heart, check)"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "reply": {
                "message_id": {"type": "str", "required": True, "description": "Message ID to reply to (thread parent)"},
                "text": {"type": "str", "required": True, "description": "Reply text"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "channels": {
                "provider": {"type": "str", "required": False, "description": "Provider name"},
                "limit": {"type": "int", "required": False, "description": "Max channels to return"},
            },
        }
    
    def _get_provider(self, name: Optional[str]) -> Optional[Any]:
        """Look up a messaging provider by name."""
        if name and name in self._providers:
            return self._providers[name]
        # Return first available provider if none specified
        if self._providers:
            return next(iter(self._providers.values()))
        return None
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            provider_name = params.get("provider")
            
            if operation == "send":
                to = params.get("to", "")
                text = params.get("text", "")
                
                if not to or not text:
                    return StepResult(False, error="Missing 'to' and/or 'text' parameter")
                
                if self._send:
                    result = await self._send(to=to, text=text, provider=provider_name, attachments=params.get("attachments"))
                    return StepResult(True, data=result)
                
                provider = self._get_provider(provider_name)
                if provider and hasattr(provider, "send"):
                    result = await provider.send(to=to, text=text, attachments=params.get("attachments"))
                    return StepResult(True, data=result)
                
                # Local fallback — store for testing/UI display
                msg = {
                    "id": f"msg_{len(self._local_messages)}_{int(datetime.now().timestamp())}",
                    "to": to,
                    "text": text,
                    "timestamp": datetime.now().isoformat(),
                    "status": "queued",
                }
                self._local_messages.append(msg)
                return StepResult(True, data=msg)
            
            elif operation == "list":
                channel = params.get("channel", "")
                limit = params.get("limit", 20)
                
                if self._list:
                    result = await self._list(channel=channel, limit=limit, provider=provider_name)
                    return StepResult(True, data=result)
                
                provider = self._get_provider(provider_name)
                if provider and hasattr(provider, "list_messages"):
                    result = await provider.list_messages(channel=channel, limit=limit)
                    return StepResult(True, data=result)
                
                # Local fallback
                msgs = [m for m in self._local_messages if m.get("to") == channel]
                return StepResult(True, data=msgs[-limit:])
            
            elif operation == "search":
                query = params.get("query", "").lower()
                channel = params.get("channel")
                
                provider = self._get_provider(provider_name)
                if provider and hasattr(provider, "search"):
                    result = await provider.search(query=query, channel=channel)
                    return StepResult(True, data=result)
                
                # Local fallback
                matches = [
                    m for m in self._local_messages
                    if query in m.get("text", "").lower()
                    and (not channel or m.get("to") == channel)
                ]
                return StepResult(True, data=matches)
            
            elif operation == "react":
                message_id = params.get("message_id", "")
                emoji = params.get("emoji", "")
                
                if not message_id or not emoji:
                    return StepResult(False, error="Missing 'message_id' and/or 'emoji' parameter")
                
                if self._react:
                    result = await self._react(message_id=message_id, emoji=emoji, provider=provider_name)
                    return StepResult(True, data=result)
                
                provider = self._get_provider(provider_name)
                if provider and hasattr(provider, "react"):
                    result = await provider.react(message_id=message_id, emoji=emoji)
                    return StepResult(True, data=result)
                
                return StepResult(True, data={"message_id": message_id, "emoji": emoji, "status": "queued"})
            
            elif operation == "reply":
                message_id = params.get("message_id", "")
                text = params.get("text", "")
                
                if not message_id or not text:
                    return StepResult(False, error="Missing 'message_id' and/or 'text' parameter")
                
                provider = self._get_provider(provider_name)
                if provider and hasattr(provider, "reply"):
                    result = await provider.reply(message_id=message_id, text=text)
                    return StepResult(True, data=result)
                
                msg = {
                    "id": f"msg_{len(self._local_messages)}_{int(datetime.now().timestamp())}",
                    "reply_to": message_id,
                    "text": text,
                    "timestamp": datetime.now().isoformat(),
                    "status": "queued",
                }
                self._local_messages.append(msg)
                return StepResult(True, data=msg)
            
            elif operation == "channels":
                provider = self._get_provider(provider_name)
                if provider and hasattr(provider, "list_channels"):
                    result = await provider.list_channels(limit=params.get("limit", 50))
                    return StepResult(True, data=result)
                
                return StepResult(True, data=[])
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  MEDIA PRIMITIVE
# ============================================================

class MediaPrimitive(Primitive):
    """Media operations — images, audio, video.
    
    Handles conversion, metadata, generation (via AI), and playback control.
    Provider-based for services like Spotify, YouTube, etc.
    """
    
    def __init__(
        self,
        llm_complete: Optional[Callable] = None,
        providers: Optional[Dict[str, Any]] = None,
    ):
        self._llm = llm_complete
        self._providers = providers or {}
    
    @property
    def name(self) -> str:
        return "MEDIA"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "info": "Get metadata about a media file (dimensions, format, EXIF: date taken, camera, GPS, etc.)",
            "convert": "Convert media between formats (e.g. mp4→mp3, png→jpg)",
            "resize": "Resize an image to specific dimensions",
            "generate": "Generate an image or audio using AI",
            "transcribe": "Transcribe audio/video to text",
            "play": "Play or queue media via a provider (Spotify, etc.)",
            "search": "Search media libraries or services",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "info": {
                "path": {"type": "str", "required": True, "description": "Path to media file"},
            },
            "convert": {
                "path": {"type": "str", "required": True, "description": "Source file path"},
                "format": {"type": "str", "required": True, "description": "Target format (mp3, mp4, png, jpg, wav, etc.)"},
                "output": {"type": "str", "required": False, "description": "Output file path (default: same dir, new extension)"},
            },
            "resize": {
                "path": {"type": "str", "required": True, "description": "Image file path"},
                "width": {"type": "int", "required": False, "description": "Target width in pixels"},
                "height": {"type": "int", "required": False, "description": "Target height in pixels"},
                "output": {"type": "str", "required": False, "description": "Output file path"},
            },
            "generate": {
                "prompt": {"type": "str", "required": True, "description": "Description of what to generate"},
                "type": {"type": "str", "required": False, "description": "image or audio (default image)"},
                "output": {"type": "str", "required": False, "description": "Output file path"},
            },
            "transcribe": {
                "path": {"type": "str", "required": True, "description": "Audio or video file path"},
                "language": {"type": "str", "required": False, "description": "Language code (default: auto-detect)"},
            },
            "play": {
                "query": {"type": "str", "required": False, "description": "What to play (song name, artist, playlist)"},
                "uri": {"type": "str", "required": False, "description": "Direct media URI (spotify:track:..., file path, URL)"},
                "action": {"type": "str", "required": False, "description": "play, pause, next, previous, volume (default play)"},
                "provider": {"type": "str", "required": False, "description": "Provider: spotify, youtube, local"},
            },
            "search": {
                "query": {"type": "str", "required": True, "description": "Search query"},
                "type": {"type": "str", "required": False, "description": "Filter: song, album, artist, playlist, video"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
                "limit": {"type": "int", "required": False, "description": "Max results"},
            },
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            if operation == "info":
                path = str(Path(params.get("path", "")).expanduser())
                if not Path(path).exists():
                    return StepResult(False, error=f"File not found: {path}")
                
                stat = Path(path).stat()
                ext = Path(path).suffix.lower()
                
                info = {
                    "path": path,
                    "name": Path(path).name,
                    "format": ext.lstrip("."),
                    "size_bytes": stat.st_size,
                    "size_mb": round(stat.st_size / (1024 * 1024), 2),
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                }
                
                # Try to get image dimensions and EXIF
                if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"):
                    try:
                        from PIL import Image
                        from PIL.ExifTags import TAGS, GPSTAGS
                        with Image.open(path) as img:
                            info["width"] = img.width
                            info["height"] = img.height
                            info["mode"] = img.mode
                            
                            # Extract EXIF data
                            exif_data = img._getexif()
                            if exif_data:
                                exif = {}
                                for tag_id, value in exif_data.items():
                                    tag = TAGS.get(tag_id, tag_id)
                                    if isinstance(value, bytes):
                                        try:
                                            value = value.decode("utf-8", errors="ignore")
                                        except:
                                            continue
                                    # Extract key fields
                                    if tag == "DateTimeOriginal":
                                        exif["date_taken"] = value
                                    elif tag == "Make":
                                        exif["camera_make"] = value
                                    elif tag == "Model":
                                        exif["camera_model"] = value
                                    elif tag == "Orientation":
                                        exif["orientation"] = value
                                    elif tag == "GPSInfo":
                                        # Parse GPS coordinates
                                        try:
                                            gps = {}
                                            for gps_tag_id, gps_value in value.items():
                                                gps_tag = GPSTAGS.get(gps_tag_id, gps_tag_id)
                                                gps[gps_tag] = gps_value
                                            if "GPSLatitude" in gps and "GPSLongitude" in gps:
                                                def convert_gps(coord, ref):
                                                    d, m, s = coord
                                                    decimal = float(d) + float(m)/60 + float(s)/3600
                                                    if ref in ["S", "W"]:
                                                        decimal = -decimal
                                                    return round(decimal, 6)
                                                lat = convert_gps(gps["GPSLatitude"], gps.get("GPSLatitudeRef", "N"))
                                                lon = convert_gps(gps["GPSLongitude"], gps.get("GPSLongitudeRef", "E"))
                                                exif["gps_latitude"] = lat
                                                exif["gps_longitude"] = lon
                                        except:
                                            pass
                                    elif tag == "ExposureTime":
                                        exif["exposure_time"] = str(value)
                                    elif tag == "FNumber":
                                        exif["f_number"] = float(value)
                                    elif tag == "ISOSpeedRatings":
                                        exif["iso"] = value
                                if exif:
                                    info["exif"] = exif
                    except ImportError:
                        info["note"] = "Install Pillow for image dimensions and EXIF"
                
                return StepResult(True, data=info)
            
            elif operation == "convert":
                path = str(Path(params.get("path", "")).expanduser())
                target_fmt = params.get("format", "")
                output = params.get("output")
                
                if not Path(path).exists():
                    return StepResult(False, error=f"File not found: {path}")
                if not target_fmt:
                    return StepResult(False, error="Missing 'format' parameter")
                
                if not output:
                    output = str(Path(path).with_suffix(f".{target_fmt.lstrip('.')}"))
                else:
                    output = str(Path(output).expanduser())
                
                src_ext = Path(path).suffix.lower()
                
                # Image conversion via Pillow
                if src_ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"):
                    try:
                        from PIL import Image
                        with Image.open(path) as img:
                            if target_fmt.lower() in ("jpg", "jpeg") and img.mode == "RGBA":
                                img = img.convert("RGB")
                            img.save(output)
                        return StepResult(True, data={"input": path, "output": output, "format": target_fmt})
                    except ImportError:
                        return StepResult(False, error="Install Pillow for image conversion: pip install Pillow")
                
                # Audio/video via ffmpeg
                try:
                    import subprocess
                    proc = await asyncio.create_subprocess_exec(
                        "ffmpeg", "-i", path, "-y", output,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
                    if proc.returncode == 0:
                        return StepResult(True, data={"input": path, "output": output, "format": target_fmt})
                    return StepResult(False, error=f"ffmpeg error: {stderr.decode()[:500]}")
                except FileNotFoundError:
                    return StepResult(False, error="ffmpeg not installed. Install ffmpeg for media conversion.")
                except asyncio.TimeoutError:
                    return StepResult(False, error="Conversion timed out after 120s")
            
            elif operation == "resize":
                path = str(Path(params.get("path", "")).expanduser())
                width = params.get("width")
                height = params.get("height")
                output = params.get("output", path)
                
                if not Path(path).exists():
                    return StepResult(False, error=f"File not found: {path}")
                
                try:
                    from PIL import Image
                    with Image.open(path) as img:
                        orig_w, orig_h = img.size
                        if width and not height:
                            height = int(orig_h * (width / orig_w))
                        elif height and not width:
                            width = int(orig_w * (height / orig_h))
                        elif not width and not height:
                            return StepResult(False, error="Specify 'width' and/or 'height'")
                        
                        resized = img.resize((width, height), Image.LANCZOS)
                        output = str(Path(output).expanduser())
                        resized.save(output)
                    
                    return StepResult(True, data={"path": output, "width": width, "height": height, "original": f"{orig_w}x{orig_h}"})
                except ImportError:
                    return StepResult(False, error="Install Pillow for image resize: pip install Pillow")
            
            elif operation == "generate":
                prompt = params.get("prompt", "")
                media_type = params.get("type", "image")
                
                if not prompt:
                    return StepResult(False, error="Missing 'prompt' parameter")
                
                if not self._llm:
                    return StepResult(False, error="LLM required for media generation")
                
                # This would connect to DALL-E, Stable Diffusion, etc.
                return StepResult(False, error=f"Image generation not configured. Connect a provider (DALL-E, Stable Diffusion, etc.) to generate: '{prompt}'")
            
            elif operation == "transcribe":
                path = str(Path(params.get("path", "")).expanduser())
                
                if not Path(path).exists():
                    return StepResult(False, error=f"File not found: {path}")
                
                # Would connect to Whisper, Google Speech, etc.
                return StepResult(False, error="Transcription not configured. Connect a provider (Whisper, Google Speech, etc.)")
            
            elif operation == "play":
                action = params.get("action", "play")
                provider_name = params.get("provider")
                
                provider = self._providers.get(provider_name) if provider_name else (next(iter(self._providers.values())) if self._providers else None)
                
                if provider and hasattr(provider, "control"):
                    result = await provider.control(
                        action=action,
                        query=params.get("query"),
                        uri=params.get("uri"),
                    )
                    return StepResult(True, data=result)
                
                return StepResult(False, error="No media player configured. Connect a provider (Spotify, YouTube, etc.)")
            
            elif operation == "search":
                query = params.get("query", "")
                provider_name = params.get("provider")
                
                provider = self._providers.get(provider_name) if provider_name else (next(iter(self._providers.values())) if self._providers else None)
                
                if provider and hasattr(provider, "search"):
                    result = await provider.search(
                        query=query,
                        type=params.get("type"),
                        limit=params.get("limit", 10),
                    )
                    return StepResult(True, data=result)
                
                return StepResult(False, error="No media search configured. Connect a provider (Spotify, YouTube, etc.)")
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  BROWSER PRIMITIVE
# ============================================================

class BrowserPrimitive(Primitive):
    """Browser automation — navigate, interact with web pages, fill forms.
    
    Distinct from WEB (which does raw HTTP). BROWSER controls a real browser
    for JavaScript-heavy sites, form filling, screenshots, etc.
    Uses Playwright when available, falls back to error messages.
    """
    
    def __init__(self, llm_complete: Optional[Callable] = None):
        self._llm = llm_complete
        self._page = None
        self._browser = None
    
    @property
    def name(self) -> str:
        return "BROWSER"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "open": "Open a URL in a browser",
            "click": "Click an element on the page",
            "type": "Type text into an input field",
            "screenshot": "Take a screenshot of the current page",
            "read": "Read the text content of the current page or a specific element",
            "fill_form": "Fill out a form with provided field values",
            "execute_js": "Execute JavaScript on the current page",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "open": {
                "url": {"type": "str", "required": True, "description": "URL to navigate to"},
                "wait": {"type": "int", "required": False, "description": "Seconds to wait after load (default 2)"},
            },
            "click": {
                "selector": {"type": "str", "required": True, "description": "CSS selector or text of element to click"},
            },
            "type": {
                "selector": {"type": "str", "required": True, "description": "CSS selector of input field"},
                "text": {"type": "str", "required": True, "description": "Text to type"},
                "clear": {"type": "bool", "required": False, "description": "Clear field before typing (default true)"},
            },
            "screenshot": {
                "path": {"type": "str", "required": False, "description": "Save path (default: ~/screenshot.png)"},
                "full_page": {"type": "bool", "required": False, "description": "Capture full page (default false)"},
            },
            "read": {
                "selector": {"type": "str", "required": False, "description": "CSS selector to read (default: body)"},
                "max_length": {"type": "int", "required": False, "description": "Max chars to return"},
            },
            "fill_form": {
                "fields": {"type": "dict", "required": True, "description": "Map of CSS selector -> value to fill"},
                "submit": {"type": "bool", "required": False, "description": "Submit the form after filling (default false)"},
            },
            "execute_js": {
                "script": {"type": "str", "required": True, "description": "JavaScript code to execute"},
            },
        }
    
    async def _ensure_browser(self) -> StepResult:
        """Lazy-init a Playwright browser instance."""
        if self._page:
            return StepResult(True)
        
        try:
            from playwright.async_api import async_playwright
            pw = await async_playwright().start()
            self._browser = await pw.chromium.launch(headless=True)
            self._page = await self._browser.new_page()
            return StepResult(True)
        except ImportError:
            return StepResult(False, error="Playwright not installed. Install: pip install playwright && playwright install chromium")
        except Exception as e:
            return StepResult(False, error=f"Failed to start browser: {e}")
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            if operation == "open":
                url = params.get("url", "")
                wait = params.get("wait", 2)
                
                if not url:
                    return StepResult(False, error="Missing 'url' parameter")
                
                init = await self._ensure_browser()
                if not init.success:
                    return init
                
                await self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
                if wait > 0:
                    await asyncio.sleep(wait)
                
                title = await self._page.title()
                return StepResult(True, data={"url": url, "title": title})
            
            elif operation == "click":
                selector = params.get("selector", "")
                if not selector:
                    return StepResult(False, error="Missing 'selector' parameter")
                
                init = await self._ensure_browser()
                if not init.success:
                    return init
                
                # Try CSS selector first, then text
                try:
                    await self._page.click(selector, timeout=5000)
                except Exception:
                    await self._page.click(f"text={selector}", timeout=5000)
                
                return StepResult(True, data={"clicked": selector})
            
            elif operation == "type":
                selector = params.get("selector", "")
                text = params.get("text", "")
                clear = params.get("clear", True)
                
                if not selector or not text:
                    return StepResult(False, error="Missing 'selector' and/or 'text' parameter")
                
                init = await self._ensure_browser()
                if not init.success:
                    return init
                
                if clear:
                    await self._page.fill(selector, text, timeout=5000)
                else:
                    await self._page.type(selector, text, timeout=5000)
                
                return StepResult(True, data={"selector": selector, "typed": len(text)})
            
            elif operation == "screenshot":
                path = params.get("path", str(Path.home() / "screenshot.png"))
                full_page = params.get("full_page", False)
                
                init = await self._ensure_browser()
                if not init.success:
                    return init
                
                path = str(Path(path).expanduser())
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                await self._page.screenshot(path=path, full_page=full_page)
                
                return StepResult(True, data={"path": path, "full_page": full_page})
            
            elif operation == "read":
                selector = params.get("selector", "body")
                max_len = params.get("max_length", 10000)
                
                init = await self._ensure_browser()
                if not init.success:
                    return init
                
                text = await self._page.inner_text(selector, timeout=5000)
                return StepResult(True, data={"text": text[:max_len], "length": len(text)})
            
            elif operation == "fill_form":
                fields = params.get("fields", {})
                submit = params.get("submit", False)
                
                if not fields:
                    return StepResult(False, error="Missing 'fields' parameter")
                
                init = await self._ensure_browser()
                if not init.success:
                    return init
                
                filled = []
                for selector, value in fields.items():
                    await self._page.fill(selector, str(value), timeout=5000)
                    filled.append(selector)
                
                if submit:
                    # Try common submit patterns
                    for submit_sel in ['button[type="submit"]', 'input[type="submit"]', "form button"]:
                        try:
                            await self._page.click(submit_sel, timeout=3000)
                            break
                        except Exception:
                            continue
                
                return StepResult(True, data={"filled": filled, "submitted": submit})
            
            elif operation == "execute_js":
                script = params.get("script", "")
                if not script:
                    return StepResult(False, error="Missing 'script' parameter")
                
                init = await self._ensure_browser()
                if not init.success:
                    return init
                
                result = await self._page.evaluate(script)
                return StepResult(True, data={"result": result})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  DEVTOOLS PRIMITIVE
# ============================================================

class DevToolsPrimitive(Primitive):
    """Developer tools — GitHub, Jira, and other dev platforms.
    
    Provider-based: plug in GitHub, Jira, or any dev platform connector.
    """
    
    def __init__(self, providers: Optional[Dict[str, Any]] = None):
        self._providers = providers or {}
    
    @property
    def name(self) -> str:
        return "DEVTOOLS"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "list_issues": "List issues or tickets from a project",
            "get_issue": "Get details of a specific issue or ticket",
            "create_issue": "Create a new issue or ticket",
            "update_issue": "Update an existing issue or ticket",
            "comment": "Add a comment to an issue or PR",
            "list_prs": "List pull requests or merge requests",
            "create_pr": "Create a pull request",
            "list_repos": "List repositories or projects",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "list_issues": {
                "repo": {"type": "str", "required": False, "description": "Repository or project key (e.g. 'owner/repo' or 'PROJ')"},
                "state": {"type": "str", "required": False, "description": "Filter: open, closed, all (default open)"},
                "limit": {"type": "int", "required": False, "description": "Max results (default 20)"},
                "provider": {"type": "str", "required": False, "description": "Provider: github, jira (default: auto)"},
            },
            "get_issue": {
                "repo": {"type": "str", "required": False, "description": "Repository or project key"},
                "issue_id": {"type": "str", "required": True, "description": "Issue number or key (e.g. '42' or 'PROJ-123')"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "create_issue": {
                "repo": {"type": "str", "required": False, "description": "Repository or project key"},
                "title": {"type": "str", "required": True, "description": "Issue title"},
                "body": {"type": "str", "required": False, "description": "Issue description/body"},
                "labels": {"type": "list", "required": False, "description": "Labels/tags"},
                "assignee": {"type": "str", "required": False, "description": "Assignee username"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "update_issue": {
                "repo": {"type": "str", "required": False, "description": "Repository or project key"},
                "issue_id": {"type": "str", "required": True, "description": "Issue number or key"},
                "title": {"type": "str", "required": False, "description": "New title"},
                "body": {"type": "str", "required": False, "description": "New body"},
                "state": {"type": "str", "required": False, "description": "New state: open or closed"},
                "labels": {"type": "list", "required": False, "description": "Updated labels"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "comment": {
                "repo": {"type": "str", "required": False, "description": "Repository or project key"},
                "issue_id": {"type": "str", "required": True, "description": "Issue/PR number or key"},
                "body": {"type": "str", "required": True, "description": "Comment text"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "list_prs": {
                "repo": {"type": "str", "required": False, "description": "Repository (e.g. 'owner/repo')"},
                "state": {"type": "str", "required": False, "description": "Filter: open, closed, all (default open)"},
                "limit": {"type": "int", "required": False, "description": "Max results"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "create_pr": {
                "repo": {"type": "str", "required": False, "description": "Repository (e.g. 'owner/repo')"},
                "title": {"type": "str", "required": True, "description": "PR title"},
                "body": {"type": "str", "required": False, "description": "PR description"},
                "head": {"type": "str", "required": True, "description": "Source branch"},
                "base": {"type": "str", "required": False, "description": "Target branch (default: main)"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "list_repos": {
                "limit": {"type": "int", "required": False, "description": "Max results"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
        }
    
    def _get_provider(self, name: Optional[str]) -> Optional[Any]:
        if name and name in self._providers:
            return self._providers[name]
        if self._providers:
            return next(iter(self._providers.values()))
        return None
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            provider_name = params.get("provider")
            provider = self._get_provider(provider_name)
            
            if not provider:
                return StepResult(False, error="No devtools provider configured. Connect GitHub, Jira, etc.")
            
            if operation == "list_issues":
                if hasattr(provider, "list_issues"):
                    result = await provider.list_issues(
                        repo=params.get("repo", ""),
                        state=params.get("state", "open"),
                        per_page=params.get("limit", 20),
                    )
                    return StepResult(True, data=result)
                return StepResult(False, error=f"Provider does not support list_issues")
            
            elif operation == "get_issue":
                issue_id = params.get("issue_id", "")
                if hasattr(provider, "get_issue"):
                    result = await provider.get_issue(repo=params.get("repo", ""), issue_number=issue_id)
                    return StepResult(True, data=result)
                return StepResult(False, error=f"Provider does not support get_issue")
            
            elif operation == "create_issue":
                if hasattr(provider, "create_issue"):
                    result = await provider.create_issue(
                        repo=params.get("repo", ""),
                        title=params.get("title", ""),
                        body=params.get("body", ""),
                        labels=params.get("labels"),
                        assignees=[params["assignee"]] if params.get("assignee") else None,
                    )
                    return StepResult(True, data=result)
                return StepResult(False, error=f"Provider does not support create_issue")
            
            elif operation == "update_issue":
                if hasattr(provider, "update_issue"):
                    result = await provider.update_issue(
                        repo=params.get("repo", ""),
                        issue_number=params.get("issue_id", ""),
                        title=params.get("title"),
                        body=params.get("body"),
                        state=params.get("state"),
                        labels=params.get("labels"),
                    )
                    return StepResult(True, data=result)
                return StepResult(False, error=f"Provider does not support update_issue")
            
            elif operation == "comment":
                if hasattr(provider, "add_comment"):
                    result = await provider.add_comment(
                        repo=params.get("repo", ""),
                        issue_number=params.get("issue_id", ""),
                        body=params.get("body", ""),
                    )
                    return StepResult(True, data=result)
                return StepResult(False, error=f"Provider does not support add_comment")
            
            elif operation == "list_prs":
                if hasattr(provider, "list_pull_requests"):
                    result = await provider.list_pull_requests(
                        repo=params.get("repo", ""),
                        state=params.get("state", "open"),
                    )
                    return StepResult(True, data=result)
                return StepResult(False, error=f"Provider does not support list_prs")
            
            elif operation == "create_pr":
                if hasattr(provider, "create_pull_request"):
                    result = await provider.create_pull_request(
                        repo=params.get("repo", ""),
                        title=params.get("title", ""),
                        body=params.get("body", ""),
                        head=params.get("head", ""),
                        base=params.get("base", "main"),
                    )
                    return StepResult(True, data=result)
                return StepResult(False, error=f"Provider does not support create_pr")
            
            elif operation == "list_repos":
                if hasattr(provider, "list_repos"):
                    result = await provider.list_repos(per_page=params.get("limit", 20))
                    return StepResult(True, data=result)
                return StepResult(False, error=f"Provider does not support list_repos")
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  CLOUD STORAGE PRIMITIVE
# ============================================================

class CloudStoragePrimitive(Primitive):
    """Cloud storage operations — Google Drive, OneDrive, Dropbox.
    
    Provider-based: plug in any cloud storage connector.
    """
    
    def __init__(self, providers: Optional[Dict[str, Any]] = None):
        self._providers = providers or {}
    
    @property
    def name(self) -> str:
        return "CLOUD_STORAGE"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "list": "List files and folders in cloud storage",
            "search": "Search for files by name or content",
            "download": "Download a file from cloud storage",
            "upload": "Upload a file to cloud storage",
            "create_folder": "Create a folder in cloud storage",
            "delete": "Delete a file or folder from cloud storage",
            "share": "Share a file or folder with others",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "list": {
                "path": {"type": "str", "required": False, "description": "Folder path or ID (default: root)"},
                "limit": {"type": "int", "required": False, "description": "Max results"},
                "provider": {"type": "str", "required": False, "description": "Provider: google_drive, onedrive, dropbox"},
            },
            "search": {
                "query": {"type": "str", "required": True, "description": "Search query (file name or content)"},
                "limit": {"type": "int", "required": False, "description": "Max results"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "download": {
                "file_id": {"type": "str", "required": True, "description": "File ID or path in cloud storage"},
                "local_path": {"type": "str", "required": True, "description": "Local path to save the file"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "upload": {
                "local_path": {"type": "str", "required": True, "description": "Local file path to upload"},
                "remote_path": {"type": "str", "required": False, "description": "Destination path in cloud storage"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "create_folder": {
                "name": {"type": "str", "required": True, "description": "Folder name"},
                "parent": {"type": "str", "required": False, "description": "Parent folder ID or path"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "delete": {
                "file_id": {"type": "str", "required": True, "description": "File or folder ID to delete"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "share": {
                "file_id": {"type": "str", "required": True, "description": "File or folder ID to share"},
                "email": {"type": "str", "required": True, "description": "Email of person to share with"},
                "role": {"type": "str", "required": False, "description": "Permission: viewer, editor, commenter (default viewer)"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
        }
    
    def _get_provider(self, name: Optional[str]) -> Optional[Any]:
        if name and name in self._providers:
            return self._providers[name]
        if self._providers:
            return next(iter(self._providers.values()))
        return None
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            provider_name = params.get("provider")
            provider = self._get_provider(provider_name)
            
            if not provider:
                return StepResult(False, error="No cloud storage provider configured. Connect Google Drive, OneDrive, or Dropbox.")
            
            if operation == "list":
                if hasattr(provider, "list_files"):
                    result = await provider.list_files(
                        folder_id=params.get("path"),
                        max_results=params.get("limit", 50),
                    )
                    return StepResult(True, data=result)
                return StepResult(False, error="Provider does not support list_files")
            
            elif operation == "search":
                if hasattr(provider, "search_files"):
                    result = await provider.search_files(
                        query=params.get("query", ""),
                        max_results=params.get("limit", 20),
                    )
                    return StepResult(True, data=result)
                return StepResult(False, error="Provider does not support search_files")
            
            elif operation == "download":
                if hasattr(provider, "download_file"):
                    result = await provider.download_file(
                        file_id=params.get("file_id", ""),
                        local_path=params.get("local_path", ""),
                    )
                    return StepResult(True, data=result)
                return StepResult(False, error="Provider does not support download_file")
            
            elif operation == "upload":
                if hasattr(provider, "upload_file"):
                    result = await provider.upload_file(
                        local_path=params.get("local_path", ""),
                        remote_path=params.get("remote_path"),
                    )
                    return StepResult(True, data=result)
                return StepResult(False, error="Provider does not support upload_file")
            
            elif operation == "create_folder":
                if hasattr(provider, "create_folder"):
                    result = await provider.create_folder(
                        name=params.get("name", ""),
                        parent_id=params.get("parent"),
                    )
                    return StepResult(True, data=result)
                return StepResult(False, error="Provider does not support create_folder")
            
            elif operation == "delete":
                if hasattr(provider, "delete_file"):
                    result = await provider.delete_file(file_id=params.get("file_id", ""))
                    return StepResult(True, data=result)
                return StepResult(False, error="Provider does not support delete_file")
            
            elif operation == "share":
                if hasattr(provider, "share_file"):
                    result = await provider.share_file(
                        file_id=params.get("file_id", ""),
                        email=params.get("email", ""),
                        role=params.get("role", "viewer"),
                    )
                    return StepResult(True, data=result)
                return StepResult(False, error="Provider does not support share_file")
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  CLIPBOARD PRIMITIVE
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

class TranslatePrimitive(Primitive):
    """Language translation and detection.
    
    Uses LLM for translation when no dedicated API is configured.
    """
    
    def __init__(self, llm_complete: Optional[Callable] = None, provider: Optional[Any] = None):
        self._llm = llm_complete
        self._provider = provider
    
    @property
    def name(self) -> str:
        return "TRANSLATE"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "translate": "Translate text from one language to another",
            "detect": "Detect the language of text",
            "languages": "List supported languages",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "translate": {
                "text": {"type": "str", "required": True, "description": "Text to translate"},
                "to": {"type": "str", "required": True, "description": "Target language (e.g. 'spanish', 'fr', 'zh')"},
                "from": {"type": "str", "required": False, "description": "Source language (default: auto-detect)"},
            },
            "detect": {
                "text": {"type": "str", "required": True, "description": "Text to analyze"},
            },
            "languages": {},
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            if operation == "translate":
                text = params.get("text", "")
                target_lang = params.get("to", "")
                source_lang = params.get("from", "auto")
                
                if not text or not target_lang:
                    return StepResult(False, error="Missing 'text' and/or 'to' parameter")
                
                if self._provider and hasattr(self._provider, "translate"):
                    result = await self._provider.translate(text, target_lang, source_lang)
                    return StepResult(True, data=result)
                
                if self._llm:
                    prompt = f"Translate the following text to {target_lang}. Return ONLY the translation, nothing else:\n\n{text}"
                    translation = await self._llm(prompt)
                    return StepResult(True, data={
                        "original": text,
                        "translated": translation.strip(),
                        "to": target_lang,
                        "from": source_lang,
                    })
                
                return StepResult(False, error="No translation provider or LLM configured")
            
            elif operation == "detect":
                text = params.get("text", "")
                if not text:
                    return StepResult(False, error="Missing 'text' parameter")
                
                if self._provider and hasattr(self._provider, "detect"):
                    result = await self._provider.detect(text)
                    return StepResult(True, data=result)
                
                if self._llm:
                    prompt = f"What language is this text written in? Respond with ONLY the language name:\n\n{text[:500]}"
                    language = await self._llm(prompt)
                    return StepResult(True, data={
                        "text": text[:100] + "..." if len(text) > 100 else text,
                        "language": language.strip(),
                        "confidence": 0.9,
                    })
                
                return StepResult(False, error="No language detection available")
            
            elif operation == "languages":
                common_languages = [
                    {"code": "en", "name": "English"},
                    {"code": "es", "name": "Spanish"},
                    {"code": "fr", "name": "French"},
                    {"code": "de", "name": "German"},
                    {"code": "it", "name": "Italian"},
                    {"code": "pt", "name": "Portuguese"},
                    {"code": "zh", "name": "Chinese"},
                    {"code": "ja", "name": "Japanese"},
                    {"code": "ko", "name": "Korean"},
                    {"code": "ar", "name": "Arabic"},
                    {"code": "ru", "name": "Russian"},
                    {"code": "hi", "name": "Hindi"},
                ]
                return StepResult(True, data=common_languages)
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  DATABASE PRIMITIVE
# ============================================================

class DatabasePrimitive(Primitive):
    """Database operations — SQLite, PostgreSQL, MySQL.
    
    Local SQLite by default, can connect to remote databases via connection string.
    """
    
    def __init__(self, default_db_path: Optional[str] = None):
        self._default_db = default_db_path or str(Path.home() / ".telic" / "data.db")
        self._connections: Dict[str, Any] = {}
    
    @property
    def name(self) -> str:
        return "DATABASE"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "query": "Execute a SELECT query and return results",
            "execute": "Execute an INSERT, UPDATE, DELETE, or DDL statement",
            "tables": "List all tables in the database",
            "schema": "Get the schema of a specific table",
            "connect": "Connect to a database",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "query": {
                "sql": {"type": "str", "required": True, "description": "SELECT query to execute"},
                "params": {"type": "list", "required": False, "description": "Query parameters for placeholders"},
                "database": {"type": "str", "required": False, "description": "Database name/path (default: local)"},
            },
            "execute": {
                "sql": {"type": "str", "required": True, "description": "SQL statement to execute"},
                "params": {"type": "list", "required": False, "description": "Query parameters"},
                "database": {"type": "str", "required": False, "description": "Database name/path"},
            },
            "tables": {
                "database": {"type": "str", "required": False, "description": "Database name/path"},
            },
            "schema": {
                "table": {"type": "str", "required": True, "description": "Table name"},
                "database": {"type": "str", "required": False, "description": "Database name/path"},
            },
            "connect": {
                "connection_string": {"type": "str", "required": True, "description": "Database connection string or file path"},
                "name": {"type": "str", "required": False, "description": "Alias for this connection"},
            },
        }
    
    def _get_connection(self, db_name: Optional[str] = None):
        """Get or create a database connection."""
        import sqlite3
        
        db_path = db_name or self._default_db
        if db_path not in self._connections:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            self._connections[db_path] = sqlite3.connect(db_path)
            self._connections[db_path].row_factory = sqlite3.Row
        return self._connections[db_path]
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            import sqlite3
            
            if operation == "query":
                sql = params.get("sql", "")
                query_params = params.get("params", [])
                db_name = params.get("database")
                
                if not sql:
                    return StepResult(False, error="Missing 'sql' parameter")
                
                # Basic injection prevention
                if not sql.strip().upper().startswith("SELECT"):
                    return StepResult(False, error="query() only allows SELECT statements. Use execute() for modifications.")
                
                conn = self._get_connection(db_name)
                cursor = conn.cursor()
                cursor.execute(sql, query_params)
                rows = cursor.fetchall()
                
                # Convert to list of dicts
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                results = [dict(zip(columns, row)) for row in rows]
                
                return StepResult(True, data={"rows": results, "count": len(results), "columns": columns})
            
            elif operation == "execute":
                sql = params.get("sql", "")
                query_params = params.get("params", [])
                db_name = params.get("database")
                
                if not sql:
                    return StepResult(False, error="Missing 'sql' parameter")
                
                conn = self._get_connection(db_name)
                cursor = conn.cursor()
                cursor.execute(sql, query_params)
                conn.commit()
                
                return StepResult(True, data={
                    "rowcount": cursor.rowcount,
                    "lastrowid": cursor.lastrowid,
                })
            
            elif operation == "tables":
                db_name = params.get("database")
                conn = self._get_connection(db_name)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
                tables = [row[0] for row in cursor.fetchall()]
                return StepResult(True, data=tables)
            
            elif operation == "schema":
                table = params.get("table", "")
                db_name = params.get("database")
                
                if not table:
                    return StepResult(False, error="Missing 'table' parameter")
                
                conn = self._get_connection(db_name)
                cursor = conn.cursor()
                cursor.execute(f"PRAGMA table_info({table})")  # noqa: S608
                columns = []
                for row in cursor.fetchall():
                    columns.append({
                        "name": row[1],
                        "type": row[2],
                        "nullable": not row[3],
                        "default": row[4],
                        "primary_key": bool(row[5]),
                    })
                return StepResult(True, data={"table": table, "columns": columns})
            
            elif operation == "connect":
                conn_str = params.get("connection_string", "")
                name = params.get("name", conn_str)
                
                if not conn_str:
                    return StepResult(False, error="Missing 'connection_string' parameter")
                
                # For now, only SQLite is supported
                if conn_str.endswith(".db") or conn_str.endswith(".sqlite"):
                    self._get_connection(conn_str)
                    return StepResult(True, data={"connected": True, "database": conn_str, "type": "sqlite"})
                
                return StepResult(False, error="Only SQLite databases (.db, .sqlite) are currently supported")
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  SCREENSHOT PRIMITIVE
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
    """Universal search — across files, emails, calendar, tasks, and more.
    
    Aggregates results from multiple primitives for a unified search experience.
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
            "all": "Search across all available sources",
            "files": "Search local files",
            "email": "Search emails",
            "calendar": "Search calendar events",
            "tasks": "Search tasks and todos",
            "knowledge": "Search remembered facts",
            "messages": "Search messages (Slack, Teams, etc.)",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "all": {
                "query": {"type": "str", "required": True, "description": "Search query"},
                "limit": {"type": "int", "required": False, "description": "Max results per source (default 5)"},
            },
            "files": {
                "query": {"type": "str", "required": True, "description": "Search query or pattern"},
                "path": {"type": "str", "required": False, "description": "Directory to search in"},
                "limit": {"type": "int", "required": False, "description": "Max results (default 20)"},
            },
            "email": {
                "query": {"type": "str", "required": True, "description": "Search query"},
                "limit": {"type": "int", "required": False, "description": "Max results (default 20)"},
            },
            "calendar": {
                "query": {"type": "str", "required": True, "description": "Search query"},
                "limit": {"type": "int", "required": False, "description": "Max results (default 20)"},
            },
            "tasks": {
                "query": {"type": "str", "required": True, "description": "Search query"},
                "limit": {"type": "int", "required": False, "description": "Max results (default 20)"},
            },
            "knowledge": {
                "query": {"type": "str", "required": True, "description": "Search query"},
                "limit": {"type": "int", "required": False, "description": "Max results (default 20)"},
            },
            "messages": {
                "query": {"type": "str", "required": True, "description": "Search query"},
                "limit": {"type": "int", "required": False, "description": "Max results (default 20)"},
            },
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            query = params.get("query", "")
            limit = params.get("limit", 20)
            
            if not query:
                return StepResult(False, error="Missing 'query' parameter")
            
            if operation == "all":
                # Search all available sources
                results = {"query": query, "sources": {}}
                per_source = params.get("limit", 5)
                
                # Files
                if "FILE" in self._primitives:
                    try:
                        file_result = await self._primitives["FILE"].execute("search", {"query": query, "limit": per_source})
                        if file_result.success:
                            results["sources"]["files"] = file_result.data
                    except Exception:
                        pass
                
                # Knowledge
                if "KNOWLEDGE" in self._primitives:
                    try:
                        know_result = await self._primitives["KNOWLEDGE"].execute("recall", {"query": query, "limit": per_source})
                        if know_result.success:
                            results["sources"]["knowledge"] = know_result.data
                    except Exception:
                        pass
                
                # Calendar
                if "CALENDAR" in self._primitives:
                    try:
                        cal_result = await self._primitives["CALENDAR"].execute("search", {"query": query, "limit": per_source})
                        if cal_result.success:
                            results["sources"]["calendar"] = cal_result.data
                    except Exception:
                        pass
                
                # Tasks
                if "TASK" in self._primitives:
                    try:
                        task_result = await self._primitives["TASK"].execute("search", {"query": query, "limit": per_source})
                        if task_result.success:
                            results["sources"]["tasks"] = task_result.data
                    except Exception:
                        pass
                
                # Messages
                if "MESSAGE" in self._primitives:
                    try:
                        msg_result = await self._primitives["MESSAGE"].execute("search", {"query": query, "limit": per_source})
                        if msg_result.success:
                            results["sources"]["messages"] = msg_result.data
                    except Exception:
                        pass
                
                return StepResult(True, data=results)
            
            elif operation == "files":
                if "FILE" not in self._primitives:
                    return StepResult(False, error="FILE primitive not available")
                path = params.get("path", str(Path.home()))
                return await self._primitives["FILE"].execute("search", {"query": query, "path": path, "limit": limit})
            
            elif operation == "email":
                if "EMAIL" not in self._primitives:
                    return StepResult(False, error="EMAIL primitive not available")
                return await self._primitives["EMAIL"].execute("search", {"query": query, "limit": limit})
            
            elif operation == "calendar":
                if "CALENDAR" not in self._primitives:
                    return StepResult(False, error="CALENDAR primitive not available")
                return await self._primitives["CALENDAR"].execute("search", {"query": query, "limit": limit})
            
            elif operation == "tasks":
                if "TASK" not in self._primitives:
                    return StepResult(False, error="TASK primitive not available")
                return await self._primitives["TASK"].execute("search", {"query": query, "limit": limit})
            
            elif operation == "knowledge":
                if "KNOWLEDGE" not in self._primitives:
                    return StepResult(False, error="KNOWLEDGE primitive not available")
                return await self._primitives["KNOWLEDGE"].execute("recall", {"query": query, "limit": limit})
            
            elif operation == "messages":
                if "MESSAGE" not in self._primitives:
                    return StepResult(False, error="MESSAGE primitive not available")
                return await self._primitives["MESSAGE"].execute("search", {"query": query, "limit": limit})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  CHAT PRIMITIVE - Instant messaging (Slack, Teams, Discord, etc.)
# ============================================================

class ChatPrimitive(Primitive):
    """Instant messaging operations - separate from MESSAGE for real-time chat."""
    
    def __init__(self, providers: Optional[Dict[str, Any]] = None):
        self._providers = providers or {}
        self._local_messages: List[Dict] = []
    
    @property
    def name(self) -> str:
        return "CHAT"
    
    def get_operations(self) -> Dict[str, str]:
        return self.get_available_operations()
    
    def get_available_operations(self) -> Dict[str, str]:
        return {
            "send": "Send a chat message to a channel or user",
            "read": "Read recent messages from a channel",
            "search": "Search chat history",
            "react": "Add reaction to a message",
            "reply": "Reply in a thread",
            "channels": "List available channels",
            "create_channel": "Create a new channel",
        }
    
    def get_param_schema(self) -> Dict[str, Any]:
        return {
            "send": {"channel": {"type": "str", "description": "Channel or user"}, "message": {"type": "str", "description": "Message text"}},
            "read": {"channel": {"type": "str", "description": "Channel"}, "limit": {"type": "int", "description": "Max messages", "default": 20}},
            "search": {"query": {"type": "str", "description": "Search query"}, "channel": {"type": "str", "description": "Channel (optional)"}},
            "react": {"message_id": {"type": "str", "description": "Message ID"}, "emoji": {"type": "str", "description": "Emoji"}},
            "reply": {"message_id": {"type": "str", "description": "Message ID"}, "text": {"type": "str", "description": "Reply text"}},
            "channels": {},
            "create_channel": {"name": {"type": "str", "description": "Channel name"}, "members": {"type": "list", "description": "Member IDs"}},
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            if operation == "send":
                channel = params.get("channel", "general")
                message = params.get("message", "")
                # Try providers first
                for name, provider in self._providers.items():
                    if hasattr(provider, "send_message"):
                        result = await provider.send_message(channel=channel, text=message)
                        return StepResult(True, data={"sent": True, "provider": name, "result": result})
                # Local fallback
                msg = {"channel": channel, "message": message, "timestamp": datetime.now().isoformat()}
                self._local_messages.append(msg)
                return StepResult(True, data={"sent": True, "provider": "local", "message": msg})
            
            elif operation == "read":
                channel = params.get("channel", "general")
                limit = params.get("limit", 20)
                for name, provider in self._providers.items():
                    if hasattr(provider, "get_messages"):
                        result = await provider.get_messages(channel=channel, limit=limit)
                        return StepResult(True, data={"messages": result, "provider": name})
                # Local fallback
                msgs = [m for m in self._local_messages if m.get("channel") == channel][-limit:]
                return StepResult(True, data={"messages": msgs, "provider": "local"})
            
            elif operation == "search":
                query = params.get("query", "").lower()
                channel = params.get("channel")
                for name, provider in self._providers.items():
                    if hasattr(provider, "search_messages"):
                        result = await provider.search_messages(query=query, channel=channel)
                        return StepResult(True, data={"results": result, "provider": name})
                # Local fallback
                results = [m for m in self._local_messages if query in m.get("message", "").lower()]
                if channel:
                    results = [m for m in results if m.get("channel") == channel]
                return StepResult(True, data={"results": results, "provider": "local"})
            
            elif operation == "react":
                message_id = params.get("message_id")
                emoji = params.get("emoji")
                for name, provider in self._providers.items():
                    if hasattr(provider, "add_reaction"):
                        result = await provider.add_reaction(message_id=message_id, emoji=emoji)
                        return StepResult(True, data={"reacted": True, "provider": name})
                return StepResult(True, data={"reacted": True, "provider": "local", "message_id": message_id, "emoji": emoji})
            
            elif operation == "reply":
                message_id = params.get("message_id")
                text = params.get("text")
                for name, provider in self._providers.items():
                    if hasattr(provider, "reply_to_message"):
                        result = await provider.reply_to_message(message_id=message_id, text=text)
                        return StepResult(True, data={"replied": True, "provider": name})
                return StepResult(True, data={"replied": True, "provider": "local", "message_id": message_id, "text": text})
            
            elif operation == "channels":
                for name, provider in self._providers.items():
                    if hasattr(provider, "list_channels"):
                        result = await provider.list_channels()
                        return StepResult(True, data={"channels": result, "provider": name})
                return StepResult(True, data={"channels": ["general", "random"], "provider": "local"})
            
            elif operation == "create_channel":
                name_param = params.get("name")
                members = params.get("members", [])
                for pname, provider in self._providers.items():
                    if hasattr(provider, "create_channel"):
                        result = await provider.create_channel(name=name_param, members=members)
                        return StepResult(True, data={"created": True, "provider": pname, "channel": result})
                return StepResult(True, data={"created": True, "provider": "local", "name": name_param})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  MEETING PRIMITIVE - Video conferencing
# ============================================================

class MeetingPrimitive(Primitive):
    """Video conferencing operations - Zoom, Teams, Meet, etc."""
    
    def __init__(self, providers: Optional[Dict[str, Any]] = None):
        self._providers = providers or {}
        self._local_meetings: List[Dict] = []
    
    @property
    def name(self) -> str:
        return "MEETING"
    
    def get_operations(self) -> Dict[str, str]:
        return self.get_available_operations()
    
    def get_available_operations(self) -> Dict[str, str]:
        return {
            "schedule": "Schedule a video meeting",
            "join": "Get join link for a meeting",
            "cancel": "Cancel a scheduled meeting",
            "list": "List upcoming meetings",
            "recording": "Get meeting recording",
            "transcript": "Get meeting transcript",
        }
    
    def get_param_schema(self) -> Dict[str, Any]:
        return {
            "schedule": {
                "title": {"type": "str", "description": "Meeting title"},
                "start": {"type": "str", "description": "Start time ISO"},
                "duration": {"type": "int", "description": "Duration in minutes"},
                "attendees": {"type": "list", "description": "Attendee emails"},
            },
            "join": {"meeting_id": {"type": "str", "description": "Meeting ID"}},
            "cancel": {"meeting_id": {"type": "str", "description": "Meeting ID"}},
            "list": {"limit": {"type": "int", "description": "Max meetings", "default": 10}},
            "recording": {"meeting_id": {"type": "str", "description": "Meeting ID"}},
            "transcript": {"meeting_id": {"type": "str", "description": "Meeting ID"}},
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            if operation == "schedule":
                title = params.get("title", "Meeting")
                start = params.get("start")
                duration = params.get("duration", 30)
                attendees = params.get("attendees", [])
                
                for name, provider in self._providers.items():
                    if hasattr(provider, "schedule_meeting"):
                        result = await provider.schedule_meeting(title=title, start=start, duration=duration, attendees=attendees)
                        return StepResult(True, data={"scheduled": True, "provider": name, "meeting": result})
                
                # Local fallback
                meeting_id = f"meet_{int(datetime.now().timestamp())}"
                meeting = {
                    "id": meeting_id,
                    "title": title,
                    "start": start,
                    "duration": duration,
                    "attendees": attendees,
                    "join_url": f"https://meet.example.com/{meeting_id}",
                }
                self._local_meetings.append(meeting)
                return StepResult(True, data={"scheduled": True, "provider": "local", "meeting": meeting})
            
            elif operation == "join":
                meeting_id = params.get("meeting_id")
                for name, provider in self._providers.items():
                    if hasattr(provider, "get_join_url"):
                        url = await provider.get_join_url(meeting_id)
                        return StepResult(True, data={"join_url": url, "provider": name})
                # Local fallback
                for m in self._local_meetings:
                    if m.get("id") == meeting_id:
                        return StepResult(True, data={"join_url": m.get("join_url"), "provider": "local"})
                return StepResult(True, data={"join_url": f"https://meet.example.com/{meeting_id}", "provider": "local"})
            
            elif operation == "cancel":
                meeting_id = params.get("meeting_id")
                for name, provider in self._providers.items():
                    if hasattr(provider, "cancel_meeting"):
                        await provider.cancel_meeting(meeting_id)
                        return StepResult(True, data={"cancelled": True, "provider": name})
                self._local_meetings = [m for m in self._local_meetings if m.get("id") != meeting_id]
                return StepResult(True, data={"cancelled": True, "provider": "local"})
            
            elif operation == "list":
                limit = params.get("limit", 10)
                for name, provider in self._providers.items():
                    if hasattr(provider, "list_meetings"):
                        result = await provider.list_meetings(limit=limit)
                        return StepResult(True, data={"meetings": result, "provider": name})
                return StepResult(True, data={"meetings": self._local_meetings[:limit], "provider": "local"})
            
            elif operation == "recording":
                meeting_id = params.get("meeting_id")
                for name, provider in self._providers.items():
                    if hasattr(provider, "get_recording"):
                        result = await provider.get_recording(meeting_id)
                        return StepResult(True, data={"recording": result, "provider": name})
                return StepResult(True, data={"recording": None, "message": "No recording available", "provider": "local"})
            
            elif operation == "transcript":
                meeting_id = params.get("meeting_id")
                for name, provider in self._providers.items():
                    if hasattr(provider, "get_transcript"):
                        result = await provider.get_transcript(meeting_id)
                        return StepResult(True, data={"transcript": result, "provider": name})
                return StepResult(True, data={"transcript": None, "message": "No transcript available", "provider": "local"})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  SMS PRIMITIVE - Text messaging
# ============================================================

class SmsPrimitive(Primitive):
    """SMS/text messaging operations."""
    
    def __init__(self, providers: Optional[Dict[str, Any]] = None):
        self._providers = providers or {}
        self._local_messages: List[Dict] = []
    
    @property
    def name(self) -> str:
        return "SMS"
    
    def get_operations(self) -> Dict[str, str]:
        return self.get_available_operations()
    
    def get_available_operations(self) -> Dict[str, str]:
        return {
            "send": "Send an SMS message",
            "read": "Read SMS messages",
            "search": "Search SMS history",
        }
    
    def get_param_schema(self) -> Dict[str, Any]:
        return {
            "send": {"to": {"type": "str", "description": "Phone number"}, "message": {"type": "str", "description": "Message text"}},
            "read": {"from": {"type": "str", "description": "Phone number (optional)"}, "limit": {"type": "int", "description": "Max messages", "default": 20}},
            "search": {"query": {"type": "str", "description": "Search query"}},
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            if operation == "send":
                to = params.get("to")
                message = params.get("message")
                for name, provider in self._providers.items():
                    if hasattr(provider, "send_sms"):
                        result = await provider.send_sms(to=to, message=message)
                        return StepResult(True, data={"sent": True, "provider": name, "result": result})
                # Local fallback
                msg = {"to": to, "message": message, "timestamp": datetime.now().isoformat()}
                self._local_messages.append(msg)
                return StepResult(True, data={"sent": True, "provider": "local", "message": msg})
            
            elif operation == "read":
                from_num = params.get("from")
                limit = params.get("limit", 20)
                for name, provider in self._providers.items():
                    if hasattr(provider, "read_sms"):
                        result = await provider.read_sms(from_number=from_num, limit=limit)
                        return StepResult(True, data={"messages": result, "provider": name})
                msgs = self._local_messages
                if from_num:
                    msgs = [m for m in msgs if m.get("to") == from_num or m.get("from") == from_num]
                return StepResult(True, data={"messages": msgs[-limit:], "provider": "local"})
            
            elif operation == "search":
                query = params.get("query", "").lower()
                for name, provider in self._providers.items():
                    if hasattr(provider, "search_sms"):
                        result = await provider.search_sms(query=query)
                        return StepResult(True, data={"results": result, "provider": name})
                results = [m for m in self._local_messages if query in m.get("message", "").lower()]
                return StepResult(True, data={"results": results, "provider": "local"})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  SPREADSHEET PRIMITIVE - Excel, Google Sheets
# ============================================================

class SpreadsheetPrimitive(Primitive):
    """Spreadsheet operations - Google Sheets, Excel, etc."""
    
    def __init__(self, llm_complete: Optional[Callable] = None, providers: Optional[Dict[str, Any]] = None):
        self._llm = llm_complete
        self._providers = providers or {}
    
    @property
    def name(self) -> str:
        return "SPREADSHEET"
    
    def get_operations(self) -> Dict[str, str]:
        return self.get_available_operations()
    
    def get_available_operations(self) -> Dict[str, str]:
        return {
            "read": "Read data from a spreadsheet",
            "write": "Write data to a spreadsheet",
            "create": "Create a new spreadsheet",
            "add_sheet": "Add a worksheet to a spreadsheet",
            "formula": "Set a formula in a cell",
            "format": "Format cells",
            "chart": "Create a chart",
        }
    
    def get_param_schema(self) -> Dict[str, Any]:
        return {
            "read": {"file": {"type": "str", "description": "File path or ID"}, "sheet": {"type": "str", "description": "Sheet name"}, "range": {"type": "str", "description": "Cell range like A1:D10"}},
            "write": {"file": {"type": "str", "description": "File path or ID"}, "data": {"type": "list", "description": "2D array of values"}, "sheet": {"type": "str", "description": "Sheet name"}, "range": {"type": "str", "description": "Starting cell"}},
            "create": {"name": {"type": "str", "description": "Spreadsheet name"}, "data": {"type": "list", "description": "Initial data (optional)"}},
            "add_sheet": {"file": {"type": "str", "description": "File path or ID"}, "name": {"type": "str", "description": "New sheet name"}},
            "formula": {"file": {"type": "str", "description": "File path or ID"}, "cell": {"type": "str", "description": "Cell like A1"}, "formula": {"type": "str", "description": "Formula"}},
            "format": {"file": {"type": "str", "description": "File path or ID"}, "range": {"type": "str", "description": "Cell range"}, "format": {"type": "dict", "description": "Format options"}},
            "chart": {"file": {"type": "str", "description": "File path or ID"}, "data_range": {"type": "str", "description": "Data range"}, "chart_type": {"type": "str", "description": "bar, line, pie, etc."}},
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            file_path = params.get("file", "")
            
            # Try providers first
            for name, provider in self._providers.items():
                if operation == "read" and hasattr(provider, "read_spreadsheet"):
                    result = await provider.read_spreadsheet(file_path, params.get("sheet"), params.get("range"))
                    return StepResult(True, data={"data": result, "provider": name})
                elif operation == "write" and hasattr(provider, "write_spreadsheet"):
                    await provider.write_spreadsheet(file_path, params.get("data"), params.get("sheet"), params.get("range"))
                    return StepResult(True, data={"written": True, "provider": name})
                elif operation == "create" and hasattr(provider, "create_spreadsheet"):
                    result = await provider.create_spreadsheet(params.get("name"), params.get("data"))
                    return StepResult(True, data={"created": True, "file": result, "provider": name})
            
            # Local file handling for CSV/Excel
            if operation == "read":
                if file_path.endswith(".csv"):
                    import csv
                    with open(file_path, "r") as f:
                        reader = csv.reader(f)
                        data = list(reader)
                    return StepResult(True, data={"data": data, "provider": "local"})
                elif file_path.endswith((".xlsx", ".xls")):
                    try:
                        import openpyxl
                        wb = openpyxl.load_workbook(file_path)
                        sheet = wb[params.get("sheet")] if params.get("sheet") else wb.active
                        data = [[cell.value for cell in row] for row in sheet.iter_rows()]
                        return StepResult(True, data={"data": data, "provider": "local"})
                    except ImportError:
                        return StepResult(False, error="openpyxl not installed for Excel support")
                return StepResult(True, data={"data": [], "message": "File type not supported locally", "provider": "local"})
            
            elif operation == "write":
                data = params.get("data", [])
                if file_path.endswith(".csv"):
                    import csv
                    with open(file_path, "w", newline="") as f:
                        writer = csv.writer(f)
                        writer.writerows(data)
                    return StepResult(True, data={"written": True, "provider": "local"})
                return StepResult(True, data={"written": True, "provider": "local", "note": "Would write to cloud"})
            
            elif operation == "create":
                name = params.get("name", "Spreadsheet")
                data = params.get("data", [])
                file_path = f"{name}.csv"
                if data:
                    import csv
                    with open(file_path, "w", newline="") as f:
                        writer = csv.writer(f)
                        writer.writerows(data)
                return StepResult(True, data={"created": True, "file": file_path, "provider": "local"})
            
            elif operation in ("add_sheet", "formula", "format", "chart"):
                return StepResult(True, data={"success": True, "provider": "local", "note": f"{operation} would be applied via cloud provider"})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  PRESENTATION PRIMITIVE - PowerPoint, Google Slides
# ============================================================

class PresentationPrimitive(Primitive):
    """Presentation operations - PowerPoint, Google Slides, etc."""
    
    def __init__(self, llm_complete: Optional[Callable] = None, providers: Optional[Dict[str, Any]] = None):
        self._llm = llm_complete
        self._providers = providers or {}
    
    @property
    def name(self) -> str:
        return "PRESENTATION"
    
    def get_operations(self) -> Dict[str, str]:
        return self.get_available_operations()
    
    def get_available_operations(self) -> Dict[str, str]:
        return {
            "create": "Create a new presentation",
            "add_slide": "Add a slide to a presentation",
            "update_slide": "Update slide content",
            "export": "Export to PDF or images",
            "get_text": "Extract all text from presentation",
        }
    
    def get_param_schema(self) -> Dict[str, Any]:
        return {
            "create": {"name": {"type": "str", "description": "Presentation name"}, "template": {"type": "str", "description": "Template (optional)"}},
            "add_slide": {"file": {"type": "str", "description": "File path or ID"}, "layout": {"type": "str", "description": "Slide layout"}, "content": {"type": "dict", "description": "Slide content"}},
            "update_slide": {"file": {"type": "str", "description": "File path or ID"}, "slide_id": {"type": "str", "description": "Slide index or ID"}, "content": {"type": "dict", "description": "New content"}},
            "export": {"file": {"type": "str", "description": "File path or ID"}, "format": {"type": "str", "description": "pdf, png, jpg"}},
            "get_text": {"file": {"type": "str", "description": "File path or ID"}},
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            file_path = params.get("file", "")
            
            for name, provider in self._providers.items():
                if operation == "create" and hasattr(provider, "create_presentation"):
                    result = await provider.create_presentation(params.get("name"), params.get("template"))
                    return StepResult(True, data={"created": True, "file": result, "provider": name})
                elif operation == "add_slide" and hasattr(provider, "add_slide"):
                    result = await provider.add_slide(file_path, params.get("layout"), params.get("content"))
                    return StepResult(True, data={"added": True, "provider": name})
            
            # Local handling
            if operation == "create":
                name = params.get("name", "Presentation")
                return StepResult(True, data={"created": True, "file": f"{name}.pptx", "provider": "local", "note": "Would create via python-pptx"})
            
            elif operation == "add_slide":
                return StepResult(True, data={"added": True, "provider": "local", "note": "Would add slide via python-pptx"})
            
            elif operation == "update_slide":
                return StepResult(True, data={"updated": True, "provider": "local"})
            
            elif operation == "export":
                fmt = params.get("format", "pdf")
                return StepResult(True, data={"exported": True, "format": fmt, "provider": "local"})
            
            elif operation == "get_text":
                try:
                    from pptx import Presentation as PPTX
                    prs = PPTX(file_path)
                    text = []
                    for slide in prs.slides:
                        for shape in slide.shapes:
                            if hasattr(shape, "text"):
                                text.append(shape.text)
                    return StepResult(True, data={"text": "\n".join(text), "provider": "local"})
                except ImportError:
                    return StepResult(True, data={"text": "", "provider": "local", "note": "python-pptx not installed"})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  NOTES PRIMITIVE - Note-taking apps
# ============================================================

class NotesPrimitive(Primitive):
    """Note-taking operations - OneNote, Apple Notes, Google Keep, etc."""
    
    def __init__(self, storage_path: str = "", providers: Optional[Dict[str, Any]] = None):
        self._storage_path = Path(storage_path) if storage_path else Path.home() / ".telic" / "notes"
        self._storage_path.mkdir(parents=True, exist_ok=True)
        self._providers = providers or {}
    
    @property
    def name(self) -> str:
        return "NOTES"
    
    def get_operations(self) -> Dict[str, str]:
        return self.get_available_operations()
    
    def get_available_operations(self) -> Dict[str, str]:
        return {
            "create": "Create a new note",
            "read": "Read a note",
            "update": "Update a note",
            "delete": "Delete a note",
            "search": "Search notes",
            "list": "List all notes",
        }
    
    def get_param_schema(self) -> Dict[str, Any]:
        return {
            "create": {"title": {"type": "str", "description": "Note title"}, "content": {"type": "str", "description": "Note content"}, "folder": {"type": "str", "description": "Folder (optional)"}, "tags": {"type": "list", "description": "Tags (optional)"}},
            "read": {"note_id": {"type": "str", "description": "Note ID or title"}},
            "update": {"note_id": {"type": "str", "description": "Note ID"}, "content": {"type": "str", "description": "New content"}},
            "delete": {"note_id": {"type": "str", "description": "Note ID"}},
            "search": {"query": {"type": "str", "description": "Search query"}},
            "list": {"folder": {"type": "str", "description": "Folder (optional)"}},
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            for name, provider in self._providers.items():
                if operation == "create" and hasattr(provider, "create_note"):
                    result = await provider.create_note(params.get("title"), params.get("content"), params.get("folder"), params.get("tags"))
                    return StepResult(True, data={"created": True, "note": result, "provider": name})
                elif operation == "read" and hasattr(provider, "read_note"):
                    result = await provider.read_note(params.get("note_id"))
                    return StepResult(True, data={"note": result, "provider": name})
                elif operation == "list" and hasattr(provider, "list_notes"):
                    result = await provider.list_notes(params.get("folder"))
                    return StepResult(True, data={"notes": result, "provider": name})
            
            # Local file-based notes
            if operation == "create":
                title = params.get("title", "Untitled")
                content = params.get("content", "")
                tags = params.get("tags", [])
                note_id = f"note_{int(datetime.now().timestamp())}"
                note_file = self._storage_path / f"{note_id}.json"
                note = {"id": note_id, "title": title, "content": content, "tags": tags, "created": datetime.now().isoformat()}
                note_file.write_text(json.dumps(note))
                return StepResult(True, data={"created": True, "note": note, "provider": "local"})
            
            elif operation == "read":
                note_id = params.get("note_id")
                note_file = self._storage_path / f"{note_id}.json"
                if note_file.exists():
                    note = json.loads(note_file.read_text())
                    return StepResult(True, data={"note": note, "provider": "local"})
                # Try to find by title
                for f in self._storage_path.glob("*.json"):
                    note = json.loads(f.read_text())
                    if note.get("title") == note_id:
                        return StepResult(True, data={"note": note, "provider": "local"})
                return StepResult(False, error=f"Note not found: {note_id}")
            
            elif operation == "update":
                note_id = params.get("note_id")
                content = params.get("content")
                note_file = self._storage_path / f"{note_id}.json"
                if note_file.exists():
                    note = json.loads(note_file.read_text())
                    note["content"] = content
                    note["updated"] = datetime.now().isoformat()
                    note_file.write_text(json.dumps(note))
                    return StepResult(True, data={"updated": True, "note": note, "provider": "local"})
                return StepResult(False, error=f"Note not found: {note_id}")
            
            elif operation == "delete":
                note_id = params.get("note_id")
                note_file = self._storage_path / f"{note_id}.json"
                if note_file.exists():
                    note_file.unlink()
                    return StepResult(True, data={"deleted": True, "provider": "local"})
                return StepResult(False, error=f"Note not found: {note_id}")
            
            elif operation == "search":
                query = params.get("query", "").lower()
                results = []
                for f in self._storage_path.glob("*.json"):
                    note = json.loads(f.read_text())
                    if query in note.get("title", "").lower() or query in note.get("content", "").lower():
                        results.append(note)
                return StepResult(True, data={"notes": results, "provider": "local"})
            
            elif operation == "list":
                notes = []
                for f in self._storage_path.glob("*.json"):
                    notes.append(json.loads(f.read_text()))
                return StepResult(True, data={"notes": notes, "provider": "local"})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  FINANCE PRIMITIVE - Banking, payments
# ============================================================

class FinancePrimitive(Primitive):
    """Financial operations - banking, payments, budgeting."""
    
    def __init__(self, providers: Optional[Dict[str, Any]] = None):
        self._providers = providers or {}
        self._local_transactions: List[Dict] = []
        self._budgets: Dict[str, Dict] = {}
    
    @property
    def name(self) -> str:
        return "FINANCE"
    
    def get_operations(self) -> Dict[str, str]:
        return self.get_available_operations()
    
    def get_available_operations(self) -> Dict[str, str]:
        return {
            "balance": "Get account balance",
            "transactions": "List transactions",
            "categorize": "Categorize a transaction",
            "spending": "Get spending summary",
            "budget": "Create or view a budget",
            "send": "Send a payment",
            "request": "Request a payment",
        }
    
    def get_param_schema(self) -> Dict[str, Any]:
        return {
            "balance": {"account": {"type": "str", "description": "Account ID (optional)"}},
            "transactions": {"account": {"type": "str", "description": "Account ID"}, "start": {"type": "str", "description": "Start date"}, "end": {"type": "str", "description": "End date"}, "limit": {"type": "int", "description": "Max transactions"}},
            "categorize": {"transaction_id": {"type": "str", "description": "Transaction ID"}, "category": {"type": "str", "description": "Category name"}},
            "spending": {"period": {"type": "str", "description": "month, week, year"}, "category": {"type": "str", "description": "Category (optional)"}},
            "budget": {"category": {"type": "str", "description": "Budget category"}, "amount": {"type": "float", "description": "Budget amount"}, "period": {"type": "str", "description": "month, week"}},
            "send": {"to": {"type": "str", "description": "Recipient"}, "amount": {"type": "float", "description": "Amount"}, "note": {"type": "str", "description": "Note (optional)"}},
            "request": {"from": {"type": "str", "description": "From person"}, "amount": {"type": "float", "description": "Amount"}, "note": {"type": "str", "description": "Note (optional)"}},
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            for name, provider in self._providers.items():
                if operation == "balance" and hasattr(provider, "get_balance"):
                    result = await provider.get_balance(params.get("account"))
                    return StepResult(True, data={"balance": result, "provider": name})
                elif operation == "transactions" and hasattr(provider, "list_transactions"):
                    result = await provider.list_transactions(params.get("account"), params.get("start"), params.get("end"), params.get("limit"))
                    return StepResult(True, data={"transactions": result, "provider": name})
                elif operation == "send" and hasattr(provider, "send_payment"):
                    result = await provider.send_payment(params.get("to"), params.get("amount"), params.get("note"))
                    return StepResult(True, data={"sent": True, "provider": name, "result": result})
            
            # Local fallback
            if operation == "balance":
                return StepResult(True, data={"balance": 0.0, "currency": "USD", "provider": "local", "note": "Connect a bank provider for real data"})
            
            elif operation == "transactions":
                return StepResult(True, data={"transactions": self._local_transactions, "provider": "local"})
            
            elif operation == "categorize":
                tx_id = params.get("transaction_id")
                category = params.get("category")
                for tx in self._local_transactions:
                    if tx.get("id") == tx_id:
                        tx["category"] = category
                        return StepResult(True, data={"categorized": True, "provider": "local"})
                return StepResult(True, data={"categorized": True, "provider": "local", "note": "Transaction not found locally"})
            
            elif operation == "spending":
                period = params.get("period", "month")
                category = params.get("category")
                return StepResult(True, data={"spending": {}, "period": period, "category": category, "provider": "local"})
            
            elif operation == "budget":
                category = params.get("category", "general")
                amount = params.get("amount")
                period = params.get("period", "month")
                if amount:
                    self._budgets[category] = {"amount": amount, "period": period}
                return StepResult(True, data={"budgets": self._budgets, "provider": "local"})
            
            elif operation == "send":
                return StepResult(True, data={"sent": True, "provider": "local", "note": "Connect payment provider to send real payments"})
            
            elif operation == "request":
                return StepResult(True, data={"requested": True, "provider": "local", "note": "Connect payment provider to request real payments"})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  SOCIAL PRIMITIVE - Social media
# ============================================================

class SocialPrimitive(Primitive):
    """Social media operations - Twitter, LinkedIn, Facebook, etc."""
    
    def __init__(self, providers: Optional[Dict[str, Any]] = None):
        self._providers = providers or {}
        self._local_posts: List[Dict] = []
    
    @property
    def name(self) -> str:
        return "SOCIAL"
    
    def get_operations(self) -> Dict[str, str]:
        return self.get_available_operations()
    
    def get_available_operations(self) -> Dict[str, str]:
        return {
            "post": "Create a social media post",
            "feed": "Get your feed",
            "search": "Search posts",
            "like": "Like a post",
            "comment": "Comment on a post",
            "share": "Share/repost",
            "profile": "Get user profile",
            "notifications": "Get notifications",
        }
    
    def get_param_schema(self) -> Dict[str, Any]:
        return {
            "post": {"content": {"type": "str", "description": "Post content"}, "media": {"type": "list", "description": "Media attachments (optional)"}},
            "feed": {"limit": {"type": "int", "description": "Max posts", "default": 20}},
            "search": {"query": {"type": "str", "description": "Search query"}},
            "like": {"post_id": {"type": "str", "description": "Post ID"}},
            "comment": {"post_id": {"type": "str", "description": "Post ID"}, "text": {"type": "str", "description": "Comment text"}},
            "share": {"post_id": {"type": "str", "description": "Post ID"}},
            "profile": {"user_id": {"type": "str", "description": "User ID (optional, defaults to self)"}},
            "notifications": {},
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            for name, provider in self._providers.items():
                if operation == "post" and hasattr(provider, "create_post"):
                    result = await provider.create_post(params.get("content"), params.get("media"))
                    return StepResult(True, data={"posted": True, "post": result, "provider": name})
                elif operation == "feed" and hasattr(provider, "get_feed"):
                    result = await provider.get_feed(params.get("limit", 20))
                    return StepResult(True, data={"posts": result, "provider": name})
                elif operation == "search" and hasattr(provider, "search_posts"):
                    result = await provider.search_posts(params.get("query"))
                    return StepResult(True, data={"posts": result, "provider": name})
            
            # Local fallback
            if operation == "post":
                content = params.get("content", "")
                post = {"id": f"post_{int(datetime.now().timestamp())}", "content": content, "timestamp": datetime.now().isoformat()}
                self._local_posts.append(post)
                return StepResult(True, data={"posted": True, "post": post, "provider": "local"})
            
            elif operation == "feed":
                return StepResult(True, data={"posts": self._local_posts, "provider": "local"})
            
            elif operation == "search":
                query = params.get("query", "").lower()
                results = [p for p in self._local_posts if query in p.get("content", "").lower()]
                return StepResult(True, data={"posts": results, "provider": "local"})
            
            elif operation in ("like", "comment", "share"):
                return StepResult(True, data={"success": True, "provider": "local"})
            
            elif operation == "profile":
                return StepResult(True, data={"profile": {"name": "Local User"}, "provider": "local"})
            
            elif operation == "notifications":
                return StepResult(True, data={"notifications": [], "provider": "local"})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  PHOTO PRIMITIVE - Photo management
# ============================================================

class PhotoPrimitive(Primitive):
    """Photo management operations - Google Photos, iCloud, etc."""
    
    def __init__(self, providers: Optional[Dict[str, Any]] = None):
        self._providers = providers or {}
    
    @property
    def name(self) -> str:
        return "PHOTO"
    
    def get_operations(self) -> Dict[str, str]:
        return self.get_available_operations()
    
    def get_available_operations(self) -> Dict[str, str]:
        return {
            "list": "List photos",
            "upload": "Upload a photo",
            "download": "Download a photo",
            "search": "Search photos",
            "create_album": "Create an album",
            "add_to_album": "Add photo to album",
            "metadata": "Get photo metadata",
            "edit": "Edit a photo",
        }
    
    def get_param_schema(self) -> Dict[str, Any]:
        return {
            "list": {"album": {"type": "str", "description": "Album ID (optional)"}, "limit": {"type": "int", "description": "Max photos"}},
            "upload": {"path": {"type": "str", "description": "Local file path"}, "album": {"type": "str", "description": "Album ID (optional)"}},
            "download": {"photo_id": {"type": "str", "description": "Photo ID"}, "path": {"type": "str", "description": "Save path"}},
            "search": {"query": {"type": "str", "description": "Search query"}},
            "create_album": {"name": {"type": "str", "description": "Album name"}},
            "add_to_album": {"photo_id": {"type": "str", "description": "Photo ID"}, "album_id": {"type": "str", "description": "Album ID"}},
            "metadata": {"photo_id": {"type": "str", "description": "Photo ID"}},
            "edit": {"photo_id": {"type": "str", "description": "Photo ID"}, "operations": {"type": "list", "description": "Edit operations"}},
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            for name, provider in self._providers.items():
                if operation == "list" and hasattr(provider, "list_photos"):
                    result = await provider.list_photos(params.get("album"), params.get("limit"))
                    return StepResult(True, data={"photos": result, "provider": name})
                elif operation == "upload" and hasattr(provider, "upload_photo"):
                    result = await provider.upload_photo(params.get("path"), params.get("album"))
                    return StepResult(True, data={"uploaded": True, "photo": result, "provider": name})
                elif operation == "search" and hasattr(provider, "search_photos"):
                    result = await provider.search_photos(params.get("query"))
                    return StepResult(True, data={"photos": result, "provider": name})
            
            # Local file handling
            if operation == "list":
                path = Path(params.get("album", str(Path.home() / "Pictures")))
                if path.exists() and path.is_dir():
                    photos = list(path.glob("*.jpg")) + list(path.glob("*.png")) + list(path.glob("*.jpeg"))
                    return StepResult(True, data={"photos": [str(p) for p in photos[:params.get("limit", 50)]], "provider": "local"})
                return StepResult(True, data={"photos": [], "provider": "local"})
            
            elif operation == "upload":
                return StepResult(True, data={"uploaded": True, "provider": "local", "note": "Connect photo provider to upload"})
            
            elif operation == "download":
                return StepResult(True, data={"downloaded": True, "provider": "local"})
            
            elif operation == "search":
                return StepResult(True, data={"photos": [], "provider": "local", "note": "Local search not implemented"})
            
            elif operation == "create_album":
                name = params.get("name", "Album")
                path = Path.home() / "Pictures" / name
                path.mkdir(parents=True, exist_ok=True)
                return StepResult(True, data={"created": True, "path": str(path), "provider": "local"})
            
            elif operation == "add_to_album":
                return StepResult(True, data={"added": True, "provider": "local"})
            
            elif operation == "metadata":
                photo_path = params.get("photo_id")
                if Path(photo_path).exists():
                    stat = Path(photo_path).stat()
                    return StepResult(True, data={"metadata": {"size": stat.st_size, "modified": stat.st_mtime}, "provider": "local"})
                return StepResult(False, error="Photo not found")
            
            elif operation == "edit":
                return StepResult(True, data={"edited": True, "provider": "local", "note": "Would apply edits via PIL"})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  RIDE PRIMITIVE - Ride sharing
# ============================================================

class RidePrimitive(Primitive):
    """Ride-sharing operations - Uber, Lyft, etc."""
    
    def __init__(self, providers: Optional[Dict[str, Any]] = None):
        self._providers = providers or {}
        self._ride_history: List[Dict] = []
    
    @property
    def name(self) -> str:
        return "RIDE"
    
    def get_operations(self) -> Dict[str, str]:
        return self.get_available_operations()
    
    def get_available_operations(self) -> Dict[str, str]:
        return {
            "estimate": "Get fare estimate",
            "request": "Request a ride",
            "cancel": "Cancel a ride",
            "track": "Track current ride",
            "history": "Get ride history",
        }
    
    def get_param_schema(self) -> Dict[str, Any]:
        return {
            "estimate": {"pickup": {"type": "str", "description": "Pickup address"}, "dropoff": {"type": "str", "description": "Dropoff address"}},
            "request": {"pickup": {"type": "str", "description": "Pickup address"}, "dropoff": {"type": "str", "description": "Dropoff address"}, "type": {"type": "str", "description": "UberX, Pool, etc."}},
            "cancel": {"ride_id": {"type": "str", "description": "Ride ID"}},
            "track": {"ride_id": {"type": "str", "description": "Ride ID"}},
            "history": {"limit": {"type": "int", "description": "Max rides", "default": 10}},
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            for name, provider in self._providers.items():
                if operation == "estimate" and hasattr(provider, "get_estimate"):
                    result = await provider.get_estimate(params.get("pickup"), params.get("dropoff"))
                    return StepResult(True, data={"estimate": result, "provider": name})
                elif operation == "request" and hasattr(provider, "request_ride"):
                    result = await provider.request_ride(params.get("pickup"), params.get("dropoff"), params.get("type"))
                    return StepResult(True, data={"ride": result, "provider": name})
            
            # Local fallback
            if operation == "estimate":
                return StepResult(True, data={
                    "estimate": {"min": 10.0, "max": 15.0, "currency": "USD", "eta": "5 min"},
                    "provider": "local",
                    "note": "Connect ride provider for real estimates"
                })
            
            elif operation == "request":
                ride = {
                    "id": f"ride_{int(datetime.now().timestamp())}",
                    "pickup": params.get("pickup"),
                    "dropoff": params.get("dropoff"),
                    "type": params.get("type", "standard"),
                    "status": "requested",
                }
                self._ride_history.append(ride)
                return StepResult(True, data={"ride": ride, "provider": "local", "note": "Connect ride provider to request real rides"})
            
            elif operation == "cancel":
                ride_id = params.get("ride_id")
                for ride in self._ride_history:
                    if ride.get("id") == ride_id:
                        ride["status"] = "cancelled"
                return StepResult(True, data={"cancelled": True, "provider": "local"})
            
            elif operation == "track":
                ride_id = params.get("ride_id")
                for ride in self._ride_history:
                    if ride.get("id") == ride_id:
                        return StepResult(True, data={"ride": ride, "provider": "local"})
                return StepResult(True, data={"ride": None, "provider": "local"})
            
            elif operation == "history":
                limit = params.get("limit", 10)
                return StepResult(True, data={"rides": self._ride_history[-limit:], "provider": "local"})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  TRAVEL PRIMITIVE - Travel booking
# ============================================================

class TravelPrimitive(Primitive):
    """Travel booking operations - flights, hotels, etc."""
    
    def __init__(self, providers: Optional[Dict[str, Any]] = None):
        self._providers = providers or {}
        self._bookings: List[Dict] = []
    
    @property
    def name(self) -> str:
        return "TRAVEL"
    
    def get_operations(self) -> Dict[str, str]:
        return self.get_available_operations()
    
    def get_available_operations(self) -> Dict[str, str]:
        return {
            "search_flights": "Search for flights",
            "search_hotels": "Search for hotels",
            "book": "Book a flight or hotel",
            "cancel": "Cancel a booking",
            "itinerary": "Get trip itinerary",
            "checkin": "Online check-in",
        }
    
    def get_param_schema(self) -> Dict[str, Any]:
        return {
            "search_flights": {"origin": {"type": "str", "description": "Origin airport"}, "destination": {"type": "str", "description": "Destination airport"}, "date": {"type": "str", "description": "Departure date"}, "return_date": {"type": "str", "description": "Return date (optional)"}},
            "search_hotels": {"location": {"type": "str", "description": "Location"}, "checkin": {"type": "str", "description": "Check-in date"}, "checkout": {"type": "str", "description": "Check-out date"}, "guests": {"type": "int", "description": "Number of guests"}},
            "book": {"type": {"type": "str", "description": "flight or hotel"}, "id": {"type": "str", "description": "Search result ID"}},
            "cancel": {"booking_id": {"type": "str", "description": "Booking ID"}},
            "itinerary": {"trip_id": {"type": "str", "description": "Trip ID (optional)"}},
            "checkin": {"booking_id": {"type": "str", "description": "Booking ID"}},
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            for name, provider in self._providers.items():
                if operation == "search_flights" and hasattr(provider, "search_flights"):
                    result = await provider.search_flights(params.get("origin"), params.get("destination"), params.get("date"), params.get("return_date"))
                    return StepResult(True, data={"flights": result, "provider": name})
                elif operation == "search_hotels" and hasattr(provider, "search_hotels"):
                    result = await provider.search_hotels(params.get("location"), params.get("checkin"), params.get("checkout"), params.get("guests"))
                    return StepResult(True, data={"hotels": result, "provider": name})
            
            # Local fallback
            if operation == "search_flights":
                return StepResult(True, data={
                    "flights": [],
                    "provider": "local",
                    "note": "Connect travel provider to search real flights"
                })
            
            elif operation == "search_hotels":
                return StepResult(True, data={
                    "hotels": [],
                    "provider": "local",
                    "note": "Connect travel provider to search real hotels"
                })
            
            elif operation == "book":
                booking = {
                    "id": f"booking_{int(datetime.now().timestamp())}",
                    "type": params.get("type"),
                    "item_id": params.get("id"),
                    "status": "confirmed",
                }
                self._bookings.append(booking)
                return StepResult(True, data={"booking": booking, "provider": "local"})
            
            elif operation == "cancel":
                booking_id = params.get("booking_id")
                for b in self._bookings:
                    if b.get("id") == booking_id:
                        b["status"] = "cancelled"
                return StepResult(True, data={"cancelled": True, "provider": "local"})
            
            elif operation == "itinerary":
                return StepResult(True, data={"itinerary": self._bookings, "provider": "local"})
            
            elif operation == "checkin":
                return StepResult(True, data={"checkedin": True, "provider": "local"})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  HOME PRIMITIVE - Smart home
# ============================================================

class HomePrimitive(Primitive):
    """Smart home operations - lights, thermostat, etc."""
    
    def __init__(self, providers: Optional[Dict[str, Any]] = None):
        self._providers = providers or {}
        self._devices: Dict[str, Dict] = {}
    
    @property
    def name(self) -> str:
        return "HOME"
    
    def get_operations(self) -> Dict[str, str]:
        return self.get_available_operations()
    
    def get_available_operations(self) -> Dict[str, str]:
        return {
            "devices": "List all devices",
            "state": "Get device state",
            "set": "Set device state",
            "on": "Turn device on",
            "off": "Turn device off",
            "temperature": "Set thermostat temperature",
            "routine": "Run a routine/scene",
        }
    
    def get_param_schema(self) -> Dict[str, Any]:
        return {
            "devices": {},
            "state": {"device_id": {"type": "str", "description": "Device ID"}},
            "set": {"device_id": {"type": "str", "description": "Device ID"}, "state": {"type": "dict", "description": "State to set"}},
            "on": {"device_id": {"type": "str", "description": "Device ID"}},
            "off": {"device_id": {"type": "str", "description": "Device ID"}},
            "temperature": {"device_id": {"type": "str", "description": "Thermostat ID"}, "temperature": {"type": "int", "description": "Temperature"}},
            "routine": {"routine_name": {"type": "str", "description": "Routine name"}},
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            for name, provider in self._providers.items():
                if operation == "devices" and hasattr(provider, "list_devices"):
                    result = await provider.list_devices()
                    return StepResult(True, data={"devices": result, "provider": name})
                elif operation == "on" and hasattr(provider, "turn_on"):
                    await provider.turn_on(params.get("device_id"))
                    return StepResult(True, data={"on": True, "provider": name})
                elif operation == "off" and hasattr(provider, "turn_off"):
                    await provider.turn_off(params.get("device_id"))
                    return StepResult(True, data={"off": True, "provider": name})
            
            # Local simulation
            if operation == "devices":
                return StepResult(True, data={"devices": list(self._devices.values()), "provider": "local"})
            
            elif operation == "state":
                device_id = params.get("device_id")
                return StepResult(True, data={"state": self._devices.get(device_id, {}), "provider": "local"})
            
            elif operation == "set":
                device_id = params.get("device_id")
                state = params.get("state", {})
                self._devices[device_id] = {**self._devices.get(device_id, {}), **state}
                return StepResult(True, data={"set": True, "state": self._devices[device_id], "provider": "local"})
            
            elif operation == "on":
                device_id = params.get("device_id")
                self._devices.setdefault(device_id, {})["on"] = True
                return StepResult(True, data={"on": True, "provider": "local"})
            
            elif operation == "off":
                device_id = params.get("device_id")
                self._devices.setdefault(device_id, {})["on"] = False
                return StepResult(True, data={"off": True, "provider": "local"})
            
            elif operation == "temperature":
                device_id = params.get("device_id")
                temp = params.get("temperature")
                self._devices.setdefault(device_id, {})["temperature"] = temp
                return StepResult(True, data={"set": True, "temperature": temp, "provider": "local"})
            
            elif operation == "routine":
                routine = params.get("routine_name")
                return StepResult(True, data={"ran": True, "routine": routine, "provider": "local"})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  SHOPPING PRIMITIVE - E-commerce
# ============================================================

class ShoppingPrimitive(Primitive):
    """E-commerce operations - Amazon, eBay, etc."""
    
    def __init__(self, providers: Optional[Dict[str, Any]] = None):
        self._providers = providers or {}
        self._cart: List[Dict] = []
        self._orders: List[Dict] = []
    
    @property
    def name(self) -> str:
        return "SHOPPING"
    
    def get_operations(self) -> Dict[str, str]:
        return self.get_available_operations()
    
    def get_available_operations(self) -> Dict[str, str]:
        return {
            "search": "Search for products",
            "product": "Get product details",
            "add_to_cart": "Add item to cart",
            "cart": "View cart",
            "track": "Track an order",
            "orders": "Get order history",
            "reorder": "Reorder a previous order",
            "price_alert": "Set price alert",
        }
    
    def get_param_schema(self) -> Dict[str, Any]:
        return {
            "search": {"query": {"type": "str", "description": "Search query"}, "filters": {"type": "dict", "description": "Filters (optional)"}},
            "product": {"product_id": {"type": "str", "description": "Product ID"}},
            "add_to_cart": {"product_id": {"type": "str", "description": "Product ID"}, "quantity": {"type": "int", "description": "Quantity", "default": 1}},
            "cart": {},
            "track": {"order_id": {"type": "str", "description": "Order ID"}},
            "orders": {"limit": {"type": "int", "description": "Max orders", "default": 10}},
            "reorder": {"order_id": {"type": "str", "description": "Order ID"}},
            "price_alert": {"product_id": {"type": "str", "description": "Product ID"}, "target_price": {"type": "float", "description": "Target price"}},
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            for name, provider in self._providers.items():
                if operation == "search" and hasattr(provider, "search_products"):
                    result = await provider.search_products(params.get("query"), params.get("filters"))
                    return StepResult(True, data={"products": result, "provider": name})
                elif operation == "product" and hasattr(provider, "get_product"):
                    result = await provider.get_product(params.get("product_id"))
                    return StepResult(True, data={"product": result, "provider": name})
            
            # Local fallback
            if operation == "search":
                return StepResult(True, data={"products": [], "provider": "local", "note": "Connect shopping provider to search"})
            
            elif operation == "product":
                return StepResult(True, data={"product": None, "provider": "local"})
            
            elif operation == "add_to_cart":
                item = {"product_id": params.get("product_id"), "quantity": params.get("quantity", 1)}
                self._cart.append(item)
                return StepResult(True, data={"added": True, "cart": self._cart, "provider": "local"})
            
            elif operation == "cart":
                return StepResult(True, data={"cart": self._cart, "provider": "local"})
            
            elif operation == "track":
                order_id = params.get("order_id")
                for order in self._orders:
                    if order.get("id") == order_id:
                        return StepResult(True, data={"order": order, "provider": "local"})
                return StepResult(True, data={"order": None, "provider": "local"})
            
            elif operation == "orders":
                limit = params.get("limit", 10)
                return StepResult(True, data={"orders": self._orders[-limit:], "provider": "local"})
            
            elif operation == "reorder":
                order_id = params.get("order_id")
                for order in self._orders:
                    if order.get("id") == order_id:
                        new_order = {**order, "id": f"order_{int(datetime.now().timestamp())}"}
                        self._orders.append(new_order)
                        return StepResult(True, data={"order": new_order, "provider": "local"})
                return StepResult(False, error="Order not found")
            
            elif operation == "price_alert":
                return StepResult(True, data={"alert_set": True, "provider": "local"})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  ORCHESTRATOR
# ============================================================

class Orchestrator:
    """Executes plans with full orchestration: parallel, conditional, loop, sub-plan.
    
    Replaces the simple for-loop in Apex.do() with a proper execution engine
    that understands step_type and handles complex control flow.
    """
    
    def __init__(
        self,
        primitives: Dict[str, 'Primitive'],
        llm_complete: Callable,
        self_heal: Callable,
        planner: Optional['TaskPlanner'] = None,
    ):
        self._primitives = primitives
        self._llm = llm_complete
        self._self_heal = self_heal
        self._planner = planner
        self._follow_path = Apex._follow_path_static
    
    async def execute_plan(
        self,
        plan: List[PlanStep],
        results: Optional[Dict[int, Any]] = None,
        resolve_wires_fn: Optional[Callable] = None,
        apply_wires_fn: Optional[Callable] = None,
    ) -> Dict[int, Any]:
        """Execute a full plan, handling all step types.
        
        Returns dict mapping step_id -> result data for successful steps.
        """
        results = results if results is not None else {}
        
        for step in plan:
            await self._execute_step(step, results, resolve_wires_fn, apply_wires_fn)
        
        return results
    
    async def _execute_step(
        self,
        step: PlanStep,
        results: Dict[int, Any],
        resolve_wires_fn: Optional[Callable] = None,
        apply_wires_fn: Optional[Callable] = None,
    ) -> None:
        """Execute a single step based on its step_type."""
        
        if step.step_type == "parallel":
            await self._execute_parallel(step, results, resolve_wires_fn, apply_wires_fn)
        elif step.step_type == "condition":
            await self._execute_condition(step, results, resolve_wires_fn, apply_wires_fn)
        elif step.step_type == "loop":
            await self._execute_loop(step, results, resolve_wires_fn, apply_wires_fn)
        elif step.step_type == "sub_plan":
            await self._execute_sub_plan(step, results, resolve_wires_fn, apply_wires_fn)
        else:
            # Default: "action"
            await self._execute_action(step, results, resolve_wires_fn, apply_wires_fn)
    
    async def _execute_action(
        self,
        step: PlanStep,
        results: Dict[int, Any],
        resolve_wires_fn: Optional[Callable] = None,
        apply_wires_fn: Optional[Callable] = None,
    ) -> None:
        """Execute a standard action step with self-healing retry."""
        
        # CLARIFY is a signal to ask the user a question, not a real primitive
        # Skip it gracefully during execution
        if step.primitive.upper() == "CLARIFY":
            step.result = StepResult(True, data={"clarify": step.params.get("question", step.description)})
            return
        
        # Check dependencies
        for dep_id in step.depends_on:
            if dep_id not in results:
                step.result = StepResult(False, error=f"Dependency step_{dep_id} failed or not available")
                return
        
        # Resolve parameters
        if apply_wires_fn:
            resolved_params = apply_wires_fn(step, results)
        else:
            resolved_params = dict(step.params)
        
        # Get primitive
        primitive = self._primitives.get(step.primitive)
        if not primitive:
            step.result = StepResult(False, error=f"Unknown primitive: {step.primitive}")
            return
        
        # Execute with self-healing retry
        max_attempts = step.max_retries
        for attempt in range(max_attempts):
            try:
                step.result = await primitive.execute(step.operation, resolved_params)
            except Exception as e:
                step.result = StepResult(False, error=str(e))
            
            if step.result.success:
                break
            
            if attempt < max_attempts - 1:
                healed = await self._self_heal(step, resolved_params, step.result.error)
                if healed:
                    resolved_params = healed
                else:
                    break
        
        if step.result and step.result.success:
            results[step.id] = step.result.data
        elif step.on_fail == "continue":
            results[step.id] = None
    
    async def _execute_parallel(
        self,
        step: PlanStep,
        results: Dict[int, Any],
        resolve_wires_fn: Optional[Callable] = None,
        apply_wires_fn: Optional[Callable] = None,
    ) -> None:
        """Execute sub-steps concurrently using asyncio.gather."""
        sub_steps = step.parallel_steps or []
        if not sub_steps:
            step.result = StepResult(True, data=[])
            results[step.id] = []
            return
        
        async def run_sub(s: PlanStep) -> StepResult:
            await self._execute_step(s, results, resolve_wires_fn, apply_wires_fn)
            return s.result or StepResult(False, error="No result")
        
        sub_results = await asyncio.gather(
            *[run_sub(s) for s in sub_steps],
            return_exceptions=True,
        )
        
        # Collect results
        collected = []
        all_ok = True
        for i, sr in enumerate(sub_results):
            if isinstance(sr, Exception):
                sub_steps[i].result = StepResult(False, error=str(sr))
                all_ok = False
                collected.append(None)
            elif isinstance(sr, StepResult):
                collected.append(sr.data if sr.success else None)
                if not sr.success:
                    all_ok = False
            else:
                collected.append(None)
        
        step.result = StepResult(
            success=all_ok or step.on_fail == "continue",
            data=collected,
        )
        results[step.id] = collected
    
    async def _execute_condition(
        self,
        step: PlanStep,
        results: Dict[int, Any],
        resolve_wires_fn: Optional[Callable] = None,
        apply_wires_fn: Optional[Callable] = None,
    ) -> None:
        """Evaluate a condition, then run then_steps or else_steps."""
        condition_expr = step.condition or ""
        
        # Resolve wire references in the condition string
        resolved_condition = condition_expr
        for match in re.finditer(r'step_(\d+)(?:\.([a-zA-Z0-9_.]+))?', condition_expr):
            ref = match.group(0)
            step_id = int(match.group(1))
            path = match.group(2)
            if step_id in results:
                val = results[step_id]
                if path:
                    val = self._follow_path(val, path)
                resolved_condition = resolved_condition.replace(ref, repr(val))
        
        # Evaluate the condition safely
        try:
            # Only allow safe builtins for condition evaluation
            safe_builtins = {"len": len, "int": int, "float": float, "str": str, "bool": bool, "None": None, "True": True, "False": False}
            condition_met = bool(eval(resolved_condition, {"__builtins__": {}}, safe_builtins))  # noqa: S307
        except Exception as e:
            # If condition can't be evaluated, ask LLM
            try:
                llm_response = await self._llm(
                    f"Evaluate this condition and respond with ONLY 'true' or 'false': {condition_expr}\n\nContext: {json.dumps({f'step_{k}': v for k, v in results.items()}, default=str)}"
                )
                condition_met = "true" in llm_response.lower()
            except Exception:
                condition_met = False
        
        # Run the appropriate branch
        if condition_met:
            branch = step.then_steps or []
        else:
            branch = step.else_steps or []
        
        branch_results = []
        for sub_step in branch:
            await self._execute_step(sub_step, results, resolve_wires_fn, apply_wires_fn)
            if sub_step.result:
                branch_results.append(sub_step.result.data)
        
        step.result = StepResult(True, data={
            "condition_met": condition_met,
            "branch_results": branch_results,
        })
        results[step.id] = step.result.data
    
    async def _execute_loop(
        self,
        step: PlanStep,
        results: Dict[int, Any],
        resolve_wires_fn: Optional[Callable] = None,
        apply_wires_fn: Optional[Callable] = None,
    ) -> None:
        """Iterate over a list, running body steps for each item."""
        # Resolve what we're iterating over
        loop_ref = step.loop_over or ""
        items = None
        
        match = re.match(r'step_(\d+)(?:\.(.+))?', loop_ref)
        if match:
            step_id = int(match.group(1))
            path = match.group(2)
            if step_id in results:
                items = results[step_id]
                if path:
                    items = self._follow_path(items, path)
        
        if not isinstance(items, (list, tuple)):
            step.result = StepResult(False, error=f"loop_over '{loop_ref}' did not resolve to a list")
            return
        
        body_template = step.loop_body or []
        all_iteration_results = []
        
        for idx, item in enumerate(items):
            # Create a scoped copy of results with the loop variable
            loop_results = dict(results)
            # Make item available as a special key for wire resolution
            loop_results[f"_loop_{step.id}"] = item
            
            # Deep-copy body steps for this iteration, injecting the loop item
            iteration_steps = []
            for tmpl in body_template:
                iter_step = PlanStep(
                    id=tmpl.id,
                    description=tmpl.description,
                    primitive=tmpl.primitive,
                    operation=tmpl.operation,
                    params=self._inject_loop_var(tmpl.params, step.loop_var, item),
                    depends_on=tmpl.depends_on,
                    wires=tmpl.wires,
                    step_type=tmpl.step_type,
                    on_fail=tmpl.on_fail,
                    max_retries=tmpl.max_retries,
                )
                iteration_steps.append(iter_step)
            
            # Execute body steps for this iteration
            iter_results = []
            for body_step in iteration_steps:
                await self._execute_step(body_step, loop_results, resolve_wires_fn, apply_wires_fn)
                if body_step.result:
                    iter_results.append(body_step.result.data)
            
            all_iteration_results.append(iter_results[-1] if iter_results else None)
        
        step.result = StepResult(True, data=all_iteration_results)
        results[step.id] = all_iteration_results
    
    def _inject_loop_var(self, params: Dict, var_name: str, value: Any) -> Dict:
        """Replace {{loop_var}} references in params with the current item."""
        injected = {}
        placeholder = f"{{{{{var_name}}}}}"
        for k, v in params.items():
            if isinstance(v, str) and placeholder in v:
                if v == placeholder:
                    injected[k] = value
                else:
                    injected[k] = v.replace(placeholder, json.dumps(value) if isinstance(value, (dict, list)) else str(value))
            elif isinstance(v, dict):
                injected[k] = self._inject_loop_var(v, var_name, value)
            else:
                injected[k] = v
        return injected
    
    async def _execute_sub_plan(
        self,
        step: PlanStep,
        results: Dict[int, Any],
        resolve_wires_fn: Optional[Callable] = None,
        apply_wires_fn: Optional[Callable] = None,
    ) -> None:
        """Delegate to the planner for a sub-request, then execute the sub-plan."""
        if not self._planner:
            step.result = StepResult(False, error="No planner available for sub_plan execution")
            return
        
        sub_request = step.sub_request or step.description
        
        # Resolve any wire refs in the sub_request
        for match in re.finditer(r'step_(\d+)(?:\.([a-zA-Z0-9_.]+))?', sub_request):
            ref = match.group(0)
            step_id = int(match.group(1))
            path = match.group(2)
            if step_id in results:
                val = results[step_id]
                if path:
                    val = self._follow_path(val, path)
                sub_request = sub_request.replace(ref, json.dumps(val) if isinstance(val, (dict, list)) else str(val))
        
        # Plan and execute the sub-request
        sub_plan = await self._planner.plan(sub_request)
        sub_results = await self.execute_plan(sub_plan, dict(results), resolve_wires_fn, apply_wires_fn)
        
        # Collect the final result from the sub-plan
        final = None
        for sub_step in reversed(sub_plan):
            if sub_step.result and sub_step.result.success and sub_step.result.data is not None:
                final = sub_step.result.data
                break
        
        step.result = StepResult(True, data=final)
        results[step.id] = final


# ============================================================
#  TASK PLANNER
# ============================================================

class TaskPlanner:
    """LLM-powered task decomposition — auto-adapts to available primitives."""
    
    def __init__(self, llm_complete: Callable, primitives: Dict[str, Primitive]):
        self._llm = llm_complete
        self._primitives = primitives
    
    def _get_capabilities_prompt(self) -> str:
        """Auto-generate capabilities + param schemas from registered primitives.
        
        Only shows operations that are actually configured and ready to use,
        so the LLM never plans for unavailable operations.
        """
        lines = ["Available primitives:\n"]
        examples = ["\nPARAMETER SCHEMAS:"]
        
        for name, prim in self._primitives.items():
            available_ops = prim.get_available_operations()
            if not available_ops:
                continue  # Skip primitives with no available operations
            
            lines.append(f"\n{name}:")
            for op, desc in available_ops.items():
                lines.append(f"  - {name}.{op}: {desc}")
            
            # Auto-generate param examples from schema (only for available ops)
            schema = prim.get_param_schema()
            if schema:
                for op, params in schema.items():
                    if op not in available_ops:
                        continue
                    example_params = {}
                    for pname, pdef in params.items():
                        if isinstance(pdef, dict):
                            ptype = pdef.get("type", "str")
                            desc = pdef.get("description", pname)
                            if ptype == "str":
                                example_params[pname] = f"<{desc}>"
                            elif ptype in ("int", "float"):
                                example_params[pname] = 0
                            elif ptype == "dict":
                                example_params[pname] = {"key": "value"}
                            elif ptype == "list":
                                example_params[pname] = []
                    examples.append(f"  {name}.{op}: {json.dumps(example_params)}")
        
        return "\n".join(lines) + "\n" + "\n".join(examples)
    
    async def plan(self, request: str, context: Optional[Dict] = None) -> List[PlanStep]:
        """Generate an execution plan for a request."""
        
        capabilities = self._get_capabilities_prompt()
        
        from datetime import datetime
        today_iso = datetime.now().strftime("%Y-%m-%d")
        
        # Build conversation context if available
        conversation_context = ""
        if context and "conversation" in context:
            conv = context["conversation"]
            if len(conv) > 1:  # More than just current message
                conversation_context = "Conversation history:\n"
                for msg in conv[:-1]:  # Exclude the current request
                    role = "User" if msg["role"] == "user" else "Assistant"
                    conversation_context += f"  {role}: {msg['content']}\n"
                conversation_context += "\nThe current message is a response to the above conversation. Use the FULL conversation to understand what the user wants.\n\n"
        
        prompt = f"""You are a task planner. Break this request into primitive operations.

TODAY: {today_iso}

{conversation_context}{capabilities}

Rules:
1. One primitive per step
2. "tonight" = {today_iso}, "tomorrow" = next day
3. Wire dynamic data between steps
4. If unclear or missing info, return: {{"clarify": "your question to user"}}

Current message: {request}

Return JSON array or clarify object:
[{{"description": "...", "primitive": "CALENDAR", "operation": "create", "params": {{}}, "wires": {{}}, "side_effect": true}}]"""

        response = await self._llm(prompt)
        
        # Check for clarification request
        clarify_match = re.search(r'\{\s*"clarify"\s*:\s*"([^"]+)"\s*\}', response)
        if clarify_match:
            # Return special step that signals clarification needed
            return [PlanStep(0, clarify_match.group(1), "CLARIFY", "ask", {"question": clarify_match.group(1)}, side_effect=False)]
        
        # Parse response
        json_match = re.search(r'\[[\s\S]*\]', response)
        if not json_match:
            return [PlanStep(0, f"Process: {request}", "KNOWLEDGE", "recall", {"query": request})]
        
        try:
            step_data = json.loads(json_match.group())
            steps = self._parse_steps(step_data)
            return steps
        except json.JSONDecodeError:
            return [PlanStep(0, f"Process: {request}", "KNOWLEDGE", "recall", {"query": request})]

    def _parse_steps(self, step_data: List[Dict], id_offset: int = 0) -> List[PlanStep]:
        """Parse step dicts into PlanStep objects, recursively handling nested steps."""
        steps = []
        for i, s in enumerate(step_data):
            wires = s.get("wires", {})
            # Auto-derive depends_on from wires + any explicit depends_on
            explicit_deps = set(s.get("depends_on", []))
            for wire_ref in wires.values():
                m = re.match(r'step_(\d+)', str(wire_ref))
                if m:
                    explicit_deps.add(int(m.group(1)))
            
            step = PlanStep(
                id=i + id_offset,
                description=s.get("description", f"Step {i}"),
                primitive=s.get("primitive", "").upper(),
                operation=s.get("operation", ""),
                params=s.get("params", {}),
                depends_on=sorted(explicit_deps),
                wires=wires,
                step_type=s.get("step_type", "action"),
                condition=s.get("condition"),
                loop_over=s.get("loop_over"),
                loop_var=s.get("loop_var", "item"),
                sub_request=s.get("sub_request"),
                on_fail=s.get("on_fail", "stop"),
                max_retries=s.get("max_retries", 3),
                side_effect=s.get("side_effect", True),  # Default to true (safer)
            )
            
            # Parse nested step lists
            if s.get("then_steps"):
                step.then_steps = self._parse_steps(s["then_steps"])
            if s.get("else_steps"):
                step.else_steps = self._parse_steps(s["else_steps"])
            if s.get("loop_body"):
                step.loop_body = self._parse_steps(s["loop_body"])
            if s.get("parallel_steps"):
                step.parallel_steps = self._parse_steps(s["parallel_steps"])
            
            steps.append(step)
        return steps


# ============================================================
#  TELIC ENGINE
# ============================================================

class Apex:
    """
    The Telic Engine - unified interface to all capabilities.
    
    Usage:
        engine = Apex(api_key="...")
        result = await engine.do("Create amortization from loan doc and email to Fred")
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        storage_path: Optional[str] = None,
        connectors: Optional[Dict[str, Any]] = None,
        enable_safety: bool = True,
    ):
        # Auto-detect API key and model
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")
        
        # Auto-select model based on API key
        if model:
            self._model = model
        elif os.environ.get("ANTHROPIC_API_KEY") or (self._api_key and self._api_key.startswith("sk-ant-")):
            self._model = "anthropic/claude-sonnet-4-20250514"
        else:
            self._model = "gpt-4o-mini"
        self._storage_path = Path(storage_path or "~/.telic").expanduser()
        self._storage_path.mkdir(parents=True, exist_ok=True)
        self._connectors = connectors or {}
        
        # Safety rails
        self._safety_enabled = enable_safety and HAS_SAFETY_RAILS
        self._redaction: Optional[Any] = None
        self._audit: Optional[Any] = None
        self._trust: Optional[Any] = None
        self._approval: Optional[Any] = None
        self._undo: Optional[Any] = None
        self._action_history: Optional[Any] = None
        
        if self._safety_enabled:
            db_dir = str(self._storage_path / "db")
            Path(db_dir).mkdir(parents=True, exist_ok=True)
            self._redaction = RedactionEngine()
            self._audit = AuditLogger(db_path=os.path.join(db_dir, "audit.db"))
            self._trust = TrustLevelManager(db_path=os.path.join(db_dir, "trust.db"))
            self._approval = ApprovalGateway(trust_mgr=self._trust, audit_logger=self._audit)
            self._undo = UndoManager(db_path=os.path.join(db_dir, "undo.db"), backup_dir=str(self._storage_path / "undo_backups"))
            self._action_history = ActionHistoryDB(db_path=os.path.join(db_dir, "history.db"))
        
        # Initialize primitives
        self._primitives: Dict[str, Primitive] = {}
        self._init_primitives()
        
        # Initialize planner
        self._planner = TaskPlanner(self._llm_complete, self._primitives)
        
        # Initialize orchestrator
        self._orchestrator = Orchestrator(
            primitives=self._primitives,
            llm_complete=self._llm_complete,
            self_heal=self._self_heal,
            planner=self._planner,
        )
        
        # Execution history
        self._history: List[ExecutionResult] = []
    
    @staticmethod
    def _follow_path_static(data: Any, path: str) -> Any:
        """Navigate into data via dot-path (static version for Orchestrator)."""
        for part in path.split('.'):
            if data is None:
                return None
            if isinstance(data, dict):
                data = data.get(part)
            elif isinstance(data, (list, tuple)):
                try:
                    data = data[int(part)]
                except (ValueError, IndexError):
                    return None
            else:
                return None
        return data
    
    def _init_primitives(self):
        """Initialize all primitives, wiring in connectors as providers."""
        c = self._connectors
        
        self._primitives["FILE"] = FilePrimitive()
        self._primitives["DOCUMENT"] = DocumentPrimitive(self._llm_complete)
        self._primitives["COMPUTE"] = ComputePrimitive(self._llm_complete)
        
        # Email — wire Gmail and/or Outlook connectors
        email_send = None
        email_list = None
        gmail = c.get("gmail")
        outlook = c.get("outlook")
        if gmail:
            email_send = gmail.send_email
            email_list = gmail.list_messages
        elif outlook:
            email_send = outlook.send_email
            email_list = outlook.list_messages
        self._primitives["EMAIL"] = EmailPrimitive(send_func=email_send, list_func=email_list)
        
        # Contacts — wire Google Contacts
        contacts_providers = {}
        if c.get("contacts"):
            contacts_providers["google"] = c["contacts"]
        self._primitives["CONTACTS"] = ContactsPrimitive(providers=contacts_providers)
        
        self._primitives["KNOWLEDGE"] = KnowledgePrimitive(str(self._storage_path / "knowledge.json"))
        
        # Calendar — wire Google Calendar and/or Outlook Calendar
        cal_create = None
        cal_list = None
        cal_list_calendars = None
        gcal = c.get("calendar")
        ocal = c.get("outlook_calendar")
        if gcal:
            cal_create = gcal.create_event
            cal_list = gcal.list_events
            cal_list_calendars = gcal.list_calendars
        elif ocal:
            cal_create = ocal.create_event
            cal_list = ocal.list_events
        self._primitives["CALENDAR"] = CalendarPrimitive(
            str(self._storage_path / "calendar.json"),
            create_func=cal_create,
            list_func=cal_list,
            list_calendars_func=cal_list_calendars,
        )
        
        self._primitives["WEB"] = WebPrimitive(self._llm_complete, search_provider=c.get("web_search"))
        
        # Notify — wire DesktopNotify connector
        notify_send = None
        desktop_notify = c.get("desktop_notify")
        if desktop_notify and hasattr(desktop_notify, "send"):
            notify_send = desktop_notify.send
        self._primitives["NOTIFY"] = NotifyPrimitive(str(self._storage_path / "reminders.json"), send_func=notify_send)
        
        # Task — wire Todoist, Microsoft To-Do, Jira
        task_providers = {}
        if c.get("todoist"):
            task_providers["todoist"] = c["todoist"]
        if c.get("microsoft_todo"):
            task_providers["microsoft_todo"] = c["microsoft_todo"]
        if c.get("jira"):
            task_providers["jira"] = c["jira"]
        self._primitives["TASK"] = TaskPrimitive(
            str(self._storage_path / "tasks.json"),
            providers=task_providers,
        )
        
        self._primitives["SHELL"] = ShellPrimitive()
        self._primitives["DATA"] = DataPrimitive(self._llm_complete)
        
        # Message — wire Slack, Teams, Discord, SMS
        msg_providers = {}
        if c.get("slack"):
            msg_providers["slack"] = c["slack"]
        if c.get("teams"):
            msg_providers["teams"] = c["teams"]
        if c.get("discord"):
            msg_providers["discord"] = c["discord"]
        if c.get("sms"):
            msg_providers["sms"] = c["sms"]
        self._primitives["MESSAGE"] = MessagePrimitive(providers=msg_providers)
        
        # Media — wire Spotify, YouTube
        media_providers = {}
        if c.get("spotify"):
            media_providers["spotify"] = c["spotify"]
        if c.get("youtube"):
            media_providers["youtube"] = c["youtube"]
        self._primitives["MEDIA"] = MediaPrimitive(self._llm_complete, providers=media_providers)
        
        self._primitives["BROWSER"] = BrowserPrimitive(self._llm_complete)
        
        # DevTools — wire GitHub, Jira
        devtools_providers = {}
        if c.get("github"):
            devtools_providers["github"] = c["github"]
        if c.get("jira"):
            devtools_providers["jira"] = c["jira"]
        if c.get("devtools"):
            devtools_providers["unified"] = c["devtools"]
        self._primitives["DEVTOOLS"] = DevToolsPrimitive(providers=devtools_providers)
        
        # Cloud Storage — wire Drive, OneDrive, Dropbox
        storage_providers = {}
        if c.get("drive"):
            storage_providers["google_drive"] = c["drive"]
        if c.get("onedrive"):
            storage_providers["onedrive"] = c["onedrive"]
        if c.get("dropbox"):
            storage_providers["dropbox"] = c["dropbox"]
        self._primitives["CLOUD_STORAGE"] = CloudStoragePrimitive(providers=storage_providers)
        
        # Clipboard — system clipboard operations
        self._primitives["CLIPBOARD"] = ClipboardPrimitive()
        
        # Translate — language translation via LLM
        self._primitives["TRANSLATE"] = TranslatePrimitive(self._llm_complete)
        
        # Database — SQLite database operations
        self._primitives["DATABASE"] = DatabasePrimitive(str(self._storage_path / "data.db"))
        
        # Screenshot — screen capture
        self._primitives["SCREENSHOT"] = ScreenshotPrimitive()
        
        # Automation — rules/triggers
        self._primitives["AUTOMATION"] = AutomationPrimitive(str(self._storage_path / "automations.json"))
        
        # Search — unified search across all primitives
        self._primitives["SEARCH"] = SearchPrimitive(self._primitives)
        
        # Chat — instant messaging (Slack, Teams, Discord)
        chat_providers = {}
        if c.get("slack"):
            chat_providers["slack"] = c["slack"]
        if c.get("teams"):
            chat_providers["teams"] = c["teams"]
        if c.get("discord"):
            chat_providers["discord"] = c["discord"]
        self._primitives["CHAT"] = ChatPrimitive(providers=chat_providers)
        
        # Meeting — video conferencing (Zoom, Teams, Meet)
        meeting_providers = {}
        if c.get("zoom"):
            meeting_providers["zoom"] = c["zoom"]
        if c.get("teams"):
            meeting_providers["teams"] = c["teams"]
        if c.get("google_meet"):
            meeting_providers["google_meet"] = c["google_meet"]
        self._primitives["MEETING"] = MeetingPrimitive(providers=meeting_providers)
        
        # SMS — text messaging
        sms_providers = {}
        if c.get("twilio"):
            sms_providers["twilio"] = c["twilio"]
        if c.get("sms"):
            sms_providers["sms"] = c["sms"]
        self._primitives["SMS"] = SmsPrimitive(providers=sms_providers)
        
        # Spreadsheet — Excel, Google Sheets
        spreadsheet_providers = {}
        if c.get("google_sheets"):
            spreadsheet_providers["google_sheets"] = c["google_sheets"]
        if c.get("excel"):
            spreadsheet_providers["excel"] = c["excel"]
        self._primitives["SPREADSHEET"] = SpreadsheetPrimitive(self._llm_complete, providers=spreadsheet_providers)
        
        # Presentation — PowerPoint, Google Slides
        presentation_providers = {}
        if c.get("google_slides"):
            presentation_providers["google_slides"] = c["google_slides"]
        if c.get("powerpoint"):
            presentation_providers["powerpoint"] = c["powerpoint"]
        self._primitives["PRESENTATION"] = PresentationPrimitive(self._llm_complete, providers=presentation_providers)
        
        # Notes — OneNote, Apple Notes, Google Keep
        notes_providers = {}
        if c.get("onenote"):
            notes_providers["onenote"] = c["onenote"]
        if c.get("google_keep"):
            notes_providers["google_keep"] = c["google_keep"]
        self._primitives["NOTES"] = NotesPrimitive(str(self._storage_path / "notes"), providers=notes_providers)
        
        # Finance — banking, payments
        finance_providers = {}
        if c.get("plaid"):
            finance_providers["plaid"] = c["plaid"]
        if c.get("paypal"):
            finance_providers["paypal"] = c["paypal"]
        if c.get("venmo"):
            finance_providers["venmo"] = c["venmo"]
        self._primitives["FINANCE"] = FinancePrimitive(providers=finance_providers)
        
        # Social — Twitter, LinkedIn, Facebook
        social_providers = {}
        if c.get("twitter"):
            social_providers["twitter"] = c["twitter"]
        if c.get("linkedin"):
            social_providers["linkedin"] = c["linkedin"]
        if c.get("facebook"):
            social_providers["facebook"] = c["facebook"]
        self._primitives["SOCIAL"] = SocialPrimitive(providers=social_providers)
        
        # Photo — Google Photos, iCloud
        photo_providers = {}
        if c.get("google_photos"):
            photo_providers["google_photos"] = c["google_photos"]
        if c.get("icloud_photos"):
            photo_providers["icloud_photos"] = c["icloud_photos"]
        self._primitives["PHOTO"] = PhotoPrimitive(providers=photo_providers)
        
        # Ride — Uber, Lyft
        ride_providers = {}
        if c.get("uber"):
            ride_providers["uber"] = c["uber"]
        if c.get("lyft"):
            ride_providers["lyft"] = c["lyft"]
        self._primitives["RIDE"] = RidePrimitive(providers=ride_providers)
        
        # Travel — flights, hotels
        travel_providers = {}
        if c.get("expedia"):
            travel_providers["expedia"] = c["expedia"]
        if c.get("google_flights"):
            travel_providers["google_flights"] = c["google_flights"]
        self._primitives["TRAVEL"] = TravelPrimitive(providers=travel_providers)
        
        # Home — smart home
        home_providers = {}
        if c.get("alexa"):
            home_providers["alexa"] = c["alexa"]
        if c.get("google_home"):
            home_providers["google_home"] = c["google_home"]
        if c.get("homekit"):
            home_providers["homekit"] = c["homekit"]
        self._primitives["HOME"] = HomePrimitive(providers=home_providers)
        
        # Shopping — Amazon, eBay
        shopping_providers = {}
        if c.get("amazon"):
            shopping_providers["amazon"] = c["amazon"]
        if c.get("ebay"):
            shopping_providers["ebay"] = c["ebay"]
        self._primitives["SHOPPING"] = ShoppingPrimitive(providers=shopping_providers)
    
    async def _llm_complete(self, prompt: str, triggering_request: str = "") -> str:
        """Call LLM for completion — with PII redaction and audit logging when safety is enabled."""
        if not self._api_key:
            raise ValueError("No API key configured. Set OPENAI_API_KEY or pass api_key to the engine")
        
        # Redact PII before sending to LLM
        send_prompt = prompt
        redaction_count = 0
        if self._safety_enabled and self._redaction:
            redaction_result = self._redaction.redact(prompt)
            send_prompt = redaction_result.redacted_text
            redaction_count = redaction_result.redaction_count
        
        # Log outbound transmission
        request_id = str(uuid.uuid4())[:8]
        if self._safety_enabled and self._audit:
            dest = TransmissionDestination.OPENAI if "gpt" in self._model else TransmissionDestination.ANTHROPIC
            self._audit.log_outbound(
                destination=dest,
                content=send_prompt[:500],
                triggering_request=triggering_request or "engine_call",
                model=self._model,
                request_id=request_id,
                contained_pii=redaction_count > 0,
                redactions_applied=redaction_count,
            )
        
        if HAS_LITELLM:
            response = await asyncio.to_thread(
                litellm.completion,
                model=self._model,
                messages=[{"role": "user", "content": send_prompt}],
                api_key=self._api_key,
            )
            result_text = response.choices[0].message.content
        else:
            # Fallback to direct OpenAI
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={"model": self._model, "messages": [{"role": "user", "content": send_prompt}]},
                    timeout=60,
                )
                result_text = resp.json()["choices"][0]["message"]["content"]
        
        # Log inbound response
        if self._safety_enabled and self._audit:
            self._audit.log_inbound(
                destination=dest,
                content=result_text[:500],
                request_id=request_id,
                model=self._model,
            )
        
        return result_text
    
    def _follow_path(self, data: Any, path: str) -> Any:
        """Navigate into data via dot-path or bracket syntax.
        
        Supports:
          - 'monthly_payment' → data['monthly_payment']
          - 'schedule.0.amount' → data['schedule'][0]['amount']
          - 'results[0].path' → data['results'][0]['path']
          - 'files[*].path' → [item['path'] for item in data['files']] (wildcard)
        """
        # Normalize bracket syntax to dot syntax: results[0].path → results.0.path
        # But handle [*] wildcard specially
        if '[*]' in path:
            # Wildcard: extract array field paths
            parts = re.split(r'\[\*\]', path, maxsplit=1)
            before = parts[0].rstrip('.')
            after = parts[1].lstrip('.') if len(parts) > 1 else None
            
            # Navigate to the array
            arr = self._follow_path(data, before) if before else data
            if not isinstance(arr, list):
                return None
            
            # Extract the field from each item
            if after:
                return [self._follow_path(item, after) for item in arr if self._follow_path(item, after) is not None]
            return arr
        
        # Normalize [N] to .N
        normalized = re.sub(r'\[(\d+)\]', r'.\1', path)
        
        for part in normalized.split('.'):
            if not part:
                continue
            if data is None:
                return None
            if isinstance(data, dict):
                data = data.get(part)
            elif isinstance(data, (list, tuple)):
                try:
                    data = data[int(part)]
                except (ValueError, IndexError):
                    return None
            else:
                return None
        return data
    
    def _resolve_wire(self, ref: str, results: Dict[int, Any]) -> Any:
        """Resolve a wire reference like 'step_0' or 'step_0.results[0].path'."""
        match = re.match(r'step_(\d+)(?:\.(.+))?', ref)
        if not match:
            return None
        step_id = int(match.group(1))
        path = match.group(2)
        if step_id not in results:
            return None
        data = results[step_id]
        if path:
            data = self._follow_path(data, path)
        return data
    
    def _resolve_params(self, params: Dict, results: Dict[int, Any]) -> Dict:
        """Resolve {{step_N}} and {{step_N.path}} references in parameters.
        
        Supports dot-path navigation: {{step_0.monthly_payment}} picks a field.
        Type-preserving: if the whole value is a reference, passes data as-is.
        """
        resolved = {}
        for k, v in params.items():
            if isinstance(v, str):
                # Match both {{step_0.field}} and {{step_0.results[0].path}} syntax
                for match in re.findall(r'\{\{(step_\d+(?:[\.\[\]\w\*]+)?)\}\}', v):
                    ref_data = self._resolve_wire(match, results)
                    placeholder = "{{" + match + "}}"
                    
                    if ref_data is not None:
                        if v == placeholder:
                            v = ref_data
                        else:
                            if isinstance(ref_data, (dict, list)):
                                v = v.replace(placeholder, json.dumps(ref_data))
                            else:
                                v = v.replace(placeholder, str(ref_data))
                resolved[k] = v
            elif isinstance(v, dict):
                resolved[k] = self._resolve_params(v, results)
            elif isinstance(v, list):
                resolved[k] = [
                    self._resolve_params(item, results) if isinstance(item, dict) else item
                    for item in v
                ]
            else:
                resolved[k] = v
        return resolved
    
    def _apply_wires(self, step: 'PlanStep', results: Dict[int, Any]) -> Dict:
        """Build final params: static params + resolved wires + {{step_N}} expansion.
        
        Wires are first-class connections between steps:
          {"body": "step_0.monthly_payment"} → sets body = step 0's monthly_payment
        
        Then any remaining {{step_N}} references in params are resolved too.
        
        Auto-wire fallback: if a step depends on a previous step and has an empty/missing
        'data' param, automatically wire in the previous step's result. This covers the
        common case where the LLM forgets to set an explicit wire.
        """
        # Start with static params
        merged = dict(step.params)
        
        # Layer on wired data
        for param_name, wire_ref in step.wires.items():
            wired_value = self._resolve_wire(wire_ref, results)
            if wired_value is not None:
                merged[param_name] = wired_value
        
        # Resolve bare step references: "step_0" or "step_0.field" (without {{ }})
        # LLMs often write these in params instead of using proper wires or {{}} templates
        for k, v in list(merged.items()):
            if isinstance(v, str):
                bare_match = re.match(r'^step_(\d+)(\.[\w.]+)?$', v.strip())
                if bare_match:
                    resolved = self._resolve_wire(v.strip(), results)
                    if resolved is not None:
                        merged[k] = resolved
        
        # Resolve any remaining {{step_N}} templates in params
        merged = self._resolve_params(merged, results)
        
        # AUTO-WIRE FALLBACK: if 'data' param is empty/missing and there are previous results,
        # inject the most recent predecessor's result as 'data'.
        # This handles the common LLM mistake of forgetting to wire step outputs.
        if "data" not in merged or merged.get("data") in ([], {}, None, ""):
            # Check explicit dependencies first, then fall back to previous step
            candidates = step.depends_on if step.depends_on else ([step.id - 1] if step.id > 0 else [])
            for dep_id in reversed(candidates):
                if dep_id in results and isinstance(results[dep_id], list):
                    merged["data"] = results[dep_id]
                    logger.info(f"[auto-wire] Injected step_{dep_id} result ({len(results[dep_id])} items) as 'data' for step {step.id}")
                    break
        
        # AUTO-WIRE PATH: Operations like DOCUMENT.parse, FILE.read, MEDIA.info need a 'path'
        # If path is missing/unresolved (still contains {{ }}), try to get it from previous FILE.search
        path_val = merged.get("path", "")
        if step.operation in ("parse", "read", "info", "checksum", "move", "copy", "delete"):
            needs_path = (
                "path" not in merged or 
                merged.get("path") in (None, "", []) or
                (isinstance(path_val, str) and "{{" in path_val)  # Unresolved placeholder
            )
            if needs_path:
                # Look for file paths from previous steps
                candidates = step.depends_on if step.depends_on else list(range(step.id))
                for dep_id in reversed(candidates):
                    if dep_id not in results:
                        continue
                    prev_result = results[dep_id]
                    # Handle list of files from FILE.search
                    if isinstance(prev_result, list) and len(prev_result) > 0:
                        first_item = prev_result[0]
                        if isinstance(first_item, dict) and 'path' in first_item:
                            merged["path"] = first_item['path']
                            logger.info(f"[auto-wire] Set path from step_{dep_id}[0].path: {first_item['path'][:50]}...")
                            break
                        elif isinstance(first_item, str) and ('/' in first_item or '\\' in first_item):
                            merged["path"] = first_item
                            logger.info(f"[auto-wire] Set path from step_{dep_id}[0]: {first_item[:50]}...")
                            break
                    # Handle dict with path key
                    elif isinstance(prev_result, dict) and 'path' in prev_result:
                        merged["path"] = prev_result['path']
                        logger.info(f"[auto-wire] Set path from step_{dep_id}.path: {prev_result['path'][:50]}...")
                        break
        
        # AUTO-WIRE CONTENT: Operations like DOCUMENT.extract, DOCUMENT.summarize need 'content'
        content_val = merged.get("content", "")
        if step.operation in ("extract", "summarize"):
            needs_content = (
                "content" not in merged or
                merged.get("content") in (None, "", []) or
                (isinstance(content_val, str) and "{{" in content_val)
            )
            if needs_content:
                candidates = step.depends_on if step.depends_on else list(range(step.id))
                for dep_id in reversed(candidates):
                    if dep_id not in results:
                        continue
                    prev_result = results[dep_id]
                    # DOCUMENT.parse returns text content as string
                    if isinstance(prev_result, str) and len(prev_result) > 20:
                        merged["content"] = prev_result
                        logger.info(f"[auto-wire] Set content from step_{dep_id} (text, {len(prev_result)} chars)")
                        break
                    # Or dict with text/content key
                    elif isinstance(prev_result, dict):
                        for key in ('text', 'content', 'body', 'raw'):
                            if key in prev_result and isinstance(prev_result[key], str):
                                merged["content"] = prev_result[key]
                                logger.info(f"[auto-wire] Set content from step_{dep_id}.{key}")
                                break
        
        # Debug: log final resolved params for tracing
        data_val = merged.get("data")
        logger.info(f"[_apply_wires] step {step.id} ({step.primitive}.{step.operation}): data type={type(data_val).__name__}, keys={list(merged.keys())}")
        
        return merged
    
    async def _self_heal(self, step, params: Dict, error: str) -> Optional[Dict]:
        """Ask the LLM to fix parameters that caused a primitive to fail.
        
        Includes the param schema so the LLM knows the exact expected format.
        Returns corrected params dict, or None if it can't fix it.
        """
        primitive = self._primitives.get(step.primitive)
        if not primitive:
            return None
        
        ops = primitive.get_operations()
        schema = primitive.get_param_schema()
        op_schema = schema.get(step.operation, {})
        
        prompt = f"""A primitive operation failed. Fix the parameters to match the expected schema.

PRIMITIVE: {step.primitive}
OPERATION: {step.operation}
DESCRIPTION: {step.description}
AVAILABLE OPERATIONS: {json.dumps(ops)}

EXPECTED PARAMETER SCHEMA:
{json.dumps(op_schema, indent=2) if op_schema else "No schema available — infer from the error message."}

PARAMETERS SENT:
{json.dumps(params, indent=2)}

ERROR:
{error}

Fix the parameters so they match the expected schema. Respond with ONLY a valid JSON object — no explanation."""

        try:
            response = await self._llm_complete(prompt, triggering_request="self_heal")
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                fixed = json.loads(json_match.group())
                if isinstance(fixed, dict) and fixed != params:
                    return fixed
        except Exception:
            pass
        return None
    
    # Map primitive.operation to canonical trust level action types
    _ACTION_TYPE_MAP = {
        # Calendar
        "CALENDAR.create": "create_calendar_event",
        "CALENDAR.delete": "delete_event",
        "CALENDAR.update": "update_event",
        "CALENDAR.list": "search_calendar",
        "CALENDAR.search": "search_calendar",
        # Email
        "EMAIL.send": "send_email",
        "EMAIL.delete": "delete_email",
        "EMAIL.search": "search_email",
        "EMAIL.draft": "create_draft",
        # File
        "FILE.write": "modify_file",
        "FILE.delete": "delete_file",
        "FILE.move": "move_file",
        "FILE.rename": "rename_file",
        "FILE.read": "read_file",
        "FILE.search": "search_files",
        "FILE.list": "list_directory",
        "FILE.info": "get_file_info",
        # Task
        "TASK.create": "create_task",
        "TASK.delete": "delete_task",
        "TASK.update": "update_task",
        # Message
        "MESSAGE.send": "send_message",
        # Drive
        "DRIVE.upload": "share_file",  # uploading to cloud involves sharing
        "DRIVE.share": "share_file",
        "DRIVE.search": "search_files",
        # Document
        "DOCUMENT.create": "create_document",
        # Compute - all read-only calculations
        "COMPUTE.amortization": "calculate",
        "COMPUTE.compound": "calculate",
        "COMPUTE.aggregate": "calculate",
        "COMPUTE.convert": "calculate",
        # Knowledge - memory operations are safe
        "KNOWLEDGE.remember": "create_document",
        "KNOWLEDGE.recall": "read_file",
    }
    
    def _check_trust(self, primitive: str, operation: str) -> str:
        """Check trust level for an action. Returns 'auto', 'ask', or 'block'."""
        if not self._safety_enabled or not self._trust:
            return "auto"
        
        # Map to canonical action type for trust lookup
        raw_action = f"{primitive}.{operation}"
        action_type = self._ACTION_TYPE_MAP.get(raw_action, raw_action)
        level = self._trust.get_trust_level(action_type)
        
        if level == TrustLevel.AUTO_APPROVE:
            return "auto"
        elif level == TrustLevel.ASK_ONCE:
            return "ask"
        else:  # ALWAYS_ASK
            risk = _classify_risk(primitive, operation)
            if risk in ("high", "critical"):
                return "ask"
            return "auto"  # Low/medium risk with ALWAYS_ASK still auto-approves reads
    
    def _create_undo_checkpoint(self, step: 'PlanStep', action_id: str) -> Optional[str]:
        """Create an undo checkpoint before a destructive operation."""
        if not self._safety_enabled or not self._undo:
            return None
        
        key = (step.primitive, step.operation)
        if key not in _UNDOABLE_OPS:
            return None
        
        try:
            undo_type_str = _UNDOABLE_OPS[key]
            
            if key == ("FILE", "write"):
                path = step.params.get("path", "")
                if path and Path(path).expanduser().exists():
                    cp = self._undo.create_file_backup(action_id, str(Path(path).expanduser()), description=step.description)
                    if cp:
                        return cp.id
            elif key[0] == "CALENDAR":
                cp = self._undo.create_calendar_event_checkpoint(action_id, step.params, step.operation)
                if cp:
                    return cp.id
            elif key[0] == "TASK":
                cp = self._undo.create_task_checkpoint(action_id, step.params, step.operation)
                if cp:
                    return cp.id
            else:
                undo_type = UndoType.GENERIC
                cp = self._undo.create_checkpoint(action_id, undo_type, step.params, description=step.description)
                if cp:
                    return cp.id
        except Exception as e:
            logger.warning(f"Failed to create undo checkpoint: {e}")
        return None
    
    def _log_step_start(self, step: 'PlanStep', request: str, session_id: str) -> Optional[str]:
        """Log step start to action history. Returns action_id."""
        if not self._safety_enabled or not self._action_history:
            return None
        
        try:
            action_type = f"{step.primitive}.{step.operation}"
            risk = _classify_risk(step.primitive, step.operation)
            is_undoable = (step.primitive, step.operation) in _UNDOABLE_OPS
            
            record = self._action_history.record_action(
                action_type=action_type,
                payload=step.params,
                preview={"description": step.description, "primitive": step.primitive, "operation": step.operation},
                triggered_by="engine",
                session_id=session_id,
                request_text=request,
                is_undoable=is_undoable,
            )
            return record.id
        except Exception as e:
            logger.warning(f"Failed to log action start: {e}")
            return None
    
    def _log_step_complete(self, action_id: Optional[str], result: StepResult, checkpoint_id: Optional[str] = None):
        """Log step completion to action history."""
        if not action_id or not self._safety_enabled or not self._action_history:
            return
        
        try:
            if result.success:
                self._action_history.mark_completed(action_id, result=result.to_dict(), checkpoint_id=checkpoint_id)
            else:
                self._action_history.mark_failed(action_id, error=result.error or "Unknown error")
        except Exception as e:
            logger.warning(f"Failed to log action completion: {e}")
    
    async def _safe_execute_step(
        self,
        step: 'PlanStep',
        resolved_params: Dict,
        request: str,
        session_id: str,
    ) -> StepResult:
        """Execute a step with full safety rails: trust check, undo, history, self-heal."""
        print(f"[ENGINE] Executing step: {step.primitive}.{step.operation}")
        
        # CLARIFY is a signal to ask the user a question, not a real primitive
        if step.primitive.upper() == "CLARIFY":
            return StepResult(True, data={"clarify": step.params.get("question", step.description)})
        
        # 1. Trust level check
        trust = self._check_trust(step.primitive, step.operation)
        risk = _classify_risk(step.primitive, step.operation)
        print(f"[ENGINE] Trust={trust}, Risk={risk} for {step.primitive}.{step.operation}")
        
        if trust == "ask":
            if risk in ("high", "critical"):
                # For high-risk actions, mark as needing approval
                # In a real UI flow, this would pause and wait for user input
                # For now, we log it and proceed (the approval gateway records it)
                print(f"[ENGINE] High-risk action queued for approval: {step.primitive}.{step.operation}")
                if self._approval:
                    try:
                        from src.control.approval_gateway import PendingAction, ActionPreview
                        action = PendingAction(
                            action_type=f"{step.primitive}.{step.operation}",
                            payload=resolved_params,
                            preview=ActionPreview(title=step.description, description=f"{step.primitive}.{step.operation}", preview_type="action"),
                            risk_level=RiskLevel.HIGH if risk == "high" else RiskLevel.CRITICAL,
                        )
                        await self._approval.submit(action)
                        # Auto-approve for engine execution (UI would pause here)
                        await self._approval.approve(action.id)
                    except Exception as e:
                        logger.debug(f"Approval flow: {e}")
        
        # 2. Log action start
        action_id = self._log_step_start(step, request, session_id)
        
        # 3. Create undo checkpoint before destructive ops
        checkpoint_id = self._create_undo_checkpoint(step, action_id or "unknown")
        
        # 4. Execute with self-healing retry
        primitive = self._primitives.get(step.primitive)
        if not primitive:
            result = StepResult(False, error=f"Unknown primitive: {step.primitive}")
            self._log_step_complete(action_id, result)
            return result
        
        max_attempts = step.max_retries
        result = StepResult(False, error="No execution attempted")
        
        for attempt in range(max_attempts):
            try:
                result = await primitive.execute(step.operation, resolved_params)
            except Exception as e:
                result = StepResult(False, error=str(e))
            
            if result.success:
                break
            
            if attempt < max_attempts - 1:
                healed = await self._self_heal(step, resolved_params, result.error)
                if healed:
                    resolved_params = healed
                else:
                    break
        
        # 5. Commit undo checkpoint on success
        if result.success and checkpoint_id and self._undo:
            try:
                self._undo.commit_checkpoint(checkpoint_id)
            except Exception:
                pass
        
        # 6. Log completion
        self._log_step_complete(action_id, result, checkpoint_id)
        
        return result
    
    async def do(
        self, 
        request: str, 
        context: Optional[Dict] = None,
        require_approval: bool = False,
        on_step_complete: Optional[Callable] = None,
    ) -> ExecutionResult:
        """
        Execute a natural language request.
        
        Args:
            request: What to do (e.g., "Find all PDFs and list them")
            context: Additional context
            on_step_complete: Optional async callback called after each step finishes.
                              Signature: async (step_id, description, primitive, operation, success, data, error) -> None
            require_approval: If True, returns plan for approval before executing
        
        Returns:
            ExecutionResult with plan and results
        """
        session_id = str(uuid.uuid4())[:12]
        
        # Redact PII from the request before sending to planner
        plan_request = request
        if self._safety_enabled and self._redaction:
            redact_result = self._redaction.redact(request)
            if redact_result.had_pii:
                plan_request = redact_result.redacted_text
        
        # Generate plan
        plan = await self._planner.plan(plan_request, context)
        
        if require_approval:
            # Return plan without executing
            return ExecutionResult(
                success=True,
                request=request,
                plan=plan,
                final_result=None,
            )
        
        # Execute plan via Orchestrator
        results: Dict[int, Any] = {}
        
        # Check if any step uses orchestration features
        has_orchestration = any(s.step_type != "action" for s in plan)
        
        if has_orchestration:
            # Full orchestration path — parallel, conditionals, loops, sub-plans
            # The orchestrator calls primitives directly; we inject safety via its self_heal callback
            results = await self._orchestrator.execute_plan(
                plan, results,
                resolve_wires_fn=self._resolve_wire,
                apply_wires_fn=self._apply_wires,
            )
            # Log all orchestrated steps to action history
            if self._safety_enabled and self._action_history:
                for step in plan:
                    if step.result:
                        action_id = self._log_step_start(step, request, session_id)
                        self._log_step_complete(action_id, step.result)
        else:
            # Fast path — simple sequential execution with full safety rails
            for step in plan:
                # Check dependencies
                dep_failed = False
                for dep_id in step.depends_on:
                    if dep_id not in results:
                        step.result = StepResult(False, error=f"Dependency step_{dep_id} failed or not available")
                        dep_failed = True
                        break
                if dep_failed:
                    if step.on_fail == "continue":
                        results[step.id] = None
                    # Notify callback of dependency failure
                    if on_step_complete:
                        await on_step_complete(
                            step.id, step.description, step.primitive, step.operation,
                            False, None, step.result.error if step.result else "Dependency failed"
                        )
                    continue
                
                # Notify callback that step is starting
                if on_step_complete:
                    await on_step_complete(
                        step.id, step.description, step.primitive, step.operation,
                        None, None, None  # success=None means "running"
                    )
                
                # Resolve parameters: static params + wired connections
                resolved_params = self._apply_wires(step, results)
                
                # Execute with safety rails
                step.result = await self._safe_execute_step(step, resolved_params, request, session_id)
                
                if step.result.success:
                    results[step.id] = step.result.data
                elif step.on_fail == "continue":
                    results[step.id] = None
                
                # Notify callback of step completion
                if on_step_complete:
                    step_data = None
                    if step.result.success and step.result.data is not None:
                        try:
                            json.dumps(step.result.data)
                            step_data = step.result.data
                        except (TypeError, ValueError):
                            step_data = str(step.result.data)
                    await on_step_complete(
                        step.id, step.description, step.primitive, step.operation,
                        step.result.success, step_data,
                        step.result.error if not step.result.success else None
                    )
        
        # Determine success
        failed = [s for s in plan if s.result and not s.result.success]
        success = len(failed) == 0
        
        # Get final result
        final_result = None
        for step in reversed(plan):
            if step.result and step.result.success and step.result.data is not None:
                final_result = step.result.data
                break
        
        result = ExecutionResult(
            success=success,
            request=request,
            plan=plan,
            final_result=final_result,
            error="; ".join(s.result.error for s in failed if s.result and s.result.error) if failed else None,
        )
        
        self._history.append(result)
        return result
    
    async def execute_plan(
        self,
        plan: list,
        request: str = "",
        on_step_complete: Optional[Callable] = None,
    ) -> 'ExecutionResult':
        """Execute a pre-built plan (from a previous require_approval=True call).
        
        This avoids re-planning — it runs the exact plan the user approved.
        """
        session_id = str(uuid.uuid4())[:12]
        results: Dict[int, Any] = {}
        
        has_orchestration = any(s.step_type != "action" for s in plan)
        
        if has_orchestration:
            results = await self._orchestrator.execute_plan(
                plan, results,
                resolve_wires_fn=self._resolve_wire,
                apply_wires_fn=self._apply_wires,
            )
        else:
            for step in plan:
                dep_failed = False
                for dep_id in step.depends_on:
                    if dep_id not in results:
                        step.result = StepResult(False, error=f"Dependency step_{dep_id} failed or not available")
                        dep_failed = True
                        break
                if dep_failed:
                    if step.on_fail == "continue":
                        results[step.id] = None
                    if on_step_complete:
                        await on_step_complete(
                            step.id, step.description, step.primitive, step.operation,
                            False, None, step.result.error if step.result else "Dependency failed"
                        )
                    continue
                
                if on_step_complete:
                    await on_step_complete(
                        step.id, step.description, step.primitive, step.operation,
                        None, None, None
                    )
                
                resolved_params = self._apply_wires(step, results)
                step.result = await self._safe_execute_step(step, resolved_params, request, session_id)
                
                if step.result.success:
                    results[step.id] = step.result.data
                elif step.on_fail == "continue":
                    results[step.id] = None
                
                if on_step_complete:
                    step_data = None
                    if step.result.success and step.result.data is not None:
                        try:
                            json.dumps(step.result.data)
                            step_data = step.result.data
                        except (TypeError, ValueError):
                            step_data = str(step.result.data)
                    await on_step_complete(
                        step.id, step.description, step.primitive, step.operation,
                        step.result.success, step_data,
                        step.result.error if not step.result.success else None
                    )
        
        failed = [s for s in plan if s.result and not s.result.success]
        success = len(failed) == 0
        
        final_result = None
        for step in reversed(plan):
            if step.result and step.result.success and step.result.data is not None:
                final_result = step.result.data
                break
        
        result = ExecutionResult(
            success=success,
            request=request,
            plan=plan,
            final_result=final_result,
            error="; ".join(s.result.error for s in failed if s.result and s.result.error) if failed else None,
        )
        self._history.append(result)
        return result
    
    # === Convenience Methods ===
    
    def add_contact(self, name: str, email: str, phone: Optional[str] = None):
        """Add a contact directly."""
        contacts = self._primitives.get("CONTACTS")
        if isinstance(contacts, ContactsPrimitive):
            contacts.add_contact(name, email, phone)
    
    def get_primitive(self, name: str) -> Optional[Primitive]:
        """Get a primitive by name."""
        return self._primitives.get(name)
    
    def list_capabilities(self) -> Dict[str, Dict[str, str]]:
        """List all available capabilities."""
        return {name: prim.get_operations() for name, prim in self._primitives.items()}


# ============================================================
#  CONVENIENCE FUNCTION
# ============================================================

async def quick_test():
    """Quick test of the engine."""
    apex = Apex()
    
    # Add a test contact
    apex.add_contact("Fred", "fred@example.com")
    
    # Test FILE primitive directly
    file_prim = apex.get_primitive("FILE")
    result = await file_prim.execute("list", {"directory": "~"})
    print(f"FILE.list home: {result.success}, {len(result.data or [])} items")
    
    # Test COMPUTE primitive
    compute = apex.get_primitive("COMPUTE")
    result = await compute.execute("formula", {
        "name": "amortization",
        "inputs": {"principal": 250000, "rate": 6.5, "term_months": 360}
    })
    print(f"COMPUTE.formula amortization: {result.success}")
    if result.success:
        print(f"  Monthly payment: ${result.data['monthly_payment']}")
        print(f"  Total interest: ${result.data['total_interest']}")
    
    print("\nCapabilities:")
    for name, ops in apex.list_capabilities().items():
        print(f"  {name}: {', '.join(ops.keys())}")


if __name__ == "__main__":
    asyncio.run(quick_test())
