"""
Cross-Service Intelligence

This is what makes Telic magical - connecting dots across services.

When you say "prepare for my meeting with John":
- Recent emails with/about John
- Previous meeting notes with John
- Shared documents
- Outstanding tasks involving John
- Calendar history (when you last met)
- Any context from semantic memory

This CANNOT be done with simple API calls - it requires:
1. Entity resolution (John Smith = john@company.com = "JS")
2. Cross-service correlation (email + calendar + files)
3. Relevance scoring (what matters NOW)
4. Context assembly (building a coherent briefing)

Usage:
    from intelligence.cross_service import CrossServiceIntelligence
    
    intel = CrossServiceIntelligence(services, memory, patterns)
    
    # Get briefing for a person
    brief = await intel.brief_on_person("John Smith")
    
    # Prepare for a meeting
    prep = await intel.prepare_for_meeting(meeting_id)
    
    # Find related content across services
    related = await intel.find_related("project apollo")
    
    # Get context for composing
    context = await intel.get_composition_context(
        action="email",
        recipient="sarah@company.com",
        topic="quarterly review"
    )
"""

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
import logging

logger = logging.getLogger(__name__)


class ContentType(Enum):
    """Types of content we can gather."""
    EMAIL = "email"
    CALENDAR_EVENT = "calendar_event"
    DOCUMENT = "document"
    TASK = "task"
    NOTE = "note"
    CONTACT = "contact"
    MEMORY = "memory"  # From semantic memory


@dataclass
class RelevantContent:
    """A piece of content relevant to a query."""
    content_type: ContentType
    title: str
    snippet: str
    source: str  # e.g., "gmail", "outlook", "google_drive"
    url: Optional[str] = None
    timestamp: Optional[datetime] = None
    
    # Relevance scoring
    relevance_score: float = 0.0  # 0-1
    relevance_reason: str = ""
    
    # Entity links
    people: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)
    
    # Raw data
    raw: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "type": self.content_type.value,
            "title": self.title,
            "snippet": self.snippet,
            "source": self.source,
            "url": self.url,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "relevance_score": self.relevance_score,
            "relevance_reason": self.relevance_reason,
            "people": self.people,
            "topics": self.topics,
        }


@dataclass
class PersonBrief:
    """Comprehensive briefing about a person."""
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    organization: Optional[str] = None
    title: Optional[str] = None
    
    # Relationship context
    relationship_summary: str = ""
    last_contact: Optional[datetime] = None
    communication_frequency: str = ""  # "daily", "weekly", "monthly", "occasional"
    
    # Recent activity
    recent_emails: List[RelevantContent] = field(default_factory=list)
    upcoming_meetings: List[RelevantContent] = field(default_factory=list)
    past_meetings: List[RelevantContent] = field(default_factory=list)
    shared_documents: List[RelevantContent] = field(default_factory=list)
    related_tasks: List[RelevantContent] = field(default_factory=list)
    
    # From memory
    known_facts: List[str] = field(default_factory=list)
    preferences: Dict[str, Any] = field(default_factory=dict)
    
    # Topics discussed
    common_topics: List[str] = field(default_factory=list)


@dataclass
class MeetingPrep:
    """Preparation materials for a meeting."""
    meeting_title: str
    meeting_time: datetime
    attendees: List[str]
    
    # Attendee briefs
    attendee_briefs: Dict[str, PersonBrief] = field(default_factory=dict)
    
    # Relevant content
    related_emails: List[RelevantContent] = field(default_factory=list)
    related_documents: List[RelevantContent] = field(default_factory=list)
    previous_meetings: List[RelevantContent] = field(default_factory=list)
    related_tasks: List[RelevantContent] = field(default_factory=list)
    
    # Context from memory
    relevant_memories: List[str] = field(default_factory=list)
    
    # Suggested discussion points
    suggested_topics: List[str] = field(default_factory=list)
    
    # Action items from previous meetings
    pending_actions: List[str] = field(default_factory=list)


class CrossServiceIntelligence:
    """
    Connects dots across all integrated services.
    
    This is where the magic happens - understanding that:
    - An email from john@company.com
    - A calendar event with "John Smith"
    - A document shared by "J. Smith"
    - A task about "John's project"
    
    Are all about the SAME PERSON.
    """
    
    def __init__(
        self,
        unified_services=None,  # The unified service layer
        semantic_memory=None,   # SemanticMemory instance
        pattern_engine=None,    # PatternEngine instance
        preference_learner=None, # PreferenceLearner instance
    ):
        self._services = unified_services
        self._memory = semantic_memory
        self._patterns = pattern_engine
        self._preferences = preference_learner
        
        # Entity resolution cache
        self._entity_aliases: Dict[str, Set[str]] = defaultdict(set)
        # e.g., {"john_smith": {"john@company.com", "John Smith", "J. Smith", "JS"}}
    
    def set_services(self, services):
        """Set unified services (for late binding)."""
        self._services = services
    
    def set_memory(self, memory):
        """Set semantic memory (for late binding)."""
        self._memory = memory
    
    def set_patterns(self, patterns):
        """Set pattern engine (for late binding)."""
        self._patterns = patterns
    
    def set_preferences(self, preferences):
        """Set preference learner (for late binding)."""
        self._preferences = preferences
    
    # =========================================================================
    # Entity Resolution
    # =========================================================================
    
    def learn_alias(self, canonical: str, alias: str):
        """
        Learn that an alias refers to a canonical entity.
        
        Example:
            intel.learn_alias("john_smith", "john@company.com")
            intel.learn_alias("john_smith", "John Smith")
        """
        canonical_lower = canonical.lower().replace(" ", "_")
        self._entity_aliases[canonical_lower].add(alias.lower())
    
    def resolve_entity(self, name_or_email: str) -> Optional[str]:
        """
        Resolve a name or email to its canonical entity.
        
        Returns the canonical name, or None if no match.
        """
        query = name_or_email.lower()
        
        # Check if it IS a canonical name
        if query.replace(" ", "_") in self._entity_aliases:
            return query.replace(" ", "_")
        
        # Check aliases
        for canonical, aliases in self._entity_aliases.items():
            if query in aliases:
                return canonical
            
            # Fuzzy match - check if query is contained in any alias
            for alias in aliases:
                if query in alias or alias in query:
                    return canonical
        
        # No match - create new canonical (normalize)
        return query.replace(" ", "_").replace("@", "_at_")
    
    def get_all_aliases(self, canonical: str) -> Set[str]:
        """Get all known aliases for an entity."""
        canonical_lower = canonical.lower().replace(" ", "_")
        return self._entity_aliases.get(canonical_lower, {canonical})
    
    # =========================================================================
    # Person Intelligence
    # =========================================================================
    
    async def brief_on_person(
        self,
        person: str,
        lookback_days: int = 30,
        max_items: int = 10,
    ) -> PersonBrief:
        """
        Get a comprehensive briefing about a person.
        
        Gathers:
        - Contact info
        - Recent email exchanges
        - Meeting history
        - Shared documents
        - Related tasks
        - Known facts from memory
        """
        canonical = self.resolve_entity(person)
        aliases = self.get_all_aliases(canonical)
        
        brief = PersonBrief(name=person)
        
        # Get contact info (if we have services)
        if self._services:
            try:
                contact = await self._find_contact(person, aliases)
                if contact:
                    brief.email = contact.get("email")
                    brief.phone = contact.get("phone")
                    brief.organization = contact.get("organization")
                    brief.title = contact.get("title")
            except Exception as e:
                logger.warning(f"Failed to get contact info: {e}")
        
        # Get emails
        if self._services:
            try:
                emails = await self._find_emails_with(person, aliases, lookback_days, max_items)
                brief.recent_emails = emails
                
                if emails:
                    brief.last_contact = max(e.timestamp for e in emails if e.timestamp)
            except Exception as e:
                logger.warning(f"Failed to get emails: {e}")
        
        # Get meetings
        if self._services:
            try:
                upcoming, past = await self._find_meetings_with(person, aliases, lookback_days, max_items)
                brief.upcoming_meetings = upcoming
                brief.past_meetings = past
            except Exception as e:
                logger.warning(f"Failed to get meetings: {e}")
        
        # Get shared documents
        if self._services:
            try:
                docs = await self._find_shared_docs(person, aliases, max_items)
                brief.shared_documents = docs
            except Exception as e:
                logger.warning(f"Failed to get documents: {e}")
        
        # Get from memory
        if self._memory:
            try:
                # Recall facts about this person
                facts = await self._recall_about_person(person, aliases)
                brief.known_facts = [f.content for f in facts[:10]]
                
                # Get entity info from knowledge graph
                entity_info = await self._memory.get_entity(canonical)
                if entity_info:
                    brief.preferences = entity_info.get("attributes", {})
            except Exception as e:
                logger.warning(f"Failed to get memory: {e}")
        
        # Analyze communication frequency
        brief.communication_frequency = self._analyze_frequency(brief)
        
        # Extract common topics
        brief.common_topics = self._extract_topics(brief)
        
        # Generate relationship summary
        brief.relationship_summary = self._generate_relationship_summary(brief)
        
        return brief
    
    async def _find_contact(self, person: str, aliases: Set[str]) -> Optional[Dict]:
        """Find contact info across services."""
        if not self._services:
            return None
        
        # Try unified contacts API
        try:
            contacts = await self._services.contacts.search(person)
            if contacts:
                return contacts[0]
            
            # Try each alias
            for alias in aliases:
                contacts = await self._services.contacts.search(alias)
                if contacts:
                    return contacts[0]
        except:
            pass
        
        return None
    
    async def _find_emails_with(
        self,
        person: str,
        aliases: Set[str],
        lookback_days: int,
        max_items: int,
    ) -> List[RelevantContent]:
        """Find recent emails involving this person."""
        if not self._services:
            return []
        
        results = []
        
        try:
            # Search for emails
            for alias in list(aliases)[:3]:  # Limit searches
                emails = await self._services.email.search(
                    query=alias,
                    limit=max_items,
                )
                
                for email in emails:
                    results.append(RelevantContent(
                        content_type=ContentType.EMAIL,
                        title=email.get("subject", "No subject"),
                        snippet=email.get("snippet", ""),
                        source=self._services.email.provider,
                        url=email.get("web_link"),
                        timestamp=self._parse_timestamp(email.get("date")),
                        people=[email.get("from", ""), *email.get("to", [])[:3]],
                        raw=email,
                    ))
        except Exception as e:
            logger.warning(f"Email search failed: {e}")
        
        # Deduplicate and sort by date
        seen_ids = set()
        unique = []
        for r in results:
            email_id = r.raw.get("id", r.title)
            if email_id not in seen_ids:
                seen_ids.add(email_id)
                unique.append(r)
        
        return sorted(
            unique,
            key=lambda x: x.timestamp or datetime.min,
            reverse=True
        )[:max_items]
    
    async def _find_meetings_with(
        self,
        person: str,
        aliases: Set[str],
        lookback_days: int,
        max_items: int,
    ) -> Tuple[List[RelevantContent], List[RelevantContent]]:
        """Find meetings with this person (upcoming and past)."""
        if not self._services:
            return [], []
        
        now = datetime.now()
        past_cutoff = now - timedelta(days=lookback_days)
        future_cutoff = now + timedelta(days=30)
        
        upcoming = []
        past = []
        
        try:
            events = await self._services.calendar.list_events(
                start=past_cutoff,
                end=future_cutoff,
                limit=100,
            )
            
            for event in events:
                # Check if person is involved
                attendees = event.get("attendees", [])
                attendee_emails = [a.get("email", "").lower() for a in attendees]
                attendee_names = [a.get("name", "").lower() for a in attendees]
                
                is_involved = False
                for alias in aliases:
                    if alias in attendee_emails or alias in attendee_names:
                        is_involved = True
                        break
                    if any(alias in e for e in attendee_emails + attendee_names):
                        is_involved = True
                        break
                
                if not is_involved:
                    # Also check title/description
                    title = event.get("title", "").lower()
                    desc = event.get("description", "").lower()
                    for alias in aliases:
                        if alias in title or alias in desc:
                            is_involved = True
                            break
                
                if is_involved:
                    start_time = self._parse_timestamp(event.get("start"))
                    
                    content = RelevantContent(
                        content_type=ContentType.CALENDAR_EVENT,
                        title=event.get("title", "Meeting"),
                        snippet=event.get("description", "")[:200],
                        source=self._services.calendar.provider,
                        url=event.get("web_link"),
                        timestamp=start_time,
                        people=[a.get("email", "") for a in attendees[:5]],
                        raw=event,
                    )
                    
                    if start_time and start_time > now:
                        upcoming.append(content)
                    else:
                        past.append(content)
        
        except Exception as e:
            logger.warning(f"Calendar search failed: {e}")
        
        return (
            sorted(upcoming, key=lambda x: x.timestamp or datetime.max)[:max_items],
            sorted(past, key=lambda x: x.timestamp or datetime.min, reverse=True)[:max_items]
        )
    
    async def _find_shared_docs(
        self,
        person: str,
        aliases: Set[str],
        max_items: int,
    ) -> List[RelevantContent]:
        """Find documents shared with/by this person."""
        if not self._services:
            return []
        
        results = []
        
        try:
            for alias in list(aliases)[:2]:
                files = await self._services.files.search(
                    query=alias,
                    limit=max_items,
                )
                
                for file in files:
                    results.append(RelevantContent(
                        content_type=ContentType.DOCUMENT,
                        title=file.get("name", "Document"),
                        snippet=f"Modified: {file.get('modified', 'Unknown')}",
                        source=self._services.files.provider,
                        url=file.get("web_link"),
                        timestamp=self._parse_timestamp(file.get("modified")),
                        raw=file,
                    ))
        except Exception as e:
            logger.warning(f"File search failed: {e}")
        
        # Deduplicate
        seen = set()
        unique = []
        for r in results:
            key = r.raw.get("id", r.title)
            if key not in seen:
                seen.add(key)
                unique.append(r)
        
        return unique[:max_items]
    
    async def _recall_about_person(self, person: str, aliases: Set[str]) -> List:
        """Get facts from semantic memory about this person."""
        if not self._memory:
            return []
        
        results = []
        
        # Try main name first
        facts = await self._memory.recall_about(person)
        results.extend(facts)
        
        # Try aliases
        for alias in list(aliases)[:3]:
            facts = await self._memory.recall_about(alias)
            results.extend(facts)
        
        return results
    
    def _analyze_frequency(self, brief: PersonBrief) -> str:
        """Analyze communication frequency."""
        total_interactions = (
            len(brief.recent_emails) +
            len(brief.past_meetings)
        )
        
        if total_interactions == 0:
            return "no_recent_contact"
        elif total_interactions >= 20:
            return "daily"
        elif total_interactions >= 8:
            return "weekly"
        elif total_interactions >= 2:
            return "monthly"
        else:
            return "occasional"
    
    def _extract_topics(self, brief: PersonBrief) -> List[str]:
        """Extract common topics from interactions."""
        # Simple keyword extraction from email subjects and meeting titles
        text = " ".join([
            *[e.title for e in brief.recent_emails],
            *[m.title for m in brief.past_meetings],
        ]).lower()
        
        # Common business topics to look for
        topic_keywords = {
            "project": ["project", "initiative", "program"],
            "budget": ["budget", "finance", "cost", "expense"],
            "planning": ["plan", "strategy", "roadmap"],
            "review": ["review", "feedback", "assessment"],
            "deadline": ["deadline", "due", "milestone"],
            "team": ["team", "hiring", "staff"],
        }
        
        found_topics = []
        for topic, keywords in topic_keywords.items():
            if any(kw in text for kw in keywords):
                found_topics.append(topic)
        
        return found_topics[:5]
    
    def _generate_relationship_summary(self, brief: PersonBrief) -> str:
        """Generate a human-readable relationship summary."""
        parts = []
        
        if brief.organization:
            parts.append(f"Works at {brief.organization}")
        
        if brief.title:
            parts.append(f"Role: {brief.title}")
        
        parts.append(f"Communication: {brief.communication_frequency.replace('_', ' ')}")
        
        if brief.last_contact:
            days_ago = (datetime.now() - brief.last_contact).days
            if days_ago == 0:
                parts.append("Last contact: today")
            elif days_ago == 1:
                parts.append("Last contact: yesterday")
            else:
                parts.append(f"Last contact: {days_ago} days ago")
        
        if brief.common_topics:
            parts.append(f"Common topics: {', '.join(brief.common_topics)}")
        
        return ". ".join(parts)
    
    # =========================================================================
    # Meeting Intelligence
    # =========================================================================
    
    async def prepare_for_meeting(
        self,
        meeting: Dict = None,
        meeting_id: str = None,
        title: str = None,
        attendees: List[str] = None,
    ) -> MeetingPrep:
        """
        Prepare comprehensive materials for a meeting.
        
        Can be called with:
        - A meeting dict from the calendar API
        - A meeting ID to look up
        - Just a title and attendees
        """
        # Get meeting details
        if meeting:
            title = meeting.get("title", "Meeting")
            start_time = self._parse_timestamp(meeting.get("start"))
            attendees = [a.get("email", "") for a in meeting.get("attendees", [])]
        elif meeting_id and self._services:
            meeting = await self._services.calendar.get_event(meeting_id)
            title = meeting.get("title", "Meeting")
            start_time = self._parse_timestamp(meeting.get("start"))
            attendees = [a.get("email", "") for a in meeting.get("attendees", [])]
        else:
            title = title or "Meeting"
            start_time = datetime.now()
            attendees = attendees or []
        
        prep = MeetingPrep(
            meeting_title=title,
            meeting_time=start_time,
            attendees=attendees,
        )
        
        # Get briefs on all attendees
        for attendee in attendees[:5]:  # Limit to 5 people
            try:
                brief = await self.brief_on_person(attendee, max_items=5)
                prep.attendee_briefs[attendee] = brief
            except Exception as e:
                logger.warning(f"Failed to brief on {attendee}: {e}")
        
        # Find related content by title/topic
        if self._services:
            # Extract keywords from title
            keywords = [w for w in title.lower().split() if len(w) > 3]
            
            try:
                # Search emails
                for kw in keywords[:2]:
                    emails = await self._services.email.search(kw, limit=5)
                    for email in emails:
                        prep.related_emails.append(RelevantContent(
                            content_type=ContentType.EMAIL,
                            title=email.get("subject", ""),
                            snippet=email.get("snippet", ""),
                            source=self._services.email.provider,
                            timestamp=self._parse_timestamp(email.get("date")),
                            relevance_reason=f"Contains '{kw}'",
                            raw=email,
                        ))
            except Exception as e:
                logger.warning(f"Email search failed: {e}")
            
            try:
                # Search documents
                for kw in keywords[:2]:
                    files = await self._services.files.search(kw, limit=5)
                    for file in files:
                        prep.related_documents.append(RelevantContent(
                            content_type=ContentType.DOCUMENT,
                            title=file.get("name", ""),
                            snippet=f"Modified: {file.get('modified', '')}",
                            source=self._services.files.provider,
                            timestamp=self._parse_timestamp(file.get("modified")),
                            relevance_reason=f"Contains '{kw}'",
                            raw=file,
                        ))
            except Exception as e:
                logger.warning(f"File search failed: {e}")
        
        # Search memory for relevant facts
        if self._memory:
            try:
                facts = await self._memory.recall(title, limit=10)
                prep.relevant_memories = [f.content for f in facts]
            except Exception as e:
                logger.warning(f"Memory recall failed: {e}")
        
        # Generate suggested discussion points
        prep.suggested_topics = self._suggest_discussion_points(prep)
        
        return prep
    
    def _suggest_discussion_points(self, prep: MeetingPrep) -> List[str]:
        """Suggest discussion points based on gathered content."""
        suggestions = []
        
        # From related emails - look for questions or action items
        for email in prep.related_emails[:3]:
            subject = email.title
            if "?" in subject:
                suggestions.append(f"Follow up on: {subject}")
        
        # From memory
        for memory in prep.relevant_memories[:3]:
            if "action" in memory.lower() or "todo" in memory.lower():
                suggestions.append(f"Review: {memory[:50]}...")
        
        # From pending tasks
        if prep.related_tasks:
            suggestions.append(f"Discuss {len(prep.related_tasks)} related tasks")
        
        return suggestions[:5]
    
    # =========================================================================
    # General Intelligence
    # =========================================================================
    
    async def find_related(
        self,
        query: str,
        content_types: List[ContentType] = None,
        max_items: int = 20,
    ) -> List[RelevantContent]:
        """
        Find content related to a topic across all services.
        
        Example:
            results = await intel.find_related("project apollo")
            # Returns emails, docs, meetings, tasks all about Apollo
        """
        content_types = content_types or [
            ContentType.EMAIL,
            ContentType.CALENDAR_EVENT,
            ContentType.DOCUMENT,
            ContentType.TASK,
            ContentType.MEMORY,
        ]
        
        results = []
        
        if ContentType.EMAIL in content_types and self._services:
            try:
                emails = await self._services.email.search(query, limit=max_items // 4)
                for email in emails:
                    results.append(RelevantContent(
                        content_type=ContentType.EMAIL,
                        title=email.get("subject", ""),
                        snippet=email.get("snippet", ""),
                        source=self._services.email.provider,
                        timestamp=self._parse_timestamp(email.get("date")),
                        relevance_score=0.8,
                        raw=email,
                    ))
            except:
                pass
        
        if ContentType.DOCUMENT in content_types and self._services:
            try:
                files = await self._services.files.search(query, limit=max_items // 4)
                for file in files:
                    results.append(RelevantContent(
                        content_type=ContentType.DOCUMENT,
                        title=file.get("name", ""),
                        snippet=f"Size: {file.get('size', 'Unknown')}",
                        source=self._services.files.provider,
                        timestamp=self._parse_timestamp(file.get("modified")),
                        relevance_score=0.7,
                        raw=file,
                    ))
            except:
                pass
        
        if ContentType.CALENDAR_EVENT in content_types and self._services:
            try:
                events = await self._services.calendar.list_events(
                    start=datetime.now() - timedelta(days=30),
                    end=datetime.now() + timedelta(days=30),
                    limit=50,
                )
                for event in events:
                    if query.lower() in event.get("title", "").lower():
                        results.append(RelevantContent(
                            content_type=ContentType.CALENDAR_EVENT,
                            title=event.get("title", ""),
                            snippet=event.get("description", "")[:200],
                            source=self._services.calendar.provider,
                            timestamp=self._parse_timestamp(event.get("start")),
                            relevance_score=0.9,
                            raw=event,
                        ))
            except:
                pass
        
        if ContentType.MEMORY in content_types and self._memory:
            try:
                facts = await self._memory.recall(query, limit=max_items // 4)
                for item in facts:
                    fact = item[0] if isinstance(item, tuple) else item
                    results.append(RelevantContent(
                        content_type=ContentType.MEMORY,
                        title="Memory",
                        snippet=fact.content,
                        source="semantic_memory",
                        timestamp=fact.created,
                        relevance_score=item[1] if isinstance(item, tuple) else 0.6,
                    ))
            except:
                pass
        
        # Sort by relevance
        return sorted(results, key=lambda x: x.relevance_score, reverse=True)[:max_items]
    
    async def get_composition_context(
        self,
        action: str,  # "email", "meeting", "document"
        recipient: str = None,
        topic: str = None,
    ) -> Dict:
        """
        Get context to help compose something.
        
        When writing an email to John about the budget:
        - How do you usually write to John? (formal/informal)
        - Previous emails about budget
        - John's preferences (from memory)
        - Relevant facts
        """
        context = {
            "tone_suggestion": "professional",
            "previous_interactions": [],
            "relevant_facts": [],
            "suggested_topics": [],
        }
        
        if recipient:
            brief = await self.brief_on_person(recipient, max_items=5)
            
            # Suggest tone based on relationship
            if brief.communication_frequency in ["daily", "weekly"]:
                context["tone_suggestion"] = "familiar"
            
            # Add recent interactions
            context["previous_interactions"] = [
                e.title for e in brief.recent_emails[:3]
            ]
            
            # Add known facts
            context["relevant_facts"] = brief.known_facts[:5]
        
        if topic:
            related = await self.find_related(topic, max_items=10)
            context["suggested_topics"] = [
                r.title for r in related if r.title
            ][:5]
        
        return context
    
    # =========================================================================
    # Utilities
    # =========================================================================
    
    async def morning_briefing(self) -> Dict:
        """Generate a morning briefing from available intelligence sources."""
        briefing = {
            "patterns": [],
            "memory_stats": {},
            "suggestions": [],
        }
        
        # Expected patterns
        if self._patterns:
            try:
                expected = await self._patterns.whats_expected_now(window_minutes=120)
                briefing["patterns"] = expected[:5]
            except Exception:
                pass
        
        # Memory stats
        if self._memory:
            try:
                briefing["memory_stats"] = self._memory.get_stats()
            except Exception:
                pass
        
        # Learned preferences
        if self._preferences:
            try:
                prefs = await self._preferences.get_preferences()
                briefing["preferences_count"] = len(prefs) if prefs else 0
            except Exception:
                pass
        
        return briefing
    
    def _parse_timestamp(self, ts: Any) -> Optional[datetime]:
        """Parse various timestamp formats."""
        if ts is None:
            return None
        
        if isinstance(ts, datetime):
            return ts
        
        if isinstance(ts, str):
            # Try ISO format
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except:
                pass
            
            # Try common formats
            for fmt in [
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
            ]:
                try:
                    return datetime.strptime(ts, fmt)
                except:
                    continue
        
        return None


# Singleton
_intel: Optional[CrossServiceIntelligence] = None

def get_cross_service_intelligence() -> CrossServiceIntelligence:
    """Get or create the cross-service intelligence singleton."""
    global _intel
    if _intel is None:
        _intel = CrossServiceIntelligence()
    return _intel
