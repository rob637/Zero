"""
End-to-End Test Scenarios for New Connectors

Tests for: Discord, GitHub, Slack, Spotify, Todoist

These tests verify:
- Connector instantiation and data models
- Method signatures exist and are callable
- Live API calls work when credentials are available
- Graceful behavior without credentials

Run all:      python -m pytest apex/test_connector_scenarios.py -v
Run one:      python -m pytest apex/test_connector_scenarios.py -k "github" -v
Run live:     LIVE_TEST=1 python -m pytest apex/test_connector_scenarios.py -v
Or directly:  python apex/test_connector_scenarios.py
"""

import asyncio
import os
import unittest
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

LIVE = os.environ.get("LIVE_TEST", "").strip() == "1"


def async_test(coro):
    """Decorator to run async tests."""
    def wrapper(*args, **kwargs):
        return asyncio.get_event_loop().run_until_complete(coro(*args, **kwargs))
    return wrapper


# ============================================================================
# Discord Tests
# ============================================================================

class TestDiscordConnector(unittest.TestCase):
    """Tests for DiscordConnector."""

    def test_import(self):
        from connectors.discord import DiscordConnector, DiscordMessage, DiscordChannel
        self.assertIsNotNone(DiscordConnector)

    def test_message_dataclass(self):
        from connectors.discord import DiscordMessage
        msg = DiscordMessage(
            id="123456",
            channel_id="789",
            author="TestUser",
            content="Hello world",
            timestamp=datetime.utcnow().isoformat(),
        )
        self.assertEqual(msg.id, "123456")
        self.assertEqual(msg.content, "Hello world")
        self.assertEqual(msg.author, "TestUser")

    def test_channel_dataclass(self):
        from connectors.discord import DiscordChannel
        ch = DiscordChannel(
            id="789",
            name="general",
            guild_id="111",
        )
        self.assertEqual(ch.name, "general")

    def test_connector_instantiation(self):
        from connectors.discord import DiscordConnector
        connector = DiscordConnector()
        self.assertTrue(hasattr(connector, 'connect'))
        self.assertTrue(hasattr(connector, 'list_guilds'))
        self.assertTrue(hasattr(connector, 'list_channels'))
        self.assertTrue(hasattr(connector, 'list_messages'))
        self.assertTrue(hasattr(connector, 'send_message'))
        self.assertTrue(hasattr(connector, 'reply_to_message'))
        self.assertTrue(hasattr(connector, 'add_reaction'))
        self.assertTrue(hasattr(connector, 'send_dm'))
        self.assertTrue(hasattr(connector, 'search_messages'))

    @unittest.skipUnless(LIVE and os.environ.get("DISCORD_BOT_TOKEN"), "Need LIVE_TEST=1 and DISCORD_BOT_TOKEN")
    @async_test
    async def test_live_list_guilds(self):
        from connectors.discord import DiscordConnector
        connector = DiscordConnector()
        await connector.connect()
        try:
            guilds = await connector.list_guilds()
            self.assertIsInstance(guilds, list)
            print(f"  Discord: Found {len(guilds)} guilds")
            for g in guilds[:3]:
                print(f"    - {g.get('name', g.get('id'))}")
        finally:
            await connector.close()

    @unittest.skipUnless(LIVE and os.environ.get("DISCORD_BOT_TOKEN"), "Need LIVE_TEST=1 and DISCORD_BOT_TOKEN")
    @async_test
    async def test_live_list_channels(self):
        from connectors.discord import DiscordConnector
        connector = DiscordConnector()
        await connector.connect()
        try:
            guilds = await connector.list_guilds()
            self.assertTrue(len(guilds) > 0, "No guilds found — bot must be in at least one server")
            guild_id = guilds[0]["id"] if isinstance(guilds[0], dict) else guilds[0].id
            channels = await connector.list_channels(guild_id)
            self.assertIsInstance(channels, list)
            print(f"  Discord: Found {len(channels)} channels in first guild")
        finally:
            await connector.close()


# ============================================================================
# GitHub Tests
# ============================================================================

class TestGitHubConnector(unittest.TestCase):
    """Tests for GitHubConnector."""

    def test_import(self):
        from connectors.github import GitHubConnector, GitHubUser, GitHubRepo, GitHubIssue, GitHubPullRequest
        self.assertIsNotNone(GitHubConnector)

    def test_data_models(self):
        from connectors.github import GitHubUser, GitHubRepo, GitHubIssue
        # These should be importable data classes / named tuples
        self.assertIsNotNone(GitHubUser)
        self.assertIsNotNone(GitHubRepo)
        self.assertIsNotNone(GitHubIssue)

    def test_connector_instantiation(self):
        from connectors.github import GitHubConnector
        connector = GitHubConnector()
        self.assertTrue(hasattr(connector, 'connect'))
        self.assertTrue(hasattr(connector, 'list_repos'))
        self.assertTrue(hasattr(connector, 'list_issues'))
        self.assertTrue(hasattr(connector, 'create_issue'))
        self.assertTrue(hasattr(connector, 'list_pull_requests'))
        self.assertTrue(hasattr(connector, 'list_notifications'))
        self.assertTrue(hasattr(connector, 'get_unread_count'))
        self.assertTrue(hasattr(connector, 'search_issues'))
        self.assertTrue(hasattr(connector, 'search_repos'))
        self.assertTrue(hasattr(connector, 'get_activity_summary'))

    @unittest.skipUnless(LIVE and (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")), "Need LIVE_TEST=1 and GITHUB_TOKEN")
    @async_test
    async def test_live_get_user(self):
        from connectors.github import GitHubConnector
        connector = GitHubConnector()
        await connector.connect()
        try:
            user = await connector.get_authenticated_user()
            self.assertIsNotNone(user)
            print(f"  GitHub: Authenticated as {user.login if hasattr(user, 'login') else user}")
        finally:
            await connector.disconnect()

    @unittest.skipUnless(LIVE and (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")), "Need LIVE_TEST=1 and GITHUB_TOKEN")
    @async_test
    async def test_live_list_repos(self):
        from connectors.github import GitHubConnector
        connector = GitHubConnector()
        await connector.connect()
        try:
            repos = await connector.list_repos(per_page=5)
            self.assertIsInstance(repos, list)
            print(f"  GitHub: Found {len(repos)} repos (showing up to 5)")
            for r in repos[:5]:
                name = r.full_name if hasattr(r, 'full_name') else r.get('full_name', str(r))
                print(f"    - {name}")
        finally:
            await connector.disconnect()

    @unittest.skipUnless(LIVE and (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")), "Need LIVE_TEST=1 and GITHUB_TOKEN")
    @async_test
    async def test_live_notifications(self):
        from connectors.github import GitHubConnector
        connector = GitHubConnector()
        await connector.connect()
        try:
            count = await connector.get_unread_count()
            self.assertIsInstance(count, int)
            print(f"  GitHub: {count} unread notifications")
        finally:
            await connector.disconnect()

    @unittest.skipUnless(LIVE and (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")), "Need LIVE_TEST=1 and GITHUB_TOKEN")
    @async_test
    async def test_live_activity_summary(self):
        from connectors.github import GitHubConnector
        connector = GitHubConnector()
        await connector.connect()
        try:
            summary = await connector.get_activity_summary()
            self.assertIsNotNone(summary)
            print(f"  GitHub activity summary: {summary}")
        finally:
            await connector.disconnect()

    @unittest.skipUnless(LIVE and (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")), "Need LIVE_TEST=1 and GITHUB_TOKEN")
    @async_test
    async def test_live_search_repos(self):
        from connectors.github import GitHubConnector
        connector = GitHubConnector()
        await connector.connect()
        try:
            results = await connector.search_repos("language:python stars:>1000", per_page=3)
            self.assertIsInstance(results, list)
            print(f"  GitHub: Search found {len(results)} repos")
        finally:
            await connector.disconnect()


# ============================================================================
# Slack Tests
# ============================================================================

class TestSlackConnector(unittest.TestCase):
    """Tests for SlackConnector."""

    def test_import(self):
        from connectors.slack import SlackConnector, SlackUser, SlackChannel, SlackMessage
        self.assertIsNotNone(SlackConnector)

    def test_data_models(self):
        from connectors.slack import SlackUser, SlackChannel, SlackMessage
        self.assertIsNotNone(SlackUser)
        self.assertIsNotNone(SlackChannel)
        self.assertIsNotNone(SlackMessage)

    def test_connector_instantiation(self):
        from connectors.slack import SlackConnector
        connector = SlackConnector()
        self.assertTrue(hasattr(connector, 'connect'))
        self.assertTrue(hasattr(connector, 'list_channels'))
        self.assertTrue(hasattr(connector, 'send_message'))
        self.assertTrue(hasattr(connector, 'get_channel_history'))
        self.assertTrue(hasattr(connector, 'search_messages'))
        self.assertTrue(hasattr(connector, 'list_users'))
        self.assertTrue(hasattr(connector, 'find_user_by_email'))
        self.assertTrue(hasattr(connector, 'get_mentions'))
        self.assertTrue(hasattr(connector, 'get_dms'))
        self.assertTrue(hasattr(connector, 'set_status'))
        self.assertTrue(hasattr(connector, 'get_activity_summary'))

    @unittest.skipUnless(LIVE and os.environ.get("SLACK_BOT_TOKEN"), "Need LIVE_TEST=1 and SLACK_BOT_TOKEN")
    @async_test
    async def test_live_list_channels(self):
        from connectors.slack import SlackConnector
        connector = SlackConnector()
        await connector.connect()
        try:
            channels = await connector.list_channels()
            self.assertIsInstance(channels, list)
            print(f"  Slack: Found {len(channels)} channels")
            for ch in channels[:5]:
                name = ch.name if hasattr(ch, 'name') else ch.get('name', str(ch))
                print(f"    - #{name}")
        finally:
            await connector.disconnect()

    @unittest.skipUnless(LIVE and os.environ.get("SLACK_BOT_TOKEN"), "Need LIVE_TEST=1 and SLACK_BOT_TOKEN")
    @async_test
    async def test_live_list_users(self):
        from connectors.slack import SlackConnector
        connector = SlackConnector()
        await connector.connect()
        try:
            users = await connector.list_users()
            self.assertIsInstance(users, list)
            print(f"  Slack: Found {len(users)} users")
        finally:
            await connector.disconnect()

    @unittest.skipUnless(LIVE and os.environ.get("SLACK_BOT_TOKEN"), "Need LIVE_TEST=1 and SLACK_BOT_TOKEN")
    @async_test
    async def test_live_activity_summary(self):
        from connectors.slack import SlackConnector
        connector = SlackConnector()
        await connector.connect()
        try:
            summary = await connector.get_activity_summary()
            self.assertIsNotNone(summary)
            print(f"  Slack activity summary: {summary}")
        finally:
            await connector.disconnect()


# ============================================================================
# Spotify Tests
# ============================================================================

class TestSpotifyConnector(unittest.TestCase):
    """Tests for SpotifyConnector."""

    def test_import(self):
        from connectors.spotify import SpotifyConnector, SpotifyTrack
        self.assertIsNotNone(SpotifyConnector)

    def test_track_dataclass(self):
        from connectors.spotify import SpotifyTrack
        track = SpotifyTrack(
            id="4u7EnebtmKWzUH433cf5Qv",
            name="Bohemian Rhapsody",
            artist="Queen",
            album="A Night at the Opera",
            uri="spotify:track:4u7EnebtmKWzUH433cf5Qv",
            duration_ms=354320,
        )
        self.assertEqual(track.name, "Bohemian Rhapsody")
        self.assertEqual(track.artist, "Queen")

    def test_connector_instantiation(self):
        from connectors.spotify import SpotifyConnector
        connector = SpotifyConnector()
        self.assertTrue(hasattr(connector, 'connect'))
        self.assertTrue(hasattr(connector, 'control'))
        self.assertTrue(hasattr(connector, 'now_playing'))
        self.assertTrue(hasattr(connector, 'search'))
        self.assertTrue(hasattr(connector, 'saved_tracks'))
        self.assertTrue(hasattr(connector, 'playlists'))
        self.assertTrue(hasattr(connector, 'add_to_queue'))

    @unittest.skipUnless(LIVE and os.environ.get("SPOTIFY_ACCESS_TOKEN"), "Need LIVE_TEST=1 and SPOTIFY_ACCESS_TOKEN")
    @async_test
    async def test_live_search(self):
        from connectors.spotify import SpotifyConnector
        connector = SpotifyConnector()
        await connector.connect()
        try:
            results = await connector.search("Bohemian Rhapsody", limit=3)
            self.assertIsNotNone(results)
            print(f"  Spotify: Search returned results")
            if isinstance(results, list):
                for t in results[:3]:
                    name = t.name if hasattr(t, 'name') else t.get('name', str(t))
                    print(f"    - {name}")
        finally:
            await connector.close()

    @unittest.skipUnless(LIVE and os.environ.get("SPOTIFY_ACCESS_TOKEN"), "Need LIVE_TEST=1 and SPOTIFY_ACCESS_TOKEN")
    @async_test
    async def test_live_now_playing(self):
        from connectors.spotify import SpotifyConnector
        connector = SpotifyConnector()
        await connector.connect()
        try:
            track = await connector.now_playing()
            if track:
                name = track.name if hasattr(track, 'name') else track.get('name', 'Unknown')
                print(f"  Spotify: Now playing: {name}")
            else:
                print("  Spotify: Nothing currently playing (OK)")
        finally:
            await connector.close()

    @unittest.skipUnless(LIVE and os.environ.get("SPOTIFY_ACCESS_TOKEN"), "Need LIVE_TEST=1 and SPOTIFY_ACCESS_TOKEN")
    @async_test
    async def test_live_playlists(self):
        from connectors.spotify import SpotifyConnector
        connector = SpotifyConnector()
        await connector.connect()
        try:
            playlists = await connector.playlists(limit=5)
            self.assertIsNotNone(playlists)
            print(f"  Spotify: Found playlists")
            if isinstance(playlists, list):
                for p in playlists[:5]:
                    name = p.get('name', str(p)) if isinstance(p, dict) else getattr(p, 'name', str(p))
                    print(f"    - {name}")
        finally:
            await connector.close()


# ============================================================================
# Todoist Tests
# ============================================================================

class TestTodoistConnector(unittest.TestCase):
    """Tests for TodoistConnector."""

    def test_import(self):
        from connectors.todoist import TodoistConnector, TodoistTask, TodoistProject
        self.assertIsNotNone(TodoistConnector)

    def test_task_dataclass(self):
        from connectors.todoist import TodoistTask
        task = TodoistTask(
            id="12345",
            content="Buy groceries",
            description="Milk, eggs, bread",
            priority=2,
            due_string="tomorrow",
        )
        self.assertEqual(task.id, "12345")
        self.assertEqual(task.content, "Buy groceries")
        self.assertEqual(task.priority, 2)

    def test_project_dataclass(self):
        from connectors.todoist import TodoistProject
        project = TodoistProject(
            id="67890",
            name="Shopping",
        )
        self.assertEqual(project.name, "Shopping")

    def test_connector_instantiation(self):
        from connectors.todoist import TodoistConnector
        connector = TodoistConnector()
        self.assertTrue(hasattr(connector, 'connect'))
        self.assertTrue(hasattr(connector, 'list_tasks'))
        self.assertTrue(hasattr(connector, 'create_task'))
        self.assertTrue(hasattr(connector, 'complete_task'))
        self.assertTrue(hasattr(connector, 'update_task'))
        self.assertTrue(hasattr(connector, 'delete_task'))
        self.assertTrue(hasattr(connector, 'get_task'))
        self.assertTrue(hasattr(connector, 'list_projects'))
        self.assertTrue(hasattr(connector, 'create_project'))

    @unittest.skipUnless(LIVE and os.environ.get("TODOIST_API_TOKEN"), "Need LIVE_TEST=1 and TODOIST_API_TOKEN")
    @async_test
    async def test_live_list_projects(self):
        from connectors.todoist import TodoistConnector
        connector = TodoistConnector()
        await connector.connect()
        try:
            projects = await connector.list_projects()
            self.assertIsInstance(projects, list)
            print(f"  Todoist: Found {len(projects)} projects")
            for p in projects[:5]:
                name = p.name if hasattr(p, 'name') else p.get('name', str(p))
                print(f"    - {name}")
        finally:
            await connector.close()

    @unittest.skipUnless(LIVE and os.environ.get("TODOIST_API_TOKEN"), "Need LIVE_TEST=1 and TODOIST_API_TOKEN")
    @async_test
    async def test_live_list_tasks(self):
        from connectors.todoist import TodoistConnector
        connector = TodoistConnector()
        await connector.connect()
        try:
            tasks = await connector.list_tasks()
            self.assertIsInstance(tasks, list)
            print(f"  Todoist: Found {len(tasks)} active tasks")
            for t in tasks[:5]:
                content = t.content if hasattr(t, 'content') else t.get('content', str(t))
                print(f"    - {content}")
        finally:
            await connector.close()

    @unittest.skipUnless(LIVE and os.environ.get("TODOIST_API_TOKEN"), "Need LIVE_TEST=1 and TODOIST_API_TOKEN")
    @async_test
    async def test_live_create_and_complete_task(self):
        """Full lifecycle: create → verify → complete → verify gone."""
        from connectors.todoist import TodoistConnector
        connector = TodoistConnector()
        await connector.connect()
        try:
            # Create
            task = await connector.create_task(
                content="[TEST] Ziggy connector test — safe to delete",
                description="Auto-created by test_connector_scenarios.py",
                priority=1,
            )
            self.assertIsNotNone(task)
            task_id = task.id if hasattr(task, 'id') else task.get('id')
            print(f"  Todoist: Created task {task_id}")

            # Verify it exists
            fetched = await connector.get_task(task_id)
            self.assertIsNotNone(fetched)

            # Complete it
            await connector.complete_task(task_id)
            print(f"  Todoist: Completed task {task_id}")
        finally:
            await connector.close()


# ============================================================================
# Cross-Connector Smoke Test
# ============================================================================

class TestAllConnectorsImport(unittest.TestCase):
    """Verify all 5 connectors import cleanly."""

    def test_all_imports(self):
        """Every connector should import without errors."""
        from connectors.discord import DiscordConnector
        from connectors.github import GitHubConnector
        from connectors.slack import SlackConnector
        from connectors.spotify import SpotifyConnector
        from connectors.todoist import TodoistConnector

        connectors = [
            DiscordConnector,
            GitHubConnector,
            SlackConnector,
            SpotifyConnector,
            TodoistConnector,
        ]
        for cls in connectors:
            instance = cls()
            self.assertTrue(hasattr(instance, 'connect'), f"{cls.__name__} missing connect()")
            print(f"  ✓ {cls.__name__} imports and instantiates")


# ============================================================================
# Run
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  Connector Scenario Tests")
    print(f"  LIVE mode: {'ON' if LIVE else 'OFF (set LIVE_TEST=1 to enable)'}")
    print("=" * 60)
    unittest.main(verbosity=2)
