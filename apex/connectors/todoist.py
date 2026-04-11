"""
Todoist Connector - Task Management Integration

Provides access to Todoist for task creation, project management,
and productivity tracking via the Todoist REST API v2.

Capabilities:
- Task CRUD (create, read, update, complete, delete)
- Project management (list, create)
- Labels and filters
- Task comments
- Due date management

Setup:
    from connectors.todoist import TodoistConnector
    
    todoist = TodoistConnector(api_token="...")
    await todoist.connect()
    
    await todoist.create_task(content="Buy groceries", due_string="tomorrow")
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TODOIST_API = "https://api.todoist.com/rest/v2"
TODOIST_API_LEGACY = "https://api.todoist.com/api/v1"


@dataclass
class TodoistTask:
    """Todoist task."""
    id: str
    content: str
    description: str = ""
    project_id: Optional[str] = None
    priority: int = 1  # 1=normal, 4=urgent
    due_date: Optional[str] = None
    due_string: Optional[str] = None
    labels: List[str] = field(default_factory=list)
    is_completed: bool = False
    created_at: Optional[str] = None
    url: Optional[str] = None

    @classmethod
    def from_api(cls, data: Dict) -> "TodoistTask":
        due = data.get("due") or {}
        return cls(
            id=data.get("id", ""),
            content=data.get("content", ""),
            description=data.get("description", ""),
            project_id=data.get("project_id"),
            priority=data.get("priority", 1),
            due_date=due.get("date"),
            due_string=due.get("string"),
            labels=data.get("labels", []),
            is_completed=data.get("is_completed", False),
            created_at=data.get("created_at"),
            url=data.get("url"),
        )


@dataclass
class TodoistProject:
    """Todoist project."""
    id: str
    name: str
    color: Optional[str] = None
    is_favorite: bool = False

    @classmethod
    def from_api(cls, data: Dict) -> "TodoistProject":
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            color=data.get("color"),
            is_favorite=data.get("is_favorite", False),
        )


class TodoistConnector:
    """Todoist task management connector."""

    def __init__(self, api_token: Optional[str] = None):
        self._token = api_token or os.environ.get("TODOIST_API_TOKEN", "")
        self._http = None
        self._using_legacy_api = False

    async def connect(self):
        """Initialize HTTP client."""
        if not self._token:
            raise ValueError("No Todoist API token. Set TODOIST_API_TOKEN.")

        import httpx
        self._http = httpx.AsyncClient(
            base_url=TODOIST_API,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json",
                "User-Agent": "Telic/1.0 (+https://github.com/rob637/Zero)",
            },
            timeout=30,
        )

    async def _ensure_client(self):
        if not self._http:
            await self.connect()

    async def _request(self, method: str, path: str, **kwargs):
        """Make a Todoist API request, falling back to legacy API if v2 returns 410."""
        await self._ensure_client()
        resp = await self._http.request(method, path, **kwargs)

        if resp.status_code == 410:
            legacy_url = f"{TODOIST_API_LEGACY}{path}"
            resp = await self._http.request(method, legacy_url, **kwargs)
            if resp.status_code < 400:
                if not self._using_legacy_api:
                    self._using_legacy_api = True
                    logger.warning(
                        "Todoist REST v2 returned 410 Gone; using legacy API endpoint for compatibility"
                    )
                return resp

        return resp

    # --- Tasks ---

    async def list_tasks(
        self,
        project_id: Optional[str] = None,
        label: Optional[str] = None,
        filter_str: Optional[str] = None,
    ) -> List[TodoistTask]:
        """List active tasks, optionally filtered."""
        params = {}
        if project_id:
            params["project_id"] = project_id
        if label:
            params["label"] = label
        if filter_str:
            params["filter"] = filter_str

        resp = await self._request("GET", "/tasks", params=params)
        resp.raise_for_status()
        return [TodoistTask.from_api(t) for t in resp.json()]

    async def create_task(
        self,
        content: str,
        description: str = "",
        project_id: Optional[str] = None,
        priority: int = 1,
        due_string: Optional[str] = None,
        due_date: Optional[str] = None,
        labels: Optional[List[str]] = None,
    ) -> TodoistTask:
        """Create a new task."""
        body: Dict[str, Any] = {"content": content}
        if description:
            body["description"] = description
        if project_id:
            body["project_id"] = project_id
        if priority > 1:
            body["priority"] = priority
        if due_string:
            body["due_string"] = due_string
        elif due_date:
            body["due_date"] = due_date
        if labels:
            body["labels"] = labels

        resp = await self._request("POST", "/tasks", json=body)
        resp.raise_for_status()
        return TodoistTask.from_api(resp.json())

    async def complete_task(self, task_id: str) -> bool:
        """Mark a task as completed."""
        resp = await self._request("POST", f"/tasks/{task_id}/close")
        return resp.status_code == 204

    async def update_task(self, task_id: str, **kwargs) -> TodoistTask:
        """Update a task. Accepts content, description, priority, due_string, labels."""
        resp = await self._request("POST", f"/tasks/{task_id}", json=kwargs)
        resp.raise_for_status()
        return TodoistTask.from_api(resp.json())

    async def delete_task(self, task_id: str) -> bool:
        """Delete a task."""
        resp = await self._request("DELETE", f"/tasks/{task_id}")
        return resp.status_code == 204

    async def get_task(self, task_id: str) -> TodoistTask:
        """Get a specific task."""
        resp = await self._request("GET", f"/tasks/{task_id}")
        resp.raise_for_status()
        return TodoistTask.from_api(resp.json())

    # --- Projects ---

    async def list_projects(self) -> List[TodoistProject]:
        """List all projects."""
        resp = await self._request("GET", "/projects")
        resp.raise_for_status()
        return [TodoistProject.from_api(p) for p in resp.json()]

    async def create_project(self, name: str, color: Optional[str] = None) -> TodoistProject:
        """Create a new project."""
        body: Dict[str, Any] = {"name": name}
        if color:
            body["color"] = color
        resp = await self._request("POST", "/projects", json=body)
        resp.raise_for_status()
        return TodoistProject.from_api(resp.json())

    async def close(self):
        if self._http:
            await self._http.aclose()
            self._http = None
