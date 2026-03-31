"""
Microsoft To-Do Connector (Microsoft Graph API)

Full Microsoft To-Do task management integration:
- List and manage task lists
- Create, update, complete tasks
- Subtasks (checklist items)
- Due dates and reminders
- Recurrence patterns
- Categories and importance

Usage:
    from connectors.microsoft_todo import MicrosoftTodoConnector
    
    todo = MicrosoftTodoConnector()
    await todo.connect()
    
    # Get all lists
    lists = await todo.get_lists()
    
    # Get tasks from default list
    tasks = await todo.list_tasks()
    
    # Create task
    task = await todo.create_task(
        title="Buy groceries",
        due_date=datetime.now() + timedelta(days=1),
        importance="high",
    )
    
    # Complete task
    await todo.complete_task(task.id)
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional

from .microsoft_graph import GraphClient, get_graph_client, GraphAPIError

import logging
logger = logging.getLogger(__name__)


@dataclass
class TodoTask:
    """Represents a Microsoft To-Do task."""
    id: str
    title: str
    list_id: str
    body: Optional[str] = None
    importance: str = "normal"  # low, normal, high
    status: str = "notStarted"  # notStarted, inProgress, completed, waitingOnOthers, deferred
    is_completed: bool = False
    completed_datetime: Optional[datetime] = None
    created_datetime: Optional[datetime] = None
    modified_datetime: Optional[datetime] = None
    due_date: Optional[date] = None
    reminder_datetime: Optional[datetime] = None
    is_reminder_on: bool = False
    recurrence: Optional[Dict] = None
    categories: List[str] = field(default_factory=list)
    checklist_items: List[Dict] = field(default_factory=list)
    linked_resources: List[Dict] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "title": self.title,
            "list_id": self.list_id,
            "body": self.body,
            "importance": self.importance,
            "status": self.status,
            "is_completed": self.is_completed,
            "completed": self.completed_datetime.isoformat() if self.completed_datetime else None,
            "created": self.created_datetime.isoformat() if self.created_datetime else None,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "reminder": self.reminder_datetime.isoformat() if self.reminder_datetime else None,
            "categories": self.categories,
            "checklist": self.checklist_items,
        }


@dataclass
class TodoList:
    """Represents a To-Do task list."""
    id: str
    name: str
    is_owner: bool = True
    is_shared: bool = False
    wellknown_name: Optional[str] = None  # defaultList, flaggedEmails, etc.
    
    @property
    def is_default(self) -> bool:
        return self.wellknown_name == "defaultList"


class MicrosoftTodoConnector:
    """
    Microsoft To-Do connector via Graph API.
    
    Provides full task management functionality:
    - Manage task lists
    - Create, update, delete, complete tasks
    - Subtasks via checklist items
    - Due dates, reminders, recurrence
    - Categories and importance levels
    """
    
    def __init__(self, client: Optional[GraphClient] = None):
        self._client = client or get_graph_client()
        self._connected = False
        self._default_list_id: Optional[str] = None
    
    async def connect(self) -> bool:
        """Connect to Microsoft To-Do via Graph API."""
        if not self._client.connected:
            success = await self._client.connect(['tasks'])
            if not success:
                return False
        
        try:
            # Get the default list
            lists = await self.get_lists()
            for lst in lists:
                if lst.is_default:
                    self._default_list_id = lst.id
                    break
            
            if not self._default_list_id and lists:
                self._default_list_id = lists[0].id
            
            self._connected = True
            return True
        except GraphAPIError as e:
            logger.error(f"Failed to connect to To-Do: {e}")
            return False
    
    @property
    def connected(self) -> bool:
        return self._connected
    
    @property
    def default_list_id(self) -> Optional[str]:
        return self._default_list_id
    
    def _parse_datetime(self, dt_str: str) -> Optional[datetime]:
        """Parse ISO datetime string."""
        if not dt_str:
            return None
        try:
            return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        except:
            return None
    
    def _parse_date(self, date_dict: Dict) -> Optional[date]:
        """Parse Graph API date dict."""
        if not date_dict:
            return None
        dt_str = date_dict.get('dateTime', '')
        try:
            return datetime.fromisoformat(dt_str.replace('Z', '')).date()
        except:
            return None
    
    def _parse_task(self, task: Dict, list_id: str) -> TodoTask:
        """Parse Graph API task into TodoTask."""
        body = task.get('body', {})
        body_content = body.get('content', '') if body else ''
        
        # Parse checklist items
        checklist = []
        for item in task.get('checklistItems', []):
            checklist.append({
                'id': item.get('id'),
                'text': item.get('displayName', ''),
                'is_checked': item.get('isChecked', False),
            })
        
        # Parse linked resources
        links = []
        for link in task.get('linkedResources', []):
            links.append({
                'id': link.get('id'),
                'web_url': link.get('webUrl'),
                'application_name': link.get('applicationName'),
                'display_name': link.get('displayName'),
            })
        
        status = task.get('status', 'notStarted')
        
        return TodoTask(
            id=task.get('id', ''),
            title=task.get('title', ''),
            list_id=list_id,
            body=body_content,
            importance=task.get('importance', 'normal'),
            status=status,
            is_completed=status == 'completed',
            completed_datetime=self._parse_datetime(
                task.get('completedDateTime', {}).get('dateTime') if task.get('completedDateTime') else None
            ),
            created_datetime=self._parse_datetime(task.get('createdDateTime')),
            modified_datetime=self._parse_datetime(task.get('lastModifiedDateTime')),
            due_date=self._parse_date(task.get('dueDateTime')),
            reminder_datetime=self._parse_datetime(
                task.get('reminderDateTime', {}).get('dateTime') if task.get('reminderDateTime') else None
            ),
            is_reminder_on=task.get('isReminderOn', False),
            recurrence=task.get('recurrence'),
            categories=task.get('categories', []),
            checklist_items=checklist,
            linked_resources=links,
        )
    
    async def get_lists(self) -> List[TodoList]:
        """Get all task lists."""
        if not self._client.connected:
            await self._client.connect(['tasks'])
        
        result = await self._client.get("/me/todo/lists", scopes=['tasks'])
        
        return [
            TodoList(
                id=lst.get('id'),
                name=lst.get('displayName', ''),
                is_owner=lst.get('isOwner', True),
                is_shared=lst.get('isShared', False),
                wellknown_name=lst.get('wellknownListName'),
            )
            for lst in result.get('value', [])
        ]
    
    async def create_list(self, name: str) -> TodoList:
        """Create a new task list."""
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        result = await self._client.post(
            "/me/todo/lists",
            json_data={"displayName": name},
            scopes=['tasks'],
        )
        
        return TodoList(
            id=result.get('id'),
            name=result.get('displayName', name),
            is_owner=True,
            is_shared=False,
        )
    
    async def delete_list(self, list_id: str) -> bool:
        """Delete a task list."""
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        await self._client.delete(f"/me/todo/lists/{list_id}", scopes=['tasks'])
        return True
    
    async def list_tasks(
        self,
        list_id: str = None,
        include_completed: bool = False,
        max_results: int = 100,
    ) -> List[TodoTask]:
        """
        List tasks from a task list.
        
        Args:
            list_id: List ID (None for default list)
            include_completed: Include completed tasks
            max_results: Maximum tasks to return
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        if not list_id:
            list_id = self._default_list_id
        
        if not list_id:
            raise RuntimeError("No list ID provided and no default list found")
        
        params = {
            '$top': max_results,
            '$orderby': 'createdDateTime desc',
        }
        
        if not include_completed:
            params['$filter'] = "status ne 'completed'"
        
        result = await self._client.get(
            f"/me/todo/lists/{list_id}/tasks",
            params=params,
            scopes=['tasks'],
        )
        
        return [self._parse_task(t, list_id) for t in result.get('value', [])]
    
    async def get_task(self, task_id: str, list_id: str = None) -> TodoTask:
        """Get a single task."""
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        if not list_id:
            list_id = self._default_list_id
        
        result = await self._client.get(
            f"/me/todo/lists/{list_id}/tasks/{task_id}",
            scopes=['tasks'],
        )
        
        return self._parse_task(result, list_id)
    
    async def create_task(
        self,
        title: str,
        list_id: str = None,
        body: str = None,
        due_date: date = None,
        reminder: datetime = None,
        importance: str = "normal",  # low, normal, high
        categories: List[str] = None,
        checklist: List[str] = None,
    ) -> TodoTask:
        """
        Create a new task.
        
        Args:
            title: Task title
            list_id: List ID (None for default)
            body: Task body/notes
            due_date: Due date
            reminder: Reminder datetime
            importance: low, normal, or high
            categories: List of categories
            checklist: List of subtask strings
        
        Returns:
            Created TodoTask
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        if not list_id:
            list_id = self._default_list_id
        
        task_data = {
            "title": title,
            "importance": importance,
        }
        
        if body:
            task_data["body"] = {
                "content": body,
                "contentType": "text",
            }
        
        if due_date:
            task_data["dueDateTime"] = {
                "dateTime": f"{due_date.isoformat()}T00:00:00",
                "timeZone": "UTC",
            }
        
        if reminder:
            task_data["reminderDateTime"] = {
                "dateTime": reminder.isoformat(),
                "timeZone": "UTC",
            }
            task_data["isReminderOn"] = True
        
        if categories:
            task_data["categories"] = categories
        
        result = await self._client.post(
            f"/me/todo/lists/{list_id}/tasks",
            json_data=task_data,
            scopes=['tasks'],
        )
        
        task = self._parse_task(result, list_id)
        
        # Add checklist items if provided
        if checklist:
            for item_text in checklist:
                await self.add_checklist_item(task.id, item_text, list_id)
            
            # Refresh task to get checklist
            task = await self.get_task(task.id, list_id)
        
        return task
    
    async def update_task(
        self,
        task_id: str,
        list_id: str = None,
        title: str = None,
        body: str = None,
        due_date: date = None,
        reminder: datetime = None,
        importance: str = None,
        status: str = None,
    ) -> TodoTask:
        """
        Update an existing task.
        
        Only provided fields are updated.
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        if not list_id:
            list_id = self._default_list_id
        
        update = {}
        
        if title is not None:
            update["title"] = title
        if body is not None:
            update["body"] = {"content": body, "contentType": "text"}
        if importance is not None:
            update["importance"] = importance
        if status is not None:
            update["status"] = status
        
        if due_date is not None:
            update["dueDateTime"] = {
                "dateTime": f"{due_date.isoformat()}T00:00:00",
                "timeZone": "UTC",
            }
        
        if reminder is not None:
            update["reminderDateTime"] = {
                "dateTime": reminder.isoformat(),
                "timeZone": "UTC",
            }
            update["isReminderOn"] = True
        
        result = await self._client.patch(
            f"/me/todo/lists/{list_id}/tasks/{task_id}",
            json_data=update,
            scopes=['tasks'],
        )
        
        return self._parse_task(result, list_id)
    
    async def complete_task(self, task_id: str, list_id: str = None) -> TodoTask:
        """Mark a task as completed."""
        return await self.update_task(task_id, list_id, status="completed")
    
    async def uncomplete_task(self, task_id: str, list_id: str = None) -> TodoTask:
        """Mark a completed task as not started."""
        return await self.update_task(task_id, list_id, status="notStarted")
    
    async def delete_task(self, task_id: str, list_id: str = None) -> bool:
        """Delete a task."""
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        if not list_id:
            list_id = self._default_list_id
        
        await self._client.delete(
            f"/me/todo/lists/{list_id}/tasks/{task_id}",
            scopes=['tasks'],
        )
        return True
    
    async def add_checklist_item(
        self,
        task_id: str,
        text: str,
        list_id: str = None,
    ) -> Dict:
        """
        Add a checklist item (subtask) to a task.
        
        Args:
            task_id: Parent task ID
            text: Checklist item text
            list_id: List ID
        
        Returns:
            Created checklist item
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        if not list_id:
            list_id = self._default_list_id
        
        result = await self._client.post(
            f"/me/todo/lists/{list_id}/tasks/{task_id}/checklistItems",
            json_data={"displayName": text},
            scopes=['tasks'],
        )
        
        return {
            'id': result.get('id'),
            'text': result.get('displayName'),
            'is_checked': result.get('isChecked', False),
        }
    
    async def check_checklist_item(
        self,
        task_id: str,
        item_id: str,
        checked: bool = True,
        list_id: str = None,
    ) -> Dict:
        """Check or uncheck a checklist item."""
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        if not list_id:
            list_id = self._default_list_id
        
        result = await self._client.patch(
            f"/me/todo/lists/{list_id}/tasks/{task_id}/checklistItems/{item_id}",
            json_data={"isChecked": checked},
            scopes=['tasks'],
        )
        
        return {
            'id': result.get('id'),
            'text': result.get('displayName'),
            'is_checked': result.get('isChecked'),
        }
    
    async def delete_checklist_item(
        self,
        task_id: str,
        item_id: str,
        list_id: str = None,
    ) -> bool:
        """Delete a checklist item."""
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        if not list_id:
            list_id = self._default_list_id
        
        await self._client.delete(
            f"/me/todo/lists/{list_id}/tasks/{task_id}/checklistItems/{item_id}",
            scopes=['tasks'],
        )
        return True
    
    async def search_tasks(
        self,
        query: str,
        list_id: str = None,
        include_completed: bool = False,
    ) -> List[TodoTask]:
        """
        Search tasks by title/body.
        
        Note: Graph API doesn't support full-text search on tasks,
        so this does client-side filtering.
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        tasks = await self.list_tasks(
            list_id=list_id,
            include_completed=include_completed,
            max_results=500,  # Get more to search through
        )
        
        query_lower = query.lower()
        return [
            t for t in tasks
            if query_lower in t.title.lower() or (t.body and query_lower in t.body.lower())
        ]
    
    async def get_due_today(self, list_id: str = None) -> List[TodoTask]:
        """Get tasks due today."""
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        tasks = await self.list_tasks(list_id=list_id, include_completed=False)
        today = date.today()
        return [t for t in tasks if t.due_date == today]
    
    async def get_overdue(self, list_id: str = None) -> List[TodoTask]:
        """Get overdue tasks."""
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        tasks = await self.list_tasks(list_id=list_id, include_completed=False)
        today = date.today()
        return [t for t in tasks if t.due_date and t.due_date < today]
    
    async def get_upcoming(
        self,
        days: int = 7,
        list_id: str = None,
    ) -> List[TodoTask]:
        """Get tasks due in the next N days."""
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        tasks = await self.list_tasks(list_id=list_id, include_completed=False)
        today = date.today()
        end_date = today + timedelta(days=days)
        
        return [
            t for t in tasks
            if t.due_date and today <= t.due_date <= end_date
        ]


# Recurrence helpers for To-Do
def daily_recurrence(interval: int = 1) -> Dict:
    """Create daily recurrence."""
    return {
        "pattern": {
            "type": "daily",
            "interval": interval,
        },
        "range": {"type": "noEnd"},
    }


def weekly_recurrence(days: List[str], interval: int = 1) -> Dict:
    """
    Create weekly recurrence.
    
    Args:
        days: List of day names (sunday, monday, etc.)
        interval: Week interval
    """
    return {
        "pattern": {
            "type": "weekly",
            "interval": interval,
            "daysOfWeek": days,
        },
        "range": {"type": "noEnd"},
    }


def monthly_recurrence(day_of_month: int, interval: int = 1) -> Dict:
    """Create monthly recurrence on specific day."""
    return {
        "pattern": {
            "type": "absoluteMonthly",
            "interval": interval,
            "dayOfMonth": day_of_month,
        },
        "range": {"type": "noEnd"},
    }
