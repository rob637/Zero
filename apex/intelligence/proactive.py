"""
Proactive Suggestion Engine

This is the "HOW DID IT KNOW?!" engine.

Instead of waiting for you to ask, Telic:
1. ANTICIPATES your needs based on patterns
2. MONITORS for triggers that require attention
3. PREPARES context before you need it
4. SUGGESTS actions at the right moment

Examples:
- "You have a meeting with John in 30 min - here's prep material"
- "Your flight was delayed - want me to reschedule your 3pm meeting?"
- "You haven't responded to Sarah's urgent email from 2 days ago"
- "Based on your Friday pattern, should I prepare the weekly report?"
- "Multiple emails about 'Project Apollo' - want a summary?"

This engine ties together:
- Pattern recognition (what you usually do)
- Semantic memory (what you know)
- Cross-service intelligence (connecting dots)
- Real-time monitoring (what's happening now)

Usage:
    from intelligence.proactive import ProactiveSuggestionEngine
    
    engine = ProactiveSuggestionEngine(memory, patterns, intel, services)
    
    # Generate suggestions for now
    suggestions = await engine.get_suggestions()
    
    # Get contextual suggestions (something just happened)
    suggestions = await engine.on_event("email_received", email_data)
    
    # Check for things that need attention
    urgent = await engine.get_attention_required()
"""

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Callable, Awaitable
import logging

logger = logging.getLogger(__name__)


class SuggestionPriority(Enum):
    """Priority levels for suggestions."""
    URGENT = "urgent"        # Needs immediate attention
    HIGH = "high"            # Important, should act soon
    MEDIUM = "medium"        # Helpful, can wait
    LOW = "low"              # Nice to have


class SuggestionCategory(Enum):
    """Categories of suggestions."""
    MEETING_PREP = "meeting_prep"        # Prepare for upcoming meeting
    EMAIL_FOLLOWUP = "email_followup"    # Follow up on email
    TASK_REMINDER = "task_reminder"      # Task needs attention
    PATTERN_BASED = "pattern_based"      # Based on detected patterns
    ANOMALY_ALERT = "anomaly_alert"      # Something unusual detected
    CONTENT_DIGEST = "content_digest"    # Summarize related content
    SCHEDULE_CONFLICT = "schedule_conflict"  # Calendar issue
    ACTION_REQUIRED = "action_required"  # Someone waiting on you


@dataclass
class ProactiveSuggestion:
    """A proactive suggestion from Telic."""
    id: str
    title: str
    description: str
    category: SuggestionCategory
    priority: SuggestionPriority
    
    # When this suggestion is relevant
    relevant_until: Optional[datetime] = None
    
    # What triggered this
    trigger: str = ""
    trigger_data: Dict = field(default_factory=dict)
    
    # Suggested actions
    actions: List[Dict] = field(default_factory=list)
    # e.g., [{"label": "Prepare materials", "action": "prepare_meeting", "params": {...}}]
    
    # Supporting content
    supporting_content: List[Dict] = field(default_factory=list)
    # e.g., [{"type": "email", "title": "Re: Budget", "url": "..."}]
    
    # Confidence and reasoning
    confidence: float = 0.0
    reasoning: str = ""
    
    created: datetime = field(default_factory=datetime.now)
    dismissed: bool = False
    acted_on: bool = False
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "category": self.category.value,
            "priority": self.priority.value,
            "relevant_until": self.relevant_until.isoformat() if self.relevant_until else None,
            "trigger": self.trigger,
            "actions": self.actions,
            "supporting_content": self.supporting_content,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "created": self.created.isoformat(),
        }


class ProactiveSuggestionEngine:
    """
    Generates proactive suggestions by connecting intelligence layers.
    
    This is the brain that ties everything together:
    - Uses patterns to know what's expected
    - Uses memory to understand context
    - Uses cross-service intel to gather info
    - Uses services to monitor real-time state
    """
    
    def __init__(
        self,
        semantic_memory=None,
        pattern_engine=None,
        cross_service_intel=None,
        unified_services=None,
        preference_learner=None,
    ):
        self._memory = semantic_memory
        self._patterns = pattern_engine
        self._intel = cross_service_intel
        self._services = unified_services
        self._prefs = preference_learner
        
        # Active suggestions
        self._suggestions: Dict[str, ProactiveSuggestion] = {}
        
        # Event handlers
        self._event_handlers: Dict[str, List[Callable]] = defaultdict(list)
        
        # State tracking
        self._last_check = datetime.now()
        self._check_interval = timedelta(minutes=5)
        
        # Register default handlers
        self._register_default_handlers()
    
    def set_services(self, services):
        """Set unified services."""
        self._services = services
    
    def set_memory(self, memory):
        """Set semantic memory."""
        self._memory = memory
    
    def set_patterns(self, patterns):
        """Set pattern engine."""
        self._patterns = patterns
    
    def set_intel(self, intel):
        """Set cross-service intelligence."""
        self._intel = intel
    
    def _generate_id(self) -> str:
        """Generate suggestion ID."""
        import hashlib
        return hashlib.sha256(datetime.now().isoformat().encode()).hexdigest()[:12]
    
    def _register_default_handlers(self):
        """Register default event handlers."""
        self._event_handlers["email_received"].append(self._handle_email_received)
        self._event_handlers["calendar_event_soon"].append(self._handle_meeting_soon)
        self._event_handlers["pattern_expected"].append(self._handle_pattern_expected)
        self._event_handlers["anomaly_detected"].append(self._handle_anomaly)
    
    # =========================================================================
    # Core API
    # =========================================================================
    
    async def get_suggestions(
        self,
        max_suggestions: int = 10,
        min_priority: SuggestionPriority = SuggestionPriority.LOW,
    ) -> List[ProactiveSuggestion]:
        """
        Get current proactive suggestions.
        
        This is the main entry point - call periodically or on-demand.
        """
        await self._refresh_suggestions()
        
        # Filter and sort
        now = datetime.now()
        priority_order = [
            SuggestionPriority.URGENT,
            SuggestionPriority.HIGH,
            SuggestionPriority.MEDIUM,
            SuggestionPriority.LOW,
        ]
        
        active = [
            s for s in self._suggestions.values()
            if not s.dismissed
            and not s.acted_on
            and (s.relevant_until is None or s.relevant_until > now)
            and priority_order.index(s.priority) <= priority_order.index(min_priority)
        ]
        
        # Sort by priority, then by creation time
        return sorted(
            active,
            key=lambda s: (priority_order.index(s.priority), s.created)
        )[:max_suggestions]
    
    async def get_attention_required(self) -> List[ProactiveSuggestion]:
        """Get urgent/high priority items that need attention."""
        return await self.get_suggestions(
            max_suggestions=5,
            min_priority=SuggestionPriority.HIGH,
        )
    
    async def on_event(
        self,
        event_type: str,
        event_data: Dict = None,
    ) -> List[ProactiveSuggestion]:
        """
        Handle an event and generate relevant suggestions.
        
        Call this when something happens:
        - Email received
        - Calendar event starting soon
        - Task completed
        - File modified
        """
        event_data = event_data or {}
        new_suggestions = []
        
        handlers = self._event_handlers.get(event_type, [])
        for handler in handlers:
            try:
                suggestions = await handler(event_data)
                new_suggestions.extend(suggestions)
            except Exception as e:
                logger.warning(f"Handler failed for {event_type}: {e}")
        
        # Add to active suggestions
        for s in new_suggestions:
            self._suggestions[s.id] = s
        
        return new_suggestions
    
    async def dismiss(self, suggestion_id: str):
        """Dismiss a suggestion."""
        if suggestion_id in self._suggestions:
            self._suggestions[suggestion_id].dismissed = True
    
    async def mark_acted(self, suggestion_id: str):
        """Mark a suggestion as acted upon."""
        if suggestion_id in self._suggestions:
            self._suggestions[suggestion_id].acted_on = True
    
    # =========================================================================
    # Suggestion Generation
    # =========================================================================
    
    async def _refresh_suggestions(self):
        """Refresh suggestions based on current state."""
        now = datetime.now()
        
        # Don't refresh too often
        if now - self._last_check < self._check_interval:
            return
        
        self._last_check = now
        
        # Check upcoming meetings
        await self._check_upcoming_meetings()
        
        # Check expected patterns
        await self._check_expected_patterns()
        
        # Check for anomalies
        await self._check_anomalies()
        
        # Check for overdue responses
        await self._check_overdue_responses()
        
        # Check for content clusters (multiple items about same topic)
        await self._check_content_clusters()
        
        # Clean up expired suggestions
        self._cleanup_expired()
    
    async def _check_upcoming_meetings(self):
        """Check for meetings in the next hour and suggest prep."""
        if not self._services:
            return
        
        try:
            now = datetime.now()
            soon = now + timedelta(hours=1)
            
            events = await self._services.calendar.list_events(
                start=now,
                end=soon,
                limit=10,
            )
            
            for event in events:
                start_str = event.get("start")
                if not start_str:
                    continue
                
                start_time = self._parse_timestamp(start_str)
                if not start_time:
                    continue
                
                minutes_until = (start_time - now).total_seconds() / 60
                
                # Suggest prep at 30 min and 10 min marks
                if 25 <= minutes_until <= 35 or 8 <= minutes_until <= 12:
                    await self.on_event("calendar_event_soon", {
                        "event": event,
                        "minutes_until": minutes_until,
                    })
        except Exception as e:
            logger.warning(f"Failed to check meetings: {e}")
    
    async def _check_expected_patterns(self):
        """Check if expected patterns are due."""
        if not self._patterns:
            return
        
        try:
            expected = await self._patterns.whats_expected_now(window_minutes=30)
            
            for pattern in expected:
                await self.on_event("pattern_expected", {
                    "pattern": pattern["pattern"],
                    "confidence": pattern["confidence"],
                    "last_occurred": pattern.get("last_occurred"),
                })
        except Exception as e:
            logger.warning(f"Failed to check patterns: {e}")
    
    async def _check_anomalies(self):
        """Check for anomalies."""
        if not self._patterns:
            return
        
        try:
            anomalies = await self._patterns.detect_anomalies()
            
            for anomaly in anomalies:
                await self.on_event("anomaly_detected", anomaly)
        except Exception as e:
            logger.warning(f"Failed to check anomalies: {e}")
    
    async def _check_overdue_responses(self):
        """Check for emails that need responses."""
        if not self._services:
            return
        
        try:
            # Get recent unread emails
            emails = await self._services.email.search(
                query="is:unread",
                limit=20,
            )
            
            now = datetime.now()
            
            for email in emails:
                date_str = email.get("date")
                if not date_str:
                    continue
                
                email_date = self._parse_timestamp(date_str)
                if not email_date:
                    continue
                
                age_hours = (now - email_date).total_seconds() / 3600
                
                # Flag if unread for >24 hours
                if age_hours > 24:
                    # Check if it seems important
                    subject = email.get("subject", "").lower()
                    is_urgent = any(w in subject for w in ["urgent", "asap", "important", "action required"])
                    
                    suggestion_id = f"email_overdue_{email.get('id', '')}"
                    
                    if suggestion_id not in self._suggestions:
                        self._suggestions[suggestion_id] = ProactiveSuggestion(
                            id=suggestion_id,
                            title=f"Unread email: {email.get('subject', 'No subject')[:50]}",
                            description=f"From {email.get('from', 'Unknown')} - {age_hours:.0f} hours old",
                            category=SuggestionCategory.EMAIL_FOLLOWUP,
                            priority=SuggestionPriority.HIGH if is_urgent else SuggestionPriority.MEDIUM,
                            trigger="overdue_email",
                            trigger_data={"email_id": email.get("id")},
                            actions=[
                                {"label": "Open email", "action": "open_email", "params": {"id": email.get("id")}},
                                {"label": "Mark read", "action": "mark_read", "params": {"id": email.get("id")}},
                            ],
                            confidence=0.8,
                            reasoning=f"Email unread for {age_hours:.0f} hours",
                        )
        except Exception as e:
            logger.warning(f"Failed to check emails: {e}")
    
    async def _check_content_clusters(self):
        """Check for clusters of related content that might need attention."""
        if not self._intel:
            return
        
        # This would analyze recent activity to find clusters
        # For now, placeholder
        pass
    
    def _cleanup_expired(self):
        """Remove expired suggestions."""
        now = datetime.now()
        expired = [
            sid for sid, s in self._suggestions.items()
            if s.relevant_until and s.relevant_until < now
        ]
        for sid in expired:
            del self._suggestions[sid]
    
    # =========================================================================
    # Event Handlers
    # =========================================================================
    
    async def _handle_email_received(self, data: Dict) -> List[ProactiveSuggestion]:
        """Handle incoming email event."""
        suggestions = []
        email = data.get("email", {})
        
        subject = email.get("subject", "")
        sender = email.get("from", "")
        
        # Check if sender is someone we communicate with frequently
        if self._intel:
            try:
                brief = await self._intel.brief_on_person(sender, max_items=3)
                
                if brief.communication_frequency in ["daily", "weekly"]:
                    # Important contact - surface this
                    suggestions.append(ProactiveSuggestion(
                        id=self._generate_id(),
                        title=f"Email from {sender}",
                        description=subject,
                        category=SuggestionCategory.EMAIL_FOLLOWUP,
                        priority=SuggestionPriority.HIGH,
                        trigger="email_received",
                        trigger_data={"email": email},
                        relevant_until=datetime.now() + timedelta(hours=4),
                        confidence=0.7,
                        reasoning=f"Frequent contact ({brief.communication_frequency} communication)",
                    ))
            except:
                pass
        
        # Check for urgency keywords
        if any(kw in subject.lower() for kw in ["urgent", "asap", "important", "action required"]):
            suggestions.append(ProactiveSuggestion(
                id=self._generate_id(),
                title=f"Urgent: {subject[:50]}",
                description=f"From {sender}",
                category=SuggestionCategory.ACTION_REQUIRED,
                priority=SuggestionPriority.URGENT,
                trigger="urgent_email",
                trigger_data={"email": email},
                relevant_until=datetime.now() + timedelta(hours=8),
                actions=[
                    {"label": "Open email", "action": "open_email", "params": {"id": email.get("id")}},
                ],
                confidence=0.9,
                reasoning="Email marked as urgent",
            ))
        
        return suggestions
    
    async def _handle_meeting_soon(self, data: Dict) -> List[ProactiveSuggestion]:
        """Handle upcoming meeting event."""
        event = data.get("event", {})
        minutes_until = data.get("minutes_until", 30)
        
        title = event.get("title", "Meeting")
        attendees = event.get("attendees", [])
        
        suggestion_id = f"meeting_prep_{event.get('id', self._generate_id())}"
        
        # Don't duplicate
        if suggestion_id in self._suggestions:
            return []
        
        # Get meeting prep materials if we have the intel layer
        supporting_content = []
        if self._intel and attendees:
            try:
                prep = await self._intel.prepare_for_meeting(meeting=event)
                supporting_content = [
                    {"type": "email", "title": e.title, "snippet": e.snippet}
                    for e in prep.related_emails[:3]
                ] + [
                    {"type": "document", "title": d.title}
                    for d in prep.related_documents[:3]
                ]
            except:
                pass
        
        suggestion = ProactiveSuggestion(
            id=suggestion_id,
            title=f"Meeting in {int(minutes_until)} min: {title}",
            description=f"With {len(attendees)} attendee(s)",
            category=SuggestionCategory.MEETING_PREP,
            priority=SuggestionPriority.HIGH if minutes_until < 15 else SuggestionPriority.MEDIUM,
            trigger="calendar_event_soon",
            trigger_data={"event": event},
            relevant_until=self._parse_timestamp(event.get("start")),
            actions=[
                {"label": "View prep materials", "action": "view_meeting_prep", "params": {"event_id": event.get("id")}},
                {"label": "Join meeting", "action": "join_meeting", "params": {"url": event.get("conference_url")}},
            ],
            supporting_content=supporting_content,
            confidence=0.95,
            reasoning=f"Meeting starting in {int(minutes_until)} minutes",
        )
        
        return [suggestion]
    
    async def _handle_pattern_expected(self, data: Dict) -> List[ProactiveSuggestion]:
        """Handle expected pattern event."""
        pattern_name = data.get("pattern", "")
        confidence = data.get("confidence", 0.5)
        
        suggestion_id = f"pattern_{pattern_name.replace(' ', '_')}"
        
        # Don't duplicate within 1 hour
        if suggestion_id in self._suggestions:
            existing = self._suggestions[suggestion_id]
            if (datetime.now() - existing.created).total_seconds() < 3600:
                return []
        
        suggestion = ProactiveSuggestion(
            id=suggestion_id,
            title=f"Usual time for: {pattern_name}",
            description=f"Based on your patterns, you usually do this now",
            category=SuggestionCategory.PATTERN_BASED,
            priority=SuggestionPriority.LOW,
            trigger="pattern_expected",
            trigger_data={"pattern": pattern_name},
            relevant_until=datetime.now() + timedelta(hours=2),
            confidence=confidence,
            reasoning=f"Pattern detected with {confidence:.0%} confidence",
        )
        
        return [suggestion]
    
    async def _handle_anomaly(self, data: Dict) -> List[ProactiveSuggestion]:
        """Handle anomaly detection event."""
        anomaly_type = data.get("type", "unknown")
        description = data.get("description", "Unusual activity detected")
        
        suggestion_id = f"anomaly_{self._generate_id()}"
        
        suggestion = ProactiveSuggestion(
            id=suggestion_id,
            title=f"Unusual: {description[:50]}",
            description=description,
            category=SuggestionCategory.ANOMALY_ALERT,
            priority=SuggestionPriority.MEDIUM,
            trigger="anomaly_detected",
            trigger_data=data,
            relevant_until=datetime.now() + timedelta(hours=8),
            confidence=0.6,
            reasoning=f"Anomaly type: {anomaly_type}",
        )
        
        return [suggestion]
    
    # =========================================================================
    # Utilities
    # =========================================================================
    
    def _parse_timestamp(self, ts: Any) -> Optional[datetime]:
        """Parse various timestamp formats."""
        if ts is None:
            return None
        
        if isinstance(ts, datetime):
            return ts
        
        if isinstance(ts, str):
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except:
                pass
        
        return None
    
    def get_stats(self) -> Dict:
        """Get engine statistics."""
        now = datetime.now()
        active = [
            s for s in self._suggestions.values()
            if not s.dismissed and not s.acted_on
        ]
        
        return {
            "total_suggestions": len(self._suggestions),
            "active_suggestions": len(active),
            "by_priority": {
                p.value: len([s for s in active if s.priority == p])
                for p in SuggestionPriority
            },
            "by_category": {
                c.value: len([s for s in active if s.category == c])
                for c in SuggestionCategory
            },
        }


# Singleton
_engine: Optional[ProactiveSuggestionEngine] = None

def get_proactive_engine() -> ProactiveSuggestionEngine:
    """Get or create the proactive suggestion engine singleton."""
    global _engine
    if _engine is None:
        _engine = ProactiveSuggestionEngine()
    return _engine
