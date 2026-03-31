"""
Unified DevTools - Provider-Agnostic Development Tool Interface

This module provides a unified interface for development/collaboration tools
including code repositories, issue trackers, and project management systems.

Supported Providers:
- GitHub (repos, issues, PRs, notifications)
- Jira (projects, issues, sprints)

The unified interface enables Telic to:
- Cross-reference GitHub PRs with Jira issues
- Track work across both systems
- Provide unified work summaries
- Generate standup reports
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


# ============================================================================
# Unified Data Models
# ============================================================================

class IssueState(Enum):
    """Unified issue state."""
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"


class IssuePriority(Enum):
    """Unified issue priority."""
    LOWEST = "lowest"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    HIGHEST = "highest"


@dataclass
class UnifiedUser:
    """Unified user representation."""
    id: str
    name: str
    email: Optional[str] = None
    provider: str = ""
    avatar_url: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "provider": self.provider,
        }


@dataclass
class UnifiedProject:
    """Unified project/repository representation."""
    id: str
    name: str
    description: Optional[str] = None
    provider: str = ""
    url: Optional[str] = None
    owner: Optional[str] = None
    is_private: bool = False
    metadata: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "provider": self.provider,
            "url": self.url,
            "owner": self.owner,
            "is_private": self.is_private,
        }


@dataclass
class UnifiedIssue:
    """Unified issue/ticket representation."""
    id: str
    key: str  # Short identifier (e.g., "PROJ-123" or "#456")
    title: str
    description: Optional[str] = None
    state: IssueState = IssueState.OPEN
    priority: Optional[IssuePriority] = None
    provider: str = ""
    project: Optional[str] = None
    assignee: Optional[UnifiedUser] = None
    reporter: Optional[UnifiedUser] = None
    labels: List[str] = field(default_factory=list)
    created: Optional[datetime] = None
    updated: Optional[datetime] = None
    due_date: Optional[datetime] = None
    url: Optional[str] = None
    metadata: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "key": self.key,
            "title": self.title,
            "state": self.state.value,
            "priority": self.priority.value if self.priority else None,
            "provider": self.provider,
            "project": self.project,
            "assignee": self.assignee.name if self.assignee else None,
            "labels": self.labels,
            "created": self.created.isoformat() if self.created else None,
            "updated": self.updated.isoformat() if self.updated else None,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "url": self.url,
        }


@dataclass
class UnifiedPullRequest:
    """Unified pull/merge request representation."""
    id: str
    number: int
    title: str
    description: Optional[str] = None
    state: str = "open"  # open, closed, merged
    provider: str = ""
    project: Optional[str] = None
    author: Optional[UnifiedUser] = None
    source_branch: Optional[str] = None
    target_branch: Optional[str] = None
    created: Optional[datetime] = None
    updated: Optional[datetime] = None
    merged: Optional[datetime] = None
    url: Optional[str] = None
    review_status: Optional[str] = None  # pending, approved, changes_requested
    metadata: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "number": self.number,
            "title": self.title,
            "state": self.state,
            "provider": self.provider,
            "project": self.project,
            "author": self.author.name if self.author else None,
            "source_branch": self.source_branch,
            "target_branch": self.target_branch,
            "created": self.created.isoformat() if self.created else None,
            "url": self.url,
            "review_status": self.review_status,
        }


@dataclass
class UnifiedNotification:
    """Unified notification/activity representation."""
    id: str
    title: str
    reason: str  # assigned, mentioned, review_requested, etc.
    provider: str = ""
    unread: bool = True
    url: Optional[str] = None
    timestamp: Optional[datetime] = None
    subject_type: Optional[str] = None  # issue, pull_request, etc.
    subject_id: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "title": self.title,
            "reason": self.reason,
            "provider": self.provider,
            "unread": self.unread,
            "url": self.url,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


# ============================================================================
# Provider Adapters
# ============================================================================

class DevToolsAdapter(ABC):
    """Abstract base class for development tool adapters."""
    
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider name (e.g., 'github', 'jira')."""
        pass
    
    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if connected to the service."""
        pass
    
    @abstractmethod
    async def get_current_user(self) -> UnifiedUser:
        """Get the authenticated user."""
        pass
    
    @abstractmethod
    async def list_projects(self, max_results: int = 50) -> List[UnifiedProject]:
        """List projects/repositories."""
        pass
    
    @abstractmethod
    async def get_my_issues(self, state: IssueState = None) -> List[UnifiedIssue]:
        """Get issues assigned to the current user."""
        pass
    
    @abstractmethod
    async def get_notifications(self, unread_only: bool = True) -> List[UnifiedNotification]:
        """Get notifications/activity."""
        pass


class GitHubAdapter(DevToolsAdapter):
    """Adapter for GitHub connector."""
    
    def __init__(self, connector):
        from .github import GitHubConnector
        self._connector: GitHubConnector = connector
    
    @property
    def provider_name(self) -> str:
        return "github"
    
    @property
    def is_connected(self) -> bool:
        return self._connector.is_connected
    
    async def get_current_user(self) -> UnifiedUser:
        user = self._connector.current_user
        return UnifiedUser(
            id=str(user.id),
            name=user.login,
            email=user.email,
            provider="github",
            avatar_url=user.avatar_url,
        )
    
    async def list_projects(self, max_results: int = 50) -> List[UnifiedProject]:
        repos = await self._connector.list_repos(per_page=max_results)
        return [
            UnifiedProject(
                id=str(r.id),
                name=r.full_name,
                description=r.description,
                provider="github",
                url=r.html_url,
                owner=r.owner,
                is_private=r.private,
            )
            for r in repos
        ]
    
    async def get_my_issues(self, state: IssueState = None) -> List[UnifiedIssue]:
        from .github import IssueState as GHIssueState
        gh_state = "open" if state == IssueState.OPEN else "all" if state is None else "closed"
        issues = await self._connector.get_assigned_issues(state=gh_state)
        
        results = []
        for i in issues:
            unified_state = IssueState.CLOSED if i.state == GHIssueState.CLOSED else IssueState.OPEN
            # Get first assignee if any
            assignee = i.assignees[0] if i.assignees else None
            results.append(UnifiedIssue(
                id=str(i.id),
                key=f"#{i.number}",
                title=i.title,
                description=i.body,
                state=unified_state,
                provider="github",
                project=None,  # GitHub issues don't carry repo info directly
                assignee=UnifiedUser(
                    id=str(assignee.id), name=assignee.login, provider="github"
                ) if assignee else None,
                labels=i.labels,
                created=i.created_at,
                updated=i.updated_at,
                url=i.html_url,
            ))
        return results
    
    async def get_my_pull_requests(self) -> List[UnifiedPullRequest]:
        prs = await self._connector.get_created_prs()
        results = []
        for pr in prs:
            state = "merged" if pr.merged else pr.state
            results.append(UnifiedPullRequest(
                id=str(pr.id),
                number=pr.number,
                title=pr.title,
                description=pr.body,
                state=state,
                provider="github",
                project=None,  # GitHub PRs don't carry repo info directly
                author=UnifiedUser(
                    id=str(pr.user.id), name=pr.user.login, provider="github"
                ) if pr.user else None,
                source_branch=pr.head_ref,
                target_branch=pr.base_ref,
                created=pr.created_at,
                updated=pr.updated_at,
                merged=pr.merged_at,
                url=pr.html_url,
            ))
        return results
    
    async def get_review_requests(self) -> List[UnifiedPullRequest]:
        prs = await self._connector.get_review_requests()
        results = []
        for pr in prs:
            results.append(UnifiedPullRequest(
                id=str(pr.id),
                number=pr.number,
                title=pr.title,
                state=pr.state,
                provider="github",
                project=None,  # GitHub PRs don't carry repo info directly
                author=UnifiedUser(
                    id=str(pr.user.id), name=pr.user.login, provider="github"
                ) if pr.user else None,
                url=pr.html_url,
                review_status="pending",
            ))
        return results
    
    async def get_notifications(self, unread_only: bool = True) -> List[UnifiedNotification]:
        notifications = await self._connector.get_notifications(all_notifications=not unread_only)
        return [
            UnifiedNotification(
                id=n.id,
                title=n.subject_title,
                reason=n.reason,
                provider="github",
                unread=n.unread,
                url=n.subject_url,
                timestamp=n.updated_at,
                subject_type=n.subject_type,
            )
            for n in notifications
        ]


class JiraAdapter(DevToolsAdapter):
    """Adapter for Jira connector."""
    
    def __init__(self, connector):
        from .jira import JiraConnector
        self._connector: JiraConnector = connector
    
    @property
    def provider_name(self) -> str:
        return "jira"
    
    @property
    def is_connected(self) -> bool:
        return self._connector.is_connected
    
    async def get_current_user(self) -> UnifiedUser:
        user = self._connector.current_user
        return UnifiedUser(
            id=user.account_id,
            name=user.display_name,
            email=user.email,
            provider="jira",
            avatar_url=user.avatar_url,
        )
    
    async def list_projects(self, max_results: int = 50) -> List[UnifiedProject]:
        projects = await self._connector.list_projects(max_results=max_results)
        return [
            UnifiedProject(
                id=p.id,
                name=f"{p.key} - {p.name}",
                description=p.description,
                provider="jira",
                url=f"{self._connector.base_url}/browse/{p.key}",
                owner=p.lead.display_name if p.lead else None,
                metadata={"key": p.key, "project_type": p.project_type},
            )
            for p in projects
        ]
    
    async def get_my_issues(self, state: IssueState = None) -> List[UnifiedIssue]:
        if state == IssueState.OPEN:
            issues = await self._connector.get_my_todo()
        elif state == IssueState.IN_PROGRESS:
            issues = await self._connector.get_my_in_progress()
        elif state == IssueState.CLOSED:
            issues = await self._connector.search(
                "assignee = currentUser() AND statusCategory = Done ORDER BY updated DESC",
                max_results=50
            )
        else:
            issues = await self._connector.get_my_issues()
        
        return [self._convert_issue(i) for i in issues]
    
    def _convert_issue(self, issue) -> UnifiedIssue:
        """Convert Jira issue to unified format."""
        # Map status category to unified state
        status_map = {
            "To Do": IssueState.OPEN,
            "In Progress": IssueState.IN_PROGRESS,
            "Done": IssueState.CLOSED,
        }
        state = status_map.get(issue.status_category, IssueState.OPEN)
        
        # Map priority
        priority_map = {
            "Lowest": IssuePriority.LOWEST,
            "Low": IssuePriority.LOW,
            "Medium": IssuePriority.MEDIUM,
            "High": IssuePriority.HIGH,
            "Highest": IssuePriority.HIGHEST,
        }
        priority = priority_map.get(issue.priority)
        
        return UnifiedIssue(
            id=issue.id,
            key=issue.key,
            title=issue.summary,
            description=issue.description,
            state=state,
            priority=priority,
            provider="jira",
            project=issue.project_key,
            assignee=UnifiedUser(
                id=issue.assignee.account_id,
                name=issue.assignee.display_name,
                provider="jira"
            ) if issue.assignee else None,
            reporter=UnifiedUser(
                id=issue.reporter.account_id,
                name=issue.reporter.display_name,
                provider="jira"
            ) if issue.reporter else None,
            labels=issue.labels,
            created=issue.created,
            updated=issue.updated,
            due_date=issue.due_date,
            url=issue.html_url,
            metadata={
                "issue_type": issue.issue_type,
                "sprint": issue.sprint,
                "story_points": issue.story_points,
                "status": issue.status,
            },
        )
    
    async def get_notifications(self, unread_only: bool = True) -> List[UnifiedNotification]:
        # Jira doesn't have a direct notifications API like GitHub
        # We simulate by getting recently updated issues assigned to user
        issues = await self._connector.get_recently_updated(days=1)
        return [
            UnifiedNotification(
                id=f"jira-updated-{i.key}",
                title=f"{i.key}: {i.summary}",
                reason="updated",
                provider="jira",
                unread=True,
                url=i.html_url,
                timestamp=i.updated,
                subject_type="issue",
                subject_id=i.key,
            )
            for i in issues
        ]


# ============================================================================
# Unified DevTools Manager
# ============================================================================

class UnifiedDevTools:
    """
    Unified interface for development tools.
    
    Provides a single interface to interact with multiple
    development tools (GitHub, Jira, etc.).
    
    Usage:
        devtools = UnifiedDevTools()
        devtools.add_github(github_connector)
        devtools.add_jira(jira_connector)
        
        # Get all issues across providers
        all_issues = await devtools.get_all_issues()
        
        # Get work summary
        summary = await devtools.get_work_summary()
    """
    
    def __init__(self):
        self._adapters: Dict[str, DevToolsAdapter] = {}
    
    def add_adapter(self, adapter: DevToolsAdapter):
        """Add a provider adapter."""
        self._adapters[adapter.provider_name] = adapter
    
    def add_github(self, connector):
        """Add GitHub connector."""
        self.add_adapter(GitHubAdapter(connector))
    
    def add_jira(self, connector):
        """Add Jira connector."""
        self.add_adapter(JiraAdapter(connector))
    
    @property
    def providers(self) -> List[str]:
        """List of connected provider names."""
        return list(self._adapters.keys())
    
    def get_adapter(self, provider: str) -> Optional[DevToolsAdapter]:
        """Get adapter for a specific provider."""
        return self._adapters.get(provider)
    
    # === Unified Operations ===
    
    async def get_all_issues(
        self,
        state: IssueState = None,
        providers: List[str] = None,
    ) -> List[UnifiedIssue]:
        """Get issues from all providers."""
        adapters = self._get_adapters(providers)
        
        tasks = [adapter.get_my_issues(state) for adapter in adapters]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        all_issues = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Error getting issues from {adapters[i].provider_name}: {result}")
            else:
                all_issues.extend(result)
        
        # Sort by updated date
        all_issues.sort(key=lambda x: x.updated or datetime.min, reverse=True)
        return all_issues
    
    async def get_all_notifications(
        self,
        unread_only: bool = True,
        providers: List[str] = None,
    ) -> List[UnifiedNotification]:
        """Get notifications from all providers."""
        adapters = self._get_adapters(providers)
        
        tasks = [adapter.get_notifications(unread_only) for adapter in adapters]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        all_notifications = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Error getting notifications from {adapters[i].provider_name}: {result}")
            else:
                all_notifications.extend(result)
        
        # Sort by timestamp
        all_notifications.sort(key=lambda x: x.timestamp or datetime.min, reverse=True)
        return all_notifications
    
    async def get_all_projects(
        self,
        providers: List[str] = None,
    ) -> List[UnifiedProject]:
        """Get projects/repos from all providers."""
        adapters = self._get_adapters(providers)
        
        tasks = [adapter.list_projects() for adapter in adapters]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        all_projects = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Error getting projects from {adapters[i].provider_name}: {result}")
            else:
                all_projects.extend(result)
        
        return all_projects
    
    async def get_work_summary(self) -> Dict:
        """
        Get a comprehensive work summary across all providers.
        
        Useful for standup preparation and proactive monitoring.
        """
        summary = {
            "timestamp": datetime.now().isoformat(),
            "providers": self.providers,
            "in_progress": [],
            "todo": [],
            "review_requests": [],
            "notifications": [],
            "by_provider": {},
        }
        
        # Get issues by state
        in_progress = await self.get_all_issues(state=IssueState.IN_PROGRESS)
        summary["in_progress"] = [i.to_dict() for i in in_progress[:10]]
        
        todo = await self.get_all_issues(state=IssueState.OPEN)
        summary["todo"] = [i.to_dict() for i in todo[:10]]
        
        # GitHub-specific: review requests
        if "github" in self._adapters:
            gh_adapter = self._adapters["github"]
            if isinstance(gh_adapter, GitHubAdapter):
                try:
                    reviews = await gh_adapter.get_review_requests()
                    summary["review_requests"] = [r.to_dict() for r in reviews[:10]]
                except Exception as e:
                    logger.error(f"Error getting review requests: {e}")
        
        # Notifications
        notifications = await self.get_all_notifications(unread_only=True)
        summary["notifications"] = [n.to_dict() for n in notifications[:20]]
        
        # Per-provider breakdown
        for provider, adapter in self._adapters.items():
            try:
                issues = await adapter.get_my_issues()
                summary["by_provider"][provider] = {
                    "total_issues": len(issues),
                    "in_progress": len([i for i in issues if i.state == IssueState.IN_PROGRESS]),
                    "open": len([i for i in issues if i.state == IssueState.OPEN]),
                }
            except Exception as e:
                logger.error(f"Error getting summary for {provider}: {e}")
                summary["by_provider"][provider] = {"error": str(e)}
        
        return summary
    
    async def find_linked_work(
        self,
        query: str,
    ) -> Dict[str, List[Union[UnifiedIssue, UnifiedPullRequest]]]:
        """
        Find related work items across providers.
        
        Useful for cross-referencing GitHub PRs with Jira tickets.
        E.g., finding all GitHub PRs that mention "PROJ-123"
        """
        results = {
            "github_issues": [],
            "github_prs": [],
            "jira_issues": [],
        }
        
        # Search GitHub
        if "github" in self._adapters:
            gh = self._adapters["github"]
            if isinstance(gh, GitHubAdapter):
                try:
                    # Search for issues/PRs mentioning the query
                    issues = await gh._connector.search_issues(query)
                    for i in issues:
                        if "/pull/" in (i.html_url or ""):
                            results["github_prs"].append(i.to_dict())
                        else:
                            results["github_issues"].append(i.to_dict())
                except Exception as e:
                    logger.error(f"Error searching GitHub: {e}")
        
        # Search Jira
        if "jira" in self._adapters:
            jira = self._adapters["jira"]
            if isinstance(jira, JiraAdapter):
                try:
                    issues = await jira._connector.search(
                        f'text ~ "{query}" ORDER BY updated DESC',
                        max_results=20
                    )
                    results["jira_issues"] = [jira._convert_issue(i).to_dict() for i in issues]
                except Exception as e:
                    logger.error(f"Error searching Jira: {e}")
        
        return results
    
    def _get_adapters(self, providers: List[str] = None) -> List[DevToolsAdapter]:
        """Get adapters, optionally filtered by provider names."""
        if providers:
            return [self._adapters[p] for p in providers if p in self._adapters]
        return list(self._adapters.values())
    
    # === Polling for ProactiveMonitor ===
    
    async def get_recent(self) -> Dict:
        """Get recent activity for proactive monitoring."""
        return await self.get_work_summary()
    
    async def poll(self) -> Dict:
        """Alias for get_recent (ProactiveMonitor compatibility)."""
        return await self.get_recent()


# ============================================================================
# Factory Function
# ============================================================================

def create_unified_devtools() -> UnifiedDevTools:
    """Create a new UnifiedDevTools instance."""
    return UnifiedDevTools()
