"""
Privacy Layer - Data Sovereignty for Apex

This module implements the core privacy principles:
1. Your data stays LOCAL - never sent externally without your knowledge
2. Minimal context - only summaries/keywords go to LLM, never raw content
3. Full audit trail - see exactly what was transmitted and when
4. Sensitive markers - flag files/folders as "never send"
5. Auto-redaction - strip PII before any external call
6. Local vector DB - semantic search stays on your machine

Components:
- AuditLogger: Tracks all external data transmissions
- RedactionEngine: Strips SSN, credit cards, account numbers
- SecureLLMClient: Privacy-wrapped LLM client
- SensitiveMarker: Marks files/folders as private (never send)
- ContextMinimizer: Extracts only needed context for LLM queries
- LocalVectorDB: Local semantic search (ChromaDB wrapper)
"""

from .audit_log import AuditLogger, TransmissionRecord, audit_logger
from .redaction import RedactionEngine, redaction_engine, PIIType
from .secure_llm import SecureLLMClient, wrap_client_secure, create_secure_client_from_env
from .sensitive_marker import SensitiveMarker, SensitivityLevel, sensitive_marker
from .context_minimizer import ContextMinimizer, MinimalContext, ExtractionMode, context_minimizer
# Lazy import - chromadb is heavy (~1.4s)
def __getattr__(name):
    if name in ('LocalVectorDB', 'SearchResult', 'SearchResults', 'local_vector_db'):
        from .local_vector_db import LocalVectorDB, SearchResult, SearchResults, local_vector_db
        globals().update({
            'LocalVectorDB': LocalVectorDB,
            'SearchResult': SearchResult,
            'SearchResults': SearchResults,
            'local_vector_db': local_vector_db,
        })
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    'AuditLogger',
    'TransmissionRecord', 
    'audit_logger',
    'RedactionEngine',
    'redaction_engine',
    'PIIType',
    'SecureLLMClient',
    'wrap_client_secure',
    'create_secure_client_from_env',
    'SensitiveMarker',
    'SensitivityLevel',
    'sensitive_marker',
    'ContextMinimizer',
    'MinimalContext',
    'ExtractionMode',
    'context_minimizer',
    'LocalVectorDB',
    'SearchResult',
    'SearchResults',
    'local_vector_db',
]
