"""
Reasoning Engine - How the brain thinks.

This is where thinking happens:
- Forming hypotheses about what's going on
- Chaining thoughts together
- Drawing inferences from knowledge
- Planning courses of action
- Evaluating options

This implements:
1. Hypothesis generation
2. Reasoning chains
3. Goal decomposition
4. Inference
5. Decision making
"""

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class ReasoningType(Enum):
    """Types of reasoning."""
    DEDUCTIVE = "deductive"        # A implies B, A is true, therefore B
    INDUCTIVE = "inductive"        # Pattern recognition, generalization
    ABDUCTIVE = "abductive"        # Best explanation for observations
    ANALOGICAL = "analogical"      # Similar situation, similar solution
    CAUSAL = "causal"              # Understanding cause and effect
    PLANNING = "planning"          # Achieving goals
    EVALUATIVE = "evaluative"      # Judging options


class ConfidenceLevel(Enum):
    """Confidence in reasoning."""
    CERTAIN = 0.95
    HIGH = 0.8
    MODERATE = 0.6
    LOW = 0.4
    SPECULATIVE = 0.2


@dataclass
class Hypothesis:
    """
    A hypothesis - a proposed explanation or prediction.
    
    Hypotheses drive reasoning by providing something
    to confirm, refine, or reject.
    """
    id: str
    statement: str                    # What we're hypothesizing
    reasoning_type: ReasoningType
    
    # Evidence
    supporting_evidence: List[str] = field(default_factory=list)
    contradicting_evidence: List[str] = field(default_factory=list)
    
    # Assessment
    confidence: float = 0.5          # 0-1
    tested: bool = False
    outcome: Optional[str] = None    # "confirmed", "rejected", "refined"
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    source_observations: List[str] = field(default_factory=list)
    
    def update_confidence(self):
        """Update confidence based on evidence."""
        support_score = len(self.supporting_evidence) * 0.15
        contradict_score = len(self.contradicting_evidence) * 0.2
        
        self.confidence = max(0.0, min(1.0, 0.5 + support_score - contradict_score))
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "statement": self.statement,
            "reasoning_type": self.reasoning_type.value,
            "confidence": self.confidence,
            "supporting_evidence": self.supporting_evidence,
            "contradicting_evidence": self.contradicting_evidence,
            "tested": self.tested,
            "outcome": self.outcome,
        }


@dataclass
class ThoughtStep:
    """
    A single step in a chain of reasoning.
    """
    id: str
    content: str                     # What is being thought
    step_type: str                   # "observation", "inference", "hypothesis", "action", "evaluation"
    
    # Connections
    inputs: List[str] = field(default_factory=list)   # What this step builds on
    outputs: List[str] = field(default_factory=list)  # What this step leads to
    
    # Assessment
    confidence: float = 0.7
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "type": self.step_type,
            "confidence": self.confidence,
        }


@dataclass
class ReasoningChain:
    """
    A chain of reasoning - connected thoughts leading to a conclusion.
    
    Reasoning chains are how the brain works through problems.
    """
    id: str
    goal: str                        # What are we trying to figure out
    reasoning_type: ReasoningType
    
    # The chain of thoughts
    steps: List[ThoughtStep] = field(default_factory=list)
    
    # Outcome
    conclusion: Optional[str] = None
    confidence: float = 0.5
    
    # Status
    status: str = "in_progress"      # "in_progress", "concluded", "stuck", "abandoned"
    
    # Metadata
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    
    def add_step(self, content: str, step_type: str, confidence: float = 0.7, builds_on: Optional[List[str]] = None) -> ThoughtStep:
        """Add a step to the reasoning chain."""
        step = ThoughtStep(
            id=f"{self.id}_{len(self.steps)}",
            content=content,
            step_type=step_type,
            confidence=confidence,
            inputs=builds_on or ([self.steps[-1].id] if self.steps else []),
        )
        
        # Link previous step to this one
        if self.steps and not builds_on:
            self.steps[-1].outputs.append(step.id)
        
        self.steps.append(step)
        
        # Update chain confidence
        self._update_confidence()
        
        return step
    
    def conclude(self, conclusion: str, confidence: float):
        """Mark the chain as concluded."""
        self.conclusion = conclusion
        self.confidence = confidence
        self.status = "concluded"
        self.completed_at = datetime.now()
    
    def _update_confidence(self):
        """Update chain confidence based on steps."""
        if not self.steps:
            return
        
        # Chain confidence is product of step confidences (weakest link)
        combined = 1.0
        for step in self.steps:
            combined *= step.confidence
        
        # But floor at lowest single confidence
        min_conf = min(s.confidence for s in self.steps)
        self.confidence = max(combined, min_conf * 0.8)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "reasoning_type": self.reasoning_type.value,
            "steps": [s.to_dict() for s in self.steps],
            "conclusion": self.conclusion,
            "confidence": self.confidence,
            "status": self.status,
        }


@dataclass
class Plan:
    """
    A plan - a sequence of actions to achieve a goal.
    """
    id: str
    goal: str
    
    # Actions
    actions: List[Dict[str, Any]] = field(default_factory=list)
    
    # Dependencies
    preconditions: List[str] = field(default_factory=list)
    postconditions: List[str] = field(default_factory=list)
    
    # Assessment
    feasibility: float = 0.5         # How likely to succeed
    cost: float = 0.5                # How much effort/resources
    
    # Status
    status: str = "proposed"         # "proposed", "approved", "executing", "completed", "failed"
    current_step: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "actions": self.actions,
            "feasibility": self.feasibility,
            "status": self.status,
            "current_step": self.current_step,
        }


class InferenceEngine:
    """
    Makes inferences from known facts.
    
    Supports:
    - Modus ponens (if A→B and A, then B)
    - Transitivity (if A→B and B→C, then A→C)
    - Pattern matching
    """
    
    def __init__(self):
        self._rules: List[Dict[str, Any]] = []
    
    def add_rule(self, condition: Callable, conclusion: str, confidence: float = 0.8):
        """Add an inference rule."""
        self._rules.append({
            "condition": condition,
            "conclusion": conclusion,
            "confidence": confidence,
        })
    
    def infer(self, facts: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate inferences from facts."""
        inferences = []
        
        for rule in self._rules:
            try:
                if rule["condition"](facts):
                    inferences.append({
                        "conclusion": rule["conclusion"],
                        "confidence": rule["confidence"],
                    })
            except Exception:
                pass
        
        return inferences


class ReasoningEngine:
    """
    The reasoning engine - the thinking core of the brain.
    
    This is where cognition happens:
    - Generating hypotheses
    - Building reasoning chains
    - Making plans
    - Drawing inferences
    - Evaluating options
    """
    
    def __init__(self):
        # Active reasoning
        self._active_chains: Dict[str, ReasoningChain] = {}
        self._hypotheses: Dict[str, Hypothesis] = {}
        self._plans: Dict[str, Plan] = {}
        
        # Inference engine
        self._inference = InferenceEngine()
        self._setup_default_rules()
        
        # Reasoning history
        self._history: List[Dict[str, Any]] = []
    
    def _setup_default_rules(self):
        """Setup default inference rules."""
        # Time pressure rule
        self._inference.add_rule(
            lambda f: f.get("deadline_days", 999) < 3,
            "This is time-sensitive and should be prioritized",
            0.8
        )
        
        # Communication rule
        self._inference.add_rule(
            lambda f: f.get("message_count", 0) > 5 and f.get("same_person", False),
            "This person is trying to reach you about something important",
            0.7
        )
        
        # Meeting prep rule
        self._inference.add_rule(
            lambda f: f.get("has_meeting_soon", False) and f.get("meeting_has_docs", True),
            "Review the relevant documents before the meeting",
            0.75
        )
    
    # === Hypothesis Generation ===
    
    def hypothesize(
        self,
        observations: List[str],
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Hypothesis]:
        """
        Generate hypotheses to explain observations.
        
        This is abductive reasoning - finding the best explanation.
        """
        hypotheses = []
        
        # Look for patterns in observations
        obs_text = " ".join(observations).lower()
        
        # Communication pattern
        if any(word in obs_text for word in ["email", "message", "call", "contact"]):
            if any(word in obs_text for word in ["multiple", "several", "many", "urgent"]):
                h = Hypothesis(
                    id=hashlib.md5(f"comm_{datetime.now().isoformat()}".encode()).hexdigest()[:12],
                    statement="Someone is trying to urgently reach you",
                    reasoning_type=ReasoningType.ABDUCTIVE,
                    source_observations=observations,
                    confidence=0.6,
                )
                hypotheses.append(h)
        
        # Deadline pattern
        if any(word in obs_text for word in ["deadline", "due", "submit", "complete"]):
            h = Hypothesis(
                id=hashlib.md5(f"deadline_{datetime.now().isoformat()}".encode()).hexdigest()[:12],
                statement="There's an upcoming deadline that needs attention",
                reasoning_type=ReasoningType.ABDUCTIVE,
                source_observations=observations,
                confidence=0.7,
            )
            hypotheses.append(h)
        
        # Meeting pattern
        if any(word in obs_text for word in ["meeting", "calendar", "schedule", "appointment"]):
            h = Hypothesis(
                id=hashlib.md5(f"meeting_{datetime.now().isoformat()}".encode()).hexdigest()[:12],
                statement="Preparation is needed for an upcoming meeting",
                reasoning_type=ReasoningType.ABDUCTIVE,
                source_observations=observations,
                confidence=0.6,
            )
            hypotheses.append(h)
        
        # Store hypotheses
        for h in hypotheses:
            self._hypotheses[h.id] = h
        
        return hypotheses
    
    def test_hypothesis(self, hypothesis_id: str, evidence: str, supports: bool):
        """Add evidence to a hypothesis."""
        h = self._hypotheses.get(hypothesis_id)
        if not h:
            return
        
        if supports:
            h.supporting_evidence.append(evidence)
        else:
            h.contradicting_evidence.append(evidence)
        
        h.update_confidence()
        h.tested = True
        
        # Determine outcome
        if h.confidence > 0.7:
            h.outcome = "confirmed"
        elif h.confidence < 0.3:
            h.outcome = "rejected"
    
    # === Reasoning Chains ===
    
    def start_reasoning(
        self,
        goal: str,
        reasoning_type: ReasoningType = ReasoningType.CAUSAL,
    ) -> ReasoningChain:
        """
        Start a new chain of reasoning.
        """
        chain = ReasoningChain(
            id=hashlib.md5(f"{goal}_{datetime.now().isoformat()}".encode()).hexdigest()[:12],
            goal=goal,
            reasoning_type=reasoning_type,
        )
        
        # Add initial observation step
        chain.add_step(f"Goal: {goal}", "observation", 1.0)
        
        self._active_chains[chain.id] = chain
        return chain
    
    def continue_reasoning(
        self,
        chain_id: str,
        thought: str,
        thought_type: str = "inference",
        confidence: float = 0.7,
    ) -> Optional[ThoughtStep]:
        """Continue a reasoning chain with a new thought."""
        chain = self._active_chains.get(chain_id)
        if not chain or chain.status != "in_progress":
            return None
        
        return chain.add_step(thought, thought_type, confidence)
    
    def conclude_reasoning(
        self,
        chain_id: str,
        conclusion: str,
        confidence: float = 0.7,
    ):
        """Conclude a reasoning chain."""
        chain = self._active_chains.get(chain_id)
        if not chain:
            return
        
        chain.conclude(conclusion, confidence)
        
        # Archive to history
        self._history.append({
            "type": "reasoning_chain",
            "chain": chain.to_dict(),
            "timestamp": datetime.now().isoformat(),
        })
    
    # === Planning ===
    
    def plan(
        self,
        goal: str,
        context: Optional[Dict[str, Any]] = None,
        constraints: Optional[List[str]] = None,
    ) -> Plan:
        """
        Create a plan to achieve a goal.
        
        This is means-ends planning - figuring out what
        actions will get us from current state to goal state.
        """
        plan = Plan(
            id=hashlib.md5(f"plan_{goal}_{datetime.now().isoformat()}".encode()).hexdigest()[:12],
            goal=goal,
        )
        
        # Start a reasoning chain for planning
        chain = self.start_reasoning(f"Plan: {goal}", ReasoningType.PLANNING)
        
        # Decompose goal (simple heuristic decomposition)
        actions = self._decompose_goal(goal, context)
        plan.actions = actions
        
        # Assess feasibility
        plan.feasibility = self._assess_feasibility(actions, constraints)
        
        # Add reasoning steps
        for action in actions:
            chain.add_step(f"Action: {action['description']}", "action", action.get('confidence', 0.7))
        
        self.conclude_reasoning(chain.id, f"Plan with {len(actions)} actions", plan.feasibility)
        
        self._plans[plan.id] = plan
        return plan
    
    def _decompose_goal(self, goal: str, context: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Decompose a goal into actions."""
        goal_lower = goal.lower()
        actions = []
        
        # Email-related goals
        if "email" in goal_lower:
            if "send" in goal_lower or "write" in goal_lower:
                actions.append({"type": "compose_email", "description": "Compose the email", "confidence": 0.8})
                actions.append({"type": "send_email", "description": "Send the email", "confidence": 0.9})
            elif "find" in goal_lower or "search" in goal_lower:
                actions.append({"type": "search_email", "description": "Search for relevant emails", "confidence": 0.8})
            elif "read" in goal_lower or "check" in goal_lower:
                actions.append({"type": "list_email", "description": "List recent emails", "confidence": 0.9})
        
        # Calendar-related goals
        if "meeting" in goal_lower or "calendar" in goal_lower or "schedule" in goal_lower:
            if "schedule" in goal_lower or "create" in goal_lower:
                actions.append({"type": "find_time", "description": "Find available time slot", "confidence": 0.7})
                actions.append({"type": "create_event", "description": "Create calendar event", "confidence": 0.9})
            elif "prepare" in goal_lower or "prep" in goal_lower:
                actions.append({"type": "get_event", "description": "Get meeting details", "confidence": 0.9})
                actions.append({"type": "find_docs", "description": "Find related documents", "confidence": 0.7})
                actions.append({"type": "summarize", "description": "Create preparation summary", "confidence": 0.6})
        
        # File-related goals
        if "file" in goal_lower or "document" in goal_lower or "organize" in goal_lower:
            if "organize" in goal_lower:
                actions.append({"type": "scan_files", "description": "Scan files to organize", "confidence": 0.9})
                actions.append({"type": "categorize", "description": "Categorize files", "confidence": 0.7})
                actions.append({"type": "move_files", "description": "Move files to categories", "confidence": 0.8})
            elif "find" in goal_lower or "search" in goal_lower:
                actions.append({"type": "search_files", "description": "Search for files", "confidence": 0.8})
        
        # Cleanup goals
        if "clean" in goal_lower or "delete" in goal_lower or "remove" in goal_lower:
            actions.append({"type": "scan", "description": "Scan for items to clean", "confidence": 0.9})
            actions.append({"type": "propose", "description": "Show items for approval", "confidence": 0.9})
            actions.append({"type": "execute", "description": "Execute approved cleanup", "confidence": 0.8})
        
        # Default fallback
        if not actions:
            actions.append({"type": "analyze", "description": f"Analyze how to: {goal}", "confidence": 0.5})
            actions.append({"type": "execute", "description": "Execute the solution", "confidence": 0.5})
        
        return actions
    
    def _assess_feasibility(self, actions: List[Dict[str, Any]], constraints: Optional[List[str]]) -> float:
        """Assess how feasible a plan is."""
        if not actions:
            return 0.0
        
        # Base feasibility is product of action confidences
        feasibility = 1.0
        for action in actions:
            feasibility *= action.get("confidence", 0.7)
        
        # Floor at reasonable level
        feasibility = max(0.3, feasibility)
        
        return feasibility
    
    # === Inference ===
    
    def infer(self, facts: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Draw inferences from facts."""
        return self._inference.infer(facts)
    
    def add_inference_rule(self, condition: Callable, conclusion: str, confidence: float = 0.8):
        """Add a custom inference rule."""
        self._inference.add_rule(condition, conclusion, confidence)
    
    # === Decision Making ===
    
    def evaluate_options(
        self,
        options: List[Dict[str, Any]],
        criteria: Dict[str, float],  # criterion -> weight
    ) -> List[Tuple[Dict[str, Any], float]]:
        """
        Evaluate options against criteria.
        
        Returns options sorted by score with their scores.
        """
        scored = []
        
        for option in options:
            score = 0.0
            for criterion, weight in criteria.items():
                option_score = option.get(criterion, 0.5)
                score += option_score * weight
            scored.append((option, score))
        
        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored
    
    def decide(
        self,
        question: str,
        options: List[str],
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, float, str]:
        """
        Make a decision between options.
        
        Returns (chosen_option, confidence, reasoning).
        """
        # Start reasoning chain for decision
        chain = self.start_reasoning(f"Decide: {question}", ReasoningType.EVALUATIVE)
        
        # Evaluate each option
        option_scores = []
        for option in options:
            score = 0.5  # Base score
            
            # Simple heuristic scoring
            if context:
                # Bias toward options that match context
                for key, value in context.items():
                    if str(value).lower() in option.lower():
                        score += 0.1
            
            chain.add_step(f"Option '{option}': score {score:.2f}", "evaluation", score)
            option_scores.append((option, score))
        
        # Choose best option
        option_scores.sort(key=lambda x: x[1], reverse=True)
        chosen = option_scores[0][0]
        confidence = option_scores[0][1]
        
        reasoning = f"Chose '{chosen}' with confidence {confidence:.2f} from {len(options)} options"
        self.conclude_reasoning(chain.id, reasoning, confidence)
        
        return chosen, confidence, reasoning
    
    # === Stats and History ===
    
    def get_active_reasoning(self) -> List[Dict[str, Any]]:
        """Get all active reasoning chains."""
        return [c.to_dict() for c in self._active_chains.values() if c.status == "in_progress"]
    
    def get_hypotheses(self, min_confidence: float = 0.0) -> List[Dict[str, Any]]:
        """Get current hypotheses."""
        return [h.to_dict() for h in self._hypotheses.values() if h.confidence >= min_confidence]
    
    def get_plans(self) -> List[Dict[str, Any]]:
        """Get all plans."""
        return [p.to_dict() for p in self._plans.values()]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get reasoning engine statistics."""
        return {
            "active_chains": len([c for c in self._active_chains.values() if c.status == "in_progress"]),
            "completed_chains": len([c for c in self._active_chains.values() if c.status == "concluded"]),
            "hypotheses": len(self._hypotheses),
            "confirmed_hypotheses": len([h for h in self._hypotheses.values() if h.outcome == "confirmed"]),
            "plans": len(self._plans),
            "history_entries": len(self._history),
        }
