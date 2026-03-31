"""
Cognitive Core - The central consciousness of the brain.

This is where everything comes together:
- The main cognitive loop
- Thought generation
- Integration of all subsystems
- The experience of "thinking"

This is the closest thing to a unified conscious experience
that a computational system can have.

Architecture:
    
    ┌─────────────────────────────────────────────────────────┐
    │                    COGNITIVE CORE                        │
    │                                                          │
    │  ┌──────────┐    ┌──────────┐    ┌──────────────┐      │
    │  │PERCEPTION│───▶│ ATTENTION│───▶│   WORKING    │      │
    │  │  STREAM  │    │  SYSTEM  │    │   MEMORY     │      │
    │  └──────────┘    └──────────┘    └──────────────┘      │
    │        │                                │                │
    │        │                                ▼                │
    │        │         ┌──────────────────────────────┐       │
    │        │         │      REASONING ENGINE        │       │
    │        │         │  ┌────────┐  ┌───────────┐  │       │
    │        │         │  │HYPOTHE-│  │           │  │       │
    │        │         │  │SIZING  │  │ PLANNING  │  │       │
    │        │         │  └────────┘  └───────────┘  │       │
    │        │         │  ┌────────┐  ┌───────────┐  │       │
    │        │         │  │INFEREN-│  │           │  │       │
    │        │         │  │CE      │  │ DECIDING  │  │       │
    │        │         │  └────────┘  └───────────┘  │       │
    │        │         └──────────────────────────────┘       │
    │        │                        │                       │
    │        │                        ▼                       │
    │        │         ┌──────────────────────────────┐       │
    │        │         │      MEMORY SYSTEMS          │       │
    │        │         │  ┌────────┐  ┌───────────┐  │       │
    │        └────────▶│  │EPISODIC│  │ SEMANTIC  │  │       │
    │                  │  └────────┘  └───────────┘  │       │
    │                  │  ┌────────┐  ┌───────────┐  │       │
    │                  │  │PROCEDU-│  │PREDICTIVE │  │       │
    │                  │  │RAL     │  │           │  │       │
    │                  │  └────────┘  └───────────┘  │       │
    │                  └──────────────────────────────┘       │
    │                                 │                       │
    │                                 ▼                       │
    │                  ┌──────────────────────────────┐       │
    │                  │       METACOGNITION          │       │
    │                  │   (Self-reflection loop)     │       │
    │                  └──────────────────────────────┘       │
    │                                 │                       │
    │                                 ▼                       │
    │                         [ OUTPUT / ACTION ]             │
    └─────────────────────────────────────────────────────────┘
"""

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# Import all subsystems
from .memory_systems import MemorySystems
from .perception import PerceptionStream, Percept
from .attention import AttentionSystem, AttentionFocus
from .reasoning import ReasoningEngine, ReasoningChain, Hypothesis, Plan
from .metacognition import Metacognition, KnowledgeState
from .predictive import PredictiveModel, Prediction, TimeHorizon, PredictionType

logger = logging.getLogger(__name__)


class ThoughtType(Enum):
    """Types of thoughts the brain can have."""
    OBSERVATION = "observation"       # Noticing something
    QUESTION = "question"             # Wondering something
    INFERENCE = "inference"           # Drawing a conclusion
    MEMORY = "memory"                 # Recalling something
    PREDICTION = "prediction"         # Anticipating something
    PLAN = "plan"                     # Planning to do something
    REFLECTION = "reflection"         # Thinking about thinking
    INTENTION = "intention"           # Intending to act
    EMOTION = "emotion"               # Emotional state (simplified)


class CognitiveMode(Enum):
    """Modes of cognitive processing."""
    REACTIVE = "reactive"             # Responding to stimuli
    DELIBERATIVE = "deliberative"     # Careful reasoning
    CREATIVE = "creative"             # Generating novel ideas
    MONITORING = "monitoring"         # Background awareness
    RESTING = "resting"               # Low activity, consolidation


@dataclass
class Thought:
    """
    A single thought - the fundamental unit of cognition.
    """
    id: str
    content: str
    thought_type: ThoughtType
    
    # Origin
    source: str = "internal"          # "perception", "reasoning", "memory", "internal"
    trigger: Optional[str] = None     # What triggered this thought
    
    # Assessment
    importance: float = 0.5           # 0-1 how important
    confidence: float = 0.7           # 0-1 how confident
    
    # Connections
    related_thoughts: List[str] = field(default_factory=list)
    
    # Timing
    created_at: datetime = field(default_factory=datetime.now)
    duration_ms: float = 100          # How long to process
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "type": self.thought_type.value,
            "source": self.source,
            "importance": self.importance,
            "confidence": self.confidence,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class CognitiveState:
    """
    The current state of the cognitive system.
    """
    mode: CognitiveMode = CognitiveMode.MONITORING
    
    # Active contents
    current_focus: Optional[str] = None
    active_thoughts: List[str] = field(default_factory=list)
    active_goals: List[str] = field(default_factory=list)
    
    # Metrics
    cognitive_load: float = 0.3       # 0-1 how taxed the system is
    arousal: float = 0.5              # 0-1 alertness level
    confidence: float = 0.5           # 0-1 overall confidence
    
    # Timestamps
    last_thought_at: Optional[datetime] = None
    last_action_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode.value,
            "current_focus": self.current_focus,
            "active_thought_count": len(self.active_thoughts),
            "active_goal_count": len(self.active_goals),
            "cognitive_load": self.cognitive_load,
            "arousal": self.arousal,
            "confidence": self.confidence,
        }


class CognitiveCore:
    """
    The Cognitive Core - the central consciousness of the brain.
    
    This is the integration point for all cognitive subsystems:
    - Perception: Taking in the world
    - Attention: Knowing what matters
    - Memory: Remembering and knowing
    - Reasoning: Thinking and planning
    - Prediction: Anticipating the future
    - Metacognition: Self-awareness
    
    The cognitive loop:
    1. PERCEIVE: Take in new information
    2. ATTEND: Filter to what's important
    3. REMEMBER: Connect to past experience
    4. REASON: Think about what it means
    5. PREDICT: Anticipate what comes next
    6. REFLECT: Check our understanding
    7. ACT: Decide what to do
    """
    
    def __init__(self, storage_path: Optional[Path] = None):
        self._storage_path = storage_path
        
        # Initialize all subsystems
        self._perception = PerceptionStream()
        self._attention = AttentionSystem()
        self._memory = MemorySystems(storage_path)
        self._reasoning = ReasoningEngine()
        self._prediction = PredictiveModel(storage_path / "predictions" if storage_path else None)
        self._metacognition = Metacognition(storage_path / "metacognition" if storage_path else None)
        
        # Cognitive state
        self._state = CognitiveState()
        
        # Thought stream
        self._thoughts: Dict[str, Thought] = {}
        self._thought_history: List[str] = []  # IDs in order
        self._max_thought_history = 1000
        
        # Action handlers
        self._action_handlers: Dict[str, Callable] = {}
        
        # Background tasks
        self._running = False
        self._cognitive_loop_task: Optional[asyncio.Task] = None
    
    # === Core Cognitive Loop ===
    
    async def start(self):
        """Start the cognitive loop."""
        self._running = True
        self._cognitive_loop_task = asyncio.create_task(self._cognitive_loop())
        logger.info("Cognitive core started")
    
    async def stop(self):
        """Stop the cognitive loop."""
        self._running = False
        if self._cognitive_loop_task:
            self._cognitive_loop_task.cancel()
            try:
                await self._cognitive_loop_task
            except asyncio.CancelledError:
                pass
        logger.info("Cognitive core stopped")
    
    async def _cognitive_loop(self):
        """
        The main cognitive loop - the heartbeat of consciousness.
        
        This runs continuously, processing percepts, generating thoughts,
        and maintaining awareness.
        """
        while self._running:
            try:
                # Adjust timing based on arousal level
                sleep_time = 0.5 if self._state.arousal > 0.7 else 1.0
                
                # 1. Process pending percepts
                await self._process_percepts()
                
                # 2. Update attention
                await self._update_attention()
                
                # 3. Memory consolidation (background)
                if self._state.mode == CognitiveMode.RESTING:
                    await self._memory.consolidate()
                
                # 4. Generate anticipatory thoughts
                await self._anticipate()
                
                # 5. Self-reflection (occasional)
                if len(self._thought_history) % 10 == 0:
                    await self._reflect()
                
                # 6. Update cognitive state
                self._update_cognitive_state()
                
                await asyncio.sleep(sleep_time)
                
            except Exception as e:
                logger.error(f"Error in cognitive loop: {e}")
                await asyncio.sleep(1.0)
    
    async def _process_percepts(self):
        """Process pending percepts from perception stream."""
        while True:
            percept = self._perception.pop_percept()
            if not percept:
                break
            
            # Check attention - should we attend to this?
            should_attend, reason = self._attention.should_attend({
                "type": percept.percept_type.value,
                "content": percept.content,
                "features": percept.features,
            })
            
            if should_attend:
                # Create observation thought
                thought = self._generate_thought(
                    ThoughtType.OBSERVATION,
                    f"Noticed: {percept.summary or percept.content[:100]}",
                    source="perception",
                    importance=percept.salience,
                )
                
                # Store in episodic memory
                await self._memory.store_episodic(
                    content=percept.content,
                    context={
                        "type": percept.percept_type.value,
                        "features": percept.features,
                        "thought_id": thought.id,
                    }
                )
                
                # Update attention focus
                self._attention.focus_on(
                    percept.summary or percept.content[:50],
                    reason=reason,
                )
    
    async def _update_attention(self):
        """Update attention system."""
        # Get current focus
        focus = self._attention.get_current_focus()
        
        if focus:
            self._state.current_focus = focus.target
            
            # Check for interrupts
            interrupt = self._attention.check_interrupt({"threshold": 0.7})
            if interrupt:
                # Something urgent came up
                thought = self._generate_thought(
                    ThoughtType.OBSERVATION,
                    f"Attention: {interrupt['item']['content']}",
                    source="attention",
                    importance=interrupt["salience"],
                )
        else:
            self._state.current_focus = None
    
    async def _anticipate(self):
        """Generate anticipatory thoughts."""
        # Get what we're currently focused on
        if not self._state.current_focus:
            return
        
        # Ask prediction system what might happen
        context = {
            "focus": self._state.current_focus,
            "recent_thoughts": [
                self._thoughts[tid].content 
                for tid in self._thought_history[-5:] 
                if tid in self._thoughts
            ],
        }
        
        predictions = self._prediction.predict_needs(context)
        
        for pred in predictions[:2]:  # Limit to top 2
            if pred.confidence > 0.6:
                thought = self._generate_thought(
                    ThoughtType.PREDICTION,
                    f"Anticipating: {pred.statement}",
                    source="prediction",
                    importance=pred.confidence,
                    confidence=pred.confidence,
                )
    
    async def _reflect(self):
        """Periodic self-reflection."""
        reflection = self._metacognition.reflect()
        
        if reflection.get("recommendations"):
            for rec in reflection["recommendations"][:1]:
                thought = self._generate_thought(
                    ThoughtType.REFLECTION,
                    f"Reflection: {rec}",
                    source="metacognition",
                    importance=0.5,
                )
    
    def _update_cognitive_state(self):
        """Update the overall cognitive state."""
        # Update cognitive load based on active thoughts
        active_count = len([
            t for t in self._thoughts.values()
            if (datetime.now() - t.created_at).seconds < 60
        ])
        self._state.cognitive_load = min(1.0, active_count / 10)
        
        # Update arousal based on recent activity
        if self._state.last_thought_at:
            seconds_since = (datetime.now() - self._state.last_thought_at).seconds
            self._state.arousal = max(0.2, 1.0 - (seconds_since / 300))
        
        # Determine mode
        if self._state.cognitive_load > 0.7:
            self._state.mode = CognitiveMode.DELIBERATIVE
        elif self._state.arousal < 0.3:
            self._state.mode = CognitiveMode.RESTING
        else:
            self._state.mode = CognitiveMode.MONITORING
    
    # === Thought Generation ===
    
    def _generate_thought(
        self,
        thought_type: ThoughtType,
        content: str,
        source: str = "internal",
        trigger: Optional[str] = None,
        importance: float = 0.5,
        confidence: float = 0.7,
    ) -> Thought:
        """Generate a new thought."""
        thought_id = hashlib.md5(
            f"{content}_{datetime.now().isoformat()}".encode()
        ).hexdigest()[:12]
        
        thought = Thought(
            id=thought_id,
            content=content,
            thought_type=thought_type,
            source=source,
            trigger=trigger,
            importance=importance,
            confidence=confidence,
        )
        
        # Store thought
        self._thoughts[thought_id] = thought
        self._thought_history.append(thought_id)
        
        # Trim history if needed
        while len(self._thought_history) > self._max_thought_history:
            old_id = self._thought_history.pop(0)
            if old_id in self._thoughts:
                del self._thoughts[old_id]
        
        # Update state
        self._state.last_thought_at = datetime.now()
        
        logger.debug(f"Thought [{thought_type.value}]: {content[:50]}...")
        
        return thought
    
    # === External Interface ===
    
    async def perceive(self, content: str, source: str = "user", metadata: Optional[Dict] = None):
        """
        Receive new perceptual input.
        
        This is the main entry point for external information.
        """
        # Process through perception stream
        percept = self._perception.process(
            content,
            source=source,
            metadata=metadata or {},
        )
        
        # Increase arousal - something happened
        self._state.arousal = min(1.0, self._state.arousal + 0.2)
        
        return percept
    
    async def think_about(self, topic: str) -> List[Thought]:
        """
        Deliberately think about a topic.
        
        This triggers active reasoning rather than passive monitoring.
        """
        self._state.mode = CognitiveMode.DELIBERATIVE
        thoughts = []
        
        # 1. What do we already know?
        relevant_memories = await self._memory.recall(topic, limit=5)
        for mem in relevant_memories[:2]:
            thought = self._generate_thought(
                ThoughtType.MEMORY,
                f"Recall: {mem.get('content', '')[:100]}",
                source="memory",
                trigger=topic,
            )
            thoughts.append(thought)
        
        # 2. What can we infer?
        facts = {
            "topic": topic,
            "memory_count": len(relevant_memories),
        }
        inferences = self._reasoning.infer(facts)
        for inf in inferences[:2]:
            thought = self._generate_thought(
                ThoughtType.INFERENCE,
                f"Inference: {inf['conclusion']}",
                source="reasoning",
                confidence=inf['confidence'],
                trigger=topic,
            )
            thoughts.append(thought)
        
        # 3. What hypotheses can we form?
        observations = [topic] + [m.get('content', '')[:100] for m in relevant_memories[:3]]
        hypotheses = self._reasoning.hypothesize(observations)
        for hyp in hypotheses[:2]:
            thought = self._generate_thought(
                ThoughtType.INFERENCE,
                f"Hypothesis: {hyp.statement}",
                source="reasoning",
                confidence=hyp.confidence,
                trigger=topic,
            )
            thoughts.append(thought)
        
        # 4. What might happen next?
        outcome, confidence = self._prediction.estimate_outcome(topic, {"topic": topic})
        thought = self._generate_thought(
            ThoughtType.PREDICTION,
            f"Prediction: {outcome}",
            source="prediction",
            confidence=confidence,
            trigger=topic,
        )
        thoughts.append(thought)
        
        return thoughts
    
    async def plan_for(self, goal: str) -> Plan:
        """
        Create a plan to achieve a goal.
        """
        self._state.mode = CognitiveMode.DELIBERATIVE
        
        # Use reasoning engine to create plan
        plan = self._reasoning.plan(goal)
        
        # Create intention thought
        self._generate_thought(
            ThoughtType.INTENTION,
            f"Planning: {goal} ({len(plan.actions)} steps)",
            source="reasoning",
            importance=0.8,
        )
        
        # Store as goal
        self._state.active_goals.append(goal)
        
        return plan
    
    async def answer(self, question: str) -> Dict[str, Any]:
        """
        Answer a question using all cognitive resources.
        """
        self._state.mode = CognitiveMode.DELIBERATIVE
        
        # 1. Perceive the question
        await self.perceive(question, source="question")
        
        # 2. Think about it
        thoughts = await self.think_about(question)
        
        # 3. Check knowledge state
        knowledge_state = self._metacognition.assess_knowledge(question.split()[0])
        uncertainty = self._metacognition.estimate_uncertainty("question", {"question": question})
        
        # 4. Should we ask for clarification?
        should_ask, reason = self._metacognition.should_ask_for_help(question, uncertainty)
        
        # 5. Compile answer
        response = {
            "thoughts": [t.to_dict() for t in thoughts],
            "knowledge_state": knowledge_state.value,
            "uncertainty": uncertainty,
            "should_clarify": should_ask,
            "clarification_reason": reason if should_ask else None,
        }
        
        # 6. Generate answer thought
        if not should_ask:
            answer_content = thoughts[-1].content if thoughts else "I don't have enough information"
            self._generate_thought(
                ThoughtType.INFERENCE,
                f"Answer: {answer_content}",
                source="reasoning",
                trigger=question,
            )
        
        return response
    
    async def remember(self, content: str, memory_type: str = "episodic") -> str:
        """
        Explicitly store something in memory.
        """
        if memory_type == "semantic":
            # Store as knowledge
            await self._memory.store_semantic(
                concept=content,
                properties={"explicit": True},
            )
        else:
            # Store as episode
            await self._memory.store_episodic(
                content=content,
                context={"explicit": True},
            )
        
        self._generate_thought(
            ThoughtType.MEMORY,
            f"Storing: {content[:50]}...",
            source="memory",
        )
        
        return "stored"
    
    async def recall(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Recall memories related to a query.
        """
        memories = await self._memory.recall(query, limit=limit)
        
        if memories:
            self._generate_thought(
                ThoughtType.MEMORY,
                f"Recalled {len(memories)} memories for: {query[:30]}",
                source="memory",
            )
        
        return memories
    
    # === Action Interface ===
    
    def register_action(self, action_name: str, handler: Callable):
        """Register an action handler."""
        self._action_handlers[action_name] = handler
    
    async def execute_action(self, action_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute an action."""
        handler = self._action_handlers.get(action_name)
        if not handler:
            return {"error": f"Unknown action: {action_name}"}
        
        # Create intention thought
        self._generate_thought(
            ThoughtType.INTENTION,
            f"Executing: {action_name}",
            source="internal",
            importance=0.7,
        )
        
        try:
            # Execute
            result = await handler(params) if asyncio.iscoroutinefunction(handler) else handler(params)
            
            # Update metacognition
            self._metacognition.update_belief("actions", action_name, True)
            
            self._state.last_action_at = datetime.now()
            
            return {"success": True, "result": result}
            
        except Exception as e:
            # Record mistake
            self._metacognition.record_mistake(
                description=f"Failed to execute {action_name}",
                category="action",
                what_we_thought="Action would succeed",
                what_actually_happened=str(e),
            )
            
            return {"success": False, "error": str(e)}
    
    # === Introspection ===
    
    def get_state(self) -> Dict[str, Any]:
        """Get the current cognitive state."""
        return {
            **self._state.to_dict(),
            "recent_thoughts": [
                self._thoughts[tid].to_dict()
                for tid in self._thought_history[-10:]
                if tid in self._thoughts
            ],
        }
    
    def get_thoughts(self, limit: int = 20, thought_type: Optional[ThoughtType] = None) -> List[Dict[str, Any]]:
        """Get recent thoughts."""
        thoughts = list(self._thoughts.values())
        
        if thought_type:
            thoughts = [t for t in thoughts if t.thought_type == thought_type]
        
        # Sort by time, most recent first
        thoughts.sort(key=lambda t: t.created_at, reverse=True)
        
        return [t.to_dict() for t in thoughts[:limit]]
    
    def get_focus(self) -> Optional[Dict[str, Any]]:
        """Get what we're currently focused on."""
        focus = self._attention.get_current_focus()
        return focus.to_dict() if focus else None
    
    def get_subsystem_stats(self) -> Dict[str, Any]:
        """Get statistics from all subsystems."""
        return {
            "perception": {
                "pending_percepts": len(self._perception._percept_queue),
            },
            "attention": self._attention.get_stats(),
            "memory": self._memory.get_stats(),
            "reasoning": self._reasoning.get_stats(),
            "prediction": self._prediction.get_stats(),
            "metacognition": self._metacognition.get_stats(),
        }
    
    async def introspect(self) -> Dict[str, Any]:
        """
        Deep introspection - examine the self.
        """
        reflection = self._metacognition.reflect()
        
        return {
            "state": self.get_state(),
            "reflection": reflection,
            "subsystems": self.get_subsystem_stats(),
            "recent_thoughts": self.get_thoughts(10),
            "current_focus": self.get_focus(),
            "active_reasoning": self._reasoning.get_active_reasoning(),
            "active_predictions": self._prediction.get_active_predictions(),
        }
