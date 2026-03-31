"""
Attention System - What deserves focus right now?

Attention is the bottleneck of cognition. We can only
consciously process a few things at once. The attention
system decides what gets through.

This implements:
- Salience detection (what's important?)
- Bottom-up attention (surprising things grab attention)
- Top-down attention (goals direct attention)
- Attentional focus (what we're currently thinking about)
- Attention shifting (when to switch focus)
"""

import asyncio
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .perception import Percept, PerceptType

logger = logging.getLogger(__name__)


class AttentionMode(Enum):
    """Current attention mode."""
    FOCUSED = "focused"        # Deep work on one thing
    MONITORING = "monitoring"  # Watching multiple things
    REACTIVE = "reactive"      # Responding to events
    IDLE = "idle"              # Nothing demanding attention


@dataclass
class Salience:
    """
    Salience score for a percept.
    
    Salience = how much something deserves attention.
    Combines multiple factors.
    """
    percept_id: str
    
    # Component scores (0-1 each)
    urgency: float = 0.0       # Time-sensitive
    novelty: float = 0.0       # New/unexpected
    relevance: float = 0.0     # Matches current goals
    emotional: float = 0.0     # Emotionally significant
    recency: float = 0.0       # Just happened
    
    # Combined score
    total: float = 0.0
    
    # Why is this salient?
    reasons: List[str] = field(default_factory=list)
    
    def calculate(self, weights: Optional[Dict[str, float]] = None):
        """Calculate total salience from components."""
        w = weights or {
            "urgency": 0.25,
            "novelty": 0.20,
            "relevance": 0.30,
            "emotional": 0.15,
            "recency": 0.10,
        }
        
        self.total = (
            self.urgency * w["urgency"] +
            self.novelty * w["novelty"] +
            self.relevance * w["relevance"] +
            self.emotional * w["emotional"] +
            self.recency * w["recency"]
        )
        
        # Build reasons list
        self.reasons = []
        if self.urgency > 0.6:
            self.reasons.append("urgent")
        if self.novelty > 0.6:
            self.reasons.append("novel/unexpected")
        if self.relevance > 0.6:
            self.reasons.append("relevant to goals")
        if self.emotional > 0.6:
            self.reasons.append("emotionally significant")


@dataclass
class AttentionFocus:
    """
    Current focus of attention.
    
    Attention can focus on:
    - A specific percept (reacting to something)
    - A goal (working toward something)
    - A topic (thinking about something)
    """
    focus_type: str           # "percept", "goal", "topic"
    target: Any               # What we're focused on
    started_at: datetime      # When focus began
    duration: timedelta = field(default_factory=lambda: timedelta(0))
    
    # Focus quality
    depth: float = 0.5        # How deep the focus is (0-1)
    stability: float = 1.0    # How stable (decreases with interruptions)
    
    def update(self):
        """Update focus duration and stability."""
        self.duration = datetime.now() - self.started_at
        
        # Stability naturally decreases over time (attention wanders)
        minutes = self.duration.total_seconds() / 60
        self.stability = max(0.1, 1.0 - (minutes / 30) * 0.3)  # 30 min = 70% stability


class AttentionSystem:
    """
    The attention system - what gets through to consciousness.
    
    Key functions:
    1. Score salience of incoming percepts
    2. Maintain current focus
    3. Detect when focus should shift
    4. Balance bottom-up and top-down attention
    """
    
    # Thresholds
    INTERRUPT_THRESHOLD = 0.8    # Salience needed to interrupt focus
    ATTENTION_THRESHOLD = 0.4    # Minimum salience to consider
    FOCUS_DECAY = 0.95           # How quickly focus decays without reinforcement
    
    def __init__(self):
        # Current attention state
        self._mode = AttentionMode.IDLE
        self._focus: Optional[AttentionFocus] = None
        
        # Current goals (top-down attention)
        self._active_goals: List[Dict[str, Any]] = []
        
        # Attention history
        self._attention_log: List[Dict[str, Any]] = []
        
        # Patterns learned
        self._importance_patterns: Dict[str, float] = {}  # entity/topic -> importance
        
        # Salience weights (can be adjusted)
        self._weights = {
            "urgency": 0.25,
            "novelty": 0.20,
            "relevance": 0.30,
            "emotional": 0.15,
            "recency": 0.10,
        }
        
        # Habituation tracking (novel things become less novel)
        self._seen_recently: Dict[str, int] = {}  # entity/topic -> count
    
    def compute_salience(self, percept: Percept) -> Salience:
        """
        Compute salience of a percept.
        
        This determines if something deserves attention.
        """
        salience = Salience(percept_id=percept.id)
        
        # 1. Urgency (from percept's urgency and type)
        salience.urgency = percept.urgency
        if percept.percept_type in [PerceptType.DEADLINE_APPROACHING, PerceptType.APPROVAL_NEEDED]:
            salience.urgency = max(salience.urgency, 0.8)
        if percept.percept_type == PerceptType.ERROR_OCCURRED:
            salience.urgency = max(salience.urgency, 0.9)
        
        # 2. Novelty (is this new/unexpected?)
        novelty_score = 1.0
        for entity in percept.entities:
            seen_count = self._seen_recently.get(entity, 0)
            if seen_count > 0:
                novelty_score *= 0.7  # Less novel if seen before
            self._seen_recently[entity] = seen_count + 1
        
        for topic in percept.topics:
            seen_count = self._seen_recently.get(topic, 0)
            if seen_count > 0:
                novelty_score *= 0.8
            self._seen_recently[topic] = seen_count + 1
        
        # Anomaly detection boost
        if percept.percept_type == PerceptType.ANOMALY_DETECTED:
            novelty_score = max(novelty_score, 0.9)
        
        salience.novelty = novelty_score
        
        # 3. Relevance to current goals
        relevance = 0.0
        for goal in self._active_goals:
            goal_keywords = set(goal.get("keywords", []))
            percept_keywords = set(percept.entities + percept.topics)
            overlap = len(goal_keywords & percept_keywords)
            if overlap > 0:
                relevance = max(relevance, min(1.0, overlap * 0.3))
        
        # Current focus relevance
        if self._focus and self._focus.focus_type == "topic":
            if self._focus.target in percept.topics or self._focus.target in percept.entities:
                relevance = max(relevance, 0.7)
        
        salience.relevance = relevance
        
        # 4. Emotional significance
        salience.emotional = abs(percept.sentiment) * 0.5  # Strong emotions = salient
        
        # Check if entities are "important" based on learned patterns
        for entity in percept.entities:
            if entity in self._importance_patterns:
                salience.emotional = max(salience.emotional, self._importance_patterns[entity])
        
        # 5. Recency (already recent if we're processing it, but may have timestamp)
        age_seconds = (datetime.now() - percept.timestamp).total_seconds()
        salience.recency = max(0, 1.0 - (age_seconds / 300))  # Decays over 5 minutes
        
        # Calculate total
        salience.calculate(self._weights)
        
        return salience
    
    def should_attend(self, percept: Percept, salience: Optional[Salience] = None) -> Tuple[bool, str]:
        """
        Determine if a percept should be attended to.
        
        Returns (should_attend, reason).
        """
        if salience is None:
            salience = self.compute_salience(percept)
        
        # Always attend to high salience
        if salience.total >= self.INTERRUPT_THRESHOLD:
            return True, f"High salience ({salience.total:.2f}): {', '.join(salience.reasons)}"
        
        # Below threshold, don't attend
        if salience.total < self.ATTENTION_THRESHOLD:
            return False, f"Below attention threshold ({salience.total:.2f})"
        
        # Medium salience - depends on current mode
        if self._mode == AttentionMode.FOCUSED:
            # Only interrupt focus for high salience
            return False, "Currently focused, not interrupting"
        
        if self._mode == AttentionMode.MONITORING:
            # In monitoring mode, attend to medium salience
            return True, f"Monitoring mode, attending ({salience.total:.2f})"
        
        if self._mode == AttentionMode.IDLE:
            # In idle mode, attend to anything above threshold
            return True, f"Idle, attending to new input ({salience.total:.2f})"
        
        return True, "Default attend"
    
    def focus_on(self, target: Any, focus_type: str = "topic", depth: float = 0.7):
        """
        Focus attention on something specific.
        
        This is top-down attention - deliberately directing focus.
        """
        # Log previous focus if exists
        if self._focus:
            self._log_attention_shift(self._focus, "new_focus")
        
        self._focus = AttentionFocus(
            focus_type=focus_type,
            target=target,
            started_at=datetime.now(),
            depth=depth,
        )
        
        self._mode = AttentionMode.FOCUSED
        logger.info(f"Focused on: {target} (type: {focus_type})")
    
    def release_focus(self, reason: str = "completed"):
        """Release current focus."""
        if self._focus:
            self._log_attention_shift(self._focus, reason)
            self._focus = None
        
        self._mode = AttentionMode.MONITORING
    
    def set_goals(self, goals: List[Dict[str, Any]]):
        """
        Set current goals for top-down attention.
        
        Goals should have:
        - name: Goal name
        - keywords: List of relevant keywords
        - priority: 0-1 importance
        """
        self._active_goals = goals
        logger.info(f"Set {len(goals)} active goals")
    
    def add_goal(self, name: str, keywords: List[str], priority: float = 0.5):
        """Add a single goal."""
        self._active_goals.append({
            "name": name,
            "keywords": keywords,
            "priority": priority,
            "created_at": datetime.now().isoformat(),
        })
    
    def learn_importance(self, entity: str, importance: float):
        """
        Learn that an entity/topic is important.
        
        This affects future salience calculations.
        """
        current = self._importance_patterns.get(entity, 0.5)
        # Exponential moving average
        self._importance_patterns[entity] = 0.3 * importance + 0.7 * current
    
    def update(self):
        """
        Update attention state.
        
        Should be called periodically.
        """
        if self._focus:
            self._focus.update()
            
            # Check if focus has degraded too much
            if self._focus.stability < 0.2:
                self.release_focus("attention_wandered")
        
        # Decay habituation (things become novel again over time)
        for key in list(self._seen_recently.keys()):
            self._seen_recently[key] -= 1
            if self._seen_recently[key] <= 0:
                del self._seen_recently[key]
    
    def interrupt_check(self, percept: Percept) -> Tuple[bool, str]:
        """
        Check if a percept should interrupt current focus.
        
        Only high-salience items interrupt focused attention.
        """
        if self._mode != AttentionMode.FOCUSED:
            return True, "Not in focused mode"
        
        salience = self.compute_salience(percept)
        
        if salience.total >= self.INTERRUPT_THRESHOLD:
            # Calculate focus cost of interruption
            focus_time = (datetime.now() - self._focus.started_at).total_seconds() if self._focus else 0
            
            # If we've been focused for a while, require higher salience
            adjusted_threshold = self.INTERRUPT_THRESHOLD + (focus_time / 1800) * 0.1  # +0.1 per 30 min
            
            if salience.total >= adjusted_threshold:
                return True, f"High priority interrupt: {', '.join(salience.reasons)}"
        
        return False, f"Below interrupt threshold ({salience.total:.2f} < {self.INTERRUPT_THRESHOLD})"
    
    def get_attention_summary(self) -> Dict[str, Any]:
        """Get current attention state summary."""
        return {
            "mode": self._mode.value,
            "focus": {
                "type": self._focus.focus_type,
                "target": str(self._focus.target),
                "duration_seconds": self._focus.duration.total_seconds(),
                "depth": self._focus.depth,
                "stability": self._focus.stability,
            } if self._focus else None,
            "active_goals": len(self._active_goals),
            "importance_patterns_learned": len(self._importance_patterns),
            "habituation_items": len(self._seen_recently),
        }
    
    def _log_attention_shift(self, focus: AttentionFocus, reason: str):
        """Log an attention shift for learning."""
        self._attention_log.append({
            "timestamp": datetime.now().isoformat(),
            "focus_type": focus.focus_type,
            "target": str(focus.target),
            "duration": focus.duration.total_seconds(),
            "depth": focus.depth,
            "reason": reason,
        })
        
        # Keep log bounded
        if len(self._attention_log) > 1000:
            self._attention_log = self._attention_log[-500:]
    
    def get_attention_patterns(self) -> Dict[str, Any]:
        """Analyze attention patterns from history."""
        if not self._attention_log:
            return {}
        
        # Average focus duration by type
        durations_by_type: Dict[str, List[float]] = {}
        for entry in self._attention_log:
            t = entry["focus_type"]
            if t not in durations_by_type:
                durations_by_type[t] = []
            durations_by_type[t].append(entry["duration"])
        
        avg_durations = {t: sum(d) / len(d) for t, d in durations_by_type.items()}
        
        # Common interruption reasons
        reason_counts: Dict[str, int] = {}
        for entry in self._attention_log:
            r = entry["reason"]
            reason_counts[r] = reason_counts.get(r, 0) + 1
        
        return {
            "avg_focus_duration_by_type": avg_durations,
            "interruption_reasons": reason_counts,
            "total_attention_shifts": len(self._attention_log),
        }
