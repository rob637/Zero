# APEX: Personal AI Operating Layer

> *"We're not building a file organizer. We're building the brain of your digital life. File organization is just the first skill."*

**Status:** 📋 Planning / Documentation Phase

---

## What is Apex?

Apex is **the foundation for a personal AI operating system** that lives on your PC. Unlike chatbots that forget everything and can't touch your files, Apex:

- 🔒 **Shows before it acts** — Always explains what it will do, waits for your OK
- 🧠 **Remembers you** — Facts, preferences, and history persist across sessions
- 📁 **Acts on your behalf** — Organizes files, automates tasks (with your approval)
- 🔐 **Respects your privacy** — Data stays local; cloud is only for reasoning
- 🧩 **Grows with skills** — File organization today, everything tomorrow

> **Core Promise:** *"Apex NEVER acts without showing you the plan and getting your explicit YES."*

## The Platform Vision

```
Phase 1: File Organizer     → "Clean my downloads"
Phase 2: Browser Agent      → "Research this topic for me"
Phase 3: Communication Hub  → "Draft reply to Sarah's email"
Phase 4: Life Orchestrator  → "Prepare everything for my trip"
Phase ∞: The Brain          → Anticipates needs before you ask
```

We start with files because everyone has file chaos. But the architecture is designed from Day 1 to become the **central nervous system** for your digital life.

## The Hybrid Architecture

```
┌─────────────────────┐         ┌─────────────────────┐
│    YOUR PC          │         │      CLOUD          │
│                     │  API    │                     │
│  • Memory (local)   │ ──────► │  • LLM Reasoning    │
│  • Skill execution  │ ◀───── │    (GPT/Claude)     │
│  • App control      │         │                     │
│  • ALL your data    │         │  (No data stored)   │
└─────────────────────┘         └─────────────────────┘
```

**Why this matters:**
- Cloud LLMs are powerful but can't touch your files
- Local LLMs can touch files but lack reasoning power
- Apex combines both: **local control + cloud intelligence**

## Key Concepts

| Concept | Description |
|---------|-------------|
| **Skills** | Pluggable capabilities (file org, browser, email). New skill = new module, not rewrite. |
| **Shared Memory** | All skills read/write the same knowledge graph. Your preferences inform everything. |
| **HITL** | Human-in-the-loop. Every significant action requires your approval. |
| **Platform** | We're building the OS, not just features. File organization is Skill #1 of many. |

## Skills Roadmap

| Skill | Version | Capability |
|-------|---------|------------|
| **File Organizer** | MVP | Clean folders, find duplicates, semantic search |
| **Browser Agent** | v1.1 | Web research, form filling, price monitoring |
| **Communication Hub** | v1.2 | Email drafts, Slack, calendar management |
| **Screen Understanding** | v2.0 | OCR, visual context awareness |
| **Voice Interface** | v2.0 | Hands-free commands, ambient listening |
| **Community Skills** | v3.0 | Plugin marketplace |

## Documentation

| Document | Description |
|----------|-------------|
| [Strategic Playbook](docs/STRATEGIC-PLAYBOOK.md) | **Start here.** Decision framework, validation gates, kill criteria |
| [Product Requirements](docs/PRD.md) | Full product spec, skill architecture, competitive analysis |
| [Technical Architecture](docs/ARCHITECTURE.md) | System design, skill interfaces, data flows |
| [MVP Roadmap](docs/MVP-ROADMAP.md) | 12-week sprint plan, milestones, team requirements |
| [Assessment](docs/ASSESSMENT.md) | Honest analysis of opportunity and risks |

## Why Not Just Use [X]?

| Product | Why It Falls Short |
|---------|-------------------|
| **ChatGPT/Claude** | Can't access your files, forgets everything |
| **Microsoft Recall** | Privacy nightmare, read-only |
| **OpenClaw** | Hacker-first, no native UI, security concerns |
| **Open Interpreter** | Terminal-only, scary for normal users |

Apex sits in the sweet spot: **powerful enough for pros, safe enough for everyone**.

## Project Status

- [x] Concept development
- [x] Requirements documentation (platform + first skill)
- [x] Architecture design (extensible skill system)
- [x] MVP roadmap (platform-first approach)
- [ ] Development kickoff
- [ ] Phase 1: Core Platform (skill registry, memory, orchestrator)
- [ ] Phase 2: First Skill (File Organizer)
- [ ] Phase 3: Desktop UI
- [ ] Phase 4: Alpha Release

## Tech Stack (Planned)

| Layer | Technology |
|-------|------------|
| Core Logic | Python + LangGraph |
| Daemon | Rust |
| Desktop UI | Tauri + React/Svelte |
| Memory | ChromaDB / Mem0 |
| LLM | LiteLLM (OpenAI/Anthropic/Google) |
| Integration | MCP (Model Context Protocol) |

## Getting Involved

This project is in early planning. If you're interested in:
- **Building it** — Review the docs and reach out
- **Testing it** — Alpha coming soon
- **Investing** — Let's talk

---

*"The AI that grows with you—starting with your files, evolving into your digital brain."*
