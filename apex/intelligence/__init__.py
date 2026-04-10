"""
Telic Intelligence Layer

This is where the magic happens - the components that make Telic
truly LEARN and ANTICIPATE rather than just execute commands.

Components:
- SemanticMemory: Knowledge graph that stores facts and relationships
- PreferenceLearner: Learns from behavior, not explicit statements
- PatternEngine: Detects recurring patterns and routines
- CrossServiceIntelligence: Connects dots across services
- ProactiveSuggestionEngine: Suggests before you ask

Together, these create the "HOW DID IT KNOW?!" moments:
- "You usually have standup at 10am on Monday - want me to prepare?"
- "When you email John, you typically include the budget spreadsheet"
- "Your flight was delayed - should I reschedule your 3pm meeting?"
- "You haven't responded to Sarah's email from 3 days ago"

Usage:
    from intelligence import get_intelligence_hub
    
    hub = get_intelligence_hub()
    hub.set_services(unified_services)
    
    # The system now learns and suggests automatically
    suggestions = await hub.get_suggestions()
"""

from typing import Optional

# Import components
from .semantic_memory import (
    SemanticMemory,
    Fact,
    Entity,
    FactCategory,
    TemporalRelevance,
    get_semantic_memory,
)

from .preference_learning import (
    PreferenceLearner,
    PreferenceType,
    LearnedPreference,
    Observation,
    get_preference_learner,
)

from .pattern_recognition import (
    PatternEngine,
    PatternType,
    TemporalGranularity,
    DetectedPattern,
    Event,
    get_pattern_engine,
)

from .cross_service import (
    CrossServiceIntelligence,
    ContentType,
    RelevantContent,
    PersonBrief,
    MeetingPrep,
    get_cross_service_intelligence,
)

from .proactive import (
    ProactiveSuggestionEngine,
    ProactiveSuggestion,
    SuggestionPriority,
    SuggestionCategory,
    get_proactive_engine,
)


class IntelligenceHub:
    """
    Central hub that orchestrates all intelligence components.
    
    This is the single entry point for the intelligence layer.
    It wires up all components and provides a unified API.
    """
    
    def __init__(self):
        # Initialize components
        self._memory = get_semantic_memory()
        self._preferences = get_preference_learner()
        self._patterns = get_pattern_engine()
        self._intel = get_cross_service_intelligence()
        self._proactive = get_proactive_engine()
        
        # Wire them together
        self._intel.set_memory(self._memory)
        self._intel.set_patterns(self._patterns)
        self._intel.set_preferences(self._preferences)
        
        self._proactive.set_memory(self._memory)
        self._proactive.set_patterns(self._patterns)
        self._proactive.set_intel(self._intel)

        # Sweep expired facts on startup (fire-and-forget)
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._memory.sweep_expired())
            else:
                loop.run_until_complete(self._memory.sweep_expired())
        except RuntimeError:
            pass  # No event loop — sweep will happen on next init
    
    def set_services(self, unified_services):
        """
        Set the unified services layer.
        
        Call this once you have authenticated services.
        """
        self._intel.set_services(unified_services)
        self._proactive.set_services(unified_services)
    
    # =========================================================================
    # Memory API
    # =========================================================================
    
    async def remember(self, fact: str, **kwargs):
        """Remember a fact."""
        return await self._memory.remember(fact, **kwargs)
    
    async def recall(self, query: str, **kwargs):
        """Recall relevant facts."""
        return await self._memory.recall(query, **kwargs)
    
    async def recall_about(self, entity: str, **kwargs):
        """Recall facts about an entity."""
        return await self._memory.recall_about(entity, **kwargs)
    
    async def connect_entities(self, entity1: str, relationship: str, entity2: str):
        """Connect two entities in the knowledge graph."""
        return await self._memory.connect_entities(entity1, relationship, entity2)
    
    # =========================================================================
    # Learning API
    # =========================================================================
    
    async def observe(self, action: str, context: dict, **kwargs):
        """Observe a user action for learning."""
        # Feed to preference learner
        await self._preferences.observe(action, context, **kwargs)
        
        # Feed to pattern engine
        await self._patterns.record_event(action, context)
    
    async def get_preferences(self, key: str = None, **kwargs):
        """Get learned preferences."""
        return await self._preferences.get_preferences(key, **kwargs)
    
    async def suggest_for_action(self, action: str, context: dict = None):
        """Get suggestions based on learned preferences."""
        return await self._preferences.suggest(action, context)
    
    # =========================================================================
    # Pattern API
    # =========================================================================
    
    async def get_patterns(self, **kwargs):
        """Get detected patterns."""
        return await self._patterns.get_patterns(**kwargs)
    
    async def whats_expected_now(self, **kwargs):
        """What patterns are expected at this time?"""
        return await self._patterns.whats_expected_now(**kwargs)
    
    async def detect_anomalies(self, **kwargs):
        """Detect anomalies in behavior."""
        return await self._patterns.detect_anomalies(**kwargs)
    
    # =========================================================================
    # Intelligence API
    # =========================================================================
    
    async def brief_on_person(self, person: str, **kwargs):
        """Get a comprehensive brief on a person."""
        return await self._intel.brief_on_person(person, **kwargs)
    
    async def prepare_for_meeting(self, **kwargs):
        """Prepare materials for a meeting."""
        return await self._intel.prepare_for_meeting(**kwargs)
    
    async def find_related(self, query: str, **kwargs):
        """Find related content across services."""
        return await self._intel.find_related(query, **kwargs)
    
    # =========================================================================
    # Proactive API
    # =========================================================================
    
    async def get_suggestions(self, **kwargs):
        """Get proactive suggestions."""
        return await self._proactive.get_suggestions(**kwargs)
    
    async def get_attention_required(self):
        """Get items that need urgent attention."""
        return await self._proactive.get_attention_required()
    
    async def on_event(self, event_type: str, data: dict = None):
        """Handle an event and get relevant suggestions."""
        return await self._proactive.on_event(event_type, data)
    
    async def dismiss_suggestion(self, suggestion_id: str):
        """Dismiss a suggestion."""
        return await self._proactive.dismiss(suggestion_id)
    
    # =========================================================================
    # Stats
    # =========================================================================
    
    def get_stats(self) -> dict:
        """Get statistics from all intelligence components."""
        return {
            "memory": self._memory.get_stats(),
            "preferences": self._preferences.get_stats(),
            "patterns": self._patterns.get_stats(),
            "proactive": self._proactive.get_stats(),
        }


# Singleton
_hub: Optional[IntelligenceHub] = None

def get_intelligence_hub() -> IntelligenceHub:
    """Get or create the intelligence hub singleton."""
    global _hub
    if _hub is None:
        _hub = IntelligenceHub()
    return _hub


__all__ = [
    # Hub
    "IntelligenceHub",
    "get_intelligence_hub",
    
    # Memory
    "SemanticMemory",
    "Fact",
    "Entity",
    "FactCategory",
    "TemporalRelevance",
    "get_semantic_memory",
    
    # Preferences
    "PreferenceLearner",
    "PreferenceType",
    "LearnedPreference",
    "Observation",
    "get_preference_learner",
    
    # Patterns
    "PatternEngine",
    "PatternType",
    "TemporalGranularity",
    "DetectedPattern",
    "Event",
    "get_pattern_engine",
    
    # Cross-Service
    "CrossServiceIntelligence",
    "ContentType",
    "RelevantContent",
    "PersonBrief",
    "MeetingPrep",
    "get_cross_service_intelligence",
    
    # Proactive
    "ProactiveSuggestionEngine",
    "ProactiveSuggestion",
    "SuggestionPriority",
    "SuggestionCategory",
    "get_proactive_engine",
]
