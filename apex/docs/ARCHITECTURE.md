# Technical Architecture: APEX
## Deep Dive for Developers

---

## 0. Architectural Philosophy

> **"Build the platform, not the feature."**

Apex is designed as an **extensible AI operating layer**, not a file organizer with extra features bolted on. Every architectural decision serves this principle:

| Principle | Implementation |
|-----------|----------------|
| **Skills are plugins** | New capabilities = new Skill module, not core changes |
| **Memory is shared** | All skills read/write the same knowledge graph |
| **MCP is the glue** | App integrations are hot-swappable MCP servers |
| **Core is stable** | Platform (daemon, memory, orchestrator) rarely changes |

This means when we add browser automation, email integration, or voice control, we're adding skills—not rewriting Apex.

---

## 1. System Overview

Apex follows a **Hybrid Agent Architecture** with clear separation between:
- **Core Platform** — Memory, orchestration, security (the brain)
- **Skill Layer** — Pluggable capabilities (file org, browser, comms)
- **MCP Layer** — App connectivity (filesystem, browser, APIs)
- **Cloud Reasoning** — LLM APIs for complex understanding

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            USER'S PC                                        │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │                         APEX CORE                                     │ │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │ │
│  │  │  Daemon     │  │  Memory     │  │  Task       │  │  Security   │  │ │
│  │  │  Manager    │──│  Engine     │──│  Orchestor  │──│  Gateway    │  │ │
│  │  │  (Rust)     │  │  (Mem0)     │  │  (LangGraph)│  │  (Scrubber) │  │ │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  │ │
│  │         │                │                │                │         │ │
│  │         └────────────────┴────────────────┴────────────────┘         │ │
│  │                                   │                                   │ │
│  └───────────────────────────────────┼───────────────────────────────────┘ │
│                                      │                                      │
│  ┌───────────────────────────────────┼───────────────────────────────────┐ │
│  │                         MCP LAYER │                                   │ │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐    │ │
│  │  │Filesys  │  │ Browser │  │ Google  │  │  Slack  │  │ Custom  │    │ │
│  │  │ MCP     │  │  MCP    │  │ Drive   │  │  MCP    │  │  MCP    │    │ │
│  │  └─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘    │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │                         UI LAYER                                      │ │
│  │  ┌─────────┐  ┌─────────────────┐  ┌─────────────────────────────┐   │ │
│  │  │  Orb    │  │    Sidebar      │  │         HUD Overlay         │   │ │
│  │  │(Tray)   │  │  (Tauri Window) │  │    (Transparent Window)     │   │ │
│  │  └─────────┘  └─────────────────┘  └─────────────────────────────┘   │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      │ HTTPS (TLS 1.3)
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            CLOUD SERVICES                                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐       │
│  │  OpenAI     │  │  Anthropic  │  │  Google     │  │  Groq       │       │
│  │  GPT-4o     │  │  Claude 3.5 │  │  Gemini     │  │  (Fast)     │       │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘       │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Skill System Architecture

### 2.0 The Skill Registry

The Skill System is what makes Apex a platform, not a product. Every capability is a Skill.

```python
# core/apex/skills/base.py

from abc import ABC, abstractmethod
from typing import List, Dict, Any
from enum import Enum

class PermissionTier(Enum):
    READ_ONLY = 1      # Can read files/data, no modifications
    ASSISTANT = 2       # Can draft/prepare, user executes
    FULL_AGENT = 3      # Can execute with HITL approval

class Skill(ABC):
    """Base class for all Apex skills.
    
    Every capability in Apex is a Skill. The core platform never 
    directly manipulates files, browsers, or apps - it delegates 
    to Skills which handle domain-specific logic.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier: 'file-organizer', 'browser-agent'"""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """Human/LLM readable description of capability."""
        pass
    
    @property
    @abstractmethod  
    def version(self) -> str:
        """Semantic version for compatibility."""
        pass
    
    @property
    @abstractmethod
    def required_mcps(self) -> List[str]:
        """MCP servers this skill needs: ['filesystem', 'browser']"""
        pass
    
    @property
    def permission_level(self) -> PermissionTier:
        """Default permission requirement."""
        return PermissionTier.ASSISTANT
    
    @abstractmethod
    async def can_handle(self, intent: str, context: 'Context') -> float:
        """Return confidence 0-1 that this skill handles the intent.
        
        The orchestrator calls this on all registered skills to 
        determine which skill(s) to invoke.
        """
        pass
    
    @abstractmethod
    async def plan(self, request: str, context: 'Context') -> 'TaskPlan':
        """Generate an execution plan for the request.
        
        Plans are inspectable, reviewable, and can be modified 
        before execution. This enables HITL.
        """
        pass
    
    @abstractmethod
    async def execute(self, plan: 'TaskPlan') -> 'Result':
        """Execute the approved plan.
        
        Must respect HITL checkpoints defined in the plan.
        """
        pass


class SkillRegistry:
    """Central registry for all available skills."""
    
    def __init__(self):
        self._skills: Dict[str, Skill] = {}
    
    def register(self, skill: Skill) -> None:
        """Register a skill with the platform."""
        self._skills[skill.name] = skill
        
    def unregister(self, name: str) -> None:
        """Remove a skill (for hot-reloading)."""
        del self._skills[name]
    
    async def find_skills_for_intent(self, intent: str, context: 'Context') -> List[tuple[Skill, float]]:
        """Find skills that can handle this intent, sorted by confidence."""
        results = []
        for skill in self._skills.values():
            confidence = await skill.can_handle(intent, context)
            if confidence > 0.1:  # Minimum threshold
                results.append((skill, confidence))
        return sorted(results, key=lambda x: x[1], reverse=True)
```

### 2.1 Skill: File Organizer (MVP)

```python
# core/apex/skills/file_organizer.py

class FileOrganizerSkill(Skill):
    """The first skill: intelligent file management."""
    
    name = "file-organizer"
    description = """Organizes, cleans, and manages files on the local filesystem.
    Capabilities: find duplicates, categorize files, rename intelligently, 
    archive old files, clean up folders, semantic file search."""
    version = "1.0.0"
    required_mcps = ["filesystem"]
    permission_level = PermissionTier.FULL_AGENT
    
    # Intent patterns this skill handles
    INTENT_PATTERNS = [
        r"clean|organize|tidy|sort",
        r"find|search|locate.*file",
        r"duplicate|similar.*photo|image",
        r"delete|remove|archive.*old",
        r"rename|move.*folder|file",
    ]
    
    async def can_handle(self, intent: str, context: Context) -> float:
        """High confidence for file-related requests."""
        intent_lower = intent.lower()
        
        # Check against patterns
        matches = sum(1 for p in self.INTENT_PATTERNS 
                      if re.search(p, intent_lower))
        
        # Boost if context contains file paths
        if context.has_file_references:
            matches += 1
            
        return min(matches * 0.3, 1.0)
    
    async def plan(self, request: str, context: Context) -> TaskPlan:
        """Use LLM to create a file operation plan."""
        # ... implementation
        pass
```

### 2.2 Future Skills (Designed Now, Built Later)

```python
# These interfaces exist from Day 1, implementations come later

class BrowserSkill(Skill):
    """v1.1: Web browsing, research, form filling."""
    name = "browser-agent"
    required_mcps = ["browser", "filesystem"]  # Save downloads
    
class CommunicationSkill(Skill):
    """v1.2: Email, Slack, messaging."""
    name = "communication-hub"
    required_mcps = ["email", "slack", "calendar"]

class ScreenUnderstandingSkill(Skill):
    """v2.0: OCR, visual context awareness."""
    name = "screen-reader"
    required_mcps = ["screen-capture"]
```

---

## 3. Core Platform Components

### 3.1 Daemon Manager (Rust)

**Purpose:** Persistent background service that manages lifecycle of all Apex components.

**Responsibilities:**
- Start/stop on system boot
- Health monitoring of subprocesses
- IPC (Inter-Process Communication) hub
- System tray integration
- Native notifications

**Technology Choice: Rust**
- Memory safety without garbage collection
- Minimal resource footprint for always-on daemon
- Easy system tray integration via `tray-icon` crate
- Fast startup time

```rust
// Conceptual structure
struct ApexDaemon {
    memory_engine: MemoryEngine,
    task_orchestrator: TaskOrchestrator,
    mcp_registry: McpRegistry,
    ui_bridge: UiBridge,
    config: ApexConfig,
}

impl ApexDaemon {
    async fn handle_user_request(&self, input: UserInput) -> Result<Response> {
        // 1. Query memory for context
        let context = self.memory_engine.get_relevant_context(&input).await?;
        
        // 2. Plan task with orchestrator
        let plan = self.task_orchestrator.plan(&input, &context).await?;
        
        // 3. If high-risk, request HITL approval
        if plan.requires_approval() {
            self.ui_bridge.request_approval(&plan).await?;
        }
        
        // 4. Execute plan
        let result = self.task_orchestrator.execute(plan).await?;
        
        // 5. Update memory
        self.memory_engine.record_outcome(&input, &result).await?;
        
        Ok(result)
    }
}
```

### 3.2 Memory Engine (The Shared Brain)

**Purpose:** Persistent storage of user facts, preferences, and task history. **This is what makes Apex more than a chatbot.**

> Every skill reads from and writes to Memory. When File Organizer learns "User prefers PDFs in Documents/", Browser Skill uses that when downloading files. Memory is the connective tissue.

**Architecture:**

```
┌─────────────────────────────────────────────────────────────┐
│                    MEMORY ENGINE                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────┐    ┌─────────────────────────┐   │
│  │   FACT STORE        │    │   TASK HISTORY          │   │
│  │   (Semantic)        │    │   (Chronological)       │   │
│  │                     │    │                         │   │
│  │  "User prefers PDF" │    │  [2026-03-29 10:00]    │   │
│  │  "Sarah = Marketing"│    │  Cleaned Downloads      │   │
│  │  "Lives in London"  │    │  Result: 14 files moved │   │
│  └─────────────────────┘    └─────────────────────────┘   │
│            │                           │                   │
│            └───────────┬───────────────┘                   │
│                        ▼                                   │
│  ┌─────────────────────────────────────────────────────┐  │
│  │              VECTOR DATABASE                         │  │
│  │              (ChromaDB / Qdrant)                     │  │
│  │                                                      │  │
│  │  • Embedding model: all-MiniLM-L6-v2 (local)        │  │
│  │  • Similarity search for context retrieval          │  │
│  │  • Clustering for fact deduplication                │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Key Operations:**

| Operation | Description |
|-----------|-------------|
| `store_fact(fact, source)` | Store new fact with embedding |
| `query_context(input, k=10)` | Retrieve k most relevant memories |
| `update_fact(old, new)` | Handle contradictions |
| `decay_memories(threshold)` | Remove stale/low-confidence facts |
| `export_memories()` | User data portability |

**Memory Schema:**

```python
class Memory:
    id: str                    # UUID
    content: str               # The actual fact/event
    embedding: List[float]     # Vector representation
    memory_type: Literal["fact", "preference", "task", "knowledge"]
    source: str                # What generated this memory
    timestamp: datetime        
    confidence: float          # 0.0 - 1.0
    access_count: int          # For decay algorithm
    last_accessed: datetime
    metadata: Dict             # Flexible extra data
```

### 3.3 Task Orchestrator (LangGraph)

**Purpose:** Route requests to skills, plan multi-step tasks, enforce HITL.

The Orchestrator is the "traffic controller" that:
1. Receives user intent
2. Queries Memory for context
3. Asks each Skill "can you handle this?"
4. Delegates to the best skill(s)
5. Enforces approval workflows

**Why LangGraph:**
- Native support for cycles and conditionals in agent workflows
- Built-in state management
- Easy human-in-the-loop integration
- Streaming support for real-time UI updates

**Task Flow Example:**

```python
from langgraph.graph import StateGraph, END

# Define the task state
class TaskState(TypedDict):
    user_input: str
    context: List[Memory]
    plan: List[Step]
    current_step: int
    results: List[StepResult]
    requires_approval: bool
    approved: bool

# Define the workflow
workflow = StateGraph(TaskState)

# Add nodes
workflow.add_node("understand", understand_request)
workflow.add_node("plan", create_execution_plan)
workflow.add_node("check_risk", assess_risk_level)
workflow.add_node("request_approval", get_hitl_approval)
workflow.add_node("execute", execute_step)
workflow.add_node("report", generate_report)

# Add edges
workflow.add_edge("understand", "plan")
workflow.add_edge("plan", "check_risk")
workflow.add_conditional_edges(
    "check_risk",
    lambda s: "request_approval" if s["requires_approval"] else "execute"
)
workflow.add_conditional_edges(
    "request_approval",
    lambda s: "execute" if s["approved"] else END
)
workflow.add_conditional_edges(
    "execute",
    lambda s: "execute" if s["current_step"] < len(s["plan"]) else "report"
)
workflow.add_edge("report", END)

# Compile
app = workflow.compile()
```

### 3.4 Security Gateway

**Purpose:** All communications between local and cloud pass through this gateway.

**Components:**

```
┌─────────────────────────────────────────────────────────────┐
│                   SECURITY GATEWAY                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              DATA SCRUBBER                           │   │
│  │                                                      │   │
│  │  Patterns detected and redacted:                     │   │
│  │  • SSN: XXX-XX-XXXX → [REDACTED_SSN]                │   │
│  │  • Credit Card: XXXX-XXXX-XXXX-XXXX → [REDACTED_CC] │   │
│  │  • Email passwords → [REDACTED_PASSWORD]            │   │
│  │  • API keys → [REDACTED_API_KEY]                    │   │
│  │  • Custom patterns (user-defined)                    │   │
│  └─────────────────────────────────────────────────────┘   │
│                          │                                  │
│                          ▼                                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              AUDIT LOGGER                            │   │
│  │                                                      │   │
│  │  Every API call logged:                              │   │
│  │  • Timestamp                                         │   │
│  │  • Destination (which LLM)                          │   │
│  │  • Payload size (bytes sent)                        │   │
│  │  • Redactions applied                               │   │
│  │  • Response time                                    │   │
│  └─────────────────────────────────────────────────────┘   │
│                          │                                  │
│                          ▼                                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              RATE LIMITER                            │   │
│  │                                                      │   │
│  │  User-configurable spending limits:                  │   │
│  │  • Max API calls per hour                           │   │
│  │  • Max $ spent per day                              │   │
│  │  • Alert thresholds                                 │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. MCP Integration Layer

### 3.1 What is MCP?

Model Context Protocol (MCP) is the 2026 standard for AI-app interoperability. Instead of writing custom integrations for every app, we implement MCP clients that connect to MCP servers.

### 3.2 Core MCP Servers (Required for MVP)

| Server | Capabilities | Priority |
|--------|-------------|----------|
| **Filesystem** | Read/write/move/delete files, list directories | P0 |
| **Browser** | Navigate, click, type, extract content | P0 |
| **Memory** | Store/retrieve from Apex memory (internal) | P0 |
| **Slack** | Read/send messages, list channels | P1 |
| **Google Drive** | List/read/write cloud files | P1 |
| **Outlook/Gmail** | Read/draft/send emails | P1 |
| **Calendar** | Read/create events | P1 |
| **Spotify** | Playback control, playlist management | P2 |

### 3.3 MCP Client Implementation

```python
from mcp import Client, Tool

class ApexMcpHub:
    """Central hub for all MCP connections."""
    
    def __init__(self):
        self.servers: Dict[str, Client] = {}
        
    async def connect_server(self, name: str, config: ServerConfig):
        """Connect to an MCP server."""
        client = Client(config.uri)
        await client.connect()
        self.servers[name] = client
        
    async def list_tools(self) -> List[Tool]:
        """Get all available tools across all connected servers."""
        tools = []
        for name, client in self.servers.items():
            server_tools = await client.list_tools()
            tools.extend(server_tools)
        return tools
        
    async def call_tool(self, tool_name: str, args: Dict) -> Any:
        """Execute a tool on the appropriate server."""
        for client in self.servers.values():
            if tool_name in await client.list_tools():
                return await client.call_tool(tool_name, args)
        raise ToolNotFoundError(tool_name)
```

---

## 5. UI Layer (Tauri)

### 4.1 Why Tauri over Electron?

| Factor | Electron | Tauri |
|--------|----------|-------|
| Bundle size | ~150MB | ~5MB |
| Memory usage | ~300MB | ~50MB |
| Startup time | 2-3 seconds | <1 second |
| Native feel | Poor | Good |
| Security | Questionable | Rust-based security |

### 4.2 UI Components

**System Tray (Orb):**
```rust
// Rust backend for system tray
use tauri::{SystemTray, SystemTrayMenu, SystemTrayEvent};

fn create_tray() -> SystemTray {
    let menu = SystemTrayMenu::new()
        .add_item(CustomMenuItem::new("open", "Open Apex"))
        .add_item(CustomMenuItem::new("pause", "Pause"))
        .add_native_item(SystemTrayMenuItem::Separator)
        .add_item(CustomMenuItem::new("quit", "Quit"));
    
    SystemTray::new().with_menu(menu)
}
```

**Sidebar (React/Svelte):**
```typescript
// TypeScript frontend
interface SidebarState {
  status: 'ready' | 'processing' | 'waiting' | 'error';
  currentTask: string | null;
  memories: Memory[];
  quickActions: QuickAction[];
}

function Sidebar() {
  const [state, setState] = useState<SidebarState>(initialState);
  
  return (
    <div className="sidebar glass">
      <OrbStatus status={state.status} />
      <InputBar onSubmit={handleUserInput} />
      <MemoryTimeline memories={state.memories} />
      <QuickActions actions={state.quickActions} />
    </div>
  );
}
```

**HUD Overlay:**
- Transparent, click-through window
- Shows file operations in real-time
- Highlights affected files/folders
- Dismisses automatically when task completes

---

## 6. Execution Sandbox

### 5.1 Why Sandboxing?

AI-generated code is probabilistic—it might work 99% of the time, but that 1% could delete System32. All code execution happens in isolation.

### 5.2 Implementation Options

| Approach | Isolation Level | Overhead | Complexity |
|----------|----------------|----------|------------|
| Python `subprocess` | Low | Minimal | Easy |
| Docker container | High | Medium | Medium |
| gVisor/Firecracker | Very High | Low | Hard |
| Windows Sandbox | High | High | Easy (Windows only) |

**Recommended: Docker with volume mounts**

```python
import docker

class ExecutionSandbox:
    def __init__(self):
        self.client = docker.from_env()
        
    async def execute(self, code: str, allowed_paths: List[str]) -> ExecutionResult:
        """Execute code in isolated container."""
        
        # Create volume mounts for allowed paths only
        volumes = {
            path: {'bind': f'/workspace/{i}', 'mode': 'rw'}
            for i, path in enumerate(allowed_paths)
        }
        
        container = self.client.containers.run(
            image='apex-sandbox:latest',
            command=['python', '-c', code],
            volumes=volumes,
            network_disabled=True,  # No internet access
            mem_limit='512m',       # Memory limit
            cpu_period=100000,      # CPU limit
            cpu_quota=50000,
            remove=True,
            detach=False,
        )
        
        return ExecutionResult(
            stdout=container.logs(stdout=True),
            stderr=container.logs(stderr=True),
            exit_code=container.attrs['State']['ExitCode']
        )
```

---

## 7. Data Flow Examples

### 6.1 "Clean my Downloads folder"

```
User Input: "Clean my Downloads folder"
          │
          ▼
┌─────────────────────────────────────────────┐
│ 1. MEMORY QUERY                             │
│    Context retrieved:                       │
│    - "User prefers keeping PDFs"            │
│    - "Last cleanup: 2 weeks ago"            │
└─────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────┐
│ 2. TASK PLANNING (Cloud LLM)                │
│    Prompt: [context] + [user request]       │
│    Response: Multi-step plan                │
│    - List files in Downloads                │
│    - Categorize by type/age                 │
│    - Propose moves to organized folders     │
└─────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────┐
│ 3. RISK ASSESSMENT                          │
│    Files affected: 47                       │
│    Risk level: MEDIUM                       │
│    → Requires HITL approval                 │
└─────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────┐
│ 4. HITL APPROVAL DIALOG                     │
│    "I'll organize 47 files into:            │
│     - Documents/ (12 PDFs)                  │
│     - Images/ (20 photos)                   │
│     - Trash/ (15 old installers)            │
│    [Cancel] [Review] [Approve]"             │
└─────────────────────────────────────────────┘
          │ User clicks Approve
          ▼
┌─────────────────────────────────────────────┐
│ 5. EXECUTION (Local, Sandboxed)             │
│    MCP Filesystem.move() calls              │
│    Progress shown in HUD overlay            │
└─────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────┐
│ 6. MEMORY UPDATE                            │
│    Store: "Cleaned Downloads on 2026-03-29" │
│    Store: "User approved installer deletion"│
└─────────────────────────────────────────────┘
```

---

## 8. Configuration & Persistence

### 7.1 Config File Structure

```yaml
# ~/.apex/config.yaml

general:
  startup_with_system: true
  telemetry: false
  
privacy:
  memory_mode: local_only  # off | local_only | cloud_assisted
  retention_days: 365
  scrub_patterns:
    - ssn
    - credit_card
    - api_key
    - custom_regex: "SECRET_[A-Z0-9]+"

brain:
  provider: anthropic  # openai | anthropic | google
  model: claude-3-5-sonnet-20241022
  api_key_env: APEX_ANTHROPIC_KEY
  max_tokens: 4096
  temperature: 0.3

permissions:
  default_tier: assistant  # read_only | assistant | full_agent
  filesystem:
    allowed_paths:
      - ~/Documents
      - ~/Downloads
      - ~/Pictures
    denied_paths:
      - ~/.*  # Hidden folders
      - /System
      - /Windows
  spending_limit_daily_usd: 5.00

ui:
  theme: dark
  orb_color: blue
  hud_opacity: 0.8
  notification_sound: true
```

### 7.2 Data Directory Structure

```
~/.apex/
├── config.yaml           # User configuration
├── memories/
│   ├── facts.db          # SQLite + vector index
│   └── history.db        # Task history
├── logs/
│   ├── apex.log          # General logs
│   ├── audit.log         # API call audit trail
│   └── errors.log        # Error logs
├── sandbox/
│   └── workspace/        # Temporary execution space
└── cache/
    ├── embeddings/       # Cached vector embeddings
    └── mcp/              # MCP server cache
```

---

## 9. API Design (Internal)

### 8.1 Core Service APIs

```python
# Service interfaces for internal communication

class MemoryService(Protocol):
    async def store(self, memory: Memory) -> str: ...
    async def query(self, text: str, k: int = 10) -> List[Memory]: ...
    async def update(self, id: str, content: str) -> None: ...
    async def delete(self, id: str) -> None: ...

class TaskService(Protocol):
    async def plan(self, request: str, context: List[Memory]) -> TaskPlan: ...
    async def execute(self, plan: TaskPlan) -> TaskResult: ...
    async def cancel(self, task_id: str) -> None: ...

class McpService(Protocol):
    async def connect(self, server: str, config: Dict) -> None: ...
    async def disconnect(self, server: str) -> None: ...
    async def call(self, tool: str, args: Dict) -> Any: ...
    async def list_tools(self) -> List[Tool]: ...

class UiService(Protocol):
    async def notify(self, message: str, level: str) -> None: ...
    async def request_approval(self, plan: TaskPlan) -> bool: ...
    async def show_progress(self, task_id: str, progress: float) -> None: ...
```

---

## 10. Testing Strategy

### 9.1 Test Categories

| Category | Scope | Tools |
|----------|-------|-------|
| Unit | Individual functions | pytest |
| Integration | Component interactions | pytest + Docker |
| E2E | Full user workflows | Playwright |
| Security | Sandbox escape attempts | Custom harness |
| Performance | Memory/CPU benchmarks | pytest-benchmark |

### 9.2 Critical Test Scenarios

1. **Sandbox Escape Prevention**
   - AI generates code that tries to access denied paths
   - Expected: Access denied, logged, user notified

2. **Memory Conflict Resolution**
   - User says "I live in NY" then "I moved to London"
   - Expected: Old fact updated, not duplicated

3. **HITL Enforcement**
   - Task would delete files, user doesn't approve
   - Expected: No files deleted, task cancelled gracefully

4. **API Failure Handling**
   - Cloud LLM API times out mid-task
   - Expected: Graceful degradation, partial results saved

---

## 11. Deployment

### 10.1 Distribution

| Platform | Format | Installer |
|----------|--------|-----------|
| Windows | `.msi` | WiX Toolset |
| macOS | `.dmg` | create-dmg |
| Linux | `.AppImage` | AppImageKit |

### 10.2 Auto-Update

Use Tauri's built-in updater with signed releases:
- Check for updates on startup (optional)
- Download in background
- Apply on next launch

---

*Architecture Version: 1.0*
*Last Updated: March 2026*
