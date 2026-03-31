"""
Task Planner - The LLM-Powered Decomposition Engine

This is what makes skills transferable.

Instead of building a skill for every scenario, we:
1. Define primitive capabilities (FILE, DOCUMENT, COMPUTE, EMAIL, etc.)
2. Use the LLM to decompose any request into primitives
3. Execute the plan step by step
4. Learn from the execution

The LLM is the "glue" that composes primitives into workflows.

Example:
    User: "Create amortization from loan doc, email to Fred"
    
    LLM decomposes to:
    1. FILE.search(pattern="*loan*")
    2. DOCUMENT.parse(path=<found_file>)
    3. DOCUMENT.extract(content=<parsed>, schema={"principal", "rate", "term"})
    4. COMPUTE.formula(name="amortization", inputs=<extracted>)
    5. DOCUMENT.create(format="csv", data=<schedule>)
    6. CONTACTS.search(query="Fred")
    7. EMAIL.send(to=<fred_email>, subject="Amortization", attachment=<csv>)
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Callable
import hashlib

from .primitives import PrimitiveRegistry, PrimitiveResult

logger = logging.getLogger(__name__)


class StepStatus(Enum):
    """Status of a plan step."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PlanStep:
    """A single step in an execution plan."""
    id: str
    description: str
    
    # What to execute
    primitive: str  # e.g., "FILE", "DOCUMENT"
    operation: str  # e.g., "search", "extract"
    parameters: Dict[str, Any]
    
    # Dependencies (step IDs that must complete first)
    depends_on: List[str] = field(default_factory=list)
    
    # Execution state
    status: StepStatus = StepStatus.PENDING
    result: Optional[PrimitiveResult] = None
    error: Optional[str] = None
    
    # Timing
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "primitive": self.primitive,
            "operation": self.operation,
            "parameters": self.parameters,
            "depends_on": self.depends_on,
            "status": self.status.value,
            "result": self.result.to_dict() if self.result else None,
            "error": self.error,
        }


@dataclass
class ExecutionPlan:
    """A plan for executing a user request."""
    id: str
    request: str
    steps: List[PlanStep]
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    
    # State
    status: str = "pending"  # pending, running, completed, failed
    final_result: Optional[Any] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "request": self.request,
            "steps": [s.to_dict() for s in self.steps],
            "status": self.status,
            "final_result": self.final_result,
        }


class TaskPlanner:
    """
    The LLM-powered task planner.
    
    Takes natural language requests and decomposes them into
    executable plans using primitives.
    """
    
    def __init__(
        self,
        llm_client,
        primitive_registry: PrimitiveRegistry,
    ):
        self._llm = llm_client
        self._primitives = primitive_registry
        
        # Execution history for learning
        self._history: List[ExecutionPlan] = []
    
    async def plan(self, request: str, context: Optional[Dict[str, Any]] = None) -> ExecutionPlan:
        """
        Create an execution plan for a request.
        
        Uses the LLM to decompose the request into primitive operations.
        """
        # Build the planning prompt
        capabilities = self._primitives.get_capabilities_prompt()
        
        prompt = f"""You are a task planner. Decompose the user's request into a sequence of primitive operations.

{capabilities}

IMPORTANT RULES:
1. Each step should use exactly ONE primitive and ONE operation
2. Use {{{{step_N}}}} to reference the result of step N (e.g., {{{{step_1}}}} for step 1's result)
3. Be specific about parameters
4. List dependencies if a step needs results from previous steps

User Request: {request}

{f"Context: {json.dumps(context)}" if context else ""}

Respond with a JSON array of steps. Each step should have:
- description: What this step does (human readable)
- primitive: The primitive name (FILE, DOCUMENT, COMPUTE, EMAIL, CALENDAR, CONTACTS, KNOWLEDGE)
- operation: The operation to perform
- parameters: Object with parameters for the operation
- depends_on: Array of step numbers this depends on (0-indexed)

Example response:
[
  {{
    "description": "Search for loan documents",
    "primitive": "FILE",
    "operation": "search",
    "parameters": {{"pattern": "*loan*.pdf", "directory": "~/Documents"}},
    "depends_on": []
  }},
  {{
    "description": "Parse the loan document",
    "primitive": "DOCUMENT",
    "operation": "parse",
    "parameters": {{"path": "{{{{step_0}}}}"}},
    "depends_on": [0]
  }}
]

ONLY respond with the JSON array, no other text."""

        # Get plan from LLM
        response = await self._llm.complete(prompt)
        
        # Parse the plan
        steps = self._parse_plan_response(response, request)
        
        # Create execution plan
        plan = ExecutionPlan(
            id=hashlib.md5(f"{request}_{datetime.now().isoformat()}".encode()).hexdigest()[:12],
            request=request,
            steps=steps,
        )
        
        return plan
    
    def _parse_plan_response(self, response: str, request: str) -> List[PlanStep]:
        """Parse LLM response into plan steps."""
        steps = []
        
        try:
            # Find JSON array in response
            json_match = re.search(r'\[[\s\S]*\]', response)
            if not json_match:
                logger.error(f"No JSON array found in response: {response[:200]}")
                return self._create_fallback_plan(request)
            
            step_data = json.loads(json_match.group())
            
            for i, data in enumerate(step_data):
                step = PlanStep(
                    id=f"step_{i}",
                    description=data.get("description", f"Step {i}"),
                    primitive=data.get("primitive", "").upper(),
                    operation=data.get("operation", ""),
                    parameters=data.get("parameters", {}),
                    depends_on=[f"step_{d}" for d in data.get("depends_on", [])],
                )
                steps.append(step)
                
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse plan JSON: {e}")
            return self._create_fallback_plan(request)
        
        return steps
    
    def _create_fallback_plan(self, request: str) -> List[PlanStep]:
        """Create a simple fallback plan when parsing fails."""
        return [
            PlanStep(
                id="step_0",
                description=f"Process request: {request[:50]}",
                primitive="KNOWLEDGE",
                operation="recall",
                parameters={"query": request},
            )
        ]
    
    async def execute(
        self,
        plan: ExecutionPlan,
        on_step_complete: Optional[Callable[[PlanStep], None]] = None,
        require_approval: bool = False,
        approval_callback: Optional[Callable[[PlanStep], bool]] = None,
    ) -> ExecutionPlan:
        """
        Execute a plan step by step.
        
        Args:
            plan: The plan to execute
            on_step_complete: Callback after each step completes
            require_approval: Whether to require approval before risky steps
            approval_callback: Function to call for approval
        
        Returns:
            The updated plan with results
        """
        plan.status = "running"
        step_results: Dict[str, Any] = {}
        
        for step in plan.steps:
            # Check dependencies
            for dep_id in step.depends_on:
                dep_step = next((s for s in plan.steps if s.id == dep_id), None)
                if dep_step and dep_step.status != StepStatus.COMPLETED:
                    step.status = StepStatus.SKIPPED
                    step.error = f"Dependency {dep_id} not completed"
                    continue
            
            # Resolve parameter references
            resolved_params = self._resolve_parameters(step.parameters, step_results)
            
            # Check if approval needed
            if require_approval and self._is_risky_operation(step):
                if approval_callback:
                    approved = approval_callback(step)
                    if not approved:
                        step.status = StepStatus.SKIPPED
                        step.error = "User declined"
                        continue
            
            # Execute the step
            step.status = StepStatus.RUNNING
            step.started_at = datetime.now()
            
            try:
                result = await self._primitives.execute(
                    step.primitive,
                    step.operation,
                    resolved_params,
                )
                
                step.result = result
                step_results[step.id] = result.data
                
                if result.success:
                    step.status = StepStatus.COMPLETED
                else:
                    step.status = StepStatus.FAILED
                    step.error = result.error
                    
            except Exception as e:
                step.status = StepStatus.FAILED
                step.error = str(e)
                logger.error(f"Step {step.id} failed: {e}")
            
            step.completed_at = datetime.now()
            
            # Callback
            if on_step_complete:
                on_step_complete(step)
            
            # If step failed, decide whether to continue
            if step.status == StepStatus.FAILED:
                # For now, continue with other steps
                # Could implement more sophisticated error handling
                pass
        
        # Determine final status
        failed_steps = [s for s in plan.steps if s.status == StepStatus.FAILED]
        if failed_steps:
            plan.status = "partial" if any(s.status == StepStatus.COMPLETED for s in plan.steps) else "failed"
        else:
            plan.status = "completed"
        
        # Set final result (last step's result)
        completed_steps = [s for s in plan.steps if s.status == StepStatus.COMPLETED]
        if completed_steps:
            plan.final_result = completed_steps[-1].result.data if completed_steps[-1].result else None
        
        plan.completed_at = datetime.now()
        
        # Store in history for learning
        self._history.append(plan)
        
        return plan
    
    def _resolve_parameters(self, params: Dict[str, Any], step_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolve parameter references like {{step_0}} to actual values.
        """
        resolved = {}
        
        for key, value in params.items():
            if isinstance(value, str):
                # Check for step references
                pattern = r'\{\{step_(\d+)\}\}'
                matches = re.findall(pattern, value)
                
                if matches:
                    for match in matches:
                        step_id = f"step_{match}"
                        if step_id in step_results:
                            result = step_results[step_id]
                            
                            # If the entire value is just a reference, replace with the full result
                            if value == f"{{{{step_{match}}}}}":
                                value = result
                            else:
                                # Otherwise, string substitute
                                value = value.replace(f"{{{{step_{match}}}}}", str(result))
                
                resolved[key] = value
            elif isinstance(value, dict):
                resolved[key] = self._resolve_parameters(value, step_results)
            elif isinstance(value, list):
                resolved[key] = [
                    self._resolve_parameters({"v": v}, step_results)["v"] if isinstance(v, (str, dict)) else v
                    for v in value
                ]
            else:
                resolved[key] = value
        
        return resolved
    
    def _is_risky_operation(self, step: PlanStep) -> bool:
        """Determine if an operation needs user approval."""
        risky_operations = {
            "FILE": ["write", "delete", "move"],
            "EMAIL": ["send"],
            "CALENDAR": ["create", "update", "delete"],
        }
        
        return step.operation in risky_operations.get(step.primitive, [])
    
    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent execution history."""
        return [p.to_dict() for p in self._history[-limit:]]


# ============================================================
#  PLANNER PROMPT TEMPLATES
# ============================================================

DECOMPOSITION_EXAMPLES = """
EXAMPLE 1:
Request: "Find all PDFs in Downloads and move them to Documents/PDFs"
Plan:
1. FILE.search(pattern="*.pdf", directory="~/Downloads")
2. FILE.move(source={{step_0}}, destination="~/Documents/PDFs")

EXAMPLE 2:
Request: "Read the loan document and calculate monthly payments"
Plan:
1. FILE.search(pattern="*loan*", directory="~/Documents")
2. DOCUMENT.parse(path={{step_0}})
3. DOCUMENT.extract(content={{step_1}}, schema={"principal": "number", "rate": "number", "term_months": "number"})
4. COMPUTE.formula(name="amortization", inputs={{step_2}})

EXAMPLE 3:
Request: "Email the Q3 report to John"
Plan:
1. FILE.search(pattern="*Q3*report*")
2. CONTACTS.search(query="John")
3. EMAIL.send(to={{step_1}}.email, subject="Q3 Report", body="Please find the Q3 report attached.", attachments=[{{step_0}}])

EXAMPLE 4:
Request: "What meetings do I have tomorrow?"
Plan:
1. CALENDAR.list(start="tomorrow 00:00", end="tomorrow 23:59")

EXAMPLE 5:
Request: "Remember that I prefer meetings in the morning"
Plan:
1. KNOWLEDGE.remember(content="User prefers meetings in the morning", tags=["preference", "scheduling"])
"""


# ============================================================
#  FACTORY
# ============================================================

def create_planner(llm_client, primitive_registry: PrimitiveRegistry) -> TaskPlanner:
    """Create a task planner."""
    return TaskPlanner(llm_client, primitive_registry)
