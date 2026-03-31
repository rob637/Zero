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
import json
import logging
import os
import re
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

logger = logging.getLogger(__name__)


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
    """A step in the execution plan."""
    id: int
    description: str
    primitive: str
    operation: str
    params: Dict[str, Any]
    depends_on: List[int] = field(default_factory=list)
    result: Optional[StepResult] = None
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "description": self.description,
            "primitive": self.primitive,
            "operation": self.operation,
            "params": self.params,
            "depends_on": self.depends_on,
            "result": self.result.to_dict() if self.result else None,
        }


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
        self._allowed = allowed_roots or [str(Path.home())]
    
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
                limit = params.get("limit", 50)
                
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
    """Mathematical and financial computations."""
    
    @property
    def name(self) -> str:
        return "COMPUTE"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "formula": "Apply a named formula (amortization, compound_interest, etc.)",
            "calculate": "Evaluate a math expression",
            "aggregate": "Aggregate data (sum, average, etc.)",
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            if operation == "formula":
                name = params.get("name", "")
                inputs = params.get("inputs", {})
                
                if name == "amortization":
                    principal = float(inputs.get("principal", 0))
                    rate = float(inputs.get("rate", 0))  # Annual percentage
                    term = int(inputs.get("term_months") or inputs.get("term", 0) * 12)
                    
                    if principal <= 0 or rate <= 0 or term <= 0:
                        return StepResult(False, error=f"Invalid inputs: principal={principal}, rate={rate}, term={term}")
                    
                    monthly_rate = (rate / 100) / 12
                    payment = principal * (monthly_rate * (1 + monthly_rate)**term) / ((1 + monthly_rate)**term - 1)
                    
                    schedule = []
                    balance = principal
                    total_interest = 0
                    
                    for month in range(1, term + 1):
                        interest = balance * monthly_rate
                        principal_payment = payment - interest
                        balance = max(0, balance - principal_payment)
                        total_interest += interest
                        
                        schedule.append({
                            "month": month,
                            "payment": round(payment, 2),
                            "principal": round(principal_payment, 2),
                            "interest": round(interest, 2),
                            "balance": round(balance, 2),
                        })
                    
                    return StepResult(True, data={
                        "monthly_payment": round(payment, 2),
                        "total_interest": round(total_interest, 2),
                        "total_paid": round(payment * term, 2),
                        "schedule": schedule,
                    })
                
                elif name == "compound_interest":
                    principal = float(inputs.get("principal", 0))
                    rate = float(inputs.get("rate", 0)) / 100
                    years = float(inputs.get("years", 1))
                    n = int(inputs.get("compounds_per_year", 12))
                    
                    amount = principal * (1 + rate/n)**(n * years)
                    
                    return StepResult(True, data={
                        "final_amount": round(amount, 2),
                        "interest_earned": round(amount - principal, 2),
                    })
                
                else:
                    return StepResult(False, error=f"Unknown formula: {name}")
            
            elif operation == "calculate":
                expr = params.get("expression", "")
                variables = params.get("variables", {})
                
                # Safe evaluation
                allowed = {"abs": abs, "round": round, "min": min, "max": max, "sum": sum, "len": len}
                allowed.update({k: float(v) for k, v in variables.items() if isinstance(v, (int, float))})
                
                result = eval(expr, {"__builtins__": {}}, allowed)
                return StepResult(True, data=result)
            
            elif operation == "aggregate":
                data = params.get("data", [])
                func = params.get("function", "sum")
                field_name = params.get("field")
                
                if field_name and isinstance(data, list):
                    values = [float(item.get(field_name, 0)) for item in data if isinstance(item, dict)]
                else:
                    values = [float(v) for v in data if isinstance(v, (int, float))]
                
                if func == "sum":
                    result = sum(values)
                elif func == "average":
                    result = sum(values) / len(values) if values else 0
                elif func == "min":
                    result = min(values) if values else 0
                elif func == "max":
                    result = max(values) if values else 0
                elif func == "count":
                    result = len(values)
                else:
                    return StepResult(False, error=f"Unknown function: {func}")
                
                return StepResult(True, data=round(result, 2))
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
                
        except Exception as e:
            return StepResult(False, error=str(e))


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
    """Contact management."""
    
    def __init__(self):
        self._contacts: Dict[str, Dict] = {}
    
    @property
    def name(self) -> str:
        return "CONTACTS"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "search": "Find contacts by name or email",
            "add": "Add a contact",
            "list": "List all contacts",
        }
    
    def add_contact(self, name: str, email: str, phone: Optional[str] = None):
        """Add a contact (can be called directly to seed data)."""
        self._contacts[name.lower()] = {"name": name, "email": email, "phone": phone}
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            if operation == "search":
                query = params.get("query", "").lower()
                matches = [
                    c for c in self._contacts.values()
                    if query in c["name"].lower() or query in c.get("email", "").lower()
                ]
                if matches:
                    return StepResult(True, data=matches[0])  # Return first match
                return StepResult(True, data=None)
            
            elif operation == "add":
                name = params.get("name")
                email = params.get("email")
                phone = params.get("phone")
                
                if name:
                    self._contacts[name.lower()] = {"name": name, "email": email, "phone": phone}
                    return StepResult(True, data={"name": name, "email": email})
                return StepResult(False, error="Name required")
            
            elif operation == "list":
                return StepResult(True, data=list(self._contacts.values()))
            
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
#  TASK PLANNER
# ============================================================

class TaskPlanner:
    """LLM-powered task decomposition."""
    
    def __init__(self, llm_complete: Callable, primitives: Dict[str, Primitive]):
        self._llm = llm_complete
        self._primitives = primitives
    
    def _get_capabilities_prompt(self) -> str:
        lines = ["Available primitives:\n"]
        for name, prim in self._primitives.items():
            lines.append(f"\n{name}:")
            for op, desc in prim.get_operations().items():
                lines.append(f"  - {name}.{op}: {desc}")
        return "\n".join(lines)
    
    async def plan(self, request: str, context: Optional[Dict] = None) -> List[PlanStep]:
        """Generate an execution plan for a request."""
        
        capabilities = self._get_capabilities_prompt()
        
        prompt = f"""You are a task planner. Decompose this request into primitive operations.

{capabilities}

RULES:
1. Each step uses ONE primitive and ONE operation
2. Use {{{{step_N}}}} to reference result of step N (0-indexed)
3. Be specific with parameters
4. Minimize steps - only what's necessary

Request: {request}
{f"Context: {json.dumps(context)}" if context else ""}

Respond with ONLY a JSON array:
[
  {{"description": "...", "primitive": "FILE", "operation": "search", "params": {{}}, "depends_on": []}},
  ...
]"""

        response = await self._llm(prompt)
        
        # Parse response
        json_match = re.search(r'\[[\s\S]*\]', response)
        if not json_match:
            return [PlanStep(0, f"Process: {request}", "KNOWLEDGE", "recall", {"query": request})]
        
        try:
            step_data = json.loads(json_match.group())
            steps = []
            for i, s in enumerate(step_data):
                steps.append(PlanStep(
                    id=i,
                    description=s.get("description", f"Step {i}"),
                    primitive=s.get("primitive", "").upper(),
                    operation=s.get("operation", ""),
                    params=s.get("params", {}),
                    depends_on=s.get("depends_on", []),
                ))
            return steps
        except json.JSONDecodeError:
            return [PlanStep(0, f"Process: {request}", "KNOWLEDGE", "recall", {"query": request})]


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
        model: str = "gpt-4o-mini",
        storage_path: Optional[str] = None,
    ):
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        self._model = model
        self._storage_path = Path(storage_path or "~/.telic").expanduser()
        self._storage_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize primitives
        self._primitives: Dict[str, Primitive] = {}
        self._init_primitives()
        
        # Initialize planner
        self._planner = TaskPlanner(self._llm_complete, self._primitives)
        
        # Execution history
        self._history: List[ExecutionResult] = []
    
    def _init_primitives(self):
        """Initialize all primitives."""
        self._primitives["FILE"] = FilePrimitive()
        self._primitives["DOCUMENT"] = DocumentPrimitive(self._llm_complete)
        self._primitives["COMPUTE"] = ComputePrimitive()
        self._primitives["EMAIL"] = EmailPrimitive()
        self._primitives["CONTACTS"] = ContactsPrimitive()
        self._primitives["KNOWLEDGE"] = KnowledgePrimitive(str(self._storage_path / "knowledge.json"))
    
    async def _llm_complete(self, prompt: str) -> str:
        """Call LLM for completion."""
        if not self._api_key:
            raise ValueError("No API key configured. Set OPENAI_API_KEY or pass api_key to the engine")
        
        if HAS_LITELLM:
            response = await asyncio.to_thread(
                litellm.completion,
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                api_key=self._api_key,
            )
            return response.choices[0].message.content
        else:
            # Fallback to direct OpenAI
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={"model": self._model, "messages": [{"role": "user", "content": prompt}]},
                    timeout=60,
                )
                return resp.json()["choices"][0]["message"]["content"]
    
    def _resolve_params(self, params: Dict, results: Dict[int, Any]) -> Dict:
        """Resolve {{step_N}} references in parameters."""
        resolved = {}
        for k, v in params.items():
            if isinstance(v, str):
                for match in re.findall(r'\{\{step_(\d+)\}\}', v):
                    step_id = int(match)
                    if step_id in results:
                        if v == f"{{{{step_{match}}}}}":
                            v = results[step_id]
                        else:
                            v = v.replace(f"{{{{step_{match}}}}}", str(results[step_id]))
                resolved[k] = v
            elif isinstance(v, dict):
                resolved[k] = self._resolve_params(v, results)
            else:
                resolved[k] = v
        return resolved
    
    async def do(
        self, 
        request: str, 
        context: Optional[Dict] = None,
        require_approval: bool = False,
    ) -> ExecutionResult:
        """
        Execute a natural language request.
        
        Args:
            request: What to do (e.g., "Find all PDFs and list them")
            context: Additional context
            require_approval: If True, returns plan for approval before executing
        
        Returns:
            ExecutionResult with plan and results
        """
        # Generate plan
        plan = await self._planner.plan(request, context)
        
        if require_approval:
            # Return plan without executing
            return ExecutionResult(
                success=True,
                request=request,
                plan=plan,
                final_result=None,
            )
        
        # Execute plan
        results: Dict[int, Any] = {}
        
        for step in plan:
            # Check dependencies
            for dep_id in step.depends_on:
                if dep_id not in results:
                    step.result = StepResult(False, error=f"Dependency step_{dep_id} not available")
                    continue
            
            # Resolve parameters
            resolved_params = self._resolve_params(step.params, results)
            
            # Get primitive
            primitive = self._primitives.get(step.primitive)
            if not primitive:
                step.result = StepResult(False, error=f"Unknown primitive: {step.primitive}")
                continue
            
            # Execute
            step.result = await primitive.execute(step.operation, resolved_params)
            
            if step.result.success:
                results[step.id] = step.result.data
        
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
