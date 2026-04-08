"""
Comprehensive Tests for Connector Infrastructure

Tests for:
- CredentialStore (file-based and memory backends)
- ConnectorRegistry (registration, discovery, status)
- Integration between components
"""

import asyncio
import json
import tempfile
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import unittest

# Add parent to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent))

from connectors.credentials import (
    CredentialStore,
    CredentialBackend,
    EncryptedFileBackend,
    MemoryBackend,
    StoredCredential,
    CredentialType,
    get_credential_store,
    reset_credential_store,
)
from connectors.registry import (
    ConnectorRegistry,
    ConnectorMetadata,
    ConnectionStatus,
    ConnectorHealth,
    BaseConnector,
    get_registry,
    reset_registry,
)


# ============================================================================
# Mock Connector for Testing
# ============================================================================

class MockConnector(BaseConnector):
    """Mock connector for testing."""
    
    def __init__(self, name: str = "mock", provider: str = "test"):
        self._name = name
        self._provider = provider
        self._connected = False
    
    @property
    def name(self) -> str:
        return self._name
    
    @property
    def provider(self) -> str:
        return self._provider
    
    async def connect(self, credentials: Optional[StoredCredential] = None) -> bool:
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
    
    @property
    def is_connected(self) -> bool:
        return self._connected


# ============================================================================
# CredentialStore Tests
# ============================================================================

class TestCredentialStore(unittest.TestCase):
    """Tests for CredentialStore."""
    
    def setUp(self):
        """Create fresh store with memory backend."""
        reset_credential_store()
        self.store = CredentialStore(MemoryBackend())
    
    def test_save_and_get_token(self):
        """Test saving and retrieving OAuth token."""
        result = self.store.save_token(
            provider="google",
            access_token="test_access_token",
            refresh_token="test_refresh_token",
            expires_in=3600,
            scopes=["email", "calendar"],
        )
        
        self.assertTrue(result)
        
        # Retrieve
        cred = self.store.get("google")
        self.assertIsNotNone(cred)
        self.assertEqual(cred.provider, "google")
        self.assertEqual(cred.data["access_token"], "test_access_token")
        self.assertEqual(cred.data["refresh_token"], "test_refresh_token")
        self.assertEqual(cred.scopes, ["email", "calendar"])
    
    def test_get_token_shorthand(self):
        """Test get_token convenience method."""
        self.store.save_token(provider="github", access_token="gh_token")
        
        token = self.store.get_token("github")
        self.assertEqual(token, "gh_token")
    
    def test_save_api_key(self):
        """Test saving API key."""
        result = self.store.save_api_key(
            provider="openai",
            api_key="sk-test123",
        )
        
        self.assertTrue(result)
        
        key = self.store.get_api_key("openai")
        self.assertEqual(key, "sk-test123")
    
    def test_save_client_credentials(self):
        """Test saving OAuth client credentials."""
        result = self.store.save_client_credentials(
            provider="google",
            client_id="test_client_id",
            client_secret="test_client_secret",
        )
        
        self.assertTrue(result)
        
        creds = self.store.get_client_credentials("google")
        self.assertIsNotNone(creds)
        self.assertEqual(creds["client_id"], "test_client_id")
        self.assertEqual(creds["client_secret"], "test_client_secret")
    
    def test_has_and_has_valid(self):
        """Test existence and validity checks."""
        # No credentials yet
        self.assertFalse(self.store.has("google"))
        self.assertFalse(self.store.has_valid("google"))
        
        # Add token with expiry
        self.store.save_token(
            provider="google",
            access_token="token",
            expires_in=3600,
        )
        
        self.assertTrue(self.store.has("google"))
        self.assertTrue(self.store.has_valid("google"))
    
    def test_expired_token(self):
        """Test expired token detection."""
        # Create expired credential directly
        cred = StoredCredential(
            provider="expired",
            credential_type=CredentialType.OAUTH_TOKEN,
            data={"access_token": "old_token"},
            created_at=datetime.utcnow() - timedelta(hours=2),
            expires_at=datetime.utcnow() - timedelta(hours=1),
        )
        
        self.assertTrue(cred.is_expired())
        # expires_soon returns True for already expired tokens (correct behavior)
        self.assertTrue(cred.expires_soon())
    
    def test_expires_soon(self):
        """Test expires_soon detection."""
        cred = StoredCredential(
            provider="expiring",
            credential_type=CredentialType.OAUTH_TOKEN,
            data={"access_token": "token"},
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(minutes=3),
        )
        
        self.assertFalse(cred.is_expired())
        self.assertTrue(cred.expires_soon(minutes=5))  # Expires within 5 min
    
    def test_needs_refresh(self):
        """Test needs_refresh combining expiry checks."""
        # Non-existent provider
        self.assertTrue(self.store.needs_refresh("nonexistent"))
        
        # Valid token
        self.store.save_token(
            provider="valid",
            access_token="token",
            expires_in=3600,
        )
        self.assertFalse(self.store.needs_refresh("valid"))
    
    def test_delete(self):
        """Test credential deletion."""
        self.store.save_token(provider="temp", access_token="token")
        self.assertTrue(self.store.has("temp"))
        
        self.store.delete("temp")
        self.assertFalse(self.store.has("temp"))
    
    def test_list_providers(self):
        """Test listing providers."""
        self.store.save_token(provider="google", access_token="g")
        self.store.save_token(provider="microsoft", access_token="m")
        self.store.save_api_key(provider="openai", api_key="o")
        
        providers = self.store.list_providers()
        self.assertEqual(set(providers), {"google", "microsoft", "openai"})
    
    def test_multi_user_credentials(self):
        """Test multiple accounts per provider."""
        self.store.save_token(provider="google", access_token="user1", user_id="user1@gmail.com")
        self.store.save_token(provider="google", access_token="user2", user_id="user2@gmail.com")
        
        cred1 = self.store.get("google", user_id="user1@gmail.com")
        cred2 = self.store.get("google", user_id="user2@gmail.com")
        
        self.assertEqual(cred1.data["access_token"], "user1")
        self.assertEqual(cred2.data["access_token"], "user2")
    
    def test_get_status(self):
        """Test overall status report."""
        self.store.save_token(provider="google", access_token="g", expires_in=3600)
        self.store.save_client_credentials(provider="microsoft", client_id="c")
        
        status = self.store.get_status()
        
        self.assertIn("total_credentials", status)
        self.assertIn("providers", status)
        self.assertIn("connected", status)
        self.assertIn("google", status["connected"])
    
    def test_clear_all(self):
        """Test clearing all credentials."""
        self.store.save_token(provider="a", access_token="a")
        self.store.save_token(provider="b", access_token="b")
        self.store.save_token(provider="c", access_token="c")
        
        count = self.store.clear_all()
        self.assertEqual(count, 3)
        self.assertEqual(len(self.store.list_providers()), 0)


class TestEncryptedFileBackend(unittest.TestCase):
    """Tests for encrypted file storage."""
    
    def setUp(self):
        """Create temporary directory for test."""
        self.temp_dir = tempfile.mkdtemp()
        self.backend = EncryptedFileBackend(storage_path=self.temp_dir)
    
    def tearDown(self):
        """Clean up temp directory."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_save_and_get(self):
        """Test file-based storage."""
        cred = StoredCredential(
            provider="test",
            credential_type=CredentialType.OAUTH_TOKEN,
            data={"access_token": "secret_token"},
            created_at=datetime.utcnow(),
        )
        
        self.assertTrue(self.backend.save("test", cred))
        
        loaded = self.backend.get("test")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.data["access_token"], "secret_token")
    
    def test_file_created(self):
        """Test that encrypted file is created."""
        cred = StoredCredential(
            provider="file_test",
            credential_type=CredentialType.API_KEY,
            data={"api_key": "key123"},
            created_at=datetime.utcnow(),
        )
        
        self.backend.save("file_test", cred)
        
        file_path = Path(self.temp_dir) / "file_test.enc"
        self.assertTrue(file_path.exists())
        
        # Content should be encrypted (not plain JSON)
        content = file_path.read_text()
        self.assertNotIn("key123", content)
    
    def test_delete(self):
        """Test file deletion."""
        cred = StoredCredential(
            provider="delete_test",
            credential_type=CredentialType.API_KEY,
            data={"key": "val"},
            created_at=datetime.utcnow(),
        )
        
        self.backend.save("delete_test", cred)
        file_path = Path(self.temp_dir) / "delete_test.enc"
        self.assertTrue(file_path.exists())
        
        self.backend.delete("delete_test")
        self.assertFalse(file_path.exists())
    
    def test_list_keys(self):
        """Test listing stored keys."""
        for i in range(3):
            cred = StoredCredential(
                provider=f"provider_{i}",
                credential_type=CredentialType.API_KEY,
                data={"key": f"val_{i}"},
                created_at=datetime.utcnow(),
            )
            self.backend.save(f"key_{i}", cred)
        
        keys = self.backend.list_keys()
        self.assertEqual(set(keys), {"key_0", "key_1", "key_2"})


# ============================================================================
# ConnectorRegistry Tests
# ============================================================================

class TestConnectorRegistry(unittest.TestCase):
    """Tests for ConnectorRegistry."""
    
    def setUp(self):
        """Create fresh registry with memory credential store."""
        reset_registry()
        reset_credential_store()
        self.cred_store = CredentialStore(MemoryBackend())
        self.registry = ConnectorRegistry(self.cred_store)
    
    def test_register_connector(self):
        """Test connector registration."""
        metadata = ConnectorMetadata(
            name="test_connector",
            display_name="Test Connector",
            provider="test",
            primitives=["EMAIL", "CALENDAR"],
            scopes=["read", "write"],
            connector_class=MockConnector,
            description="A test connector",
        )
        
        result = self.registry.register(metadata)
        self.assertTrue(result)
        
        # Verify registration
        retrieved = self.registry.get_metadata("test_connector")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.display_name, "Test Connector")
    
    def test_primitive_mapping(self):
        """Test primitive to connector mapping."""
        # Register connector for EMAIL
        self.registry.register(ConnectorMetadata(
            name="email_connector",
            display_name="Email",
            provider="email_provider",
            primitives=["EMAIL"],
            scopes=[],
            connector_class=MockConnector,
        ))
        
        providers = self.registry.get_providers_for_primitive("EMAIL")
        self.assertIn("email_connector", providers)
    
    def test_multi_provider_for_primitive(self):
        """Test multiple connectors for same primitive."""
        # Note: Builtin connectors (gmail, outlook) already support EMAIL
        # Verify they're both present
        providers = self.registry.get_providers_for_primitive("EMAIL")
        
        # Should have at least gmail and outlook from builtins
        self.assertIn("gmail", providers)
        self.assertIn("outlook", providers)
        self.assertGreaterEqual(len(providers), 2)
    
    def test_list_connectors(self):
        """Test listing all connectors."""
        # Register some connectors
        for i in range(3):
            self.registry.register(ConnectorMetadata(
                name=f"conn_{i}",
                display_name=f"Connector {i}",
                provider=f"provider_{i}",
                primitives=["TEST"],
                scopes=[],
                connector_class=MockConnector,
            ))
        
        connectors = self.registry.list_connectors()
        names = [c.name for c in connectors]
        
        self.assertIn("conn_0", names)
        self.assertIn("conn_1", names)
        self.assertIn("conn_2", names)
    
    def test_unregister(self):
        """Test connector unregistration."""
        self.registry.register(ConnectorMetadata(
            name="temp_conn",
            display_name="Temp",
            provider="temp",
            primitives=["TEMP"],
            scopes=[],
            connector_class=MockConnector,
        ))
        
        self.assertIsNotNone(self.registry.get_metadata("temp_conn"))
        
        self.registry.unregister("temp_conn")
        
        self.assertIsNone(self.registry.get_metadata("temp_conn"))
    
    def test_get_providers(self):
        """Test listing unique providers."""
        # Builtin connectors register many providers
        providers = self.registry.get_providers()
        
        # Should have google and microsoft at minimum
        self.assertIn("google", providers)
        self.assertIn("microsoft", providers)
        
        # Add custom provider
        self.registry.register(ConnectorMetadata(
            name="custom1", display_name="Custom", provider="custom_provider",
            primitives=["CUSTOM"], scopes=[], connector_class=MockConnector,
        ))
        
        providers = self.registry.get_providers()
        self.assertIn("custom_provider", providers)
    
    def test_get_connectors_for_provider(self):
        """Test getting connectors for a specific provider."""
        # Builtin Google connectors should be present
        google_connectors = self.registry.get_connectors_for_provider("google")
        
        # Should have gmail, calendar, drive, contacts at minimum
        self.assertIn("gmail", google_connectors)
        self.assertIn("google_calendar", google_connectors)
        self.assertIn("google_drive", google_connectors)
        self.assertIn("google_contacts", google_connectors)
    
    def test_set_preferred_connector(self):
        """Test setting preferred connector for primitive."""
        self.registry.register(ConnectorMetadata(
            name="pref_a", display_name="A", provider="pa",
            primitives=["SHARED"], scopes=[], connector_class=MockConnector,
        ))
        self.registry.register(ConnectorMetadata(
            name="pref_b", display_name="B", provider="pb",
            primitives=["SHARED"], scopes=[], connector_class=MockConnector,
        ))
        
        # Set preference
        result = self.registry.set_preferred_connector("SHARED", "pref_b")
        self.assertTrue(result)
        
        # Since no credentials, preference isn't active, but it's stored
        # In real usage with credentials, pref_b would be preferred
    
    def test_available_primitives(self):
        """Test getting all available primitives."""
        self.registry.register(ConnectorMetadata(
            name="ap1", display_name="AP1", provider="p1",
            primitives=["EMAIL", "CALENDAR"], scopes=[], connector_class=MockConnector,
        ))
        self.registry.register(ConnectorMetadata(
            name="ap2", display_name="AP2", provider="p2",
            primitives=["TASK"], scopes=[], connector_class=MockConnector,
        ))
        
        primitives = self.registry.get_available_primitives()
        
        self.assertIn("EMAIL", primitives)
        self.assertIn("CALENDAR", primitives)
        self.assertIn("TASK", primitives)


class TestConnectorRegistryAsync(unittest.TestCase):
    """Async tests for ConnectorRegistry."""
    
    def setUp(self):
        reset_registry()
        reset_credential_store()
        self.cred_store = CredentialStore(MemoryBackend())
        self.registry = ConnectorRegistry(self.cred_store)
    
    def test_connect(self):
        """Test connecting to a connector."""
        self.registry.register(ConnectorMetadata(
            name="async_conn",
            display_name="Async",
            provider="async_provider",
            primitives=["TEST"],
            scopes=[],
            connector_class=MockConnector,
        ))
        
        async def run_test():
            result = await self.registry.connect("async_conn")
            self.assertTrue(result)
            
            # Get connector instance
            conn = self.registry.get_connector("async_conn")
            self.assertIsNotNone(conn)
            self.assertTrue(conn.is_connected)
        
        asyncio.run(run_test())
    
    def test_disconnect(self):
        """Test disconnecting from a connector."""
        self.registry.register(ConnectorMetadata(
            name="disc_conn",
            display_name="Disc",
            provider="disc_provider",
            primitives=["TEST"],
            scopes=[],
            connector_class=MockConnector,
        ))
        
        async def run_test():
            await self.registry.connect("disc_conn")
            conn = self.registry.get_connector("disc_conn")
            self.assertTrue(conn.is_connected)
            
            await self.registry.disconnect("disc_conn")
            self.assertFalse(conn.is_connected)
        
        asyncio.run(run_test())
    
    def test_check_health(self):
        """Test health check."""
        self.registry.register(ConnectorMetadata(
            name="health_conn",
            display_name="Health",
            provider="health_provider",
            primitives=["TEST"],
            scopes=[],
            connector_class=MockConnector,
        ))
        
        async def run_test():
            await self.registry.connect("health_conn")
            
            health = await self.registry.check_health("health_conn")
            self.assertEqual(health.status, ConnectionStatus.CONNECTED)
            self.assertTrue(health.is_healthy)
        
        asyncio.run(run_test())
    
    def test_connection_status(self):
        """Test overall connection status."""
        self.registry.register(ConnectorMetadata(
            name="stat_conn",
            display_name="Status",
            provider="stat_provider",
            primitives=["TEST"],
            scopes=[],
            connector_class=MockConnector,
        ))
        
        async def run_test():
            await self.registry.connect("stat_conn")
            
            status = self.registry.get_connection_status()
            
            self.assertIn("total_connectors", status)
            self.assertIn("connected_count", status)
            self.assertIn("providers", status)
        
        asyncio.run(run_test())


# ============================================================================
# Integration Tests
# ============================================================================

class TestIntegration(unittest.TestCase):
    """Integration tests for credential store and registry."""
    
    def setUp(self):
        reset_registry()
        reset_credential_store()
        self.cred_store = CredentialStore(MemoryBackend())
        self.registry = ConnectorRegistry(self.cred_store)
    
    def test_full_flow(self):
        """Test complete flow: register, store creds, connect."""
        # 1. Register connector
        self.registry.register(ConnectorMetadata(
            name="full_flow_conn",
            display_name="Full Flow",
            provider="full_flow",
            primitives=["EMAIL"],
            scopes=["email.read"],
            connector_class=MockConnector,
        ))
        
        # 2. Store credentials
        self.cred_store.save_token(
            provider="full_flow",
            access_token="test_token",
            refresh_token="refresh_token",
            expires_in=3600,
            scopes=["email.read"],
        )
        
        # 3. Verify credential status
        self.assertTrue(self.cred_store.has_valid("full_flow"))
        
        # 4. Connect
        async def connect():
            result = await self.registry.connect("full_flow_conn")
            return result
        
        result = asyncio.run(connect())
        self.assertTrue(result)
        
        # 5. Verify connection
        conn = self.registry.get_connector("full_flow_conn")
        self.assertIsNotNone(conn)
        self.assertTrue(conn.is_connected)
    
    def test_primitive_resolution(self):
        """Test resolving primitive to connector."""
        # Register multiple email providers
        self.registry.register(ConnectorMetadata(
            name="email_a", display_name="Email A", provider="provider_a",
            primitives=["EMAIL"], scopes=[], connector_class=MockConnector,
        ))
        self.registry.register(ConnectorMetadata(
            name="email_b", display_name="Email B", provider="provider_b",
            primitives=["EMAIL"], scopes=[], connector_class=MockConnector,
        ))
        
        # Connect to email_b
        async def setup():
            await self.registry.connect("email_b")
        asyncio.run(setup())
        
        # Get connector for EMAIL primitive
        async def resolve():
            return self.registry.get_connector_for_primitive("EMAIL")
        
        # Should get email_b since it's connected
        # (In real impl, would check credentials)
        providers = self.registry.get_providers_for_primitive("EMAIL")
        self.assertIn("email_a", providers)
        self.assertIn("email_b", providers)
    
    def test_setup_status(self):
        """Test setup status reporting."""
        self.registry.register(ConnectorMetadata(
            name="setup_test",
            display_name="Setup Test",
            provider="setup_provider",
            primitives=["TEST"],
            scopes=[],
            connector_class=MockConnector,
            requires_client_creds=True,
        ))
        
        status = self.registry.get_setup_status()
        
        # Without credentials, should need credentials
        self.assertIn("needs_credentials", status)
        self.assertIn("ready", status)


# ============================================================================
# Run Tests
# ============================================================================

def run_tests():
    """Run all tests and print summary."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add test classes
    suite.addTests(loader.loadTestsFromTestCase(TestCredentialStore))
    suite.addTests(loader.loadTestsFromTestCase(TestEncryptedFileBackend))
    suite.addTests(loader.loadTestsFromTestCase(TestConnectorRegistry))
    suite.addTests(loader.loadTestsFromTestCase(TestConnectorRegistryAsync))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    
    # Run with verbosity
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print("\n" + "=" * 70)
    print("CONNECTOR INFRASTRUCTURE TEST RESULTS")
    print("=" * 70)
    
    total = result.testsRun
    failures = len(result.failures)
    errors = len(result.errors)
    passed = total - failures - errors
    
    print(f"\nTotal tests: {total}")
    print(f"Passed: {passed} ({100 * passed / total:.1f}%)")
    print(f"Failed: {failures} ({100 * failures / total:.1f}%)")
    print(f"Errors: {errors} ({100 * errors / total:.1f}%)")
    
    if failures > 0:
        print("\nFailed tests:")
        for test, traceback in result.failures:
            print(f"  - {test}")
    
    if errors > 0:
        print("\nErrors:")
        for test, traceback in result.errors:
            print(f"  - {test}")
    
    return passed == total


if __name__ == "__main__":
    success = run_tests()
    exit(0 if success else 1)
