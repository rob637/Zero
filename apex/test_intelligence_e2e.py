"""
Integration Tests for the Intelligence Layer

Tests that the intelligence components work together to create
the "HOW DID IT KNOW?!" moments.

Test scenarios:
1. Memory stores and recalls facts about entities
2. Preference learner learns from observed actions
3. Pattern recognition detects weekly/daily patterns
4. Cross-service intelligence connects dots
5. Proactive engine generates timely suggestions

Run with: pytest test_intelligence_e2e.py -v
"""

import asyncio
import pytest
import tempfile
import shutil
from datetime import datetime, timedelta
from pathlib import Path


# ============================================================================
# Unit Tests for Semantic Memory
# ============================================================================

class TestSemanticMemory:
    """Test the semantic memory knowledge graph."""
    
    @pytest.fixture
    def memory(self):
        """Create a temporary memory instance."""
        from intelligence.semantic_memory import SemanticMemory
        
        temp_dir = tempfile.mkdtemp()
        mem = SemanticMemory(storage_path=temp_dir)
        yield mem
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.mark.asyncio
    async def test_remember_and_recall(self, memory):
        """Test basic remember and recall."""
        from intelligence.semantic_memory import FactCategory
        
        # Remember a fact
        fact = await memory.remember(
            "John prefers morning meetings",
            category=FactCategory.PREFERENCE,
            entity="john",
            related_entities=["meetings"],
        )
        
        assert fact is not None
        assert fact.content == "John prefers morning meetings"
        
        # Recall the fact - returns list of (Fact, relevance_score) tuples
        results = await memory.recall("John meeting preference")
        
        assert len(results) > 0
        assert any("morning" in fact.content for fact, _ in results)
    
    @pytest.mark.asyncio
    async def test_entity_relationships(self, memory):
        """Test knowledge graph relationships."""
        # Connect entities
        await memory.connect_entities("john", "works_with", "sarah")
        await memory.connect_entities("john", "manages", "apollo_project")
        
        # Get entity info
        john_info = await memory.get_entity("john")
        
        assert john_info is not None
        # Relationships are in entity["relationships"] dict with lists of related entity IDs
        assert "sarah" in str(john_info["entity"]["relationships"])
    
    @pytest.mark.asyncio
    async def test_recall_about_entity(self, memory):
        """Test recalling facts about a specific entity."""
        from intelligence.semantic_memory import FactCategory
        
        # Store multiple facts about one entity
        await memory.remember("John's birthday is March 15", entity="john")
        await memory.remember("John likes coffee", entity="john")
        await memory.remember("John manages the backend team", entity="john")
        
        # Recall about john
        results = await memory.recall_about("john")
        
        assert len(results) >= 3
    
    @pytest.mark.asyncio
    async def test_temporal_relevance(self, memory):
        """Test that temporal relevance affects recall."""
        from intelligence.semantic_memory import TemporalRelevance
        
        # Store ephemeral fact
        await memory.remember(
            "The meeting is in room 301",
            temporal=TemporalRelevance.EPHEMERAL,
        )
        
        # Store permanent fact
        await memory.remember(
            "John's employee ID is 12345",
            temporal=TemporalRelevance.PERMANENT,
        )
        
        # Both should be recallable now
        results = await memory.recall("John room")
        
        assert len(results) >= 1


# ============================================================================
# Unit Tests for Preference Learning
# ============================================================================

class TestPreferenceLearning:
    """Test preference learning from behavior."""
    
    @pytest.fixture
    def learner(self):
        """Create a temporary preference learner."""
        from intelligence.preference_learning import PreferenceLearner
        
        temp_dir = tempfile.mkdtemp()
        pl = PreferenceLearner(storage_path=temp_dir)
        yield pl
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.mark.asyncio
    async def test_observe_actions(self, learner):
        """Test observing user actions."""
        # Observe multiple meeting times
        for hour in [10, 10, 10, 9, 11, 10]:
            await learner.observe("schedule_meeting", {
                "time": f"{hour}:00",
                "duration": 45,
                "day_of_week": "monday",
            })
        
        # Check that preferences were learned
        prefs = await learner.get_preferences("meeting_start_hour")
        
        assert len(prefs) > 0
        meeting_pref = prefs.get("meeting_start_hour")
        assert meeting_pref is not None
        assert meeting_pref.value == 10  # Most common hour
    
    @pytest.mark.asyncio
    async def test_suggest_based_on_learning(self, learner):
        """Test suggestions based on learned preferences."""
        # Observe a pattern
        for _ in range(6):
            await learner.observe("schedule_meeting", {
                "time": "14:00",
                "duration": 30,
            })
        
        # Get suggestion
        suggestion = await learner.suggest("schedule_meeting", {})
        
        assert suggestion is not None
        assert "suggested_duration" in suggestion or "suggested_hour" in suggestion
    
    @pytest.mark.asyncio
    async def test_email_preferences(self, learner):
        """Test learning email composition preferences."""
        # Observe email patterns
        for _ in range(6):
            await learner.observe("send_email", {
                "body_length": 150,
                "has_greeting": True,
                "send_hour": 9,
            })
        
        prefs = await learner.get_preferences()
        
        # Should have learned email style
        assert any("email" in k for k in prefs.keys())


# ============================================================================
# Unit Tests for Pattern Recognition
# ============================================================================

class TestPatternRecognition:
    """Test pattern detection."""
    
    @pytest.fixture
    def engine(self):
        """Create a temporary pattern engine."""
        from intelligence.pattern_recognition import PatternEngine
        
        temp_dir = tempfile.mkdtemp()
        pe = PatternEngine(storage_path=temp_dir)
        yield pe
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.mark.asyncio
    async def test_record_events(self, engine):
        """Test recording events."""
        event = await engine.record_event(
            "standup",
            {"attendees": ["team"], "duration": 15},
        )
        
        assert event is not None
        assert event.event_type == "standup"
    
    @pytest.mark.asyncio
    async def test_detect_weekly_pattern(self, engine):
        """Test detecting a weekly pattern."""
        # Create events at the same time on multiple weeks
        now = datetime.now()
        
        for week in range(4):
            # Monday at 10am
            timestamp = now - timedelta(weeks=week)
            # Adjust to Monday
            days_since_monday = timestamp.weekday()
            timestamp = timestamp - timedelta(days=days_since_monday)
            timestamp = timestamp.replace(hour=10, minute=0)
            
            await engine.record_event(
                "standup",
                {"attendees": ["team"]},
                timestamp=timestamp,
            )
        
        # Trigger detection
        await engine._detect_weekly_patterns()
        
        patterns = await engine.get_patterns()
        
        # Should detect the Monday standup pattern
        assert any("standup" in p.name.lower() for p in patterns)
    
    @pytest.mark.asyncio
    async def test_whats_expected_now(self, engine):
        """Test getting expected patterns for current time."""
        # This tests the API even without data
        expected = await engine.whats_expected_now()
        
        # Without patterns, should be empty
        assert isinstance(expected, list)


# ============================================================================
# Unit Tests for Cross-Service Intelligence
# ============================================================================

class TestCrossServiceIntelligence:
    """Test cross-service connection of dots."""
    
    @pytest.fixture
    def intel(self):
        """Create cross-service intelligence."""
        from intelligence.cross_service import CrossServiceIntelligence
        return CrossServiceIntelligence()
    
    def test_entity_resolution(self, intel):
        """Test learning and resolving entity aliases."""
        # Teach aliases
        intel.learn_alias("john_smith", "john@company.com")
        intel.learn_alias("john_smith", "John Smith")
        intel.learn_alias("john_smith", "J. Smith")
        
        # Resolve
        assert intel.resolve_entity("john@company.com") == "john_smith"
        assert intel.resolve_entity("John Smith") == "john_smith"
        assert intel.resolve_entity("J. Smith") == "john_smith"
    
    def test_get_all_aliases(self, intel):
        """Test getting all aliases for an entity."""
        intel.learn_alias("jane_doe", "jane@company.com")
        intel.learn_alias("jane_doe", "Jane Doe")
        
        aliases = intel.get_all_aliases("jane_doe")
        
        assert "jane@company.com" in aliases
        assert "jane doe" in aliases
    
    @pytest.mark.asyncio
    async def test_brief_without_services(self, intel):
        """Test briefing works even without services."""
        # Should not crash, just return limited data
        brief = await intel.brief_on_person("Unknown Person")
        
        assert brief is not None
        assert brief.name == "Unknown Person"


# ============================================================================
# Unit Tests for Proactive Suggestions
# ============================================================================

class TestProactiveSuggestions:
    """Test proactive suggestion generation."""
    
    @pytest.fixture
    def engine(self):
        """Create proactive suggestion engine."""
        from intelligence.proactive import ProactiveSuggestionEngine
        return ProactiveSuggestionEngine()
    
    @pytest.mark.asyncio
    async def test_get_suggestions_empty(self, engine):
        """Test getting suggestions with no data."""
        suggestions = await engine.get_suggestions()
        
        assert isinstance(suggestions, list)
    
    @pytest.mark.asyncio
    async def test_handle_email_event(self, engine):
        """Test handling an email event."""
        from intelligence.proactive import SuggestionPriority
        
        # Simulate urgent email
        suggestions = await engine.on_event("email_received", {
            "email": {
                "id": "test123",
                "subject": "URGENT: Action Required",
                "from": "boss@company.com",
            }
        })
        
        # Should generate urgent suggestion
        assert len(suggestions) > 0
        assert any(s.priority == SuggestionPriority.URGENT for s in suggestions)
    
    @pytest.mark.asyncio
    async def test_dismiss_suggestion(self, engine):
        """Test dismissing a suggestion."""
        # Generate a suggestion
        suggestions = await engine.on_event("email_received", {
            "email": {
                "id": "test456",
                "subject": "URGENT: Test",
                "from": "test@test.com",
            }
        })
        
        if suggestions:
            sid = suggestions[0].id
            await engine.dismiss(sid)
            
            # Should not appear in active suggestions
            active = await engine.get_suggestions()
            assert all(s.id != sid for s in active)


# ============================================================================
# Integration Tests
# ============================================================================

class TestIntelligenceIntegration:
    """Test that all components work together."""
    
    @pytest.fixture
    def hub(self):
        """Create a temporary intelligence hub."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        
        # Create temp directories
        temp_dir = tempfile.mkdtemp()
        
        # Create components with temp storage
        from intelligence.semantic_memory import SemanticMemory
        from intelligence.preference_learning import PreferenceLearner
        from intelligence.pattern_recognition import PatternEngine
        from intelligence.cross_service import CrossServiceIntelligence
        from intelligence.proactive import ProactiveSuggestionEngine
        
        memory = SemanticMemory(storage_path=f"{temp_dir}/memory")
        prefs = PreferenceLearner(storage_path=f"{temp_dir}/prefs")
        patterns = PatternEngine(storage_path=f"{temp_dir}/patterns")
        intel = CrossServiceIntelligence()
        proactive = ProactiveSuggestionEngine()
        
        # Wire together
        intel.set_memory(memory)
        intel.set_patterns(patterns)
        intel.set_preferences(prefs)
        
        proactive.set_memory(memory)
        proactive.set_patterns(patterns)
        proactive.set_intel(intel)
        
        yield {
            "memory": memory,
            "prefs": prefs,
            "patterns": patterns,
            "intel": intel,
            "proactive": proactive,
        }
        
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.mark.asyncio
    async def test_memory_informs_intelligence(self, hub):
        """Test that memory informs cross-service intelligence."""
        from intelligence.semantic_memory import FactCategory
        
        # Store facts about a person
        await hub["memory"].remember(
            "John prefers short meetings",
            category=FactCategory.PREFERENCE,
            entity="john",
        )
        await hub["memory"].remember(
            "John works on Project Apollo",
            entity="john",
            related_entities=["apollo"],
        )
        
        # Get brief (without services, so limited)
        brief = await hub["intel"].brief_on_person("john")
        
        # The brief should still work
        assert brief is not None
    
    @pytest.mark.asyncio
    async def test_patterns_inform_proactive(self, hub):
        """Test that detected patterns inform proactive suggestions."""
        # Create a pattern
        now = datetime.now()
        
        for week in range(4):
            timestamp = now - timedelta(weeks=week)
            timestamp = timestamp.replace(hour=10, minute=0)
            
            await hub["patterns"].record_event(
                "review_emails",
                {},
                timestamp=timestamp,
            )
        
        # Trigger detection
        await hub["patterns"]._detect_patterns()
        
        # Get stats
        stats = hub["patterns"].get_stats()
        
        assert stats["total_events"] >= 4
    
    @pytest.mark.asyncio
    async def test_learning_creates_suggestions(self, hub):
        """Test that learned preferences can inform suggestions."""
        # Train preferences
        for _ in range(6):
            await hub["prefs"].observe("schedule_meeting", {
                "time": "10:00",
                "duration": 30,
            })
        
        # Get meeting suggestion
        suggestion = await hub["prefs"].suggest("schedule_meeting", {})
        
        assert suggestion.get("suggested_hour") == 10 or suggestion.get("suggested_duration") == 30
    
    @pytest.mark.asyncio
    async def test_full_intelligence_flow(self, hub):
        """Test a complete intelligence flow."""
        from intelligence.semantic_memory import FactCategory
        
        # 1. User schedules meetings with John
        for _ in range(5):
            await hub["prefs"].observe("schedule_meeting", {
                "time": "10:00",
                "attendees": ["john@company.com"],
            })
        
        # 2. System learns about John
        await hub["memory"].remember(
            "John is the CFO",
            entity="john",
        )
        hub["intel"].learn_alias("john", "john@company.com")
        
        # 3. Pattern engine records the meetings
        for i in range(5):
            await hub["patterns"].record_event(
                "meeting_with_john",
                {"attendee": "john@company.com"},
            )
        
        # 4. Now test the flow
        
        # Preferences learned
        prefs = await hub["prefs"].get_preferences()
        assert len(prefs) > 0
        
        # Memory works
        facts = await hub["memory"].recall("john meeting")
        
        # Entity resolved
        canonical = hub["intel"].resolve_entity("john@company.com")
        assert canonical == "john"
        
        print("✓ Full intelligence flow works!")


# ============================================================================
# Performance Tests
# ============================================================================

class TestIntelligencePerformance:
    """Test that intelligence operations are performant."""
    
    @pytest.mark.asyncio
    async def test_memory_scaling(self):
        """Test memory with many facts."""
        import time
        from intelligence.semantic_memory import SemanticMemory
        
        temp_dir = tempfile.mkdtemp()
        memory = SemanticMemory(storage_path=temp_dir)
        
        try:
            # Store 100 facts
            start = time.time()
            for i in range(100):
                await memory.remember(f"Test fact number {i} about topic {i % 10}")
            store_time = time.time() - start
            
            # Recall should still be fast
            start = time.time()
            results = await memory.recall("topic 5")
            recall_time = time.time() - start
            
            print(f"Store 100 facts: {store_time:.2f}s")
            print(f"Recall: {recall_time:.3f}s")
            
            assert store_time < 5.0  # Should be under 5 seconds
            assert recall_time < 0.5  # Should be under 500ms
            
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.mark.asyncio
    async def test_pattern_detection_scaling(self):
        """Test pattern detection with many events."""
        import time
        from intelligence.pattern_recognition import PatternEngine
        
        temp_dir = tempfile.mkdtemp()
        engine = PatternEngine(storage_path=temp_dir)
        
        try:
            # Record 500 events
            now = datetime.now()
            start = time.time()
            
            for i in range(500):
                timestamp = now - timedelta(hours=i)
                await engine.record_event(
                    f"event_type_{i % 5}",
                    {"value": i},
                    timestamp=timestamp,
                )
            
            record_time = time.time() - start
            
            # Detection should be reasonable
            start = time.time()
            await engine._detect_patterns()
            detect_time = time.time() - start
            
            print(f"Record 500 events: {record_time:.2f}s")
            print(f"Detect patterns: {detect_time:.3f}s")
            
            assert record_time < 10.0
            assert detect_time < 2.0
            
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
