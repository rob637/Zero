"""
Skill System - The foundation of Apex's extensibility

Every capability in Apex is a Skill. Adding new features = adding new Skill classes.
The registry routes user requests to the appropriate skill.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable
from enum import Enum


class ActionType(Enum):
    """Types of actions a skill can propose."""
    MOVE = "move"
    DELETE = "delete"  # Always means "move to Recycle Bin"
    CREATE_FOLDER = "create_folder"
    RENAME = "rename"
    COPY = "copy"
    # Add more as skills need them


@dataclass
class ProposedAction:
    """
    A single action the AI wants to take.
    
    CRITICAL: Actions are PROPOSALS, never executed without user approval.
    """
    action_type: ActionType
    source: str
    destination: str | None = None
    reason: str = ""
    risk_level: str = "low"  # low, medium, high
    reversible: bool = True


@dataclass
class ActionPlan:
    """
    A complete plan of actions for user approval.
    
    This is what gets shown in the approval dialog.
    """
    summary: str
    reasoning: str
    actions: list[ProposedAction] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    affected_files_count: int = 0
    space_freed_estimate: str = "0 MB"
    
    def to_display_dict(self) -> dict:
        """Format for showing in approval UI."""
        return {
            "summary": self.summary,
            "reasoning": self.reasoning,
            "warnings": self.warnings,
            "actions": [
                {
                    "type": a.action_type.value,
                    "source": a.source,
                    "destination": a.destination,
                    "reason": a.reason,
                    "risk": a.risk_level,
                }
                for a in self.actions
            ],
            "stats": {
                "files": self.affected_files_count,
                "space": self.space_freed_estimate,
            }
        }


class Skill(ABC):
    """
    Base class for all Apex capabilities.
    
    To add a new capability to Apex:
    1. Create a new class that inherits from Skill
    2. Implement the required methods
    3. Register it with the SkillRegistry
    
    That's it. No rewrites, no touching other code.
    """
    
    # Subclasses must define these
    name: str = "base_skill"
    description: str = "Base skill class"
    version: str = "0.1.0"
    
    # What triggers this skill (for intent matching)
    trigger_phrases: list[str] = []
    
    # Required permissions
    permissions: list[str] = []  # e.g., ["filesystem.read", "filesystem.write"]
    
    @abstractmethod
    async def analyze(self, request: str, context: dict) -> ActionPlan:
        """
        Analyze the user's request and generate a plan.
        
        NEVER execute anything here. Only propose actions.
        
        Args:
            request: Natural language request from user
            context: Additional context (files, memory, etc.)
            
        Returns:
            ActionPlan with proposed actions for user approval
        """
        pass
    
    @abstractmethod
    async def execute(self, plan: ActionPlan, approved_actions: list[int]) -> dict:
        """
        Execute the approved actions from a plan.
        
        Only called AFTER user approval. Only executes the specific
        action indices the user approved.
        
        Args:
            plan: The original plan
            approved_actions: Indices of actions the user approved
            
        Returns:
            Execution result with success/failure for each action
        """
        pass
    
    def can_handle(self, request: str) -> float:
        """
        Return confidence (0-1) that this skill can handle the request.
        
        Used by SkillRegistry to route requests.
        Override for smarter matching.
        """
        request_lower = request.lower()
        for phrase in self.trigger_phrases:
            if phrase.lower() in request_lower:
                return 0.8
        return 0.0
    
    async def get_context(self) -> dict:
        """
        Gather context needed for analysis.
        Override to add skill-specific context gathering.
        """
        return {}


class SkillRegistry:
    """
    Routes user requests to the appropriate skill.
    
    The registry is the "router" of Apex. It:
    1. Receives a natural language request
    2. Asks each skill "can you handle this?"
    3. Routes to the most confident skill
    4. Returns the skill's proposed plan
    """
    
    def __init__(self):
        self._skills: dict[str, Skill] = {}
        self._fallback: Skill | None = None
    
    def register(self, skill: Skill) -> None:
        """Register a skill with the registry."""
        self._skills[skill.name] = skill
        print(f"[SkillRegistry] Registered: {skill.name} v{skill.version}")
    
    def set_fallback(self, skill: Skill) -> None:
        """Set a fallback skill for unmatched requests."""
        self._fallback = skill
    
    def get_skill(self, name: str) -> Skill | None:
        """Get a skill by name."""
        return self._skills.get(name)
    
    def list_skills(self) -> list[dict]:
        """List all registered skills."""
        return [
            {
                "name": s.name,
                "description": s.description,
                "version": s.version,
                "permissions": s.permissions,
            }
            for s in self._skills.values()
        ]
    
    async def route(self, request: str) -> tuple[Skill | None, float]:
        """
        Find the best skill to handle a request.
        
        Returns:
            Tuple of (skill, confidence) or (None, 0) if no match
        """
        best_skill = None
        best_confidence = 0.0
        
        for skill in self._skills.values():
            confidence = skill.can_handle(request)
            if confidence > best_confidence:
                best_confidence = confidence
                best_skill = skill
        
        # Use fallback if no good match
        if best_confidence < 0.3 and self._fallback:
            return self._fallback, 0.3
        
        return best_skill, best_confidence
    
    async def process_request(self, request: str) -> ActionPlan | None:
        """
        Process a user request end-to-end (analysis only).
        
        Returns an ActionPlan for user approval.
        Does NOT execute anything.
        """
        skill, confidence = await self.route(request)
        
        if not skill:
            return ActionPlan(
                summary="I'm not sure how to help with that.",
                reasoning="No skill matched your request with sufficient confidence.",
                warnings=["Try rephrasing or ask what I can do."],
            )
        
        context = await skill.get_context()
        return await skill.analyze(request, context)


# Global registry instance
registry = SkillRegistry()


def register_skill(skill: Skill) -> Skill:
    """Decorator/function to register a skill."""
    registry.register(skill)
    return skill
