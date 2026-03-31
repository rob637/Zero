"""
Phase 5 E2E Tests - Universal Platform (DevTools)

Tests for GitHub, Jira, and unified DevTools integration.

Run with: python -m pytest test_devtools_e2e.py -v
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from connectors.github import (
    GitHubConnector, GitHubUser, GitHubRepo, GitHubIssue,
    GitHubPullRequest, GitHubNotification, IssueState as GHIssueState,
)
from connectors.jira import (
    JiraConnector, JiraUser, JiraProject, JiraIssue, JiraSprint,
)
from connectors.devtools import (
    UnifiedDevTools, GitHubAdapter, JiraAdapter,
    UnifiedUser, UnifiedProject, UnifiedIssue, UnifiedPullRequest,
    UnifiedNotification, IssueState, IssuePriority,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_github_user():
    """Sample GitHub user."""
    return GitHubUser(
        id=12345,
        login="testuser",
        name="Test User",
        email="test@example.com",
        avatar_url="https://github.com/testuser.png",
    )


@pytest.fixture
def mock_github_repo():
    """Sample GitHub repository."""
    return GitHubRepo(
        id=1001,
        name="test-repo",
        full_name="testuser/test-repo",
        owner="testuser",
        description="A test repository",
        private=False,
        fork=False,
        default_branch="main",
        html_url="https://github.com/testuser/test-repo",
        updated_at=datetime.now() - timedelta(hours=1),
        language="Python",
        stargazers_count=42,
        forks_count=7,
        open_issues_count=3,
    )


@pytest.fixture
def mock_github_issue():
    """Sample GitHub issue."""
    return GitHubIssue(
        id=2001,
        number=42,
        title="Fix login bug",
        body="Users cannot login with SSO",
        state=GHIssueState.OPEN,
        html_url="https://github.com/testuser/test-repo/issues/42",
        user=GitHubUser(id=1, login="reporter", name="Reporter"),
        assignees=[GitHubUser(id=12345, login="testuser", name="Test User")],
        labels=["bug", "high-priority"],
        created_at=datetime.now() - timedelta(days=2),
        updated_at=datetime.now() - timedelta(hours=6),
        closed_at=None,
        comments_count=3,
    )


@pytest.fixture
def mock_github_pr():
    """Sample GitHub pull request."""
    return GitHubPullRequest(
        id=3001,
        number=99,
        title="Add new feature",
        body="Implements the requested feature",
        state="open",
        html_url="https://github.com/testuser/test-repo/pull/99",
        user=GitHubUser(id=12345, login="testuser", name="Test User"),
        head_ref="feature-branch",
        base_ref="main",
        created_at=datetime.now() - timedelta(days=1),
        updated_at=datetime.now() - timedelta(hours=2),
        merged_at=None,
        draft=False,
    )


@pytest.fixture
def mock_github_notification():
    """Sample GitHub notification."""
    return GitHubNotification(
        id="notif-001",
        repository="testuser/test-repo",
        subject_title="Review requested",
        subject_type="PullRequest",
        subject_url="https://api.github.com/repos/testuser/test-repo/pulls/99",
        reason="review_requested",
        unread=True,
        updated_at=datetime.now() - timedelta(minutes=30),
    )


@pytest.fixture
def mock_jira_user():
    """Sample Jira user."""
    return JiraUser(
        account_id="abc123",
        display_name="Test User",
        email="test@example.com",
        avatar_url="https://jira.example.com/avatar/abc123",
        active=True,
    )


@pytest.fixture
def mock_jira_project():
    """Sample Jira project."""
    return JiraProject(
        id="10001",
        key="PROJ",
        name="Test Project",
        description="Our test project",
        lead=JiraUser(account_id="lead123", display_name="Project Lead"),
        project_type="software",
    )


@pytest.fixture
def mock_jira_issue():
    """Sample Jira issue."""
    return JiraIssue(
        id="10042",
        key="PROJ-123",
        summary="Implement user authentication",
        description="Add OAuth2 login support",
        status="In Progress",
        status_category="In Progress",
        issue_type="Story",
        priority="High",
        project_key="PROJ",
        assignee=JiraUser(account_id="abc123", display_name="Test User"),
        reporter=JiraUser(account_id="reporter456", display_name="Product Owner"),
        labels=["backend", "security"],
        components=["auth-service"],
        sprint="Sprint 5",
        story_points=8.0,
        created=datetime.now() - timedelta(days=5),
        updated=datetime.now() - timedelta(hours=2),
        due_date=datetime.now() + timedelta(days=3),
        html_url="https://jira.example.com/browse/PROJ-123",
    )


@pytest.fixture
def mock_jira_sprint():
    """Sample Jira sprint."""
    return JiraSprint(
        id=100,
        name="Sprint 5",
        state="active",
        start_date=datetime.now() - timedelta(days=7),
        end_date=datetime.now() + timedelta(days=7),
        goal="Complete auth feature",
        board_id=1,
    )


# ============================================================================
# GitHub Connector Tests
# ============================================================================

class TestGitHubConnector:
    """Tests for GitHub connector."""
    
    @pytest.mark.asyncio
    async def test_github_user_model(self, mock_github_user):
        """Test GitHubUser data model."""
        assert mock_github_user.login == "testuser"
        assert mock_github_user.id == 12345
        
        d = mock_github_user.to_dict()
        assert d["login"] == "testuser"
        assert d["email"] == "test@example.com"
    
    @pytest.mark.asyncio
    async def test_github_repo_model(self, mock_github_repo):
        """Test GitHubRepo data model."""
        assert mock_github_repo.full_name == "testuser/test-repo"
        assert mock_github_repo.stargazers_count == 42
        
        d = mock_github_repo.to_dict()
        assert d["name"] == "test-repo"
        assert d["language"] == "Python"
    
    @pytest.mark.asyncio
    async def test_github_issue_model(self, mock_github_issue):
        """Test GitHubIssue data model."""
        assert mock_github_issue.number == 42
        assert mock_github_issue.state == GHIssueState.OPEN
        assert "bug" in mock_github_issue.labels
        
        d = mock_github_issue.to_dict()
        assert d["title"] == "Fix login bug"
        assert "testuser" in d["assignees"]
    
    @pytest.mark.asyncio
    async def test_github_pr_model(self, mock_github_pr):
        """Test GitHubPullRequest data model."""
        assert mock_github_pr.number == 99
        assert mock_github_pr.head_ref == "feature-branch"
        assert not mock_github_pr.draft
        
        d = mock_github_pr.to_dict()
        assert d["head_ref"] == "feature-branch"
        assert d["base_ref"] == "main"
    
    @pytest.mark.asyncio
    async def test_github_notification_model(self, mock_github_notification):
        """Test GitHubNotification data model."""
        assert mock_github_notification.reason == "review_requested"
        assert mock_github_notification.unread
        
        d = mock_github_notification.to_dict()
        assert d["reason"] == "review_requested"
    
    @pytest.mark.asyncio
    async def test_github_connector_not_connected(self):
        """Test connector reports not connected without auth."""
        connector = GitHubConnector(token=None)
        assert not connector.is_connected
    
    @pytest.mark.asyncio
    async def test_github_activity_summary_structure(self, mock_github_user, mock_github_repo, mock_github_issue, mock_github_pr, mock_github_notification):
        """Test activity summary returns expected structure."""
        connector = GitHubConnector(token="test-token")
        
        # Mock the connector state and methods (match actual method names used by get_activity_summary)
        connector._connected = True
        connector._client = MagicMock()  # Needed for is_connected check
        connector._user = mock_github_user
        connector.list_notifications = AsyncMock(return_value=[mock_github_notification])
        connector.get_review_requests = AsyncMock(return_value=[mock_github_pr.to_dict()])
        connector.get_assigned_issues = AsyncMock(return_value=[mock_github_issue])
        connector.get_mentioned_issues = AsyncMock(return_value=[])
        
        summary = await connector.get_activity_summary()
        
        assert "timestamp" in summary
        assert summary["user"] == "testuser"
        assert len(summary["assigned_issues"]) == 1
        assert len(summary["notifications"]["items"]) == 1


# ============================================================================
# Jira Connector Tests
# ============================================================================

class TestJiraConnector:
    """Tests for Jira connector."""
    
    @pytest.mark.asyncio
    async def test_jira_user_model(self, mock_jira_user):
        """Test JiraUser data model."""
        assert mock_jira_user.display_name == "Test User"
        assert mock_jira_user.account_id == "abc123"
        
        d = mock_jira_user.to_dict()
        assert d["display_name"] == "Test User"
        assert d["active"] == True
    
    @pytest.mark.asyncio
    async def test_jira_project_model(self, mock_jira_project):
        """Test JiraProject data model."""
        assert mock_jira_project.key == "PROJ"
        assert mock_jira_project.name == "Test Project"
        
        d = mock_jira_project.to_dict()
        assert d["key"] == "PROJ"
        assert d["lead"] == "Project Lead"
    
    @pytest.mark.asyncio
    async def test_jira_issue_model(self, mock_jira_issue):
        """Test JiraIssue data model."""
        assert mock_jira_issue.key == "PROJ-123"
        assert mock_jira_issue.status == "In Progress"
        assert mock_jira_issue.story_points == 8.0
        assert "backend" in mock_jira_issue.labels
        
        d = mock_jira_issue.to_dict()
        assert d["key"] == "PROJ-123"
        assert d["sprint"] == "Sprint 5"
    
    @pytest.mark.asyncio
    async def test_jira_sprint_model(self, mock_jira_sprint):
        """Test JiraSprint data model."""
        assert mock_jira_sprint.name == "Sprint 5"
        assert mock_jira_sprint.state == "active"
        
        d = mock_jira_sprint.to_dict()
        assert d["name"] == "Sprint 5"
        assert d["goal"] == "Complete auth feature"
    
    @pytest.mark.asyncio
    async def test_jira_connector_not_connected(self):
        """Test connector reports not connected without auth."""
        connector = JiraConnector(url=None, email=None, api_token=None)
        assert not connector.is_connected
    
    @pytest.mark.asyncio
    async def test_jira_activity_summary_structure(self, mock_jira_user, mock_jira_issue):
        """Test activity summary returns expected structure."""
        connector = JiraConnector(url="https://test.atlassian.net", email="test@example.com", api_token="token")
        
        # Mock the connector state and methods
        connector._connected = True
        connector._user = mock_jira_user
        connector.get_my_in_progress = AsyncMock(return_value=[mock_jira_issue])
        connector.get_my_todo = AsyncMock(return_value=[])
        connector.get_recently_updated = AsyncMock(return_value=[mock_jira_issue])
        connector.search = AsyncMock(return_value=[])
        
        summary = await connector.get_activity_summary()
        
        assert "timestamp" in summary
        assert summary["user"] == "Test User"
        assert len(summary["in_progress"]) == 1
        assert summary["in_progress"][0]["key"] == "PROJ-123"


# ============================================================================
# Unified DevTools Tests
# ============================================================================

class TestUnifiedDevTools:
    """Tests for unified DevTools interface."""
    
    @pytest.mark.asyncio
    async def test_unified_user_model(self):
        """Test UnifiedUser data model."""
        user = UnifiedUser(
            id="123",
            name="Test User",
            email="test@example.com",
            provider="github",
        )
        
        assert user.name == "Test User"
        d = user.to_dict()
        assert d["provider"] == "github"
    
    @pytest.mark.asyncio
    async def test_unified_project_model(self):
        """Test UnifiedProject data model."""
        project = UnifiedProject(
            id="1001",
            name="test-repo",
            description="A test repo",
            provider="github",
            url="https://github.com/test/test-repo",
        )
        
        assert project.name == "test-repo"
        d = project.to_dict()
        assert d["provider"] == "github"
    
    @pytest.mark.asyncio
    async def test_unified_issue_model(self):
        """Test UnifiedIssue data model."""
        issue = UnifiedIssue(
            id="42",
            key="#42",
            title="Test issue",
            state=IssueState.OPEN,
            priority=IssuePriority.HIGH,
            provider="github",
        )
        
        assert issue.title == "Test issue"
        assert issue.state == IssueState.OPEN
        d = issue.to_dict()
        assert d["priority"] == "high"
    
    @pytest.mark.asyncio
    async def test_unified_pr_model(self):
        """Test UnifiedPullRequest data model."""
        pr = UnifiedPullRequest(
            id="99",
            number=99,
            title="Add feature",
            state="open",
            provider="github",
            source_branch="feature",
            target_branch="main",
        )
        
        assert pr.number == 99
        d = pr.to_dict()
        assert d["source_branch"] == "feature"
    
    @pytest.mark.asyncio
    async def test_unified_notification_model(self):
        """Test UnifiedNotification data model."""
        notif = UnifiedNotification(
            id="n001",
            title="Review requested",
            reason="review_requested",
            provider="github",
            unread=True,
        )
        
        assert notif.reason == "review_requested"
        d = notif.to_dict()
        assert d["unread"] == True
    
    @pytest.mark.asyncio
    async def test_add_providers(self):
        """Test adding providers to unified interface."""
        devtools = UnifiedDevTools()
        
        # Create mock connectors
        github_connector = MagicMock()
        github_connector.is_connected = True
        
        jira_connector = MagicMock()
        jira_connector.is_connected = True
        
        devtools.add_github(github_connector)
        devtools.add_jira(jira_connector)
        
        assert "github" in devtools.providers
        assert "jira" in devtools.providers
        assert len(devtools.providers) == 2
    
    @pytest.mark.asyncio
    async def test_github_adapter(self, mock_github_user, mock_github_issue):
        """Test GitHub adapter converts to unified format."""
        # Create mock GitHub connector
        connector = MagicMock()
        connector.is_connected = True
        connector.current_user = mock_github_user
        connector.get_assigned_issues = AsyncMock(return_value=[mock_github_issue])
        
        adapter = GitHubAdapter(connector)
        
        assert adapter.provider_name == "github"
        assert adapter.is_connected
        
        # Test user conversion
        user = await adapter.get_current_user()
        assert user.name == "testuser"
        assert user.provider == "github"
        
        # Test issue conversion
        issues = await adapter.get_my_issues()
        assert len(issues) == 1
        assert issues[0].key == "#42"
        assert issues[0].provider == "github"
    
    @pytest.mark.asyncio
    async def test_jira_adapter(self, mock_jira_user, mock_jira_issue):
        """Test Jira adapter converts to unified format."""
        # Create mock Jira connector
        connector = MagicMock()
        connector.is_connected = True
        connector.current_user = mock_jira_user
        connector.get_my_issues = AsyncMock(return_value=[mock_jira_issue])
        
        adapter = JiraAdapter(connector)
        
        assert adapter.provider_name == "jira"
        assert adapter.is_connected
        
        # Test user conversion
        user = await adapter.get_current_user()
        assert user.name == "Test User"
        assert user.provider == "jira"
        
        # Test issue conversion
        issues = await adapter.get_my_issues()
        assert len(issues) == 1
        assert issues[0].key == "PROJ-123"
        assert issues[0].state == IssueState.IN_PROGRESS
        assert issues[0].provider == "jira"
    
    @pytest.mark.asyncio
    async def test_get_all_issues_across_providers(self, mock_github_issue, mock_jira_issue):
        """Test aggregating issues from multiple providers."""
        devtools = UnifiedDevTools()
        
        # Mock GitHub adapter
        github_connector = MagicMock()
        github_connector.is_connected = True
        github_connector.current_user = GitHubUser(id=1, login="user", name="User")
        github_connector.get_assigned_issues = AsyncMock(return_value=[mock_github_issue])
        devtools.add_github(github_connector)
        
        # Mock Jira adapter
        jira_connector = MagicMock()
        jira_connector.is_connected = True
        jira_connector.current_user = JiraUser(account_id="123", display_name="User")
        jira_connector.get_my_issues = AsyncMock(return_value=[mock_jira_issue])
        devtools.add_jira(jira_connector)
        
        # Get all issues
        issues = await devtools.get_all_issues()
        
        assert len(issues) == 2
        providers = {i.provider for i in issues}
        assert "github" in providers
        assert "jira" in providers
    
    @pytest.mark.asyncio
    async def test_work_summary(self, mock_github_user, mock_github_issue, mock_github_pr, mock_github_notification, mock_jira_user, mock_jira_issue):
        """Test work summary aggregation."""
        devtools = UnifiedDevTools()
        
        # Mock GitHub
        github_connector = MagicMock()
        github_connector.is_connected = True
        github_connector.current_user = mock_github_user
        github_connector.get_assigned_issues = AsyncMock(return_value=[mock_github_issue])
        github_connector.get_created_prs = AsyncMock(return_value=[mock_github_pr])
        github_connector.get_review_requests = AsyncMock(return_value=[mock_github_pr])
        github_connector.get_notifications = AsyncMock(return_value=[mock_github_notification])
        github_connector.list_repos = AsyncMock(return_value=[])
        devtools.add_github(github_connector)
        
        # Mock Jira
        jira_connector = MagicMock()
        jira_connector.is_connected = True
        jira_connector.current_user = mock_jira_user
        jira_connector.get_my_issues = AsyncMock(return_value=[mock_jira_issue])
        jira_connector.get_my_in_progress = AsyncMock(return_value=[mock_jira_issue])
        jira_connector.get_my_todo = AsyncMock(return_value=[])
        jira_connector.get_recently_updated = AsyncMock(return_value=[mock_jira_issue])
        devtools.add_jira(jira_connector)
        
        summary = await devtools.get_work_summary()
        
        assert "timestamp" in summary
        assert "github" in summary["providers"]
        assert "jira" in summary["providers"]
        assert "in_progress" in summary
        assert "review_requests" in summary
        assert "notifications" in summary
        assert "by_provider" in summary
    
    @pytest.mark.asyncio
    async def test_issue_state_mapping(self):
        """Test issue state enum values."""
        assert IssueState.OPEN.value == "open"
        assert IssueState.IN_PROGRESS.value == "in_progress"
        assert IssueState.CLOSED.value == "closed"
    
    @pytest.mark.asyncio
    async def test_issue_priority_mapping(self):
        """Test issue priority enum values."""
        assert IssuePriority.LOWEST.value == "lowest"
        assert IssuePriority.LOW.value == "low"
        assert IssuePriority.MEDIUM.value == "medium"
        assert IssuePriority.HIGH.value == "high"
        assert IssuePriority.HIGHEST.value == "highest"
    
    @pytest.mark.asyncio
    async def test_poll_for_proactive_monitor(self, mock_github_user, mock_jira_user):
        """Test poll method for ProactiveMonitor compatibility."""
        devtools = UnifiedDevTools()
        
        # Minimal mocks
        github_connector = MagicMock()
        github_connector.is_connected = True
        github_connector.current_user = mock_github_user
        github_connector.get_assigned_issues = AsyncMock(return_value=[])
        github_connector.get_created_prs = AsyncMock(return_value=[])
        github_connector.get_review_requests = AsyncMock(return_value=[])
        github_connector.get_notifications = AsyncMock(return_value=[])
        github_connector.list_repos = AsyncMock(return_value=[])
        devtools.add_github(github_connector)
        
        jira_connector = MagicMock()
        jira_connector.is_connected = True
        jira_connector.current_user = mock_jira_user
        jira_connector.get_my_issues = AsyncMock(return_value=[])
        jira_connector.get_my_in_progress = AsyncMock(return_value=[])
        jira_connector.get_my_todo = AsyncMock(return_value=[])
        jira_connector.get_recently_updated = AsyncMock(return_value=[])
        devtools.add_jira(jira_connector)
        
        # poll() should work for ProactiveMonitor
        result = await devtools.poll()
        assert "timestamp" in result
        assert "providers" in result


# ============================================================================
# Integration Tests
# ============================================================================

class TestDevToolsIntegration:
    """Integration tests for the DevTools system."""
    
    @pytest.mark.asyncio
    async def test_filter_issues_by_state(self, mock_github_issue, mock_jira_issue):
        """Test filtering issues by state."""
        devtools = UnifiedDevTools()
        
        # Create mock that returns both open and in-progress issues
        open_github_issue = GitHubIssue(
            id=1, number=1, title="Open issue", state=GHIssueState.OPEN,
            html_url="https://github.com/test/repo/issues/1",
        )
        
        github_connector = MagicMock()
        github_connector.is_connected = True
        github_connector.current_user = GitHubUser(id=1, login="user", name="User")
        github_connector.get_assigned_issues = AsyncMock(return_value=[open_github_issue])
        devtools.add_github(github_connector)
        
        # Filter by OPEN state
        open_issues = await devtools.get_all_issues(state=IssueState.OPEN)
        assert all(i.state == IssueState.OPEN for i in open_issues)
    
    @pytest.mark.asyncio
    async def test_filter_by_provider(self, mock_github_issue, mock_jira_issue):
        """Test filtering by specific providers."""
        devtools = UnifiedDevTools()
        
        github_connector = MagicMock()
        github_connector.is_connected = True
        github_connector.current_user = GitHubUser(id=1, login="user", name="User")
        github_connector.get_assigned_issues = AsyncMock(return_value=[mock_github_issue])
        devtools.add_github(github_connector)
        
        jira_connector = MagicMock()
        jira_connector.is_connected = True  
        jira_connector.current_user = JiraUser(account_id="123", display_name="User")
        jira_connector.get_my_issues = AsyncMock(return_value=[mock_jira_issue])
        devtools.add_jira(jira_connector)
        
        # Filter to GitHub only
        github_issues = await devtools.get_all_issues(providers=["github"])
        assert all(i.provider == "github" for i in github_issues)
        
        # Filter to Jira only
        jira_issues = await devtools.get_all_issues(providers=["jira"])
        assert all(i.provider == "jira" for i in jira_issues)
    
    @pytest.mark.asyncio
    async def test_handle_provider_error_gracefully(self):
        """Test that errors from one provider don't break others."""
        devtools = UnifiedDevTools()
        
        # GitHub that works
        github_connector = MagicMock()
        github_connector.is_connected = True
        github_connector.current_user = GitHubUser(id=1, login="user", name="User")
        github_connector.get_assigned_issues = AsyncMock(return_value=[
            GitHubIssue(id=1, number=1, title="Working issue", state=GHIssueState.OPEN,
                       html_url="https://github.com/test/repo/issues/1")
        ])
        devtools.add_github(github_connector)
        
        # Jira that throws errors
        jira_connector = MagicMock()
        jira_connector.is_connected = True
        jira_connector.current_user = JiraUser(account_id="123", display_name="User")
        jira_connector.get_my_issues = AsyncMock(side_effect=Exception("Jira API error"))
        devtools.add_jira(jira_connector)
        
        # Should still return GitHub issues despite Jira error
        issues = await devtools.get_all_issues()
        assert len(issues) == 1
        assert issues[0].provider == "github"
    
    @pytest.mark.asyncio
    async def test_empty_providers(self):
        """Test behavior with no providers added."""
        devtools = UnifiedDevTools()
        
        assert devtools.providers == []
        
        issues = await devtools.get_all_issues()
        assert issues == []
        
        notifications = await devtools.get_all_notifications()
        assert notifications == []


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
