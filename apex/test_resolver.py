"""
Primitive Resolver Tests

Tests for the multi-provider primitive resolver including:
- Provider resolution
- Execution modes (single, all, fallback, fastest)
- Result aggregation strategies
- Method mapping
- Preference handling
"""

import asyncio
import sys
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))

from connectors.resolver import (
    PrimitiveResolver,
    ExecutionMode,
    AggregationStrategy,
    ProviderResult,
    ResolverResult,
    get_resolver,
    reset_resolver,
    get_default_mode,
    get_default_aggregation,
    AGGREGATABLE_OPERATIONS,
    SINGLE_PROVIDER_OPERATIONS,
)
from connectors.registry import (
    ConnectorRegistry,
    ConnectorMetadata,
    ConnectionStatus,
    ConnectorHealth,
    BaseConnector,
    reset_registry,
)
from connectors.credentials import (
    CredentialStore,
    MemoryBackend,
    CredentialType,
    StoredCredential,
    reset_credential_store,
)


# ============================================================================
# MOCK CONNECTOR
# ============================================================================

class MockConnector(BaseConnector):
    """Mock connector for testing."""
    
    def __init__(self, name: str = "mock", provider: str = "mock_provider"):
        self._name = name
        self._provider = provider
        self._connected = False
        self._data = {}
    
    @property
    def name(self) -> str:
        return self._name
    
    @property
    def provider(self) -> str:
        return self._provider
    
    @property
    def is_connected(self) -> bool:
        return self._connected
    
    async def connect(self, credentials=None) -> bool:
        self._connected = True
        return True
    
    async def disconnect(self) -> bool:
        self._connected = False
        return True
    
    async def check_health(self) -> ConnectorHealth:
        return ConnectorHealth(
            status=ConnectionStatus.CONNECTED if self._connected else ConnectionStatus.DISCONNECTED,
            last_check=datetime.utcnow(),
        )
    
    # Mock email operations
    async def send_email(self, **params) -> Dict:
        return {"sent": True, "to": params.get("to"), "provider": self._name}
    
    async def search_messages(self, **params) -> List[Dict]:
        query = params.get("query", "")
        return [
            {"id": f"{self._name}_1", "subject": f"Result 1 for {query}", "provider": self._name},
            {"id": f"{self._name}_2", "subject": f"Result 2 for {query}", "provider": self._name},
        ]
    
    async def list_messages(self, **params) -> List[Dict]:
        return [
            {"id": f"{self._name}_msg_1", "subject": "Message 1", "provider": self._name},
            {"id": f"{self._name}_msg_2", "subject": "Message 2", "provider": self._name},
        ]
    
    # Mock calendar operations
    async def create_event(self, **params) -> Dict:
        return {"created": True, "title": params.get("title"), "provider": self._name}
    
    async def list_events(self, **params) -> List[Dict]:
        return [
            {"id": f"{self._name}_evt_1", "title": "Event 1", "provider": self._name},
        ]


# ============================================================================
# TEST: DEFAULT MODE SELECTION
# ============================================================================

class TestDefaultModes(unittest.TestCase):
    """Test default execution mode selection."""
    
    def test_send_operations_are_single(self):
        """Send operations should default to SINGLE mode."""
        for op in ["send", "create", "update", "delete", "write"]:
            mode = get_default_mode(op)
            self.assertEqual(mode, ExecutionMode.SINGLE, f"{op} should be SINGLE mode")
    
    def test_search_operations_are_all(self):
        """Search operations should default to ALL mode."""
        for op in ["search", "list", "read", "get", "find"]:
            mode = get_default_mode(op)
            self.assertEqual(mode, ExecutionMode.ALL, f"{op} should be ALL mode")
    
    def test_aggregation_for_search_is_merge(self):
        """Search operations should merge lists."""
        for op in ["search", "list", "find"]:
            strategy = get_default_aggregation(op)
            self.assertEqual(strategy, AggregationStrategy.MERGE_LISTS)
    
    def test_aggregation_for_count_is_count(self):
        """Count operations should sum results."""
        for op in ["count", "get_count"]:
            strategy = get_default_aggregation(op)
            self.assertEqual(strategy, AggregationStrategy.COUNT)


# ============================================================================
# TEST: METHOD MAPPING
# ============================================================================

class TestMethodMapping(unittest.TestCase):
    """Test primitive-to-connector method mapping."""
    
    def setUp(self):
        reset_resolver()
        reset_registry()
        reset_credential_store()
        
        self.store = CredentialStore(backend=MemoryBackend())
        self.registry = ConnectorRegistry(credential_store=self.store)
        self.resolver = PrimitiveResolver(
            registry=self.registry,
            credential_store=self.store,
        )
    
    def test_email_send_maps_correctly(self):
        """EMAIL.send should map to send_email."""
        method = self.resolver.get_connector_method("EMAIL", "send")
        self.assertEqual(method, "send_email")
    
    def test_email_search_maps_correctly(self):
        """EMAIL.search should map to search_messages."""
        method = self.resolver.get_connector_method("EMAIL", "search")
        self.assertEqual(method, "search_messages")
    
    def test_calendar_create_maps_correctly(self):
        """CALENDAR.create should map to create_event."""
        method = self.resolver.get_connector_method("CALENDAR", "create")
        self.assertEqual(method, "create_event")
    
    def test_unmapped_operation_uses_operation_name(self):
        """Unmapped operations should use the operation name directly."""
        method = self.resolver.get_connector_method("CUSTOM", "custom_operation")
        self.assertEqual(method, "custom_operation")
    
    def test_case_insensitive_primitive(self):
        """Primitive names should be case-insensitive."""
        method1 = self.resolver.get_connector_method("email", "send")
        method2 = self.resolver.get_connector_method("EMAIL", "send")
        method3 = self.resolver.get_connector_method("Email", "send")
        
        self.assertEqual(method1, method2)
        self.assertEqual(method2, method3)


# ============================================================================
# TEST: PROVIDER RESOLUTION
# ============================================================================

class TestProviderResolution(unittest.TestCase):
    """Test provider resolution for primitives."""
    
    def setUp(self):
        reset_resolver()
        reset_registry()
        reset_credential_store()
        
        self.store = CredentialStore(backend=MemoryBackend())
        self.registry = ConnectorRegistry(credential_store=self.store)
        self.resolver = PrimitiveResolver(
            registry=self.registry,
            credential_store=self.store,
        )
    
    def test_email_has_multiple_providers(self):
        """EMAIL should have multiple providers (Gmail, Outlook)."""
        providers = self.resolver.get_available_providers("EMAIL", connected_only=False)
        self.assertIn("gmail", providers)
        self.assertIn("outlook", providers)
        self.assertGreaterEqual(len(providers), 2)
    
    def test_calendar_has_multiple_providers(self):
        """CALENDAR should have multiple providers."""
        providers = self.resolver.get_available_providers("CALENDAR", connected_only=False)
        self.assertIn("google_calendar", providers)
        self.assertIn("outlook_calendar", providers)
    
    def test_connected_only_filters_correctly(self):
        """connected_only=True should only return connected providers."""
        # No credentials stored, so nothing should be connected
        connected = self.resolver.get_available_providers("EMAIL", connected_only=True)
        self.assertEqual(len(connected), 0)
        
        # Store Google credentials
        self.store.save_token(
            provider="google",
            access_token="test-token",
            expires_in=3600,
        )
        
        # Now Gmail should be available
        connected = self.resolver.get_available_providers("EMAIL", connected_only=True)
        self.assertIn("gmail", connected)
    
    def test_needs_selection_with_multiple_providers(self):
        """Should report multiple providers when both connected."""
        # Connect both Google and Microsoft
        self.store.save_token(provider="google", access_token="token1", expires_in=3600)
        self.store.save_token(provider="microsoft", access_token="token2", expires_in=3600)
        
        needs_selection, providers = self.resolver.needs_provider_selection("EMAIL")
        
        # Both connected - registry will use first as default preference
        # So needs_selection may be False (falls back to first)
        # But providers should have both
        self.assertGreaterEqual(len(providers), 2)
    
    def test_no_selection_needed_with_preference(self):
        """Should not need selection when preference is set."""
        # Connect both
        self.store.save_token(provider="google", access_token="token1", expires_in=3600)
        self.store.save_token(provider="microsoft", access_token="token2", expires_in=3600)
        
        # Set preference
        self.registry.set_preferred_connector("EMAIL", "gmail")
        
        needs_selection, _ = self.resolver.needs_provider_selection("EMAIL")
        self.assertFalse(needs_selection)


# ============================================================================
# TEST: RESULT CLASSES
# ============================================================================

class TestResultClasses(unittest.TestCase):
    """Test result dataclasses."""
    
    def test_provider_result_serialization(self):
        """ProviderResult should serialize to dict."""
        result = ProviderResult(
            provider="google",
            connector="gmail",
            success=True,
            data={"count": 5},
            latency_ms=150.5,
        )
        
        d = result.to_dict()
        
        self.assertEqual(d["provider"], "google")
        self.assertEqual(d["connector"], "gmail")
        self.assertTrue(d["success"])
        self.assertEqual(d["data"], {"count": 5})
        self.assertEqual(d["latency_ms"], 150.5)
    
    def test_resolver_result_serialization(self):
        """ResolverResult should serialize to dict."""
        provider_result = ProviderResult(
            provider="google",
            connector="gmail",
            success=True,
            data=[{"id": "1"}],
        )
        
        result = ResolverResult(
            success=True,
            primitive="EMAIL",
            operation="search",
            providers_used=["gmail"],
            data=[{"id": "1"}],
            provider_results=[provider_result],
            execution_mode="all",
        )
        
        d = result.to_dict()
        
        self.assertTrue(d["success"])
        self.assertEqual(d["primitive"], "EMAIL")
        self.assertEqual(d["operation"], "search")
        self.assertEqual(d["providers_used"], ["gmail"])
        self.assertEqual(len(d["provider_results"]), 1)


# ============================================================================
# TEST: AGGREGATION STRATEGIES
# ============================================================================

class TestAggregation(unittest.TestCase):
    """Test result aggregation strategies."""
    
    def setUp(self):
        reset_resolver()
        reset_registry()
        reset_credential_store()
        
        self.store = CredentialStore(backend=MemoryBackend())
        self.registry = ConnectorRegistry(credential_store=self.store)
        self.resolver = PrimitiveResolver(
            registry=self.registry,
            credential_store=self.store,
        )
    
    def test_merge_lists_combines_results(self):
        """MERGE_LISTS should combine list results."""
        results = [
            ProviderResult("google", "gmail", True, [{"id": "g1"}, {"id": "g2"}]),
            ProviderResult("microsoft", "outlook", True, [{"id": "m1"}]),
        ]
        
        merged = self.resolver._aggregate_results(results, AggregationStrategy.MERGE_LISTS)
        
        self.assertEqual(len(merged), 3)
        # Check source tagging
        sources = {item.get("_source") for item in merged}
        self.assertIn("gmail", sources)
        self.assertIn("outlook", sources)
    
    def test_first_success_returns_first(self):
        """FIRST_SUCCESS should return first successful result."""
        results = [
            ProviderResult("google", "gmail", True, {"first": True}),
            ProviderResult("microsoft", "outlook", True, {"second": True}),
        ]
        
        data = self.resolver._aggregate_results(results, AggregationStrategy.FIRST_SUCCESS)
        self.assertEqual(data, {"first": True})
    
    def test_collect_all_returns_dict(self):
        """COLLECT_ALL should return dict by provider."""
        results = [
            ProviderResult("google", "gmail", True, [{"id": "g1"}]),
            ProviderResult("microsoft", "outlook", True, [{"id": "m1"}]),
        ]
        
        data = self.resolver._aggregate_results(results, AggregationStrategy.COLLECT_ALL)
        
        self.assertIn("gmail", data)
        self.assertIn("outlook", data)
        self.assertEqual(data["gmail"], [{"id": "g1"}])
    
    def test_count_sums_results(self):
        """COUNT should sum numeric results."""
        results = [
            ProviderResult("google", "gmail", True, 10),
            ProviderResult("microsoft", "outlook", True, 5),
        ]
        
        data = self.resolver._aggregate_results(results, AggregationStrategy.COUNT)
        
        self.assertEqual(data["count"], 15)
        self.assertIn("by_provider", data)


# ============================================================================
# TEST: EXECUTION PREVIEW
# ============================================================================

class TestExecutionPreview(unittest.TestCase):
    """Test execution preview functionality."""
    
    def setUp(self):
        reset_resolver()
        reset_registry()
        reset_credential_store()
        
        self.store = CredentialStore(backend=MemoryBackend())
        self.registry = ConnectorRegistry(credential_store=self.store)
        self.resolver = PrimitiveResolver(
            registry=self.registry,
            credential_store=self.store,
        )
    
    def test_preview_shows_mode(self):
        """Preview should show execution mode."""
        preview = self.resolver.get_execution_preview("EMAIL", "search")
        
        self.assertEqual(preview["primitive"], "EMAIL")
        self.assertEqual(preview["operation"], "search")
        self.assertEqual(preview["mode"], "all")  # search defaults to ALL
    
    def test_preview_shows_available_providers(self):
        """Preview should show available providers."""
        preview = self.resolver.get_execution_preview("EMAIL", "send")
        
        self.assertIn("available_providers", preview)
        self.assertIn("disconnected_providers", preview)
    
    def test_preview_with_explicit_mode(self):
        """Preview should use explicit mode when provided."""
        preview = self.resolver.get_execution_preview(
            "EMAIL", "search", ExecutionMode.SINGLE
        )
        
        self.assertEqual(preview["mode"], "single")


# ============================================================================
# TEST: SINGLETON PATTERN
# ============================================================================

class TestSingleton(unittest.TestCase):
    """Test singleton pattern for PrimitiveResolver."""
    
    def setUp(self):
        reset_resolver()
    
    def tearDown(self):
        reset_resolver()
    
    def test_singleton_returns_same_instance(self):
        """get_resolver should return same instance."""
        r1 = get_resolver()
        r2 = get_resolver()
        self.assertIs(r1, r2)
    
    def test_reset_creates_new_instance(self):
        """reset_resolver should allow new instance."""
        r1 = get_resolver()
        reset_resolver()
        r2 = get_resolver()
        self.assertIsNot(r1, r2)


# ============================================================================
# TEST: ASYNC EXECUTION
# ============================================================================

class TestAsyncExecution(unittest.TestCase):
    """Test async execution functionality."""
    
    def setUp(self):
        reset_resolver()
        reset_registry()
        reset_credential_store()
        
        self.store = CredentialStore(backend=MemoryBackend())
        self.registry = ConnectorRegistry(credential_store=self.store)
        self.resolver = PrimitiveResolver(
            registry=self.registry,
            credential_store=self.store,
        )
    
    def test_execute_returns_error_when_no_providers(self):
        """Execute should return error when no providers available."""
        async def run():
            result = await self.resolver.execute(
                primitive="EMAIL",
                operation="search",
                params={"query": "test"},
            )
            
            self.assertFalse(result.success)
            self.assertIn("No connectors available", result.error)
        
        asyncio.run(run())
    
    def test_execute_single_mode(self):
        """Execute with SINGLE mode should use one provider."""
        # This is a structural test - actual execution requires real connectors
        async def run():
            # With no connected providers, should fail gracefully
            result = await self.resolver.execute(
                primitive="EMAIL",
                operation="send",
                params={"to": "test@example.com"},
                mode=ExecutionMode.SINGLE,
            )
            
            self.assertFalse(result.success)
            self.assertEqual(result.execution_mode, "single")
        
        asyncio.run(run())
    
    def test_execute_all_mode(self):
        """Execute with ALL mode should try all providers."""
        async def run():
            result = await self.resolver.execute(
                primitive="EMAIL",
                operation="search",
                params={"query": "test"},
                mode=ExecutionMode.ALL,
            )
            
            # No providers connected, so should fail
            self.assertFalse(result.success)
            self.assertEqual(result.execution_mode, "all")
        
        asyncio.run(run())


# ============================================================================
# RUN TESTS
# ============================================================================

def run_tests():
    """Run all resolver tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestDefaultModes))
    suite.addTests(loader.loadTestsFromTestCase(TestMethodMapping))
    suite.addTests(loader.loadTestsFromTestCase(TestProviderResolution))
    suite.addTests(loader.loadTestsFromTestCase(TestResultClasses))
    suite.addTests(loader.loadTestsFromTestCase(TestAggregation))
    suite.addTests(loader.loadTestsFromTestCase(TestExecutionPreview))
    suite.addTests(loader.loadTestsFromTestCase(TestSingleton))
    suite.addTests(loader.loadTestsFromTestCase(TestAsyncExecution))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Summary
    print("\n" + "="*60)
    print("PRIMITIVE RESOLVER TEST SUMMARY")
    print("="*60)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Success: {result.wasSuccessful()}")
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
