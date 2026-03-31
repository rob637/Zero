"""
GitHub Connector - Development Tools Integration

Provides access to GitHub repositories, issues, pull requests,
and notifications for proactive development assistance.

Uses GitHub's REST API with OAuth token authentication.

Capabilities:
- Repository information and activity
- Issue management (list, create, update, close)
- Pull request management (list, create, review status)
- Notifications and mentions
- Code search
- Commit and branch information

This enables Apex to:
- Alert when PRs need review
- Track issue assignments
- Monitor CI/CD status
- Surface important notifications
- Cross-reference with calendar (standup prep, sprint planning)
"""

import asyncio
import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import json

import httpx

logger = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================

class IssueState(Enum):
    """GitHub issue state."""
    OPEN = "open"
    CLOSED = "closed"
    ALL = "all"


class PRState(Enum):
    """GitHub pull request state."""
    OPEN = "open"
    CLOSED = "closed"
    MERGED = "merged"
    ALL = "all"


class NotificationType(Enum):
    """GitHub notification types."""
    ISSUE = "Issue"
    PULL_REQUEST = "PullRequest"
    RELEASE = "Release"
    DISCUSSION = "Discussion"
    COMMIT = "Commit"
    REPOSITORY_VULNERABILITY_ALERT = "RepositoryVulnerabilityAlert"


@dataclass
class GitHubUser:
    """GitHub user information."""
    id: int
    login: str
    name: Optional[str] = None
    email: Optional[str] = None
    avatar_url: Optional[str] = None
    html_url: Optional[str] = None
    
    @classmethod
    def from_api(cls, data: Dict) -> "GitHubUser":
        return cls(
            id=data.get("id", 0),
            login=data.get("login", ""),
            name=data.get("name"),
            email=data.get("email"),
            avatar_url=data.get("avatar_url"),
            html_url=data.get("html_url"),
        )
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "login": self.login,
            "name": self.name,
            "email": self.email,
            "avatar_url": self.avatar_url,
            "html_url": self.html_url,
        }


@dataclass
class GitHubRepo:
    """GitHub repository information."""
    id: int
    name: str
    full_name: str
    owner: str
    description: Optional[str] = None
    html_url: Optional[str] = None
    private: bool = False
    fork: bool = False
    default_branch: str = "main"
    open_issues_count: int = 0
    stargazers_count: int = 0
    forks_count: int = 0
    language: Optional[str] = None
    updated_at: Optional[datetime] = None
    
    @classmethod
    def from_api(cls, data: Dict) -> "GitHubRepo":
        updated = data.get("updated_at")
        if updated and isinstance(updated, str):
            try:
                updated = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            except:
                updated = None
        
        return cls(
            id=data.get("id", 0),
            name=data.get("name", ""),
            full_name=data.get("full_name", ""),
            owner=data.get("owner", {}).get("login", ""),
            description=data.get("description"),
            html_url=data.get("html_url"),
            private=data.get("private", False),
            fork=data.get("fork", False),
            default_branch=data.get("default_branch", "main"),
            open_issues_count=data.get("open_issues_count", 0),
            stargazers_count=data.get("stargazers_count", 0),
            forks_count=data.get("forks_count", 0),
            language=data.get("language"),
            updated_at=updated,
        )
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "full_name": self.full_name,
            "owner": self.owner,
            "description": self.description,
            "html_url": self.html_url,
            "private": self.private,
            "default_branch": self.default_branch,
            "open_issues_count": self.open_issues_count,
            "language": self.language,
        }


@dataclass
class GitHubIssue:
    """GitHub issue information."""
    id: int
    number: int
    title: str
    state: IssueState
    body: Optional[str] = None
    html_url: Optional[str] = None
    user: Optional[GitHubUser] = None
    assignees: List[GitHubUser] = field(default_factory=list)
    labels: List[str] = field(default_factory=list)
    milestone: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    comments_count: int = 0
    is_pull_request: bool = False
    
    @classmethod
    def from_api(cls, data: Dict) -> "GitHubIssue":
        def parse_dt(s):
            if s and isinstance(s, str):
                try:
                    return datetime.fromisoformat(s.replace("Z", "+00:00"))
                except:
                    pass
            return None
        
        return cls(
            id=data.get("id", 0),
            number=data.get("number", 0),
            title=data.get("title", ""),
            state=IssueState(data.get("state", "open")),
            body=data.get("body"),
            html_url=data.get("html_url"),
            user=GitHubUser.from_api(data["user"]) if data.get("user") else None,
            assignees=[GitHubUser.from_api(a) for a in data.get("assignees", [])],
            labels=[l.get("name", "") for l in data.get("labels", [])],
            milestone=data.get("milestone", {}).get("title") if data.get("milestone") else None,
            created_at=parse_dt(data.get("created_at")),
            updated_at=parse_dt(data.get("updated_at")),
            closed_at=parse_dt(data.get("closed_at")),
            comments_count=data.get("comments", 0),
            is_pull_request="pull_request" in data,
        )
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "number": self.number,
            "title": self.title,
            "state": self.state.value,
            "html_url": self.html_url,
            "user": self.user.login if self.user else None,
            "assignees": [a.login for a in self.assignees],
            "labels": self.labels,
            "milestone": self.milestone,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "comments_count": self.comments_count,
            "is_pull_request": self.is_pull_request,
        }


@dataclass
class GitHubPullRequest:
    """GitHub pull request information."""
    id: int
    number: int
    title: str
    state: str  # open, closed
    merged: bool = False
    draft: bool = False
    body: Optional[str] = None
    html_url: Optional[str] = None
    user: Optional[GitHubUser] = None
    head_ref: Optional[str] = None  # Source branch
    base_ref: Optional[str] = None  # Target branch
    assignees: List[GitHubUser] = field(default_factory=list)
    reviewers: List[GitHubUser] = field(default_factory=list)
    labels: List[str] = field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    merged_at: Optional[datetime] = None
    mergeable: Optional[bool] = None
    additions: int = 0
    deletions: int = 0
    changed_files: int = 0
    comments_count: int = 0
    review_comments_count: int = 0
    
    @classmethod
    def from_api(cls, data: Dict) -> "GitHubPullRequest":
        def parse_dt(s):
            if s and isinstance(s, str):
                try:
                    return datetime.fromisoformat(s.replace("Z", "+00:00"))
                except:
                    pass
            return None
        
        return cls(
            id=data.get("id", 0),
            number=data.get("number", 0),
            title=data.get("title", ""),
            state=data.get("state", "open"),
            merged=data.get("merged", False),
            draft=data.get("draft", False),
            body=data.get("body"),
            html_url=data.get("html_url"),
            user=GitHubUser.from_api(data["user"]) if data.get("user") else None,
            head_ref=data.get("head", {}).get("ref"),
            base_ref=data.get("base", {}).get("ref"),
            assignees=[GitHubUser.from_api(a) for a in data.get("assignees", [])],
            reviewers=[GitHubUser.from_api(r.get("user", {})) for r in data.get("requested_reviewers", []) if r.get("user")],
            labels=[l.get("name", "") for l in data.get("labels", [])],
            created_at=parse_dt(data.get("created_at")),
            updated_at=parse_dt(data.get("updated_at")),
            merged_at=parse_dt(data.get("merged_at")),
            mergeable=data.get("mergeable"),
            additions=data.get("additions", 0),
            deletions=data.get("deletions", 0),
            changed_files=data.get("changed_files", 0),
            comments_count=data.get("comments", 0),
            review_comments_count=data.get("review_comments", 0),
        )
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "number": self.number,
            "title": self.title,
            "state": self.state,
            "merged": self.merged,
            "draft": self.draft,
            "html_url": self.html_url,
            "user": self.user.login if self.user else None,
            "head_ref": self.head_ref,
            "base_ref": self.base_ref,
            "assignees": [a.login for a in self.assignees],
            "reviewers": [r.login for r in self.reviewers],
            "labels": self.labels,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "mergeable": self.mergeable,
            "additions": self.additions,
            "deletions": self.deletions,
            "changed_files": self.changed_files,
        }


@dataclass
class GitHubNotification:
    """GitHub notification information."""
    id: str
    unread: bool
    reason: str  # assign, author, comment, mention, review_requested, etc.
    subject_title: str
    subject_type: str  # Issue, PullRequest, Release, etc.
    subject_url: Optional[str] = None
    repository: Optional[str] = None
    updated_at: Optional[datetime] = None
    
    @classmethod  
    def from_api(cls, data: Dict) -> "GitHubNotification":
        updated = data.get("updated_at")
        if updated and isinstance(updated, str):
            try:
                updated = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            except:
                updated = None
        
        return cls(
            id=data.get("id", ""),
            unread=data.get("unread", False),
            reason=data.get("reason", ""),
            subject_title=data.get("subject", {}).get("title", ""),
            subject_type=data.get("subject", {}).get("type", ""),
            subject_url=data.get("subject", {}).get("url"),
            repository=data.get("repository", {}).get("full_name"),
            updated_at=updated,
        )
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "unread": self.unread,
            "reason": self.reason,
            "subject_title": self.subject_title,
            "subject_type": self.subject_type,
            "repository": self.repository,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ============================================================================
# GitHub Connector
# ============================================================================

class GitHubConnector:
    """
    GitHub API connector for development workflow integration.
    
    Authentication options:
    1. GITHUB_TOKEN environment variable
    2. gh CLI authentication (uses token from gh auth)
    3. Explicit token parameter
    
    Usage:
        connector = GitHubConnector()
        await connector.connect()
        
        # List your repos
        repos = await connector.list_repos()
        
        # Get issues assigned to you
        issues = await connector.get_assigned_issues()
        
        # Check PRs needing review
        prs = await connector.get_review_requests()
    """
    
    BASE_URL = "https://api.github.com"
    
    def __init__(self, token: Optional[str] = None):
        self._token = token
        self._client: Optional[httpx.AsyncClient] = None
        self._user: Optional[GitHubUser] = None
        self._connected = False
    
    async def connect(self) -> bool:
        """
        Connect to GitHub API.
        
        Tries:
        1. Explicit token
        2. GITHUB_TOKEN env var
        3. gh CLI token
        """
        # Get token
        token = self._token or os.environ.get("GITHUB_TOKEN")
        
        if not token:
            # Try gh CLI
            token = self._get_gh_token()
        
        if not token:
            logger.error("No GitHub token found. Set GITHUB_TOKEN or authenticate with 'gh auth login'")
            return False
        
        self._token = token
        
        # Create client
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )
        
        # Verify authentication
        try:
            self._user = await self.get_authenticated_user()
            self._connected = True
            logger.info(f"Connected to GitHub as {self._user.login}")
            return True
        except Exception as e:
            logger.error(f"GitHub authentication failed: {e}")
            await self._client.aclose()
            self._client = None
            return False
    
    async def disconnect(self):
        """Disconnect from GitHub API."""
        if self._client:
            await self._client.aclose()
            self._client = None
        self._connected = False
        self._user = None
    
    def _get_gh_token(self) -> Optional[str]:
        """Get token from gh CLI."""
        try:
            result = subprocess.run(
                ["gh", "auth", "token"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception as e:
            logger.debug(f"Could not get gh token: {e}")
        return None
    
    @property
    def is_connected(self) -> bool:
        return self._connected
    
    @property
    def current_user(self) -> Optional[GitHubUser]:
        return self._user
    
    # === API Methods ===
    
    async def _get(self, endpoint: str, params: Dict = None) -> Dict:
        """Make GET request to GitHub API."""
        if not self._client:
            raise RuntimeError("Not connected to GitHub")
        
        response = await self._client.get(endpoint, params=params)
        response.raise_for_status()
        return response.json()
    
    async def _post(self, endpoint: str, data: Dict = None) -> Dict:
        """Make POST request to GitHub API."""
        if not self._client:
            raise RuntimeError("Not connected to GitHub")
        
        response = await self._client.post(endpoint, json=data)
        response.raise_for_status()
        return response.json()
    
    async def _patch(self, endpoint: str, data: Dict = None) -> Dict:
        """Make PATCH request to GitHub API."""
        if not self._client:
            raise RuntimeError("Not connected to GitHub")
        
        response = await self._client.patch(endpoint, json=data)
        response.raise_for_status()
        return response.json()
    
    # === User ===
    
    async def get_authenticated_user(self) -> GitHubUser:
        """Get the authenticated user."""
        data = await self._get("/user")
        return GitHubUser.from_api(data)
    
    # === Repositories ===
    
    async def list_repos(
        self,
        type: str = "all",  # all, owner, public, private, member
        sort: str = "updated",  # created, updated, pushed, full_name
        per_page: int = 30,
    ) -> List[GitHubRepo]:
        """List repositories for the authenticated user."""
        data = await self._get("/user/repos", {
            "type": type,
            "sort": sort,
            "per_page": per_page,
        })
        return [GitHubRepo.from_api(r) for r in data]
    
    async def get_repo(self, owner: str, repo: str) -> GitHubRepo:
        """Get a specific repository."""
        data = await self._get(f"/repos/{owner}/{repo}")
        return GitHubRepo.from_api(data)
    
    # === Issues ===
    
    async def list_issues(
        self,
        owner: str,
        repo: str,
        state: IssueState = IssueState.OPEN,
        labels: List[str] = None,
        assignee: str = None,
        per_page: int = 30,
    ) -> List[GitHubIssue]:
        """List issues for a repository."""
        params = {
            "state": state.value,
            "per_page": per_page,
        }
        if labels:
            params["labels"] = ",".join(labels)
        if assignee:
            params["assignee"] = assignee
        
        data = await self._get(f"/repos/{owner}/{repo}/issues", params)
        return [GitHubIssue.from_api(i) for i in data]
    
    async def get_issue(self, owner: str, repo: str, number: int) -> GitHubIssue:
        """Get a specific issue."""
        data = await self._get(f"/repos/{owner}/{repo}/issues/{number}")
        return GitHubIssue.from_api(data)
    
    async def create_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str = None,
        labels: List[str] = None,
        assignees: List[str] = None,
        milestone: int = None,
    ) -> GitHubIssue:
        """Create a new issue."""
        data = {"title": title}
        if body:
            data["body"] = body
        if labels:
            data["labels"] = labels
        if assignees:
            data["assignees"] = assignees
        if milestone:
            data["milestone"] = milestone
        
        result = await self._post(f"/repos/{owner}/{repo}/issues", data)
        return GitHubIssue.from_api(result)
    
    async def update_issue(
        self,
        owner: str,
        repo: str,
        number: int,
        title: str = None,
        body: str = None,
        state: IssueState = None,
        labels: List[str] = None,
        assignees: List[str] = None,
    ) -> GitHubIssue:
        """Update an existing issue."""
        data = {}
        if title is not None:
            data["title"] = title
        if body is not None:
            data["body"] = body
        if state is not None:
            data["state"] = state.value
        if labels is not None:
            data["labels"] = labels
        if assignees is not None:
            data["assignees"] = assignees
        
        result = await self._patch(f"/repos/{owner}/{repo}/issues/{number}", data)
        return GitHubIssue.from_api(result)
    
    async def get_assigned_issues(
        self,
        state: IssueState = IssueState.OPEN,
        per_page: int = 30,
    ) -> List[GitHubIssue]:
        """Get issues assigned to the authenticated user across all repos."""
        data = await self._get("/issues", {
            "filter": "assigned",
            "state": state.value,
            "per_page": per_page,
        })
        return [GitHubIssue.from_api(i) for i in data]
    
    async def get_mentioned_issues(
        self,
        state: IssueState = IssueState.OPEN,
        per_page: int = 30,
    ) -> List[GitHubIssue]:
        """Get issues where the authenticated user is mentioned."""
        data = await self._get("/issues", {
            "filter": "mentioned",
            "state": state.value,
            "per_page": per_page,
        })
        return [GitHubIssue.from_api(i) for i in data]
    
    # === Pull Requests ===
    
    async def list_pull_requests(
        self,
        owner: str,
        repo: str,
        state: str = "open",  # open, closed, all
        sort: str = "updated",  # created, updated, popularity
        per_page: int = 30,
    ) -> List[GitHubPullRequest]:
        """List pull requests for a repository."""
        data = await self._get(f"/repos/{owner}/{repo}/pulls", {
            "state": state,
            "sort": sort,
            "per_page": per_page,
        })
        return [GitHubPullRequest.from_api(pr) for pr in data]
    
    async def get_pull_request(
        self,
        owner: str,
        repo: str,
        number: int,
    ) -> GitHubPullRequest:
        """Get a specific pull request."""
        data = await self._get(f"/repos/{owner}/{repo}/pulls/{number}")
        return GitHubPullRequest.from_api(data)
    
    async def get_review_requests(self, per_page: int = 30) -> List[Dict]:
        """
        Get pull requests where the authenticated user's review is requested.
        
        Returns list of dicts with repo and PR info.
        """
        # Search for PRs where user is requested reviewer
        if not self._user:
            return []
        
        query = f"is:pr is:open review-requested:{self._user.login}"
        data = await self._get("/search/issues", {
            "q": query,
            "per_page": per_page,
        })
        
        results = []
        for item in data.get("items", []):
            # Parse repo from URL
            url = item.get("repository_url", "")
            parts = url.split("/")
            if len(parts) >= 2:
                owner = parts[-2]
                repo = parts[-1]
            else:
                owner = repo = ""
            
            results.append({
                "number": item.get("number"),
                "title": item.get("title"),
                "html_url": item.get("html_url"),
                "owner": owner,
                "repo": repo,
                "user": item.get("user", {}).get("login"),
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
            })
        
        return results
    
    # === Notifications ===
    
    async def list_notifications(
        self,
        all: bool = False,
        participating: bool = False,
        per_page: int = 50,
    ) -> List[GitHubNotification]:
        """List notifications for the authenticated user."""
        params = {"per_page": per_page}
        if all:
            params["all"] = "true"
        if participating:
            params["participating"] = "true"
        
        data = await self._get("/notifications", params)
        return [GitHubNotification.from_api(n) for n in data]
    
    async def get_unread_count(self) -> int:
        """Get count of unread notifications."""
        notifications = await self.list_notifications()
        return sum(1 for n in notifications if n.unread)
    
    async def mark_notification_read(self, notification_id: str):
        """Mark a notification as read."""
        if not self._client:
            raise RuntimeError("Not connected to GitHub")
        
        response = await self._client.patch(f"/notifications/threads/{notification_id}")
        response.raise_for_status()
    
    # === Search ===
    
    async def search_issues(
        self,
        query: str,
        per_page: int = 30,
    ) -> List[GitHubIssue]:
        """Search issues and pull requests."""
        data = await self._get("/search/issues", {
            "q": query,
            "per_page": per_page,
        })
        return [GitHubIssue.from_api(i) for i in data.get("items", [])]
    
    async def search_repos(
        self,
        query: str,
        per_page: int = 30,
    ) -> List[GitHubRepo]:
        """Search repositories."""
        data = await self._get("/search/repositories", {
            "q": query,
            "per_page": per_page,
        })
        return [GitHubRepo.from_api(r) for r in data.get("items", [])]
    
    # === Activity Summary (for proactive monitoring) ===
    
    async def get_activity_summary(self) -> Dict:
        """
        Get a summary of activity relevant to the user.
        
        Useful for proactive alerts and daily briefings.
        """
        summary = {
            "timestamp": datetime.now().isoformat(),
            "user": self._user.login if self._user else None,
            "notifications": {"unread": 0, "items": []},
            "review_requests": [],
            "assigned_issues": [],
            "mentioned": [],
        }
        
        try:
            # Unread notifications
            notifications = await self.list_notifications()
            unread = [n for n in notifications if n.unread]
            summary["notifications"]["unread"] = len(unread)
            summary["notifications"]["items"] = [n.to_dict() for n in unread[:10]]
            
            # Review requests
            review_requests = await self.get_review_requests(per_page=10)
            summary["review_requests"] = review_requests
            
            # Assigned issues
            assigned = await self.get_assigned_issues(per_page=10)
            summary["assigned_issues"] = [i.to_dict() for i in assigned]
            
            # Mentions (last 5)
            mentioned = await self.get_mentioned_issues(per_page=5)
            summary["mentioned"] = [i.to_dict() for i in mentioned]
            
        except Exception as e:
            logger.error(f"Error getting activity summary: {e}")
            summary["error"] = str(e)
        
        return summary
    
    # === Polling for ProactiveMonitor ===
    
    async def get_recent(self) -> Dict:
        """
        Get recent activity for proactive monitoring.
        
        Returns a dict compatible with ProactiveMonitor polling.
        """
        return await self.get_activity_summary()
    
    async def poll(self) -> Dict:
        """Alias for get_recent (ProactiveMonitor compatibility)."""
        return await self.get_recent()


# ============================================================================
# Factory Function
# ============================================================================

def create_github_connector(token: Optional[str] = None) -> GitHubConnector:
    """Create a new GitHubConnector instance."""
    return GitHubConnector(token=token)
