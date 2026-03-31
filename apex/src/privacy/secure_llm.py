"""
Secure LLM Wrapper - Privacy-First LLM Access

This module wraps the LLM client with privacy protections:
1. All outbound content is logged to the audit trail
2. PII is automatically redacted before transmission
3. Context is minimized to only what's needed
4. User can review exactly what was sent

Usage:
    client = SecureLLMClient(base_client)
    
    # This will:
    # 1. Redact any PII in the prompt
    # 2. Log the outbound transmission
    # 3. Call the LLM
    # 4. Log the inbound response
    # 5. Return the result
    
    response = await client.complete(
        system="You are a helpful assistant.",
        user="What's in doc with SSN 123-45-6789?",  # SSN will be redacted!
        triggering_request="User asked about document",
    )
"""

import time
from dataclasses import dataclass
from typing import Optional, Dict, Any
import logging

from ..privacy.audit_log import (
    AuditLogger,
    TransmissionDestination,
    audit_logger,
)
from ..privacy.redaction import RedactionEngine, redaction_engine

logger = logging.getLogger(__name__)


def provider_to_destination(provider: str) -> TransmissionDestination:
    """Map LLM provider to audit destination."""
    mapping = {
        "anthropic": TransmissionDestination.ANTHROPIC,
        "openai": TransmissionDestination.OPENAI,
        "google": TransmissionDestination.GOOGLE_AI,
        "ollama": TransmissionDestination.LOCAL_LLM,
        "llama": TransmissionDestination.LOCAL_LLM,
    }
    return mapping.get(provider.lower(), TransmissionDestination.OTHER)


class SecureLLMClient:
    """
    Privacy-first wrapper for LLM clients.
    
    Wraps any LLM client to add:
    - Automatic PII redaction
    - Audit logging of all transmissions
    - Context minimization (TODO)
    
    The original client is used for actual LLM calls,
    but all content passes through the privacy layer first.
    """
    
    def __init__(
        self,
        base_client,
        audit: Optional[AuditLogger] = None,
        redactor: Optional[RedactionEngine] = None,
        enable_redaction: bool = True,
        enable_audit: bool = True,
    ):
        """
        Initialize the secure wrapper.
        
        Args:
            base_client: The underlying LLM client (from llm.py)
            audit: AuditLogger instance (default: global)
            redactor: RedactionEngine instance (default: global)
            enable_redaction: Whether to redact PII (default: True)
            enable_audit: Whether to log transmissions (default: True)
        """
        self._client = base_client
        self._audit = audit or audit_logger
        self._redactor = redactor or redaction_engine
        self._enable_redaction = enable_redaction
        self._enable_audit = enable_audit
        
        # Tracking
        self._total_calls = 0
        self._total_redactions = 0
        self._total_bytes_sent = 0
        
        logger.info(
            f"SecureLLMClient initialized "
            f"(redaction: {enable_redaction}, audit: {enable_audit})"
        )
    
    @property
    def config(self):
        """Access underlying client config."""
        return self._client.config
    
    async def complete(
        self,
        system: str,
        user: str,
        json_mode: bool = False,
        triggering_request: str = "",
    ) -> str:
        """
        Get a completion from the LLM with privacy protections.
        
        Args:
            system: System prompt
            user: User message
            json_mode: If True, expect JSON output
            triggering_request: What the user asked (for audit trail)
            
        Returns:
            LLM response text
        """
        self._total_calls += 1
        
        # === STEP 1: Redact PII ===
        redacted_system = system
        redacted_user = user
        redaction_count = 0
        had_pii = False
        
        if self._enable_redaction:
            # Redact system prompt
            system_result = self._redactor.redact(system)
            redacted_system = system_result.redacted_text
            
            # Redact user message
            user_result = self._redactor.redact(user)
            redacted_user = user_result.redacted_text
            
            redaction_count = system_result.redaction_count + user_result.redaction_count
            had_pii = system_result.had_pii or user_result.had_pii
            
            if had_pii:
                self._total_redactions += redaction_count
                logger.info(f"Redacted {redaction_count} PII items before LLM call")
        
        # === STEP 2: Log outbound transmission ===
        outbound_content = f"SYSTEM:\n{redacted_system}\n\nUSER:\n{redacted_user}"
        destination = provider_to_destination(self._client.config.provider)
        request_id = None
        
        if self._enable_audit:
            # Skip audit for local LLMs (data stays on machine)
            if destination != TransmissionDestination.LOCAL_LLM:
                request_id = self._audit.log_outbound(
                    destination=destination,
                    content=outbound_content,
                    triggering_request=triggering_request or user[:100],
                    model=self._client.config.model,
                    contained_pii=had_pii,
                    redactions_applied=redaction_count,
                )
                
                self._total_bytes_sent += len(outbound_content.encode('utf-8'))
        
        # === STEP 3: Call LLM ===
        start_time = time.time()
        
        try:
            response = await self._client.complete(
                system=redacted_system,
                user=redacted_user,
                json_mode=json_mode,
            )
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            raise
        
        latency_ms = (time.time() - start_time) * 1000
        
        # === STEP 4: Log inbound response ===
        if self._enable_audit and destination != TransmissionDestination.LOCAL_LLM:
            self._audit.log_inbound(
                destination=destination,
                content=response,
                request_id=request_id,
                latency_ms=latency_ms,
                model=self._client.config.model,
            )
        
        logger.debug(f"LLM call completed in {latency_ms:.0f}ms")
        return response
    
    async def complete_json(
        self,
        system: str,
        user: str,
        triggering_request: str = "",
    ) -> dict:
        """
        Get a JSON completion from the LLM with privacy protections.
        
        Args:
            system: System prompt
            user: User message
            triggering_request: What the user asked (for audit trail)
            
        Returns:
            Parsed JSON dict
        """
        response = await self.complete(
            system=system,
            user=user,
            json_mode=True,
            triggering_request=triggering_request,
        )
        
        # Extract JSON from markdown code blocks if present
        import json
        
        if "```json" in response:
            response = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            response = response.split("```")[1].split("```")[0]
        
        return json.loads(response.strip())
    
    def get_stats(self) -> Dict[str, Any]:
        """Get privacy statistics for this client."""
        return {
            "total_calls": self._total_calls,
            "total_redactions": self._total_redactions,
            "total_bytes_sent": self._total_bytes_sent,
            "redaction_enabled": self._enable_redaction,
            "audit_enabled": self._enable_audit,
            "provider": self._client.config.provider,
            "model": self._client.config.model,
        }
    
    def clear_session(self):
        """Clear redaction session (removes in-memory PII mappings)."""
        if self._enable_redaction:
            self._redactor.clear_session()


def wrap_client_secure(base_client) -> SecureLLMClient:
    """
    Convenience function to wrap an LLM client with privacy protections.
    
    Args:
        base_client: Any LLM client from llm.py
        
    Returns:
        SecureLLMClient wrapper
    """
    return SecureLLMClient(base_client)


def create_secure_client_from_env():
    """
    Create a secure LLM client from environment variables.
    
    This is a drop-in replacement for create_client_from_env()
    that adds privacy protections.
    
    Returns:
        SecureLLMClient or None if no API keys found
    """
    # Import here to avoid circular imports
    from ..core.llm import create_client_from_env
    
    base_client = create_client_from_env()
    if base_client is None:
        return None
    
    return SecureLLMClient(base_client)
