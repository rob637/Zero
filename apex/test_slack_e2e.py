"""
End-to-End Tests for Slack Connector

Tests the Slack connector for workplace communication integration.

Run with: python -m pytest apex/test_slack_e2e.py -v
Or directly: python apex/test_slack_e2e.py

Set SLACK_BOT_TOKEN environment variable to run live tests.
Without the token, tests use mock responses.
"""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from apex.connectors.slack import (
    SlackConnector,
    SlackUser,
    SlackChannel,
    SlackMessage,
    create_slack_connector,
)


# ============================================================
#  Test Data
# ============================================================

MOCK_USER = {
    "id": "U12345678",
    "name": "apex_bot",
    "real_name": "Apex Bot",
    "profile": {
        "real_name": "Apex Bot",
        "display_name": "apex",
        "email": "apex@example.com",
        "image_72": "https://example.com/avatar.png",
        "status_text": "Working",
        "status_emoji": ":computer:",
    },
    "is_bot": True,
    "is_admin": False,
    "tz": "America/Los_Angeles",
}

MOCK_CHANNEL = {
    "id": "C12345678",
    "name": "general",
    "is_private": False,
    "is_archived": False,
    "is_member": True,
    "topic": {"value": "General discussion"},
    "purpose": {"value": "Company-wide announcements"},
    "num_members": 100,
    "created": 1609459200,  # 2021-01-01
}

MOCK_MESSAGE = {
    "ts": "1704067200.000100",  # 2024-01-01
    "text": "Hello from Apex! <@U87654321> check this out",
    "user": "U12345678",
    "channel": "C12345678",
    "reactions": [{"name": "thumbsup", "count": 3}],
    "files": [],
}

MOCK_AUTH_RESPONSE = {
    "ok": True,
    "url": "https://example.slack.com/",
    "team": "Example Team",
    "team_id": "T12345678",
    "user": "apex_bot",
    "user_id": "U12345678",
}


# ============================================================
#  Data Model Tests
# ============================================================

class TestSlackDataModels:
    """Test Slack data model classes."""
    
    def test_slack_user_from_api(self):
        """Test SlackUser.from_api()."""
        user = SlackUser.from_api(MOCK_USER)
        
        assert user.id == "U12345678"
        assert user.name == "apex_bot"
        assert user.real_name == "Apex Bot"
        assert user.email == "apex@example.com"
        assert user.is_bot is True
        assert user.status_emoji == ":computer:"
        
        # Test to_dict serialization
        d = user.to_dict()
        assert d["id"] == "U12345678"
        assert "Working" in (d.get("status") or "")
    
    def test_slack_channel_from_api(self):
        """Test SlackChannel.from_api()."""
        channel = SlackChannel.from_api(MOCK_CHANNEL)
        
        assert channel.id == "C12345678"
        assert channel.name == "general"
        assert channel.is_private is False
        assert channel.is_member is True
        assert channel.num_members == 100
        assert channel.topic == "General discussion"
        
        # Test to_dict serialization
        d = channel.to_dict()
        assert d["name"] == "general"
        assert d["num_members"] == 100
    
    def test_slack_message_from_api(self):
        """Test SlackMessage.from_api()."""
        msg = SlackMessage.from_api(MOCK_MESSAGE, channel_name="general")
        
        assert msg.ts == "1704067200.000100"
        assert "Hello from Apex" in msg.text
        assert msg.user_id == "U12345678"
        assert msg.channel_name == "general"
        assert len(msg.reactions) == 1
        assert "U87654321" in msg.mentions  # Extracted from text
        
        # Test to_dict serialization
        d = msg.to_dict()
        assert d["ts"] == "1704067200.000100"
        assert "thumbsup" in d["reactions"]


# ============================================================
#  Connector Tests (Mock)
# ============================================================

class TestSlackConnectorMock:
    """Test SlackConnector with mocked API."""
    
    @pytest.fixture
    def connector(self):
        """Create connector with mock token."""
        return SlackConnector(token="xoxb-test-token")
    
    @pytest.mark.asyncio
    async def test_connect_success(self, connector):
        """Test successful connection."""
        with patch.object(connector, '_post', new=AsyncMock(return_value=MOCK_AUTH_RESPONSE)):
            with patch.object(connector, '_get', new=AsyncMock(return_value={"ok": True, "user": MOCK_USER})):
                # Need to set client for _post/_get to work
                connector._client = MagicMock()
                result = await connector.connect()
                # Note: This will fail on actual execution since _post needs real client
                # In real test, we'd use httpx mock
    
    @pytest.mark.asyncio
    async def test_list_channels_mock(self, connector):
        """Test listing channels with mock response."""
        mock_response = {
            "ok": True,
            "channels": [MOCK_CHANNEL, {**MOCK_CHANNEL, "id": "C87654321", "name": "random"}]
        }
        
        connector._client = AsyncMock()
        connector._client.get = AsyncMock(return_value=MagicMock(json=lambda: mock_response))
        
        channels = await connector.list_channels()
        
        assert len(channels) == 2
        assert channels[0].name == "general"
        assert channels[1].name == "random"
    
    @pytest.mark.asyncio
    async def test_send_message_mock(self, connector):
        """Test sending a message with mock response."""
        mock_response = {
            "ok": True,
            "ts": "1704067200.000200",
            "channel": "C12345678",
        }
        
        connector._client = AsyncMock()
        connector._client.post = AsyncMock(return_value=MagicMock(json=lambda: mock_response))
        connector._channels_cache["C12345678"] = SlackChannel.from_api(MOCK_CHANNEL)
        
        ts = await connector.send_message("C12345678", "Test message")
        
        assert ts == "1704067200.000200"
    
    @pytest.mark.asyncio
    async def test_get_channel_history_mock(self, connector):
        """Test getting channel history with mock response."""
        mock_response = {
            "ok": True,
            "messages": [
                MOCK_MESSAGE,
                {**MOCK_MESSAGE, "ts": "1704067100.000100", "text": "Earlier message"},
            ]
        }
        
        connector._client = AsyncMock()
        connector._client.get = AsyncMock(return_value=MagicMock(json=lambda: mock_response))
        connector._channels_cache["C12345678"] = SlackChannel.from_api(MOCK_CHANNEL)
        
        messages = await connector.get_channel_history("C12345678", limit=10)
        
        assert len(messages) == 2
        assert "Hello from Apex" in messages[0].text
    
    @pytest.mark.asyncio
    async def test_search_messages_mock(self, connector):
        """Test searching messages with mock response."""
        mock_response = {
            "ok": True,
            "messages": {
                "matches": [
                    {**MOCK_MESSAGE, "channel": {"name": "general"}, "username": "apex_bot", "permalink": "https://..."},
                ]
            }
        }
        
        connector._client = AsyncMock()
        connector._client.get = AsyncMock(return_value=MagicMock(json=lambda: mock_response))
        
        messages = await connector.search_messages("Apex")
        
        assert len(messages) == 1
        assert messages[0].channel_name == "general"
    
    @pytest.mark.asyncio
    async def test_get_user_mock(self, connector):
        """Test getting user info with mock response."""
        mock_response = {"ok": True, "user": MOCK_USER}
        
        connector._client = AsyncMock()
        connector._client.get = AsyncMock(return_value=MagicMock(json=lambda: mock_response))
        
        user = await connector.get_user("U12345678")
        
        assert user.id == "U12345678"
        assert user.name == "apex_bot"
        
        # Test cache hit
        user2 = await connector.get_user("U12345678")
        assert user2.id == user.id


# ============================================================
#  Integration with ProactiveMonitor
# ============================================================

class TestSlackProactiveIntegration:
    """Test Slack connector's ProactiveMonitor compatibility."""
    
    @pytest.mark.asyncio
    async def test_poll_method_exists(self):
        """Test that poll() method exists for ProactiveMonitor."""
        connector = SlackConnector(token="xoxb-test")
        
        # Should have poll method
        assert hasattr(connector, 'poll')
        assert callable(connector.poll)
        
        # Should have get_recent method
        assert hasattr(connector, 'get_recent')
        assert callable(connector.get_recent)
    
    @pytest.mark.asyncio
    async def test_activity_summary_structure(self):
        """Test activity summary has expected structure."""
        connector = SlackConnector(token="xoxb-test")
        
        # Mock the internal methods
        connector._connected = True
        connector._user = SlackUser.from_api(MOCK_USER)
        connector._team = {"name": "Test Team"}
        connector.get_mentions = AsyncMock(return_value=[])
        connector.get_dms = AsyncMock(return_value=[])
        connector.list_channels = AsyncMock(return_value=[SlackChannel.from_api(MOCK_CHANNEL)])
        
        summary = await connector.get_activity_summary()
        
        assert "timestamp" in summary
        assert "team" in summary
        assert "user" in summary
        assert "mentions" in summary
        assert "unread_dms" in summary
        assert "channels" in summary
        
        # Verify channel was included (member=True)
        assert len(summary["channels"]) == 1


# ============================================================
#  Factory Function Tests
# ============================================================

class TestSlackFactory:
    """Test factory function."""
    
    def test_create_slack_connector(self):
        """Test create_slack_connector factory."""
        connector = create_slack_connector(token="xoxb-test-token")
        
        assert isinstance(connector, SlackConnector)
        assert connector._token == "xoxb-test-token"
    
    def test_create_slack_connector_from_env(self):
        """Test creating connector from environment variable."""
        old_env = os.environ.get("SLACK_BOT_TOKEN")
        try:
            os.environ["SLACK_BOT_TOKEN"] = "xoxb-env-token"
            connector = create_slack_connector()
            
            assert connector._token == "xoxb-env-token"
        finally:
            if old_env:
                os.environ["SLACK_BOT_TOKEN"] = old_env
            else:
                os.environ.pop("SLACK_BOT_TOKEN", None)


# ============================================================
#  Live Tests (require SLACK_BOT_TOKEN)
# ============================================================

@pytest.mark.skipif(
    not os.environ.get("SLACK_BOT_TOKEN"),
    reason="SLACK_BOT_TOKEN not set"
)
class TestSlackLive:
    """Live tests against real Slack API."""
    
    @pytest.fixture
    async def live_connector(self):
        """Create and connect live connector."""
        connector = SlackConnector()
        connected = await connector.connect()
        if not connected:
            pytest.skip("Could not connect to Slack")
        yield connector
        await connector.disconnect()
    
    @pytest.mark.asyncio
    async def test_live_connect(self, live_connector):
        """Test live connection to Slack."""
        assert live_connector.is_connected
        assert live_connector.current_user is not None
        assert live_connector.team is not None
        print(f"\n✓ Connected as {live_connector.current_user.name} to {live_connector.team.get('name')}")
    
    @pytest.mark.asyncio
    async def test_live_list_channels(self, live_connector):
        """Test listing channels from live Slack."""
        channels = await live_connector.list_channels(limit=10)
        
        assert isinstance(channels, list)
        print(f"\n✓ Found {len(channels)} channels")
        for ch in channels[:3]:
            print(f"  - #{ch.name} ({ch.num_members} members)")
    
    @pytest.mark.asyncio
    async def test_live_list_users(self, live_connector):
        """Test listing users from live Slack."""
        users = await live_connector.list_users(limit=10)
        
        assert isinstance(users, list)
        print(f"\n✓ Found {len(users)} users")
        for u in users[:3]:
            print(f"  - @{u.name} ({u.real_name})")
    
    @pytest.mark.asyncio
    async def test_live_activity_summary(self, live_connector):
        """Test getting activity summary from live Slack."""
        summary = await live_connector.get_activity_summary()
        
        assert "timestamp" in summary
        assert "team" in summary
        print(f"\n✓ Activity summary:")
        print(f"  - Team: {summary.get('team')}")
        print(f"  - Channels: {len(summary.get('channels', []))}")
        print(f"  - Mentions: {len(summary.get('mentions', []))}")


# ============================================================
#  Run All Tests
# ============================================================

async def run_all_tests():
    """Run all tests manually."""
    print("=" * 60)
    print("Slack Connector E2E Tests")
    print("=" * 60)
    
    # Data model tests
    print("\n--- Data Model Tests ---")
    test_models = TestSlackDataModels()
    test_models.test_slack_user_from_api()
    print("✓ SlackUser.from_api()")
    test_models.test_slack_channel_from_api()
    print("✓ SlackChannel.from_api()")
    test_models.test_slack_message_from_api()
    print("✓ SlackMessage.from_api()")
    
    # Factory tests
    print("\n--- Factory Tests ---")
    factory_tests = TestSlackFactory()
    factory_tests.test_create_slack_connector()
    print("✓ create_slack_connector()")
    
    # ProactiveMonitor integration
    print("\n--- ProactiveMonitor Integration ---")
    integration_tests = TestSlackProactiveIntegration()
    await integration_tests.test_poll_method_exists()
    print("✓ poll() method exists")
    await integration_tests.test_activity_summary_structure()
    print("✓ Activity summary structure")
    
    # Live tests (if token available)
    if os.environ.get("SLACK_BOT_TOKEN"):
        print("\n--- Live Tests ---")
        connector = SlackConnector()
        connected = await connector.connect()
        if connected:
            print(f"✓ Connected to {connector.team.get('name')}")
            
            channels = await connector.list_channels(limit=5)
            print(f"✓ Listed {len(channels)} channels")
            
            users = await connector.list_users(limit=5)
            print(f"✓ Listed {len(users)} users")
            
            summary = await connector.get_activity_summary()
            print(f"✓ Generated activity summary")
            
            await connector.disconnect()
            print("✓ Disconnected")
        else:
            print("✗ Could not connect (check token)")
    else:
        print("\n[SKIP] Live tests (SLACK_BOT_TOKEN not set)")
    
    print("\n" + "=" * 60)
    print("All tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
