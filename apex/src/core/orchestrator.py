"""
Orchestrator - Task planning and execution coordinator

The orchestrator:
1. Receives user requests
2. Uses the SkillRegistry to generate plans
3. Presents plans for user approval
4. Coordinates execution of approved actions
5. Handles errors and rollback

This is the "conductor" that makes everything work together.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Any

from .skill import SkillRegistry, ActionPlan, Skill, registry


class TaskStatus(Enum):
    """Status of a task in the orchestrator."""
    PENDING = "pending"
    ANALYZING = "analyzing"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    """A task being processed by the orchestrator."""
    id: str
    request: str
    status: TaskStatus = TaskStatus.PENDING
    skill: Skill | None = None
    plan: ActionPlan | None = None
    approved_actions: list[int] = field(default_factory=list)
    result: dict | None = None
    error: str | None = None
    created_at: str = ""
    completed_at: str | None = None
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


class Orchestrator:
    """
    Coordinates task processing in Apex.
    
    Usage:
        orch = Orchestrator()
        
        # Submit a request
        task = await orch.submit("Clean up my downloads")
        
        # Task now has a plan awaiting approval
        print(task.plan.to_display_dict())
        
        # User approves some or all actions
        await orch.approve(task.id, approved_indices=[0, 1, 2])
        
        # Or user rejects
        await orch.reject(task.id)
    """
    
    def __init__(self, skill_registry: SkillRegistry = None):
        """
        Initialize orchestrator.
        
        Args:
            skill_registry: Registry to use. Defaults to global registry.
        """
        self.registry = skill_registry or registry
        self._tasks: dict[str, Task] = {}
        self._task_counter = 0
        
        # Callbacks for UI integration
        self._on_plan_ready: Callable[[Task], None] | None = None
        self._on_execution_complete: Callable[[Task], None] | None = None
        self._on_error: Callable[[Task, str], None] | None = None
    
    def set_callbacks(
        self,
        on_plan_ready: Callable[[Task], None] = None,
        on_execution_complete: Callable[[Task], None] = None,
        on_error: Callable[[Task, str], None] = None,
    ) -> None:
        """Set callbacks for UI integration."""
        self._on_plan_ready = on_plan_ready
        self._on_execution_complete = on_execution_complete
        self._on_error = on_error
    
    def _generate_task_id(self) -> str:
        """Generate a unique task ID."""
        self._task_counter += 1
        return f"task_{self._task_counter}_{datetime.now().strftime('%H%M%S')}"
    
    async def submit(self, request: str) -> Task:
        """
        Submit a new request for processing.
        
        This will:
        1. Create a task
        2. Route to the appropriate skill
        3. Generate an action plan
        4. Return the task (now awaiting approval)
        
        Args:
            request: Natural language request from user
            
        Returns:
            Task with plan ready for approval
        """
        # Create task
        task = Task(
            id=self._generate_task_id(),
            request=request,
            status=TaskStatus.ANALYZING,
        )
        self._tasks[task.id] = task
        
        try:
            # Route to skill
            skill, confidence = await self.registry.route(request)
            task.skill = skill
            
            if not skill:
                task.status = TaskStatus.FAILED
                task.error = "No skill could handle this request"
                if self._on_error:
                    self._on_error(task, task.error)
                return task
            
            # Generate plan
            context = await skill.get_context()
            plan = await skill.analyze(request, context)
            
            task.plan = plan
            task.status = TaskStatus.AWAITING_APPROVAL
            
            if self._on_plan_ready:
                self._on_plan_ready(task)
            
            return task
            
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            if self._on_error:
                self._on_error(task, task.error)
            return task
    
    async def approve(self, task_id: str, approved_indices: list[int] = None) -> Task:
        """
        Approve a task's plan (or specific actions).
        
        Args:
            task_id: ID of task to approve
            approved_indices: Which action indices to execute.
                              None = approve all.
            
        Returns:
            Updated task after execution
        """
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")
        
        if task.status != TaskStatus.AWAITING_APPROVAL:
            raise ValueError(f"Task is not awaiting approval: {task.status}")
        
        # Default to all actions if none specified
        if approved_indices is None:
            approved_indices = list(range(len(task.plan.actions)))
        
        task.approved_actions = approved_indices
        task.status = TaskStatus.EXECUTING
        
        try:
            # Execute approved actions
            result = await task.skill.execute(task.plan, approved_indices)
            
            task.result = result
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now().isoformat()
            
            if self._on_execution_complete:
                self._on_execution_complete(task)
            
            return task
            
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            if self._on_error:
                self._on_error(task, task.error)
            return task
    
    async def reject(self, task_id: str, reason: str = None) -> Task:
        """
        Reject/cancel a task.
        
        Args:
            task_id: ID of task to reject
            reason: Optional reason for rejection
            
        Returns:
            Updated task
        """
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")
        
        task.status = TaskStatus.CANCELLED
        task.completed_at = datetime.now().isoformat()
        if reason:
            task.error = f"Rejected: {reason}"
        
        return task
    
    def get_task(self, task_id: str) -> Task | None:
        """Get a task by ID."""
        return self._tasks.get(task_id)
    
    def get_pending_tasks(self) -> list[Task]:
        """Get all tasks awaiting approval."""
        return [
            t for t in self._tasks.values()
            if t.status == TaskStatus.AWAITING_APPROVAL
        ]
    
    def get_history(self, limit: int = 20) -> list[Task]:
        """Get recent completed/failed tasks."""
        completed = [
            t for t in self._tasks.values()
            if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
        ]
        # Sort by completion time, most recent first
        completed.sort(key=lambda t: t.completed_at or "", reverse=True)
        return completed[:limit]


# Global orchestrator instance
orchestrator = Orchestrator()
