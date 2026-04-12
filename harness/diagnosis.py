"""Lightweight access to the shared Harness diagnosis implementation.

This keeps The Harness importable without triggering the full apex package
initializer, while still reusing the existing diagnosis logic.
"""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


_DIAGNOSIS_PATH = Path(__file__).resolve().parents[1] / "apex" / "harness" / "diagnosis.py"
_SPEC = spec_from_file_location("_shared_harness_diagnosis", _DIAGNOSIS_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Unable to load shared diagnosis module from {_DIAGNOSIS_PATH}")

_MODULE = module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

IssueCategory = _MODULE.IssueCategory
RootCause = _MODULE.RootCause
DiagnosisResult = _MODULE.DiagnosisResult
IssueAnalyzer = _MODULE.IssueAnalyzer
create_analyzer = _MODULE.create_analyzer

__all__ = [
    "IssueCategory",
    "RootCause",
    "DiagnosisResult",
    "IssueAnalyzer",
    "create_analyzer",
]