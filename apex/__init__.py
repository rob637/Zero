"""
Telic - AI Operating System

A primitives-based AI assistant that works with your real services.

Usage:
    from apex import Apex
    
    apex = Apex(api_key="...")
    
    # Local operations (no API key needed for these)
    result = await apex.do("Find all PDFs in ~/Documents")
    result = await apex.do("Calculate amortization for $300k at 7% for 30 years")
    
    # With Google integration
    await apex.connect_google()
    result = await apex.do("Find my unread emails from John")
    result = await apex.do("What meetings do I have tomorrow?")
"""

from apex.apex_engine import (
    Apex as BaseApex,
    Primitive,
    StepResult,
    PlanStep,
    ExecutionResult,
    FilePrimitive,
    DocumentPrimitive,
    ComputePrimitive,
    KnowledgePrimitive,
)

# Use v2 engine by default (includes Google integration)
from apex.apex_engine_v2 import Apex

__version__ = "0.1.0"

__all__ = [
    'Apex',
    'BaseApex',
    'Primitive',
    'StepResult',
    'PlanStep',
    'ExecutionResult',
    'FilePrimitive',
    'DocumentPrimitive',
    'ComputePrimitive',
    'KnowledgePrimitive',
]
