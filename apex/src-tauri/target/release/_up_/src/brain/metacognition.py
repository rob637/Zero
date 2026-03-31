"""
Metacognition - The brain thinking about itself.

This is self-awareness:
- Knowing what you know (and don't know)
- Confidence calibration
- Learning from mistakes
- Self-reflection
- Identifying gaps in knowledge

This is what separates intelligent systems from mechanical ones.
"""

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class KnowledgeState(Enum):
    """How well we know something."""
    UNKNOWN = "unknown"              # Never encountered
    UNCERTAIN = "uncertain"          # Encountered but unsure
    PARTIAL = "partial"              # Know some things
    CONFIDENT = "confident"          # Know well
    MASTERED = "mastered"            # Deep expertise


class LearningOutcome(Enum):
    """What happened when we tried something."""
    SUCCESS = "success"              # It worked
    PARTIAL_SUCCESS = "partial"      # Partially worked
    FAILURE = "failure"              # Didn't work
    UNEXPECTED = "unexpected"        # Something else happened


@dataclass
class KnowledgeBelief:
    """
    A belief about what we know.
    
    Tracks confidence and how it changes over time.
    """
    domain: str                      # What area this is about
    belief: str                      # What we believe
    confidence: float                # 0-1 how sure we are
    
    # Evidence
    confirmations: int = 0           # Times this was confirmed
    contradictions: int = 0          # Times this was contradicted
    
    # History
    last_tested: Optional[datetime] = None
    last_updated: datetime = field(default_factory=datetime.now)
    
    def update(self, outcome: bool):
        """Update belief based on new evidence."""
        if outcome:
            self.confirmations += 1
            # Increase confidence, with diminishing returns
            delta = 0.1 * (1.0 - self.confidence)
            self.confidence = min(1.0, self.confidence + delta)
        else:
            self.contradictions += 1
            # Decrease confidence
            self.confidence = max(0.0, self.confidence - 0.15)
        
        self.last_tested = datetime.now()
        self.last_updated = datetime.now()
    
    @property
    def reliability(self) -> float:
        """How reliable is this belief?"""
        total = self.confirmations + self.contradictions
        if total == 0:
            return 0.5
        return self.confirmations / total
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "belief": self.belief,
            "confidence": self.confidence,
            "reliability": self.reliability,
            "confirmations": self.confirmations,
            "contradictions": self.contradictions,
        }


@dataclass
class ConfidenceRecord:
    """
    Record of a confidence estimate and what actually happened.
    
    Used for confidence calibration.
    """
    timestamp: datetime
    prediction: str
    confidence: float               # What we thought would happen
    actual_outcome: bool            # What actually happened
    
    @property
    def calibration_error(self) -> float:
        """How wrong was our confidence?"""
        actual = 1.0 if self.actual_outcome else 0.0
        return abs(self.confidence - actual)


@dataclass
class Mistake:
    """
    A mistake we made - something to learn from.
    """
    id: str
    description: str
    category: str                   # "reasoning", "prediction", "action", "memory"
    
    # What happened
    what_we_thought: str
    what_actually_happened: str
    
    # Learning
    lesson: Optional[str] = None
    times_similar: int = 1          # Similar mistakes made
    
    # Metadata
    timestamp: datetime = field(default_factory=datetime.now)
    context: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "category": self.category,
            "what_we_thought": self.what_we_thought,
            "what_actually_happened": self.what_actually_happened,
            "lesson": self.lesson,
            "times_similar": self.times_similar,
        }


class Metacognition:
    """
    Metacognition - thinking about thinking.
    
    This system provides:
    1. Knowledge state tracking - what do we know?
    2. Confidence calibration - are our estimates accurate?
    3. Mistake tracking - what have we learned from failure?
    4. Self-reflection - structured introspection
    5. Uncertainty quantification - how sure are we?
    """
    
    def __init__(self, storage_path: Optional[Path] = None):
        self._storage_path = storage_path
        
        # Knowledge beliefs
        self._beliefs: Dict[str, KnowledgeBelief] = {}
        
        # Confidence calibration
        self._confidence_records: List[ConfidenceRecord] = []
        self._calibration_bins: Dict[int, Tuple[int, int]] = {}  # bin -> (correct, total)
        
        # Mistakes
        self._mistakes: Dict[str, Mistake] = {}
        
        # Self-model
        self._strengths: List[str] = []
        self._weaknesses: List[str] = []
        self._current_state: Dict[str, Any] = {
            "mental_load": 0.3,  # How taxed is the system
            "uncertainty_level": 0.5,  # Overall uncertainty
        }
        
        # Initialize storage
        if storage_path:
            self._init_storage()
    
    def _init_storage(self):
        """Initialize persistent storage."""
        self._storage_path.mkdir(parents=True, exist_ok=True)
        db_path = self._storage_path / "metacognition.db"
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS beliefs (
                id TEXT PRIMARY KEY,
                domain TEXT,
                belief TEXT,
                confidence REAL,
                confirmations INTEGER,
                contradictions INTEGER,
                last_updated TEXT
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mistakes (
                id TEXT PRIMARY KEY,
                description TEXT,
                category TEXT,
                what_we_thought TEXT,
                what_actually_happened TEXT,
                lesson TEXT,
                times_similar INTEGER,
                timestamp TEXT
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS confidence_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                prediction TEXT,
                confidence REAL,
                actual_outcome INTEGER
            )
        """)
        
        conn.commit()
        conn.close()
    
    # === Knowledge State ===
    
    def assess_knowledge(self, domain: str) -> KnowledgeState:
        """
        Assess our knowledge state for a domain.
        """
        beliefs = [b for b in self._beliefs.values() if b.domain == domain]
        
        if not beliefs:
            return KnowledgeState.UNKNOWN
        
        avg_confidence = sum(b.confidence for b in beliefs) / len(beliefs)
        avg_reliability = sum(b.reliability for b in beliefs) / len(beliefs)
        
        combined_score = (avg_confidence + avg_reliability) / 2
        
        if combined_score > 0.9:
            return KnowledgeState.MASTERED
        elif combined_score > 0.7:
            return KnowledgeState.CONFIDENT
        elif combined_score > 0.4:
            return KnowledgeState.PARTIAL
        else:
            return KnowledgeState.UNCERTAIN
    
    def update_belief(self, domain: str, belief: str, outcome: bool):
        """
        Update a belief based on evidence.
        """
        key = f"{domain}:{belief}"
        
        if key not in self._beliefs:
            self._beliefs[key] = KnowledgeBelief(
                domain=domain,
                belief=belief,
                confidence=0.5,
            )
        
        self._beliefs[key].update(outcome)
        
        # Persist
        if self._storage_path:
            self._persist_belief(self._beliefs[key])
    
    def _persist_belief(self, belief: KnowledgeBelief):
        """Persist a belief to storage."""
        db_path = self._storage_path / "metacognition.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        key = f"{belief.domain}:{belief.belief}"
        cursor.execute("""
            INSERT OR REPLACE INTO beliefs 
            (id, domain, belief, confidence, confirmations, contradictions, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            key,
            belief.domain,
            belief.belief,
            belief.confidence,
            belief.confirmations,
            belief.contradictions,
            belief.last_updated.isoformat(),
        ))
        
        conn.commit()
        conn.close()
    
    def get_beliefs(self, domain: Optional[str] = None, min_confidence: float = 0.0) -> List[Dict[str, Any]]:
        """Get current beliefs."""
        beliefs = self._beliefs.values()
        
        if domain:
            beliefs = [b for b in beliefs if b.domain == domain]
        
        beliefs = [b for b in beliefs if b.confidence >= min_confidence]
        
        return [b.to_dict() for b in beliefs]
    
    # === Confidence Calibration ===
    
    def record_confidence(self, prediction: str, confidence: float, actual_outcome: bool):
        """
        Record a confidence estimate and its outcome.
        
        Used to calibrate future confidence estimates.
        """
        record = ConfidenceRecord(
            timestamp=datetime.now(),
            prediction=prediction,
            confidence=confidence,
            actual_outcome=actual_outcome,
        )
        
        self._confidence_records.append(record)
        
        # Update calibration bins (0-10, 10-20, ..., 90-100)
        bin_index = min(9, int(confidence * 10))
        if bin_index not in self._calibration_bins:
            self._calibration_bins[bin_index] = (0, 0)
        
        correct, total = self._calibration_bins[bin_index]
        self._calibration_bins[bin_index] = (
            correct + (1 if actual_outcome else 0),
            total + 1
        )
        
        # Persist
        if self._storage_path:
            self._persist_confidence_record(record)
    
    def _persist_confidence_record(self, record: ConfidenceRecord):
        """Persist a confidence record."""
        db_path = self._storage_path / "metacognition.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO confidence_records (timestamp, prediction, confidence, actual_outcome)
            VALUES (?, ?, ?, ?)
        """, (
            record.timestamp.isoformat(),
            record.prediction,
            record.confidence,
            1 if record.actual_outcome else 0,
        ))
        
        conn.commit()
        conn.close()
    
    def calibrate_confidence(self, raw_confidence: float) -> float:
        """
        Calibrate a confidence estimate based on past accuracy.
        
        If we've historically been overconfident, this will reduce
        our confidence. If underconfident, it will increase it.
        """
        if not self._calibration_bins:
            return raw_confidence
        
        # Find the appropriate bin
        bin_index = min(9, int(raw_confidence * 10))
        
        if bin_index not in self._calibration_bins:
            return raw_confidence
        
        correct, total = self._calibration_bins[bin_index]
        if total < 5:  # Need enough samples
            return raw_confidence
        
        # Actual accuracy in this bin
        actual_accuracy = correct / total
        
        # Blend raw confidence with historical accuracy
        # More weight to historical as we get more samples
        weight = min(0.5, total / 100)
        calibrated = raw_confidence * (1 - weight) + actual_accuracy * weight
        
        return calibrated
    
    def get_calibration_stats(self) -> Dict[str, Any]:
        """Get confidence calibration statistics."""
        stats = {
            "total_records": len(self._confidence_records),
            "bins": {},
            "overall_calibration_error": 0.0,
        }
        
        total_error = 0.0
        total_count = 0
        
        for bin_idx, (correct, total) in self._calibration_bins.items():
            if total > 0:
                expected = (bin_idx + 0.5) / 10  # Midpoint of bin
                actual = correct / total
                error = abs(expected - actual)
                
                stats["bins"][f"{bin_idx*10}-{(bin_idx+1)*10}%"] = {
                    "expected": expected,
                    "actual": actual,
                    "error": error,
                    "samples": total,
                }
                
                total_error += error * total
                total_count += total
        
        if total_count > 0:
            stats["overall_calibration_error"] = total_error / total_count
        
        return stats
    
    # === Mistake Tracking ===
    
    def record_mistake(
        self,
        description: str,
        category: str,
        what_we_thought: str,
        what_actually_happened: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Mistake:
        """
        Record a mistake for learning.
        """
        import hashlib
        
        mistake_id = hashlib.md5(
            f"{category}:{description}:{datetime.now().isoformat()}".encode()
        ).hexdigest()[:12]
        
        # Check for similar mistakes
        similar = self._find_similar_mistake(description, category)
        if similar:
            similar.times_similar += 1
            return similar
        
        mistake = Mistake(
            id=mistake_id,
            description=description,
            category=category,
            what_we_thought=what_we_thought,
            what_actually_happened=what_actually_happened,
            context=context or {},
        )
        
        self._mistakes[mistake_id] = mistake
        
        # Persist
        if self._storage_path:
            self._persist_mistake(mistake)
        
        return mistake
    
    def _find_similar_mistake(self, description: str, category: str) -> Optional[Mistake]:
        """Find a similar mistake."""
        description_lower = description.lower()
        
        for mistake in self._mistakes.values():
            if mistake.category != category:
                continue
            
            # Simple similarity check
            if description_lower in mistake.description.lower() or \
               mistake.description.lower() in description_lower:
                return mistake
        
        return None
    
    def _persist_mistake(self, mistake: Mistake):
        """Persist a mistake to storage."""
        db_path = self._storage_path / "metacognition.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO mistakes 
            (id, description, category, what_we_thought, what_actually_happened, lesson, times_similar, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            mistake.id,
            mistake.description,
            mistake.category,
            mistake.what_we_thought,
            mistake.what_actually_happened,
            mistake.lesson,
            mistake.times_similar,
            mistake.timestamp.isoformat(),
        ))
        
        conn.commit()
        conn.close()
    
    def add_lesson(self, mistake_id: str, lesson: str):
        """Add a lesson learned from a mistake."""
        mistake = self._mistakes.get(mistake_id)
        if mistake:
            mistake.lesson = lesson
            if self._storage_path:
                self._persist_mistake(mistake)
    
    def get_mistakes(self, category: Optional[str] = None, min_times: int = 1) -> List[Dict[str, Any]]:
        """Get recorded mistakes."""
        mistakes = self._mistakes.values()
        
        if category:
            mistakes = [m for m in mistakes if m.category == category]
        
        mistakes = [m for m in mistakes if m.times_similar >= min_times]
        
        return [m.to_dict() for m in mistakes]
    
    # === Self-Reflection ===
    
    def reflect(self) -> Dict[str, Any]:
        """
        Perform self-reflection - assess current state.
        """
        reflection = {
            "timestamp": datetime.now().isoformat(),
            "knowledge_summary": {},
            "calibration_quality": "unknown",
            "recurring_mistakes": [],
            "strengths": self._strengths,
            "weaknesses": self._weaknesses,
            "recommendations": [],
        }
        
        # Summarize knowledge by domain
        domains = set(b.domain for b in self._beliefs.values())
        for domain in domains:
            state = self.assess_knowledge(domain)
            beliefs = [b for b in self._beliefs.values() if b.domain == domain]
            reflection["knowledge_summary"][domain] = {
                "state": state.value,
                "belief_count": len(beliefs),
                "avg_confidence": sum(b.confidence for b in beliefs) / len(beliefs) if beliefs else 0,
            }
        
        # Assess calibration quality
        cal_stats = self.get_calibration_stats()
        error = cal_stats.get("overall_calibration_error", 0.5)
        if error < 0.1:
            reflection["calibration_quality"] = "excellent"
        elif error < 0.2:
            reflection["calibration_quality"] = "good"
        elif error < 0.3:
            reflection["calibration_quality"] = "fair"
        else:
            reflection["calibration_quality"] = "poor"
        
        # Find recurring mistakes
        recurring = [m.to_dict() for m in self._mistakes.values() if m.times_similar > 2]
        reflection["recurring_mistakes"] = recurring
        
        # Generate recommendations
        if reflection["calibration_quality"] in ["poor", "fair"]:
            reflection["recommendations"].append(
                "Confidence estimates have been inaccurate - consider being more conservative"
            )
        
        if recurring:
            reflection["recommendations"].append(
                f"There are {len(recurring)} recurring mistakes - review lessons learned"
            )
        
        uncertain_domains = [d for d, s in reflection["knowledge_summary"].items() 
                           if s["state"] in ["unknown", "uncertain"]]
        if uncertain_domains:
            reflection["recommendations"].append(
                f"Knowledge gaps in domains: {', '.join(uncertain_domains)}"
            )
        
        return reflection
    
    def update_self_model(self, strength: Optional[str] = None, weakness: Optional[str] = None):
        """Update the self-model."""
        if strength and strength not in self._strengths:
            self._strengths.append(strength)
        
        if weakness and weakness not in self._weaknesses:
            self._weaknesses.append(weakness)
    
    # === Uncertainty Quantification ===
    
    def estimate_uncertainty(self, task_type: str, context: Dict[str, Any]) -> float:
        """
        Estimate uncertainty for a task.
        
        Returns 0-1 where higher means more uncertain.
        """
        base_uncertainty = 0.3
        
        # Check knowledge state for relevant domain
        knowledge_state = self.assess_knowledge(task_type)
        if knowledge_state == KnowledgeState.UNKNOWN:
            base_uncertainty += 0.4
        elif knowledge_state == KnowledgeState.UNCERTAIN:
            base_uncertainty += 0.3
        elif knowledge_state == KnowledgeState.PARTIAL:
            base_uncertainty += 0.1
        elif knowledge_state == KnowledgeState.CONFIDENT:
            base_uncertainty -= 0.1
        elif knowledge_state == KnowledgeState.MASTERED:
            base_uncertainty -= 0.2
        
        # Check for similar past mistakes
        mistakes = [m for m in self._mistakes.values() if m.category == task_type]
        if mistakes:
            base_uncertainty += 0.1 * min(len(mistakes), 3)
        
        # Apply calibration
        if self._calibration_bins:
            # If we've been overconfident, increase uncertainty
            cal_stats = self.get_calibration_stats()
            error = cal_stats.get("overall_calibration_error", 0)
            base_uncertainty += error * 0.5
        
        return max(0.0, min(1.0, base_uncertainty))
    
    def should_ask_for_help(self, task_description: str, uncertainty: float) -> Tuple[bool, str]:
        """
        Should we ask for help or clarification?
        
        Returns (should_ask, reason).
        """
        # High uncertainty
        if uncertainty > 0.7:
            return True, f"High uncertainty ({uncertainty:.0%}) about this task"
        
        # Recurring mistakes in this area
        task_lower = task_description.lower()
        for mistake in self._mistakes.values():
            if mistake.times_similar > 2:
                if any(word in task_lower for word in mistake.description.lower().split()):
                    return True, f"Similar tasks have led to repeated mistakes"
        
        # Unknown domain
        words = task_lower.split()
        for word in words:
            if self.assess_knowledge(word) == KnowledgeState.UNKNOWN:
                return True, f"Unfamiliar with '{word}'"
        
        return False, ""
    
    # === Stats ===
    
    def get_stats(self) -> Dict[str, Any]:
        """Get metacognition statistics."""
        return {
            "beliefs": len(self._beliefs),
            "confidence_records": len(self._confidence_records),
            "mistakes": len(self._mistakes),
            "recurring_mistakes": len([m for m in self._mistakes.values() if m.times_similar > 2]),
            "strengths": len(self._strengths),
            "weaknesses": len(self._weaknesses),
            "calibration_error": self.get_calibration_stats().get("overall_calibration_error", 0.5),
        }
