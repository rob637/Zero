"""
Predictive Modeling - Anticipating the future.

This is looking ahead:
- Pattern-based prediction
- Timeline projection
- Outcome estimation
- Proactive identification
- Anticipatory preparation

The brain that can predict is the brain that can prepare.
"""

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class PredictionType(Enum):
    """Types of predictions."""
    EVENT = "event"                  # Something will happen
    NEED = "need"                    # User will need something
    PATTERN = "pattern"              # A pattern will repeat
    DEADLINE = "deadline"            # A deadline is approaching
    PREFERENCE = "preference"        # User will prefer something
    PROBLEM = "problem"              # A problem will occur


class TimeHorizon(Enum):
    """When the prediction is for."""
    IMMEDIATE = "immediate"          # Now / very soon
    SHORT_TERM = "short_term"        # Hours to a day
    MEDIUM_TERM = "medium_term"      # Days to a week
    LONG_TERM = "long_term"          # Weeks to months


@dataclass
class Prediction:
    """
    A prediction about the future.
    """
    id: str
    prediction_type: PredictionType
    statement: str                   # What we predict
    
    # Timing
    time_horizon: TimeHorizon
    expected_time: Optional[datetime] = None
    window_hours: float = 24.0       # Prediction window
    
    # Confidence
    confidence: float = 0.5
    basis: str = ""                  # Why we predict this
    
    # Validation
    validated: bool = False
    outcome: Optional[bool] = None   # True = happened, False = didn't
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    
    @property
    def is_expired(self) -> bool:
        """Has the prediction window passed?"""
        if not self.expected_time:
            return False
        deadline = self.expected_time + timedelta(hours=self.window_hours)
        return datetime.now() > deadline
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.prediction_type.value,
            "statement": self.statement,
            "time_horizon": self.time_horizon.value,
            "expected_time": self.expected_time.isoformat() if self.expected_time else None,
            "confidence": self.confidence,
            "basis": self.basis,
            "validated": self.validated,
            "outcome": self.outcome,
        }


@dataclass 
class TemporalPattern:
    """
    A recurring pattern over time.
    """
    id: str
    description: str
    pattern_type: str                # "daily", "weekly", "monthly", "event_based"
    
    # Pattern data
    occurrences: List[datetime] = field(default_factory=list)
    typical_time: Optional[str] = None  # "09:00", "monday"
    interval_hours: Optional[float] = None
    
    # Stats
    confidence: float = 0.5
    last_occurrence: Optional[datetime] = None
    
    def add_occurrence(self, when: datetime):
        """Add a new occurrence."""
        self.occurrences.append(when)
        self.last_occurrence = when
        
        # Update confidence based on consistency
        if len(self.occurrences) >= 3:
            self._update_confidence()
    
    def _update_confidence(self):
        """Update confidence based on pattern consistency."""
        if len(self.occurrences) < 3:
            return
        
        # Calculate intervals
        intervals = []
        for i in range(1, len(self.occurrences)):
            delta = self.occurrences[i] - self.occurrences[i-1]
            intervals.append(delta.total_seconds() / 3600)
        
        if not intervals:
            return
        
        # Measure consistency (coefficient of variation)
        avg_interval = sum(intervals) / len(intervals)
        if avg_interval == 0:
            return
            
        variance = sum((i - avg_interval) ** 2 for i in intervals) / len(intervals)
        std_dev = variance ** 0.5
        cv = std_dev / avg_interval
        
        # Lower CV = more consistent = higher confidence
        self.confidence = max(0.3, min(0.95, 1.0 - cv))
        self.interval_hours = avg_interval
    
    def predict_next(self) -> Optional[datetime]:
        """Predict the next occurrence."""
        if not self.last_occurrence or not self.interval_hours:
            return None
        
        return self.last_occurrence + timedelta(hours=self.interval_hours)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "pattern_type": self.pattern_type,
            "confidence": self.confidence,
            "interval_hours": self.interval_hours,
            "occurrence_count": len(self.occurrences),
            "next_predicted": self.predict_next().isoformat() if self.predict_next() else None,
        }


class PredictiveModel:
    """
    The predictive system - anticipating the future.
    
    Capabilities:
    1. Pattern learning - identify recurring patterns
    2. Event prediction - anticipate upcoming events
    3. Need prediction - anticipate user needs
    4. Timeline projection - what happens when
    5. Outcome estimation - what's likely to happen
    """
    
    def __init__(self, storage_path: Optional[Path] = None):
        self._storage_path = storage_path
        
        # Predictions
        self._predictions: Dict[str, Prediction] = {}
        
        # Patterns
        self._patterns: Dict[str, TemporalPattern] = {}
        
        # User model for preference prediction
        self._user_preferences: Dict[str, Dict[str, int]] = {}  # category -> {choice: count}
        
        # Prediction accuracy tracking
        self._accuracy_history: List[Tuple[bool, float]] = []  # (correct, confidence)
        
        # Initialize storage
        if storage_path:
            self._init_storage()
    
    def _init_storage(self):
        """Initialize persistent storage."""
        self._storage_path.mkdir(parents=True, exist_ok=True)
        db_path = self._storage_path / "predictions.db"
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS predictions (
                id TEXT PRIMARY KEY,
                type TEXT,
                statement TEXT,
                time_horizon TEXT,
                expected_time TEXT,
                confidence REAL,
                basis TEXT,
                validated INTEGER,
                outcome INTEGER,
                created_at TEXT
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS patterns (
                id TEXT PRIMARY KEY,
                description TEXT,
                pattern_type TEXT,
                typical_time TEXT,
                interval_hours REAL,
                confidence REAL,
                data TEXT
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                category TEXT,
                choice TEXT,
                count INTEGER,
                PRIMARY KEY (category, choice)
            )
        """)
        
        conn.commit()
        conn.close()
    
    # === Pattern Learning ===
    
    def observe_event(self, event_type: str, metadata: Optional[Dict[str, Any]] = None):
        """
        Observe an event to learn patterns.
        """
        pattern_id = f"pattern_{event_type}"
        
        if pattern_id not in self._patterns:
            self._patterns[pattern_id] = TemporalPattern(
                id=pattern_id,
                description=f"Pattern for {event_type}",
                pattern_type="event_based",
            )
        
        self._patterns[pattern_id].add_occurrence(datetime.now())
        
        # Persist
        if self._storage_path:
            self._persist_pattern(self._patterns[pattern_id])
    
    def _persist_pattern(self, pattern: TemporalPattern):
        """Persist a pattern to storage."""
        db_path = self._storage_path / "predictions.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO patterns 
            (id, description, pattern_type, typical_time, interval_hours, confidence, data)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            pattern.id,
            pattern.description,
            pattern.pattern_type,
            pattern.typical_time,
            pattern.interval_hours,
            pattern.confidence,
            json.dumps([o.isoformat() for o in pattern.occurrences[-100:]]),  # Keep last 100
        ))
        
        conn.commit()
        conn.close()
    
    def get_patterns(self, min_confidence: float = 0.5) -> List[Dict[str, Any]]:
        """Get learned patterns."""
        patterns = [p for p in self._patterns.values() if p.confidence >= min_confidence]
        return [p.to_dict() for p in patterns]
    
    # === Event Prediction ===
    
    def predict(
        self,
        prediction_type: PredictionType,
        statement: str,
        time_horizon: TimeHorizon,
        confidence: float,
        basis: str,
        expected_time: Optional[datetime] = None,
    ) -> Prediction:
        """
        Make a prediction.
        """
        pred_id = hashlib.md5(
            f"{statement}_{datetime.now().isoformat()}".encode()
        ).hexdigest()[:12]
        
        prediction = Prediction(
            id=pred_id,
            prediction_type=prediction_type,
            statement=statement,
            time_horizon=time_horizon,
            expected_time=expected_time,
            confidence=confidence,
            basis=basis,
        )
        
        self._predictions[pred_id] = prediction
        
        # Persist
        if self._storage_path:
            self._persist_prediction(prediction)
        
        return prediction
    
    def _persist_prediction(self, pred: Prediction):
        """Persist a prediction to storage."""
        db_path = self._storage_path / "predictions.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO predictions 
            (id, type, statement, time_horizon, expected_time, confidence, basis, validated, outcome, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pred.id,
            pred.prediction_type.value,
            pred.statement,
            pred.time_horizon.value,
            pred.expected_time.isoformat() if pred.expected_time else None,
            pred.confidence,
            pred.basis,
            1 if pred.validated else 0,
            1 if pred.outcome else (0 if pred.outcome is False else None),
            pred.created_at.isoformat(),
        ))
        
        conn.commit()
        conn.close()
    
    def validate_prediction(self, prediction_id: str, outcome: bool):
        """Validate whether a prediction came true."""
        pred = self._predictions.get(prediction_id)
        if not pred:
            return
        
        pred.validated = True
        pred.outcome = outcome
        
        # Track accuracy
        self._accuracy_history.append((outcome, pred.confidence))
        
        # Persist
        if self._storage_path:
            self._persist_prediction(pred)
    
    # === Need Prediction ===
    
    def predict_needs(
        self,
        context: Dict[str, Any],
        time_horizon: TimeHorizon = TimeHorizon.SHORT_TERM,
    ) -> List[Prediction]:
        """
        Predict what the user might need.
        """
        predictions = []
        now = datetime.now()
        
        # Check patterns for upcoming events
        for pattern in self._patterns.values():
            next_occurrence = pattern.predict_next()
            if next_occurrence and pattern.confidence > 0.5:
                # Check if within time horizon
                horizon_hours = {
                    TimeHorizon.IMMEDIATE: 1,
                    TimeHorizon.SHORT_TERM: 24,
                    TimeHorizon.MEDIUM_TERM: 168,
                    TimeHorizon.LONG_TERM: 720,
                }[time_horizon]
                
                if next_occurrence < now + timedelta(hours=horizon_hours):
                    pred = self.predict(
                        PredictionType.PATTERN,
                        f"Based on pattern: {pattern.description}",
                        time_horizon,
                        pattern.confidence * 0.9,  # Slightly lower than pattern confidence
                        f"Seen {len(pattern.occurrences)} times with {pattern.interval_hours:.1f}h average interval",
                        next_occurrence,
                    )
                    predictions.append(pred)
        
        # Check for calendar-based needs
        if "upcoming_events" in context:
            for event in context["upcoming_events"][:5]:  # Top 5 soonest
                pred = self.predict(
                    PredictionType.NEED,
                    f"Prepare for: {event.get('summary', 'upcoming event')}",
                    TimeHorizon.SHORT_TERM,
                    0.7,
                    "Calendar event approaching",
                    event.get("start_time"),
                )
                predictions.append(pred)
        
        # Check for deadline-based needs
        if "deadlines" in context:
            for deadline in context["deadlines"]:
                urgency = 0.5
                if deadline.get("days_until", 999) < 3:
                    urgency = 0.8
                elif deadline.get("days_until", 999) < 7:
                    urgency = 0.6
                
                pred = self.predict(
                    PredictionType.DEADLINE,
                    f"Deadline approaching: {deadline.get('description', 'deadline')}",
                    TimeHorizon.SHORT_TERM,
                    urgency,
                    f"Due in {deadline.get('days_until', '?')} days",
                )
                predictions.append(pred)
        
        return predictions
    
    # === Preference Prediction ===
    
    def observe_preference(self, category: str, choice: str):
        """Observe a user preference."""
        if category not in self._user_preferences:
            self._user_preferences[category] = {}
        
        if choice not in self._user_preferences[category]:
            self._user_preferences[category][choice] = 0
        
        self._user_preferences[category][choice] += 1
        
        # Persist
        if self._storage_path:
            self._persist_preference(category, choice)
    
    def _persist_preference(self, category: str, choice: str):
        """Persist a preference observation."""
        db_path = self._storage_path / "predictions.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        count = self._user_preferences[category][choice]
        cursor.execute("""
            INSERT OR REPLACE INTO user_preferences (category, choice, count)
            VALUES (?, ?, ?)
        """, (category, choice, count))
        
        conn.commit()
        conn.close()
    
    def predict_preference(self, category: str, options: List[str]) -> Tuple[str, float]:
        """
        Predict which option the user will prefer.
        
        Returns (predicted_choice, confidence).
        """
        if category not in self._user_preferences:
            return options[0] if options else "", 0.5
        
        prefs = self._user_preferences[category]
        total = sum(prefs.values())
        
        if total == 0:
            return options[0] if options else "", 0.5
        
        # Score each option
        scores = []
        for opt in options:
            count = prefs.get(opt, 0)
            score = count / total
            scores.append((opt, score))
        
        # Sort by score
        scores.sort(key=lambda x: x[1], reverse=True)
        
        best = scores[0]
        confidence = 0.5 + (best[1] * 0.4)  # Base 0.5, up to 0.9
        
        return best[0], min(confidence, 0.9)
    
    # === Timeline Projection ===
    
    def project_timeline(
        self,
        events: List[Dict[str, Any]],
        duration_hours: float = 24.0,
    ) -> List[Dict[str, Any]]:
        """
        Project what's coming up in a timeline.
        """
        now = datetime.now()
        end_time = now + timedelta(hours=duration_hours)
        
        timeline = []
        
        # Add explicit events
        for event in events:
            event_time = event.get("time")
            if isinstance(event_time, str):
                try:
                    event_time = datetime.fromisoformat(event_time)
                except:
                    continue
            
            if event_time and now <= event_time <= end_time:
                timeline.append({
                    "time": event_time.isoformat(),
                    "type": "event",
                    "description": event.get("description", "Event"),
                    "confidence": 1.0,  # Explicit events are certain
                })
        
        # Add pattern-based predictions
        for pattern in self._patterns.values():
            next_occurrence = pattern.predict_next()
            if next_occurrence and now <= next_occurrence <= end_time:
                timeline.append({
                    "time": next_occurrence.isoformat(),
                    "type": "predicted",
                    "description": pattern.description,
                    "confidence": pattern.confidence,
                })
        
        # Add pending predictions
        for pred in self._predictions.values():
            if pred.expected_time and now <= pred.expected_time <= end_time:
                if not pred.validated:
                    timeline.append({
                        "time": pred.expected_time.isoformat(),
                        "type": "prediction",
                        "description": pred.statement,
                        "confidence": pred.confidence,
                    })
        
        # Sort by time
        timeline.sort(key=lambda x: x["time"])
        
        return timeline
    
    # === Outcome Estimation ===
    
    def estimate_outcome(
        self,
        action: str,
        context: Dict[str, Any],
    ) -> Tuple[str, float]:
        """
        Estimate the likely outcome of an action.
        
        Returns (likely_outcome, confidence).
        """
        action_lower = action.lower()
        
        # Check for similar past situations in patterns
        base_confidence = 0.5
        likely_outcome = "uncertain"
        
        # Simple heuristics based on action type
        if "send" in action_lower and "email" in action_lower:
            likely_outcome = "Email will be delivered successfully"
            base_confidence = 0.9
        elif "schedule" in action_lower or "calendar" in action_lower:
            likely_outcome = "Event will be created"
            base_confidence = 0.85
        elif "delete" in action_lower or "remove" in action_lower:
            likely_outcome = "Items will be removed permanently"
            base_confidence = 0.95
        elif "organize" in action_lower or "sort" in action_lower:
            likely_outcome = "Files will be reorganized"
            base_confidence = 0.8
        elif "search" in action_lower or "find" in action_lower:
            likely_outcome = "Results will be found if they exist"
            base_confidence = 0.7
        
        # Adjust based on prediction accuracy history
        if self._accuracy_history:
            accuracy = sum(1 for correct, _ in self._accuracy_history if correct) / len(self._accuracy_history)
            # If our predictions have been accurate, we can be more confident
            base_confidence *= (0.8 + accuracy * 0.2)
        
        return likely_outcome, min(base_confidence, 0.95)
    
    # === Stats ===
    
    def get_active_predictions(self) -> List[Dict[str, Any]]:
        """Get predictions that haven't been validated yet."""
        active = [p for p in self._predictions.values() if not p.validated and not p.is_expired]
        return [p.to_dict() for p in active]
    
    def get_accuracy_stats(self) -> Dict[str, Any]:
        """Get prediction accuracy statistics."""
        if not self._accuracy_history:
            return {"predictions_made": 0, "accuracy": None}
        
        total = len(self._accuracy_history)
        correct = sum(1 for c, _ in self._accuracy_history if c)
        
        # Confidence-weighted accuracy
        weighted_correct = sum(conf for c, conf in self._accuracy_history if c)
        weighted_total = sum(conf for _, conf in self._accuracy_history)
        
        return {
            "predictions_made": total,
            "correct": correct,
            "accuracy": correct / total if total > 0 else None,
            "weighted_accuracy": weighted_correct / weighted_total if weighted_total > 0 else None,
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get predictive model statistics."""
        accuracy_stats = self.get_accuracy_stats()
        return {
            "predictions": len(self._predictions),
            "active_predictions": len([p for p in self._predictions.values() if not p.validated]),
            "patterns": len(self._patterns),
            "high_confidence_patterns": len([p for p in self._patterns.values() if p.confidence > 0.7]),
            "preference_categories": len(self._user_preferences),
            **accuracy_stats,
        }
