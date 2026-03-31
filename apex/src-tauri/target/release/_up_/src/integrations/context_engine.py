"""
Context Engine for Apex Integration Platform

The "Brain" that connects everything:
- Entity recognition and relationship mapping
- Temporal awareness (what time means for the user)
- Cross-service context correlation
- Pattern learning from user behavior

This is what makes Apex DIFFERENT from simple automation tools.
"""

import asyncio
import logging
import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import re

from .event_bus import Event

logger = logging.getLogger(__name__)


class EntityType(Enum):
    """Types of entities the system recognizes."""
    PERSON = "person"
    ORGANIZATION = "organization"
    PROJECT = "project"
    DOCUMENT = "document"
    EVENT = "event"
    LOCATION = "location"
    TOPIC = "topic"
    UNKNOWN = "unknown"


class RelationshipType(Enum):
    """Types of relationships between entities."""
    WORKS_WITH = "works_with"
    BELONGS_TO = "belongs_to"
    RELATED_TO = "related_to"
    CREATED_BY = "created_by"
    MENTIONS = "mentions"
    SCHEDULED_WITH = "scheduled_with"


@dataclass
class Entity:
    """
    Represents a recognized entity in the user's data.
    
    Entities are extracted from emails, calendar events, documents, etc.
    and linked together to form a knowledge graph.
    """
    
    id: str
    name: str
    entity_type: EntityType
    
    # Entity details
    aliases: List[str] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)
    
    # Relationship tracking
    relationships: List[Dict[str, Any]] = field(default_factory=list)
    
    # Interaction history
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    interaction_count: int = 0
    
    # Context
    services_seen: Set[str] = field(default_factory=set)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "entity_type": self.entity_type.value,
            "aliases": self.aliases,
            "attributes": self.attributes,
            "relationships": self.relationships,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "interaction_count": self.interaction_count,
            "services_seen": list(self.services_seen),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Entity':
        """Deserialize from dictionary."""
        return cls(
            id=data["id"],
            name=data["name"],
            entity_type=EntityType(data["entity_type"]),
            aliases=data.get("aliases", []),
            attributes=data.get("attributes", {}),
            relationships=data.get("relationships", []),
            first_seen=datetime.fromisoformat(data["first_seen"]) if data.get("first_seen") else None,
            last_seen=datetime.fromisoformat(data["last_seen"]) if data.get("last_seen") else None,
            interaction_count=data.get("interaction_count", 0),
            services_seen=set(data.get("services_seen", [])),
        )


@dataclass
class TemporalContext:
    """
    Temporal awareness for context-aware processing.
    
    Understands what time means for the user:
    - Current time of day / week / year
    - User's typical patterns (work hours, focus time)
    - Upcoming deadlines and events
    - What's urgent vs can wait
    """
    
    # Current time context
    timestamp: datetime = field(default_factory=datetime.now)
    day_of_week: str = ""
    time_of_day: str = ""  # morning, afternoon, evening, night
    is_weekend: bool = False
    is_work_hours: bool = True
    
    # User patterns (learned)
    typical_work_start: str = "09:00"
    typical_work_end: str = "17:00"
    focus_times: List[Tuple[str, str]] = field(default_factory=list)
    
    # Upcoming context
    next_meeting: Optional[Dict[str, Any]] = None
    minutes_until_next_meeting: Optional[int] = None
    upcoming_deadlines: List[Dict[str, Any]] = field(default_factory=list)
    
    # Recent context
    last_user_activity: Optional[datetime] = None
    recent_services_used: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        """Calculate derived fields."""
        self.day_of_week = self.timestamp.strftime("%A")
        self.is_weekend = self.timestamp.weekday() >= 5
        
        hour = self.timestamp.hour
        if 5 <= hour < 12:
            self.time_of_day = "morning"
        elif 12 <= hour < 17:
            self.time_of_day = "afternoon"
        elif 17 <= hour < 21:
            self.time_of_day = "evening"
        else:
            self.time_of_day = "night"
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "day_of_week": self.day_of_week,
            "time_of_day": self.time_of_day,
            "is_weekend": self.is_weekend,
            "is_work_hours": self.is_work_hours,
            "next_meeting": self.next_meeting,
            "minutes_until_next_meeting": self.minutes_until_next_meeting,
            "upcoming_deadlines": self.upcoming_deadlines,
        }


class EntityExtractor:
    """
    Extract entities from various data types.
    
    Uses pattern matching and (optionally) LLM for entity extraction.
    """
    
    # Email pattern
    EMAIL_PATTERN = re.compile(r'[\w\.-]+@[\w\.-]+\.\w+')
    
    # Common name patterns
    NAME_PATTERN = re.compile(r'(?:From|To|Cc):\s*([^<\n]+?)(?:\s*<|$)', re.IGNORECASE)
    
    def __init__(self, use_llm: bool = False):
        self.use_llm = use_llm
    
    def extract_from_email(self, email_data: Dict[str, Any]) -> List[Entity]:
        """Extract entities from email data."""
        entities = []
        
        # Extract sender
        sender = email_data.get("from", "")
        if sender:
            entity = self._create_person_entity(sender)
            if entity:
                entities.append(entity)
        
        # Extract recipients
        for recipient in email_data.get("to", []):
            entity = self._create_person_entity(recipient)
            if entity:
                entities.append(entity)
        
        # Extract mentions from body
        body = email_data.get("body", "")
        mentioned_emails = self.EMAIL_PATTERN.findall(body)
        for email in mentioned_emails:
            entity = self._create_person_entity(email)
            if entity:
                entities.append(entity)
        
        return entities
    
    def extract_from_calendar(self, event_data: Dict[str, Any]) -> List[Entity]:
        """Extract entities from calendar event."""
        entities = []
        
        # Extract organizer
        organizer = event_data.get("organizer", {})
        if organizer:
            entity = self._create_person_entity(organizer.get("email"))
            if entity:
                entities.append(entity)
        
        # Extract attendees
        for attendee in event_data.get("attendees", []):
            entity = self._create_person_entity(attendee.get("email"))
            if entity:
                entities.append(entity)
        
        # Extract location as entity
        location = event_data.get("location")
        if location:
            entity = Entity(
                id=self._generate_id(f"location:{location}"),
                name=location,
                entity_type=EntityType.LOCATION,
            )
            entities.append(entity)
        
        return entities
    
    def _create_person_entity(self, identifier: str) -> Optional[Entity]:
        """Create a person entity from an email or name string."""
        if not identifier:
            return None
        
        # Extract email and name
        email_match = self.EMAIL_PATTERN.search(identifier)
        email = email_match.group() if email_match else None
        
        # Try to extract name
        name = identifier
        if "<" in identifier:
            name = identifier.split("<")[0].strip()
        elif email:
            # Use email prefix as name
            name = email.split("@")[0].replace(".", " ").title()
        
        if not name:
            return None
        
        return Entity(
            id=self._generate_id(f"person:{email or name}"),
            name=name,
            entity_type=EntityType.PERSON,
            aliases=[email] if email else [],
            attributes={"email": email} if email else {},
        )
    
    def _generate_id(self, identifier: str) -> str:
        """Generate a stable ID from an identifier."""
        return hashlib.sha256(identifier.lower().encode()).hexdigest()[:16]


class ContextEngine:
    """
    The brain of Apex - connects everything with context.
    
    Responsibilities:
    1. Entity extraction and graph building
    2. Temporal context awareness
    3. Cross-service correlation
    4. Event enrichment
    5. Pattern learning
    """
    
    def __init__(self, storage_path: Optional[Path] = None):
        """
        Initialize context engine.
        
        Args:
            storage_path: Where to store context data
        """
        self.storage_path = storage_path or Path.home() / ".apex" / "context"
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize database
        self.db_path = self.storage_path / "entities.db"
        self._init_database()
        
        # Entity extractor
        self.extractor = EntityExtractor()
        
        # In-memory entity cache
        self._entity_cache: Dict[str, Entity] = {}
        
        # Temporal context
        self._temporal = self._build_temporal_context()
        
        # Load entities
        self._load_entities()
    
    def _init_database(self):
        """Initialize SQLite database for entity storage."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Entities table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        
        # Relationships table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relationship_type TEXT NOT NULL,
                weight REAL DEFAULT 1.0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (source_id) REFERENCES entities(id),
                FOREIGN KEY (target_id) REFERENCES entities(id)
            )
        """)
        
        # Entity interactions (for temporal context)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id TEXT NOT NULL,
                service TEXT NOT NULL,
                event_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                data TEXT,
                FOREIGN KEY (entity_id) REFERENCES entities(id)
            )
        """)
        
        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_relationships_source ON relationships(source_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_relationships_target ON relationships(target_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_interactions_entity ON interactions(entity_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_interactions_time ON interactions(timestamp)")
        
        conn.commit()
        conn.close()
    
    def _load_entities(self):
        """Load entities from database into cache."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, data FROM entities")
        for row in cursor.fetchall():
            entity_id, data = row
            entity = Entity.from_dict(json.loads(data))
            self._entity_cache[entity_id] = entity
        
        conn.close()
        logger.info(f"Loaded {len(self._entity_cache)} entities from database")
    
    def _save_entity(self, entity: Entity):
        """Save entity to database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        now = datetime.now().isoformat()
        data = json.dumps(entity.to_dict())
        
        cursor.execute("""
            INSERT OR REPLACE INTO entities (id, name, entity_type, data, created_at, updated_at)
            VALUES (?, ?, ?, ?, COALESCE((SELECT created_at FROM entities WHERE id = ?), ?), ?)
        """, (entity.id, entity.name, entity.entity_type.value, data, entity.id, now, now))
        
        conn.commit()
        conn.close()
        
        # Update cache
        self._entity_cache[entity.id] = entity
    
    def _build_temporal_context(self) -> TemporalContext:
        """Build current temporal context."""
        return TemporalContext()
    
    # === Entity Management ===
    
    def get_entity(self, entity_id: str) -> Optional[Entity]:
        """Get entity by ID."""
        return self._entity_cache.get(entity_id)
    
    def find_entity_by_attribute(self, key: str, value: str) -> Optional[Entity]:
        """Find entity by attribute value."""
        for entity in self._entity_cache.values():
            if entity.attributes.get(key) == value:
                return entity
            if key == "email" and value in entity.aliases:
                return entity
        return None
    
    def search_entities(
        self,
        query: str,
        entity_type: Optional[EntityType] = None,
        limit: int = 10,
    ) -> List[Entity]:
        """Search entities by name or alias."""
        results = []
        query_lower = query.lower()
        
        for entity in self._entity_cache.values():
            if entity_type and entity.entity_type != entity_type:
                continue
            
            # Check name and aliases
            if query_lower in entity.name.lower():
                results.append(entity)
            elif any(query_lower in alias.lower() for alias in entity.aliases):
                results.append(entity)
        
        # Sort by interaction count (most interacted first)
        results.sort(key=lambda e: e.interaction_count, reverse=True)
        
        return results[:limit]
    
    def add_or_update_entity(self, entity: Entity) -> Entity:
        """Add new entity or update existing one."""
        existing = self._entity_cache.get(entity.id)
        
        if existing:
            # Merge data
            existing.aliases = list(set(existing.aliases + entity.aliases))
            existing.attributes.update(entity.attributes)
            existing.services_seen.update(entity.services_seen)
            existing.interaction_count += 1
            existing.last_seen = datetime.now()
            entity = existing
        else:
            entity.first_seen = datetime.now()
            entity.last_seen = datetime.now()
            entity.interaction_count = 1
        
        self._save_entity(entity)
        return entity
    
    def add_relationship(
        self,
        source_id: str,
        target_id: str,
        relationship_type: RelationshipType,
        weight: float = 1.0,
    ):
        """Add relationship between entities."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO relationships (source_id, target_id, relationship_type, weight, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (source_id, target_id, relationship_type.value, weight, datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
    
    def get_related_entities(self, entity_id: str, limit: int = 10) -> List[Tuple[Entity, str, float]]:
        """Get entities related to a given entity."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get both directions of relationships
        cursor.execute("""
            SELECT target_id, relationship_type, SUM(weight) as total_weight
            FROM relationships
            WHERE source_id = ?
            GROUP BY target_id
            UNION ALL
            SELECT source_id, relationship_type, SUM(weight) as total_weight
            FROM relationships
            WHERE target_id = ?
            GROUP BY source_id
            ORDER BY total_weight DESC
            LIMIT ?
        """, (entity_id, entity_id, limit))
        
        results = []
        for row in cursor.fetchall():
            related_id, rel_type, weight = row
            entity = self.get_entity(related_id)
            if entity:
                results.append((entity, rel_type, weight))
        
        conn.close()
        return results
    
    # === Event Enrichment ===
    
    async def enrich_event(self, event: Event) -> Event:
        """
        Enrich an event with contextual information.
        
        This is the core of the context engine - taking a raw event
        and adding understanding from:
        - Entity recognition
        - Temporal context
        - Related items from other services
        - Suggested actions
        """
        event.add_processing_step("context_enrichment_start")
        
        # 1. Extract and record entities
        entities = self._extract_entities_from_event(event)
        for entity in entities:
            entity.services_seen.add(event.service)
            self.add_or_update_entity(entity)
        
        event.entities = [e.to_dict() for e in entities]
        
        # 2. Add temporal context
        event.temporal_context = self._temporal.to_dict()
        
        # 3. Find related items
        event.related_items = await self._find_related_items(event, entities)
        
        # 4. Suggest actions based on context
        event.suggested_actions = await self._suggest_actions(event, entities)
        
        event.add_processing_step("context_enrichment_complete")
        
        return event
    
    def _extract_entities_from_event(self, event: Event) -> List[Entity]:
        """Extract entities based on event type."""
        if event.service == "gmail":
            return self.extractor.extract_from_email(event.data)
        elif event.service == "calendar":
            return self.extractor.extract_from_calendar(event.data)
        # Add more extractors as needed
        return []
    
    async def _find_related_items(
        self,
        event: Event,
        entities: List[Entity],
    ) -> List[Dict[str, Any]]:
        """Find items related to this event from other services."""
        related = []
        
        # For each entity, find recent interactions
        for entity in entities:
            related_entities = self.get_related_entities(entity.id, limit=5)
            for rel_entity, rel_type, weight in related_entities:
                related.append({
                    "type": "entity_relation",
                    "entity": rel_entity.to_dict(),
                    "relationship": rel_type,
                    "relevance": weight,
                })
        
        # Find recent items from the same context
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get recent interactions for involved entities
        entity_ids = [e.id for e in entities]
        if entity_ids:
            placeholders = ",".join("?" * len(entity_ids))
            cursor.execute(f"""
                SELECT service, event_type, data, timestamp
                FROM interactions
                WHERE entity_id IN ({placeholders})
                ORDER BY timestamp DESC
                LIMIT 10
            """, entity_ids)
            
            for row in cursor.fetchall():
                service, evt_type, data, timestamp = row
                if service != event.service:  # Cross-service correlation
                    related.append({
                        "type": "recent_interaction",
                        "service": service,
                        "event_type": evt_type,
                        "data": json.loads(data) if data else {},
                        "timestamp": timestamp,
                    })
        
        conn.close()
        return related
    
    async def _suggest_actions(
        self,
        event: Event,
        entities: List[Entity],
    ) -> List[Dict[str, Any]]:
        """Suggest actions based on event context."""
        suggestions = []
        
        # Email-specific suggestions
        if event.service == "gmail" and event.event_type == "email.received":
            # Check for calendar-related content
            body = event.data.get("body", "").lower()
            subject = event.data.get("subject", "").lower()
            
            if any(word in body + subject for word in ["meeting", "schedule", "calendar", "appointment"]):
                suggestions.append({
                    "action": "create_calendar_event",
                    "reason": "Email mentions scheduling",
                    "confidence": 0.7,
                })
            
            if any(word in body + subject for word in ["deadline", "due", "submit by"]):
                suggestions.append({
                    "action": "create_reminder",
                    "reason": "Email mentions deadline",
                    "confidence": 0.8,
                })
            
            # Check for attachment mentions
            if "attachment" in body or "attached" in body:
                if not event.data.get("attachments"):
                    suggestions.append({
                        "action": "check_missing_attachment",
                        "reason": "Email mentions attachment but none found",
                        "confidence": 0.9,
                    })
        
        # Calendar-specific suggestions
        if event.service == "calendar" and event.event_type == "event.created":
            # Suggest travel time if location is set
            if event.data.get("location"):
                suggestions.append({
                    "action": "add_travel_time",
                    "reason": "Event has a location",
                    "confidence": 0.6,
                })
            
            # Suggest prep time for meetings
            attendees = event.data.get("attendees", [])
            if len(attendees) > 2:
                suggestions.append({
                    "action": "add_prep_time",
                    "reason": "Multi-person meeting",
                    "confidence": 0.7,
                })
        
        return suggestions
    
    def record_interaction(
        self,
        entity_id: str,
        service: str,
        event_type: str,
        data: Optional[Dict[str, Any]] = None,
    ):
        """Record an interaction with an entity."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO interactions (entity_id, service, event_type, timestamp, data)
            VALUES (?, ?, ?, ?, ?)
        """, (entity_id, service, event_type, datetime.now().isoformat(), json.dumps(data) if data else None))
        
        conn.commit()
        conn.close()
    
    # === Temporal Context ===
    
    def get_temporal_context(self) -> TemporalContext:
        """Get current temporal context."""
        self._temporal = self._build_temporal_context()
        return self._temporal
    
    def set_user_patterns(
        self,
        work_start: Optional[str] = None,
        work_end: Optional[str] = None,
        focus_times: Optional[List[Tuple[str, str]]] = None,
    ):
        """Update user's temporal patterns."""
        if work_start:
            self._temporal.typical_work_start = work_start
        if work_end:
            self._temporal.typical_work_end = work_end
        if focus_times:
            self._temporal.focus_times = focus_times
    
    # === Statistics and Queries ===
    
    def get_stats(self) -> Dict[str, Any]:
        """Get context engine statistics."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM entities")
        entity_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM relationships")
        relationship_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM interactions")
        interaction_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT entity_type, COUNT(*) FROM entities GROUP BY entity_type")
        type_counts = dict(cursor.fetchall())
        
        conn.close()
        
        return {
            "total_entities": entity_count,
            "total_relationships": relationship_count,
            "total_interactions": interaction_count,
            "entity_types": type_counts,
            "cached_entities": len(self._entity_cache),
        }
    
    def get_most_interacted_entities(self, limit: int = 10) -> List[Entity]:
        """Get entities with most interactions."""
        entities = list(self._entity_cache.values())
        entities.sort(key=lambda e: e.interaction_count, reverse=True)
        return entities[:limit]


# Singleton instance
_context_engine: Optional[ContextEngine] = None

def get_context_engine() -> ContextEngine:
    """Get or create the context engine singleton."""
    global _context_engine
    if _context_engine is None:
        _context_engine = ContextEngine()
    return _context_engine
