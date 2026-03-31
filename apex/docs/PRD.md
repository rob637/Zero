# PRODUCT REQUIREMENTS DOCUMENT: APEX
## Telic - The AI Operating System with Purpose
**Version:** 1.0  
**Date:** March 2026  
**Status:** Draft

---

## 1. Executive Summary

### The Vision
Apex is **the brain of your digital life**—a local-first AI operating layer that starts as your personal file organizer but evolves into the central nervous system for everything you do on your computer.

> *"We're not building a file organizer. We're building the foundation for a personal AI operating system. File organization is just the first skill."*

Apex manages files today, but the architecture is designed from Day 1 to become:
- Your **memory** — remembering everything you've done, seen, and learned
- Your **hands** — executing tasks across any app on your behalf  
- Your **eyes** — understanding context from screen, files, and communications
- Your **voice** — representing you to the digital world

### The Problem
Current AI assistants (ChatGPT, Copilot, Gemini) are:
- **Stateless** — They forget everything between sessions
- **Siloed** — They live in a browser tab, disconnected from your actual work
- **Cloud-dependent** — Your private data leaves your machine
- **Passive** — They tell you what to do; they don't do it for you

### The Solution
A **Hybrid Agent Architecture** where:
- **Your PC** holds the keys, memories, and executes all actions locally
- **Cloud LLMs** (via API) provide reasoning power when needed
- **You** remain in control with human-in-the-loop approval for sensitive actions

### Target Market
- Privacy-conscious power users frustrated with Big Tech surveillance
- Knowledge workers drowning in digital chaos (10,000+ unorganized photos, cluttered downloads)
- Professionals who want automation without sacrificing control
- Early adopters seeking "the Jarvis experience" without the Hollywood fiction

---

## 2. Core Philosophy

### "Trust Through Transparency" (Primary Principle)

> **User Research Finding (March 2026):** In 10 early conversations, users expressed fear that AI would "do bad things" without their knowledge. The solution: **Apex never acts without showing its plan and getting explicit approval.**

This isn't just a safety feature—it's the **entire product positioning**:

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│   "Other AI tells you what to do.                          │
│    Apex SHOWS you what it WILL do, then waits for YES."    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**The Trust Contract:**
1. **Apex ALWAYS explains** what it's about to do (in plain English)
2. **Apex ALWAYS shows** exactly which files/data will be affected
3. **Apex ALWAYS waits** for your explicit approval
4. **Apex ALWAYS provides** an undo path
5. **Apex NEVER acts** autonomously on anything that matters

### "The Vault, Not the Cloud"
> *"Your data never leaves your machine unless you explicitly allow it. The AI sees only what it needs, processes locally what it can, and asks permission before every significant action."*

### "Platform, Not Feature"
Apex isn't a feature—it's a **platform**. File organization is the first skill, but the architecture supports unlimited skills:

```
Phase 1: File Organizer     → "Clean my downloads"
Phase 2: Research Assistant → "Summarize these articles"
Phase 3: Communication Hub  → "Draft reply to Sarah's email"
Phase 4: Life Orchestrator  → "Prepare everything for my trip"
Phase ∞: The Brain          → Anticipates needs before you ask
```

### "Collaborator, Not Autonomous Agent"
The 2024-2025 startup graveyard is full of products that tried to make AI do everything automatically. Apex succeeds by keeping humans in the loop:
- **Bad:** AI deletes photos automatically to save space
- **Good:** AI finds 500 blurry photos, puts them in "Review" folder, sends notification: "Found 2GB of potential junk. Delete with one click?"

---

## 3. System Architecture

### 3.1 The "Body & Brain" Split

```
┌─────────────────────────────────────────────────────────────┐
│                     YOUR PC (The "Body")                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ Controller  │  │   Memory    │  │   Integration       │ │
│  │  (Python/   │──│   (Vector   │──│   Layer (MCP)       │ │
│  │   Rust)     │  │    DB)      │  │                     │ │
│  └──────┬──────┘  └─────────────┘  └─────────────────────┘ │
│         │                                                   │
│         │ API Calls (scrubbed of sensitive data)           │
│         ▼                                                   │
│  ┌─────────────────────────────────────────────────────────┐│
│  │              Secure Gateway / Data Scrubber             ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
                              │
                              │ HTTPS (encrypted)
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 CLOUD (The "Brain")                         │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ GPT-4o      │  │ Claude 3.5  │  │ Gemini Ultra        │ │
│  │ (OpenAI)    │  │ (Anthropic) │  │ (Google)            │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
│                    (User selects provider)                  │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Component Breakdown

| Component | Location | Purpose |
|-----------|----------|---------|
| **Controller** | Local | Persistent daemon that receives commands, manages state, executes actions |
| **Memory Store** | Local | Vector database storing facts, preferences, task history |
| **Integration Layer** | Local | MCP servers connecting to apps (Files, Browser, Slack, etc.) |
| **Data Scrubber** | Local | Middleware that redacts sensitive data before cloud transmission |
| **Reasoning Engine** | Cloud | LLM API for complex reasoning and natural language understanding |

### 3.3 Why This Architecture?

| Approach | Privacy | Performance | Cost | Capability |
|----------|---------|-------------|------|------------|
| 100% Local (Ollama) | ✅ Perfect | ❌ Slow/GPU needed | ✅ Free | ❌ Limited reasoning |
| 100% Cloud | ❌ Data leaves PC | ✅ Fast | ⚠️ Usage fees | ✅ Best reasoning |
| **Hybrid (Apex)** | ✅ Data stays local | ✅ Fast | ⚠️ Small API fees | ✅ Best reasoning |

---

## 4. Extensible Skill Architecture

### 4.0 The Skill System (Foundation for Everything)

**Philosophy:** Every capability in Apex is a "Skill." The core platform provides memory, reasoning, and action execution—Skills define *what* Apex can do.

```
┌─────────────────────────────────────────────────────────────┐
│                    APEX CORE PLATFORM                       │
├─────────────────────────────────────────────────────────────┤
│  Memory Engine │ Task Orchestrator │ Security Gateway       │
└────────────────┴──────────────────┴─────────────────────────┘
                            │
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
     ┌───────────┐   ┌───────────┐   ┌───────────┐
     │  SKILL:   │   │  SKILL:   │   │  SKILL:   │
     │  Files    │   │  Browser  │   │  Comms    │
     │  (MVP)    │   │  (v1.1)   │   │  (v1.2)   │
     └───────────┘   └───────────┘   └───────────┘
            │               │               │
            ▼               ▼               ▼
     ┌───────────┐   ┌───────────┐   ┌───────────┐
     │ MCP:      │   │ MCP:      │   │ MCP:      │
     │ Filesystem│   │ Playwright│   │ Slack/    │
     │           │   │           │   │ Email     │
     └───────────┘   └───────────┘   └───────────┘
```

**Skill Interface (Every skill implements this):**

```python
class Skill(Protocol):
    """Base interface for all Apex skills."""
    
    name: str                          # "file-organizer"
    description: str                   # For LLM to understand capability
    version: str                       # Semantic versioning
    required_mcps: List[str]           # ["filesystem"]
    permission_level: PermissionTier   # What access it needs
    
    async def can_handle(self, intent: str) -> float:
        """Return confidence (0-1) that this skill handles the intent."""
        ...
    
    async def plan(self, request: str, context: Context) -> TaskPlan:
        """Generate execution plan for the request."""
        ...
    
    async def execute(self, plan: TaskPlan) -> Result:
        """Execute the plan (with HITL checkpoints)."""
        ...
```

**Why this matters:** When we add browser automation in v1.1, we don't rewrite Apex—we add `BrowserSkill`. When we add email in v1.2, we add `CommunicationSkill`. The platform grows through skills.

---

## 5. Core Skills (Roadmap)

### 5.1 Contextual File Management ("The Librarian") — MVP

**Goal:** AI performs "semantic" file operations—understanding content, not just filenames.

| Feature | Description | User Story |
|---------|-------------|------------|
| **Intelligent Cleanup** | Identify near-duplicate photos, blurry images, temp files, old installers | "Clean up my Downloads folder" |
| **Semantic Sorting** | Rename and move files based on content | "Sort all my tax-related PDFs into 'Taxes 2025'" |
| **Natural Language Search** | Find files by describing them | "Find that receipt from the coffee shop last Tuesday" |
| **Contextual Renaming** | Fix "IMG_5922.jpg" using vision/metadata | Auto-rename to "2026_Trip_Italy_Colosseum.jpg" |
| **Archive Management** | Find "cold" files untouched for years | "Archive everything I haven't opened in 2 years" |

**Technical Requirements:**
- Index file metadata and content summaries in local vector DB
- Use vision model for image understanding (can be local or cloud)
- Implement file system watcher for real-time updates
- Support Windows Explorer, OneDrive, Google Drive via MCP

### 5.2 Long-Term Memory ("The Vault") — MVP

**Goal:** Store user preferences, past tasks, and specific facts locally so the AI "remembers" across sessions.

> **This is not a skill—it's the CORE.** Memory is what makes Apex more than a chatbot. Every skill reads from and writes to the shared memory, creating a unified understanding of *you*.

| Feature | Description | Example |
|---------|-------------|---------|
| **Fact Extraction** | Distill conversations into salient facts | "User prefers PDF over Word" |
| **Conflict Resolution** | Auto-update contradictory facts | Old: "Lives in NY" → New: "Moved to London" |
| **Context Injection** | Prime cloud LLM with relevant memories | "Remember user prefers dark mode..." |
| **Memory Timeline** | Scrollable history of AI actions and remembered facts | Visual timeline in UI |

**Technical Requirements:**
- Implement local Vector Database (ChromaDB or Mem0)
- Store memories as embeddings for semantic search
- Implement memory "decay" or manual pruning options
- Memory format: `{fact, source, timestamp, confidence}`

### 5.3 Cross-App Orchestration ("The Doer") — v1.1+

**Goal:** Execute multi-step actions across different software by combining multiple skills.

| Scenario | Skills Involved | Steps Automated |
|----------|-----------------|------------------|
| "I'm meeting with Sarah in 10 mins" | Files + Comms + Browser | Find last email thread → Open project spreadsheet → Generate summary → Display on desktop |
| "Prepare for tax season" | Files + Memory | Find all PDFs with "invoice" → Move to Taxes folder → Create summary spreadsheet |
| "My internet bill went up" | Browser + Comms | Research competitor prices → Compose complaint/switch letter |
| "Book London trip" | Browser + Calendar | Find flights under $800 → Compare hotels near venue → Add to calendar |

**The Power of Combined Skills:**
```
User: "Prepare for my call with Acme Corp"

┌─────────────────────────────────────────────────────────────┐
│ ORCHESTRATOR analyzes request, selects skills:              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Memory Skill  →  "Acme Corp = client since 2024,           │
│                    main contact is John, last call was      │
│                    about Q2 deliverables"                   │
│                                                             │
│  File Skill    →  Find: Acme-proposal.docx,                │
│                    Q2-deliverables.xlsx                     │
│                                                             │
│  Email Skill   →  Last 5 emails with @acmecorp.com         │
│                                                             │
│  Calendar Skill→  Previous meeting notes                    │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│ OUTPUT: Briefing document + files opened + key points       │
└─────────────────────────────────────────────────────────────┘
```

**Technical Requirements:**
- Implement MCP (Model Context Protocol) clients for major apps
- Build browser agent for web actions (Playwright/Browser-use)
- Support "workflow templates" for common scenarios
- All actions must pass through Human-in-the-Loop approval

### 5.4 World Access ("The Scout") — v1.2+

**Goal:** Reach out to the internet to monitor, research, and act on user's behalf.

| Feature | Description |
|---------|-------------|
| **Research Agent** | "Summarize reviews for RTX 5090" |
| **Price Monitoring** | "Alert me when this monitor drops below $400" |
| **Form Filling** | "Fill out this application using my resume" |
| **Web Automation** | "Book this flight" (with approval before payment) |

**Technical Requirements:**
- Headless browser integration (Playwright preferred)
- Spending limits requiring biometric/2FA approval
- Web action sandboxing to prevent accidental purchases

### 5.5 Future Skills (The Vision)

| Skill | Target | Capability |
|-------|--------|------------|
| **Screen Understanding** | v2.0 | "What am I looking at?" — OCR + vision to understand current context |
| **Voice Interface** | v2.0 | Hands-free interaction, ambient listening (local, privacy-first) |
| **Proactive Suggestions** | v2.0 | "You have a meeting in 10 mins, want me to prep?" |
| **Learning & Patterns** | v2.5 | Detect your habits, automate without being asked |
| **Multi-Device Sync** | v3.0 | Phone ↔ PC ↔ Tablet unified memory |
| **Plugin Marketplace** | v3.0 | Community-built skills |

---

## 6. The Approval Experience (Critical UX)

> **This is the most important UX in the product.** Users fear AI will "do bad things." The approval flow is how we earn trust.

### 6.1 The "Show, Don't Hide" Principle

Every action follows this flow:

```
User Request
     │
     ▼
┌─────────────────────────────────────────────┐
│  APEX THINKS (visible to user)              │
│  "Analyzing your Downloads folder..."        │
│  "Found 47 files..."                        │
│  "Categorizing by type and age..."          │
└─────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────┐
│  APEX EXPLAINS (plain English)              │
│  "Here's what I'd like to do:"              │
│  • Move 12 PDFs to Documents/               │
│  • Move 8 images to Pictures/               │
│  • Delete 15 old installers (2.1 GB)        │
└─────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────┐
│  APEX SHOWS (exact details)                 │
│  📄 Tax_2024.pdf → Documents/PDFs/          │
│  📄 Receipt_March.pdf → Documents/PDFs/     │
│  🖼️ Screenshot_1.png → Pictures/Screenshots/│
│  🗑️ installer_v2.3.exe → Recycle Bin        │
│  [View all 47 files...]                     │
└─────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────┐
│  APEX WAITS (no action without approval)    │
│                                             │
│  ⚠️ This will move 35 files and delete 12   │
│  🔄 Undo: Files go to Recycle Bin           │
│                                             │
│  [Cancel]  [Edit Plan]  [✓ Approve]         │
└─────────────────────────────────────────────┘
     │
     ▼ (only after user clicks Approve)
┌─────────────────────────────────────────────┐
│  APEX ACTS (with live progress)             │
│  ████████████░░░░░░░░ 60%                   │
│  Moving: Receipt_March.pdf...               │
│                                             │
│  [Pause]  [Cancel]                          │
└─────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────┐
│  APEX REPORTS (what happened)               │
│  ✅ Done! Organized 47 files.               │
│  • 35 moved to new locations                │
│  • 12 sent to Recycle Bin                   │
│  [Undo Everything] [View Changes]           │
└─────────────────────────────────────────────┘
```

### 6.2 Approval Dialog Design

The approval dialog is the **trust moment**. It must be:

| Requirement | Implementation |
|-------------|----------------|
| **Scannable** | Summary at top, details expandable |
| **Honest** | Show deletions prominently, don't hide risks |
| **Escapable** | Cancel is always easy, never buried |
| **Undoable** | Always show the undo path |
| **Editable** | User can modify plan before approving |

**Approval Dialog Mockup:**

```
╔═══════════════════════════════════════════════════════════╗
║                    APEX NEEDS YOUR OK                     ║
╠═══════════════════════════════════════════════════════════╣
║                                                           ║
║  📋 WHAT I'LL DO                                          ║
║  ─────────────────────────────────────────────────────    ║
║  Organize your Downloads folder by moving files to        ║
║  better locations and cleaning up old installers.         ║
║                                                           ║
║  📊 SUMMARY                                               ║
║  ─────────────────────────────────────────────────────    ║
║  ├── 📁 Move 12 PDFs      → Documents/PDFs/               ║
║  ├── 📁 Move 8 images     → Pictures/Screenshots/         ║
║  ├── 📁 Move 10 archives  → Documents/Archives/           ║
║  └── 🗑️ Delete 15 files   → Recycle Bin (2.1 GB)          ║
║                                                           ║
║  [▼ View all 45 files with exact paths]                   ║
║                                                           ║
║  ⚠️  HEADS UP                                              ║
║  ─────────────────────────────────────────────────────    ║
║  • 15 files will be deleted (sent to Recycle Bin)         ║
║  • You can undo this anytime                              ║
║  • Nothing leaves your computer                           ║
║                                                           ║
║  ┌─────────────────────────────────────────────────────┐  ║
║  │               WHAT IF SOMETHING GOES WRONG?         │  ║
║  │  All deleted files go to Recycle Bin.               │  ║
║  │  Click "Undo" anytime to restore everything.        │  ║
║  └─────────────────────────────────────────────────────┘  ║
║                                                           ║
║         ┌──────────┐  ┌──────────┐  ┌──────────────┐     ║
║         │  Cancel  │  │Edit Plan │  │ ✓ Approve   │     ║
║         └──────────┘  └──────────┘  └──────────────┘     ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
```

### 6.3 Progressive Trust Levels

Users can choose how much approval they want:

| Level | Description | For Who |
|-------|-------------|----------|
| **🔒 Paranoid** | Approve every single file | New users, sensitive data |
| **🔐 Careful** (default) | Approve batches, see summary | Most users |
| **🔓 Trusting** | Approve category (e.g., "yes to all PDF moves") | Power users |

**Never offer a "fully autonomous" mode.** The approval is the product.

### 6.4 Language Guidelines

How Apex speaks matters for trust:

| ❌ Don't Say | ✅ Do Say |
|--------------|----------|
| "Deleting files..." | "Moving to Recycle Bin (you can restore anytime)" |
| "Processing..." | "Looking at your files..." |
| "Executing task" | "Here's what I'll do — what do you think?" |
| "Operation complete" | "Done! Here's what changed (undo anytime)" |
| "Error occurred" | "Something went wrong. Nothing was changed. Here's what happened:" |

---

## 7. Security & Privacy ("The Trust Pillar")

### 7.1 This Is Our Competitive Moat

> *"Microsoft and Google tried to force these features; we earn trust by giving users control."*

### 7.2 Required Guardrails

| Guardrail | Implementation |
|-----------|----------------|
| **Local Execution Sandbox** | All AI-generated code runs in Docker container or restricted sandbox |
| **Data Scrubbing** | Middleware scans outgoing API calls, redacts SSN/passwords/financial data |
| **Human-in-the-Loop (HITL)** | High-risk actions require explicit approval in System Tray |
| **Shadow Mode** | AI performs actions on virtual copy first; user clicks "Commit" to apply |
| **Permission Tiers** | Tier 1: Read-Only / Tier 2: Draft (no send/save) / Tier 3: Full Agent |
| **Blast Radius Check** | Actions affecting >5 files or any $$ require detailed approval screen |
| **Audit Trail** | Every action logged locally with timestamp, intent, and outcome |

### 7.3 The "Approval" Flow

```
User Request: "Delete all duplicate photos"

┌─────────────────────────────────────────────────────┐
│              APEX APPROVAL DIALOG                   │
├─────────────────────────────────────────────────────┤
│                                                     │
│  📋 PLANNED ACTION                                  │
│  ─────────────────                                  │
│  Intent: Delete duplicate photos                    │
│  Scope: Pictures folder (recursive)                 │
│  Files affected: 247 files (1.2 GB)                │
│                                                     │
│  ⚠️  THIS ACTION IS DESTRUCTIVE                     │
│                                                     │
│  📁 Preview:                                        │
│  • IMG_2031.jpg → DELETE (duplicate of IMG_2030)   │
│  • Photo_copy(1).png → DELETE (exact match)        │
│  • [View all 247 files...]                         │
│                                                     │
│  🔄 Undo Path: Files moved to Recycle Bin          │
│                                                     │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │  Cancel  │  │ Review First │  │   Approve    │ │
│  └──────────┘  └──────────────┘  └──────────────┘ │
└─────────────────────────────────────────────────────┘
```

---

## 8. User Interface

### 8.1 Design Philosophy: "Subtle Glass"

The AI shouldn't demand attention—it should be a **presence**, not a destination.

### 8.2 Three States of Presence

| State | Description | Visual |
|-------|-------------|--------|
| **The Orb** | System tray icon | Small glowing sphere; pulses when processing |
| **The Sidebar** | Slide-out control panel | Memory timeline, quick actions, settings |
| **The HUD** | Transparent overlay | Shows AI "working" on files in real-time |

### 8.3 The Orb (System Tray)

```
┌────────────────────────────────────────┐
│  Windows Taskbar                       │
│                          [🔵 Apex Orb] │
└────────────────────────────────────────┘

Orb States:
• Blue pulse    = Listening/Ready
• Green rotation = Processing locally
• Gold shimmer  = Waiting for cloud response
• Red glow      = Needs attention/approval
```

### 8.4 The Sidebar (Control Center)

```
┌──────────────────────────────────────┐
│         APEX CONTROL CENTER          │
├──────────────────────────────────────┤
│                                      │
│  ┌────────────────────────────────┐  │
│  │        🔵 APEX ORB             │  │
│  │   "Ready to help"              │  │
│  └────────────────────────────────┘  │
│                                      │
│  ┌────────────────────────────────┐  │
│  │ 💬 What can I help with?       │  │
│  │ [____________________________] │  │
│  │  📎 Attach  🌐 Web  📧 Email   │  │
│  └────────────────────────────────┘  │
│                                      │
│  ═══ MEMORY TIMELINE ════════════   │
│                                      │
│  🕐 5 mins ago                       │
│  ✅ Cleaned Downloads (14 files)     │
│     [View Folder]                    │
│                                      │
│  🕐 20 mins ago                      │
│  🧠 Remembered: "Sarah is Marketing  │
│     Lead"                            │
│                                      │
│  🕐 1 hour ago                       │
│  🔍 Researched RTX 5090 benchmarks   │
│     [View Summary]                   │
│                                      │
│  ═══ QUICK ACTIONS ══════════════   │
│                                      │
│  ┌──────┐ ┌──────┐ ┌──────┐        │
│  │ 🧹   │ │ 📅   │ │ 🌐   │        │
│  │Clean │ │Prep  │ │Search│        │
│  └──────┘ └──────┘ └──────┘        │
│                                      │
│  ┌──────┐ ┌──────┐ ┌──────┐        │
│  │ 📝   │ │ 📊   │ │ ⚙️   │        │
│  │Draft │ │Stats │ │Setts │        │
│  └──────┘ └──────┘ └──────┘        │
│                                      │
└──────────────────────────────────────┘
```

### 8.5 The Settings Page

| Section | Options |
|---------|---------|
| **Privacy & Memory** | Memory Mode: Off / Local Only / Cloud Assisted |
| | Retention Policy: Forever / 1 Year / 30 Days |
| | Scrub Sensitive Data: Toggle |
| | Wipe Memory: Nuclear button |
| **App Integrations** | MCP Server management (Files, Drive, Slack, Outlook, Spotify) |
| | Per-app permissions: Read Only / Full Action |
| **The Brain** | Cognition Provider: Claude / GPT-4o / Gemini |
| | Model preference for different tasks |
| **Local Execution** | Python sandbox path and permissions |
| | Allowed/denied folder paths |
| **Appearance** | Orb color theme, HUD transparency, notification preferences |

---

## 9. Competitive Analysis

### 9.1 Existing Solutions

| Product | Approach | Strengths | Weaknesses |
|---------|----------|-----------|------------|
| **Microsoft Copilot+ Recall** | System-wide screen recording | Deep OS integration | Privacy nightmare, no user trust |
| **Limitless (Rewind)** | Screen/audio recording | Great memory/search | Read-only, can't take actions |
| **OpenClaw** | Messaging-based agent | Open source, powerful | Hacker-first, security concerns, no native UI |
| **Open Interpreter** | Terminal-based agent | Can execute code | Scary for non-developers |
| **Lindy.ai / Manus AI** | Cloud-based automation | Polished UI | Data leaves your PC |

### 9.2 Apex Differentiation

| Factor | Competitors | Apex |
|--------|-------------|------|
| **Data Location** | Cloud or invasive local recording | Local-first with optional cloud reasoning |
| **User Control** | Minimal | Full HITL + permission tiers |
| **UI** | Chat/terminal | Native desktop integration (Orb/HUD) |
| **Target User** | Developers | Privacy-conscious power users |
| **Trust Model** | "Trust us" | "Trust yourself—we just provide tools" |

---

## 10. Technical Stack (Recommendations)

| Layer | Recommended Technology | Alternatives |
|-------|------------------------|--------------|
| **Language** | Python (AI logic) + Rust (performance-critical) | Go |
| **Desktop UI** | Tauri (lightweight) | Electron |
| **Agent Framework** | LangGraph | CrewAI, AutoGen |
| **Memory/Vector DB** | Mem0 (local profile) | ChromaDB, Qdrant |
| **LLM Connectivity** | LiteLLM (unified API) | Direct SDK per provider |
| **App Integration** | MCP (Model Context Protocol) | Custom APIs |
| **Browser Automation** | Playwright | Puppeteer, Browser-use |
| **Sandbox** | Docker | Firecracker, gVisor |

---

## 11. Risk Analysis

### 11.1 Technical Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| LLM hallucination causes file deletion | Medium | High | Shadow mode, HITL, Recycle Bin as undo |
| Memory poisoning attacks | Low | High | Input sanitization, fact verification prompts |
| MCP server compatibility issues | High | Medium | Start with core apps, community MCP servers |
| Local performance on older hardware | Medium | Medium | Async processing, optional task offloading |

### 11.2 Business Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Big Tech releases competing feature | High | Medium | Move fast, differentiate on privacy/trust |
| User reluctance to grant permissions | Medium | High | Graduated onboarding, transparent permissions |
| API cost unpredictability | Medium | Low | User-controlled spending limits, local fallback |
| Liability for AI mistakes | Medium | High | Clear ToS, HITL enforcement, audit trails |

---

## 12. Success Metrics

| Metric | Target (v1.0) | Target (v2.0) |
|--------|---------------|---------------|
| **Daily Active Users** | 1,000 | 50,000 |
| **Files organized per user/month** | 500+ | 2,000+ |
| **Task completion rate** | 85%+ | 95%+ |
| **User-reported "saves me time"** | 70%+ | 90%+ |
| **Zero critical data loss incidents** | 100% | 100% |
| **NPS (Net Promoter Score)** | 40+ | 60+ |

---

## 13. Open Questions for Development

1. **Monetization Model:** Freemium? Subscription? One-time purchase?
2. **LLM Provider Default:** Which API to default to? Allow user choice?
3. **Offline Mode:** How much functionality when internet is unavailable?
4. **Mobile Companion:** Should there be a phone app to control PC remotely?
5. **Enterprise Version:** Different requirements for team/business use?

---

## Appendices

- **Appendix A:** [Technical Architecture Deep Dive](./ARCHITECTURE.md)
- **Appendix B:** [MVP Roadmap & Sprints](./MVP-ROADMAP.md)
- **Appendix C:** [Competitive Analysis Details](./COMPETITIVE-ANALYSIS.md)
- **Appendix D:** [Security Framework](./SECURITY.md)

---

*Document Status: DRAFT - Awaiting stakeholder review*
