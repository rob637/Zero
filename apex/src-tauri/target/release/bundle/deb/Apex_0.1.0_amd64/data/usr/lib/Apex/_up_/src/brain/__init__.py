"""
Apex Brain - Cognitive Architecture
====================================

This is not a chatbot. This is not a wrapper.
This is a cognitive system that thinks, learns, and grows.

Architecture inspired by human cognition:

┌─────────────────────────────────────────────────────────────────┐
│                        COGNITIVE CORE                           │
│                                                                 │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐       │
│   │ PERCEPTION  │───▶│  ATTENTION  │───▶│  REASONING  │       │
│   │   Stream    │    │   Focus     │    │   Engine    │       │
│   └─────────────┘    └─────────────┘    └─────────────┘       │
│          │                  │                  │               │
│          ▼                  ▼                  ▼               │
│   ┌─────────────────────────────────────────────────────┐     │
│   │                 MEMORY SYSTEMS                       │     │
│   │                                                      │     │
│   │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │     │
│   │  │ Working  │  │ Episodic │  │ Semantic │          │     │
│   │  │ Memory   │  │ Memory   │  │ Memory   │          │     │
│   │  │ (now)    │  │ (events) │  │ (facts)  │          │     │
│   │  └──────────┘  └──────────┘  └──────────┘          │     │
│   │                                                      │     │
│   │  ┌──────────┐  ┌──────────┐                         │     │
│   │  │Procedural│  │Predictive│                         │     │
│   │  │ Memory   │  │ Models   │                         │     │
│   │  │ (how-to) │  │ (future) │                         │     │
│   │  └──────────┘  └──────────┘                         │     │
│   └─────────────────────────────────────────────────────┘     │
│                           │                                    │
│                           ▼                                    │
│   ┌─────────────────────────────────────────────────────┐     │
│   │              METACOGNITION LAYER                     │     │
│   │  Self-reflection, confidence estimation, learning   │     │
│   └─────────────────────────────────────────────────────┘     │
│                           │                                    │
│                           ▼                                    │
│   ┌─────────────────────────────────────────────────────┐     │
│   │                   ACTION LAYER                       │     │
│   │   Execute, observe outcomes, update beliefs          │     │
│   └─────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────┘

This is the new new thing.
"""

from .cognitive_core import CognitiveCore, Thought, ThoughtType
from .memory_systems import (
    MemorySystems,
    WorkingMemory,
    EpisodicMemory,
    SemanticMemory,
    ProceduralMemory,
    Episode,
    Concept,
    Procedure,
)
from .attention import AttentionSystem, Salience, AttentionFocus
from .reasoning import ReasoningEngine, ReasoningChain, Hypothesis
from .perception import PerceptionStream, Percept, PerceptType
from .metacognition import Metacognition, KnowledgeBelief, ConfidenceRecord
from .predictive import PredictiveModel, Prediction, TimeHorizon

# New cognitive architecture components
from .world_interface import WorldInterface, WorldAction, WorldObservation, get_world_interface
from .learning import LearningEngine, Lesson, LessonType, get_learning_engine
from .consciousness import ConsciousnessLoop, ConsciousnessState, Intention, create_consciousness
from .adapters import (
    ServiceAdapter,
    AdapterRegistry,
    GmailAdapter,
    CalendarAdapter,
    DriveAdapter,
    ServiceType,
    AdapterResult,
)
from .brain import UnifiedBrain, BrainConfig, create_brain, quick_start

# Primitive-based architecture (composable capabilities)
from .primitives import (
    Primitive,
    PrimitiveResult,
    PrimitiveRegistry,
    FilePrimitive,
    DocumentPrimitive,
    ComputePrimitive,
    EmailPrimitive,
    CalendarPrimitive,
    ContactsPrimitive,
    KnowledgePrimitive,
    create_primitive_registry,
)
from .planner import (
    TaskPlanner,
    ExecutionPlan,
    PlanStep,
    StepStatus,
    create_planner,
)

__all__ = [
    # Cognitive Core
    "CognitiveCore",
    "Thought",
    "ThoughtType",
    # Memory Systems
    "MemorySystems",
    "WorkingMemory",
    "EpisodicMemory",
    "SemanticMemory",
    "ProceduralMemory",
    "Episode",
    "Concept",
    "Procedure",
    # Attention
    "AttentionSystem",
    "Salience",
    "AttentionFocus",
    # Reasoning
    "ReasoningEngine",
    "ReasoningChain",
    "Hypothesis",
    # Perception
    "PerceptionStream",
    "Percept",
    "PerceptType",
    # Metacognition
    "Metacognition",
    "Belief",
    "Confidence",
    # Predictive
    "PredictiveModel",
    "Prediction",
    "TimeHorizon",
    # World Interface
    "WorldInterface",
    "WorldAction",
    "WorldObservation",
    "get_world_interface",
    # Learning
    "LearningEngine",
    "Lesson",
    "LessonType",
    "get_learning_engine",
    # Consciousness
    "ConsciousnessLoop",
    "ConsciousnessState",
    "Intention",
    "create_consciousness",
    # Adapters
    "ServiceAdapter",
    "AdapterRegistry",
    "GmailAdapter",
    "CalendarAdapter",
    "DriveAdapter",
    "ServiceType",
    "AdapterResult",
    # Unified Brain (the crown jewel)
    "UnifiedBrain",
    "BrainConfig",
    "create_brain",
    "quick_start",
    # Primitives (composable capabilities)
    "Primitive",
    "PrimitiveResult",
    "PrimitiveRegistry",
    "FilePrimitive",
    "DocumentPrimitive",
    "ComputePrimitive",
    "EmailPrimitive",
    "CalendarPrimitive",
    "ContactsPrimitive",
    "KnowledgePrimitive",
    "create_primitive_registry",
    # Planner (LLM-powered decomposition)
    "TaskPlanner",
    "ExecutionPlan",
    "PlanStep",
    "StepStatus",
    "create_planner",
]
