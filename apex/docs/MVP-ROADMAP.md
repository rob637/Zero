# MVP Roadmap: APEX
## From Concept to Prototype in 12 Weeks

---

## 1. MVP Philosophy

> **"Build the platform, ship the first skill."**

We're not building a file organizer—we're building **the foundation for a personal AI operating system**. File organization is the first skill that proves the platform works.

The MVP must demonstrate:
1. ✅ **Skill architecture works** — New capabilities = new Skill module
2. ✅ **Memory is shared** — Facts persist and inform all skills
3. ✅ **HITL is enforced** — Dangerous actions require approval
4. ✅ **One skill works great** — File Organizer is polished and useful

The MVP does **NOT** need:
- ❌ Multiple skills (browser, email)
- ❌ Beautiful settings page
- ❌ Cross-platform support
- ❌ Voice interface

---

## 2. Phase Overview

| Phase | Duration | Goal | Deliverable |
|-------|----------|------|-------------|
| **Phase 0** | 1 week | Foundation Setup | Dev environment, CI/CD, project structure |
| **Phase 1** | 3 weeks | Core Platform | Skill registry, Memory engine, Orchestrator shell |
| **Phase 2** | 3 weeks | First Skill: File Organizer | Complete file operations with sandbox |
| **Phase 3** | 3 weeks | Desktop UI | System tray orb + approval dialogs |
| **Phase 4** | 2 weeks | Integration & Polish | End-to-end testing, bug fixes |

**Total: 12 weeks to working prototype**

### Why This Order?

```
Week 1-4:   Build the PLATFORM (skills, memory, orchestrator)
            ↓
            This foundation supports ALL future skills
            ↓
Week 5-7:   Build FIRST SKILL (file organizer) on top
            ↓
            Proves the platform works
            ↓
Week 8-12:  Build UI + Polish
            ↓
            Ship something users can touch
```

---

## 3. Phase 0: Foundation (Week 1)

### Objectives
- Set up development environment
- Establish project structure
- Configure CI/CD pipeline

### Tasks

| # | Task | Owner | Est. Hours |
|---|------|-------|------------|
| 0.1 | Create Git repository with branch protection | Dev Lead | 2 |
| 0.2 | Set up Python environment (Poetry/uv) | Backend Dev | 4 |
| 0.3 | Set up Rust environment for daemon | Backend Dev | 4 |
| 0.4 | Initialize Tauri project for UI | Frontend Dev | 4 |
| 0.5 | Configure GitHub Actions (lint, test, build) | Dev Lead | 4 |
| 0.6 | Write initial README and contributing guide | Dev Lead | 2 |
| 0.7 | Set up local LLM for development (Ollama) | Backend Dev | 2 |

### Deliverables
- [ ] Monorepo structure established
- [ ] All developers can build locally
- [ ] CI pipeline runs on every PR

### Project Structure

```
apex/
├── README.md
├── .github/
│   └── workflows/
│       ├── ci.yml
│       └── release.yml
├── core/                    # Python - AI logic
│   ├── pyproject.toml
│   ├── apex/
│   │   ├── __init__.py
│   │   ├── brain/           # LLM interaction
│   │   ├── memory/          # Vector DB
│   │   ├── tasks/           # LangGraph workflows
│   │   ├── mcp/             # MCP clients
│   │   └── security/        # Gateway, scrubber
│   └── tests/
├── daemon/                  # Rust - Persistent service
│   ├── Cargo.toml
│   └── src/
│       └── main.rs
├── ui/                      # Tauri - Desktop app
│   ├── package.json
│   ├── src-tauri/
│   └── src/                 # React/Svelte frontend
└── docs/
    ├── PRD.md
    ├── ARCHITECTURE.md
    └── MVP-ROADMAP.md
```

---

## 4. Phase 1: Core Platform (Weeks 2-4)

### Objectives
- Build the Skill Registry (extensible architecture)
- Implement Memory Engine with vector search
- Create Orchestrator shell that routes to skills
- CLI interface for testing

### Sprint 1.1: Skill System Foundation (Week 2)

| # | Task | Description | Est. Hours |
|---|------|-------------|------------|
| 1.1.1 | Define Skill base class | Abstract interface from architecture doc | 4 |
| 1.1.2 | Implement SkillRegistry | Registration, discovery, routing | 6 |
| 1.1.3 | Create stub FileOrganizerSkill | Skeleton that returns "not implemented" | 4 |
| 1.1.4 | Implement LiteLLM wrapper | Unified API for OpenAI/Anthropic/Google | 8 |
| 1.1.5 | Create intent classification | LLM determines which skill handles request | 6 |
| 1.1.6 | Write unit tests | Skill routing, intent classification | 6 |

**Milestone:** Can route "clean my downloads" to FileOrganizerSkill (stub).

### Sprint 1.2: Memory Engine (Week 3)

| # | Task | Description | Est. Hours |
|---|------|-------------|------------|
| 1.2.1 | Set up ChromaDB locally | Initial configuration | 4 |
| 1.2.2 | Implement Memory class | Schema from architecture doc | 6 |
| 1.2.3 | Create embedding pipeline | Use sentence-transformers (local) | 6 |
| 1.2.4 | Implement store/query/update operations | Core CRUD for memories | 8 |
| 1.2.5 | Add fact extraction from conversations | LLM extracts key facts | 6 |

**Milestone:** User facts persist across CLI sessions. Memory API ready for all skills.

### Sprint 1.3: Orchestrator + Context (Week 4)

| # | Task | Description | Est. Hours |
|---|------|-------------|------------|
| 1.3.1 | Implement LangGraph Orchestrator | Base workflow: intent → skill → execute | 10 |
| 1.3.2 | Build context retrieval pipeline | Query memory before each request | 6 |
| 1.3.3 | Add skill selection logic | Multi-skill detection, confidence scoring | 6 |
| 1.3.4 | Implement TaskPlan structure | Inspectable, approvable action plans | 6 |
| 1.3.5 | Integration tests | End-to-end orchestrator flow | 6 |
| 1.3.6 | CLI polish | Nice formatting, debug mode | 4 |

**Milestone:** Platform routes requests to skills with memory context.

### Phase 1 Success Criteria

```bash
# The PLATFORM works (skill routing + memory)
$ apex chat
> My name is Rob and I prefer PDFs in Documents/
Apex: Got it, Rob! I'll remember that preference.

> Clean my Downloads folder
Apex: [Routes to FileOrganizerSkill]
       Skill response: "File organization not yet implemented. 
       But I know you prefer PDFs in Documents/!"

# Memory persists across sessions
$ apex chat  
> What do you know about me?
Apex: You're Rob. You prefer PDFs saved to Documents/.
```

---

## 5. Phase 2: First Skill - File Organizer (Weeks 5-7)

### Objectives
- Implement complete FileOrganizerSkill
- Build MCP filesystem client
- Create execution sandbox
- Wire up HITL approval flow

### Sprint 2.1: Filesystem MCP + Skill Planning (Week 5)

| # | Task | Description | Est. Hours |
|---|------|-------------|------------|
| 2.1.1 | Implement MCP client base class | Protocol handling | 8 |
| 2.1.2 | Create filesystem MCP server | list, read, write, move, delete | 12 |
| 2.1.3 | Add path permission checking | Respect allowed/denied paths | 6 |
| 2.1.4 | Implement FileOrganizerSkill.plan() | LLM generates file operation plan | 8 |
| 2.1.5 | Write filesystem + planning tests | Edge cases, permissions | 6 |

**Milestone:** LLM can analyze folder and propose organization plan.

### Sprint 2.2: Execution Sandbox (Week 6)

| # | Task | Description | Est. Hours |
|---|------|-------------|------------|
| 2.2.1 | Create Docker sandbox image | Python + common tools | 8 |
| 2.2.2 | Implement sandbox executor | Volume mounts, network isolation | 10 |
| 2.2.3 | Add code validation layer | Block dangerous operations | 8 |
| 2.2.4 | Implement timeout handling | Kill runaway processes | 4 |
| 2.2.5 | Security tests | Escape attempts | 8 |

**Milestone:** AI-generated code runs in isolation.

### Sprint 2.3: Complete Skill + HITL (Week 7)

| # | Task | Description | Est. Hours |
|---|------|-------------|------------|
| 2.3.1 | Implement FileOrganizerSkill.execute() | Execute approved plans | 10 |
| 2.3.2 | Create risk assessment module | Classify action severity | 6 |
| 2.3.3 | Build CLI approval flow | Show plan, wait for yes/no | 6 |
| 2.3.4 | Add rollback capability | Undo via Recycle Bin | 6 |
| 2.3.5 | Integration tests | Full cleanup workflow via Skill | 8 |

**Milestone:** Complete "clean my downloads" via FileOrganizerSkill with approval.

### Phase 2 Success Criteria

```bash
$ apex chat
> Clean up my Downloads folder

Apex: [FileOrganizerSkill activated]
      Analyzing Downloads... found 47 files.
      
      Here's my plan based on your preferences:
      (I know you prefer PDFs in Documents/)

📁 PLANNED ACTIONS:
├── Move 12 PDFs → Documents/Downloads-PDFs/
├── Move 8 images → Pictures/Downloads-Images/
├── Delete 15 old installers (2.1 GB)
└── Keep 5 recent files in place

⚠️  This will modify 35 files and free 2.1 GB.

Proceed? [y/N]: y

Apex: ✓ Done! Organized 35 files. 
      Memory updated: "Last cleanup: Downloads, 2026-03-29"
```

---

## 6. Phase 3: Desktop UI (Weeks 8-10)

### Objectives
- Create system tray orb
- Build approval dialog windows
- Implement sidebar (basic version)

### Sprint 3.1: System Tray + Daemon (Week 8)

| # | Task | Description | Est. Hours |
|---|------|-------------|------------|
| 3.1.1 | Create Tauri project shell | Basic window + tray | 8 |
| 3.1.2 | Implement Rust daemon | Startup, IPC with Python core | 12 |
| 3.1.3 | Add system tray with orb states | Blue/green/gold/red | 8 |
| 3.1.4 | Create tray menu | Open, Pause, Settings, Quit | 4 |

**Milestone:** App starts with system, shows orb in tray.

### Sprint 3.2: Approval Dialogs (Week 9)

| # | Task | Description | Est. Hours |
|---|------|-------------|------------|
| 3.2.1 | Design approval dialog UI | Mockup → React/Svelte | 8 |
| 3.2.2 | Implement dialog component | Plan display, buttons | 10 |
| 3.2.3 | Connect dialog to daemon | IPC messaging | 8 |
| 3.2.4 | Add keyboard shortcuts | Enter = approve, Esc = cancel | 2 |
| 3.2.5 | Test approval flow | End-to-end | 4 |

**Milestone:** File cleanup shows native approval dialog.

### Sprint 3.3: Basic Sidebar (Week 10)

| # | Task | Description | Est. Hours |
|---|------|-------------|------------|
| 3.3.1 | Create sidebar layout | Orb + input + timeline | 10 |
| 3.3.2 | Implement input bar | Text entry, submit | 6 |
| 3.3.3 | Add memory timeline | Last 10 actions | 8 |
| 3.3.4 | Implement quick actions | 3 preset buttons | 6 |
| 3.3.5 | Style with glass morphism | Match Windows 11 aesthetic | 6 |

**Milestone:** Functional sidebar for basic interactions.

### Phase 3 Success Criteria

- [ ] App appears in system tray on Windows login
- [ ] Clicking orb opens sidebar
- [ ] User can type request in sidebar
- [ ] Approval dialog appears for file operations
- [ ] Timeline shows recent actions

---

## 7. Phase 4: Integration & Polish (Weeks 11-12)

### Objectives
- End-to-end testing
- Bug fixing
- Documentation
- Prepare for alpha release

### Sprint 4.1: Integration Testing (Week 11)

| # | Task | Description | Est. Hours |
|---|------|-------------|------------|
| 4.1.1 | Write E2E test suite | Playwright for UI | 12 |
| 4.1.2 | Test all user journeys | Happy paths | 8 |
| 4.1.3 | Test error scenarios | Network failure, API errors | 8 |
| 4.1.4 | Performance profiling | Memory, CPU, startup time | 6 |
| 4.1.5 | Security audit | Basic penetration testing | 8 |

### Sprint 4.2: Polish & Ship (Week 12)

| # | Task | Description | Est. Hours |
|---|------|-------------|------------|
| 4.2.1 | Bug triage and fixes | Critical/high priority only | 16 |
| 4.2.2 | Create installer | MSI for Windows | 8 |
| 4.2.3 | Write user documentation | Getting started guide | 6 |
| 4.2.4 | Set up crash reporting | Sentry or similar | 4 |
| 4.2.5 | Create demo video | 2-minute walkthrough | 4 |
| 4.2.6 | Alpha release | Internal/limited distribution | 4 |

---

## 8. MVP Feature Matrix

| Feature | MVP | v1.1 | v1.2 | v2.0 |
|---------|-----|------|------|------|
| **Platform** |
| Skill Registry | ✅ | ✅ | ✅ | ✅ |
| Skill routing/orchestration | ✅ | ✅ | ✅ | ✅ |
| Shared Memory Engine | ✅ | ✅ | ✅ | ✅ |
| HITL enforcement | ✅ | ✅ | ✅ | ✅ |
| Execution sandbox | ✅ | ✅ | ✅ | ✅ |
| **Skills** |
| File Organizer | ✅ | ✅ | ✅ | ✅ |
| Browser Agent | ❌ | ✅ | ✅ | ✅ |
| Communication Hub | ❌ | ❌ | ✅ | ✅ |
| Screen Understanding | ❌ | ❌ | ❌ | ✅ |
| Voice Interface | ❌ | ❌ | ❌ | ✅ |
| **UI** |
| System tray orb | ✅ | ✅ | ✅ | ✅ |
| Approval dialogs | ✅ | ✅ | ✅ | ✅ |
| Basic sidebar | ✅ | ✅ | ✅ | ✅ |
| HUD overlay | ❌ | ✅ | ✅ | ✅ |
| Settings page | ❌ | ✅ | ✅ | ✅ |
| **Platform** |
| Windows | ✅ | ✅ | ✅ | ✅ |
| macOS | ❌ | ✅ | ✅ | ✅ |
| Linux | ❌ | ❌ | ✅ | ✅ |

---

## 9. Team Requirements

### Minimum Team (for MVP)

| Role | Count | Focus |
|------|-------|-------|
| **Backend/AI Engineer** | 1-2 | Python core, LangGraph, memory |
| **Systems/Rust Developer** | 1 | Daemon, sandbox, security |
| **Frontend Developer** | 1 | Tauri UI, React/Svelte |

### Ideal Team (faster delivery)

| Role | Count | Focus |
|------|-------|-------|
| **Tech Lead** | 1 | Architecture, code review |
| **Backend/AI Engineer** | 2 | Split brain/memory vs tasks/MCP |
| **Systems Developer** | 1 | Rust daemon, sandbox |
| **Frontend Developer** | 1-2 | UI/UX |
| **QA Engineer** | 1 | Testing, security audit |

---

## 10. Risk Mitigation

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| LLM API costs exceed budget | Medium | Implement spending caps, use cheaper models for simple tasks |
| Tauri has Windows compatibility issues | Low | Keep Electron as fallback option |
| Memory performance degrades with scale | Medium | Implement pagination, archival |
| Security vulnerability discovered | Medium | Bug bounty for alpha testers |
| Key developer leaves | Medium | Document everything, pair programming |

---

## 11. Post-MVP Roadmap

### v1.1 (4 weeks after MVP)
- **Browser Agent Skill** — Web research, form filling
- HUD overlay for real-time operations
- Settings page
- macOS support

### v1.2 (8 weeks after MVP)
- **Communication Hub Skill** — Email, Slack, calendar
- Google Drive integration
- Workflow templates ("Prepare for tax season")

### v2.0 (Future)
- **Screen Understanding Skill** — OCR, visual context
- **Voice Interface Skill** — Ambient listening
- Proactive suggestions
- Plugin marketplace for community skills

---

## 12. Success Metrics for MVP

| Metric | Target |
|--------|--------|
| Time from idea to working prototype | ≤12 weeks |
| Platform features complete (skill system, memory, orchestrator) | 100% |
| File Organizer skill complete | 100% |
| Critical bugs | 0 |
| Can complete "clean downloads" task | Yes |
| User memory persists across restarts | Yes |
| Memory informs skill behavior | Yes |
| No unintentional file deletions | Yes |
| Adding a new skill requires only new Skill class | Yes |
| Internal testers can install & use | Yes |

---

## Appendix: Sprint Planning Template

```markdown
## Sprint X.Y: [Name]

**Dates:** YYYY-MM-DD to YYYY-MM-DD
**Goal:** [One sentence goal]

### Planned Work
| Ticket | Description | Owner | Points | Status |
|--------|-------------|-------|--------|--------|
| AX-001 | ... | @dev | 3 | 🔲 |

### Blockers
- None yet

### Retrospective Notes
- What went well:
- What could improve:
- Action items:
```

---

*Roadmap Version: 1.0*
*Last Updated: March 2026*
