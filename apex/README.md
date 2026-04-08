# TELIC: The AI Operating System

> *"The AI that lives on your PC, connects all your services, and acts only with your approval."*

**Status:** 🚀 **Ready for Use** — Core complete, desktop builds ready

---

## What is Telic?

Telic is a **personal AI operating system** that runs locally on your computer. Unlike cloud chatbots that forget everything, Telic:

- 🔒 **Shows before it acts** — Every action requires your explicit approval
- 🧠 **Remembers you** — Preferences, history, and context persist forever
- 🔗 **Connects everything** — Google, Microsoft, Slack, GitHub, Todoist, and more
- 🔐 **Privacy-first** — Your data stays local; AI reasoning in the cloud
- 🤖 **Acts on your behalf** — Files, emails, calendar, tasks — with your OK

```
                    ┌──────────────────────────────────────────────┐
                    │                YOUR REQUEST                    │
                    │   "Organize my Downloads and email me a       │
                    │    summary with the loan amortization"        │
                    └──────────────────────────────────────────────┘
                                           │
                                           ▼
    ┌───────────────────────────────────────────────────────────────────────┐
    │                         TELIC ENGINE                                    │
    │  ┌─────────────────────────────────────────────────────────────────┐  │
    │  │  PLANNER (LLM)                                                    │  │
    │  │  Breaks request into steps using 36 primitives                   │  │
    │  └─────────────────────────────────────────────────────────────────┘  │
    │                               │                                        │
    │                               ▼                                        │
    │  ┌─────────────────────────────────────────────────────────────────┐  │
    │  │  STEP 0: FILE.list(~/Downloads)           ✓ Auto-run (read-only)  │  │
    │  │  STEP 1: DOCUMENT.parse(loan.pdf)         ✓ Auto-run (read-only)  │  │
    │  │  STEP 2: COMPUTE.formula(amortization)    ✓ Auto-run (read-only)  │  │
    │  │  STEP 3: FILE.write(organize folders)     ⏸ Needs approval        │  │
    │  │  STEP 4: EMAIL.send(summary)              ⏸ Needs approval        │  │
    │  └─────────────────────────────────────────────────────────────────┘  │
    │                               │                                        │
    │                               ▼                                        │
    │  ┌─────────────────────────────────────────────────────────────────┐  │
    │  │  👤 USER APPROVAL                                                  │  │
    │  │  [✓ Approve]  [✗ Reject]                                          │  │
    │  └─────────────────────────────────────────────────────────────────┘  │
    └───────────────────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# 1. Clone and enter
cd apex

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set your API key
export ANTHROPIC_API_KEY="sk-..."  # or OPENAI_API_KEY

# 4. Run
python server.py

# 5. Open http://localhost:8000
```

## What's Built

### 36 Universal Primitives (194 Operations)

| Primitive | Operations | Examples |
|-----------|------------|----------|
| **FILE** | search, read, write, list, info | Find PDFs, organize folders |
| **DOCUMENT** | parse, extract, create, summarize | Parse loan docs, generate reports |
| **COMPUTE** | formula, calculate, aggregate | Amortization, compound interest, any math |
| **EMAIL** | send, draft, search, list | Gmail, Outlook integration |
| **CALENDAR** | create, list, search, delete | Google Calendar, Outlook Calendar |
| **TASK** | create, list, update, complete | Todoist, Microsoft To-Do, Jira |
| **MESSAGE** | send, list, search, react | Slack, Teams, Discord |
| **CLOUD_STORAGE** | list, upload, download, share | Google Drive, OneDrive, Dropbox |
| **DEVTOOLS** | list_issues, create_pr, comment | GitHub, Jira |
| **BROWSER** | open, click, fill_form, screenshot | Web automation |
| **TRANSLATE** | translate, detect | Any language |
| **DATABASE** | query, execute, tables | SQLite operations |
| **AUTOMATION** | create, list, enable, run | Scheduled tasks |
| *...and 23 more* | | |

### 23 Cloud Connectors

**Google:** Gmail, Calendar, Drive, Contacts, Sheets, Slides, Photos  
**Microsoft:** Outlook, Calendar, OneDrive, To-Do, OneNote, Teams  
**Other:** Slack, GitHub, Discord, Spotify, Twilio, Todoist, Dropbox, Jira, Twitter, SmartThings

### Cognitive Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        UNIFIED BRAIN                              │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                   MEMORY SYSTEMS                             │  │
│  │  Working │ Episodic │ Semantic │ Procedural │ Predictive   │  │
│  │  (active) (events)   (facts)    (skills)     (patterns)    │  │
│  └────────────────────────────────────────────────────────────┘  │
│                              │                                    │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │               CONSCIOUSNESS LOOP (100ms)                     │  │
│  │  sense → attend → remember → think → predict → act → learn  │  │
│  └────────────────────────────────────────────────────────────┘  │
│                              │                                    │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │              INTELLIGENCE LAYER                               │  │
│  │  Preference Learning │ Proactive Suggestions │ Cross-Service │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### Control & Safety Layer

| Feature | Description |
|---------|-------------|
| **Approval Gateway** | Every write action requires explicit user approval |
| **Trust Levels** | ALWAYS_ASK → ASK_ONCE → AUTO_APPROVE (earned over time) |
| **PII Redaction** | Sensitive data stripped before cloud transmission |
| **Audit Logging** | Every action logged with full context |
| **Undo System** | Checkpoint-based rollback for destructive operations |
| **Action History** | Searchable database of everything Telic has done |

### Desktop App (Tauri)

- System tray with hide/show/quit
- Auto-starts Python backend
- Cross-platform: Windows, macOS, Linux
- <10MB installer

## Architecture

```
apex/
├── apex_engine.py          # 🧠 Core engine (6,900+ lines)
│   ├── 36 Primitives       # Universal building blocks
│   ├── TaskPlanner         # LLM-powered plan generation
│   ├── Orchestrator        # Step execution with self-healing
│   └── Safety Rails        # Trust, approval, undo, audit
│
├── server.py               # 🌐 FastAPI server
│   ├── /chat               # Main chat endpoint
│   ├── /execute            # Run approved plans
│   └── /google/*           # OAuth flows
│
├── ui/index.html           # 💻 Desktop UI
│   ├── Chat interface
│   ├── Plan approval cards
│   └── Alerts panel
│
├── src/
│   ├── brain/              # Cognitive architecture
│   │   ├── memory_systems.py   # 5 memory types
│   │   ├── consciousness.py    # Awareness loop
│   │   └── learning.py         # Pattern recognition
│   ├── control/            # Safety layer
│   │   ├── approval_gateway.py # HITL enforcement
│   │   ├── trust_levels.py     # Graduated permissions
│   │   └── undo_manager.py     # Rollback support
│   └── skills/             # Built-in skills
│       ├── file_organizer.py
│       ├── photo_organizer.py
│       └── ...5 more
│
├── connectors/             # 23 service integrations
└── src-tauri/              # Rust desktop app
```

## Test Suite

```
334 tests passing ✓

Primitives:     194/194 ✓
OAuth Flow:      38/38  ✓
Connectors:      33/33  ✓
Resolver:        28/28  ✓
New Connectors:  41/41  ✓
```

## Example Requests

```
"Find all PDFs in Downloads and list them"
"Create an amortization schedule for $250k at 6.5% for 30 years"
"Add Mom's birthday to my calendar - April 15th, yearly"
"Organize my Downloads folder by file type"
"Draft an email to Bob summarizing yesterday's meeting"
"Check my calendar for conflicts next week"
"Find duplicate photos and show me what to delete"
```

## Why Telic?

| Alternative | The Problem |
|-------------|-------------|
| ChatGPT/Claude | Can't access your files, forgets everything |
| Microsoft Recall | Read-only, privacy nightmare |
| Rabbit R1 | Hardware-dependent, limited integrations |
| Open Interpreter | Terminal-only, scary for regular users |

**Telic:** Cloud intelligence + local control + your approval always required.

## Roadmap

- [x] 36 Primitives / 194 Operations
- [x] Full cognitive architecture  
- [x] 23 cloud connectors with OAuth
- [x] Approval gateway & trust levels
- [x] FastAPI server with streaming
- [x] Desktop UI with plan cards
- [x] Tauri desktop app scaffolding
- [x] 334 tests passing
- [ ] End-to-end user testing
- [ ] Polish streaming UI
- [ ] Production builds

## License

MIT

---

*"The AI that grows with you — not a chatbot, an operating system."*
