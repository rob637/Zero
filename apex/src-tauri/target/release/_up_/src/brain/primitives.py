"""
Apex Primitive Capabilities

These are the atomic operations the brain can perform.
The LLM composes these to handle any scenario.

Architecture:
    ┌─────────────────────────────────────────────────────────────┐
    │                      USER REQUEST                           │
    │        "Do X with Y and send to Z"                          │
    └─────────────────────────────────────────────────────────────┘
                               │
                               ▼
    ┌─────────────────────────────────────────────────────────────┐
    │                    LLM PLANNER                              │
    │   Decomposes request into primitive operations              │
    └─────────────────────────────────────────────────────────────┘
                               │
                               ▼
    ┌─────────────────────────────────────────────────────────────┐
    │                    PRIMITIVES                               │
    │   FILE | DOCUMENT | COMPUTE | EMAIL | CALENDAR | ...        │
    └─────────────────────────────────────────────────────────────┘

With ~40 primitives, we can handle thousands of scenarios.
"""

import asyncio
import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable, Union
import os

logger = logging.getLogger(__name__)


# ============================================================
#  PRIMITIVE RESULT
# ============================================================

@dataclass
class PrimitiveResult:
    """Result from executing a primitive."""
    success: bool
    data: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "metadata": self.metadata,
        }


# ============================================================
#  BASE PRIMITIVE
# ============================================================

class Primitive(ABC):
    """Base class for all primitives."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Primitive category name (e.g., 'FILE', 'DOCUMENT')."""
        pass
    
    @property
    @abstractmethod
    def operations(self) -> List[str]:
        """Available operations."""
        pass
    
    @abstractmethod
    async def execute(self, operation: str, params: Dict[str, Any]) -> PrimitiveResult:
        """Execute an operation."""
        pass
    
    def describe(self) -> Dict[str, Any]:
        """Describe this primitive for the LLM."""
        return {
            "name": self.name,
            "operations": self.operations,
        }


# ============================================================
#  FILE PRIMITIVE
# ============================================================

class FilePrimitive(Primitive):
    """
    File system operations.
    
    Operations:
    - read: Read file contents
    - write: Write content to file
    - search: Find files matching pattern
    - list: List directory contents
    - move: Move/rename file
    - delete: Delete file
    - exists: Check if file exists
    - info: Get file metadata
    """
    
    def __init__(self, allowed_paths: Optional[List[str]] = None):
        self._allowed_paths = allowed_paths or [str(Path.home())]
    
    @property
    def name(self) -> str:
        return "FILE"
    
    @property
    def operations(self) -> List[str]:
        return ["read", "write", "search", "list", "move", "delete", "exists", "info"]
    
    def _is_path_allowed(self, path: str) -> bool:
        """Check if path is within allowed directories."""
        path = str(Path(path).resolve())
        return any(path.startswith(allowed) for allowed in self._allowed_paths)
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> PrimitiveResult:
        try:
            if operation == "read":
                path = params.get("path")
                if not self._is_path_allowed(path):
                    return PrimitiveResult(False, error="Path not allowed")
                
                with open(path, "r") as f:
                    content = f.read()
                return PrimitiveResult(True, data=content, metadata={"path": path, "size": len(content)})
            
            elif operation == "write":
                path = params.get("path")
                content = params.get("content")
                if not self._is_path_allowed(path):
                    return PrimitiveResult(False, error="Path not allowed")
                
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                with open(path, "w") as f:
                    f.write(content)
                return PrimitiveResult(True, data={"path": path}, metadata={"size": len(content)})
            
            elif operation == "search":
                pattern = params.get("pattern", "*")
                directory = params.get("directory", str(Path.home()))
                recursive = params.get("recursive", True)
                limit = params.get("limit", 100)
                
                if not self._is_path_allowed(directory):
                    return PrimitiveResult(False, error="Directory not allowed")
                
                base = Path(directory)
                if recursive:
                    matches = list(base.rglob(pattern))[:limit]
                else:
                    matches = list(base.glob(pattern))[:limit]
                
                files = [{"path": str(m), "name": m.name, "is_dir": m.is_dir()} for m in matches]
                return PrimitiveResult(True, data=files, metadata={"count": len(files)})
            
            elif operation == "list":
                directory = params.get("directory", str(Path.home()))
                if not self._is_path_allowed(directory):
                    return PrimitiveResult(False, error="Directory not allowed")
                
                base = Path(directory)
                items = [
                    {"path": str(p), "name": p.name, "is_dir": p.is_dir(), "size": p.stat().st_size if p.is_file() else 0}
                    for p in base.iterdir()
                ]
                return PrimitiveResult(True, data=items, metadata={"count": len(items)})
            
            elif operation == "move":
                source = params.get("source")
                destination = params.get("destination")
                if not self._is_path_allowed(source) or not self._is_path_allowed(destination):
                    return PrimitiveResult(False, error="Path not allowed")
                
                Path(source).rename(destination)
                return PrimitiveResult(True, data={"source": source, "destination": destination})
            
            elif operation == "delete":
                path = params.get("path")
                if not self._is_path_allowed(path):
                    return PrimitiveResult(False, error="Path not allowed")
                
                p = Path(path)
                if p.is_dir():
                    import shutil
                    shutil.rmtree(path)
                else:
                    p.unlink()
                return PrimitiveResult(True, data={"deleted": path})
            
            elif operation == "exists":
                path = params.get("path")
                exists = Path(path).exists()
                return PrimitiveResult(True, data={"exists": exists, "path": path})
            
            elif operation == "info":
                path = params.get("path")
                if not self._is_path_allowed(path):
                    return PrimitiveResult(False, error="Path not allowed")
                
                p = Path(path)
                stat = p.stat()
                return PrimitiveResult(True, data={
                    "path": str(p),
                    "name": p.name,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    "is_dir": p.is_dir(),
                    "extension": p.suffix,
                })
            
            else:
                return PrimitiveResult(False, error=f"Unknown operation: {operation}")
                
        except Exception as e:
            logger.error(f"FILE.{operation} error: {e}")
            return PrimitiveResult(False, error=str(e))


# ============================================================
#  DOCUMENT PRIMITIVE
# ============================================================

class DocumentPrimitive(Primitive):
    """
    Document understanding and creation.
    
    Operations:
    - extract: Use LLM to extract structured data from document
    - parse: Parse document into text
    - create: Create a new document
    - convert: Convert between formats
    - summarize: Summarize document content
    """
    
    def __init__(self, llm_client=None):
        self._llm = llm_client
    
    @property
    def name(self) -> str:
        return "DOCUMENT"
    
    @property
    def operations(self) -> List[str]:
        return ["extract", "parse", "create", "convert", "summarize"]
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> PrimitiveResult:
        try:
            if operation == "extract":
                # Use LLM to extract structured data
                content = params.get("content")
                schema = params.get("schema")  # What to extract
                
                if not self._llm:
                    return PrimitiveResult(False, error="LLM not configured")
                
                prompt = f"""Extract the following information from this document.
                
Schema to extract: {json.dumps(schema)}

Document content:
{content[:10000]}  # Limit for context

Return a JSON object with the extracted values. If a value cannot be found, use null."""

                response = await self._llm.complete(prompt)
                
                # Parse JSON from response
                try:
                    # Find JSON in response
                    json_match = re.search(r'\{[\s\S]*\}', response)
                    if json_match:
                        extracted = json.loads(json_match.group())
                    else:
                        extracted = {"raw": response}
                except json.JSONDecodeError:
                    extracted = {"raw": response}
                
                return PrimitiveResult(True, data=extracted, metadata={"schema": schema})
            
            elif operation == "parse":
                # Parse document to text
                path = params.get("path")
                content = params.get("content")
                
                if path:
                    ext = Path(path).suffix.lower()
                    
                    if ext == ".pdf":
                        # Use pypdf if available
                        try:
                            import pypdf
                            reader = pypdf.PdfReader(path)
                            text = "\n".join(page.extract_text() for page in reader.pages)
                        except ImportError:
                            return PrimitiveResult(False, error="pypdf not installed")
                    
                    elif ext in [".txt", ".md", ".csv", ".json"]:
                        with open(path, "r") as f:
                            text = f.read()
                    
                    elif ext in [".docx"]:
                        try:
                            import docx
                            doc = docx.Document(path)
                            text = "\n".join(p.text for p in doc.paragraphs)
                        except ImportError:
                            return PrimitiveResult(False, error="python-docx not installed")
                    
                    else:
                        # Try as text
                        with open(path, "r") as f:
                            text = f.read()
                else:
                    text = content or ""
                
                return PrimitiveResult(True, data=text, metadata={"length": len(text)})
            
            elif operation == "create":
                # Create a document
                format_type = params.get("format", "text")  # text, csv, json, markdown
                content = params.get("content")
                data = params.get("data")  # Structured data
                path = params.get("path")
                
                if format_type == "csv" and data:
                    import csv
                    import io
                    output = io.StringIO()
                    if isinstance(data, list) and data:
                        writer = csv.DictWriter(output, fieldnames=data[0].keys())
                        writer.writeheader()
                        writer.writerows(data)
                    result = output.getvalue()
                
                elif format_type == "json" and data:
                    result = json.dumps(data, indent=2)
                
                elif format_type == "markdown":
                    result = content or ""
                    if data:
                        # Convert data to markdown table
                        if isinstance(data, list) and data:
                            headers = list(data[0].keys())
                            result += "\n| " + " | ".join(headers) + " |\n"
                            result += "| " + " | ".join(["---"] * len(headers)) + " |\n"
                            for row in data:
                                result += "| " + " | ".join(str(row.get(h, "")) for h in headers) + " |\n"
                
                else:
                    result = content or str(data)
                
                if path:
                    with open(path, "w") as f:
                        f.write(result)
                
                return PrimitiveResult(True, data=result, metadata={"format": format_type, "path": path})
            
            elif operation == "summarize":
                content = params.get("content")
                max_length = params.get("max_length", 500)
                
                if not self._llm:
                    return PrimitiveResult(False, error="LLM not configured")
                
                prompt = f"""Summarize the following document in {max_length} characters or less:

{content[:10000]}"""

                summary = await self._llm.complete(prompt)
                return PrimitiveResult(True, data=summary[:max_length])
            
            else:
                return PrimitiveResult(False, error=f"Unknown operation: {operation}")
                
        except Exception as e:
            logger.error(f"DOCUMENT.{operation} error: {e}")
            return PrimitiveResult(False, error=str(e))


# ============================================================
#  COMPUTE PRIMITIVE
# ============================================================

class ComputePrimitive(Primitive):
    """
    Calculations and data transformations.
    
    Operations:
    - formula: Apply a named formula (amortization, compound_interest, etc.)
    - calculate: Evaluate a mathematical expression
    - aggregate: Sum, average, etc. on data
    - transform: Apply transformation to data
    """
    
    @property
    def name(self) -> str:
        return "COMPUTE"
    
    @property
    def operations(self) -> List[str]:
        return ["formula", "calculate", "aggregate", "transform"]
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> PrimitiveResult:
        try:
            if operation == "formula":
                formula_name = params.get("name")
                inputs = params.get("inputs", {})
                
                if formula_name == "amortization":
                    # Calculate loan amortization schedule
                    principal = float(inputs.get("principal", 0))
                    annual_rate = float(inputs.get("rate", 0)) / 100
                    months = int(inputs.get("term_months", inputs.get("term", 0) * 12))
                    
                    if principal <= 0 or annual_rate <= 0 or months <= 0:
                        return PrimitiveResult(False, error="Invalid inputs for amortization")
                    
                    monthly_rate = annual_rate / 12
                    
                    # Monthly payment formula
                    payment = principal * (monthly_rate * (1 + monthly_rate)**months) / ((1 + monthly_rate)**months - 1)
                    
                    schedule = []
                    balance = principal
                    total_interest = 0
                    
                    for month in range(1, months + 1):
                        interest = balance * monthly_rate
                        principal_payment = payment - interest
                        balance -= principal_payment
                        total_interest += interest
                        
                        schedule.append({
                            "month": month,
                            "payment": round(payment, 2),
                            "principal": round(principal_payment, 2),
                            "interest": round(interest, 2),
                            "balance": round(max(0, balance), 2),
                        })
                    
                    return PrimitiveResult(True, data={
                        "monthly_payment": round(payment, 2),
                        "total_interest": round(total_interest, 2),
                        "total_paid": round(payment * months, 2),
                        "schedule": schedule,
                    })
                
                elif formula_name == "compound_interest":
                    principal = float(inputs.get("principal", 0))
                    rate = float(inputs.get("rate", 0)) / 100
                    years = float(inputs.get("years", 1))
                    compounds_per_year = int(inputs.get("compounds_per_year", 12))
                    
                    amount = principal * (1 + rate/compounds_per_year)**(compounds_per_year * years)
                    return PrimitiveResult(True, data={
                        "final_amount": round(amount, 2),
                        "interest_earned": round(amount - principal, 2),
                    })
                
                elif formula_name == "percentage":
                    value = float(inputs.get("value", 0))
                    percentage = float(inputs.get("percentage", 0))
                    result = value * percentage / 100
                    return PrimitiveResult(True, data={"result": round(result, 2)})
                
                else:
                    return PrimitiveResult(False, error=f"Unknown formula: {formula_name}")
            
            elif operation == "calculate":
                expression = params.get("expression")
                variables = params.get("variables", {})
                
                # Safe evaluation (basic math only)
                allowed_names = {"abs": abs, "round": round, "min": min, "max": max, "sum": sum}
                allowed_names.update(variables)
                
                # Very basic expression evaluation
                result = eval(expression, {"__builtins__": {}}, allowed_names)
                return PrimitiveResult(True, data={"result": result})
            
            elif operation == "aggregate":
                data = params.get("data", [])
                field = params.get("field")
                func = params.get("function", "sum")
                
                if field:
                    values = [item.get(field, 0) for item in data if isinstance(item, dict)]
                else:
                    values = data
                
                values = [float(v) for v in values if v is not None]
                
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
                    return PrimitiveResult(False, error=f"Unknown function: {func}")
                
                return PrimitiveResult(True, data={"result": round(result, 2), "function": func})
            
            elif operation == "transform":
                data = params.get("data", [])
                transformation = params.get("transformation")
                
                # Apply transformation to each item
                # This would use LLM for complex transformations
                return PrimitiveResult(True, data=data)
            
            else:
                return PrimitiveResult(False, error=f"Unknown operation: {operation}")
                
        except Exception as e:
            logger.error(f"COMPUTE.{operation} error: {e}")
            return PrimitiveResult(False, error=str(e))


# ============================================================
#  EMAIL PRIMITIVE
# ============================================================

class EmailPrimitive(Primitive):
    """
    Email operations.
    
    Operations:
    - send: Send an email
    - draft: Create a draft
    - search: Search emails
    - read: Read an email
    - reply: Reply to an email
    """
    
    def __init__(self, gmail_connector=None):
        self._gmail = gmail_connector
    
    @property
    def name(self) -> str:
        return "EMAIL"
    
    @property
    def operations(self) -> List[str]:
        return ["send", "draft", "search", "read", "reply", "list_unread"]
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> PrimitiveResult:
        if not self._gmail:
            return PrimitiveResult(False, error="Email not connected")
        
        try:
            if operation == "send":
                result = await self._gmail.send_message(
                    to=params.get("to"),
                    subject=params.get("subject"),
                    body=params.get("body"),
                    cc=params.get("cc"),
                    bcc=params.get("bcc"),
                    # attachments=params.get("attachments"),  # TODO: implement
                )
                return PrimitiveResult(True, data=result)
            
            elif operation == "draft":
                result = await self._gmail.create_draft(
                    to=params.get("to"),
                    subject=params.get("subject"),
                    body=params.get("body"),
                )
                return PrimitiveResult(True, data=result)
            
            elif operation == "search":
                messages = await self._gmail.list_messages(
                    query=params.get("query", ""),
                    max_results=params.get("limit", 20),
                )
                return PrimitiveResult(True, data=messages, metadata={"count": len(messages)})
            
            elif operation == "read":
                message = await self._gmail.get_message(params.get("message_id"))
                return PrimitiveResult(True, data=message)
            
            elif operation == "list_unread":
                messages = await self._gmail.list_messages(
                    query="is:unread",
                    max_results=params.get("limit", 20),
                )
                return PrimitiveResult(True, data=messages, metadata={"count": len(messages)})
            
            else:
                return PrimitiveResult(False, error=f"Unknown operation: {operation}")
                
        except Exception as e:
            logger.error(f"EMAIL.{operation} error: {e}")
            return PrimitiveResult(False, error=str(e))


# ============================================================
#  CALENDAR PRIMITIVE
# ============================================================

class CalendarPrimitive(Primitive):
    """
    Calendar operations.
    
    Operations:
    - list: List events
    - create: Create event
    - update: Update event
    - delete: Delete event
    - find_free: Find free time slots
    """
    
    def __init__(self, calendar_connector=None):
        self._calendar = calendar_connector
    
    @property
    def name(self) -> str:
        return "CALENDAR"
    
    @property
    def operations(self) -> List[str]:
        return ["list", "create", "update", "delete", "find_free"]
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> PrimitiveResult:
        if not self._calendar:
            return PrimitiveResult(False, error="Calendar not connected")
        
        try:
            if operation == "list":
                events = await self._calendar.list_events(
                    time_min=params.get("start"),
                    time_max=params.get("end"),
                    max_results=params.get("limit", 20),
                )
                return PrimitiveResult(True, data=events, metadata={"count": len(events)})
            
            elif operation == "create":
                event = await self._calendar.create_event(
                    summary=params.get("title"),
                    start_time=params.get("start"),
                    end_time=params.get("end"),
                    description=params.get("description"),
                    location=params.get("location"),
                    attendees=params.get("attendees"),
                )
                return PrimitiveResult(True, data=event)
            
            elif operation == "update":
                event = await self._calendar.update_event(
                    event_id=params.get("event_id"),
                    summary=params.get("title"),
                    start_time=params.get("start"),
                    end_time=params.get("end"),
                )
                return PrimitiveResult(True, data=event)
            
            elif operation == "delete":
                await self._calendar.delete_event(params.get("event_id"))
                return PrimitiveResult(True)
            
            else:
                return PrimitiveResult(False, error=f"Unknown operation: {operation}")
                
        except Exception as e:
            logger.error(f"CALENDAR.{operation} error: {e}")
            return PrimitiveResult(False, error=str(e))


# ============================================================
#  CONTACTS PRIMITIVE
# ============================================================

class ContactsPrimitive(Primitive):
    """
    Contact management.
    
    Operations:
    - search: Find contacts by name/email
    - get: Get contact details
    - add: Add a contact
    """
    
    def __init__(self, contacts_connector=None):
        self._contacts = contacts_connector
        self._local_contacts: Dict[str, Dict] = {}  # Fallback local storage
    
    @property
    def name(self) -> str:
        return "CONTACTS"
    
    @property
    def operations(self) -> List[str]:
        return ["search", "get", "add", "list"]
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> PrimitiveResult:
        try:
            if operation == "search":
                query = params.get("query", "").lower()
                
                if self._contacts:
                    # Use connected contacts service
                    results = await self._contacts.search(query)
                else:
                    # Search local contacts
                    results = [
                        c for c in self._local_contacts.values()
                        if query in c.get("name", "").lower() or query in c.get("email", "").lower()
                    ]
                
                return PrimitiveResult(True, data=results, metadata={"count": len(results)})
            
            elif operation == "add":
                contact = {
                    "name": params.get("name"),
                    "email": params.get("email"),
                    "phone": params.get("phone"),
                }
                
                if self._contacts:
                    result = await self._contacts.add(contact)
                else:
                    # Add to local contacts
                    key = contact["email"] or contact["name"]
                    self._local_contacts[key] = contact
                    result = contact
                
                return PrimitiveResult(True, data=result)
            
            elif operation == "list":
                if self._contacts:
                    results = await self._contacts.list()
                else:
                    results = list(self._local_contacts.values())
                
                return PrimitiveResult(True, data=results, metadata={"count": len(results)})
            
            else:
                return PrimitiveResult(False, error=f"Unknown operation: {operation}")
                
        except Exception as e:
            logger.error(f"CONTACTS.{operation} error: {e}")
            return PrimitiveResult(False, error=str(e))


# ============================================================
#  KNOWLEDGE PRIMITIVE (Memory)
# ============================================================

class KnowledgePrimitive(Primitive):
    """
    Knowledge/Memory operations.
    
    Operations:
    - remember: Store information
    - recall: Retrieve relevant information
    - forget: Remove information
    - search: Search knowledge base
    """
    
    def __init__(self, memory_systems=None):
        self._memory = memory_systems
        self._local_knowledge: List[Dict] = []  # Fallback
    
    @property
    def name(self) -> str:
        return "KNOWLEDGE"
    
    @property
    def operations(self) -> List[str]:
        return ["remember", "recall", "forget", "search"]
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> PrimitiveResult:
        try:
            if operation == "remember":
                content = params.get("content")
                tags = params.get("tags", [])
                
                if self._memory:
                    memory_id = await self._memory.store(content, tags=tags)
                else:
                    memory_id = f"mem_{len(self._local_knowledge)}"
                    self._local_knowledge.append({
                        "id": memory_id,
                        "content": content,
                        "tags": tags,
                        "timestamp": datetime.now().isoformat(),
                    })
                
                return PrimitiveResult(True, data={"memory_id": memory_id})
            
            elif operation == "recall":
                query = params.get("query")
                limit = params.get("limit", 5)
                
                if self._memory:
                    memories = await self._memory.recall(query, limit=limit)
                else:
                    # Simple keyword matching
                    query_lower = query.lower()
                    memories = [
                        m for m in self._local_knowledge
                        if query_lower in m["content"].lower()
                    ][:limit]
                
                return PrimitiveResult(True, data=memories, metadata={"count": len(memories)})
            
            elif operation == "search":
                return await self.execute("recall", params)
            
            else:
                return PrimitiveResult(False, error=f"Unknown operation: {operation}")
                
        except Exception as e:
            logger.error(f"KNOWLEDGE.{operation} error: {e}")
            return PrimitiveResult(False, error=str(e))


# ============================================================
#  PRIMITIVE REGISTRY
# ============================================================

class PrimitiveRegistry:
    """
    Registry of all available primitives.
    
    The LLM uses this to understand what operations are available.
    """
    
    def __init__(self):
        self._primitives: Dict[str, Primitive] = {}
    
    def register(self, primitive: Primitive):
        """Register a primitive."""
        self._primitives[primitive.name] = primitive
        logger.info(f"Registered primitive: {primitive.name}")
    
    def get(self, name: str) -> Optional[Primitive]:
        """Get a primitive by name."""
        return self._primitives.get(name)
    
    async def execute(self, primitive_name: str, operation: str, params: Dict[str, Any]) -> PrimitiveResult:
        """Execute a primitive operation."""
        primitive = self.get(primitive_name)
        if not primitive:
            return PrimitiveResult(False, error=f"Unknown primitive: {primitive_name}")
        
        return await primitive.execute(operation, params)
    
    def describe_all(self) -> List[Dict[str, Any]]:
        """Describe all primitives for the LLM."""
        return [p.describe() for p in self._primitives.values()]
    
    def get_capabilities_prompt(self) -> str:
        """Generate a prompt describing all capabilities for the LLM."""
        lines = ["Available primitives and operations:\n"]
        
        for name, primitive in self._primitives.items():
            lines.append(f"\n{name}:")
            for op in primitive.operations:
                lines.append(f"  - {op}")
        
        return "\n".join(lines)


# ============================================================
#  FACTORY
# ============================================================

def create_primitive_registry(
    llm_client=None,
    gmail_connector=None,
    calendar_connector=None,
    contacts_connector=None,
    memory_systems=None,
    allowed_paths: Optional[List[str]] = None,
) -> PrimitiveRegistry:
    """Create a fully configured primitive registry."""
    
    registry = PrimitiveRegistry()
    
    # Register all primitives
    registry.register(FilePrimitive(allowed_paths))
    registry.register(DocumentPrimitive(llm_client))
    registry.register(ComputePrimitive())
    registry.register(EmailPrimitive(gmail_connector))
    registry.register(CalendarPrimitive(calendar_connector))
    registry.register(ContactsPrimitive(contacts_connector))
    registry.register(KnowledgePrimitive(memory_systems))
    
    return registry
