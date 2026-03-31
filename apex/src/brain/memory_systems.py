"""
Memory Systems - The storage that makes a mind.

Human memory isn't a database. It's:
- Associative (things link to related things)
- Reconstructive (we rebuild memories, not replay them)
- Decaying (old things fade unless rehearsed)
- Consolidating (important things get strengthened)
- Emotional (feelings enhance encoding)

This implements five memory systems:

1. WORKING MEMORY
   - Limited capacity (~7 items)
   - Current focus of attention
   - Decays in seconds without rehearsal
   - The "stage" where thinking happens

2. EPISODIC MEMORY  
   - Autobiographical events
   - Time-stamped, contextualized
   - "What happened" memories
   - Enables learning from experience

3. SEMANTIC MEMORY
   - Facts, concepts, relationships
   - Decontextualized knowledge
   - "What I know" memories
   - Forms the knowledge graph

4. PROCEDURAL MEMORY
   - Skills and procedures
   - "How to do things"
   - Learned through repetition
   - Enables automatic behavior

5. PREDICTIVE MEMORY
   - Patterns and expectations
   - "What usually happens"
   - Enables anticipation
   - Updated through surprise
"""

import asyncio
import hashlib
import json
import logging
import math
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import numpy as np

logger = logging.getLogger(__name__)


# ============================================
# Memory Primitives
# ============================================

class MemoryStrength(Enum):
    """How strongly encoded a memory is."""
    FLEETING = 1      # Will fade in minutes
    WEAK = 2          # Will fade in hours
    MODERATE = 3      # Will persist days
    STRONG = 4        # Will persist weeks
    PERMANENT = 5     # Core knowledge


@dataclass
class MemoryTrace:
    """
    A single memory trace - the fundamental unit of storage.
    
    Memories have:
    - Content: What is remembered
    - Strength: How well encoded
    - Activation: Current accessibility
    - Last access: For decay calculation
    - Emotional valence: Importance weight
    """
    id: str
    content: Dict[str, Any]
    strength: float = 1.0           # 0-10 scale
    activation: float = 1.0         # Current accessibility (decays)
    created_at: datetime = field(default_factory=datetime.now)
    last_accessed: datetime = field(default_factory=datetime.now)
    access_count: int = 0
    emotional_valence: float = 0.0  # -1 to 1 (negative to positive)
    importance: float = 0.5         # 0-1 scale
    embedding: Optional[List[float]] = None  # Semantic vector
    associations: Set[str] = field(default_factory=set)  # Links to other traces
    
    def decay(self, hours_passed: float) -> float:
        """
        Apply memory decay following Ebbinghaus forgetting curve.
        R = e^(-t/S) where S is stability (strength)
        """
        stability = self.strength + 1  # Prevent division issues
        decay_factor = math.exp(-hours_passed / (stability * 24))  # Scale to days
        self.activation *= decay_factor
        return self.activation
    
    def reinforce(self, amount: float = 0.1):
        """Strengthen memory through rehearsal/access."""
        self.access_count += 1
        self.last_accessed = datetime.now()
        # Spaced repetition: bigger boost if time has passed
        hours_since = (datetime.now() - self.last_accessed).total_seconds() / 3600
        spacing_bonus = min(hours_since / 24, 1.0) * 0.5
        self.strength = min(10.0, self.strength + amount + spacing_bonus)
        self.activation = min(1.0, self.activation + 0.3)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "strength": self.strength,
            "activation": self.activation,
            "created_at": self.created_at.isoformat(),
            "last_accessed": self.last_accessed.isoformat(),
            "access_count": self.access_count,
            "emotional_valence": self.emotional_valence,
            "importance": self.importance,
            "associations": list(self.associations),
        }


# ============================================
# Working Memory - The Mental Workspace
# ============================================

class WorkingMemory:
    """
    Working memory: The stage where conscious thought happens.
    
    Properties:
    - Limited capacity (Miller's 7±2)
    - Rapid decay without rehearsal
    - Items can be "chunked" together
    - Serves as the focus of attention
    """
    
    CAPACITY = 7  # Miller's magic number
    DECAY_SECONDS = 20  # Items fade without attention
    
    def __init__(self):
        self._items: List[MemoryTrace] = []
        self._focus_index: int = 0
        self._last_update: datetime = datetime.now()
    
    def add(self, content: Dict[str, Any], importance: float = 0.5) -> MemoryTrace:
        """
        Add item to working memory.
        May displace least important item if at capacity.
        """
        trace = MemoryTrace(
            id=hashlib.md5(json.dumps(content, sort_keys=True).encode()).hexdigest()[:12],
            content=content,
            importance=importance,
            activation=1.0,
        )
        
        # Apply decay to existing items
        self._apply_decay()
        
        # If at capacity, remove lowest activation item
        if len(self._items) >= self.CAPACITY:
            weakest = min(self._items, key=lambda x: x.activation * x.importance)
            self._items.remove(weakest)
        
        self._items.append(trace)
        self._last_update = datetime.now()
        return trace
    
    def focus(self, item_id: str) -> Optional[MemoryTrace]:
        """Focus attention on an item, reinforcing it."""
        for i, item in enumerate(self._items):
            if item.id == item_id:
                item.reinforce(0.2)
                self._focus_index = i
                return item
        return None
    
    def get_focused(self) -> Optional[MemoryTrace]:
        """Get currently focused item."""
        if 0 <= self._focus_index < len(self._items):
            return self._items[self._focus_index]
        return None
    
    def get_all(self) -> List[MemoryTrace]:
        """Get all items in working memory."""
        self._apply_decay()
        return [item for item in self._items if item.activation > 0.1]
    
    def rehearse(self, item_ids: Optional[List[str]] = None):
        """Rehearse items to prevent decay."""
        if item_ids is None:
            # Rehearse all
            for item in self._items:
                item.activation = min(1.0, item.activation + 0.2)
        else:
            for item in self._items:
                if item.id in item_ids:
                    item.activation = min(1.0, item.activation + 0.3)
    
    def clear(self):
        """Clear working memory."""
        self._items = []
        self._focus_index = 0
    
    def _apply_decay(self):
        """Apply decay to all items."""
        now = datetime.now()
        seconds_passed = (now - self._last_update).total_seconds()
        
        for item in self._items:
            # Faster decay for working memory
            decay_factor = math.exp(-seconds_passed / self.DECAY_SECONDS)
            item.activation *= decay_factor
        
        # Remove items that have faded completely
        self._items = [item for item in self._items if item.activation > 0.05]
        self._last_update = now


# ============================================
# Episodic Memory - Life Events
# ============================================

@dataclass
class Episode:
    """
    An episodic memory - a remembered experience.
    
    Episodes are:
    - Time-stamped
    - Contextualized (where, when, who)
    - Emotional (how it felt)
    - Causal (what led to what)
    """
    id: str
    timestamp: datetime
    
    # What happened
    event_type: str
    description: str
    content: Dict[str, Any]
    
    # Context
    location: Optional[str] = None
    participants: List[str] = field(default_factory=list)
    services_involved: List[str] = field(default_factory=list)
    
    # Connections
    caused_by: Optional[str] = None  # ID of causing episode
    led_to: List[str] = field(default_factory=list)  # IDs of resulting episodes
    related_concepts: List[str] = field(default_factory=list)
    
    # Memory qualities
    emotional_valence: float = 0.0  # -1 to 1
    importance: float = 0.5         # 0 to 1
    vividness: float = 1.0          # How detailed (fades over time)
    
    # Storage metadata
    encoding_strength: float = 1.0
    last_recalled: Optional[datetime] = None
    recall_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
            "description": self.description,
            "content": self.content,
            "location": self.location,
            "participants": self.participants,
            "emotional_valence": self.emotional_valence,
            "importance": self.importance,
            "vividness": self.vividness,
        }


class EpisodicMemory:
    """
    Episodic memory: Autobiographical record of experiences.
    
    Features:
    - Time-based indexing
    - Causal chain tracking
    - Emotional weighting
    - Consolidation (strengthening important memories)
    - Forgetting (graceful decay of unimportant details)
    """
    
    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or Path.home() / ".apex" / "brain"
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        self.db_path = self.storage_path / "episodic.db"
        self._init_database()
        
        # In-memory recent episode buffer for fast access
        self._recent_buffer: List[Episode] = []
        self._buffer_size = 100
    
    def _init_database(self):
        """Initialize SQLite database for episodic storage."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS episodes (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                description TEXT NOT NULL,
                content TEXT NOT NULL,
                location TEXT,
                participants TEXT,
                services TEXT,
                caused_by TEXT,
                led_to TEXT,
                related_concepts TEXT,
                emotional_valence REAL DEFAULT 0.0,
                importance REAL DEFAULT 0.5,
                vividness REAL DEFAULT 1.0,
                encoding_strength REAL DEFAULT 1.0,
                last_recalled TEXT,
                recall_count INTEGER DEFAULT 0,
                embedding BLOB
            )
        """)
        
        # Indexes for common queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_episodes_time ON episodes(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_episodes_type ON episodes(event_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_episodes_importance ON episodes(importance DESC)")
        
        conn.commit()
        conn.close()
    
    def record(
        self,
        event_type: str,
        description: str,
        content: Dict[str, Any],
        importance: float = 0.5,
        emotional_valence: float = 0.0,
        participants: Optional[List[str]] = None,
        services: Optional[List[str]] = None,
        caused_by: Optional[str] = None,
    ) -> Episode:
        """
        Record a new episode to memory.
        
        This is how the brain learns from experience.
        """
        episode = Episode(
            id=hashlib.md5(f"{datetime.now().isoformat()}:{event_type}:{description}".encode()).hexdigest()[:16],
            timestamp=datetime.now(),
            event_type=event_type,
            description=description,
            content=content,
            participants=participants or [],
            services_involved=services or [],
            emotional_valence=emotional_valence,
            importance=importance,
            caused_by=caused_by,
        )
        
        # If this was caused by another episode, update that episode
        if caused_by:
            self._link_episodes(caused_by, episode.id)
        
        # Store to database
        self._store_episode(episode)
        
        # Add to recent buffer
        self._recent_buffer.append(episode)
        if len(self._recent_buffer) > self._buffer_size:
            self._recent_buffer.pop(0)
        
        logger.debug(f"Recorded episode: {event_type} - {description[:50]}")
        return episode
    
    def recall(
        self,
        query: Optional[str] = None,
        event_type: Optional[str] = None,
        time_range: Optional[Tuple[datetime, datetime]] = None,
        participants: Optional[List[str]] = None,
        min_importance: float = 0.0,
        limit: int = 20,
    ) -> List[Episode]:
        """
        Recall episodes from memory.
        
        Recalling strengthens the memory (testing effect).
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        conditions = ["importance >= ?"]
        params: List[Any] = [min_importance]
        
        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        
        if time_range:
            conditions.append("timestamp BETWEEN ? AND ?")
            params.extend([time_range[0].isoformat(), time_range[1].isoformat()])
        
        if query:
            conditions.append("(description LIKE ? OR content LIKE ?)")
            params.extend([f"%{query}%", f"%{query}%"])
        
        sql = f"""
            SELECT * FROM episodes
            WHERE {" AND ".join(conditions)}
            ORDER BY timestamp DESC
            LIMIT ?
        """
        params.append(limit)
        
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        conn.close()
        
        episodes = [self._row_to_episode(row) for row in rows]
        
        # Recalling strengthens memories
        for ep in episodes:
            self._strengthen_episode(ep.id)
        
        return episodes
    
    def recall_by_context(
        self,
        current_context: Dict[str, Any],
        limit: int = 10,
    ) -> List[Episode]:
        """
        Recall episodes similar to current context.
        
        This is associative memory - things remind us of related things.
        """
        # Extract context features
        participants = current_context.get("participants", [])
        services = current_context.get("services", [])
        event_type = current_context.get("event_type")
        
        # Build query for similar episodes
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        conditions = []
        params = []
        
        if participants:
            for p in participants[:3]:  # Limit to avoid huge queries
                conditions.append("participants LIKE ?")
                params.append(f"%{p}%")
        
        if services:
            for s in services[:3]:
                conditions.append("services LIKE ?")
                params.append(f"%{s}%")
        
        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        
        if not conditions:
            # No context to match, return recent
            return self.recall(limit=limit)
        
        sql = f"""
            SELECT * FROM episodes
            WHERE {" OR ".join(conditions)}
            ORDER BY importance DESC, timestamp DESC
            LIMIT ?
        """
        params.append(limit)
        
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_episode(row) for row in rows]
    
    def get_causal_chain(self, episode_id: str, depth: int = 5) -> List[Episode]:
        """Get the causal chain leading to/from an episode."""
        chain = []
        visited = set()
        
        def traverse_back(eid: str, current_depth: int):
            if current_depth <= 0 or eid in visited:
                return
            visited.add(eid)
            
            ep = self._get_episode(eid)
            if ep:
                chain.insert(0, ep)
                if ep.caused_by:
                    traverse_back(ep.caused_by, current_depth - 1)
        
        def traverse_forward(eid: str, current_depth: int):
            if current_depth <= 0 or eid in visited:
                return
            visited.add(eid)
            
            ep = self._get_episode(eid)
            if ep:
                chain.append(ep)
                for led_to_id in ep.led_to:
                    traverse_forward(led_to_id, current_depth - 1)
        
        # Get the starting episode
        start = self._get_episode(episode_id)
        if start:
            if start.caused_by:
                traverse_back(start.caused_by, depth)
            chain.append(start)
            for led_to_id in start.led_to:
                traverse_forward(led_to_id, depth)
        
        return chain
    
    def consolidate(self, hours_threshold: int = 24):
        """
        Memory consolidation - like sleep for the brain.
        
        - Strengthen important memories
        - Decay unimportant ones
        - Generalize patterns to semantic memory
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get episodes that haven't been consolidated recently
        threshold = (datetime.now() - timedelta(hours=hours_threshold)).isoformat()
        
        cursor.execute("""
            SELECT id, importance, vividness, encoding_strength, recall_count
            FROM episodes
            WHERE timestamp < ?
        """, (threshold,))
        
        updates = []
        for row in cursor.fetchall():
            ep_id, importance, vividness, strength, recalls = row
            
            # Calculate new vividness (details fade)
            new_vividness = max(0.1, vividness * 0.95)
            
            # Strengthen based on importance and recall frequency
            rehearsal_bonus = min(recalls * 0.1, 0.5)
            new_strength = min(10.0, strength + importance * 0.1 + rehearsal_bonus)
            
            updates.append((new_vividness, new_strength, ep_id))
        
        cursor.executemany("""
            UPDATE episodes SET vividness = ?, encoding_strength = ? WHERE id = ?
        """, updates)
        
        conn.commit()
        conn.close()
        
        logger.info(f"Consolidated {len(updates)} episodes")
    
    def _store_episode(self, episode: Episode):
        """Store episode to database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO episodes
            (id, timestamp, event_type, description, content, location,
             participants, services, caused_by, led_to, related_concepts,
             emotional_valence, importance, vividness, encoding_strength,
             last_recalled, recall_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            episode.id,
            episode.timestamp.isoformat(),
            episode.event_type,
            episode.description,
            json.dumps(episode.content),
            episode.location,
            json.dumps(episode.participants),
            json.dumps(episode.services_involved),
            episode.caused_by,
            json.dumps(episode.led_to),
            json.dumps(episode.related_concepts),
            episode.emotional_valence,
            episode.importance,
            episode.vividness,
            episode.encoding_strength,
            episode.last_recalled.isoformat() if episode.last_recalled else None,
            episode.recall_count,
        ))
        
        conn.commit()
        conn.close()
    
    def _get_episode(self, episode_id: str) -> Optional[Episode]:
        """Get episode by ID."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,))
        row = cursor.fetchone()
        conn.close()
        return self._row_to_episode(row) if row else None
    
    def _row_to_episode(self, row) -> Episode:
        """Convert database row to Episode object."""
        return Episode(
            id=row[0],
            timestamp=datetime.fromisoformat(row[1]),
            event_type=row[2],
            description=row[3],
            content=json.loads(row[4]),
            location=row[5],
            participants=json.loads(row[6]) if row[6] else [],
            services_involved=json.loads(row[7]) if row[7] else [],
            caused_by=row[8],
            led_to=json.loads(row[9]) if row[9] else [],
            related_concepts=json.loads(row[10]) if row[10] else [],
            emotional_valence=row[11],
            importance=row[12],
            vividness=row[13],
            encoding_strength=row[14],
            last_recalled=datetime.fromisoformat(row[15]) if row[15] else None,
            recall_count=row[16],
        )
    
    def _strengthen_episode(self, episode_id: str):
        """Strengthen an episode (called when recalled)."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE episodes 
            SET recall_count = recall_count + 1,
                last_recalled = ?,
                encoding_strength = MIN(10.0, encoding_strength + 0.1)
            WHERE id = ?
        """, (datetime.now().isoformat(), episode_id))
        conn.commit()
        conn.close()
    
    def _link_episodes(self, cause_id: str, effect_id: str):
        """Link two episodes causally."""
        episode = self._get_episode(cause_id)
        if episode:
            episode.led_to.append(effect_id)
            self._store_episode(episode)


# ============================================
# Semantic Memory - Knowledge Graph
# ============================================

@dataclass
class Concept:
    """
    A concept in semantic memory - a unit of knowledge.
    
    Concepts are:
    - Abstract (not tied to specific events)
    - Related to other concepts
    - Weighted by confidence and importance
    """
    id: str
    name: str
    category: str  # person, place, thing, idea, action, etc.
    
    # Definition and properties
    definition: str = ""
    properties: Dict[str, Any] = field(default_factory=dict)
    
    # Relationships to other concepts
    is_a: List[str] = field(default_factory=list)      # Hierarchical
    has_a: List[str] = field(default_factory=list)     # Compositional
    related_to: List[Tuple[str, float]] = field(default_factory=list)  # Associative with strength
    opposite_of: List[str] = field(default_factory=list)
    
    # Learning metadata
    confidence: float = 0.5       # How sure we are about this
    sources: List[str] = field(default_factory=list)  # Where we learned it
    learned_at: datetime = field(default_factory=datetime.now)
    last_used: datetime = field(default_factory=datetime.now)
    use_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "definition": self.definition,
            "properties": self.properties,
            "is_a": self.is_a,
            "has_a": self.has_a,
            "related_to": self.related_to,
            "confidence": self.confidence,
        }


class SemanticMemory:
    """
    Semantic memory: The knowledge graph.
    
    This is what the brain "knows" as opposed to what it "remembers."
    Knowledge is generalized from experiences and can be reasoned over.
    """
    
    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or Path.home() / ".apex" / "brain"
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        self.db_path = self.storage_path / "semantic.db"
        self._init_database()
        
        # In-memory concept cache
        self._concept_cache: Dict[str, Concept] = {}
        self._load_frequent_concepts()
    
    def _init_database(self):
        """Initialize semantic memory database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS concepts (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                definition TEXT,
                properties TEXT,
                is_a TEXT,
                has_a TEXT,
                related_to TEXT,
                opposite_of TEXT,
                confidence REAL DEFAULT 0.5,
                sources TEXT,
                learned_at TEXT,
                last_used TEXT,
                use_count INTEGER DEFAULT 0,
                embedding BLOB
            )
        """)
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_concepts_name ON concepts(name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_concepts_category ON concepts(category)")
        
        conn.commit()
        conn.close()
    
    def _load_frequent_concepts(self, limit: int = 500):
        """Load frequently used concepts into cache."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM concepts ORDER BY use_count DESC LIMIT ?
        """, (limit,))
        
        for row in cursor.fetchall():
            concept = self._row_to_concept(row)
            self._concept_cache[concept.id] = concept
        conn.close()
    
    def learn(
        self,
        name: str,
        category: str,
        definition: str = "",
        properties: Optional[Dict[str, Any]] = None,
        source: Optional[str] = None,
        confidence: float = 0.5,
    ) -> Concept:
        """
        Learn a new concept or update existing one.
        
        Multiple exposures increase confidence.
        """
        concept_id = hashlib.md5(f"{category}:{name.lower()}".encode()).hexdigest()[:16]
        
        existing = self.get_concept(concept_id)
        
        if existing:
            # Update existing concept
            if definition and not existing.definition:
                existing.definition = definition
            if properties:
                existing.properties.update(properties)
            if source and source not in existing.sources:
                existing.sources.append(source)
            # Increase confidence with repeated exposure
            existing.confidence = min(1.0, existing.confidence + 0.1)
            existing.use_count += 1
            existing.last_used = datetime.now()
            
            self._store_concept(existing)
            return existing
        else:
            # Create new concept
            concept = Concept(
                id=concept_id,
                name=name,
                category=category,
                definition=definition,
                properties=properties or {},
                sources=[source] if source else [],
                confidence=confidence,
            )
            self._store_concept(concept)
            self._concept_cache[concept.id] = concept
            return concept
    
    def relate(
        self,
        concept1_id: str,
        concept2_id: str,
        relationship: str = "related_to",
        strength: float = 0.5,
        bidirectional: bool = True,
    ):
        """
        Create or strengthen a relationship between concepts.
        """
        c1 = self.get_concept(concept1_id)
        c2 = self.get_concept(concept2_id)
        
        if not c1 or not c2:
            return
        
        # Add relationship based on type
        if relationship == "is_a":
            if concept2_id not in c1.is_a:
                c1.is_a.append(concept2_id)
        elif relationship == "has_a":
            if concept2_id not in c1.has_a:
                c1.has_a.append(concept2_id)
        elif relationship == "opposite_of":
            if concept2_id not in c1.opposite_of:
                c1.opposite_of.append(concept2_id)
                if bidirectional and concept1_id not in c2.opposite_of:
                    c2.opposite_of.append(concept1_id)
        else:
            # Generic related_to with strength
            existing = next((r for r in c1.related_to if r[0] == concept2_id), None)
            if existing:
                # Strengthen existing relationship
                c1.related_to = [(r[0], min(1.0, r[1] + 0.1)) if r[0] == concept2_id else r 
                                 for r in c1.related_to]
            else:
                c1.related_to.append((concept2_id, strength))
            
            if bidirectional:
                existing = next((r for r in c2.related_to if r[0] == concept1_id), None)
                if existing:
                    c2.related_to = [(r[0], min(1.0, r[1] + 0.1)) if r[0] == concept1_id else r 
                                     for r in c2.related_to]
                else:
                    c2.related_to.append((concept1_id, strength))
                self._store_concept(c2)
        
        self._store_concept(c1)
    
    def get_concept(self, concept_id: str) -> Optional[Concept]:
        """Get concept by ID."""
        if concept_id in self._concept_cache:
            return self._concept_cache[concept_id]
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM concepts WHERE id = ?", (concept_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            concept = self._row_to_concept(row)
            self._concept_cache[concept.id] = concept
            return concept
        return None
    
    def find_by_name(self, name: str) -> Optional[Concept]:
        """Find concept by name."""
        # Check cache first
        for concept in self._concept_cache.values():
            if concept.name.lower() == name.lower():
                return concept
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM concepts WHERE LOWER(name) = LOWER(?)", (name,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            concept = self._row_to_concept(row)
            return concept
        return None
    
    def search(
        self,
        query: str,
        category: Optional[str] = None,
        limit: int = 20,
    ) -> List[Concept]:
        """Search for concepts."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if category:
            cursor.execute("""
                SELECT * FROM concepts 
                WHERE (name LIKE ? OR definition LIKE ?) AND category = ?
                ORDER BY use_count DESC LIMIT ?
            """, (f"%{query}%", f"%{query}%", category, limit))
        else:
            cursor.execute("""
                SELECT * FROM concepts 
                WHERE name LIKE ? OR definition LIKE ?
                ORDER BY use_count DESC LIMIT ?
            """, (f"%{query}%", f"%{query}%", limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_concept(row) for row in rows]
    
    def get_related(self, concept_id: str, depth: int = 1) -> List[Tuple[Concept, float]]:
        """Get concepts related to a given concept."""
        concept = self.get_concept(concept_id)
        if not concept:
            return []
        
        related = []
        visited = {concept_id}
        
        def collect_related(c: Concept, current_depth: int, path_strength: float):
            if current_depth > depth:
                return
            
            # Collect all relationships
            for related_id, strength in c.related_to:
                if related_id not in visited:
                    visited.add(related_id)
                    related_concept = self.get_concept(related_id)
                    if related_concept:
                        combined_strength = path_strength * strength
                        related.append((related_concept, combined_strength))
                        collect_related(related_concept, current_depth + 1, combined_strength)
            
            for related_id in c.is_a + c.has_a:
                if related_id not in visited:
                    visited.add(related_id)
                    related_concept = self.get_concept(related_id)
                    if related_concept:
                        related.append((related_concept, path_strength * 0.8))
                        collect_related(related_concept, current_depth + 1, path_strength * 0.8)
        
        collect_related(concept, 1, 1.0)
        
        # Sort by strength
        related.sort(key=lambda x: x[1], reverse=True)
        return related
    
    def infer(self, concept_id: str) -> List[Dict[str, Any]]:
        """
        Make inferences about a concept based on its relationships.
        
        If X is_a Y, and Y has_property Z, then X likely has_property Z.
        """
        concept = self.get_concept(concept_id)
        if not concept:
            return []
        
        inferences = []
        
        # Inherit properties from parent concepts
        for parent_id in concept.is_a:
            parent = self.get_concept(parent_id)
            if parent:
                for prop_key, prop_value in parent.properties.items():
                    if prop_key not in concept.properties:
                        inferences.append({
                            "type": "inherited_property",
                            "property": prop_key,
                            "value": prop_value,
                            "source": parent.name,
                            "confidence": parent.confidence * 0.7,
                        })
        
        # Find patterns in related concepts
        related = self.get_related(concept_id, depth=1)
        common_categories = {}
        for related_concept, strength in related:
            cat = related_concept.category
            common_categories[cat] = common_categories.get(cat, 0) + strength
        
        if common_categories:
            most_common = max(common_categories.items(), key=lambda x: x[1])
            if most_common[1] > 1.5:  # Threshold for inference
                inferences.append({
                    "type": "category_association",
                    "category": most_common[0],
                    "strength": most_common[1],
                    "confidence": min(0.8, most_common[1] / 3),
                })
        
        return inferences
    
    def _store_concept(self, concept: Concept):
        """Store concept to database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO concepts
            (id, name, category, definition, properties, is_a, has_a, related_to,
             opposite_of, confidence, sources, learned_at, last_used, use_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            concept.id,
            concept.name,
            concept.category,
            concept.definition,
            json.dumps(concept.properties),
            json.dumps(concept.is_a),
            json.dumps(concept.has_a),
            json.dumps(concept.related_to),
            json.dumps(concept.opposite_of),
            concept.confidence,
            json.dumps(concept.sources),
            concept.learned_at.isoformat(),
            concept.last_used.isoformat(),
            concept.use_count,
        ))
        
        conn.commit()
        conn.close()
        
        # Update cache
        self._concept_cache[concept.id] = concept
    
    def _row_to_concept(self, row) -> Concept:
        """Convert database row to Concept object."""
        return Concept(
            id=row[0],
            name=row[1],
            category=row[2],
            definition=row[3] or "",
            properties=json.loads(row[4]) if row[4] else {},
            is_a=json.loads(row[5]) if row[5] else [],
            has_a=json.loads(row[6]) if row[6] else [],
            related_to=json.loads(row[7]) if row[7] else [],
            opposite_of=json.loads(row[8]) if row[8] else [],
            confidence=row[9],
            sources=json.loads(row[10]) if row[10] else [],
            learned_at=datetime.fromisoformat(row[11]) if row[11] else datetime.now(),
            last_used=datetime.fromisoformat(row[12]) if row[12] else datetime.now(),
            use_count=row[13],
        )


# ============================================
# Procedural Memory - How to Do Things
# ============================================

@dataclass
class Procedure:
    """
    A procedure - knowledge of how to do something.
    
    Procedures are:
    - Step-by-step
    - Condition-dependent
    - Refined through practice
    """
    id: str
    name: str
    description: str
    
    # The steps
    steps: List[Dict[str, Any]] = field(default_factory=list)
    
    # When to use this procedure
    trigger_conditions: List[str] = field(default_factory=list)
    preconditions: List[str] = field(default_factory=list)
    
    # Learning metadata
    success_rate: float = 0.5      # How often it works
    execution_count: int = 0
    last_executed: Optional[datetime] = None
    refinement_history: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "steps": self.steps,
            "trigger_conditions": self.trigger_conditions,
            "success_rate": self.success_rate,
            "execution_count": self.execution_count,
        }


class ProceduralMemory:
    """
    Procedural memory: Learned skills and procedures.
    
    This is "how to" knowledge - refined through practice
    and feedback.
    """
    
    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or Path.home() / ".apex" / "brain"
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        self._procedures: Dict[str, Procedure] = {}
        self._load_procedures()
    
    def _load_procedures(self):
        """Load procedures from disk."""
        proc_file = self.storage_path / "procedures.json"
        if proc_file.exists():
            data = json.loads(proc_file.read_text())
            for item in data:
                proc = Procedure(**item)
                if "last_executed" in item and item["last_executed"]:
                    proc.last_executed = datetime.fromisoformat(item["last_executed"])
                self._procedures[proc.id] = proc
    
    def _save_procedures(self):
        """Save procedures to disk."""
        proc_file = self.storage_path / "procedures.json"
        data = []
        for proc in self._procedures.values():
            item = proc.to_dict()
            item["preconditions"] = proc.preconditions
            item["refinement_history"] = proc.refinement_history
            if proc.last_executed:
                item["last_executed"] = proc.last_executed.isoformat()
            data.append(item)
        proc_file.write_text(json.dumps(data, indent=2))
    
    def learn_procedure(
        self,
        name: str,
        description: str,
        steps: List[Dict[str, Any]],
        trigger_conditions: Optional[List[str]] = None,
    ) -> Procedure:
        """
        Learn a new procedure or update existing.
        """
        proc_id = hashlib.md5(name.lower().encode()).hexdigest()[:16]
        
        if proc_id in self._procedures:
            # Update existing
            proc = self._procedures[proc_id]
            proc.steps = steps
            if trigger_conditions:
                proc.trigger_conditions = trigger_conditions
        else:
            proc = Procedure(
                id=proc_id,
                name=name,
                description=description,
                steps=steps,
                trigger_conditions=trigger_conditions or [],
            )
            self._procedures[proc_id] = proc
        
        self._save_procedures()
        return proc
    
    def get_procedure(self, name: str) -> Optional[Procedure]:
        """Get procedure by name."""
        proc_id = hashlib.md5(name.lower().encode()).hexdigest()[:16]
        return self._procedures.get(proc_id)
    
    def find_applicable(self, context: Dict[str, Any]) -> List[Procedure]:
        """Find procedures applicable to current context."""
        applicable = []
        
        context_str = json.dumps(context).lower()
        
        for proc in self._procedures.values():
            for trigger in proc.trigger_conditions:
                if trigger.lower() in context_str:
                    applicable.append(proc)
                    break
        
        # Sort by success rate
        applicable.sort(key=lambda p: p.success_rate, reverse=True)
        return applicable
    
    def record_execution(self, proc_id: str, success: bool, feedback: Optional[str] = None):
        """
        Record procedure execution and learn from outcome.
        """
        proc = self._procedures.get(proc_id)
        if not proc:
            return
        
        proc.execution_count += 1
        proc.last_executed = datetime.now()
        
        # Update success rate using exponential moving average
        alpha = 0.3  # Learning rate
        proc.success_rate = alpha * (1.0 if success else 0.0) + (1 - alpha) * proc.success_rate
        
        # Record refinement if feedback provided
        if feedback:
            proc.refinement_history.append({
                "timestamp": datetime.now().isoformat(),
                "success": success,
                "feedback": feedback,
            })
        
        self._save_procedures()
    
    def refine_procedure(self, proc_id: str, new_steps: List[Dict[str, Any]], reason: str):
        """
        Refine a procedure based on experience.
        """
        proc = self._procedures.get(proc_id)
        if not proc:
            return
        
        # Store old version in history
        proc.refinement_history.append({
            "timestamp": datetime.now().isoformat(),
            "reason": reason,
            "old_steps": proc.steps,
        })
        
        proc.steps = new_steps
        self._save_procedures()


# ============================================
# Memory Systems - Unified Interface
# ============================================

class MemorySystems:
    """
    Unified interface to all memory systems.
    
    This is the "memory" of the brain - coordinating
    working, episodic, semantic, and procedural memory.
    """
    
    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or Path.home() / ".apex" / "brain"
        
        # Initialize all memory systems
        self.working = WorkingMemory()
        self.episodic = EpisodicMemory(self.storage_path)
        self.semantic = SemanticMemory(self.storage_path)
        self.procedural = ProceduralMemory(self.storage_path)
    
    def remember(
        self,
        content: Dict[str, Any],
        memory_type: str = "auto",
        importance: float = 0.5,
    ):
        """
        Encode something to memory.
        
        Automatically routes to appropriate memory system.
        """
        # Always add to working memory first
        self.working.add(content, importance)
        
        if memory_type == "auto":
            # Determine appropriate memory type from content
            if "event" in content or "timestamp" in content:
                memory_type = "episodic"
            elif "procedure" in content or "steps" in content:
                memory_type = "procedural"
            elif "concept" in content or "definition" in content:
                memory_type = "semantic"
            else:
                memory_type = "episodic"  # Default to episodic
        
        if memory_type == "episodic":
            self.episodic.record(
                event_type=content.get("event_type", "general"),
                description=content.get("description", str(content)),
                content=content,
                importance=importance,
            )
        elif memory_type == "semantic":
            self.semantic.learn(
                name=content.get("name", "unknown"),
                category=content.get("category", "general"),
                definition=content.get("definition", ""),
                properties=content.get("properties"),
            )
        elif memory_type == "procedural":
            self.procedural.learn_procedure(
                name=content.get("name", "unnamed"),
                description=content.get("description", ""),
                steps=content.get("steps", []),
            )
    
    def recall(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        memory_types: Optional[List[str]] = None,
        limit: int = 10,
    ) -> Dict[str, List[Any]]:
        """
        Recall from memory, searching across systems.
        """
        results = {
            "working": [],
            "episodic": [],
            "semantic": [],
            "procedural": [],
        }
        
        types_to_search = memory_types or ["working", "episodic", "semantic", "procedural"]
        
        if "working" in types_to_search:
            # Search working memory
            for item in self.working.get_all():
                if query.lower() in json.dumps(item.content).lower():
                    results["working"].append(item)
        
        if "episodic" in types_to_search:
            # Search episodic memory
            if context:
                results["episodic"] = self.episodic.recall_by_context(context, limit)
            else:
                results["episodic"] = self.episodic.recall(query=query, limit=limit)
        
        if "semantic" in types_to_search:
            # Search semantic memory
            results["semantic"] = self.semantic.search(query, limit=limit)
        
        if "procedural" in types_to_search:
            # Search procedural memory
            if context:
                results["procedural"] = self.procedural.find_applicable(context)
            else:
                # Search by name
                proc = self.procedural.get_procedure(query)
                if proc:
                    results["procedural"] = [proc]
        
        return results
    
    def consolidate(self):
        """
        Run memory consolidation across all systems.
        
        Like sleep - processes memories, strengthens important ones,
        generalizes patterns.
        """
        # Consolidate episodic memories
        self.episodic.consolidate()
        
        # Extract patterns from recent episodes and add to semantic memory
        recent_episodes = self.episodic.recall(limit=50)
        
        # Find recurring participants and add as concepts
        participant_counts: Dict[str, int] = {}
        for ep in recent_episodes:
            for p in ep.participants:
                participant_counts[p] = participant_counts.get(p, 0) + 1
        
        for participant, count in participant_counts.items():
            if count >= 3:  # Threshold for learning
                self.semantic.learn(
                    name=participant,
                    category="person",
                    source="episodic_consolidation",
                    confidence=min(0.9, count * 0.1),
                )
        
        logger.info("Memory consolidation complete")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get memory system statistics."""
        return {
            "working_memory_items": len(self.working.get_all()),
            "working_memory_capacity": WorkingMemory.CAPACITY,
            "episodic_recent_buffer": len(self.episodic._recent_buffer),
            "semantic_cached_concepts": len(self.semantic._concept_cache),
            "procedural_procedures": len(self.procedural._procedures),
        }
