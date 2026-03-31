"""
Perception Stream - How the brain takes in the world.

The brain doesn't see raw data. It sees percepts - 
meaningful interpretations of sensory input.

This module:
- Receives raw events from services
- Extracts meaningful features
- Creates percepts that can be processed
- Handles continuous background perception
"""

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
import re

logger = logging.getLogger(__name__)


class PerceptType(Enum):
    """Types of percepts the brain can recognize."""
    
    # Communication
    MESSAGE_RECEIVED = "message_received"
    MESSAGE_SENT = "message_sent"
    CONVERSATION = "conversation"
    
    # Scheduling  
    MEETING_SCHEDULED = "meeting_scheduled"
    DEADLINE_APPROACHING = "deadline_approaching"
    TIME_BLOCK_AVAILABLE = "time_block_available"
    
    # Information
    DOCUMENT_CREATED = "document_created"
    DOCUMENT_MODIFIED = "document_modified"
    INFORMATION_REQUESTED = "information_requested"
    
    # Actions
    TASK_COMPLETED = "task_completed"
    TASK_BLOCKED = "task_blocked"
    APPROVAL_NEEDED = "approval_needed"
    
    # Patterns
    PATTERN_DETECTED = "pattern_detected"
    ANOMALY_DETECTED = "anomaly_detected"
    
    # Social
    PERSON_MENTIONED = "person_mentioned"
    RELATIONSHIP_SIGNAL = "relationship_signal"
    
    # System
    SERVICE_EVENT = "service_event"
    ERROR_OCCURRED = "error_occurred"
    
    # User intent
    USER_QUERY = "user_query"
    USER_COMMAND = "user_command"
    USER_FEEDBACK = "user_feedback"


@dataclass
class Percept:
    """
    A percept - a meaningful unit of perception.
    
    Percepts are what the brain "sees" - not raw data,
    but interpreted, meaningful information.
    """
    id: str
    percept_type: PerceptType
    timestamp: datetime
    
    # Core content
    source: str                      # Where did this come from
    content: Dict[str, Any]          # The actual data
    summary: str                     # Human-readable summary
    
    # Extracted features
    entities: List[str] = field(default_factory=list)     # People, places, things
    topics: List[str] = field(default_factory=list)       # What it's about
    actions: List[str] = field(default_factory=list)      # Verbs/actions mentioned
    sentiment: float = 0.0                                 # -1 to 1
    urgency: float = 0.0                                   # 0 to 1
    
    # Temporal features
    references_past: bool = False
    references_future: bool = False
    temporal_expressions: List[str] = field(default_factory=list)
    
    # Attention weight (set by attention system)
    salience: float = 0.5
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.percept_type.value,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "summary": self.summary,
            "entities": self.entities,
            "topics": self.topics,
            "urgency": self.urgency,
            "salience": self.salience,
        }


class FeatureExtractor:
    """
    Extracts meaningful features from raw data.
    
    This is "perception" - turning raw signals into
    meaningful features the brain can work with.
    """
    
    # Patterns for extraction
    EMAIL_PATTERN = re.compile(r'[\w\.-]+@[\w\.-]+\.\w+')
    DATE_PATTERN = re.compile(r'\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\w+ \d{1,2}(?:st|nd|rd|th)?(?:,? \d{4})?)\b', re.I)
    TIME_PATTERN = re.compile(r'\b(\d{1,2}:\d{2}(?:\s*[ap]m)?|\d{1,2}\s*[ap]m)\b', re.I)
    URGENCY_WORDS = {'urgent', 'asap', 'immediately', 'critical', 'emergency', 'deadline', 'due', 'important'}
    FUTURE_WORDS = {'will', 'going to', 'tomorrow', 'next', 'upcoming', 'scheduled', 'planning'}
    PAST_WORDS = {'was', 'were', 'did', 'yesterday', 'last', 'ago', 'previously'}
    ACTION_WORDS = {'send', 'create', 'update', 'delete', 'schedule', 'remind', 'call', 'email', 'meet', 'review', 'approve', 'submit'}
    
    def extract(self, raw_data: Dict[str, Any], source: str) -> Dict[str, Any]:
        """Extract features from raw data."""
        text = self._get_text_content(raw_data)
        
        features = {
            "entities": self._extract_entities(text, raw_data),
            "topics": self._extract_topics(text),
            "actions": self._extract_actions(text),
            "sentiment": self._estimate_sentiment(text),
            "urgency": self._estimate_urgency(text),
            "references_past": self._references_past(text),
            "references_future": self._references_future(text),
            "temporal_expressions": self._extract_temporal(text),
        }
        
        return features
    
    def _get_text_content(self, data: Dict[str, Any]) -> str:
        """Extract text content from various data formats."""
        text_parts = []
        
        for key in ['subject', 'title', 'summary', 'body', 'content', 'description', 'message', 'text', 'name']:
            if key in data and isinstance(data[key], str):
                text_parts.append(data[key])
        
        return " ".join(text_parts)
    
    def _extract_entities(self, text: str, raw_data: Dict[str, Any]) -> List[str]:
        """Extract named entities."""
        entities = set()
        
        # Extract emails
        emails = self.EMAIL_PATTERN.findall(text)
        entities.update(emails)
        
        # Get explicit participants
        for key in ['from', 'sender', 'to', 'cc', 'attendees', 'participants', 'creator', 'owner']:
            if key in raw_data:
                val = raw_data[key]
                if isinstance(val, str):
                    entities.add(val)
                elif isinstance(val, list):
                    entities.update(str(v) for v in val if v)
                elif isinstance(val, dict):
                    for v in val.values():
                        if isinstance(v, str):
                            entities.add(v)
        
        return list(entities)[:20]  # Limit
    
    def _extract_topics(self, text: str) -> List[str]:
        """Extract topics/themes from text."""
        # Simple keyword extraction - could be enhanced with ML
        words = text.lower().split()
        
        # Filter for meaningful words
        stopwords = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'to', 'of', 'and', 'or', 'in', 'on', 'at', 'for', 'with', 'by', 'from', 'as', 'it', 'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'we', 'they'}
        
        meaningful = [w for w in words if len(w) > 3 and w not in stopwords and w.isalpha()]
        
        # Count frequency
        freq = {}
        for w in meaningful:
            freq[w] = freq.get(w, 0) + 1
        
        # Return top topics
        sorted_topics = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        return [t[0] for t in sorted_topics[:10]]
    
    def _extract_actions(self, text: str) -> List[str]:
        """Extract action verbs from text."""
        words = set(text.lower().split())
        return [w for w in self.ACTION_WORDS if w in words]
    
    def _estimate_sentiment(self, text: str) -> float:
        """Estimate sentiment from text (-1 to 1)."""
        positive = {'good', 'great', 'excellent', 'amazing', 'wonderful', 'happy', 'pleased', 'thanks', 'thank', 'appreciate', 'love', 'perfect'}
        negative = {'bad', 'terrible', 'awful', 'horrible', 'disappointed', 'frustrated', 'angry', 'upset', 'problem', 'issue', 'error', 'fail', 'wrong'}
        
        words = set(text.lower().split())
        pos_count = len(words & positive)
        neg_count = len(words & negative)
        
        total = pos_count + neg_count
        if total == 0:
            return 0.0
        
        return (pos_count - neg_count) / total
    
    def _estimate_urgency(self, text: str) -> float:
        """Estimate urgency from text (0 to 1)."""
        words = set(text.lower().split())
        urgent_count = len(words & self.URGENCY_WORDS)
        
        # Cap at 1.0
        return min(1.0, urgent_count * 0.25)
    
    def _references_past(self, text: str) -> bool:
        """Check if text references the past."""
        text_lower = text.lower()
        return any(word in text_lower for word in self.PAST_WORDS)
    
    def _references_future(self, text: str) -> bool:
        """Check if text references the future."""
        text_lower = text.lower()
        return any(word in text_lower for word in self.FUTURE_WORDS)
    
    def _extract_temporal(self, text: str) -> List[str]:
        """Extract temporal expressions."""
        expressions = []
        expressions.extend(self.DATE_PATTERN.findall(text))
        expressions.extend(self.TIME_PATTERN.findall(text))
        return expressions[:10]


class PerceptionStream:
    """
    The perception stream - continuous intake of information.
    
    This is the brain's interface to the world.
    It receives raw events, transforms them into percepts,
    and feeds them to the attention system.
    """
    
    def __init__(self, buffer_size: int = 100):
        self.buffer_size = buffer_size
        self._buffer: List[Percept] = []
        self._extractor = FeatureExtractor()
        self._processors: List[Callable[[Percept], Optional[Percept]]] = []
        self._listeners: List[Callable[[Percept], None]] = []
        self._running = False
        self._perception_count = 0
    
    def add_processor(self, processor: Callable[[Percept], Optional[Percept]]):
        """Add a perception processor (for enhancement/filtering)."""
        self._processors.append(processor)
    
    def add_listener(self, listener: Callable[[Percept], None]):
        """Add a listener that receives all percepts."""
        self._listeners.append(listener)
    
    def perceive(
        self,
        source: str,
        raw_data: Dict[str, Any],
        percept_type: Optional[PerceptType] = None,
    ) -> Percept:
        """
        Perceive something - transform raw data into a percept.
        
        This is how information enters the brain.
        """
        self._perception_count += 1
        
        # Determine percept type if not specified
        if percept_type is None:
            percept_type = self._infer_percept_type(source, raw_data)
        
        # Extract features
        features = self._extractor.extract(raw_data, source)
        
        # Create percept
        percept = Percept(
            id=hashlib.md5(f"{datetime.now().isoformat()}:{source}:{self._perception_count}".encode()).hexdigest()[:16],
            percept_type=percept_type,
            timestamp=datetime.now(),
            source=source,
            content=raw_data,
            summary=self._generate_summary(percept_type, raw_data, features),
            entities=features["entities"],
            topics=features["topics"],
            actions=features["actions"],
            sentiment=features["sentiment"],
            urgency=features["urgency"],
            references_past=features["references_past"],
            references_future=features["references_future"],
            temporal_expressions=features["temporal_expressions"],
        )
        
        # Run through processors
        for processor in self._processors:
            result = processor(percept)
            if result is None:
                return percept  # Filtered out
            percept = result
        
        # Add to buffer
        self._buffer.append(percept)
        if len(self._buffer) > self.buffer_size:
            self._buffer.pop(0)
        
        # Notify listeners
        for listener in self._listeners:
            try:
                listener(percept)
            except Exception as e:
                logger.error(f"Listener error: {e}")
        
        logger.debug(f"Perceived: {percept_type.value} from {source}")
        return percept
    
    def _infer_percept_type(self, source: str, data: Dict[str, Any]) -> PerceptType:
        """Infer percept type from source and data."""
        source_lower = source.lower()
        
        # Email-related
        if 'mail' in source_lower or 'email' in source_lower:
            if data.get('direction') == 'sent':
                return PerceptType.MESSAGE_SENT
            return PerceptType.MESSAGE_RECEIVED
        
        # Calendar-related
        if 'calendar' in source_lower:
            return PerceptType.MEETING_SCHEDULED
        
        # Document-related
        if 'drive' in source_lower or 'doc' in source_lower or 'file' in source_lower:
            if data.get('action') == 'modified':
                return PerceptType.DOCUMENT_MODIFIED
            return PerceptType.DOCUMENT_CREATED
        
        # User input
        if 'user' in source_lower or 'chat' in source_lower:
            return PerceptType.USER_QUERY
        
        # Default
        return PerceptType.SERVICE_EVENT
    
    def _generate_summary(
        self,
        percept_type: PerceptType,
        data: Dict[str, Any],
        features: Dict[str, Any],
    ) -> str:
        """Generate human-readable summary of percept."""
        # Try to use existing summary fields
        for key in ['subject', 'title', 'summary', 'name', 'description']:
            if key in data and isinstance(data[key], str):
                return data[key][:200]
        
        # Generate based on type
        type_name = percept_type.value.replace('_', ' ').title()
        
        if features["entities"]:
            return f"{type_name} involving {', '.join(features['entities'][:3])}"
        
        if features["topics"]:
            return f"{type_name} about {', '.join(features['topics'][:3])}"
        
        return f"{type_name}"
    
    def get_recent(self, limit: int = 20, percept_type: Optional[PerceptType] = None) -> List[Percept]:
        """Get recent percepts."""
        percepts = self._buffer
        
        if percept_type:
            percepts = [p for p in percepts if p.percept_type == percept_type]
        
        return list(reversed(percepts[-limit:]))
    
    def get_by_salience(self, threshold: float = 0.5, limit: int = 10) -> List[Percept]:
        """Get percepts above salience threshold."""
        high_salience = [p for p in self._buffer if p.salience >= threshold]
        high_salience.sort(key=lambda p: p.salience, reverse=True)
        return high_salience[:limit]
    
    def clear(self):
        """Clear perception buffer."""
        self._buffer = []
    
    def get_stats(self) -> Dict[str, Any]:
        """Get perception statistics."""
        type_counts = {}
        for p in self._buffer:
            t = p.percept_type.value
            type_counts[t] = type_counts.get(t, 0) + 1
        
        return {
            "total_perceived": self._perception_count,
            "buffer_size": len(self._buffer),
            "buffer_capacity": self.buffer_size,
            "type_distribution": type_counts,
            "avg_salience": sum(p.salience for p in self._buffer) / len(self._buffer) if self._buffer else 0,
        }
