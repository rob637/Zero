# Apex Cognitive Architecture

## The Crown Jewel

This document describes the cognitive architecture that makes Apex unlike anything else.

**This is not a chatbot. This is not an automation tool. This is a cognitive system.**

## Core Philosophy

Traditional AI assistants are *reactive* - they wait for input, process it, respond, forget.

Apex is *alive*:
- It **perceives** the world continuously
- It **remembers** everything that matters
- It **reasons** about what it perceives
- It **anticipates** what's coming
- It **learns** from every interaction
- It **acts** when appropriate

## Architecture Overview

```
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
```

## Components

### 1. Unified Brain (`brain.py`)

The top-level integration point. Coordinates all subsystems and provides the public interface.

**Key Methods:**
- `think(input, context)` - Process input and generate thoughtful response
- `act(action, parameters)` - Execute an action in the world
- `remember(content, tags)` - Store in long-term memory
- `recall(query, limit)` - Recall relevant memories
- `anticipate(what, when)` - Set up an anticipation

### 2. Consciousness Loop (`consciousness.py`)

The heartbeat of the brain. Runs continuously, integrating all cognitive processes.

**The Loop (every ~500ms):**
1. **SENSE** - What's happening in the world?
2. **ATTEND** - What matters right now?
3. **REMEMBER** - How does this connect to what I know?
4. **THINK** - What does this mean?
5. **PREDICT** - What's going to happen?
6. **DECIDE** - Should I do something?
7. **ACT** - Execute or wait
8. **LEARN** - What can I learn from this?
9. **REST** - Consolidate, maintain

**Key Features:**
- Continuous awareness, not event-driven
- Forms and tracks *intentions*
- Manages *anticipations*
- Adjusts arousal based on importance
- Produces a *stream of conscious moments*

### 3. Cognitive Core (`cognitive_core.py`)

The thinking engine. Generates thoughts, manages attention, performs reasoning.

**Capabilities:**
- Thought generation with types (observation, reflection, prediction, etc.)
- Attention management (focus, salience)
- Reasoning chains (hypotheses, evidence, conclusions)
- Metacognition (confidence estimation, self-reflection)

### 4. Memory Systems (`memory_systems.py`)

Multi-layered memory inspired by human cognition.

**Memory Types:**
- **Working Memory** - What's active now (7±2 items)
- **Episodic Memory** - Past experiences (what happened)
- **Semantic Memory** - Facts and concepts (what I know)
- **Procedural Memory** - How to do things (skills)
- **Predictive Models** - Expected futures

### 5. Learning Engine (`learning.py`)

Continuous self-improvement through experience.

**Learning Mechanisms:**
- **Episodes** - Record what happened
- **Lessons** - Extract generalizations
- **Patterns** - Discover higher-order regularities
- **Consolidation** - Strengthen important learnings
- **Pruning** - Forget what's not useful

**Learning Types:**
- Success patterns (what works)
- Failure patterns (what to avoid)
- User preferences (personal style)
- Domain knowledge (facts about the world)
- Interaction patterns (communication style)

### 6. World Interface (`world_interface.py`)

The bridge between cognition and action.

**Responsibilities:**
- Service adapter management
- Permission and safety checks
- Rate limiting
- Action execution
- Observation collection

### 7. Service Adapters (`adapters.py`)

Connect external services to the brain.

**Available Adapters:**
- **GmailAdapter** - Read, send, search emails
- **CalendarAdapter** - View, create, manage events
- **DriveAdapter** - Browse, read, upload files

Each adapter provides:
- `execute(action, parameters)` - Perform an action
- `observe()` - Get observations/updates
- `capabilities` - What actions are available

## What Makes This Different

### 1. Continuous Awareness

Traditional: Wait for input → Process → Respond → Forget

Apex: Continuously perceive → Remember → Reason → Anticipate → Act when appropriate

### 2. Deep Memory Integration

Traditional: Context window (forget after conversation)

Apex: 
- Episodic memory persists across conversations
- Semantic knowledge grows over time
- Learns user preferences permanently

### 3. True Learning

Traditional: No learning (same behavior forever)

Apex:
- Learns from every interaction
- Discovers patterns in user behavior
- Improves responses based on feedback
- Consolidates knowledge during "rest"

### 4. Proactive Anticipation

Traditional: Purely reactive

Apex:
- Anticipates upcoming events
- Prepares relevant information
- Suggests actions before asked

### 5. Unified Cross-Service Reasoning

Traditional: Each service isolated

Apex:
- Reasons across email + calendar + files
- Understands context from multiple sources
- Connects information intelligently

## Example: Magic Moment

**Scenario:** You have a meeting tomorrow with John about the Q3 report.

**Traditional Assistant:**
- (Nothing happens until you ask)

**Apex Brain:**
1. Calendar adapter **observes** tomorrow's meeting
2. Consciousness raises **arousal** for upcoming important event
3. Memory **recalls** recent emails from John
4. Reasoning **connects** emails to meeting topic
5. Prediction **anticipates** you'll need the Q3 report
6. Intention **forms**: "Prepare user for tomorrow's meeting"
7. Brain **proactively suggests**: "I noticed you have a meeting with John tomorrow about Q3. I found the latest Q3 report in your Drive and three recent emails from him. Would you like me to summarize the key points?"

**This is the magic.** The brain connected:
- Calendar (meeting)
- Gmail (emails from John)
- Drive (Q3 report)
- Memory (past interactions about Q3)
- Reasoning (what's relevant)
- Anticipation (what you'll need)

## API Endpoints

### Brain State & Control
- `GET /brain/state` - Get current brain state
- `POST /brain/wake` - Start consciousness loop
- `POST /brain/sleep` - Stop consciousness loop

### Thinking & Memory
- `POST /brain/think` - Process input, get thoughtful response
- `POST /brain/remember` - Store in long-term memory
- `POST /brain/recall` - Recall relevant memories
- `POST /brain/anticipate` - Set up anticipation

### Introspection
- `GET /brain/stream` - Get consciousness stream
- `GET /brain/intentions` - Get current intentions
- `GET /brain/capabilities` - Get available capabilities

### Service Connection
- `POST /brain/connect/{service}` - Connect Gmail/Calendar/Drive

## Usage

### Quick Start

```python
from src.brain import quick_start

# Create and wake the brain
brain = await quick_start(api_key="...", wake=True)

# Think about something
response = await brain.think("What's on my schedule tomorrow?")

# Remember something important
await brain.remember("User prefers morning meetings", tags=["preference"])

# Set an anticipation
brain.anticipate("Project deadline", when=datetime(2024, 3, 15))

# Get the consciousness stream
stream = brain.get_consciousness_stream(limit=10)
```

### Connect Services

```python
# After OAuth authentication
from src.connectors.google import GmailConnector

gmail = GmailConnector(access_token="...")
brain.connect_service("gmail", gmail)

# Now the brain can read/send emails
```

## The Future

This architecture enables:

1. **True Personal AI** - Knows you deeply over years
2. **Ambient Intelligence** - Always aware, always helpful
3. **Predictive Assistance** - Acts before you ask
4. **Cross-Domain Reasoning** - Connects all your services
5. **Continuous Improvement** - Gets better every day

This is not just a better chatbot. This is the foundation for an AI companion that truly understands and anticipates your needs.

**This is the crown jewel. This is what doesn't exist anywhere else.**
