"""
Learning Engine - Continuous Self-Improvement

This is how the brain gets smarter.

Unlike static systems, this brain LEARNS from:
- Every interaction
- Every success and failure
- Every prediction that was right or wrong
- Every pattern it discovers
- Every feedback it receives

Learning Systems:
1. REINFORCEMENT - Learn from outcomes
2. PATTERN - Recognize recurring structures  
3. FEEDBACK - Learn from user corrections
4. TRANSFER - Apply knowledge to new situations
5. CONSOLIDATION - Strengthen important memories
6. PRUNING - Forget irrelevant information

The brain that learns is the brain that survives.
"""

import asyncio
import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import math

logger = logging.getLogger(__name__)


class LessonType(Enum):
    """Types of things we can learn."""
    SUCCESS_PATTERN = "success_pattern"       # What works
    FAILURE_PATTERN = "failure_pattern"       # What doesn't work
    USER_PREFERENCE = "user_preference"       # What user likes
    USER_CORRECTION = "user_correction"       # User fixed our mistake
    PREDICTION_OUTCOME = "prediction_outcome" # Was prediction right?
    TASK_COMPLETION = "task_completion"       # How tasks get done
    TEMPORAL_PATTERN = "temporal_pattern"     # When things happen
    CAUSAL_RELATION = "causal_relation"       # What causes what
    CONTEXTUAL = "contextual"                 # Context affects outcome


class LearningSignal(Enum):
    """Signals that trigger learning."""
    POSITIVE = "positive"      # This was good
    NEGATIVE = "negative"      # This was bad
    NEUTRAL = "neutral"        # Just information
    SURPRISE = "surprise"      # Unexpected outcome
    CORRECTION = "correction"  # User corrected us


@dataclass
class Lesson:
    """
    A single thing learned.
    
    Lessons are the atoms of knowledge gained from experience.
    """
    id: str
    lesson_type: LessonType
    content: str                    # What was learned
    
    # Context
    context: Dict[str, Any] = field(default_factory=dict)
    trigger_event: Optional[str] = None
    
    # Learning strength
    signal: LearningSignal = LearningSignal.NEUTRAL
    strength: float = 1.0           # How strongly learned
    confidence: float = 0.5         # How confident we are
    
    # Application
    applicable_to: List[str] = field(default_factory=list)  # Situations where this applies
    times_applied: int = 0
    times_helpful: int = 0
    
    # Metadata
    learned_at: datetime = field(default_factory=datetime.now)
    last_applied: Optional[datetime] = None
    source: str = "experience"      # Where this came from
    
    def apply(self, was_helpful: bool):
        """Record that this lesson was applied."""
        self.times_applied += 1
        self.last_applied = datetime.now()
        if was_helpful:
            self.times_helpful += 1
            self.strength = min(10.0, self.strength + 0.5)
        else:
            self.strength = max(0.1, self.strength - 0.3)
        
        # Update confidence based on track record
        if self.times_applied >= 3:
            self.confidence = self.times_helpful / self.times_applied
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.lesson_type.value,
            "content": self.content,
            "context": self.context,
            "signal": self.signal.value,
            "strength": self.strength,
            "confidence": self.confidence,
            "times_applied": self.times_applied,
            "times_helpful": self.times_helpful,
            "learned_at": self.learned_at.isoformat(),
        }


@dataclass
class Pattern:
    """
    A recognized pattern in behavior or data.
    
    Patterns are higher-order learnings that emerge from
    multiple experiences.
    """
    id: str
    description: str
    pattern_type: str              # "behavioral", "temporal", "causal", "contextual"
    
    # Pattern data
    components: List[str] = field(default_factory=list)  # What makes up this pattern
    conditions: Dict[str, Any] = field(default_factory=dict)  # When it applies
    
    # Statistics
    occurrences: int = 0
    confidence: float = 0.3
    predictive_power: float = 0.0  # How well does this predict outcomes
    
    # Examples
    positive_examples: List[str] = field(default_factory=list)
    negative_examples: List[str] = field(default_factory=list)
    
    # Metadata
    discovered_at: datetime = field(default_factory=datetime.now)
    last_seen: Optional[datetime] = None
    
    def add_occurrence(self, positive: bool = True, example: Optional[str] = None):
        """Record pattern occurrence."""
        self.occurrences += 1
        self.last_seen = datetime.now()
        
        if example:
            if positive:
                self.positive_examples.append(example)
                # Keep last 10 examples
                self.positive_examples = self.positive_examples[-10:]
            else:
                self.negative_examples.append(example)
                self.negative_examples = self.negative_examples[-10:]
        
        # Update confidence
        total_examples = len(self.positive_examples) + len(self.negative_examples)
        if total_examples > 0:
            positive_rate = len(self.positive_examples) / total_examples
            self.confidence = min(0.95, 0.3 + (0.65 * positive_rate * min(self.occurrences / 10, 1.0)))
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "type": self.pattern_type,
            "occurrences": self.occurrences,
            "confidence": self.confidence,
            "predictive_power": self.predictive_power,
            "conditions": self.conditions,
        }


@dataclass
class LearningEpisode:
    """
    A learning episode - a complete interaction we can learn from.
    """
    id: str
    
    # What happened
    stimulus: str                  # What triggered this
    response: str                  # What we did
    outcome: str                   # What happened
    
    # Assessment
    success: bool = False
    surprise_level: float = 0.0   # How unexpected was outcome
    
    # Context
    context: Dict[str, Any] = field(default_factory=dict)
    
    # Metadata
    timestamp: datetime = field(default_factory=datetime.now)
    processed: bool = False
    lessons_extracted: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "stimulus": self.stimulus,
            "response": self.response,
            "outcome": self.outcome,
            "success": self.success,
            "surprise_level": self.surprise_level,
            "processed": self.processed,
        }


class LearningEngine:
    """
    The Learning Engine - continuous self-improvement.
    
    This is what makes the brain get smarter over time.
    
    Processes:
    1. Episode Recording - Capture what happened
    2. Lesson Extraction - What can we learn?
    3. Pattern Recognition - What patterns emerge?
    4. Model Update - Update internal models
    5. Consolidation - Strengthen important learning
    6. Pruning - Forget irrelevant things
    """
    
    def __init__(self, storage_path: Optional[Path] = None):
        self._storage_path = storage_path
        
        # Lessons learned
        self._lessons: Dict[str, Lesson] = {}
        
        # Patterns discovered
        self._patterns: Dict[str, Pattern] = {}
        
        # Learning episodes
        self._episodes: List[LearningEpisode] = []
        self._max_episodes = 500
        
        # User model
        self._user_preferences: Dict[str, float] = {}  # preference -> strength
        self._user_corrections: List[Dict] = []        # history of corrections
        
        # Model parameters (continuously updated)
        self._model_params: Dict[str, Any] = {
            "response_style": {"formal": 0.5, "casual": 0.5},
            "proactivity_level": 0.5,
            "detail_preference": 0.5,
            "time_sensitivity": {},  # time -> importance
        }
        
        # Learning statistics
        self._stats = {
            "total_episodes": 0,
            "lessons_learned": 0,
            "patterns_discovered": 0,
            "successful_applications": 0,
            "corrections_received": 0,
        }
        
        # Initialize storage
        if storage_path:
            self._init_storage()
    
    def _init_storage(self):
        """Initialize persistent learning storage."""
        self._storage_path.mkdir(parents=True, exist_ok=True)
        
        db_path = self._storage_path / "learning.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Lessons table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lessons (
                id TEXT PRIMARY KEY,
                lesson_type TEXT,
                content TEXT,
                context TEXT,
                signal TEXT,
                strength REAL,
                confidence REAL,
                times_applied INTEGER,
                times_helpful INTEGER,
                learned_at TEXT
            )
        """)
        
        # Patterns table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS patterns (
                id TEXT PRIMARY KEY,
                description TEXT,
                pattern_type TEXT,
                occurrences INTEGER,
                confidence REAL,
                predictive_power REAL,
                discovered_at TEXT
            )
        """)
        
        # Episodes table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS episodes (
                id TEXT PRIMARY KEY,
                stimulus TEXT,
                response TEXT,
                outcome TEXT,
                success INTEGER,
                surprise_level REAL,
                context TEXT,
                timestamp TEXT
            )
        """)
        
        conn.commit()
        conn.close()
        
        # Load existing data
        self._load_from_storage()
    
    def _load_from_storage(self):
        """Load learned data from storage."""
        if not self._storage_path:
            return
        
        db_path = self._storage_path / "learning.db"
        if not db_path.exists():
            return
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Load lessons
        cursor.execute("SELECT * FROM lessons ORDER BY strength DESC LIMIT 1000")
        for row in cursor.fetchall():
            lesson = Lesson(
                id=row[0],
                lesson_type=LessonType(row[1]),
                content=row[2],
                context=json.loads(row[3]) if row[3] else {},
                signal=LearningSignal(row[4]) if row[4] else LearningSignal.NEUTRAL,
                strength=row[5] or 1.0,
                confidence=row[6] or 0.5,
                times_applied=row[7] or 0,
                times_helpful=row[8] or 0,
            )
            self._lessons[lesson.id] = lesson
        
        # Load patterns
        cursor.execute("SELECT * FROM patterns ORDER BY confidence DESC LIMIT 500")
        for row in cursor.fetchall():
            pattern = Pattern(
                id=row[0],
                description=row[1],
                pattern_type=row[2],
                occurrences=row[3] or 0,
                confidence=row[4] or 0.3,
                predictive_power=row[5] or 0.0,
            )
            self._patterns[pattern.id] = pattern
        
        conn.close()
        
        self._stats["lessons_learned"] = len(self._lessons)
        self._stats["patterns_discovered"] = len(self._patterns)
        
        logger.info(f"Loaded {len(self._lessons)} lessons and {len(self._patterns)} patterns")
    
    def _save_lesson(self, lesson: Lesson):
        """Persist a lesson to storage."""
        if not self._storage_path:
            return
        
        db_path = self._storage_path / "learning.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO lessons 
            (id, lesson_type, content, context, signal, strength, confidence, times_applied, times_helpful, learned_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            lesson.id,
            lesson.lesson_type.value,
            lesson.content,
            json.dumps(lesson.context),
            lesson.signal.value,
            lesson.strength,
            lesson.confidence,
            lesson.times_applied,
            lesson.times_helpful,
            lesson.learned_at.isoformat(),
        ))
        
        conn.commit()
        conn.close()
    
    # === Core Learning Methods ===
    
    def record_episode(
        self,
        stimulus: str,
        response: str,
        outcome: str,
        success: bool,
        context: Optional[Dict] = None,
        surprise_level: float = 0.0,
    ) -> LearningEpisode:
        """
        Record a learning episode.
        
        This is the entry point for learning from experience.
        """
        episode = LearningEpisode(
            id=hashlib.md5(f"{stimulus}_{datetime.now().isoformat()}".encode()).hexdigest()[:12],
            stimulus=stimulus,
            response=response,
            outcome=outcome,
            success=success,
            surprise_level=surprise_level,
            context=context or {},
        )
        
        self._episodes.append(episode)
        self._stats["total_episodes"] += 1
        
        # Trim episodes
        while len(self._episodes) > self._max_episodes:
            self._episodes.pop(0)
        
        # Extract lessons immediately for important episodes
        if success or surprise_level > 0.5:
            self._extract_lessons(episode)
        
        logger.debug(f"Recorded learning episode: {episode.id}")
        return episode
    
    def _extract_lessons(self, episode: LearningEpisode) -> List[Lesson]:
        """Extract lessons from an episode."""
        lessons = []
        
        # Success pattern
        if episode.success:
            lesson = Lesson(
                id=f"lesson_{episode.id}_success",
                lesson_type=LessonType.SUCCESS_PATTERN,
                content=f"When '{episode.stimulus[:50]}' → responding with '{episode.response[:50]}' works",
                context=episode.context,
                signal=LearningSignal.POSITIVE,
                strength=1.5 if episode.surprise_level < 0.3 else 1.0,
            )
            lessons.append(lesson)
        
        # Failure pattern
        else:
            lesson = Lesson(
                id=f"lesson_{episode.id}_failure",
                lesson_type=LessonType.FAILURE_PATTERN,
                content=f"When '{episode.stimulus[:50]}' → responding with '{episode.response[:50]}' failed",
                context=episode.context,
                signal=LearningSignal.NEGATIVE,
            )
            lessons.append(lesson)
        
        # Surprise lesson
        if episode.surprise_level > 0.5:
            lesson = Lesson(
                id=f"lesson_{episode.id}_surprise",
                lesson_type=LessonType.PREDICTION_OUTCOME,
                content=f"Unexpected outcome: {episode.outcome[:100]}",
                context=episode.context,
                signal=LearningSignal.SURPRISE,
                strength=episode.surprise_level * 2,  # Surprises are memorable
            )
            lessons.append(lesson)
        
        # Store lessons
        for lesson in lessons:
            self._lessons[lesson.id] = lesson
            self._save_lesson(lesson)
            self._stats["lessons_learned"] += 1
        
        episode.processed = True
        episode.lessons_extracted = [l.id for l in lessons]
        
        return lessons
    
    def learn_from_feedback(
        self,
        feedback: str,
        about: str,
        signal: LearningSignal = LearningSignal.CORRECTION,
        context: Optional[Dict] = None,
    ) -> Lesson:
        """
        Learn from explicit user feedback.
        
        This is learning from correction/praise.
        """
        lesson = Lesson(
            id=hashlib.md5(f"feedback_{datetime.now().isoformat()}".encode()).hexdigest()[:12],
            lesson_type=LessonType.USER_CORRECTION if signal == LearningSignal.CORRECTION else LessonType.USER_PREFERENCE,
            content=f"User feedback about '{about[:50]}': {feedback[:100]}",
            context=context or {},
            signal=signal,
            strength=2.0,  # Direct feedback is strong
            confidence=0.9,  # User feedback is reliable
            source="user_feedback",
        )
        
        self._lessons[lesson.id] = lesson
        self._save_lesson(lesson)
        self._stats["lessons_learned"] += 1
        
        if signal == LearningSignal.CORRECTION:
            self._stats["corrections_received"] += 1
            self._user_corrections.append({
                "feedback": feedback,
                "about": about,
                "timestamp": datetime.now().isoformat(),
            })
        
        logger.info(f"Learned from feedback: {lesson.content[:50]}")
        return lesson
    
    def learn_preference(self, category: str, preference: str, strength: float = 0.3):
        """Learn a user preference."""
        key = f"{category}:{preference}"
        current = self._user_preferences.get(key, 0.5)
        self._user_preferences[key] = min(1.0, current + strength)
        
        # Also create a lesson
        lesson = Lesson(
            id=hashlib.md5(f"pref_{key}_{datetime.now().isoformat()}".encode()).hexdigest()[:12],
            lesson_type=LessonType.USER_PREFERENCE,
            content=f"User prefers {preference} for {category}",
            signal=LearningSignal.POSITIVE,
            strength=strength * 2,
            source="preference_learning",
        )
        self._lessons[lesson.id] = lesson
    
    # === Pattern Recognition ===
    
    async def recognize_patterns(self) -> List[Pattern]:
        """
        Analyze recent episodes to discover patterns.
        
        This runs periodically to find higher-order learnings.
        """
        if len(self._episodes) < 5:
            return []
        
        new_patterns = []
        
        # Look for success patterns in context
        success_contexts = [
            e.context for e in self._episodes[-50:]
            if e.success and e.context
        ]
        
        # Find common context elements
        context_counts: Dict[str, int] = {}
        for ctx in success_contexts:
            for key, value in ctx.items():
                ctx_key = f"{key}:{value}"
                context_counts[ctx_key] = context_counts.get(ctx_key, 0) + 1
        
        # Create patterns for frequent contexts
        for ctx_key, count in context_counts.items():
            if count >= 3:  # Appears in at least 3 successes
                pattern_id = hashlib.md5(f"ctx_pattern_{ctx_key}".encode()).hexdigest()[:12]
                
                if pattern_id in self._patterns:
                    self._patterns[pattern_id].add_occurrence()
                else:
                    pattern = Pattern(
                        id=pattern_id,
                        description=f"Success often occurs with {ctx_key}",
                        pattern_type="contextual",
                        conditions={ctx_key.split(":")[0]: ctx_key.split(":")[1]},
                    )
                    pattern.occurrences = count
                    pattern.confidence = min(0.9, 0.3 + (count * 0.1))
                    self._patterns[pattern_id] = pattern
                    new_patterns.append(pattern)
                    self._stats["patterns_discovered"] += 1
        
        # Look for temporal patterns
        temporal_patterns = self._find_temporal_patterns()
        new_patterns.extend(temporal_patterns)
        
        logger.info(f"Discovered {len(new_patterns)} new patterns")
        return new_patterns
    
    def _find_temporal_patterns(self) -> List[Pattern]:
        """Find temporal patterns in episodes."""
        patterns = []
        
        # Group episodes by hour
        hour_success: Dict[int, List[bool]] = {}
        for episode in self._episodes[-100:]:
            hour = episode.timestamp.hour
            if hour not in hour_success:
                hour_success[hour] = []
            hour_success[hour].append(episode.success)
        
        # Find hours with high/low success rates
        for hour, successes in hour_success.items():
            if len(successes) >= 3:
                rate = sum(successes) / len(successes)
                
                if rate > 0.7:
                    pattern_id = f"temporal_high_{hour}"
                    if pattern_id not in self._patterns:
                        pattern = Pattern(
                            id=pattern_id,
                            description=f"Higher success rate around {hour}:00",
                            pattern_type="temporal",
                            conditions={"hour": hour, "success_rate": rate},
                        )
                        pattern.occurrences = len(successes)
                        pattern.confidence = rate
                        self._patterns[pattern_id] = pattern
                        patterns.append(pattern)
                
                elif rate < 0.3 and len(successes) >= 5:
                    pattern_id = f"temporal_low_{hour}"
                    if pattern_id not in self._patterns:
                        pattern = Pattern(
                            id=pattern_id,
                            description=f"Lower success rate around {hour}:00",
                            pattern_type="temporal",
                            conditions={"hour": hour, "success_rate": rate},
                        )
                        pattern.occurrences = len(successes)
                        pattern.confidence = 1 - rate
                        self._patterns[pattern_id] = pattern
                        patterns.append(pattern)
        
        return patterns
    
    # === Applying Learning ===
    
    def get_relevant_lessons(
        self,
        situation: str,
        context: Optional[Dict] = None,
        limit: int = 5,
    ) -> List[Lesson]:
        """
        Get lessons relevant to a situation.
        
        This is how learning is applied.
        """
        candidates = []
        
        situation_lower = situation.lower()
        context = context or {}
        
        for lesson in self._lessons.values():
            score = 0.0
            
            # Content similarity (simple keyword matching)
            lesson_content_lower = lesson.content.lower()
            words = situation_lower.split()
            matches = sum(1 for w in words if w in lesson_content_lower)
            if matches > 0:
                score += matches * 0.3
            
            # Context match
            for key, value in context.items():
                if lesson.context.get(key) == value:
                    score += 0.5
            
            # Weight by strength and confidence
            score *= lesson.strength * lesson.confidence
            
            if score > 0.1:
                candidates.append((score, lesson))
        
        # Sort by score
        candidates.sort(key=lambda x: x[0], reverse=True)
        
        # Return top lessons
        return [l for _, l in candidates[:limit]]
    
    def get_relevant_patterns(
        self,
        context: Dict[str, Any],
    ) -> List[Pattern]:
        """Get patterns that match the current context."""
        matching = []
        
        for pattern in self._patterns.values():
            if pattern.confidence < 0.3:
                continue
            
            # Check if context matches pattern conditions
            matches = True
            for cond_key, cond_value in pattern.conditions.items():
                if cond_key in context:
                    if context[cond_key] != cond_value:
                        matches = False
                        break
            
            if matches:
                matching.append(pattern)
        
        # Sort by confidence
        matching.sort(key=lambda p: p.confidence, reverse=True)
        return matching
    
    def apply_lesson(self, lesson_id: str, was_helpful: bool):
        """Record that a lesson was applied."""
        if lesson_id in self._lessons:
            self._lessons[lesson_id].apply(was_helpful)
            self._save_lesson(self._lessons[lesson_id])
            
            if was_helpful:
                self._stats["successful_applications"] += 1
    
    # === Model Updates ===
    
    def update_model_param(self, param: str, value: float, delta: bool = True):
        """Update a model parameter based on learning."""
        if param in self._model_params:
            if delta:
                if isinstance(self._model_params[param], float):
                    self._model_params[param] = max(0, min(1, self._model_params[param] + value))
            else:
                self._model_params[param] = value
    
    def get_model_params(self) -> Dict[str, Any]:
        """Get current model parameters."""
        return self._model_params.copy()
    
    # === Consolidation & Pruning ===
    
    async def consolidate(self):
        """
        Consolidate learning - strengthen important memories.
        
        This should run periodically (like during "sleep").
        """
        # Strengthen frequently helpful lessons
        for lesson in self._lessons.values():
            if lesson.times_applied >= 5 and lesson.times_helpful / lesson.times_applied > 0.7:
                lesson.strength = min(10.0, lesson.strength + 0.2)
        
        # Strengthen strong patterns
        for pattern in self._patterns.values():
            if pattern.occurrences >= 10 and pattern.confidence > 0.7:
                pattern.predictive_power = min(1.0, pattern.predictive_power + 0.1)
        
        logger.debug("Learning consolidation complete")
    
    async def prune(self):
        """
        Prune weak learnings - forget irrelevant things.
        
        This prevents the learning system from getting cluttered.
        """
        # Prune weak lessons
        weak_lessons = [
            lid for lid, l in self._lessons.items()
            if l.strength < 0.3 and l.times_applied > 5 and l.confidence < 0.3
        ]
        
        for lid in weak_lessons:
            del self._lessons[lid]
        
        # Prune weak patterns
        weak_patterns = [
            pid for pid, p in self._patterns.items()
            if p.confidence < 0.2 and p.occurrences > 20
        ]
        
        for pid in weak_patterns:
            del self._patterns[pid]
        
        if weak_lessons or weak_patterns:
            logger.info(f"Pruned {len(weak_lessons)} lessons and {len(weak_patterns)} patterns")
    
    # === Statistics ===
    
    def get_stats(self) -> Dict[str, Any]:
        """Get learning statistics."""
        return {
            **self._stats,
            "current_lessons": len(self._lessons),
            "current_patterns": len(self._patterns),
            "episodes_in_memory": len(self._episodes),
            "user_preferences_count": len(self._user_preferences),
            "strong_lessons": len([l for l in self._lessons.values() if l.strength > 5]),
            "high_confidence_patterns": len([p for p in self._patterns.values() if p.confidence > 0.7]),
        }
    
    def get_learning_summary(self) -> Dict[str, Any]:
        """Get a summary of what has been learned."""
        # Top lessons
        top_lessons = sorted(
            self._lessons.values(),
            key=lambda l: l.strength * l.confidence,
            reverse=True
        )[:10]
        
        # Top patterns
        top_patterns = sorted(
            self._patterns.values(),
            key=lambda p: p.confidence * (p.predictive_power + 0.1),
            reverse=True
        )[:10]
        
        # Recent corrections
        recent_corrections = self._user_corrections[-5:]
        
        return {
            "top_lessons": [l.to_dict() for l in top_lessons],
            "top_patterns": [p.to_dict() for p in top_patterns],
            "recent_corrections": recent_corrections,
            "user_preferences": dict(sorted(
                self._user_preferences.items(),
                key=lambda x: x[1],
                reverse=True
            )[:20]),
            "model_params": self._model_params,
        }


# Singleton
_learning_engine: Optional[LearningEngine] = None

def get_learning_engine() -> LearningEngine:
    """Get or create the learning engine singleton."""
    global _learning_engine
    if _learning_engine is None:
        _learning_engine = LearningEngine(Path.home() / ".apex" / "learning")
    return _learning_engine
