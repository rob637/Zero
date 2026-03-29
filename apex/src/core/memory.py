"""
Memory Engine - Persistent fact storage for Apex

Apex remembers things about you across sessions:
- User preferences ("I like files organized by date")
- Facts ("My project folder is in C:/Projects")
- History (what was done, when, outcomes)

Uses vector storage for semantic retrieval.
"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any
import hashlib


@dataclass
class Fact:
    """A single piece of remembered information."""
    content: str
    category: str  # preference, fact, history, skill_specific
    source: str  # how we learned this (user_stated, inferred, action_result)
    created_at: str = ""
    last_accessed: str = ""
    access_count: int = 0
    confidence: float = 1.0
    metadata: dict = None
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.last_accessed:
            self.last_accessed = self.created_at
        if self.metadata is None:
            self.metadata = {}
    
    @property
    def id(self) -> str:
        """Generate stable ID from content."""
        return hashlib.sha256(self.content.encode()).hexdigest()[:16]


class MemoryEngine:
    """
    Persistent memory for Apex.
    
    For MVP, uses simple JSON file storage.
    Can be upgraded to ChromaDB/Mem0 for vector search later.
    
    Usage:
        memory = MemoryEngine()
        memory.remember("User prefers organizing by date", category="preference")
        facts = memory.recall("how does user like files organized")
    """
    
    def __init__(self, storage_path: str | Path = None):
        """
        Initialize memory engine.
        
        Args:
            storage_path: Where to store memory. Defaults to ~/.apex/memory/
        """
        if storage_path is None:
            storage_path = Path.home() / ".apex" / "memory"
        
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        self._facts_file = self.storage_path / "facts.json"
        self._facts: dict[str, Fact] = {}
        
        self._load()
    
    def _load(self) -> None:
        """Load facts from storage."""
        if self._facts_file.exists():
            try:
                with open(self._facts_file, "r") as f:
                    data = json.load(f)
                    self._facts = {
                        k: Fact(**v) for k, v in data.items()
                    }
                print(f"[Memory] Loaded {len(self._facts)} facts")
            except Exception as e:
                print(f"[Memory] Error loading: {e}")
                self._facts = {}
    
    def _save(self) -> None:
        """Persist facts to storage."""
        try:
            with open(self._facts_file, "w") as f:
                data = {k: asdict(v) for k, v in self._facts.items()}
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[Memory] Error saving: {e}")
    
    def remember(
        self,
        content: str,
        category: str = "fact",
        source: str = "user_stated",
        confidence: float = 1.0,
        metadata: dict = None,
    ) -> Fact:
        """
        Store a new fact in memory.
        
        Args:
            content: The fact to remember
            category: Type of fact (preference, fact, history)
            source: How we learned this
            confidence: How sure we are (0-1)
            metadata: Additional data
            
        Returns:
            The stored Fact
        """
        fact = Fact(
            content=content,
            category=category,
            source=source,
            confidence=confidence,
            metadata=metadata or {},
        )
        
        self._facts[fact.id] = fact
        self._save()
        
        print(f"[Memory] Remembered: {content[:50]}...")
        return fact
    
    def recall(
        self,
        query: str,
        category: str = None,
        limit: int = 5,
    ) -> list[Fact]:
        """
        Recall facts relevant to a query.
        
        For MVP, uses simple keyword matching.
        TODO: Upgrade to vector similarity search.
        
        Args:
            query: What to search for
            category: Optional category filter
            limit: Max facts to return
            
        Returns:
            List of relevant Facts
        """
        query_lower = query.lower()
        query_words = set(query_lower.split())
        
        scored_facts = []
        for fact in self._facts.values():
            # Filter by category if specified
            if category and fact.category != category:
                continue
            
            # Simple keyword scoring
            fact_words = set(fact.content.lower().split())
            overlap = len(query_words & fact_words)
            
            if overlap > 0:
                # Boost by confidence and access count
                score = overlap * fact.confidence * (1 + fact.access_count * 0.1)
                scored_facts.append((score, fact))
        
        # Sort by score and return top results
        scored_facts.sort(key=lambda x: x[0], reverse=True)
        results = [f for _, f in scored_facts[:limit]]
        
        # Update access counts
        for fact in results:
            fact.last_accessed = datetime.now().isoformat()
            fact.access_count += 1
        self._save()
        
        return results
    
    def recall_all(self, category: str = None) -> list[Fact]:
        """Get all facts, optionally filtered by category."""
        if category:
            return [f for f in self._facts.values() if f.category == category]
        return list(self._facts.values())
    
    def forget(self, fact_id: str) -> bool:
        """Remove a fact from memory."""
        if fact_id in self._facts:
            del self._facts[fact_id]
            self._save()
            return True
        return False
    
    def clear(self, category: str = None) -> int:
        """
        Clear facts from memory.
        
        Args:
            category: If specified, only clear this category
            
        Returns:
            Number of facts cleared
        """
        if category:
            to_remove = [k for k, v in self._facts.items() if v.category == category]
        else:
            to_remove = list(self._facts.keys())
        
        for k in to_remove:
            del self._facts[k]
        
        self._save()
        return len(to_remove)
    
    def get_context_for_skill(self, skill_name: str) -> dict:
        """
        Get memory context relevant to a skill.
        
        Returns preferences, facts, and recent history
        that might be useful for the skill.
        """
        return {
            "preferences": [
                f.content for f in self.recall_all("preference")
            ],
            "relevant_facts": [
                f.content for f in self.recall(skill_name, limit=10)
            ],
            "recent_history": [
                f.content for f in self.recall_all("history")[-5:]
            ],
        }


# Global memory instance
memory = MemoryEngine()
