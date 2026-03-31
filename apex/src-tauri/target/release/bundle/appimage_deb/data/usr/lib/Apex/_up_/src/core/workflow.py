"""
Workflow Engine - Chain skills together for compound intelligence

This is what transforms Apex from "utility app" to "brain":
- Skills can pass data to each other
- Complex requests become multi-step workflows
- Each step still requires approval (trust through transparency)

Example workflow:
  "Create an itinerary from my travel emails"
  
  Step 1: Gmail skill → finds travel confirmations
  Step 2: Extract skill → pulls dates, flights, hotels  
  Step 3: Document skill → creates formatted itinerary
  
  User approves at each step (or approves entire workflow)
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable

from .skill import Skill, ActionPlan, registry


class WorkflowStepStatus(Enum):
    """Status of a workflow step."""
    PENDING = "pending"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class WorkflowStep:
    """A single step in a workflow."""
    id: str
    skill_name: str
    description: str
    input_data: dict = field(default_factory=dict)
    output_data: dict = field(default_factory=dict)
    plan: ActionPlan | None = None
    status: WorkflowStepStatus = WorkflowStepStatus.PENDING
    error: str | None = None
    approved_indices: list[int] = field(default_factory=list)


@dataclass 
class Workflow:
    """A multi-step workflow that chains skills together."""
    id: str
    name: str
    description: str
    steps: list[WorkflowStep]
    context: dict = field(default_factory=dict)  # Shared data between steps
    created_at: str = ""
    current_step: int = 0
    completed: bool = False
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
    
    def get_current_step(self) -> WorkflowStep | None:
        """Get the current step to execute."""
        if self.current_step < len(self.steps):
            return self.steps[self.current_step]
        return None
    
    def advance(self) -> bool:
        """Move to next step. Returns False if workflow complete."""
        self.current_step += 1
        if self.current_step >= len(self.steps):
            self.completed = True
            return False
        return True
    
    def to_display_dict(self) -> dict:
        """Convert to dict for UI display."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "current_step": self.current_step,
            "total_steps": len(self.steps),
            "completed": self.completed,
            "steps": [
                {
                    "id": s.id,
                    "skill": s.skill_name,
                    "description": s.description,
                    "status": s.status.value,
                    "has_plan": s.plan is not None,
                    "error": s.error,
                }
                for s in self.steps
            ],
            "context_keys": list(self.context.keys()),
        }


# ============================================
# Pre-defined Workflow Templates
# ============================================

WORKFLOW_TEMPLATES = {
    "travel_itinerary": {
        "name": "Create Travel Itinerary",
        "description": "Search emails for travel bookings and create an organized itinerary",
        "triggers": ["itinerary", "travel", "trip", "vacation", "flight"],
        "steps": [
            {
                "skill": "gmail",
                "description": "Find travel confirmation emails",
                "input": {"search_type": "travel"},
            },
            {
                "skill": "document",
                "description": "Create formatted itinerary",
                "input": {"doc_type": "itinerary"},
                "uses_context": ["email_data"],  # Gets data from previous step
            },
        ],
    },
    
    "pc_cleanup": {
        "name": "Full PC Cleanup",
        "description": "Comprehensive cleanup: temp files, duplicates, disk analysis",
        "triggers": ["full cleanup", "deep clean", "clean everything"],
        "steps": [
            {
                "skill": "disk_analyzer",
                "description": "Analyze disk usage and find space wasters",
                "input": {},
            },
            {
                "skill": "temp_cleaner",
                "description": "Clean temporary files and caches",
                "input": {},
            },
            {
                "skill": "duplicate_finder",
                "description": "Find and remove duplicate files",
                "input": {"target": "~"},
            },
        ],
    },
    
    "photo_cleanup": {
        "name": "Photo Library Cleanup",
        "description": "Organize photos, remove duplicates, separate screenshots",
        "triggers": ["photo cleanup", "organize all photos", "photo library"],
        "steps": [
            {
                "skill": "photo_organizer",
                "description": "Organize photos by date and separate screenshots",
                "input": {},
            },
            {
                "skill": "duplicate_finder",
                "description": "Find duplicate photos",
                "input": {"target": "Pictures", "extensions": [".jpg", ".png", ".heic"]},
            },
        ],
    },
    
    "weekly_maintenance": {
        "name": "Weekly PC Maintenance",
        "description": "Regular maintenance: clean temps, organize downloads, check disk",
        "triggers": ["weekly", "maintenance", "regular cleanup"],
        "steps": [
            {
                "skill": "temp_cleaner",
                "description": "Clean temporary files",
                "input": {},
            },
            {
                "skill": "file_organizer",
                "description": "Organize Downloads folder",
                "input": {"target": "Downloads"},
            },
            {
                "skill": "disk_analyzer",
                "description": "Check disk health",
                "input": {},
            },
        ],
    },
}


class WorkflowEngine:
    """
    Orchestrates multi-step workflows.
    
    The workflow engine is what makes Apex a "brain" instead of
    a collection of utilities. It:
    
    1. Detects when a request needs multiple skills
    2. Creates a workflow with connected steps
    3. Passes data between steps via shared context
    4. Maintains approval flow at each step
    """
    
    def __init__(self):
        self._workflows: dict[str, Workflow] = {}
        self._workflow_counter = 0
    
    def _generate_id(self) -> str:
        """Generate unique workflow ID."""
        self._workflow_counter += 1
        return f"wf_{self._workflow_counter}_{datetime.now().strftime('%H%M%S')}"
    
    def detect_workflow(self, request: str) -> str | None:
        """
        Detect if a request should trigger a workflow.
        
        Returns the workflow template name, or None for single-skill requests.
        """
        request_lower = request.lower()
        
        for template_name, template in WORKFLOW_TEMPLATES.items():
            for trigger in template["triggers"]:
                if trigger in request_lower:
                    return template_name
        
        return None
    
    def create_workflow(self, template_name: str, context: dict = None) -> Workflow:
        """
        Create a workflow from a template.
        
        Args:
            template_name: Name of the workflow template
            context: Initial context data
            
        Returns:
            New Workflow instance ready for execution
        """
        template = WORKFLOW_TEMPLATES.get(template_name)
        if not template:
            raise ValueError(f"Unknown workflow template: {template_name}")
        
        workflow_id = self._generate_id()
        
        steps = []
        for i, step_def in enumerate(template["steps"]):
            step = WorkflowStep(
                id=f"{workflow_id}_step_{i}",
                skill_name=step_def["skill"],
                description=step_def["description"],
                input_data=step_def.get("input", {}),
            )
            steps.append(step)
        
        workflow = Workflow(
            id=workflow_id,
            name=template["name"],
            description=template["description"],
            steps=steps,
            context=context or {},
        )
        
        self._workflows[workflow_id] = workflow
        return workflow
    
    async def analyze_step(self, workflow: Workflow) -> WorkflowStep:
        """
        Analyze the current step of a workflow.
        
        Gets the skill, prepares input from workflow context,
        and generates an action plan for user approval.
        """
        step = workflow.get_current_step()
        if not step:
            raise ValueError("Workflow has no more steps")
        
        # Get the skill
        skill = registry.get_skill(step.skill_name)
        if not skill:
            step.status = WorkflowStepStatus.FAILED
            step.error = f"Skill not found: {step.skill_name}"
            return step
        
        # Merge workflow context into step input
        step_context = {**workflow.context, **step.input_data}
        
        try:
            # Generate plan
            plan = await skill.analyze(
                step.description,
                step_context,
            )
            step.plan = plan
            step.status = WorkflowStepStatus.AWAITING_APPROVAL
            
        except Exception as e:
            step.status = WorkflowStepStatus.FAILED
            step.error = str(e)
        
        return step
    
    async def execute_step(
        self, 
        workflow: Workflow, 
        approved_indices: list[int] = None
    ) -> WorkflowStep:
        """
        Execute the current approved step.
        
        Runs the skill with approved actions, captures output data,
        and stores it in workflow context for subsequent steps.
        """
        step = workflow.get_current_step()
        if not step or not step.plan:
            raise ValueError("No step or plan to execute")
        
        skill = registry.get_skill(step.skill_name)
        if not skill:
            step.status = WorkflowStepStatus.FAILED
            step.error = f"Skill not found: {step.skill_name}"
            return step
        
        # Default to all actions if none specified
        if approved_indices is None:
            approved_indices = list(range(len(step.plan.actions)))
        
        step.approved_indices = approved_indices
        step.status = WorkflowStepStatus.EXECUTING
        
        try:
            # Execute
            result = await skill.execute(step.plan, approved_indices)
            
            # Store output
            step.output_data = result
            step.status = WorkflowStepStatus.COMPLETED
            
            # Merge relevant output into workflow context
            # This is how data flows between steps
            self._update_workflow_context(workflow, step, result)
            
        except Exception as e:
            step.status = WorkflowStepStatus.FAILED
            step.error = str(e)
        
        return step
    
    def _update_workflow_context(
        self, 
        workflow: Workflow, 
        step: WorkflowStep, 
        result: dict
    ) -> None:
        """
        Update workflow context with step output.
        
        This is the "data bridge" between skills. For example:
        - Gmail skill outputs email_data
        - Document skill reads email_data from context
        """
        # Store full result
        workflow.context[f"step_{step.id}_result"] = result
        
        # Extract specific data based on skill
        if step.skill_name == "gmail":
            # Gmail outputs email data for other skills to use
            if "emails" in result:
                workflow.context["email_data"] = result["emails"]
            if "travel_info" in result:
                workflow.context["travel_info"] = result["travel_info"]
                
        elif step.skill_name == "disk_analyzer":
            # Disk analyzer outputs findings
            if "space_wasters" in result:
                workflow.context["space_wasters"] = result.get("space_wasters", [])
            if "total_freed" in result:
                workflow.context["total_freed"] = result.get("total_freed", 0)
                
        elif step.skill_name == "document":
            # Document skill outputs file path
            if "file_path" in result:
                workflow.context["created_document"] = result["file_path"]
    
    def skip_step(self, workflow: Workflow) -> WorkflowStep:
        """Skip the current step and move to next."""
        step = workflow.get_current_step()
        if step:
            step.status = WorkflowStepStatus.SKIPPED
        return step
    
    def get_workflow(self, workflow_id: str) -> Workflow | None:
        """Get a workflow by ID."""
        return self._workflows.get(workflow_id)
    
    def get_workflow_summary(self, workflow: Workflow) -> str:
        """Get a human-readable summary of workflow progress."""
        completed = sum(1 for s in workflow.steps if s.status == WorkflowStepStatus.COMPLETED)
        total = len(workflow.steps)
        
        lines = [
            f"**{workflow.name}** ({completed}/{total} steps complete)",
            "",
        ]
        
        for i, step in enumerate(workflow.steps):
            status_icon = {
                WorkflowStepStatus.PENDING: "⏳",
                WorkflowStepStatus.AWAITING_APPROVAL: "🔔",
                WorkflowStepStatus.APPROVED: "✅",
                WorkflowStepStatus.EXECUTING: "⚙️",
                WorkflowStepStatus.COMPLETED: "✓",
                WorkflowStepStatus.SKIPPED: "⏭️",
                WorkflowStepStatus.FAILED: "❌",
            }.get(step.status, "?")
            
            current = " ← current" if i == workflow.current_step and not workflow.completed else ""
            lines.append(f"{status_icon} Step {i+1}: {step.description}{current}")
        
        return "\n".join(lines)


# Global workflow engine instance
workflow_engine = WorkflowEngine()
