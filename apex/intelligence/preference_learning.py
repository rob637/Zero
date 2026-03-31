"""
Preference Learning Engine

This is how Apex learns YOU without you telling it.

Instead of asking "what time do you prefer meetings?", it observes:
- You scheduled 23 meetings last month
- 18 of them were between 9-11am
- You moved 3 afternoon meetings to morning slots
- Average meeting length: 42 minutes

Then when you say "schedule a meeting", it suggests 10am for 45 minutes.

The magic: It learns from BEHAVIOR, not just explicit statements.

Tracks preferences for:
- Time preferences (meeting times, email times, work hours)
- Communication preferences (email length, tone, response time)
- Contact preferences (who you contact most, preferred channels)
- Content preferences (document formats, naming conventions)
- Workflow preferences (task ordering, tool usage)

Usage:
    from intelligence.preference_learning import PreferenceLearner
    
    learner = PreferenceLearner()
    
    # Record an observation
    await learner.observe(
        action="schedule_meeting",
        context={"time": "10:00", "duration": 45, "attendee": "john"},
    )
    
    # Get learned preferences
    prefs = await learner.get_preferences("meeting_time")
    # Returns: {"preferred_hour": 10, "confidence": 0.78, "reason": "70% of meetings scheduled 9-11am"}
    
    # Get suggestion for new action
    suggestion = await learner.suggest("schedule_meeting", {"attendee": "sarah"})
    # Returns: {"time": "10:00", "duration": 45, "reason": "Based on your typical meeting patterns"}
"""

import asyncio
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, time
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import statistics

import logging
logger = logging.getLogger(__name__)


class PreferenceType(Enum):
    """Types of preferences we track."""
    TIME = "time"                    # Time-of-day preferences
    DURATION = "duration"            # How long things take
    FREQUENCY = "frequency"          # How often things happen
    COMMUNICATION = "communication"  # Email/message style
    CONTACT = "contact"              # Who you interact with
    CONTENT = "content"              # Document/content preferences
    WORKFLOW = "workflow"            # How you work
    LOCATION = "location"            # Where things happen


@dataclass
class Observation:
    """A single observed user action."""
    id: str
    action: str  # e.g., "schedule_meeting", "send_email", "create_document"
    timestamp: datetime
    context: Dict[str, Any]
    
    # Outcome tracking (did they modify our suggestion?)
    was_modified: bool = False
    modification_details: Optional[Dict] = None
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "action": self.action,
            "timestamp": self.timestamp.isoformat(),
            "context": self.context,
            "was_modified": self.was_modified,
            "modification_details": self.modification_details,
        }


@dataclass
class LearnedPreference:
    """A preference learned from observations."""
    preference_type: PreferenceType
    key: str  # e.g., "meeting_start_hour", "email_length"
    
    # The learned value(s)
    value: Any  # Could be number, string, distribution
    distribution: Optional[Dict[str, float]] = None  # For categorical
    
    # Confidence and evidence
    confidence: float = 0.0  # 0-1
    observation_count: int = 0
    last_updated: datetime = field(default_factory=datetime.now)
    
    # Explanation
    reason: str = ""
    
    def to_dict(self) -> Dict:
        return {
            "type": self.preference_type.value,
            "key": self.key,
            "value": self.value,
            "distribution": self.distribution,
            "confidence": self.confidence,
            "observations": self.observation_count,
            "reason": self.reason,
        }


class PreferenceLearner:
    """
    Learns user preferences from observed behavior.
    
    This is unsupervised learning - we don't ask the user,
    we watch and learn patterns.
    """
    
    # Minimum observations needed for confident preference
    MIN_OBSERVATIONS = 5
    
    def __init__(self, storage_path: str = None):
        self._storage_path = Path(storage_path or "~/.apex/preferences").expanduser()
        self._storage_path.mkdir(parents=True, exist_ok=True)
        
        # Observations grouped by action type
        self._observations: Dict[str, List[Observation]] = defaultdict(list)
        
        # Learned preferences
        self._preferences: Dict[str, LearnedPreference] = {}
        
        # Action-specific analyzers
        self._analyzers = {
            "schedule_meeting": self._analyze_meeting_preferences,
            "send_email": self._analyze_email_preferences,
            "create_document": self._analyze_document_preferences,
            "add_task": self._analyze_task_preferences,
            "search": self._analyze_search_preferences,
        }
        
        self._load()
    
    def _load(self):
        """Load saved observations and preferences."""
        obs_file = self._storage_path / "observations.json"
        pref_file = self._storage_path / "preferences.json"
        
        if obs_file.exists():
            try:
                with open(obs_file) as f:
                    data = json.load(f)
                    for action, obs_list in data.items():
                        for obs_data in obs_list:
                            obs = Observation(
                                id=obs_data["id"],
                                action=obs_data["action"],
                                timestamp=datetime.fromisoformat(obs_data["timestamp"]),
                                context=obs_data["context"],
                                was_modified=obs_data.get("was_modified", False),
                                modification_details=obs_data.get("modification_details"),
                            )
                            self._observations[action].append(obs)
                logger.info(f"Loaded {sum(len(v) for v in self._observations.values())} observations")
            except Exception as e:
                logger.error(f"Failed to load observations: {e}")
        
        if pref_file.exists():
            try:
                with open(pref_file) as f:
                    data = json.load(f)
                    for key, pref_data in data.items():
                        self._preferences[key] = LearnedPreference(
                            preference_type=PreferenceType(pref_data["type"]),
                            key=pref_data["key"],
                            value=pref_data["value"],
                            distribution=pref_data.get("distribution"),
                            confidence=pref_data["confidence"],
                            observation_count=pref_data["observations"],
                            reason=pref_data.get("reason", ""),
                        )
                logger.info(f"Loaded {len(self._preferences)} learned preferences")
            except Exception as e:
                logger.error(f"Failed to load preferences: {e}")
    
    def _save(self):
        """Persist observations and preferences."""
        obs_file = self._storage_path / "observations.json"
        pref_file = self._storage_path / "preferences.json"
        
        # Save observations (keep last 1000 per action type)
        obs_data = {}
        for action, obs_list in self._observations.items():
            obs_data[action] = [o.to_dict() for o in obs_list[-1000:]]
        with open(obs_file, 'w') as f:
            json.dump(obs_data, f, indent=2)
        
        # Save preferences
        pref_data = {k: v.to_dict() for k, v in self._preferences.items()}
        with open(pref_file, 'w') as f:
            json.dump(pref_data, f, indent=2)
    
    def _generate_id(self) -> str:
        """Generate observation ID."""
        import hashlib
        return hashlib.sha256(datetime.now().isoformat().encode()).hexdigest()[:12]
    
    # =========================================================================
    # Core API
    # =========================================================================
    
    async def observe(
        self,
        action: str,
        context: Dict[str, Any],
        was_modified: bool = False,
        modification_details: Dict = None,
    ) -> Observation:
        """
        Record an observed user action.
        
        Call this whenever the user does something we can learn from:
        - Schedules a meeting
        - Sends an email
        - Creates a document
        - Completes a task
        - Modifies our suggestion
        
        Args:
            action: Type of action (e.g., "schedule_meeting")
            context: Details about the action
            was_modified: Did they modify our suggestion?
            modification_details: What they changed
        
        Example:
            await learner.observe("schedule_meeting", {
                "time": "10:00",
                "duration": 45,
                "day_of_week": "tuesday",
                "attendees": ["john@example.com"],
                "has_agenda": True,
            })
        """
        obs = Observation(
            id=self._generate_id(),
            action=action,
            timestamp=datetime.now(),
            context=context,
            was_modified=was_modified,
            modification_details=modification_details,
        )
        
        self._observations[action].append(obs)
        
        # Trigger learning if we have enough observations
        if len(self._observations[action]) >= self.MIN_OBSERVATIONS:
            await self._learn_from_observations(action)
        
        self._save()
        logger.debug(f"Observed: {action} with context {list(context.keys())}")
        
        return obs
    
    async def _learn_from_observations(self, action: str):
        """Analyze observations and update learned preferences."""
        if action in self._analyzers:
            await self._analyzers[action]()
        else:
            # Generic learning for unknown action types
            await self._analyze_generic(action)
    
    async def get_preferences(
        self,
        preference_key: str = None,
        preference_type: PreferenceType = None,
    ) -> Dict[str, LearnedPreference]:
        """
        Get learned preferences.
        
        Args:
            preference_key: Specific preference (e.g., "meeting_start_hour")
            preference_type: Filter by type (e.g., TIME)
        
        Returns:
            Dict of preference_key -> LearnedPreference
        """
        if preference_key:
            if preference_key in self._preferences:
                return {preference_key: self._preferences[preference_key]}
            return {}
        
        if preference_type:
            return {
                k: v for k, v in self._preferences.items()
                if v.preference_type == preference_type
            }
        
        return self._preferences.copy()
    
    async def suggest(
        self,
        action: str,
        context: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        Get suggestions based on learned preferences.
        
        Args:
            action: Type of action (e.g., "schedule_meeting")
            context: Partial context (e.g., {"attendee": "john"})
        
        Returns:
            Suggested values with confidence and explanations
        """
        context = context or {}
        suggestions = {}
        
        if action == "schedule_meeting":
            suggestions = await self._suggest_meeting(context)
        elif action == "send_email":
            suggestions = await self._suggest_email(context)
        elif action == "add_task":
            suggestions = await self._suggest_task(context)
        else:
            # Generic suggestions
            suggestions = await self._suggest_generic(action, context)
        
        return suggestions
    
    # =========================================================================
    # Action-Specific Analyzers
    # =========================================================================
    
    async def _analyze_meeting_preferences(self):
        """Learn meeting scheduling preferences."""
        observations = self._observations.get("schedule_meeting", [])
        if len(observations) < self.MIN_OBSERVATIONS:
            return
        
        # Analyze meeting times
        hours = []
        durations = []
        days = defaultdict(int)
        
        for obs in observations[-100:]:  # Last 100 meetings
            ctx = obs.context
            
            if "time" in ctx:
                try:
                    hour = int(ctx["time"].split(":")[0])
                    hours.append(hour)
                except:
                    pass
            
            if "duration" in ctx:
                durations.append(ctx["duration"])
            
            if "day_of_week" in ctx:
                days[ctx["day_of_week"]] += 1
        
        # Learn preferred meeting hour
        if hours:
            avg_hour = statistics.mean(hours)
            mode_hour = max(set(hours), key=hours.count)
            
            self._preferences["meeting_start_hour"] = LearnedPreference(
                preference_type=PreferenceType.TIME,
                key="meeting_start_hour",
                value=mode_hour,
                confidence=self._calculate_confidence(hours),
                observation_count=len(hours),
                reason=f"Most common meeting time: {mode_hour}:00 ({hours.count(mode_hour)}/{len(hours)} meetings)",
            )
            
            # Morning vs afternoon preference
            morning = len([h for h in hours if h < 12])
            afternoon = len([h for h in hours if h >= 12])
            
            self._preferences["meeting_time_preference"] = LearnedPreference(
                preference_type=PreferenceType.TIME,
                key="meeting_time_preference",
                value="morning" if morning > afternoon else "afternoon",
                confidence=(max(morning, afternoon) / len(hours)) if hours else 0,
                observation_count=len(hours),
                reason=f"Morning: {morning}, Afternoon: {afternoon}",
            )
        
        # Learn preferred duration
        if durations:
            avg_duration = statistics.mean(durations)
            # Round to nearest 15 minutes
            rounded = round(avg_duration / 15) * 15
            
            self._preferences["meeting_duration"] = LearnedPreference(
                preference_type=PreferenceType.DURATION,
                key="meeting_duration",
                value=rounded,
                confidence=self._calculate_confidence(durations),
                observation_count=len(durations),
                reason=f"Average duration: {avg_duration:.0f} min (rounded to {rounded})",
            )
        
        # Learn preferred days
        if days:
            total = sum(days.values())
            distribution = {k: v/total for k, v in days.items()}
            preferred_day = max(days, key=days.get)
            
            self._preferences["meeting_preferred_day"] = LearnedPreference(
                preference_type=PreferenceType.TIME,
                key="meeting_preferred_day",
                value=preferred_day,
                distribution=distribution,
                confidence=days[preferred_day] / total,
                observation_count=total,
                reason=f"Day distribution: {dict(days)}",
            )
        
        self._save()
        logger.info("Updated meeting preferences")
    
    async def _analyze_email_preferences(self):
        """Learn email composition preferences."""
        observations = self._observations.get("send_email", [])
        if len(observations) < self.MIN_OBSERVATIONS:
            return
        
        subject_lengths = []
        body_lengths = []
        send_hours = []
        uses_greeting = []
        uses_signature = []
        
        for obs in observations[-100:]:
            ctx = obs.context
            
            if "subject_length" in ctx:
                subject_lengths.append(ctx["subject_length"])
            if "body_length" in ctx:
                body_lengths.append(ctx["body_length"])
            if "send_hour" in ctx:
                send_hours.append(ctx["send_hour"])
            if "has_greeting" in ctx:
                uses_greeting.append(ctx["has_greeting"])
            if "has_signature" in ctx:
                uses_signature.append(ctx["has_signature"])
        
        # Email length preference
        if body_lengths:
            avg_length = statistics.mean(body_lengths)
            
            # Categorize
            if avg_length < 100:
                style = "brief"
            elif avg_length < 300:
                style = "moderate"
            else:
                style = "detailed"
            
            self._preferences["email_length_style"] = LearnedPreference(
                preference_type=PreferenceType.COMMUNICATION,
                key="email_length_style",
                value=style,
                confidence=self._calculate_confidence(body_lengths),
                observation_count=len(body_lengths),
                reason=f"Average email length: {avg_length:.0f} chars",
            )
        
        # Greeting preference
        if uses_greeting:
            greeting_rate = sum(uses_greeting) / len(uses_greeting)
            
            self._preferences["email_uses_greeting"] = LearnedPreference(
                preference_type=PreferenceType.COMMUNICATION,
                key="email_uses_greeting",
                value=greeting_rate > 0.5,
                confidence=abs(greeting_rate - 0.5) * 2,  # Higher confidence when clear preference
                observation_count=len(uses_greeting),
                reason=f"Uses greeting {greeting_rate*100:.0f}% of the time",
            )
        
        # Send time preference
        if send_hours:
            peak_hour = max(set(send_hours), key=send_hours.count)
            
            self._preferences["email_send_hour"] = LearnedPreference(
                preference_type=PreferenceType.TIME,
                key="email_send_hour",
                value=peak_hour,
                confidence=self._calculate_confidence(send_hours),
                observation_count=len(send_hours),
                reason=f"Most emails sent around {peak_hour}:00",
            )
        
        self._save()
        logger.info("Updated email preferences")
    
    async def _analyze_document_preferences(self):
        """Learn document creation preferences."""
        observations = self._observations.get("create_document", [])
        if len(observations) < self.MIN_OBSERVATIONS:
            return
        
        formats = defaultdict(int)
        naming_patterns = []
        
        for obs in observations[-100:]:
            ctx = obs.context
            
            if "format" in ctx:
                formats[ctx["format"]] += 1
            if "filename" in ctx:
                naming_patterns.append(ctx["filename"])
        
        # Preferred format
        if formats:
            total = sum(formats.values())
            preferred = max(formats, key=formats.get)
            
            self._preferences["document_format"] = LearnedPreference(
                preference_type=PreferenceType.CONTENT,
                key="document_format",
                value=preferred,
                distribution={k: v/total for k, v in formats.items()},
                confidence=formats[preferred] / total,
                observation_count=total,
                reason=f"Format usage: {dict(formats)}",
            )
        
        self._save()
        logger.info("Updated document preferences")
    
    async def _analyze_task_preferences(self):
        """Learn task management preferences."""
        observations = self._observations.get("add_task", [])
        if len(observations) < self.MIN_OBSERVATIONS:
            return
        
        due_offsets = []  # Days until due date
        priorities = defaultdict(int)
        
        for obs in observations[-100:]:
            ctx = obs.context
            
            if "due_offset_days" in ctx:
                due_offsets.append(ctx["due_offset_days"])
            if "priority" in ctx:
                priorities[ctx["priority"]] += 1
        
        # Typical due date offset
        if due_offsets:
            avg_offset = statistics.mean(due_offsets)
            
            self._preferences["task_due_offset"] = LearnedPreference(
                preference_type=PreferenceType.DURATION,
                key="task_due_offset",
                value=round(avg_offset),
                confidence=self._calculate_confidence(due_offsets),
                observation_count=len(due_offsets),
                reason=f"Average time to due date: {avg_offset:.1f} days",
            )
        
        # Priority preference
        if priorities:
            total = sum(priorities.values())
            default_priority = max(priorities, key=priorities.get)
            
            self._preferences["task_default_priority"] = LearnedPreference(
                preference_type=PreferenceType.WORKFLOW,
                key="task_default_priority",
                value=default_priority,
                distribution={k: v/total for k, v in priorities.items()},
                confidence=priorities[default_priority] / total,
                observation_count=total,
                reason=f"Priority distribution: {dict(priorities)}",
            )
        
        self._save()
        logger.info("Updated task preferences")
    
    async def _analyze_search_preferences(self):
        """Learn search and lookup preferences."""
        observations = self._observations.get("search", [])
        if len(observations) < self.MIN_OBSERVATIONS:
            return
        
        # Track what gets searched for most
        search_types = defaultdict(int)
        
        for obs in observations[-100:]:
            ctx = obs.context
            if "search_type" in ctx:
                search_types[ctx["search_type"]] += 1
        
        # Most common search type
        if search_types:
            total = sum(search_types.values())
            common = max(search_types, key=search_types.get)
            
            self._preferences["common_search_type"] = LearnedPreference(
                preference_type=PreferenceType.WORKFLOW,
                key="common_search_type",
                value=common,
                distribution={k: v/total for k, v in search_types.items()},
                confidence=search_types[common] / total,
                observation_count=total,
                reason=f"Search distribution: {dict(search_types)}",
            )
        
        self._save()
    
    async def _analyze_generic(self, action: str):
        """Generic analysis for unknown action types."""
        observations = self._observations.get(action, [])
        if len(observations) < self.MIN_OBSERVATIONS:
            return
        
        # Analyze any numeric fields
        numeric_fields = defaultdict(list)
        categorical_fields = defaultdict(lambda: defaultdict(int))
        
        for obs in observations[-100:]:
            for key, value in obs.context.items():
                if isinstance(value, (int, float)):
                    numeric_fields[key].append(value)
                elif isinstance(value, str):
                    categorical_fields[key][value] += 1
        
        # Learn from numeric fields
        for field, values in numeric_fields.items():
            if len(values) >= self.MIN_OBSERVATIONS:
                avg = statistics.mean(values)
                self._preferences[f"{action}_{field}"] = LearnedPreference(
                    preference_type=PreferenceType.WORKFLOW,
                    key=f"{action}_{field}",
                    value=avg,
                    confidence=self._calculate_confidence(values),
                    observation_count=len(values),
                    reason=f"Average {field}: {avg:.2f}",
                )
        
        # Learn from categorical fields
        for field, counts in categorical_fields.items():
            total = sum(counts.values())
            if total >= self.MIN_OBSERVATIONS:
                common = max(counts, key=counts.get)
                self._preferences[f"{action}_{field}"] = LearnedPreference(
                    preference_type=PreferenceType.WORKFLOW,
                    key=f"{action}_{field}",
                    value=common,
                    distribution={k: v/total for k, v in counts.items()},
                    confidence=counts[common] / total,
                    observation_count=total,
                    reason=f"Most common {field}: {common}",
                )
        
        self._save()
    
    # =========================================================================
    # Suggestion Generation
    # =========================================================================
    
    async def _suggest_meeting(self, context: Dict) -> Dict:
        """Generate meeting suggestions based on preferences."""
        suggestions = {"confidence": 0.0, "reasons": []}
        
        # Suggest time
        if "meeting_start_hour" in self._preferences:
            pref = self._preferences["meeting_start_hour"]
            suggestions["suggested_hour"] = pref.value
            suggestions["confidence"] = max(suggestions["confidence"], pref.confidence)
            suggestions["reasons"].append(pref.reason)
        
        # Suggest duration
        if "meeting_duration" in self._preferences:
            pref = self._preferences["meeting_duration"]
            suggestions["suggested_duration"] = pref.value
            suggestions["confidence"] = max(suggestions["confidence"], pref.confidence)
            suggestions["reasons"].append(pref.reason)
        
        # Suggest day if no date specified
        if "date" not in context and "meeting_preferred_day" in self._preferences:
            pref = self._preferences["meeting_preferred_day"]
            suggestions["suggested_day"] = pref.value
            suggestions["reasons"].append(pref.reason)
        
        return suggestions
    
    async def _suggest_email(self, context: Dict) -> Dict:
        """Generate email suggestions based on preferences."""
        suggestions = {"confidence": 0.0, "reasons": []}
        
        if "email_uses_greeting" in self._preferences:
            pref = self._preferences["email_uses_greeting"]
            suggestions["include_greeting"] = pref.value
            suggestions["reasons"].append(pref.reason)
        
        if "email_length_style" in self._preferences:
            pref = self._preferences["email_length_style"]
            suggestions["suggested_style"] = pref.value
            suggestions["confidence"] = max(suggestions["confidence"], pref.confidence)
        
        return suggestions
    
    async def _suggest_task(self, context: Dict) -> Dict:
        """Generate task suggestions based on preferences."""
        suggestions = {"confidence": 0.0, "reasons": []}
        
        if "task_due_offset" in self._preferences:
            pref = self._preferences["task_due_offset"]
            suggestions["suggested_due_days"] = pref.value
            suggestions["confidence"] = max(suggestions["confidence"], pref.confidence)
            suggestions["reasons"].append(pref.reason)
        
        if "task_default_priority" in self._preferences:
            pref = self._preferences["task_default_priority"]
            suggestions["suggested_priority"] = pref.value
        
        return suggestions
    
    async def _suggest_generic(self, action: str, context: Dict) -> Dict:
        """Generate generic suggestions for unknown actions."""
        suggestions = {"confidence": 0.0, "reasons": []}
        
        prefix = f"{action}_"
        for key, pref in self._preferences.items():
            if key.startswith(prefix):
                field = key[len(prefix):]
                suggestions[f"suggested_{field}"] = pref.value
                suggestions["confidence"] = max(suggestions["confidence"], pref.confidence)
                suggestions["reasons"].append(pref.reason)
        
        return suggestions
    
    # =========================================================================
    # Utilities
    # =========================================================================
    
    def _calculate_confidence(self, values: List) -> float:
        """
        Calculate confidence based on consistency of values.
        
        Low variance + more samples = higher confidence.
        """
        if len(values) < 2:
            return 0.3
        
        try:
            stdev = statistics.stdev(values)
            mean = statistics.mean(values)
            
            # Coefficient of variation (lower = more consistent)
            cv = stdev / mean if mean != 0 else 1
            
            # Convert to confidence (0-1)
            consistency = max(0, 1 - cv)
            
            # Boost for more samples
            sample_boost = min(1, len(values) / 20)
            
            return min(1.0, consistency * 0.7 + sample_boost * 0.3)
        except:
            return 0.5
    
    def get_stats(self) -> Dict:
        """Get learning statistics."""
        return {
            "total_observations": sum(len(v) for v in self._observations.values()),
            "observations_by_action": {k: len(v) for k, v in self._observations.items()},
            "learned_preferences": len(self._preferences),
            "high_confidence_preferences": len([
                p for p in self._preferences.values()
                if p.confidence > 0.7
            ]),
            "preferences": [
                {
                    "key": p.key,
                    "value": p.value,
                    "confidence": f"{p.confidence:.0%}",
                    "observations": p.observation_count,
                }
                for p in sorted(
                    self._preferences.values(),
                    key=lambda x: x.confidence,
                    reverse=True
                )
            ],
        }


# Singleton
_learner: Optional[PreferenceLearner] = None

def get_preference_learner() -> PreferenceLearner:
    """Get or create the preference learner singleton."""
    global _learner
    if _learner is None:
        _learner = PreferenceLearner()
    return _learner
