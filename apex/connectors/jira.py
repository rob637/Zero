"""
Jira Connector - Project Management Integration

Provides access to Jira Cloud for issue tracking,
sprint management, and project monitoring.

Uses Jira REST API v3 with basic authentication (email + API token).

Capabilities:
- Issue management (list, create, update, transition)
- Sprint and board information
- Project tracking
- JQL search
- Worklog and comments

This enables Apex to:
- Alert on assigned issues
- Track sprint progress
- Cross-reference with GitHub PRs
- Prepare for standup (what I worked on, blockers)
- Monitor project deadlines
"""

import asyncio
import base64
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional
import json

import httpx

logger = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class JiraUser:
    """Jira user information."""
    account_id: str
    display_name: str
    email: Optional[str] = None
    avatar_url: Optional[str] = None
    active: bool = True
    
    @classmethod
    def from_api(cls, data: Dict) -> "JiraUser":
        if not data:
            return None
        return cls(
            account_id=data.get("accountId", ""),
            display_name=data.get("displayName", ""),
            email=data.get("emailAddress"),
            avatar_url=data.get("avatarUrls", {}).get("48x48"),
            active=data.get("active", True),
        )
    
    def to_dict(self) -> Dict:
        return {
            "account_id": self.account_id,
            "display_name": self.display_name,
            "email": self.email,
            "active": self.active,
        }


@dataclass
class JiraProject:
    """Jira project information."""
    id: str
    key: str
    name: str
    description: Optional[str] = None
    lead: Optional[JiraUser] = None
    project_type: Optional[str] = None
    avatar_url: Optional[str] = None
    
    @classmethod
    def from_api(cls, data: Dict) -> "JiraProject":
        return cls(
            id=data.get("id", ""),
            key=data.get("key", ""),
            name=data.get("name", ""),
            description=data.get("description"),
            lead=JiraUser.from_api(data.get("lead")),
            project_type=data.get("projectTypeKey"),
            avatar_url=data.get("avatarUrls", {}).get("48x48"),
        )
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "lead": self.lead.display_name if self.lead else None,
            "project_type": self.project_type,
        }


@dataclass
class JiraIssue:
    """Jira issue information."""
    id: str
    key: str  # e.g., "PROJ-123"
    summary: str
    description: Optional[str] = None
    status: Optional[str] = None
    status_category: Optional[str] = None  # To Do, In Progress, Done
    issue_type: Optional[str] = None  # Bug, Story, Task, Epic
    priority: Optional[str] = None
    project_key: Optional[str] = None
    assignee: Optional[JiraUser] = None
    reporter: Optional[JiraUser] = None
    labels: List[str] = field(default_factory=list)
    components: List[str] = field(default_factory=list)
    sprint: Optional[str] = None
    story_points: Optional[float] = None
    created: Optional[datetime] = None
    updated: Optional[datetime] = None
    due_date: Optional[datetime] = None
    resolution: Optional[str] = None
    parent_key: Optional[str] = None  # For subtasks
    subtasks: List[str] = field(default_factory=list)
    html_url: Optional[str] = None
    
    @classmethod
    def from_api(cls, data: Dict, base_url: str = "") -> "JiraIssue":
        def parse_dt(s):
            if s and isinstance(s, str):
                try:
                    # Jira uses ISO format but sometimes with timezone
                    return datetime.fromisoformat(s.replace("Z", "+00:00").split(".")[0])
                except:
                    pass
            return None
        
        fields = data.get("fields", {})
        
        # Get sprint from custom field (varies by instance)
        sprint = None
        sprint_field = fields.get("customfield_10020") or fields.get("sprint")
        if sprint_field and isinstance(sprint_field, list) and sprint_field:
            sprint = sprint_field[0].get("name") if isinstance(sprint_field[0], dict) else str(sprint_field[0])
        
        # Story points (custom field varies)
        story_points = fields.get("customfield_10016") or fields.get("storyPoints")
        
        return cls(
            id=data.get("id", ""),
            key=data.get("key", ""),
            summary=fields.get("summary", ""),
            description=fields.get("description"),
            status=fields.get("status", {}).get("name"),
            status_category=fields.get("status", {}).get("statusCategory", {}).get("name"),
            issue_type=fields.get("issuetype", {}).get("name"),
            priority=fields.get("priority", {}).get("name"),
            project_key=fields.get("project", {}).get("key"),
            assignee=JiraUser.from_api(fields.get("assignee")),
            reporter=JiraUser.from_api(fields.get("reporter")),
            labels=fields.get("labels", []),
            components=[c.get("name", "") for c in fields.get("components", [])],
            sprint=sprint,
            story_points=float(story_points) if story_points else None,
            created=parse_dt(fields.get("created")),
            updated=parse_dt(fields.get("updated")),
            due_date=parse_dt(fields.get("duedate")),
            resolution=fields.get("resolution", {}).get("name") if fields.get("resolution") else None,
            parent_key=fields.get("parent", {}).get("key"),
            subtasks=[st.get("key", "") for st in fields.get("subtasks", [])],
            html_url=f"{base_url}/browse/{data.get('key', '')}" if base_url else None,
        )
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "key": self.key,
            "summary": self.summary,
            "status": self.status,
            "status_category": self.status_category,
            "issue_type": self.issue_type,
            "priority": self.priority,
            "project_key": self.project_key,
            "assignee": self.assignee.display_name if self.assignee else None,
            "labels": self.labels,
            "sprint": self.sprint,
            "story_points": self.story_points,
            "created": self.created.isoformat() if self.created else None,
            "updated": self.updated.isoformat() if self.updated else None,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "html_url": self.html_url,
        }


@dataclass
class JiraSprint:
    """Jira sprint information."""
    id: int
    name: str
    state: str  # future, active, closed
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    goal: Optional[str] = None
    board_id: Optional[int] = None
    
    @classmethod
    def from_api(cls, data: Dict) -> "JiraSprint":
        def parse_dt(s):
            if s:
                try:
                    return datetime.fromisoformat(s.replace("Z", "+00:00"))
                except:
                    pass
            return None
        
        return cls(
            id=data.get("id", 0),
            name=data.get("name", ""),
            state=data.get("state", ""),
            start_date=parse_dt(data.get("startDate")),
            end_date=parse_dt(data.get("endDate")),
            goal=data.get("goal"),
            board_id=data.get("originBoardId"),
        )
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "state": self.state,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "goal": self.goal,
        }


# ============================================================================
# Jira Connector
# ============================================================================

class JiraConnector:
    """
    Jira Cloud API connector for project management integration.
    
    Authentication:
    - JIRA_URL: Your Jira instance URL (e.g., https://your-domain.atlassian.net)
    - JIRA_EMAIL: Your Atlassian account email
    - JIRA_API_TOKEN: API token from https://id.atlassian.com/manage-profile/security/api-tokens
    
    Usage:
        connector = JiraConnector(
            url="https://your-domain.atlassian.net",
            email="you@example.com",
            api_token="your-api-token"
        )
        await connector.connect()
        
        # Get your assigned issues
        issues = await connector.get_my_issues()
        
        # Search with JQL
        results = await connector.search("project = PROJ AND sprint in openSprints()")
    """
    
    def __init__(
        self,
        url: Optional[str] = None,
        email: Optional[str] = None,
        api_token: Optional[str] = None,
    ):
        self._url = (url or os.environ.get("JIRA_URL", "")).rstrip("/")
        self._email = email or os.environ.get("JIRA_EMAIL", "")
        self._api_token = api_token or os.environ.get("JIRA_API_TOKEN", "")
        self._client: Optional[httpx.AsyncClient] = None
        self._user: Optional[JiraUser] = None
        self._connected = False
    
    async def connect(self) -> bool:
        """Connect to Jira API."""
        if not self._url or not self._email or not self._api_token:
            logger.error("Missing Jira credentials. Set JIRA_URL, JIRA_EMAIL, and JIRA_API_TOKEN")
            return False
        
        # Create basic auth header
        auth_string = f"{self._email}:{self._api_token}"
        auth_bytes = base64.b64encode(auth_string.encode()).decode()
        
        self._client = httpx.AsyncClient(
            base_url=f"{self._url}/rest/api/3",
            headers={
                "Authorization": f"Basic {auth_bytes}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        
        # Also create agile client for sprint/board endpoints
        self._agile_client = httpx.AsyncClient(
            base_url=f"{self._url}/rest/agile/1.0",
            headers={
                "Authorization": f"Basic {auth_bytes}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        
        # Verify authentication
        try:
            self._user = await self.get_myself()
            self._connected = True
            logger.info(f"Connected to Jira as {self._user.display_name}")
            return True
        except Exception as e:
            logger.error(f"Jira authentication failed: {e}")
            await self._client.aclose()
            await self._agile_client.aclose()
            self._client = None
            self._agile_client = None
            return False
    
    async def disconnect(self):
        """Disconnect from Jira API."""
        if self._client:
            await self._client.aclose()
            self._client = None
        if self._agile_client:
            await self._agile_client.aclose()
            self._agile_client = None
        self._connected = False
        self._user = None
    
    @property
    def is_connected(self) -> bool:
        return self._connected
    
    @property
    def current_user(self) -> Optional[JiraUser]:
        return self._user
    
    @property
    def base_url(self) -> str:
        return self._url
    
    # === API Methods ===
    
    async def _get(self, endpoint: str, params: Dict = None) -> Dict:
        """Make GET request to Jira API."""
        if not self._client:
            raise RuntimeError("Not connected to Jira")
        
        response = await self._client.get(endpoint, params=params)
        response.raise_for_status()
        return response.json()
    
    async def _post(self, endpoint: str, data: Dict = None) -> Dict:
        """Make POST request to Jira API."""
        if not self._client:
            raise RuntimeError("Not connected to Jira")
        
        response = await self._client.post(endpoint, json=data)
        response.raise_for_status()
        return response.json()
    
    async def _put(self, endpoint: str, data: Dict = None) -> Dict:
        """Make PUT request to Jira API."""
        if not self._client:
            raise RuntimeError("Not connected to Jira")
        
        response = await self._client.put(endpoint, json=data)
        response.raise_for_status()
        return response.json() if response.content else {}
    
    async def _agile_get(self, endpoint: str, params: Dict = None) -> Dict:
        """Make GET request to Jira Agile API."""
        if not self._agile_client:
            raise RuntimeError("Not connected to Jira")
        
        response = await self._agile_client.get(endpoint, params=params)
        response.raise_for_status()
        return response.json()
    
    # === User ===
    
    async def get_myself(self) -> JiraUser:
        """Get the authenticated user."""
        data = await self._get("/myself")
        return JiraUser.from_api(data)
    
    # === Projects ===
    
    async def list_projects(self, max_results: int = 50) -> List[JiraProject]:
        """List accessible projects."""
        data = await self._get("/project", {"maxResults": max_results})
        return [JiraProject.from_api(p) for p in data]
    
    async def get_project(self, key: str) -> JiraProject:
        """Get a specific project."""
        data = await self._get(f"/project/{key}")
        return JiraProject.from_api(data)
    
    # === Issues ===
    
    async def search(
        self,
        jql: str,
        fields: List[str] = None,
        max_results: int = 50,
        start_at: int = 0,
    ) -> List[JiraIssue]:
        """
        Search issues using JQL.
        
        Examples:
            "assignee = currentUser() AND status != Done"
            "project = PROJ AND sprint in openSprints()"
            "updated >= -7d"
        """
        default_fields = [
            "summary", "description", "status", "issuetype", "priority",
            "project", "assignee", "reporter", "labels", "components",
            "created", "updated", "duedate", "resolution", "parent", "subtasks",
            "customfield_10020",  # Sprint (may vary)
            "customfield_10016",  # Story points (may vary)
        ]
        
        data = await self._post("/search", {
            "jql": jql,
            "fields": fields or default_fields,
            "maxResults": max_results,
            "startAt": start_at,
        })
        
        return [JiraIssue.from_api(i, self._url) for i in data.get("issues", [])]
    
    async def get_issue(self, key: str) -> JiraIssue:
        """Get a specific issue."""
        data = await self._get(f"/issue/{key}")
        return JiraIssue.from_api(data, self._url)
    
    async def create_issue(
        self,
        project_key: str,
        summary: str,
        issue_type: str = "Task",
        description: str = None,
        assignee_account_id: str = None,
        labels: List[str] = None,
        priority: str = None,
    ) -> JiraIssue:
        """Create a new issue."""
        fields = {
            "project": {"key": project_key},
            "summary": summary,
            "issuetype": {"name": issue_type},
        }
        
        if description:
            # Jira uses Atlassian Document Format for rich text
            fields["description"] = {
                "type": "doc",
                "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": description}]}]
            }
        if assignee_account_id:
            fields["assignee"] = {"accountId": assignee_account_id}
        if labels:
            fields["labels"] = labels
        if priority:
            fields["priority"] = {"name": priority}
        
        data = await self._post("/issue", {"fields": fields})
        return await self.get_issue(data["key"])
    
    async def update_issue(
        self,
        key: str,
        summary: str = None,
        description: str = None,
        assignee_account_id: str = None,
        labels: List[str] = None,
    ) -> JiraIssue:
        """Update an existing issue."""
        fields = {}
        
        if summary:
            fields["summary"] = summary
        if description:
            fields["description"] = {
                "type": "doc",
                "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": description}]}]
            }
        if assignee_account_id is not None:
            fields["assignee"] = {"accountId": assignee_account_id} if assignee_account_id else None
        if labels is not None:
            fields["labels"] = labels
        
        await self._put(f"/issue/{key}", {"fields": fields})
        return await self.get_issue(key)
    
    async def transition_issue(self, key: str, transition_name: str) -> bool:
        """
        Transition an issue to a new status.
        
        Common transitions: "To Do", "In Progress", "Done"
        """
        # Get available transitions
        response = await self._get(f"/issue/{key}/transitions")
        transitions = response.get("transitions", [])
        
        # Find matching transition
        transition_id = None
        for t in transitions:
            if t.get("name", "").lower() == transition_name.lower():
                transition_id = t.get("id")
                break
        
        if not transition_id:
            available = [t.get("name") for t in transitions]
            raise ValueError(f"Transition '{transition_name}' not found. Available: {available}")
        
        await self._post(f"/issue/{key}/transitions", {"transition": {"id": transition_id}})
        return True
    
    async def add_comment(self, key: str, body: str) -> Dict:
        """Add a comment to an issue."""
        data = await self._post(f"/issue/{key}/comment", {
            "body": {
                "type": "doc",
                "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": body}]}]
            }
        })
        return data
    
    # === My Issues ===
    
    async def get_my_issues(
        self,
        status_category: str = None,  # "To Do", "In Progress", "Done"
        max_results: int = 50,
    ) -> List[JiraIssue]:
        """Get issues assigned to the current user."""
        jql = "assignee = currentUser()"
        if status_category:
            jql += f' AND statusCategory = "{status_category}"'
        jql += " ORDER BY updated DESC"
        
        return await self.search(jql, max_results=max_results)
    
    async def get_my_in_progress(self) -> List[JiraIssue]:
        """Get issues I'm currently working on."""
        return await self.get_my_issues(status_category="In Progress")
    
    async def get_my_todo(self) -> List[JiraIssue]:
        """Get issues assigned to me that are not started."""
        return await self.get_my_issues(status_category="To Do")
    
    async def get_recently_updated(self, days: int = 7) -> List[JiraIssue]:
        """Get issues updated in the last N days."""
        jql = f"assignee = currentUser() AND updated >= -{days}d ORDER BY updated DESC"
        return await self.search(jql)
    
    # === Sprints ===
    
    async def get_active_sprints(self, board_id: int) -> List[JiraSprint]:
        """Get active sprints for a board."""
        data = await self._agile_get(f"/board/{board_id}/sprint", {"state": "active"})
        return [JiraSprint.from_api(s) for s in data.get("values", [])]
    
    async def get_sprint_issues(
        self,
        sprint_id: int,
        max_results: int = 100,
    ) -> List[JiraIssue]:
        """Get issues in a sprint."""
        jql = f"sprint = {sprint_id} ORDER BY rank"
        return await self.search(jql, max_results=max_results)
    
    # === Boards ===
    
    async def list_boards(self, project_key: str = None) -> List[Dict]:
        """List Scrum/Kanban boards."""
        params = {}
        if project_key:
            params["projectKeyOrId"] = project_key
        
        data = await self._agile_get("/board", params)
        return data.get("values", [])
    
    # === Activity Summary (for proactive monitoring) ===
    
    async def get_activity_summary(self) -> Dict:
        """
        Get a summary of Jira activity for the user.
        
        Useful for proactive alerts and standup preparation.
        """
        summary = {
            "timestamp": datetime.now().isoformat(),
            "user": self._user.display_name if self._user else None,
            "in_progress": [],
            "todo": [],
            "recently_updated": [],
            "due_soon": [],
        }
        
        try:
            # In progress
            in_progress = await self.get_my_in_progress()
            summary["in_progress"] = [i.to_dict() for i in in_progress[:10]]
            
            # To do
            todo = await self.get_my_todo()
            summary["todo"] = [i.to_dict() for i in todo[:10]]
            
            # Recently updated (last 3 days)
            recent = await self.get_recently_updated(days=3)
            summary["recently_updated"] = [i.to_dict() for i in recent[:10]]
            
            # Due soon (next 7 days)
            due_soon = await self.search(
                "assignee = currentUser() AND duedate >= now() AND duedate <= 7d ORDER BY duedate",
                max_results=10
            )
            summary["due_soon"] = [i.to_dict() for i in due_soon]
            
        except Exception as e:
            logger.error(f"Error getting Jira activity summary: {e}")
            summary["error"] = str(e)
        
        return summary
    
    # === Polling for ProactiveMonitor ===
    
    async def get_recent(self) -> Dict:
        """Get recent activity for proactive monitoring."""
        return await self.get_activity_summary()
    
    async def poll(self) -> Dict:
        """Alias for get_recent (ProactiveMonitor compatibility)."""
        return await self.get_recent()


# ============================================================================
# Factory Function
# ============================================================================

def create_jira_connector(
    url: Optional[str] = None,
    email: Optional[str] = None,
    api_token: Optional[str] = None,
) -> JiraConnector:
    """Create a new JiraConnector instance."""
    return JiraConnector(url=url, email=email, api_token=api_token)
