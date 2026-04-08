"""
Primitive Resolver

Resolves abstract primitives to concrete connectors and executes operations
across multiple providers when needed.

This is the key component that enables:
- Provider-agnostic primitive execution
- Multi-provider aggregation (search Gmail AND Outlook)
- Automatic fallback when one provider fails
- User preference for preferred connectors
- Smart connector selection based on context

Architecture:
    User Request: "Search my email for invoices"
                        │
                        ▼
    Planner Output: EMAIL.search(query="invoices")
                        │
                        ▼
    PrimitiveResolver:
        1. Which connectors support EMAIL? → [gmail, outlook]
        2. Which are connected? → [gmail, outlook]
        3. User preference? → gmail (primary)
        4. Execution mode:
           - "single": Use preferred (gmail)
           - "all": Execute both, aggregate results
           - "fallback": Try primary, fall back if fails
                        │
                        ▼
    Aggregated Result: Combined results from all providers

Usage:
    from apex.connectors.resolver import PrimitiveResolver, get_resolver
    
    resolver = get_resolver()
    
    # Execute on preferred provider only
    result = await resolver.execute(
        primitive="EMAIL",
        operation="search",
        params={"query": "invoices"},
        mode="single",
    )
    
    # Execute on ALL connected providers (aggregate)
    results = await resolver.execute(
        primitive="EMAIL", 
        operation="search",
        params={"query": "invoices"},
        mode="all",
    )
    
    # Check what providers are available
    providers = resolver.get_available_providers("EMAIL")
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

from .registry import (
    ConnectorRegistry,
    ConnectorMetadata,
    ConnectionStatus,
    ConnectorHealth,
    BaseConnector,
    get_registry,
)
from .credentials import (
    CredentialStore,
    get_credential_store,
)


class ExecutionMode(Enum):
    """How to execute across multiple providers."""
    SINGLE = "single"         # Use preferred provider only
    ALL = "all"               # Execute on all connected, aggregate results
    FALLBACK = "fallback"     # Try preferred, fall back to others if error
    FASTEST = "fastest"       # Execute all, return first success
    PARALLEL = "parallel"     # Execute all in parallel, return all results


class AggregationStrategy(Enum):
    """How to aggregate results from multiple providers."""
    MERGE_LISTS = "merge_lists"     # Combine lists (for search results)
    FIRST_SUCCESS = "first_success"  # Return first successful result
    COLLECT_ALL = "collect_all"      # Return dict of {provider: result}
    COUNT = "count"                  # Sum numeric results


@dataclass
class ProviderResult:
    """Result from a single provider."""
    provider: str
    connector: str
    success: bool
    data: Any = None
    error: Optional[str] = None
    latency_ms: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            "provider": self.provider,
            "connector": self.connector,
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "latency_ms": self.latency_ms,
        }


@dataclass
class ResolverResult:
    """Aggregated result from primitive execution."""
    success: bool
    primitive: str
    operation: str
    providers_used: List[str]
    data: Any = None
    error: Optional[str] = None
    provider_results: List[ProviderResult] = field(default_factory=list)
    execution_mode: str = "single"
    total_latency_ms: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "primitive": self.primitive,
            "operation": self.operation,
            "providers_used": self.providers_used,
            "data": self.data,
            "error": self.error,
            "provider_results": [r.to_dict() for r in self.provider_results],
            "execution_mode": self.execution_mode,
            "total_latency_ms": self.total_latency_ms,
        }


# ============================================================================
# OPERATION TRAITS
# ============================================================================

# Operations that benefit from multi-provider aggregation
AGGREGATABLE_OPERATIONS = {
    "search", "list", "read", "get", "find", "query",
    "list_messages", "list_events", "list_files", "list_tasks",
    "get_unread", "get_count",
}

# Operations that should use a single provider (writes, sends)
SINGLE_PROVIDER_OPERATIONS = {
    "send", "create", "update", "delete", "write", "move",
    "reply", "forward", "draft", "schedule", "cancel",
}

# Operations that return numeric results (for COUNT aggregation)
COUNTABLE_OPERATIONS = {
    "count", "get_count", "get_unread_count",
}


def get_default_mode(operation: str) -> ExecutionMode:
    """Get default execution mode based on operation type."""
    op_lower = operation.lower()
    
    if op_lower in SINGLE_PROVIDER_OPERATIONS:
        return ExecutionMode.SINGLE
    elif op_lower in AGGREGATABLE_OPERATIONS:
        return ExecutionMode.ALL
    else:
        return ExecutionMode.SINGLE


def get_default_aggregation(operation: str) -> AggregationStrategy:
    """Get default aggregation strategy based on operation type."""
    op_lower = operation.lower()
    
    if op_lower in COUNTABLE_OPERATIONS:
        return AggregationStrategy.COUNT
    elif op_lower in AGGREGATABLE_OPERATIONS:
        return AggregationStrategy.MERGE_LISTS
    else:
        return AggregationStrategy.FIRST_SUCCESS


# ============================================================================
# PRIMITIVE RESOLVER
# ============================================================================

class PrimitiveResolver:
    """
    Resolves primitives to connectors and executes operations.
    
    This is the core execution layer that:
    - Maps primitive operations to connector methods
    - Handles multi-provider execution
    - Aggregates results intelligently
    - Manages fallback on errors
    """
    
    def __init__(
        self,
        registry: Optional[ConnectorRegistry] = None,
        credential_store: Optional[CredentialStore] = None,
    ):
        self._registry = registry or get_registry()
        self._credential_store = credential_store or get_credential_store()
        
        # Cache of connector instances
        self._connector_cache: Dict[str, BaseConnector] = {}
        
        # Method mapping: (primitive, operation) -> connector method name
        self._method_map: Dict[Tuple[str, str], str] = self._build_method_map()
    
    def _build_method_map(self) -> Dict[Tuple[str, str], str]:
        """
        Build mapping from (primitive, operation) to connector method names.
        
        Most operations map directly: EMAIL.send -> connector.send_email
        Some need translation: EMAIL.list -> connector.list_messages
        """
        return {
            # EMAIL operations
            ("EMAIL", "send"): "send_email",
            ("EMAIL", "draft"): "create_draft",
            ("EMAIL", "reply"): "reply_to_email",
            ("EMAIL", "forward"): "forward_email",
            ("EMAIL", "search"): "search_messages",
            ("EMAIL", "read"): "get_message",
            ("EMAIL", "list"): "list_messages",
            ("EMAIL", "move"): "move_message",
            ("EMAIL", "delete"): "delete_message",
            ("EMAIL", "label"): "add_labels",
            ("EMAIL", "archive"): "archive_message",
            
            # CALENDAR operations
            ("CALENDAR", "create"): "create_event",
            ("CALENDAR", "update"): "update_event",
            ("CALENDAR", "delete"): "delete_event",
            ("CALENDAR", "list"): "list_events",
            ("CALENDAR", "search"): "search_events",
            ("CALENDAR", "get"): "get_event",
            ("CALENDAR", "book"): "book_meeting",
            ("CALENDAR", "cancel"): "cancel_event",
            
            # CLOUD_STORAGE operations
            ("CLOUD_STORAGE", "list"): "list_files",
            ("CLOUD_STORAGE", "search"): "search_files",
            ("CLOUD_STORAGE", "read"): "read_file",
            ("CLOUD_STORAGE", "upload"): "upload_file",
            ("CLOUD_STORAGE", "download"): "download_file",
            ("CLOUD_STORAGE", "delete"): "delete_file",
            ("CLOUD_STORAGE", "share"): "share_file",
            
            # TASK operations
            ("TASK", "create"): "create_task",
            ("TASK", "update"): "update_task",
            ("TASK", "complete"): "complete_task",
            ("TASK", "delete"): "delete_task",
            ("TASK", "list"): "list_tasks",
            
            # CONTACTS operations
            ("CONTACTS", "search"): "search_contacts",
            ("CONTACTS", "get"): "get_contact",
            ("CONTACTS", "add"): "add_contact",
            ("CONTACTS", "list"): "list_contacts",
            
            # CHAT operations
            ("CHAT", "send"): "send_message",
            ("CHAT", "read"): "read_messages",
            ("CHAT", "search"): "search_messages",
            ("CHAT", "list_channels"): "list_channels",
            
            # DEVTOOLS operations
            ("DEVTOOLS", "create_issue"): "create_issue",
            ("DEVTOOLS", "list_issues"): "list_issues",
            ("DEVTOOLS", "create_pr"): "create_pull_request",
            ("DEVTOOLS", "list_prs"): "list_pull_requests",
        }
    
    def get_connector_method(
        self, 
        primitive: str, 
        operation: str,
    ) -> str:
        """Get the connector method name for a primitive operation."""
        key = (primitive.upper(), operation.lower())
        
        if key in self._method_map:
            return self._method_map[key]
        
        # Fall back to operation name directly
        # (e.g., "send" -> "send")
        return operation.lower()
    
    def get_available_providers(
        self, 
        primitive: str,
        connected_only: bool = True,
    ) -> List[str]:
        """
        Get available providers for a primitive.
        
        Args:
            primitive: Primitive name (EMAIL, CALENDAR, etc.)
            connected_only: If True, only return connected providers
        
        Returns:
            List of connector names
        """
        connectors = self._registry.get_providers_for_primitive(primitive.upper())
        
        if not connected_only:
            return connectors
        
        # Filter to only connected
        connected = []
        for conn_name in connectors:
            metadata = self._registry.get_metadata(conn_name)
            if metadata and self._credential_store.has_valid(metadata.provider):
                connected.append(conn_name)
        
        return connected
    
    def get_preferred_provider(self, primitive: str) -> Optional[str]:
        """Get the user's preferred provider for a primitive."""
        return self._registry.get_preferred_connector(primitive.upper())
    
    def needs_provider_selection(self, primitive: str) -> Tuple[bool, List[str]]:
        """
        Check if we need user input to select a provider.
        
        Returns:
            (needs_selection, available_providers)
        """
        available = self.get_available_providers(primitive, connected_only=True)
        
        if len(available) == 0:
            # No providers connected - need setup
            all_providers = self.get_available_providers(primitive, connected_only=False)
            return (True, all_providers)
        
        if len(available) == 1:
            # Only one option - no selection needed
            return (False, available)
        
        # Multiple providers - check if preference is set
        preferred = self.get_preferred_provider(primitive)
        if preferred and preferred in available:
            return (False, available)
        
        # No preference for multiple providers - need selection
        return (True, available)
    
    async def _get_connector_instance(
        self, 
        connector_name: str,
    ) -> Optional[BaseConnector]:
        """Get or create a connector instance."""
        if connector_name in self._connector_cache:
            return self._connector_cache[connector_name]
        
        metadata = self._registry.get_metadata(connector_name)
        if not metadata:
            return None
        
        try:
            # Create instance
            instance = metadata.connector_class()
            
            # Connect with stored credentials
            creds = self._credential_store.get(metadata.provider)
            if creds:
                await instance.connect(creds)
            
            self._connector_cache[connector_name] = instance
            return instance
            
        except Exception as e:
            logger.error(f"Failed to instantiate connector {connector_name}: {e}")
            return None
    
    async def _execute_on_connector(
        self,
        connector_name: str,
        primitive: str,
        operation: str,
        params: Dict[str, Any],
    ) -> ProviderResult:
        """Execute operation on a single connector."""
        import time
        start = time.time()
        
        metadata = self._registry.get_metadata(connector_name)
        if not metadata:
            return ProviderResult(
                provider="unknown",
                connector=connector_name,
                success=False,
                error=f"Unknown connector: {connector_name}",
            )
        
        try:
            # Get connector instance
            instance = await self._get_connector_instance(connector_name)
            if not instance:
                return ProviderResult(
                    provider=metadata.provider,
                    connector=connector_name,
                    success=False,
                    error="Failed to get connector instance",
                )
            
            # Get method
            method_name = self.get_connector_method(primitive, operation)
            
            if not hasattr(instance, method_name):
                # Try direct operation name
                if hasattr(instance, operation):
                    method_name = operation
                else:
                    return ProviderResult(
                        provider=metadata.provider,
                        connector=connector_name,
                        success=False,
                        error=f"Connector doesn't support operation: {operation}",
                    )
            
            method = getattr(instance, method_name)
            
            # Execute
            if asyncio.iscoroutinefunction(method):
                result = await method(**params)
            else:
                result = method(**params)
            
            latency = (time.time() - start) * 1000
            
            return ProviderResult(
                provider=metadata.provider,
                connector=connector_name,
                success=True,
                data=result,
                latency_ms=latency,
            )
            
        except Exception as e:
            latency = (time.time() - start) * 1000
            logger.error(f"Error executing {operation} on {connector_name}: {e}")
            
            return ProviderResult(
                provider=metadata.provider,
                connector=connector_name,
                success=False,
                error=str(e),
                latency_ms=latency,
            )
    
    def _aggregate_results(
        self,
        results: List[ProviderResult],
        strategy: AggregationStrategy,
    ) -> Any:
        """Aggregate results from multiple providers."""
        successful = [r for r in results if r.success]
        
        if not successful:
            return None
        
        if strategy == AggregationStrategy.FIRST_SUCCESS:
            return successful[0].data
        
        elif strategy == AggregationStrategy.COLLECT_ALL:
            return {r.connector: r.data for r in successful}
        
        elif strategy == AggregationStrategy.COUNT:
            total = 0
            for r in successful:
                if isinstance(r.data, (int, float)):
                    total += r.data
                elif isinstance(r.data, dict) and "count" in r.data:
                    total += r.data["count"]
                elif isinstance(r.data, list):
                    total += len(r.data)
            return {"count": total, "by_provider": {r.connector: r.data for r in successful}}
        
        elif strategy == AggregationStrategy.MERGE_LISTS:
            # Merge list results
            merged = []
            for r in successful:
                if isinstance(r.data, list):
                    # Tag each item with source
                    for item in r.data:
                        if isinstance(item, dict):
                            item["_source"] = r.connector
                        merged.append(item)
                elif r.data is not None:
                    merged.append({"_source": r.connector, "data": r.data})
            
            # Sort by date if possible
            def get_date_key(item):
                if isinstance(item, dict):
                    for key in ["date", "datetime", "created_at", "timestamp", "received_at"]:
                        if key in item:
                            return item[key]
                return ""
            
            try:
                merged.sort(key=get_date_key, reverse=True)
            except:
                pass
            
            return merged
        
        return successful[0].data
    
    async def execute(
        self,
        primitive: str,
        operation: str,
        params: Dict[str, Any],
        mode: Optional[ExecutionMode] = None,
        aggregation: Optional[AggregationStrategy] = None,
        connectors: Optional[List[str]] = None,
    ) -> ResolverResult:
        """
        Execute a primitive operation.
        
        Args:
            primitive: Primitive name (EMAIL, CALENDAR, etc.)
            operation: Operation name (send, search, list, etc.)
            params: Operation parameters
            mode: Execution mode (single, all, fallback)
            aggregation: How to aggregate multi-provider results
            connectors: Specific connectors to use (overrides mode)
        
        Returns:
            ResolverResult with aggregated data from all executed providers
        """
        import time
        start = time.time()
        
        primitive = primitive.upper()
        
        # Determine execution mode
        if mode is None:
            mode = get_default_mode(operation)
        
        if aggregation is None:
            aggregation = get_default_aggregation(operation)
        
        # Get connectors to execute on
        if connectors:
            target_connectors = connectors
        elif mode == ExecutionMode.SINGLE:
            preferred = self.get_preferred_provider(primitive)
            if preferred:
                target_connectors = [preferred]
            else:
                available = self.get_available_providers(primitive)
                target_connectors = available[:1] if available else []
        else:
            target_connectors = self.get_available_providers(primitive)
        
        if not target_connectors:
            return ResolverResult(
                success=False,
                primitive=primitive,
                operation=operation,
                providers_used=[],
                error=f"No connectors available for {primitive}",
                execution_mode=mode.value,
            )
        
        # Execute based on mode
        results: List[ProviderResult] = []
        
        if mode in [ExecutionMode.ALL, ExecutionMode.PARALLEL]:
            # Execute all in parallel
            tasks = [
                self._execute_on_connector(conn, primitive, operation, params)
                for conn in target_connectors
            ]
            results = await asyncio.gather(*tasks)
        
        elif mode == ExecutionMode.FASTEST:
            # Race all connectors, return first success
            tasks = [
                self._execute_on_connector(conn, primitive, operation, params)
                for conn in target_connectors
            ]
            
            done, pending = await asyncio.wait(
                [asyncio.create_task(t) for t in tasks],
                return_when=asyncio.FIRST_COMPLETED,
            )
            
            # Get first completed
            for task in done:
                result = task.result()
                if result.success:
                    results = [result]
                    break
            
            # Cancel pending
            for task in pending:
                task.cancel()
            
            if not results:
                # All failed, get all results
                results = [task.result() for task in done]
        
        elif mode == ExecutionMode.FALLBACK:
            # Try connectors in order until one succeeds
            for conn in target_connectors:
                result = await self._execute_on_connector(conn, primitive, operation, params)
                results.append(result)
                if result.success:
                    break
        
        else:  # SINGLE
            if target_connectors:
                result = await self._execute_on_connector(
                    target_connectors[0], primitive, operation, params
                )
                results = [result]
        
        # Aggregate results
        successful = [r for r in results if r.success]
        failed = [r for r in results if not r.success]
        
        if not successful:
            # All failed
            error = "; ".join(f"{r.connector}: {r.error}" for r in failed)
            return ResolverResult(
                success=False,
                primitive=primitive,
                operation=operation,
                providers_used=[r.connector for r in results],
                error=error,
                provider_results=results,
                execution_mode=mode.value,
                total_latency_ms=(time.time() - start) * 1000,
            )
        
        # Aggregate successful results
        data = self._aggregate_results(results, aggregation)
        
        return ResolverResult(
            success=True,
            primitive=primitive,
            operation=operation,
            providers_used=[r.connector for r in successful],
            data=data,
            provider_results=results,
            execution_mode=mode.value,
            total_latency_ms=(time.time() - start) * 1000,
        )
    
    async def execute_single(
        self,
        primitive: str,
        operation: str,
        params: Dict[str, Any],
        connector: Optional[str] = None,
    ) -> ResolverResult:
        """
        Execute on a single provider (convenience method).
        
        Args:
            primitive: Primitive name
            operation: Operation name
            params: Operation parameters
            connector: Specific connector (uses preferred if not specified)
        """
        connectors = [connector] if connector else None
        return await self.execute(
            primitive=primitive,
            operation=operation,
            params=params,
            mode=ExecutionMode.SINGLE,
            connectors=connectors,
        )
    
    async def execute_all(
        self,
        primitive: str,
        operation: str,
        params: Dict[str, Any],
        merge: bool = True,
    ) -> ResolverResult:
        """
        Execute on all connected providers and aggregate results.
        
        Args:
            primitive: Primitive name
            operation: Operation name
            params: Operation parameters
            merge: If True, merge results; if False, return dict by provider
        """
        aggregation = (
            AggregationStrategy.MERGE_LISTS if merge 
            else AggregationStrategy.COLLECT_ALL
        )
        return await self.execute(
            primitive=primitive,
            operation=operation,
            params=params,
            mode=ExecutionMode.ALL,
            aggregation=aggregation,
        )
    
    def get_execution_preview(
        self,
        primitive: str,
        operation: str,
        mode: Optional[ExecutionMode] = None,
    ) -> Dict[str, Any]:
        """
        Get a preview of how an operation would be executed.
        
        Useful for showing user what will happen before execution.
        
        Returns:
            Dict with execution plan details
        """
        if mode is None:
            mode = get_default_mode(operation)
        
        primitive = primitive.upper()
        connected = self.get_available_providers(primitive, connected_only=True)
        all_providers = self.get_available_providers(primitive, connected_only=False)
        preferred = self.get_preferred_provider(primitive)
        
        if mode == ExecutionMode.SINGLE:
            will_use = [preferred] if preferred else connected[:1]
        else:
            will_use = connected
        
        return {
            "primitive": primitive,
            "operation": operation,
            "mode": mode.value,
            "will_execute_on": will_use,
            "available_providers": connected,
            "disconnected_providers": [p for p in all_providers if p not in connected],
            "preferred_provider": preferred,
            "needs_selection": len(connected) > 1 and not preferred and mode == ExecutionMode.SINGLE,
        }


# ============================================================================
# SINGLETON ACCESS
# ============================================================================

_resolver: Optional[PrimitiveResolver] = None


def get_resolver() -> PrimitiveResolver:
    """Get singleton PrimitiveResolver instance."""
    global _resolver
    if _resolver is None:
        _resolver = PrimitiveResolver()
    return _resolver


def reset_resolver():
    """Reset the singleton (for testing)."""
    global _resolver
    _resolver = None
