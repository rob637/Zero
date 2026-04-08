"""
OAuth Flow Tests

Tests for the OAuth 2.0 flow module including:
- Provider configuration
- Authorization URL generation
- PKCE verification
- State management
- Token storage integration
- Callback handling (mocked)
"""

import asyncio
import base64
import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))

from connectors.oauth_flow import (
    OAuthFlow,
    OAuthProviderConfig,
    PendingAuth,
    OAUTH_PROVIDERS,
    get_oauth_flow,
    reset_oauth_flow,
)
from connectors.credentials import (
    CredentialStore,
    MemoryBackend,
    reset_credential_store,
)


class TestOAuthProviderConfigs(unittest.TestCase):
    """Test OAuth provider configurations."""
    
    def test_all_expected_providers_exist(self):
        """All expected providers should be configured."""
        expected = {
            "google", "microsoft", "slack", "github",
            "discord", "spotify", "dropbox", "atlassian"
        }
        actual = set(OAUTH_PROVIDERS.keys())
        self.assertEqual(expected, actual)
    
    def test_google_config(self):
        """Google provider should have correct configuration."""
        config = OAUTH_PROVIDERS["google"]
        
        self.assertEqual(config.name, "Google")
        self.assertIn("accounts.google.com", config.auth_url)
        self.assertIn("oauth2.googleapis.com", config.token_url)
        self.assertTrue(config.supports_pkce)
        
        # Check important services
        self.assertIn("gmail", config.scopes)
        self.assertIn("calendar", config.scopes)
        self.assertIn("drive", config.scopes)
        self.assertIn("all", config.scopes)
    
    def test_microsoft_config(self):
        """Microsoft provider should have correct configuration."""
        config = OAUTH_PROVIDERS["microsoft"]
        
        self.assertEqual(config.name, "Microsoft")
        self.assertIn("login.microsoftonline.com", config.auth_url)
        self.assertIn("login.microsoftonline.com", config.token_url)
        self.assertTrue(config.supports_pkce)
        
        # Check important services
        self.assertIn("mail", config.scopes)
        self.assertIn("calendar", config.scopes)
        self.assertIn("onedrive", config.scopes)
        self.assertIn("tasks", config.scopes)
        self.assertIn("all", config.scopes)
    
    def test_slack_no_pkce(self):
        """Slack should not support PKCE."""
        config = OAUTH_PROVIDERS["slack"]
        self.assertFalse(config.supports_pkce)
    
    def test_github_no_pkce(self):
        """GitHub should not support PKCE."""
        config = OAUTH_PROVIDERS["github"]
        self.assertFalse(config.supports_pkce)
    
    def test_all_providers_have_scopes(self):
        """All providers should have at least one scope definition."""
        for name, config in OAUTH_PROVIDERS.items():
            self.assertGreater(len(config.scopes), 0, f"{name} has no scopes")


class TestOAuthFlowInit(unittest.TestCase):
    """Test OAuthFlow initialization."""
    
    def setUp(self):
        reset_oauth_flow()
        reset_credential_store()
    
    def tearDown(self):
        reset_oauth_flow()
        reset_credential_store()
    
    def test_oauth_flow_initialization(self):
        """OAuthFlow should initialize correctly."""
        store = CredentialStore(backend=MemoryBackend())
        flow = OAuthFlow(credential_store=store)
        
        self.assertIsNotNone(flow)
        self.assertIsNotNone(flow._credential_store)
    
    def test_get_supported_providers(self):
        """Should return list of supported providers."""
        store = CredentialStore(backend=MemoryBackend())
        flow = OAuthFlow(credential_store=store)
        
        providers = flow.get_supported_providers()
        
        self.assertIsInstance(providers, list)
        self.assertIn("google", providers)
        self.assertIn("microsoft", providers)
        self.assertGreater(len(providers), 5)
    
    def test_get_provider_info(self):
        """Should return provider information."""
        store = CredentialStore(backend=MemoryBackend())
        flow = OAuthFlow(credential_store=store)
        
        info = flow.get_provider_info("google")
        
        self.assertEqual(info["name"], "Google")
        self.assertIn("gmail", info["services"])
        self.assertTrue(info["supports_pkce"])
    
    def test_get_invalid_provider_info(self):
        """Should raise error for unknown provider."""
        store = CredentialStore(backend=MemoryBackend())
        flow = OAuthFlow(credential_store=store)
        
        with self.assertRaises(ValueError):
            flow.get_provider_info("invalid_provider")


class TestAuthUrlGeneration(unittest.TestCase):
    """Test OAuth authorization URL generation."""
    
    def setUp(self):
        reset_oauth_flow()
        reset_credential_store()
        self.store = CredentialStore(backend=MemoryBackend())
        self.flow = OAuthFlow(
            credential_store=self.store,
            redirect_uri="http://127.0.0.1:8000/oauth/callback",
        )
    
    def tearDown(self):
        reset_oauth_flow()
        reset_credential_store()
    
    def test_google_auth_url_generation(self):
        """Should generate valid Google auth URL."""
        url = self.flow.get_auth_url(
            provider="google",
            client_id="test-client-id",
            client_secret="test-secret",
            services=["gmail", "calendar"],
        )
        
        self.assertIn("accounts.google.com", url)
        self.assertIn("client_id=test-client-id", url)
        self.assertIn("response_type=code", url)
        self.assertIn("redirect_uri=", url)
        self.assertIn("state=", url)
        # PKCE
        self.assertIn("code_challenge=", url)
        self.assertIn("code_challenge_method=S256", url)
        # Google specific
        self.assertIn("access_type=offline", url)
    
    def test_microsoft_auth_url_generation(self):
        """Should generate valid Microsoft auth URL."""
        url = self.flow.get_auth_url(
            provider="microsoft",
            client_id="test-ms-client",
            services=["mail", "calendar"],
        )
        
        self.assertIn("login.microsoftonline.com", url)
        self.assertIn("client_id=test-ms-client", url)
        self.assertIn("response_type=code", url)
    
    def test_slack_no_pkce(self):
        """Slack auth URL should not have PKCE parameters."""
        url = self.flow.get_auth_url(
            provider="slack",
            client_id="test-slack-id",
            services=["bot"],
        )
        
        self.assertIn("slack.com", url)
        self.assertNotIn("code_challenge", url)
    
    def test_custom_redirect_uri(self):
        """Should use custom redirect URI when provided."""
        url = self.flow.get_auth_url(
            provider="google",
            client_id="test-id",
            redirect_uri="https://myapp.com/callback",
        )
        
        self.assertIn("redirect_uri=https%3A%2F%2Fmyapp.com%2Fcallback", url)
    
    def test_custom_scopes_override(self):
        """Should allow custom scopes."""
        url = self.flow.get_auth_url(
            provider="google",
            client_id="test-id",
            scopes=["https://custom.scope.com/api"],
        )
        
        self.assertIn("custom.scope.com", url)
    
    def test_state_is_generated(self):
        """State parameter should be generated."""
        url = self.flow.get_auth_url(
            provider="google",
            client_id="test-id",
            services=["gmail"],
        )
        
        self.assertIn("state=", url)
    
    def test_pending_auth_stored(self):
        """Pending auth should be stored after URL generation."""
        url = self.flow.get_auth_url(
            provider="google",
            client_id="test-id",
            client_secret="test-secret",
            services=["gmail"],
        )
        
        # Extract state from URL
        import urllib.parse
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        state = params["state"][0]
        
        # Verify pending auth exists
        self.assertIn(state, self.flow._pending)
        pending = self.flow._pending[state]
        
        self.assertEqual(pending.provider, "google")
        self.assertEqual(pending.client_id, "test-id")
        self.assertEqual(pending.client_secret, "test-secret")
        self.assertIn("gmail", pending.services)
    
    def test_invalid_provider_raises(self):
        """Should raise error for unknown provider."""
        with self.assertRaises(ValueError):
            self.flow.get_auth_url(
                provider="invalid",
                client_id="test-id",
            )
    
    def test_no_scopes_uses_all(self):
        """Should use 'all' scopes when none specified."""
        url = self.flow.get_auth_url(
            provider="google",
            client_id="test-id",
        )
        
        # Should contain scopes from "all"
        self.assertIn("scope=", url)


class TestPKCEGeneration(unittest.TestCase):
    """Test PKCE code verifier and challenge generation."""
    
    def setUp(self):
        self.store = CredentialStore(backend=MemoryBackend())
        self.flow = OAuthFlow(credential_store=self.store)
    
    def test_pkce_verifier_length(self):
        """PKCE verifier should be URL-safe and proper length."""
        verifier, challenge = self.flow._generate_pkce()
        
        # Verifier should be 43-128 chars (URL-safe base64)
        self.assertGreater(len(verifier), 40)
        self.assertLess(len(verifier), 130)
    
    def test_pkce_challenge_correct(self):
        """PKCE challenge should be SHA256 of verifier."""
        verifier, challenge = self.flow._generate_pkce()
        
        # Manually compute expected challenge
        digest = hashlib.sha256(verifier.encode()).digest()
        expected = base64.urlsafe_b64encode(digest).decode().rstrip("=")
        
        self.assertEqual(challenge, expected)
    
    def test_pkce_unique_each_time(self):
        """Each call should generate unique verifier/challenge."""
        v1, c1 = self.flow._generate_pkce()
        v2, c2 = self.flow._generate_pkce()
        
        self.assertNotEqual(v1, v2)
        self.assertNotEqual(c1, c2)


class TestPendingAuth(unittest.TestCase):
    """Test PendingAuth dataclass."""
    
    def test_pending_auth_not_expired(self):
        """Fresh pending auth should not be expired."""
        pending = PendingAuth(
            state="test-state",
            provider="google",
            services=["gmail"],
            scopes=["scope1"],
            redirect_uri="http://localhost/callback",
            code_verifier="verifier",
            created_at=datetime.utcnow(),
            client_id="client-id",
            client_secret="secret",
        )
        
        self.assertFalse(pending.is_expired())
    
    def test_pending_auth_expired(self):
        """Old pending auth should be expired."""
        pending = PendingAuth(
            state="test-state",
            provider="google",
            services=["gmail"],
            scopes=["scope1"],
            redirect_uri="http://localhost/callback",
            code_verifier="verifier",
            created_at=datetime.utcnow() - timedelta(minutes=15),
            client_id="client-id",
            client_secret="secret",
        )
        
        self.assertTrue(pending.is_expired())
    
    def test_pending_auth_serialization(self):
        """PendingAuth should serialize/deserialize correctly."""
        pending = PendingAuth(
            state="test-state",
            provider="google",
            services=["gmail", "calendar"],
            scopes=["scope1", "scope2"],
            redirect_uri="http://localhost/callback",
            code_verifier="verifier123",
            created_at=datetime.utcnow(),
            client_id="client-id",
            client_secret="secret",
        )
        
        # Serialize
        data = pending.to_dict()
        
        # Deserialize
        restored = PendingAuth.from_dict(data)
        
        self.assertEqual(restored.state, pending.state)
        self.assertEqual(restored.provider, pending.provider)
        self.assertEqual(restored.services, pending.services)
        self.assertEqual(restored.scopes, pending.scopes)
        self.assertEqual(restored.client_id, pending.client_id)


class TestConnectionStatus(unittest.TestCase):
    """Test connection status checking."""
    
    def setUp(self):
        reset_oauth_flow()
        reset_credential_store()
        self.store = CredentialStore(backend=MemoryBackend())
        self.flow = OAuthFlow(credential_store=self.store)
    
    def tearDown(self):
        reset_oauth_flow()
        reset_credential_store()
    
    def test_not_connected_by_default(self):
        """Provider should not be connected by default."""
        self.assertFalse(self.flow.is_connected("google"))
    
    def test_connection_status_all_providers(self):
        """Should return status for all providers."""
        status = self.flow.get_connection_status()
        
        for provider in OAUTH_PROVIDERS:
            self.assertIn(provider, status)
            self.assertIn("connected", status[provider])
            self.assertIn("scopes", status[provider])
    
    def test_connected_after_token_stored(self):
        """Should show connected after token is stored."""
        # Manually store a token
        self.store.save_token(
            provider="google",
            access_token="test-token",
            refresh_token="refresh-token",
            expires_in=3600,
            scopes=["gmail"],
        )
        
        self.assertTrue(self.flow.is_connected("google"))
        
        status = self.flow.get_connection_status()
        self.assertTrue(status["google"]["connected"])
    
    def test_disconnect_removes_credentials(self):
        """Disconnect should remove stored credentials."""
        # Store token
        self.store.save_token(
            provider="microsoft",
            access_token="test-token",
            expires_in=3600,
        )
        
        self.assertTrue(self.flow.is_connected("microsoft"))
        
        # Disconnect
        success = self.flow.disconnect("microsoft")
        
        self.assertTrue(success)
        self.assertFalse(self.flow.is_connected("microsoft"))


class TestScopeResolution(unittest.TestCase):
    """Test scope name to OAuth scope resolution."""
    
    def setUp(self):
        self.store = CredentialStore(backend=MemoryBackend())
        self.flow = OAuthFlow(credential_store=self.store)
    
    def test_google_gmail_scopes(self):
        """Gmail service should resolve to Gmail API scopes."""
        scopes = self.flow._resolve_scopes("google", services=["gmail"])
        
        self.assertIn("https://www.googleapis.com/auth/gmail.readonly", scopes)
        self.assertIn("https://www.googleapis.com/auth/gmail.send", scopes)
    
    def test_multiple_services(self):
        """Multiple services should combine scopes."""
        scopes = self.flow._resolve_scopes("google", services=["gmail", "calendar"])
        
        # Should have gmail scopes
        self.assertIn("https://www.googleapis.com/auth/gmail.readonly", scopes)
        # Should have calendar scopes
        self.assertIn("https://www.googleapis.com/auth/calendar", scopes)
    
    def test_custom_scopes_added(self):
        """Custom scopes should be added."""
        scopes = self.flow._resolve_scopes(
            "google",
            services=["gmail"],
            custom_scopes=["https://custom.scope"],
        )
        
        self.assertIn("https://custom.scope", scopes)
        self.assertIn("https://www.googleapis.com/auth/gmail.readonly", scopes)
    
    def test_all_scopes_default(self):
        """Should use 'all' when no services specified."""
        scopes = self.flow._resolve_scopes("google")
        
        # Should have scopes from "all"
        self.assertGreater(len(scopes), 0)


class TestSingletonPattern(unittest.TestCase):
    """Test singleton pattern for OAuthFlow."""
    
    def setUp(self):
        reset_oauth_flow()
    
    def tearDown(self):
        reset_oauth_flow()
    
    def test_singleton_returns_same_instance(self):
        """get_oauth_flow should return same instance."""
        flow1 = get_oauth_flow()
        flow2 = get_oauth_flow()
        
        self.assertIs(flow1, flow2)
    
    def test_reset_creates_new_instance(self):
        """reset_oauth_flow should allow new instance."""
        flow1 = get_oauth_flow()
        reset_oauth_flow()
        flow2 = get_oauth_flow()
        
        self.assertIsNot(flow1, flow2)


class TestCallbackHandling(unittest.TestCase):
    """Test OAuth callback handling (with mocks)."""
    
    def setUp(self):
        reset_oauth_flow()
        reset_credential_store()
        self.store = CredentialStore(backend=MemoryBackend())
        self.flow = OAuthFlow(credential_store=self.store)
    
    def tearDown(self):
        reset_oauth_flow()
        reset_credential_store()
    
    def test_invalid_state_raises(self):
        """Invalid state should raise error."""
        async def run():
            with self.assertRaises(ValueError):
                await self.flow.handle_callback("code", "invalid-state")
        
        asyncio.run(run())
    
    def test_expired_state_raises(self):
        """Expired state should raise error."""
        # Create expired pending auth
        expired_pending = PendingAuth(
            state="expired-state",
            provider="google",
            services=["gmail"],
            scopes=["scope1"],
            redirect_uri="http://localhost/callback",
            code_verifier="verifier",
            created_at=datetime.utcnow() - timedelta(minutes=15),
            client_id="client-id",
            client_secret="secret",
        )
        self.flow._pending["expired-state"] = expired_pending
        
        async def run():
            with self.assertRaises(ValueError) as ctx:
                await self.flow.handle_callback("code", "expired-state")
            self.assertIn("expired", str(ctx.exception).lower())
        
        asyncio.run(run())
    
    @patch('connectors.oauth_flow.httpx')
    def test_successful_callback(self, mock_httpx):
        """Successful callback should store tokens."""
        # Set up pending auth
        state = "valid-state"
        self.flow._pending[state] = PendingAuth(
            state=state,
            provider="google",
            services=["gmail"],
            scopes=["scope1"],
            redirect_uri="http://localhost/callback",
            code_verifier="verifier",
            created_at=datetime.utcnow(),
            client_id="client-id",
            client_secret="secret",
        )
        
        # Mock httpx response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 3600,
            "token_type": "Bearer",
        }
        
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_httpx.AsyncClient.return_value = mock_client
        
        async def run():
            result = await self.flow.handle_callback("auth-code", state)
            
            self.assertTrue(result["success"])
            self.assertEqual(result["provider"], "google")
            self.assertIn("gmail", result["services"])
            
            # Verify token was stored
            self.assertTrue(self.flow.is_connected("google"))
        
        asyncio.run(run())


def run_tests():
    """Run all OAuth flow tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestOAuthProviderConfigs))
    suite.addTests(loader.loadTestsFromTestCase(TestOAuthFlowInit))
    suite.addTests(loader.loadTestsFromTestCase(TestAuthUrlGeneration))
    suite.addTests(loader.loadTestsFromTestCase(TestPKCEGeneration))
    suite.addTests(loader.loadTestsFromTestCase(TestPendingAuth))
    suite.addTests(loader.loadTestsFromTestCase(TestConnectionStatus))
    suite.addTests(loader.loadTestsFromTestCase(TestScopeResolution))
    suite.addTests(loader.loadTestsFromTestCase(TestSingletonPattern))
    suite.addTests(loader.loadTestsFromTestCase(TestCallbackHandling))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Summary
    print("\n" + "="*60)
    print("OAUTH FLOW TEST SUMMARY")
    print("="*60)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Success: {result.wasSuccessful()}")
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
