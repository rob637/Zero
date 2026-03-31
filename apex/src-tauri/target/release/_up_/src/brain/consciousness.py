"""
Consciousness Loop - The Unified Experience

This is the heartbeat of the brain.

Like human consciousness, this is a continuous stream that:
- Integrates all cognitive subsystems
- Maintains awareness of the world
- Directs attention to what matters
- Forms and tracks intentions
- Learns from every experience
- Anticipates what's coming

The consciousness loop is what makes this system feel ALIVE.

This is not event-driven. This is continuously aware.
This is not reactive-only. This is proactive.
This is not stateless. This is an ongoing experience.

Architecture:
    ┌─────────────────────────────────────────────────────────────────┐
    │                    CONSCIOUSNESS LOOP                           │
    │                                                                 │
    │    Every ~100ms, the loop:                                     │
    │                                                                 │
    │    1. SENSE     - What's happening in the world?               │
    │    2. ATTEND    - What matters right now?                      │
    │    3. REMEMBER  - How does this connect to what I know?        │
    │    4. THINK     - What does this mean?                         │
    │    5. PREDICT   - What's going to happen?                      │
    │    6. DECIDE    - Should I do something?                       │
    │    7. ACT       - Execute or wait                              │
    │    8. LEARN     - What can I learn from this?                  │
    │    9. REST      - Consolidate, maintain                        │
    │                                                                 │
    │    ────────────────────── REPEAT ───────────────────────────   │
    └─────────────────────────────────────────────────────────────────┘
"""

import asyncio
import logging
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set
import hashlib

logger = logging.getLogger(__name__)


class ConsciousnessState(Enum):
    """States of consciousness."""
    DORMANT = "dormant"           # Not running
    WAKING = "waking"             # Starting up
    AWARE = "aware"               # Normal operation
    FOCUSED = "focused"           # Deep concentration on task
    ANTICIPATING = "anticipating" # Waiting for expected event
    ACTING = "acting"             # Executing action
    REFLECTING = "reflecting"     # Deep self-reflection
    CONSOLIDATING = "consolidating"  # Background processing
    RESTING = "resting"           # Low activity


class UrgencyLevel(Enum):
    """How urgent something is."""
    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class Intention:
    """
    An intention to do something.
    
    Intentions are formed through reasoning and drive action.
    """
    id: str
    description: str
    
    # What and why
    action: str
    goal: str
    
    # Assessment
    urgency: UrgencyLevel = UrgencyLevel.MEDIUM
    confidence: float = 0.7
    
    # Status
    status: str = "pending"  # "pending", "executing", "completed", "abandoned"
    
    # Timing
    created_at: datetime = field(default_factory=datetime.now)
    deadline: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "action": self.action,
            "goal": self.goal,
            "urgency": self.urgency.value,
            "confidence": self.confidence,
            "status": self.status,
        }


@dataclass
class AwarenessMoment:
    """
    A moment in the stream of consciousness.
    
    Each cycle produces a moment that captures:
    - What was perceived
    - What was attended to
    - What was thought
    - What was decided
    """
    id: str
    timestamp: datetime
    state: ConsciousnessState
    
    # Contents
    percepts: List[str] = field(default_factory=list)
    focus: Optional[str] = None
    thoughts: List[str] = field(default_factory=list)
    memories_accessed: List[str] = field(default_factory=list)
    predictions: List[str] = field(default_factory=list)
    intentions: List[str] = field(default_factory=list)
    actions_taken: List[str] = field(default_factory=list)
    
    # Metrics
    cognitive_load: float = 0.3
    arousal: float = 0.5
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "state": self.state.value,
            "focus": self.focus,
            "thought_count": len(self.thoughts),
            "predictions": self.predictions[:3],
            "intentions": self.intentions,
            "cognitive_load": self.cognitive_load,
            "arousal": self.arousal,
        }


class ConsciousnessLoop:
    """
    The Consciousness Loop - the unified experience of being.
    
    This is the crown jewel that ties everything together.
    
    It maintains continuous awareness by:
    1. Running a persistent background loop
    2. Integrating all cognitive subsystems
    3. Forming and tracking intentions
    4. Making decisions about action
    5. Learning from every moment
    """
    
    def __init__(
        self,
        cognitive_core,
        world_interface,
        learning_engine,
        storage_path: Optional[Path] = None,
    ):
        # Core systems
        self._cognitive = cognitive_core
        self._world = world_interface
        self._learning = learning_engine
        
        self._storage_path = storage_path
        
        # State
        self._state = ConsciousnessState.DORMANT
        self._running = False
        
        # Current awareness
        self._current_moment: Optional[AwarenessMoment] = None
        self._moment_history: List[AwarenessMoment] = []
        self._max_history = 100
        
        # Intentions
        self._intentions: Dict[str, Intention] = {}
        self._pending_intentions: List[str] = []
        
        # Anticipations
        self._anticipations: Dict[str, Dict] = {}
        
        # Event callbacks
        self._event_callbacks: Dict[str, List[Callable]] = {
            "intention_formed": [],
            "action_taken": [],
            "insight_gained": [],
            "state_changed": [],
        }
        
        # Loop control
        self._loop_task: Optional[asyncio.Task] = None
        self._cycle_time_ms = 500  # Base cycle time
        
        # Metrics
        self._metrics = {
            "total_cycles": 0,
            "thoughts_generated": 0,
            "actions_taken": 0,
            "predictions_made": 0,
            "intentions_completed": 0,
            "lessons_learned": 0,
        }
        
        logger.info("Consciousness loop initialized")
    
    # === Lifecycle ===
    
    async def wake(self):
        """Wake up the consciousness."""
        if self._running:
            return
        
        self._state = ConsciousnessState.WAKING
        self._running = True
        
        # Start cognitive core
        await self._cognitive.start()
        
        # Start world monitoring
        await self._world.start_monitoring()
        
        # Start the loop
        self._loop_task = asyncio.create_task(self._run_loop())
        
        self._state = ConsciousnessState.AWARE
        logger.info("Consciousness awakened")
    
    async def sleep(self):
        """Put consciousness to sleep."""
        self._state = ConsciousnessState.RESTING
        
        # Consolidate learning
        await self._learning.consolidate()
        
        # Stop loop
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        
        # Stop subsystems
        await self._cognitive.stop()
        await self._world.stop_monitoring()
        
        self._state = ConsciousnessState.DORMANT
        logger.info("Consciousness sleeping")
    
    # === The Main Loop ===
    
    async def _run_loop(self):
        """
        The consciousness loop - continuous awareness.
        
        This is the heartbeat.
        """
        while self._running:
            try:
                cycle_start = datetime.now()
                
                # Create moment
                moment = AwarenessMoment(
                    id=hashlib.md5(f"moment_{cycle_start.isoformat()}".encode()).hexdigest()[:12],
                    timestamp=cycle_start,
                    state=self._state,
                )
                
                # 1. SENSE - What's happening?
                await self._sense(moment)
                
                # 2. ATTEND - What matters?
                await self._attend(moment)
                
                # 3. REMEMBER - Connect to knowledge
                await self._remember(moment)
                
                # 4. THINK - Process and understand
                await self._think(moment)
                
                # 5. PREDICT - What's coming?
                await self._predict(moment)
                
                # 6. DECIDE - Form intentions
                await self._decide(moment)
                
                # 7. ACT - Execute if appropriate
                await self._act(moment)
                
                # 8. LEARN - Extract lessons
                await self._learn(moment)
                
                # 9. REST - Maintenance
                await self._rest(moment)
                
                # Record moment
                self._current_moment = moment
                self._moment_history.append(moment)
                while len(self._moment_history) > self._max_history:
                    self._moment_history.pop(0)
                
                self._metrics["total_cycles"] += 1
                
                # Calculate sleep time based on arousal
                cycle_time = self._cycle_time_ms
                if moment.arousal > 0.8:
                    cycle_time = 200  # Faster when aroused
                elif moment.arousal < 0.3:
                    cycle_time = 1000  # Slower when calm
                
                # Sleep until next cycle
                elapsed = (datetime.now() - cycle_start).total_seconds() * 1000
                sleep_time = max(50, cycle_time - elapsed)
                await asyncio.sleep(sleep_time / 1000)
                
            except Exception as e:
                logger.error(f"Error in consciousness loop: {e}")
                await asyncio.sleep(1.0)
    
    # === Loop Phases ===
    
    async def _sense(self, moment: AwarenessMoment):
        """Sense - gather perceptions from the world."""
        # Get observations from world interface
        while True:
            observation = await self._world.get_observation()
            if not observation:
                break
            
            # Feed to cognitive perception
            percept = await self._cognitive.perceive(
                content=json.dumps(observation.content),
                source=observation.source,
                metadata={
                    "importance": observation.importance,
                    "urgency": observation.urgency,
                }
            )
            
            moment.percepts.append(observation.source)
            
            # High urgency increases arousal
            if observation.urgency > 0.7:
                moment.arousal = min(1.0, moment.arousal + 0.2)
    
    async def _attend(self, moment: AwarenessMoment):
        """Attend - focus on what matters."""
        # Get current focus from cognitive core
        focus = self._cognitive.get_focus()
        
        if focus:
            moment.focus = focus.get("target", "")
        
        # Check for high-priority intentions
        urgent_intentions = [
            self._intentions[iid] for iid in self._pending_intentions
            if self._intentions[iid].urgency.value >= UrgencyLevel.HIGH.value
        ]
        
        if urgent_intentions:
            # Urgent intention takes focus
            most_urgent = max(urgent_intentions, key=lambda i: i.urgency.value)
            moment.focus = most_urgent.description
            moment.arousal = min(1.0, moment.arousal + 0.1)
    
    async def _remember(self, moment: AwarenessMoment):
        """Remember - connect to past knowledge."""
        if not moment.focus:
            return
        
        # Recall relevant memories
        memories = await self._cognitive.recall(moment.focus, limit=3)
        
        for mem in memories:
            moment.memories_accessed.append(mem.get("id", ""))
        
        # Get relevant learned lessons
        lessons = self._learning.get_relevant_lessons(moment.focus)
        
        for lesson in lessons[:2]:
            moment.thoughts.append(f"Lesson: {lesson.content[:50]}")
    
    async def _think(self, moment: AwarenessMoment):
        """Think - process and generate understanding."""
        if moment.focus:
            # Think about the focus
            thoughts = await self._cognitive.think_about(moment.focus)
            
            for thought in thoughts:
                moment.thoughts.append(thought.content[:100])
                self._metrics["thoughts_generated"] += 1
        
        # Check cognitive load
        state = self._cognitive.get_state()
        moment.cognitive_load = state.get("cognitive_load", 0.3)
        
        # High cognitive load -> focused state
        if moment.cognitive_load > 0.7:
            self._state = ConsciousnessState.FOCUSED
            moment.state = self._state
    
    async def _predict(self, moment: AwarenessMoment):
        """Predict - anticipate what's coming."""
        # Check anticipations
        for aid, anticipation in list(self._anticipations.items()):
            if anticipation.get("expected_time"):
                expected = datetime.fromisoformat(anticipation["expected_time"])
                now = datetime.now()
                
                # Is it time?
                if now >= expected - timedelta(minutes=5):
                    moment.predictions.append(f"Expecting: {anticipation['description']}")
                    self._state = ConsciousnessState.ANTICIPATING
                    moment.state = self._state
                    moment.arousal = min(1.0, moment.arousal + 0.15)
        
        # Generate new predictions
        if moment.focus:
            # Ask cognitive core for predictions
            response = await self._cognitive.answer(f"What might happen next regarding {moment.focus}?")
            
            for thought in response.get("thoughts", []):
                if thought.get("type") == "prediction":
                    moment.predictions.append(thought.get("content", "")[:100])
                    self._metrics["predictions_made"] += 1
    
    async def _decide(self, moment: AwarenessMoment):
        """Decide - form intentions about action."""
        # Check if we should form new intentions
        if moment.arousal > 0.6 and moment.thoughts:
            # High arousal + active thoughts = potential action
            
            # Ask cognitive core if action is warranted
            for thought in moment.thoughts[-3:]:
                if "should" in thought.lower() or "need to" in thought.lower():
                    # This thought suggests action
                    intention = Intention(
                        id=hashlib.md5(f"intent_{datetime.now().isoformat()}".encode()).hexdigest()[:12],
                        description=thought[:100],
                        action="investigate",  # Default action
                        goal=moment.focus or "respond",
                        urgency=UrgencyLevel.MEDIUM if moment.arousal > 0.7 else UrgencyLevel.LOW,
                        confidence=0.6,
                    )
                    
                    self._intentions[intention.id] = intention
                    self._pending_intentions.append(intention.id)
                    moment.intentions.append(intention.description)
                    
                    logger.debug(f"Formed intention: {intention.description[:50]}")
                    self._trigger_event("intention_formed", intention.to_dict())
    
    async def _act(self, moment: AwarenessMoment):
        """Act - execute intentions if appropriate."""
        if not self._pending_intentions:
            return
        
        # Get most urgent pending intention
        pending = [self._intentions[iid] for iid in self._pending_intentions if iid in self._intentions]
        if not pending:
            return
        
        pending.sort(key=lambda i: i.urgency.value, reverse=True)
        intention = pending[0]
        
        # Check if we should act now
        should_act = (
            intention.urgency.value >= UrgencyLevel.HIGH.value or
            (intention.urgency.value >= UrgencyLevel.MEDIUM.value and moment.arousal > 0.5)
        )
        
        if should_act and intention.confidence > 0.5:
            self._state = ConsciousnessState.ACTING
            moment.state = self._state
            
            # Execute through cognitive core
            result = await self._cognitive.execute_action(
                intention.action,
                {"goal": intention.goal, "context": moment.focus}
            )
            
            if result.get("success"):
                intention.status = "completed"
                self._pending_intentions.remove(intention.id)
                moment.actions_taken.append(intention.action)
                self._metrics["actions_taken"] += 1
                self._metrics["intentions_completed"] += 1
                
                logger.info(f"Action completed: {intention.action}")
                self._trigger_event("action_taken", {
                    "intention": intention.to_dict(),
                    "result": result,
                })
            else:
                # Action failed - learn from it
                intention.confidence -= 0.2
                if intention.confidence < 0.3:
                    intention.status = "abandoned"
                    self._pending_intentions.remove(intention.id)
    
    async def _learn(self, moment: AwarenessMoment):
        """Learn - extract lessons from this moment."""
        # Learn from completed actions
        if moment.actions_taken:
            for action in moment.actions_taken:
                self._learning.record_episode(
                    stimulus=moment.focus or "unknown",
                    response=action,
                    outcome="completed",
                    success=True,
                    context={
                        "arousal": moment.arousal,
                        "cognitive_load": moment.cognitive_load,
                        "state": moment.state.value,
                    }
                )
                self._metrics["lessons_learned"] += 1
        
        # Learn from predictions (track for validation later)
        for prediction in moment.predictions:
            self._anticipations[hashlib.md5(prediction.encode()).hexdigest()[:12]] = {
                "description": prediction,
                "created_at": moment.timestamp.isoformat(),
            }
    
    async def _rest(self, moment: AwarenessMoment):
        """Rest - maintenance and consolidation."""
        # Periodic learning consolidation
        if self._metrics["total_cycles"] % 100 == 0:
            await self._learning.consolidate()
        
        # Periodic pattern recognition
        if self._metrics["total_cycles"] % 50 == 0:
            patterns = await self._learning.recognize_patterns()
            if patterns:
                logger.info(f"Discovered {len(patterns)} new patterns")
                self._trigger_event("insight_gained", {
                    "patterns": [p.to_dict() for p in patterns]
                })
        
        # Periodic pruning
        if self._metrics["total_cycles"] % 500 == 0:
            await self._learning.prune()
        
        # Decay arousal naturally
        moment.arousal = max(0.2, moment.arousal - 0.02)
        
        # Return to aware state if we were focused/acting
        if self._state in [ConsciousnessState.FOCUSED, ConsciousnessState.ACTING]:
            if moment.cognitive_load < 0.5 and not moment.actions_taken:
                self._state = ConsciousnessState.AWARE
    
    # === External Interface ===
    
    async def receive_input(self, content: str, source: str = "user") -> Dict[str, Any]:
        """
        Receive external input and process it consciously.
        
        This is the main entry point for user interaction.
        """
        # Create percept
        await self._cognitive.perceive(content, source)
        
        # Increase arousal - someone is talking to us
        if self._current_moment:
            self._current_moment.arousal = min(1.0, self._current_moment.arousal + 0.3)
        
        # Process immediately (don't wait for loop)
        response = await self._cognitive.answer(content)
        
        # Learn from interaction
        self._learning.record_episode(
            stimulus=content,
            response=response.get("thoughts", [{}])[-1].get("content", ""),
            outcome="responded",
            success=True,
            context={"source": source},
        )
        
        return response
    
    def add_anticipation(self, description: str, expected_time: Optional[datetime] = None):
        """Add something to anticipate."""
        aid = hashlib.md5(description.encode()).hexdigest()[:12]
        self._anticipations[aid] = {
            "description": description,
            "expected_time": expected_time.isoformat() if expected_time else None,
            "created_at": datetime.now().isoformat(),
        }
    
    def on(self, event_type: str, callback: Callable):
        """Subscribe to consciousness events."""
        if event_type in self._event_callbacks:
            self._event_callbacks[event_type].append(callback)
    
    def _trigger_event(self, event_type: str, data: Dict[str, Any]):
        """Trigger event callbacks."""
        for callback in self._event_callbacks.get(event_type, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(callback(data))
                else:
                    callback(data)
            except Exception as e:
                logger.error(f"Event callback error: {e}")
    
    # === Introspection ===
    
    def get_state(self) -> Dict[str, Any]:
        """Get current consciousness state."""
        return {
            "state": self._state.value,
            "running": self._running,
            "current_moment": self._current_moment.to_dict() if self._current_moment else None,
            "pending_intentions": len(self._pending_intentions),
            "anticipations": len(self._anticipations),
            "metrics": self._metrics,
        }
    
    def get_stream(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent moments from the stream of consciousness."""
        return [m.to_dict() for m in self._moment_history[-limit:]]
    
    def get_intentions(self) -> List[Dict[str, Any]]:
        """Get current intentions."""
        return [self._intentions[iid].to_dict() for iid in self._pending_intentions if iid in self._intentions]
    
    def get_anticipations(self) -> List[Dict[str, Any]]:
        """Get current anticipations."""
        return list(self._anticipations.values())


# Factory function
def create_consciousness(
    cognitive_core,
    world_interface,
    learning_engine,
    storage_path: Optional[Path] = None,
) -> ConsciousnessLoop:
    """Create a consciousness loop."""
    return ConsciousnessLoop(
        cognitive_core=cognitive_core,
        world_interface=world_interface,
        learning_engine=learning_engine,
        storage_path=storage_path,
    )
