"""
The Unified Brain - Where Everything Comes Together

This is the crown jewel of Apex.

The Unified Brain integrates:
- Cognitive Core (thinking, reasoning, attention)
- Memory Systems (episodic, semantic, working)
- World Interface (service connections)
- Learning Engine (continuous improvement)
- Consciousness Loop (unified experience)
- Service Adapters (Gmail, Calendar, Drive, etc.)

This creates a LIVING system that:
- Perceives the world continuously
- Remembers everything that matters
- Reasons about what it perceives
- Anticipates what's coming
- Learns from every interaction
- Acts when appropriate

Architecture:
    ┌─────────────────────────────────────────────────────────────────┐
    │                       UNIFIED BRAIN                             │
    │                                                                 │
    │    ┌───────────────────────────────────────────────────────┐   │
    │    │                CONSCIOUSNESS LOOP                      │   │
    │    │  ┌───────────────────────────────────────────────┐    │   │
    │    │  │              COGNITIVE CORE                    │    │   │
    │    │  │   ┌─────────┐  ┌──────────┐  ┌───────────┐    │    │   │
    │    │  │   │Attention│  │Reasoning │  │ Prediction│    │    │   │
    │    │  │   └─────────┘  └──────────┘  └───────────┘    │    │   │
    │    │  │                     │                          │    │   │
    │    │  │   ┌─────────────────┴─────────────────┐       │    │   │
    │    │  │   │          MEMORY SYSTEMS           │       │    │   │
    │    │  │   │  Episodic | Semantic | Working    │       │    │   │
    │    │  │   └──────────────────────────────────┘       │    │   │
    │    │  └────────────────────────────────────────────────┘    │   │
    │    │                         │                              │   │
    │    │    ┌────────────────────┴────────────────────┐        │   │
    │    │    │            LEARNING ENGINE              │        │   │
    │    │    └─────────────────────────────────────────┘        │   │
    │    └────────────────────────────────────────────────────────┘   │
    │                              │                                  │
    │    ┌─────────────────────────┴─────────────────────────┐       │
    │    │                WORLD INTERFACE                     │       │
    │    │  ┌─────────┐  ┌──────────┐  ┌───────────┐        │       │
    │    │  │ Gmail   │  │ Calendar │  │   Drive   │  ...   │       │
    │    │  │ Adapter │  │  Adapter │  │  Adapter  │        │       │
    │    │  └─────────┘  └──────────┘  └───────────┘        │       │
    │    └───────────────────────────────────────────────────┘       │
    │                              │                                  │
    │                         EXTERNAL WORLD                         │
    └─────────────────────────────────────────────────────────────────┘

This is not a chatbot.
This is not an automation tool.
This is a COGNITIVE SYSTEM.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import json

# Import all brain components
from .cognitive_core import CognitiveCore
from .memory_systems import MemorySystems
from .consciousness import ConsciousnessLoop, create_consciousness
from .learning import LearningEngine, get_learning_engine
from .world_interface import WorldInterface, get_world_interface
from .adapters import (
    AdapterRegistry,
    GmailAdapter,
    CalendarAdapter,
    DriveAdapter,
    ServiceType,
)

logger = logging.getLogger(__name__)


@dataclass
class BrainConfig:
    """Configuration for the unified brain."""
    storage_path: Path
    
    # LLM settings
    llm_model: str = "gpt-4o-mini"
    llm_api_key: Optional[str] = None
    
    # Consciousness settings
    consciousness_cycle_ms: int = 500
    
    # Memory settings
    max_working_memory: int = 20
    max_episodic_memory: int = 1000
    
    # Learning settings
    learning_enabled: bool = True
    consolidation_interval: int = 100
    
    # Proactive settings
    proactive_enabled: bool = True
    observation_interval: int = 60  # seconds


class UnifiedBrain:
    """
    The Unified Brain - a complete cognitive system.
    
    This class integrates all brain components into a cohesive whole.
    """
    
    def __init__(self, config: BrainConfig):
        self._config = config
        self._storage_path = config.storage_path
        
        # Ensure storage directories exist
        self._storage_path.mkdir(parents=True, exist_ok=True)
        (self._storage_path / "memory").mkdir(exist_ok=True)
        (self._storage_path / "learning").mkdir(exist_ok=True)
        
        # Initialize components (lazy initialization)
        self._cognitive_core: Optional[CognitiveCore] = None
        self._memory_systems: Optional[MemorySystems] = None
        self._world_interface: Optional[WorldInterface] = None
        self._learning_engine: Optional[LearningEngine] = None
        self._consciousness: Optional[ConsciousnessLoop] = None
        self._adapter_registry: Optional[AdapterRegistry] = None
        
        # State
        self._initialized = False
        self._awake = False
        
        # Event handlers
        self._event_handlers: Dict[str, List[Callable]] = {
            "wake": [],
            "sleep": [],
            "thought": [],
            "action": [],
            "insight": [],
            "error": [],
        }
        
        logger.info(f"Unified Brain created (storage: {self._storage_path})")
    
    # === Initialization ===
    
    async def initialize(self):
        """Initialize all brain components."""
        if self._initialized:
            return
        
        logger.info("Initializing Unified Brain...")
        
        # 1. Initialize memory systems
        self._memory_systems = MemorySystems(
            storage_path=self._storage_path / "memory",
            working_capacity=self._config.max_working_memory,
        )
        await self._memory_systems.initialize()
        logger.info("Memory systems initialized")
        
        # 2. Initialize cognitive core
        self._cognitive_core = CognitiveCore(
            memory=self._memory_systems,
            llm_model=self._config.llm_model,
            api_key=self._config.llm_api_key,
        )
        await self._cognitive_core.initialize()
        logger.info("Cognitive core initialized")
        
        # 3. Initialize learning engine
        self._learning_engine = get_learning_engine(
            storage_path=self._storage_path / "learning",
        )
        await self._learning_engine.initialize()
        logger.info("Learning engine initialized")
        
        # 4. Initialize world interface and adapters
        self._adapter_registry = AdapterRegistry()
        self._world_interface = get_world_interface(
            storage_path=self._storage_path,
        )
        logger.info("World interface initialized")
        
        # 5. Initialize consciousness loop
        self._consciousness = create_consciousness(
            cognitive_core=self._cognitive_core,
            world_interface=self._world_interface,
            learning_engine=self._learning_engine,
            storage_path=self._storage_path,
        )
        
        # Wire consciousness events
        self._consciousness.on("intention_formed", self._on_intention)
        self._consciousness.on("action_taken", self._on_action)
        self._consciousness.on("insight_gained", self._on_insight)
        
        logger.info("Consciousness loop initialized")
        
        self._initialized = True
        logger.info("Unified Brain initialization complete")
    
    # === Lifecycle ===
    
    async def wake(self):
        """Wake up the brain - start continuous awareness."""
        if not self._initialized:
            await self.initialize()
        
        if self._awake:
            return
        
        logger.info("Waking the brain...")
        
        # Start consciousness loop
        await self._consciousness.wake()
        
        self._awake = True
        
        # Trigger event handlers
        await self._trigger_event("wake")
        
        logger.info("Brain is awake and aware")
    
    async def sleep(self):
        """Put the brain to sleep - stop continuous awareness."""
        if not self._awake:
            return
        
        logger.info("Putting brain to sleep...")
        
        # Stop consciousness loop (this consolidates learning)
        await self._consciousness.sleep()
        
        self._awake = False
        
        # Trigger event handlers
        await self._trigger_event("sleep")
        
        logger.info("Brain is asleep")
    
    # === External Interface ===
    
    async def think(self, input_text: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Process input and generate a thoughtful response.
        
        This is the main entry point for interactions.
        """
        if not self._initialized:
            await self.initialize()
        
        # If consciousness is running, use it
        if self._awake:
            response = await self._consciousness.receive_input(input_text, source="user")
        else:
            # Direct cognitive processing
            response = await self._cognitive_core.answer(input_text, context)
        
        # Learn from this interaction
        if self._config.learning_enabled:
            self._learning_engine.record_episode(
                stimulus=input_text,
                response=json.dumps(response, default=str),
                outcome="responded",
                success=True,
                context=context or {},
            )
        
        await self._trigger_event("thought", {"input": input_text, "response": response})
        
        return response
    
    async def act(self, action: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute an action in the world.
        
        Uses the world interface to safely execute actions.
        """
        if not self._initialized:
            await self.initialize()
        
        # Execute through world interface
        result = await self._world_interface.execute(action, parameters)
        
        # Learn from this action
        if self._config.learning_enabled:
            self._learning_engine.record_episode(
                stimulus=f"action:{action}",
                response=json.dumps(result, default=str),
                outcome="success" if result.get("success") else "failure",
                success=result.get("success", False),
                context=parameters,
            )
        
        await self._trigger_event("action", {"action": action, "result": result})
        
        return result
    
    async def remember(self, content: str, tags: Optional[List[str]] = None) -> str:
        """Store something in long-term memory."""
        if not self._initialized:
            await self.initialize()
        
        memory_id = await self._memory_systems.store(content, tags=tags or [])
        return memory_id
    
    async def recall(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Recall memories related to a query."""
        if not self._initialized:
            await self.initialize()
        
        memories = await self._memory_systems.recall(query, limit=limit)
        return memories
    
    def anticipate(self, what: str, when: Optional[datetime] = None):
        """Set up an anticipation for something."""
        if not self._consciousness:
            return
        
        self._consciousness.add_anticipation(what, expected_time=when)
    
    # === Service Integration ===
    
    def connect_service(self, service_name: str, connector):
        """
        Connect an external service to the brain.
        
        This wires a service connector through an adapter to the world interface.
        """
        # Create adapter for the service
        adapter = self._adapter_registry.create_adapter(service_name, connector)
        
        if adapter:
            # Register with world interface
            self._world_interface.register_adapter(adapter.service_type, adapter)
            logger.info(f"Connected service: {service_name}")
            return True
        
        logger.warning(f"No adapter available for service: {service_name}")
        return False
    
    def get_connected_services(self) -> List[str]:
        """Get list of connected services."""
        if not self._world_interface:
            return []
        return [s.value for s in self._world_interface.get_services()]
    
    def get_capabilities(self) -> Dict[str, List[str]]:
        """Get all available capabilities from connected services."""
        if not self._adapter_registry:
            return {}
        return self._adapter_registry.get_capabilities()
    
    # === Introspection ===
    
    def get_state(self) -> Dict[str, Any]:
        """Get current brain state."""
        state = {
            "initialized": self._initialized,
            "awake": self._awake,
            "storage_path": str(self._storage_path),
        }
        
        if self._consciousness:
            state["consciousness"] = self._consciousness.get_state()
        
        if self._learning_engine:
            state["learning"] = {
                "lessons_count": len(self._learning_engine._lessons),
                "patterns_count": len(self._learning_engine._patterns),
            }
        
        if self._world_interface:
            state["services"] = self.get_connected_services()
            state["capabilities"] = self.get_capabilities()
        
        return state
    
    def get_consciousness_stream(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent moments from consciousness stream."""
        if not self._consciousness:
            return []
        return self._consciousness.get_stream(limit)
    
    def get_intentions(self) -> List[Dict[str, Any]]:
        """Get current intentions."""
        if not self._consciousness:
            return []
        return self._consciousness.get_intentions()
    
    def get_anticipations(self) -> List[Dict[str, Any]]:
        """Get current anticipations."""
        if not self._consciousness:
            return []
        return self._consciousness.get_anticipations()
    
    # === Event Handling ===
    
    def on(self, event: str, handler: Callable):
        """Subscribe to brain events."""
        if event in self._event_handlers:
            self._event_handlers[event].append(handler)
    
    async def _trigger_event(self, event: str, data: Optional[Dict[str, Any]] = None):
        """Trigger event handlers."""
        for handler in self._event_handlers.get(event, []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(data or {})
                else:
                    handler(data or {})
            except Exception as e:
                logger.error(f"Event handler error for {event}: {e}")
    
    def _on_intention(self, data: Dict[str, Any]):
        """Handle intention formed event."""
        logger.debug(f"Intention formed: {data.get('description', '')[:50]}")
    
    def _on_action(self, data: Dict[str, Any]):
        """Handle action taken event."""
        logger.info(f"Action taken: {data.get('intention', {}).get('action', '')}")
    
    def _on_insight(self, data: Dict[str, Any]):
        """Handle insight gained event."""
        patterns = data.get("patterns", [])
        logger.info(f"Gained {len(patterns)} insights")


# === Factory Function ===

def create_brain(
    storage_path: str = "~/.telic",
    llm_model: str = "gpt-4o-mini",
    llm_api_key: Optional[str] = None,
) -> UnifiedBrain:
    """
    Create a Unified Brain instance.
    
    Args:
        storage_path: Where to store brain data (~/.telic by default)
        llm_model: LLM model to use for cognition
        llm_api_key: API key for LLM provider
    
    Returns:
        A new UnifiedBrain instance
    """
    path = Path(storage_path).expanduser()
    
    config = BrainConfig(
        storage_path=path,
        llm_model=llm_model,
        llm_api_key=llm_api_key,
    )
    
    return UnifiedBrain(config)


# === Quick Start ===

async def quick_start(
    api_key: Optional[str] = None,
    wake: bool = True,
) -> UnifiedBrain:
    """
    Quick start the brain with sensible defaults.
    
    Args:
        api_key: LLM API key (uses env if not provided)
        wake: Whether to wake up consciousness immediately
    
    Returns:
        Ready-to-use brain instance
    """
    import os
    
    key = api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    
    brain = create_brain(
        storage_path="~/.telic",
        llm_api_key=key,
    )
    
    await brain.initialize()
    
    if wake:
        await brain.wake()
    
    return brain
