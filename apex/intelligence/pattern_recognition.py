"""
Pattern Recognition Engine

Detects recurring patterns in user behavior:

1. TEMPORAL PATTERNS
   - Weekly routines (Monday standup, Friday reports)
   - Daily rhythms (email mornings, deep work afternoons)
   - Seasonal patterns (quarterly reviews, annual planning)

2. SEQUENCE PATTERNS
   - Workflow sequences (pull data -> analyze -> report)
   - Action chains (email arrives -> create task -> schedule meeting)
   - Preparation patterns (meeting coming -> gather docs)

3. CORRELATION PATTERNS
   - What triggers what (budget email -> expense review)
   - Who triggers what (message from boss -> quick response)
   - Context triggers (location change -> activity change)

4. ANOMALY DETECTION
   - Unusual timing (working at 2am?)
   - Missing patterns (no Monday standup?)
   - Frequency changes (suddenly lots of meetings)

Usage:
    from intelligence.pattern_recognition import PatternEngine
    
    engine = PatternEngine()
    
    # Record events
    await engine.record_event("meeting", {"attendees": ["john"], "topic": "standup"})
    
    # Get detected patterns
    patterns = await engine.get_patterns()
    
    # Check if pattern is expected now
    expected = await engine.whats_expected_now()
    # Returns: [{"pattern": "Monday standup", "confidence": 0.9}]
    
    # Detect anomalies
    anomalies = await engine.detect_anomalies()
"""

import asyncio
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, time
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set
import statistics
import logging

logger = logging.getLogger(__name__)


class PatternType(Enum):
    """Types of patterns we detect."""
    TEMPORAL = "temporal"        # Time-based recurring patterns
    SEQUENCE = "sequence"        # Action sequences
    CORRELATION = "correlation"  # What triggers what
    FREQUENCY = "frequency"      # How often things happen


class TemporalGranularity(Enum):
    """Time granularity for patterns."""
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


@dataclass
class Event:
    """A recorded event in the user's activity stream."""
    id: str
    event_type: str  # e.g., "meeting", "email_sent", "task_completed"
    timestamp: datetime
    context: Dict[str, Any]
    
    # For sequence detection
    session_id: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "timestamp": self.timestamp.isoformat(),
            "context": self.context,
            "session_id": self.session_id,
        }
    
    @property
    def day_of_week(self) -> int:
        """Monday = 0, Sunday = 6"""
        return self.timestamp.weekday()
    
    @property
    def hour(self) -> int:
        return self.timestamp.hour
    
    @property
    def day_of_month(self) -> int:
        return self.timestamp.day
    
    @property
    def week_of_month(self) -> int:
        return (self.timestamp.day - 1) // 7 + 1


@dataclass
class DetectedPattern:
    """A pattern detected from user behavior."""
    id: str
    pattern_type: PatternType
    name: str
    description: str
    
    # Pattern specifics
    event_types: List[str]  # What events make up this pattern
    
    # Temporal info (for temporal patterns)
    granularity: Optional[TemporalGranularity] = None
    time_slot: Optional[Dict] = None  # e.g., {"day_of_week": 0, "hour": 10}
    
    # Sequence info (for sequence patterns)
    sequence: Optional[List[str]] = None
    
    # Statistics
    occurrence_count: int = 0
    confidence: float = 0.0
    last_occurred: Optional[datetime] = None
    
    # Predictions
    expected_next: Optional[datetime] = None
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "type": self.pattern_type.value,
            "name": self.name,
            "description": self.description,
            "event_types": self.event_types,
            "granularity": self.granularity.value if self.granularity else None,
            "time_slot": self.time_slot,
            "sequence": self.sequence,
            "occurrences": self.occurrence_count,
            "confidence": self.confidence,
            "last_occurred": self.last_occurred.isoformat() if self.last_occurred else None,
            "expected_next": self.expected_next.isoformat() if self.expected_next else None,
        }


class PatternEngine:
    """
    Main pattern recognition engine.
    
    Watches the event stream and detects recurring patterns.
    """
    
    # Minimum occurrences to consider something a pattern
    MIN_PATTERN_OCCURRENCES = 3
    
    # Minimum confidence to report a pattern
    MIN_CONFIDENCE = 0.6
    
    def __init__(self, storage_path: str = None):
        self._storage_path = Path(storage_path or "~/.apex/patterns").expanduser()
        self._storage_path.mkdir(parents=True, exist_ok=True)
        
        # Event history
        self._events: List[Event] = []
        
        # Detected patterns
        self._patterns: Dict[str, DetectedPattern] = {}
        
        # Indexes for fast lookup
        self._events_by_type: Dict[str, List[Event]] = defaultdict(list)
        self._events_by_day: Dict[int, List[Event]] = defaultdict(list)  # day_of_week
        self._events_by_hour: Dict[int, List[Event]] = defaultdict(list)
        
        # Sequence tracking
        self._current_session_id: str = None
        self._session_events: List[Event] = []
        
        self._load()
    
    def _load(self):
        """Load saved events and patterns."""
        events_file = self._storage_path / "events.json"
        patterns_file = self._storage_path / "patterns.json"
        
        if events_file.exists():
            try:
                with open(events_file) as f:
                    data = json.load(f)
                    for e in data:
                        event = Event(
                            id=e["id"],
                            event_type=e["event_type"],
                            timestamp=datetime.fromisoformat(e["timestamp"]),
                            context=e["context"],
                            session_id=e.get("session_id"),
                        )
                        self._events.append(event)
                        self._index_event(event)
                logger.info(f"Loaded {len(self._events)} events")
            except Exception as e:
                logger.error(f"Failed to load events: {e}")
        
        if patterns_file.exists():
            try:
                with open(patterns_file) as f:
                    data = json.load(f)
                    for p in data:
                        pattern = DetectedPattern(
                            id=p["id"],
                            pattern_type=PatternType(p["type"]),
                            name=p["name"],
                            description=p["description"],
                            event_types=p["event_types"],
                            granularity=TemporalGranularity(p["granularity"]) if p.get("granularity") else None,
                            time_slot=p.get("time_slot"),
                            sequence=p.get("sequence"),
                            occurrence_count=p["occurrences"],
                            confidence=p["confidence"],
                            last_occurred=datetime.fromisoformat(p["last_occurred"]) if p.get("last_occurred") else None,
                            expected_next=datetime.fromisoformat(p["expected_next"]) if p.get("expected_next") else None,
                        )
                        self._patterns[pattern.id] = pattern
                logger.info(f"Loaded {len(self._patterns)} patterns")
            except Exception as e:
                logger.error(f"Failed to load patterns: {e}")
    
    def _save(self):
        """Persist events and patterns."""
        events_file = self._storage_path / "events.json"
        patterns_file = self._storage_path / "patterns.json"
        
        # Save recent events (keep last 5000)
        with open(events_file, 'w') as f:
            json.dump([e.to_dict() for e in self._events[-5000:]], f, indent=2)
        
        # Save patterns
        with open(patterns_file, 'w') as f:
            json.dump([p.to_dict() for p in self._patterns.values()], f, indent=2)
    
    def _index_event(self, event: Event):
        """Index event for fast lookup."""
        self._events_by_type[event.event_type].append(event)
        self._events_by_day[event.day_of_week].append(event)
        self._events_by_hour[event.hour].append(event)
    
    def _generate_id(self) -> str:
        """Generate unique ID."""
        import hashlib
        return hashlib.sha256(datetime.now().isoformat().encode()).hexdigest()[:12]
    
    # =========================================================================
    # Core API
    # =========================================================================
    
    async def record_event(
        self,
        event_type: str,
        context: Dict[str, Any] = None,
        timestamp: datetime = None,
    ) -> Event:
        """
        Record an event in the user's activity stream.
        
        Call this whenever something happens that we should track:
        - Meeting starts/ends
        - Email sent/received
        - Task created/completed
        - Document opened/edited
        - Search performed
        
        Args:
            event_type: Type of event (e.g., "meeting_start")
            context: Additional details
            timestamp: When it happened (defaults to now)
        """
        event = Event(
            id=self._generate_id(),
            event_type=event_type,
            timestamp=timestamp or datetime.now(),
            context=context or {},
            session_id=self._current_session_id,
        )
        
        self._events.append(event)
        self._index_event(event)
        
        # Track for sequence detection
        if self._current_session_id:
            self._session_events.append(event)
        
        # Trigger pattern detection periodically
        if len(self._events) % 50 == 0:
            await self._detect_patterns()
        
        self._save()
        logger.debug(f"Recorded event: {event_type}")
        
        return event
    
    def start_session(self, session_id: str = None):
        """
        Start a new session for sequence detection.
        
        Call this when user starts a work session.
        """
        self._current_session_id = session_id or self._generate_id()
        self._session_events = []
        return self._current_session_id
    
    def end_session(self):
        """
        End current session.
        
        This triggers sequence analysis for the session.
        """
        if self._session_events:
            asyncio.create_task(self._analyze_session_sequence())
        
        self._current_session_id = None
        self._session_events = []
    
    async def get_patterns(
        self,
        pattern_type: PatternType = None,
        min_confidence: float = None,
    ) -> List[DetectedPattern]:
        """
        Get detected patterns.
        
        Args:
            pattern_type: Filter by type
            min_confidence: Minimum confidence threshold
        """
        min_conf = min_confidence or self.MIN_CONFIDENCE
        
        patterns = list(self._patterns.values())
        
        if pattern_type:
            patterns = [p for p in patterns if p.pattern_type == pattern_type]
        
        patterns = [p for p in patterns if p.confidence >= min_conf]
        
        return sorted(patterns, key=lambda p: p.confidence, reverse=True)
    
    async def whats_expected_now(
        self,
        window_minutes: int = 60,
    ) -> List[Dict]:
        """
        What patterns are expected around the current time?
        
        Returns patterns that typically occur at this:
        - Day of week
        - Hour of day
        - Time of month
        
        Args:
            window_minutes: Look window (default 60 min)
        """
        now = datetime.now()
        expected = []
        
        for pattern in self._patterns.values():
            if pattern.pattern_type != PatternType.TEMPORAL:
                continue
            
            if pattern.confidence < self.MIN_CONFIDENCE:
                continue
            
            match_score = self._check_pattern_match_now(pattern, now, window_minutes)
            
            if match_score > 0:
                expected.append({
                    "pattern": pattern.name,
                    "description": pattern.description,
                    "confidence": pattern.confidence,
                    "match_score": match_score,
                    "last_occurred": pattern.last_occurred,
                    "expected_next": pattern.expected_next,
                })
        
        return sorted(expected, key=lambda x: x["match_score"], reverse=True)
    
    def _check_pattern_match_now(
        self,
        pattern: DetectedPattern,
        now: datetime,
        window_minutes: int,
    ) -> float:
        """Check if a pattern matches the current time."""
        if not pattern.time_slot:
            return 0
        
        slot = pattern.time_slot
        score = 0
        
        # Check day of week
        if "day_of_week" in slot:
            if slot["day_of_week"] == now.weekday():
                score += 0.5
            else:
                return 0  # Wrong day, no match
        
        # Check hour
        if "hour" in slot:
            target_hour = slot["hour"]
            hour_diff = abs(now.hour - target_hour) + abs(now.minute) / 60
            
            if hour_diff * 60 <= window_minutes:
                score += 0.5 * (1 - hour_diff / (window_minutes / 60))
            else:
                score -= 0.3  # Outside window
        
        # Check day of month
        if "day_of_month" in slot:
            if slot["day_of_month"] == now.day:
                score += 0.3
        
        # Check week of month
        if "week_of_month" in slot:
            current_week = (now.day - 1) // 7 + 1
            if slot["week_of_month"] == current_week:
                score += 0.3
        
        return max(0, score)
    
    async def detect_anomalies(
        self,
        lookback_days: int = 14,
    ) -> List[Dict]:
        """
        Detect anomalies in recent behavior.
        
        Anomalies:
        - Missing expected patterns
        - Unusual timing
        - Frequency changes
        """
        anomalies = []
        now = datetime.now()
        
        # Check for missing expected patterns
        for pattern in self._patterns.values():
            if pattern.pattern_type != PatternType.TEMPORAL:
                continue
            
            if pattern.confidence < self.MIN_CONFIDENCE:
                continue
            
            if pattern.expected_next and pattern.expected_next < now - timedelta(hours=2):
                anomalies.append({
                    "type": "missing_pattern",
                    "pattern": pattern.name,
                    "expected": pattern.expected_next,
                    "description": f"Expected '{pattern.name}' but it didn't happen",
                })
        
        # Check for unusual activity times
        recent_events = [e for e in self._events if e.timestamp > now - timedelta(days=lookback_days)]
        
        # Activity outside normal hours
        for event in recent_events[-20:]:  # Check last 20 events
            if event.hour < 6 or event.hour > 22:
                # Check if this is unusual
                late_night_count = sum(
                    1 for e in self._events_by_type[event.event_type]
                    if e.hour < 6 or e.hour > 22
                )
                total_count = len(self._events_by_type[event.event_type])
                
                if total_count > 10 and late_night_count / total_count < 0.1:
                    anomalies.append({
                        "type": "unusual_timing",
                        "event": event.event_type,
                        "time": event.timestamp,
                        "description": f"Unusual timing for {event.event_type}",
                    })
        
        # Frequency anomalies
        for event_type, events in self._events_by_type.items():
            if len(events) < 20:
                continue
            
            # Calculate typical daily frequency
            daily_counts = defaultdict(int)
            for e in events[-100:]:
                date_key = e.timestamp.date()
                daily_counts[date_key] += 1
            
            if len(daily_counts) < 5:
                continue
            
            avg_daily = statistics.mean(daily_counts.values())
            stdev_daily = statistics.stdev(daily_counts.values()) if len(daily_counts) > 1 else 0
            
            # Check today's count
            today = now.date()
            if today in daily_counts:
                today_count = daily_counts[today]
                if stdev_daily > 0 and abs(today_count - avg_daily) > 2 * stdev_daily:
                    anomalies.append({
                        "type": "frequency_change",
                        "event": event_type,
                        "current": today_count,
                        "typical": avg_daily,
                        "description": f"{'More' if today_count > avg_daily else 'Fewer'} {event_type} events than usual",
                    })
        
        return anomalies
    
    # =========================================================================
    # Pattern Detection Algorithms
    # =========================================================================
    
    async def _detect_patterns(self):
        """Run all pattern detection algorithms."""
        await self._detect_weekly_patterns()
        await self._detect_daily_patterns()
        await self._detect_monthly_patterns()
        await self._detect_sequence_patterns()
        
        # Update expected_next for temporal patterns
        self._update_pattern_predictions()
        
        self._save()
    
    async def _detect_weekly_patterns(self):
        """Detect patterns that repeat weekly."""
        # Group events by (event_type, day_of_week, hour)
        weekly_buckets = defaultdict(list)
        
        for event in self._events[-500:]:  # Last 500 events
            key = (event.event_type, event.day_of_week, event.hour)
            weekly_buckets[key].append(event)
        
        # Find patterns with enough occurrences
        for (event_type, dow, hour), events in weekly_buckets.items():
            if len(events) < self.MIN_PATTERN_OCCURRENCES:
                continue
            
            # Calculate confidence based on consistency
            # Get all weeks in our data
            weeks = set()
            for e in self._events:
                week_key = e.timestamp.isocalendar()[:2]
                weeks.add(week_key)
            
            total_weeks = len(weeks)
            weeks_with_event = set()
            for e in events:
                week_key = e.timestamp.isocalendar()[:2]
                weeks_with_event.add(week_key)
            
            if total_weeks < 3:
                continue
            
            # Confidence = how often this happens when it "should"
            confidence = len(weeks_with_event) / total_weeks
            
            if confidence >= self.MIN_CONFIDENCE:
                day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", 
                           "Friday", "Saturday", "Sunday"]
                pattern_id = f"weekly_{event_type}_{dow}_{hour}"
                
                self._patterns[pattern_id] = DetectedPattern(
                    id=pattern_id,
                    pattern_type=PatternType.TEMPORAL,
                    name=f"{day_names[dow]} {event_type}",
                    description=f"{event_type} every {day_names[dow]} around {hour}:00",
                    event_types=[event_type],
                    granularity=TemporalGranularity.WEEKLY,
                    time_slot={"day_of_week": dow, "hour": hour},
                    occurrence_count=len(events),
                    confidence=confidence,
                    last_occurred=max(e.timestamp for e in events),
                )
    
    async def _detect_daily_patterns(self):
        """Detect patterns that repeat daily."""
        # Group events by (event_type, hour)
        daily_buckets = defaultdict(list)
        
        for event in self._events[-500:]:
            key = (event.event_type, event.hour)
            daily_buckets[key].append(event)
        
        for (event_type, hour), events in daily_buckets.items():
            if len(events) < self.MIN_PATTERN_OCCURRENCES:
                continue
            
            # Get unique days
            days = set()
            for e in self._events:
                days.add(e.timestamp.date())
            
            days_with_event = set()
            for e in events:
                days_with_event.add(e.timestamp.date())
            
            if len(days) < 5:
                continue
            
            confidence = len(days_with_event) / len(days)
            
            # Only consider daily patterns if they happen most days
            if confidence >= 0.5:
                pattern_id = f"daily_{event_type}_{hour}"
                
                self._patterns[pattern_id] = DetectedPattern(
                    id=pattern_id,
                    pattern_type=PatternType.TEMPORAL,
                    name=f"Daily {event_type}",
                    description=f"{event_type} every day around {hour}:00",
                    event_types=[event_type],
                    granularity=TemporalGranularity.DAILY,
                    time_slot={"hour": hour},
                    occurrence_count=len(events),
                    confidence=confidence,
                    last_occurred=max(e.timestamp for e in events),
                )
    
    async def _detect_monthly_patterns(self):
        """Detect patterns that repeat monthly."""
        # Group events by (event_type, day_of_month or week_of_month)
        monthly_buckets = defaultdict(list)
        
        for event in self._events[-1000:]:
            # Check both specific day and week-of-month
            day_key = (event.event_type, "day", event.day_of_month)
            week_key = (event.event_type, "week", event.week_of_month)
            
            monthly_buckets[day_key].append(event)
            monthly_buckets[week_key].append(event)
        
        for key, events in monthly_buckets.items():
            if len(events) < self.MIN_PATTERN_OCCURRENCES:
                continue
            
            event_type, slot_type, slot_value = key
            
            # Get unique months
            months = set()
            for e in self._events:
                months.add((e.timestamp.year, e.timestamp.month))
            
            months_with_event = set()
            for e in events:
                months_with_event.add((e.timestamp.year, e.timestamp.month))
            
            if len(months) < 3:
                continue
            
            confidence = len(months_with_event) / len(months)
            
            if confidence >= self.MIN_CONFIDENCE:
                pattern_id = f"monthly_{event_type}_{slot_type}_{slot_value}"
                
                time_slot = {}
                if slot_type == "day":
                    time_slot["day_of_month"] = slot_value
                    description = f"{event_type} on day {slot_value} of each month"
                else:
                    time_slot["week_of_month"] = slot_value
                    week_ord = ["first", "second", "third", "fourth", "fifth"]
                    description = f"{event_type} in the {week_ord[slot_value-1]} week of each month"
                
                self._patterns[pattern_id] = DetectedPattern(
                    id=pattern_id,
                    pattern_type=PatternType.TEMPORAL,
                    name=f"Monthly {event_type}",
                    description=description,
                    event_types=[event_type],
                    granularity=TemporalGranularity.MONTHLY,
                    time_slot=time_slot,
                    occurrence_count=len(events),
                    confidence=confidence,
                    last_occurred=max(e.timestamp for e in events),
                )
    
    async def _detect_sequence_patterns(self):
        """Detect action sequences that commonly occur together."""
        # Look at events close in time
        sequences = defaultdict(int)
        
        sorted_events = sorted(self._events[-500:], key=lambda e: e.timestamp)
        
        for i in range(len(sorted_events) - 1):
            e1 = sorted_events[i]
            e2 = sorted_events[i + 1]
            
            # If events are close together (within 30 min), consider them a sequence
            time_diff = (e2.timestamp - e1.timestamp).total_seconds()
            if time_diff < 1800:  # 30 minutes
                seq = (e1.event_type, e2.event_type)
                sequences[seq] += 1
        
        # Find significant sequences
        for seq, count in sequences.items():
            if count < self.MIN_PATTERN_OCCURRENCES:
                continue
            
            # Calculate confidence
            first_event_total = len(self._events_by_type[seq[0]])
            if first_event_total < 5:
                continue
            
            confidence = count / first_event_total
            
            if confidence >= self.MIN_CONFIDENCE:
                pattern_id = f"sequence_{seq[0]}_{seq[1]}"
                
                self._patterns[pattern_id] = DetectedPattern(
                    id=pattern_id,
                    pattern_type=PatternType.SEQUENCE,
                    name=f"{seq[0]} → {seq[1]}",
                    description=f"{seq[0]} is often followed by {seq[1]}",
                    event_types=list(seq),
                    sequence=list(seq),
                    occurrence_count=count,
                    confidence=confidence,
                )
    
    async def _analyze_session_sequence(self):
        """Analyze events in the current session for sequences."""
        if len(self._session_events) < 2:
            return
        
        # Create a sequence signature
        sequence = [e.event_type for e in self._session_events]
        
        # We could store and analyze full session sequences here
        # For now, the pairwise detection handles it
    
    def _update_pattern_predictions(self):
        """Update expected_next for all temporal patterns."""
        now = datetime.now()
        
        for pattern in self._patterns.values():
            if pattern.pattern_type != PatternType.TEMPORAL:
                continue
            
            if not pattern.time_slot:
                continue
            
            slot = pattern.time_slot
            
            if pattern.granularity == TemporalGranularity.DAILY:
                # Next occurrence is today or tomorrow
                hour = slot.get("hour", 9)
                next_time = now.replace(hour=hour, minute=0, second=0, microsecond=0)
                if next_time <= now:
                    next_time += timedelta(days=1)
                pattern.expected_next = next_time
            
            elif pattern.granularity == TemporalGranularity.WEEKLY:
                dow = slot.get("day_of_week", 0)
                hour = slot.get("hour", 9)
                
                days_ahead = dow - now.weekday()
                if days_ahead < 0:
                    days_ahead += 7
                
                next_time = now.replace(hour=hour, minute=0, second=0, microsecond=0)
                next_time += timedelta(days=days_ahead)
                
                if next_time <= now:
                    next_time += timedelta(weeks=1)
                
                pattern.expected_next = next_time
            
            elif pattern.granularity == TemporalGranularity.MONTHLY:
                if "day_of_month" in slot:
                    day = slot["day_of_month"]
                    try:
                        next_time = now.replace(day=day, hour=9, minute=0, second=0, microsecond=0)
                        if next_time <= now:
                            # Next month
                            if now.month == 12:
                                next_time = next_time.replace(year=now.year + 1, month=1)
                            else:
                                next_time = next_time.replace(month=now.month + 1)
                        pattern.expected_next = next_time
                    except ValueError:
                        pass  # Invalid day for month
    
    # =========================================================================
    # Statistics
    # =========================================================================
    
    def get_stats(self) -> Dict:
        """Get pattern recognition statistics."""
        return {
            "total_events": len(self._events),
            "event_types": len(self._events_by_type),
            "detected_patterns": len(self._patterns),
            "patterns_by_type": {
                pt.value: len([p for p in self._patterns.values() if p.pattern_type == pt])
                for pt in PatternType
            },
            "high_confidence_patterns": [
                {
                    "name": p.name,
                    "confidence": f"{p.confidence:.0%}",
                    "occurrences": p.occurrence_count,
                }
                for p in sorted(
                    self._patterns.values(),
                    key=lambda x: x.confidence,
                    reverse=True
                )[:10]
            ],
        }


# Singleton
_engine: Optional[PatternEngine] = None

def get_pattern_engine() -> PatternEngine:
    """Get or create the pattern engine singleton."""
    global _engine
    if _engine is None:
        _engine = PatternEngine()
    return _engine
