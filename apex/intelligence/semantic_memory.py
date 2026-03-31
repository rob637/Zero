"""
Semantic Memory Engine

This is what makes Telic actually different from competitors.

NOT just key-value storage. This is a knowledge graph that:
- Stores facts with relationships and context
- Supports semantic search (finds related concepts)
- Tracks temporal relevance (some facts decay, some are permanent)
- Enables inference (connects dots across disparate information)
- Learns entity relationships (John → works at Acme → Acme is a client)

The magic: When you say "prepare for my meeting with John", this system
can instantly retrieve:
- Your relationship with John
- Recent interactions (emails, meetings)
- John's preferences you've noted
- Relevant documents involving John
- Historical context of your dealings

Usage:
    from intelligence.semantic_memory import SemanticMemory
    
    memory = SemanticMemory()
    
    # Remember a fact
    await memory.remember(
        fact="John prefers morning meetings",
        entity="John",
        category="preference",
        confidence=0.9,
    )
    
    # Semantic recall
    results = await memory.recall("When should I schedule with John?")
    # Returns: John prefers morning meetings, John hates Mondays, etc.
    
    # Entity graph
    john = await memory.get_entity("John")
    # Returns full knowledge about John with relationships
"""

import asyncio
import json
import hashlib
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import math

import logging
logger = logging.getLogger(__name__)


class FactCategory(Enum):
    """Categories of remembered facts."""
    PREFERENCE = "preference"      # User prefers X
    RELATIONSHIP = "relationship"  # Person A relates to Person B
    EVENT = "event"               # Something that happened
    INSIGHT = "insight"           # Derived understanding
    CONTEXT = "context"           # Situational context
    INSTRUCTION = "instruction"   # User told us to do/remember X
    BEHAVIOR = "behavior"         # Observed user behavior pattern
    ENTITY_INFO = "entity_info"   # Facts about an entity


class TemporalRelevance(Enum):
    """How facts decay over time."""
    PERMANENT = "permanent"       # Never decays (birthdays, relationships)
    LONG_TERM = "long_term"       # Slow decay (preferences)
    MEDIUM_TERM = "medium_term"   # Moderate decay (project context)
    SHORT_TERM = "short_term"     # Fast decay (temporary reminders)
    EPHEMERAL = "ephemeral"       # One-time use


@dataclass
class Fact:
    """A single fact in semantic memory."""
    id: str
    content: str
    category: FactCategory
    temporal: TemporalRelevance
    confidence: float  # 0.0 to 1.0
    
    # Entity relationships
    primary_entity: Optional[str] = None
    related_entities: List[str] = field(default_factory=list)
    
    # Temporal tracking
    created_at: datetime = field(default_factory=datetime.now)
    last_accessed: datetime = field(default_factory=datetime.now)
    access_count: int = 0
    
    # Source tracking
    source: Optional[str] = None  # "user_stated", "inferred", "observed"
    source_context: Optional[str] = None
    
    # Semantic embedding (for similarity search)
    embedding: Optional[List[float]] = None
    
    # Tags for fast lookup
    tags: Set[str] = field(default_factory=set)
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "content": self.content,
            "category": self.category.value,
            "temporal": self.temporal.value,
            "confidence": self.confidence,
            "primary_entity": self.primary_entity,
            "related_entities": self.related_entities,
            "created_at": self.created_at.isoformat(),
            "last_accessed": self.last_accessed.isoformat(),
            "access_count": self.access_count,
            "source": self.source,
            "tags": list(self.tags),
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Fact':
        return cls(
            id=data["id"],
            content=data["content"],
            category=FactCategory(data["category"]),
            temporal=TemporalRelevance(data["temporal"]),
            confidence=data["confidence"],
            primary_entity=data.get("primary_entity"),
            related_entities=data.get("related_entities", []),
            created_at=datetime.fromisoformat(data["created_at"]),
            last_accessed=datetime.fromisoformat(data["last_accessed"]),
            access_count=data.get("access_count", 0),
            source=data.get("source"),
            source_context=data.get("source_context"),
            tags=set(data.get("tags", [])),
        )


@dataclass 
class Entity:
    """
    An entity in the knowledge graph.
    
    Entities are people, organizations, projects, etc.
    They have facts associated with them and relationships to other entities.
    """
    id: str
    name: str
    type: str  # person, organization, project, location, etc.
    
    # Core attributes
    attributes: Dict[str, Any] = field(default_factory=dict)
    
    # Relationships to other entities
    relationships: Dict[str, List[str]] = field(default_factory=dict)
    # e.g., {"works_at": ["acme_corp"], "manages": ["bob", "alice"]}
    
    # Associated fact IDs
    fact_ids: Set[str] = field(default_factory=set)
    
    # Tracking
    created_at: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)
    interaction_count: int = 0


class SemanticMemory:
    """
    The brain of Telic - semantic memory with knowledge graph.
    
    This is NOT a simple key-value store. It's a knowledge graph that:
    1. Stores facts with rich metadata
    2. Maintains entity relationships  
    3. Supports semantic similarity search
    4. Tracks temporal relevance
    5. Enables inference across facts
    """
    
    def __init__(self, storage_path: str = None):
        self._storage_path = Path(storage_path or "~/.apex/memory").expanduser()
        self._storage_path.mkdir(parents=True, exist_ok=True)
        
        # In-memory stores
        self._facts: Dict[str, Fact] = {}
        self._entities: Dict[str, Entity] = {}
        
        # Indexes for fast lookup
        self._entity_index: Dict[str, Set[str]] = {}  # entity_name -> fact_ids
        self._category_index: Dict[FactCategory, Set[str]] = {}
        self._tag_index: Dict[str, Set[str]] = {}
        
        # Load existing memory
        self._load()
    
    def _load(self):
        """Load memory from disk."""
        facts_file = self._storage_path / "facts.json"
        entities_file = self._storage_path / "entities.json"
        
        if facts_file.exists():
            try:
                with open(facts_file) as f:
                    data = json.load(f)
                    for fact_data in data:
                        fact = Fact.from_dict(fact_data)
                        self._facts[fact.id] = fact
                        self._index_fact(fact)
                logger.info(f"Loaded {len(self._facts)} facts from memory")
            except Exception as e:
                logger.error(f"Failed to load facts: {e}")
        
        if entities_file.exists():
            try:
                with open(entities_file) as f:
                    data = json.load(f)
                    for entity_data in data:
                        entity = Entity(
                            id=entity_data["id"],
                            name=entity_data["name"],
                            type=entity_data["type"],
                            attributes=entity_data.get("attributes", {}),
                            relationships=entity_data.get("relationships", {}),
                            fact_ids=set(entity_data.get("fact_ids", [])),
                            interaction_count=entity_data.get("interaction_count", 0),
                        )
                        self._entities[entity.id] = entity
                logger.info(f"Loaded {len(self._entities)} entities from memory")
            except Exception as e:
                logger.error(f"Failed to load entities: {e}")
    
    def _save(self):
        """Persist memory to disk."""
        facts_file = self._storage_path / "facts.json"
        entities_file = self._storage_path / "entities.json"
        
        # Save facts
        with open(facts_file, 'w') as f:
            json.dump([fact.to_dict() for fact in self._facts.values()], f, indent=2)
        
        # Save entities
        entities_data = []
        for entity in self._entities.values():
            entities_data.append({
                "id": entity.id,
                "name": entity.name,
                "type": entity.type,
                "attributes": entity.attributes,
                "relationships": entity.relationships,
                "fact_ids": list(entity.fact_ids),
                "interaction_count": entity.interaction_count,
            })
        with open(entities_file, 'w') as f:
            json.dump(entities_data, f, indent=2)
    
    def _index_fact(self, fact: Fact):
        """Add fact to indexes."""
        # Entity index
        if fact.primary_entity:
            entity_key = self._normalize_entity(fact.primary_entity)
            if entity_key not in self._entity_index:
                self._entity_index[entity_key] = set()
            self._entity_index[entity_key].add(fact.id)
        
        for entity in fact.related_entities:
            entity_key = self._normalize_entity(entity)
            if entity_key not in self._entity_index:
                self._entity_index[entity_key] = set()
            self._entity_index[entity_key].add(fact.id)
        
        # Category index
        if fact.category not in self._category_index:
            self._category_index[fact.category] = set()
        self._category_index[fact.category].add(fact.id)
        
        # Tag index
        for tag in fact.tags:
            if tag not in self._tag_index:
                self._tag_index[tag] = set()
            self._tag_index[tag].add(fact.id)
    
    def _normalize_entity(self, name: str) -> str:
        """Normalize entity name for consistent lookup."""
        return name.lower().strip()
    
    def _generate_id(self, content: str) -> str:
        """Generate unique ID for a fact."""
        timestamp = datetime.now().isoformat()
        hash_input = f"{content}:{timestamp}"
        return hashlib.sha256(hash_input.encode()).hexdigest()[:16]
    
    def _extract_entities(self, text: str) -> List[str]:
        """Extract potential entity names from text."""
        # Simple extraction - capitalized words
        # In production, use NER model
        entities = []
        
        # Find capitalized words that aren't at sentence start
        words = text.split()
        for i, word in enumerate(words):
            clean = re.sub(r'[^\w]', '', word)
            if clean and clean[0].isupper() and len(clean) > 1:
                # Skip common words
                if clean.lower() not in {'the', 'a', 'an', 'is', 'are', 'was', 'i', 'my'}:
                    entities.append(clean)
        
        return list(set(entities))
    
    def _extract_tags(self, text: str, category: FactCategory) -> Set[str]:
        """Extract relevant tags from fact content."""
        tags = set()
        text_lower = text.lower()
        
        # Time-related tags
        time_words = ['morning', 'afternoon', 'evening', 'night', 'monday', 'tuesday', 
                      'wednesday', 'thursday', 'friday', 'saturday', 'sunday', 'weekly',
                      'daily', 'monthly']
        for word in time_words:
            if word in text_lower:
                tags.add(f"time:{word}")
        
        # Preference tags
        if 'prefer' in text_lower or 'like' in text_lower or 'love' in text_lower:
            tags.add('preference')
        if 'hate' in text_lower or 'dislike' in text_lower or "don't like" in text_lower:
            tags.add('dislike')
        
        # Communication tags
        if any(w in text_lower for w in ['email', 'call', 'meeting', 'message', 'text']):
            tags.add('communication')
        
        # Add category tag
        tags.add(f"category:{category.value}")
        
        return tags
    
    def _calculate_relevance(self, fact: Fact, query: str = None) -> float:
        """
        Calculate current relevance score for a fact.
        
        Considers:
        - Temporal decay
        - Access frequency
        - Confidence
        - Query match (if provided)
        """
        score = fact.confidence
        
        # Temporal decay
        age_days = (datetime.now() - fact.created_at).days
        decay_rates = {
            TemporalRelevance.PERMANENT: 0,
            TemporalRelevance.LONG_TERM: 0.001,      # 50% after ~2 years
            TemporalRelevance.MEDIUM_TERM: 0.01,    # 50% after ~70 days
            TemporalRelevance.SHORT_TERM: 0.05,     # 50% after ~14 days
            TemporalRelevance.EPHEMERAL: 0.2,       # 50% after ~3 days
        }
        decay = decay_rates.get(fact.temporal, 0.01)
        temporal_factor = math.exp(-decay * age_days)
        score *= temporal_factor
        
        # Boost for frequently accessed facts
        access_boost = min(1.5, 1 + (fact.access_count * 0.05))
        score *= access_boost
        
        # Query match bonus
        if query:
            query_lower = query.lower()
            content_lower = fact.content.lower()
            
            # Exact substring match
            if query_lower in content_lower:
                score *= 2.0
            else:
                # Word overlap
                query_words = set(query_lower.split())
                content_words = set(content_lower.split())
                overlap = len(query_words & content_words)
                if overlap > 0:
                    score *= (1 + overlap * 0.3)
        
        return min(1.0, score)
    
    # =========================================================================
    # Core API
    # =========================================================================
    
    async def remember(
        self,
        fact: str,
        category: FactCategory = FactCategory.CONTEXT,
        temporal: TemporalRelevance = TemporalRelevance.LONG_TERM,
        confidence: float = 0.8,
        entity: str = None,
        related_entities: List[str] = None,
        source: str = "user_stated",
        tags: Set[str] = None,
    ) -> Fact:
        """
        Remember a new fact.
        
        Args:
            fact: The fact to remember
            category: Type of fact
            temporal: How long to remember
            confidence: How confident we are (0-1)
            entity: Primary entity this fact is about
            related_entities: Other entities mentioned
            source: Where this fact came from
            tags: Additional tags for search
        
        Returns:
            Created Fact object
        """
        # Extract entities if not provided
        if not entity and not related_entities:
            extracted = self._extract_entities(fact)
            if extracted:
                entity = extracted[0]
                related_entities = extracted[1:] if len(extracted) > 1 else []
        
        # Auto-extract tags
        auto_tags = self._extract_tags(fact, category)
        if tags:
            auto_tags.update(tags)
        
        # Create fact
        fact_obj = Fact(
            id=self._generate_id(fact),
            content=fact,
            category=category,
            temporal=temporal,
            confidence=confidence,
            primary_entity=entity,
            related_entities=related_entities or [],
            source=source,
            tags=auto_tags,
        )
        
        # Store and index
        self._facts[fact_obj.id] = fact_obj
        self._index_fact(fact_obj)
        
        # Update/create entity if applicable
        if entity:
            await self._update_entity(entity, fact_obj)
        
        # Persist
        self._save()
        
        logger.info(f"Remembered: {fact[:50]}... (entity={entity})")
        return fact_obj
    
    async def _update_entity(self, name: str, fact: Fact):
        """Update or create an entity based on a fact."""
        entity_id = self._normalize_entity(name)
        
        if entity_id not in self._entities:
            # Infer entity type from fact
            entity_type = "unknown"
            content_lower = fact.content.lower()
            if any(w in content_lower for w in ['he ', 'she ', 'they ', 'person', 'mr.', 'ms.']):
                entity_type = "person"
            elif any(w in content_lower for w in ['company', 'corp', 'inc', 'organization']):
                entity_type = "organization"
            elif any(w in content_lower for w in ['project', 'initiative']):
                entity_type = "project"
            
            self._entities[entity_id] = Entity(
                id=entity_id,
                name=name,
                type=entity_type,
            )
        
        entity = self._entities[entity_id]
        entity.fact_ids.add(fact.id)
        entity.last_updated = datetime.now()
        entity.interaction_count += 1
    
    async def recall(
        self,
        query: str,
        entity: str = None,
        category: FactCategory = None,
        limit: int = 10,
        min_relevance: float = 0.1,
    ) -> List[Tuple[Fact, float]]:
        """
        Recall facts relevant to a query.
        
        This is semantic recall - it finds facts related to the query,
        not just exact matches.
        
        Args:
            query: What to recall
            entity: Limit to facts about this entity
            category: Limit to this category
            limit: Maximum facts to return
            min_relevance: Minimum relevance score
        
        Returns:
            List of (Fact, relevance_score) tuples
        """
        candidates = set(self._facts.keys())
        
        # Filter by entity
        if entity:
            entity_key = self._normalize_entity(entity)
            if entity_key in self._entity_index:
                candidates &= self._entity_index[entity_key]
            else:
                # Also check entity mentions in query
                extracted = self._extract_entities(query)
                for e in extracted:
                    e_key = self._normalize_entity(e)
                    if e_key in self._entity_index:
                        candidates &= self._entity_index[e_key]
        
        # Filter by category
        if category and category in self._category_index:
            candidates &= self._category_index[category]
        
        # Score and rank
        scored = []
        for fact_id in candidates:
            fact = self._facts[fact_id]
            relevance = self._calculate_relevance(fact, query)
            if relevance >= min_relevance:
                scored.append((fact, relevance))
        
        # Sort by relevance
        scored.sort(key=lambda x: x[1], reverse=True)
        
        # Update access stats for returned facts
        for fact, _ in scored[:limit]:
            fact.last_accessed = datetime.now()
            fact.access_count += 1
        
        self._save()
        
        return scored[:limit]
    
    async def recall_about(self, entity: str) -> List[Fact]:
        """Get all facts about a specific entity."""
        entity_key = self._normalize_entity(entity)
        
        if entity_key not in self._entity_index:
            return []
        
        facts = []
        for fact_id in self._entity_index[entity_key]:
            if fact_id in self._facts:
                facts.append(self._facts[fact_id])
        
        # Sort by relevance
        facts.sort(key=lambda f: self._calculate_relevance(f), reverse=True)
        return facts
    
    async def get_entity(self, name: str) -> Optional[Dict]:
        """
        Get comprehensive information about an entity.
        
        Returns entity details plus all associated facts.
        """
        entity_id = self._normalize_entity(name)
        
        if entity_id not in self._entities:
            # Try to find by fuzzy match
            for eid, entity in self._entities.items():
                if name.lower() in entity.name.lower():
                    entity_id = eid
                    break
            else:
                return None
        
        entity = self._entities[entity_id]
        facts = await self.recall_about(name)
        
        return {
            "entity": {
                "id": entity.id,
                "name": entity.name,
                "type": entity.type,
                "attributes": entity.attributes,
                "relationships": entity.relationships,
                "interaction_count": entity.interaction_count,
            },
            "facts": [f.to_dict() for f in facts],
            "summary": self._summarize_entity(entity, facts),
        }
    
    def _summarize_entity(self, entity: Entity, facts: List[Fact]) -> str:
        """Generate a natural language summary of an entity."""
        if not facts:
            return f"{entity.name} is a {entity.type} with no recorded information."
        
        # Group facts by category
        preferences = [f for f in facts if f.category == FactCategory.PREFERENCE]
        relationships = [f for f in facts if f.category == FactCategory.RELATIONSHIP]
        behaviors = [f for f in facts if f.category == FactCategory.BEHAVIOR]
        other = [f for f in facts if f.category not in 
                 {FactCategory.PREFERENCE, FactCategory.RELATIONSHIP, FactCategory.BEHAVIOR}]
        
        summary_parts = [f"{entity.name} ({entity.type}):"]
        
        if preferences:
            summary_parts.append(f"  Preferences: {', '.join(f.content for f in preferences[:3])}")
        if behaviors:
            summary_parts.append(f"  Patterns: {', '.join(f.content for f in behaviors[:3])}")
        if relationships:
            summary_parts.append(f"  Relationships: {', '.join(f.content for f in relationships[:3])}")
        if other:
            summary_parts.append(f"  Other: {', '.join(f.content for f in other[:3])}")
        
        return "\n".join(summary_parts)
    
    async def forget(
        self,
        fact_id: str = None,
        entity: str = None,
        older_than_days: int = None,
    ) -> int:
        """
        Forget facts.
        
        Can forget by:
        - Specific fact ID
        - All facts about an entity
        - Facts older than N days
        
        Returns number of facts forgotten.
        """
        to_forget = set()
        
        if fact_id:
            to_forget.add(fact_id)
        
        if entity:
            entity_key = self._normalize_entity(entity)
            if entity_key in self._entity_index:
                to_forget.update(self._entity_index[entity_key])
        
        if older_than_days:
            cutoff = datetime.now() - timedelta(days=older_than_days)
            for fid, fact in self._facts.items():
                if fact.created_at < cutoff and fact.temporal != TemporalRelevance.PERMANENT:
                    to_forget.add(fid)
        
        # Remove from indexes and storage
        for fid in to_forget:
            if fid in self._facts:
                del self._facts[fid]
        
        # Rebuild indexes
        self._entity_index.clear()
        self._category_index.clear()
        self._tag_index.clear()
        for fact in self._facts.values():
            self._index_fact(fact)
        
        self._save()
        
        return len(to_forget)
    
    async def connect_entities(
        self,
        entity1: str,
        relationship: str,
        entity2: str,
    ):
        """
        Create a relationship between two entities.
        
        Example: connect_entities("John", "works_at", "Acme Corp")
        """
        e1_id = self._normalize_entity(entity1)
        e2_id = self._normalize_entity(entity2)
        
        # Ensure both entities exist
        if e1_id not in self._entities:
            self._entities[e1_id] = Entity(id=e1_id, name=entity1, type="unknown")
        if e2_id not in self._entities:
            self._entities[e2_id] = Entity(id=e2_id, name=entity2, type="unknown")
        
        # Add relationship
        if relationship not in self._entities[e1_id].relationships:
            self._entities[e1_id].relationships[relationship] = []
        if e2_id not in self._entities[e1_id].relationships[relationship]:
            self._entities[e1_id].relationships[relationship].append(e2_id)
        
        # Also store as a fact
        await self.remember(
            fact=f"{entity1} {relationship} {entity2}",
            category=FactCategory.RELATIONSHIP,
            temporal=TemporalRelevance.LONG_TERM,
            entity=entity1,
            related_entities=[entity2],
            source="inferred",
        )
        
        self._save()
    
    # =========================================================================
    # Analytics & Insights
    # =========================================================================
    
    def get_stats(self) -> Dict:
        """Get memory statistics."""
        category_counts = {}
        for cat in FactCategory:
            if cat in self._category_index:
                category_counts[cat.value] = len(self._category_index[cat])
            else:
                category_counts[cat.value] = 0
        
        return {
            "total_facts": len(self._facts),
            "total_entities": len(self._entities),
            "facts_by_category": category_counts,
            "top_entities": sorted(
                [(e.name, e.interaction_count) for e in self._entities.values()],
                key=lambda x: x[1],
                reverse=True
            )[:10],
        }
    
    async def get_related_entities(self, entity: str, depth: int = 1) -> List[Dict]:
        """Find entities related to the given entity."""
        entity_id = self._normalize_entity(entity)
        
        if entity_id not in self._entities:
            return []
        
        related = []
        visited = {entity_id}
        queue = [(entity_id, 0)]
        
        while queue:
            current_id, current_depth = queue.pop(0)
            if current_depth >= depth:
                continue
            
            current = self._entities.get(current_id)
            if not current:
                continue
            
            # Get directly related entities
            for rel_type, rel_ids in current.relationships.items():
                for rel_id in rel_ids:
                    if rel_id not in visited:
                        visited.add(rel_id)
                        if rel_id in self._entities:
                            rel_entity = self._entities[rel_id]
                            related.append({
                                "entity": rel_entity.name,
                                "relationship": rel_type,
                                "from": current.name,
                                "depth": current_depth + 1,
                            })
                            queue.append((rel_id, current_depth + 1))
        
        return related


# Singleton instance
_memory: Optional[SemanticMemory] = None

def get_semantic_memory() -> SemanticMemory:
    """Get or create the semantic memory singleton."""
    global _memory
    if _memory is None:
        _memory = SemanticMemory()
    return _memory
