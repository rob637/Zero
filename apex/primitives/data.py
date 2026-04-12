"""Telic Engine — Data & Knowledge Primitives"""

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

                has_content = isinstance(content, str) and bool(content.strip())
                has_data = data is not None and (not isinstance(data, (list, dict)) or len(data) > 0)
                if not has_content and not has_data:
                    content = str(params.get("title") or "Untitled document")
                
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
                    "__import__": lambda name, *a, **k: __import__(name) if name in ("math", "datetime", "json", "re", "uuid") else (_ for _ in ()).throw(ImportError(f"Import of '{name}' not allowed")),
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
                    dataset_name = params.get("dataset") or params.get("name") or params.get("source")
                    if dataset_name and dataset_name in self._datasets:
                        data = self._datasets[dataset_name]

                # Fall back to the only known dataset when unambiguous.
                if not data and len(self._datasets) == 1:
                    data = next(iter(self._datasets.values()))

                # Some tool chains pass rows/items/photos under alternate keys.
                if not data:
                    for key in ("rows", "items", "results", "records", "photos"):
                        value = params.get(key)
                        if isinstance(value, list) and value:
                            data = value
                            break
                
                if not data:
                    known = sorted(self._datasets.keys())
                    hint = f" Available datasets: {known}." if known else ""
                    return StepResult(False, error="No data provided. Pass 'data' (list of dicts) or wire from a previous step." + hint)
                
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



class KnowledgePrimitive(Primitive):
    """Memory and knowledge storage backed by the intelligence layer's SemanticMemory.
    
    Provides the agent with persistent, semantic memory — facts about people,
    preferences, relationships, and context that survive across sessions.
    """
    
    def __init__(self, storage_path: Optional[str] = None):
        # Initialize real semantic memory from intelligence layer
        try:
            from intelligence.semantic_memory import get_semantic_memory
            self._memory = get_semantic_memory()
        except ImportError:
            self._memory = None
        # Keep legacy fallback
        self._memories: List[Dict] = []
        self._storage_path = storage_path
        if storage_path and Path(storage_path).exists():
            self._load()
    
    @property
    def name(self) -> str:
        return "KNOWLEDGE"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "remember": "Store a fact or piece of information for later recall. Use this to remember user preferences, facts about people, important context, or anything worth persisting across conversations.",
            "recall": "Search memory for relevant facts matching a query. Returns the most relevant stored facts ranked by relevance.",
            "recall_about": "Get everything known about a specific person or entity — all facts, relationships, interaction history.",
            "connect": "Create a relationship between two entities in the knowledge graph (e.g., 'Alice' works_with 'Bob').",
            "forget": "Remove stored information by fact ID or entity name.",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "remember": {
                "content": {"type": "str", "required": True, "description": "The fact or information to remember"},
                "entity": {"type": "str", "required": False, "description": "Primary entity this fact is about (person name, org, etc.)"},
                "category": {"type": "str", "required": False, "description": "Category: preference, relationship, event, insight, context, instruction, behavior, entity_info"},
            },
            "recall": {
                "query": {"type": "str", "required": True, "description": "Search query to find relevant memories"},
                "limit": {"type": "int", "required": False, "description": "Max results (default 5)"},
            },
            "recall_about": {
                "entity": {"type": "str", "required": True, "description": "Person or entity name to get facts about"},
            },
            "connect": {
                "entity1": {"type": "str", "required": True, "description": "First entity name"},
                "relationship": {"type": "str", "required": True, "description": "Relationship type (e.g., works_with, manages, married_to)"},
                "entity2": {"type": "str", "required": True, "description": "Second entity name"},
            },
            "forget": {
                "entity": {"type": "str", "required": False, "description": "Entity name — forgets all facts about this entity"},
                "fact_id": {"type": "str", "required": False, "description": "Specific fact ID to remove"},
            },
        }
    
    def _load(self):
        if self._storage_path:
            try:
                with open(self._storage_path, "r") as f:
                    self._memories = json.load(f)
            except Exception:
                pass
    
    def _save(self):
        if self._storage_path:
            Path(self._storage_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self._storage_path, "w") as f:
                json.dump(self._memories, f, indent=2)
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            # Use real SemanticMemory if available
            if self._memory:
                return await self._execute_semantic(operation, params)
            # Fallback to basic list storage
            return await self._execute_basic(operation, params)
        except Exception as e:
            return StepResult(False, error=str(e))
    
    async def _execute_semantic(self, operation: str, params: Dict[str, Any]) -> StepResult:
        """Execute using the real SemanticMemory intelligence layer."""
        if operation == "remember":
            content = params.get("content") or params.get("text") or ""
            entity = params.get("entity")
            category_str = params.get("category", "context")
            
            # Convert category string to enum, fallback to CONTEXT
            from intelligence.semantic_memory import FactCategory
            category_map = {c.value: c for c in FactCategory}
            category = category_map.get(category_str.lower(), FactCategory.CONTEXT) if isinstance(category_str, str) else category_str
            
            fact = await self._memory.remember(
                content,
                category=category,
                entity=entity,
            )
            return StepResult(True, data={
                "stored": True,
                "fact_id": fact.id if hasattr(fact, 'id') else str(fact),
                "message": f"Remembered: {content[:100]}"
            })
        
        elif operation == "recall":
            query = params.get("query", "")
            limit = params.get("limit", 5)
            
            results = await self._memory.recall(query, limit=limit)
            if not results:
                return StepResult(True, data={"results": [], "message": "No matching memories found."})
            
            facts = []
            for item in results:
                # recall() returns List[Tuple[Fact, float]]
                fact = item[0] if isinstance(item, tuple) else item
                if hasattr(fact, 'content'):
                    facts.append({
                        "content": fact.content,
                        "category": fact.category.value if hasattr(fact.category, 'value') else str(fact.category),
                        "entity": fact.primary_entity,
                        "created": fact.created_at if hasattr(fact, 'created_at') else None,
                    })
                elif isinstance(fact, dict):
                    facts.append(fact)
            
            return StepResult(True, data={"results": facts[:limit]})
        
        elif operation == "recall_about":
            entity = params.get("entity", "")
            facts = await self._memory.recall_about(entity)
            
            if not facts:
                return StepResult(True, data={"entity": entity, "facts": [], "message": f"No facts known about '{entity}'."})
            
            fact_list = []
            for f in facts:
                if hasattr(f, 'content'):
                    fact_list.append({"content": f.content, "category": f.category.value if hasattr(f.category, 'value') else str(f.category)})
                elif isinstance(f, dict):
                    fact_list.append(f)
            
            # Also get entity summary if available
            entity_info = await self._memory.get_entity(entity)
            summary = None
            if entity_info and isinstance(entity_info, dict):
                summary = entity_info.get("summary")
            
            return StepResult(True, data={
                "entity": entity,
                "facts": fact_list,
                "summary": summary,
                "count": len(fact_list),
            })
        
        elif operation == "connect":
            e1 = params.get("entity1", "")
            rel = params.get("relationship", "")
            e2 = params.get("entity2", "")
            await self._memory.connect_entities(e1, rel, e2)
            return StepResult(True, data={"connected": f"{e1} --[{rel}]--> {e2}"})
        
        elif operation == "forget":
            entity = params.get("entity")
            fact_id = params.get("fact_id")
            if entity:
                await self._memory.forget(entity=entity)
                return StepResult(True, data={"forgotten": f"All facts about '{entity}'"})
            elif fact_id:
                await self._memory.forget(fact_id=fact_id)
                return StepResult(True, data={"forgotten": f"Fact {fact_id}"})
            else:
                return StepResult(False, error="Provide either 'entity' or 'fact_id'")
        
        else:
            return StepResult(False, error=f"Unknown operation: {operation}")
    
    async def _execute_basic(self, operation: str, params: Dict[str, Any]) -> StepResult:
        """Fallback: basic list-based memory."""
        if operation == "remember":
            content = params.get("content", "")
            memory = {
                "id": len(self._memories),
                "content": content,
                "tags": params.get("tags", []),
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
            memory_id = params.get("id") or params.get("fact_id")
            self._memories = [m for m in self._memories if m.get("id") != memory_id]
            self._save()
            return StepResult(True)
        
        else:
            return StepResult(True, data={"results": []})


# ============================================================
#  PATTERNS PRIMITIVE
# ============================================================



class PatternsPrimitive(Primitive):
    """Behavioral pattern recognition — detects routines, habits, and anomalies.
    
    The agent can check what the user typically does at this time,
    detect when something is unusual, and understand recurring behaviors.
    """
    
    def __init__(self):
        try:
            from intelligence.pattern_recognition import get_pattern_engine
            self._patterns = get_pattern_engine()
        except ImportError:
            self._patterns = None
    
    @property
    def name(self) -> str:
        return "PATTERNS"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "whats_expected": "Check what the user typically does at this time of day/week. Use to proactively suggest routine actions.",
            "get_patterns": "List all detected behavioral patterns (routines, habits, recurring actions).",
            "detect_anomalies": "Check for anything unusual — missed routines, unexpected behavior changes.",
        }
    
    def get_available_operations(self) -> Dict[str, str]:
        if not self._patterns:
            return {}
        return self.get_operations()
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "whats_expected": {
                "window_minutes": {"type": "int", "required": False, "description": "Time window to check (default 60 minutes)"},
            },
            "get_patterns": {
                "min_confidence": {"type": "float", "required": False, "description": "Minimum confidence threshold 0-1 (default 0.5)"},
            },
            "detect_anomalies": {
                "lookback_days": {"type": "int", "required": False, "description": "Days to look back for anomaly detection (default 7)"},
            },
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        if not self._patterns:
            return StepResult(False, error="Pattern engine not available")
        
        try:
            if operation == "whats_expected":
                window = params.get("window_minutes", 60)
                expected = await self._patterns.whats_expected_now(window_minutes=window)
                if not expected:
                    return StepResult(True, data={"expected": [], "message": "No expected patterns right now."})
                # whats_expected_now() returns List[Dict] with keys: pattern, description, confidence
                patterns = [{"name": p.get("pattern", ""), "description": p.get("description", ""), "confidence": p.get("confidence", 0)} for p in expected]
                return StepResult(True, data={"expected": patterns})
            
            elif operation == "get_patterns":
                min_conf = params.get("min_confidence", 0.5)
                detected = await self._patterns.get_patterns(min_confidence=min_conf)
                if not detected:
                    return StepResult(True, data={"patterns": [], "message": "No patterns detected yet. Patterns emerge after repeated usage."})
                patterns = [{
                    "name": p.name,
                    "description": p.description,
                    "type": p.pattern_type.value if hasattr(p.pattern_type, 'value') else str(p.pattern_type),
                    "confidence": p.confidence,
                    "occurrences": p.occurrence_count,
                } for p in detected]
                return StepResult(True, data={"patterns": patterns, "count": len(patterns)})
            
            elif operation == "detect_anomalies":
                lookback = params.get("lookback_days", 7)
                anomalies = await self._patterns.detect_anomalies(lookback_days=lookback)
                if not anomalies:
                    return StepResult(True, data={"anomalies": [], "message": "No anomalies detected."})
                items = [{"type": a.get("type", "unknown"), "description": a.get("description", ""), "severity": a.get("severity", "low")} for a in anomalies]
                return StepResult(True, data={"anomalies": items})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  INTELLIGENCE PRIMITIVE (cross-service + proactive)
# ============================================================



class IntelligencePrimitive(Primitive):
    """Cross-service intelligence — connects dots across email, calendar, files, and memory.
    
    Provides person briefs, meeting preparation, related content discovery,
    and proactive suggestions.
    """
    
    def __init__(self):
        try:
            from intelligence import get_intelligence_hub
            self._hub = get_intelligence_hub()
        except ImportError:
            self._hub = None
    
    @property
    def name(self) -> str:
        return "INTELLIGENCE"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "brief_on_person": "Get a comprehensive brief on a person — recent emails, meetings, shared docs, known facts, communication frequency.",
            "prepare_for_meeting": "Gather preparation materials for a meeting — attendee briefs, related emails/docs, suggested discussion points.",
            "find_related": "Search across all services for content related to a query — finds emails, docs, tasks, and memories that connect.",
            "get_suggestions": "Get proactive suggestions — things the user should do, follow up on, or prepare for.",
        }
    
    def get_available_operations(self) -> Dict[str, str]:
        if not self._hub:
            return {}
        return self.get_operations()
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "brief_on_person": {
                "person": {"type": "str", "required": True, "description": "Person name or email to get a brief on"},
            },
            "prepare_for_meeting": {
                "title": {"type": "str", "required": False, "description": "Meeting title to prepare for"},
                "attendees": {"type": "str", "required": False, "description": "Comma-separated attendee names/emails"},
            },
            "find_related": {
                "query": {"type": "str", "required": True, "description": "Topic or query to find related content across all services"},
                "max_items": {"type": "int", "required": False, "description": "Max results (default 10)"},
            },
            "get_suggestions": {
                "max_suggestions": {"type": "int", "required": False, "description": "Max suggestions to return (default 5)"},
            },
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        if not self._hub:
            return StepResult(False, error="Intelligence hub not available")
        
        try:
            if operation == "brief_on_person":
                person = params.get("person", "")
                brief = await self._hub.brief_on_person(person)
                if not brief:
                    return StepResult(True, data={"person": person, "message": f"No information found about '{person}'."})
                # Convert to serializable dict
                if hasattr(brief, '__dict__'):
                    data = {k: v for k, v in brief.__dict__.items() if not k.startswith('_')}
                elif isinstance(brief, dict):
                    data = brief
                else:
                    data = {"brief": str(brief)}
                data["person"] = person
                return StepResult(True, data=data)
            
            elif operation == "prepare_for_meeting":
                title = params.get("title")
                attendees_str = params.get("attendees", "")
                attendees = [a.strip() for a in attendees_str.split(",") if a.strip()] if attendees_str else []
                prep = await self._hub.prepare_for_meeting(title=title, attendees=attendees)
                if not prep:
                    return StepResult(True, data={"message": "No meeting preparation data available."})
                if hasattr(prep, '__dict__'):
                    data = {k: v for k, v in prep.__dict__.items() if not k.startswith('_')}
                elif isinstance(prep, dict):
                    data = prep
                else:
                    data = {"prep": str(prep)}
                return StepResult(True, data=data)
            
            elif operation == "find_related":
                query = params.get("query", "")
                max_items = params.get("max_items", 10)
                results = await self._hub.find_related(query, max_items=max_items)
                if not results:
                    return StepResult(True, data={"results": [], "message": f"No related content found for '{query}'."})
                items = []
                for r in results:
                    if hasattr(r, 'to_dict'):
                        items.append(r.to_dict())
                    elif hasattr(r, '__dict__'):
                        items.append({k: v for k, v in r.__dict__.items() if not k.startswith('_')})
                    else:
                        items.append(str(r))
                return StepResult(True, data={"results": items, "count": len(items)})
            
            elif operation == "get_suggestions":
                max_sugg = params.get("max_suggestions", 5)
                suggestions = await self._hub.get_suggestions(max_suggestions=max_sugg)
                if not suggestions:
                    return StepResult(True, data={"suggestions": [], "message": "No proactive suggestions right now."})
                items = []
                for s in suggestions:
                    if hasattr(s, 'to_dict'):
                        items.append(s.to_dict())
                    elif hasattr(s, '__dict__'):
                        items.append({k: v for k, v in s.__dict__.items() if not k.startswith('_')})
                    else:
                        items.append(str(s))
                return StepResult(True, data={"suggestions": items, "count": len(items)})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  CALENDAR PRIMITIVE
# ============================================================


