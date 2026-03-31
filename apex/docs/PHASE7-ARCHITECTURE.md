# Phase 7: Trust & Control - Architecture

**Goal:** Your data stays home, you approve every action

## Component Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PHASE 7 ARCHITECTURE                                │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         UI LAYER                                    │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────────┐ │   │
│  │  │ StepPreview  │  │ InlineEditor │  │ ApprovalPanel             │ │   │
│  │  │ Component    │  │ Component    │  │ (doc/email/calc preview)  │ │   │
│  │  └──────────────┘  └──────────────┘  └───────────────────────────┘ │   │
│  │  ┌──────────────────────────────────────────────────────────────┐  │   │
│  │  │ ActionHistory (undo, review past actions)                    │  │   │
│  │  └──────────────────────────────────────────────────────────────┘  │   │
│  │  ┌──────────────────────────────────────────────────────────────┐  │   │
│  │  │ AuditLog Viewer (see what was sent externally)               │  │   │
│  │  └──────────────────────────────────────────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│  ┌─────────────────────────────────▼───────────────────────────────────┐   │
│  │                       CONTROL LAYER                                 │   │
│  │                                                                     │   │
│  │  ┌──────────────────┐    ┌──────────────────┐    ┌───────────────┐ │   │
│  │  │ ApprovalGateway  │    │ TrustLevelMgr    │    │ UndoManager   │ │   │
│  │  │ - queue actions  │    │ - per-action     │    │ - checkpoint  │ │   │
│  │  │ - enforce review │    │ - per-pattern    │    │ - rollback    │ │   │
│  │  └──────────────────┘    └──────────────────┘    └───────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│  ┌─────────────────────────────────▼───────────────────────────────────┐   │
│  │                       PRIVACY LAYER                                 │   │
│  │                                                                     │   │
│  │  ┌──────────────────┐    ┌──────────────────┐    ┌───────────────┐ │   │
│  │  │ ContextMinimizer │    │ RedactionEngine  │    │ AuditLogger   │ │   │
│  │  │ - extract only   │    │ - strip SSN      │    │ - log all     │ │   │
│  │  │   what's needed  │    │ - strip accounts │    │   external    │ │   │
│  │  │ - summarize      │    │ - strip PII      │    │   calls       │ │   │
│  │  └──────────────────┘    └──────────────────┘    └───────────────┘ │   │
│  │                                                                     │   │
│  │  ┌──────────────────┐    ┌──────────────────────────────────────┐  │   │
│  │  │ SensitiveMarker  │    │ LocalVectorDB (ChromaDB/SQLite)      │  │   │
│  │  │ - folder markers │    │ - embeddings stored locally           │  │   │
│  │  │ - file markers   │    │ - no cloud sync                       │  │   │
│  │  └──────────────────┘    └──────────────────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│  ┌─────────────────────────────────▼───────────────────────────────────┐   │
│  │                       DATA LAYER (LOCAL ONLY)                       │   │
│  │                                                                     │   │
│  │  ┌─────────────────────────────────────────────────────────────┐   │   │
│  │  │                    SQLite Database                          │   │   │
│  │  │  • memories.db - semantic memory, entity graph              │   │   │
│  │  │  • patterns.db - learned preferences, routines              │   │   │
│  │  │  • audit.db    - external transmission log                  │   │   │
│  │  │  • actions.db  - action history for undo                    │   │   │
│  │  └─────────────────────────────────────────────────────────────┘   │   │
│  │                                                                     │   │
│  │  ┌─────────────────────────────────────────────────────────────┐   │   │
│  │  │               Local Vector Store (ChromaDB)                 │   │   │
│  │  │  • Document embeddings                                      │   │   │
│  │  │  • Email summaries                                          │   │   │
│  │  │  • Semantic search index                                    │   │   │
│  │  └─────────────────────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 1. Privacy Layer Components

### 1.1 ContextMinimizer

**Purpose:** Ensures only minimal, necessary context goes to the LLM.

**File:** `apex/src/privacy/context_minimizer.py`

```python
"""
ContextMinimizer - Extract only what's needed for LLM queries.

The goal: user asks "What's in my loan document?"
We send: "Summarize this: Principal $425k, Rate 6.5%, Term 30y"
NOT: The entire 50-page PDF

Strategies:
1. Extract key facts from documents (not full text)
2. Summarize emails (subject + key points, not full body)
3. Reference by ID, not content ("email_id_123" not the email)
4. Use semantic chunking - only relevant chunks
"""

class ContextMinimizer:
    """
    Minimizes context sent to external LLMs.
    
    Configurable modes:
    - STRICT: Only summaries and keywords, never raw content
    - BALANCED: Summaries + relevant snippets (default)
    - PERMISSIVE: Full relevant content (user explicitly allows)
    """
    
    def minimize(self, context: Dict, request: str) -> Dict:
        """
        Minimize context for a given request.
        
        Returns only what's needed to answer the request.
        """
        pass
    
    def extract_key_facts(self, document: Dict) -> Dict:
        """Extract only key facts from a document."""
        pass
    
    def summarize_email(self, email: Dict) -> Dict:
        """Create minimal email summary."""
        pass
```

### 1.2 RedactionEngine

**Purpose:** Auto-strips sensitive data before LLM queries.

**File:** `apex/src/privacy/redaction.py`

```python
"""
RedactionEngine - Strip PII before external transmission.

Detects and redacts:
- SSN (XXX-XX-XXXX pattern)
- Credit card numbers
- Bank account numbers
- Phone numbers (optionally)
- Email addresses (optionally)
- Custom patterns (user-defined)

The redacted values are replaced with tokens like [SSN_REDACTED_1]
that can be restored after LLM response if needed.
"""

class RedactionEngine:
    def __init__(self):
        self.patterns = {
            "ssn": r'\b\d{3}-\d{2}-\d{4}\b',
            "credit_card": r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b',
            "bank_account": r'\b\d{9,17}\b',  # Generic account number
        }
        self._redaction_map = {}  # For restoration
    
    def redact(self, text: str) -> str:
        """Redact all sensitive patterns."""
        pass
    
    def restore(self, text: str) -> str:
        """Restore redacted values (if needed)."""
        pass
```

### 1.3 AuditLogger

**Purpose:** Logs every external transmission for user review.

**File:** `apex/src/privacy/audit_log.py`

```python
"""
AuditLogger - Track all external data transmissions.

Every time data leaves the machine, we log:
- Timestamp
- Destination (which LLM provider)
- What was sent (truncated, for review)
- What was received
- Why (which user request triggered it)

User can review: "Show me everything I sent to the LLM this week"
"""

class AuditLogger:
    def __init__(self, db_path: str = "~/.apex/audit.db"):
        pass
    
    def log_transmission(
        self,
        direction: str,  # "outbound" or "inbound"
        destination: str,  # "anthropic", "openai", etc.
        content_preview: str,  # First 500 chars
        content_hash: str,  # SHA256 for verification
        triggering_request: str,  # What the user asked
        bytes_sent: int,
    ) -> str:
        """Log an external transmission."""
        pass
    
    def get_transmissions(
        self,
        since: datetime = None,
        destination: str = None,
    ) -> List[Dict]:
        """Query transmission history."""
        pass
```

### 1.4 SensitiveMarker

**Purpose:** Mark files/folders as "never send to LLM".

**File:** `apex/src/privacy/sensitive_marker.py`

```python
"""
SensitiveMarker - Mark files/folders as sensitive.

Uses a simple .apex-sensitive file in directories, or
file-level markers stored in the local DB.

Marked items are:
- Never included in LLM context (even summaries)
- Shown with a 🔒 icon in UI
- Excluded from semantic search sent externally
"""

class SensitiveMarker:
    def mark_sensitive(self, path: str, recursive: bool = True) -> bool:
        """Mark a file or folder as sensitive."""
        pass
    
    def unmark_sensitive(self, path: str) -> bool:
        """Remove sensitive marker."""
        pass
    
    def is_sensitive(self, path: str) -> bool:
        """Check if a path is marked sensitive."""
        pass
    
    def get_all_sensitive(self) -> List[str]:
        """List all marked paths."""
        pass
```

---

## 2. Control Layer Components

### 2.1 ApprovalGateway

**Purpose:** Central gate that all actions must pass through.

**File:** `apex/src/control/approval_gateway.py`

```python
"""
ApprovalGateway - Every action flows through here.

This is the enforcement layer. No action executes without:
1. Passing through the gateway
2. Getting appropriate approval (based on trust level)
3. Being logged for audit

The gateway also:
- Queues actions for batched approval
- Groups related actions together
- Provides previews for each action type
"""

@dataclass
class PendingAction:
    id: str
    action_type: str  # "send_email", "delete_file", "create_event", etc.
    payload: Dict[str, Any]
    preview: Dict[str, Any]  # Human-readable preview
    risk_level: str  # "low", "medium", "high", "critical"
    reversible: bool
    requires_approval: bool
    approved: Optional[bool] = None
    created_at: datetime = field(default_factory=datetime.now)


class ApprovalGateway:
    def __init__(self, trust_manager: 'TrustLevelManager'):
        self._pending: Dict[str, PendingAction] = {}
        self._trust = trust_manager
        self._undo_manager = UndoManager()
    
    async def submit(self, action: PendingAction) -> str:
        """
        Submit an action for approval.
        
        Returns action ID for tracking.
        Based on trust level, may auto-approve or queue for user.
        """
        pass
    
    async def approve(self, action_id: str, modifications: Dict = None) -> Dict:
        """
        Approve an action, optionally with modifications.
        
        User can edit the action before approving:
        - Modify email text
        - Change recipient
        - Adjust calculation parameters
        """
        pass
    
    async def reject(self, action_id: str, reason: str = None) -> bool:
        """Reject an action."""
        pass
    
    def get_pending(self) -> List[PendingAction]:
        """Get all pending actions for UI display."""
        pass
```

### 2.2 TrustLevelManager

**Purpose:** Manages per-action trust levels.

**File:** `apex/src/control/trust_levels.py`

```python
"""
TrustLevelManager - Control what needs approval.

Trust Levels:
- ALWAYS_ASK (🔴): Always require explicit approval
- ASK_ONCE (🟡): Ask first time, offer to remember
- AUTO_APPROVE (🟢): User has pre-approved this action type

Default trust levels by action type:
- send_email: ALWAYS_ASK
- delete_file: ALWAYS_ASK  
- create_event: ASK_ONCE
- read_file: AUTO_APPROVE
- search: AUTO_APPROVE

Users can customize per action type, per recipient, per pattern.
"""

class TrustLevel(Enum):
    ALWAYS_ASK = "always_ask"      # 🔴 Always confirm
    ASK_ONCE = "ask_once"          # 🟡 Learn pattern
    AUTO_APPROVE = "auto_approve"  # 🟢 Trusted

class TrustLevelManager:
    # Default trust levels
    DEFAULT_LEVELS = {
        # High risk - always ask
        "send_email": TrustLevel.ALWAYS_ASK,
        "delete_file": TrustLevel.ALWAYS_ASK,
        "move_to_trash": TrustLevel.ALWAYS_ASK,
        "send_slack_message": TrustLevel.ALWAYS_ASK,
        "create_calendar_event": TrustLevel.ASK_ONCE,
        "create_task": TrustLevel.ASK_ONCE,
        
        # Medium risk - ask once, then remember
        "create_document": TrustLevel.ASK_ONCE,
        "modify_file": TrustLevel.ASK_ONCE,
        
        # Low risk - auto approve
        "read_file": TrustLevel.AUTO_APPROVE,
        "search_files": TrustLevel.AUTO_APPROVE,
        "search_email": TrustLevel.AUTO_APPROVE,
        "list_directory": TrustLevel.AUTO_APPROVE,
    }
    
    def get_trust_level(self, action_type: str, context: Dict = None) -> TrustLevel:
        """Get trust level for an action, considering context."""
        pass
    
    def set_trust_level(self, action_type: str, level: TrustLevel, pattern: Dict = None):
        """Set trust level, optionally for a specific pattern."""
        pass
    
    def remember_approval(self, action_type: str, pattern: Dict):
        """Remember that user approved this pattern (for ASK_ONCE)."""
        pass
```

### 2.3 UndoManager

**Purpose:** Checkpoint and rollback for reversible actions.

**File:** `apex/src/control/undo_manager.py`

```python
"""
UndoManager - Undo recent actions.

Before executing any action, we checkpoint the state.
User can then undo recent actions:
- "Undo the last email" → moves sent email to drafts
- "Undo file moves" → moves files back to original locations
- "Undo calendar event" → deletes the created event

Limitations (made clear to user):
- Some actions are not reversible (e.g., external API calls)
- Time limit on undo (e.g., 24 hours)
- Some actions require service support (e.g., Gmail unsend window)
"""

@dataclass
class Checkpoint:
    id: str
    action_id: str
    action_type: str
    timestamp: datetime
    before_state: Dict[str, Any]
    after_state: Dict[str, Any]
    reversible: bool
    reversed: bool = False

class UndoManager:
    def __init__(self, db_path: str = "~/.apex/actions.db"):
        self._checkpoints: Dict[str, Checkpoint] = {}
        self._max_age_hours = 24
    
    def checkpoint(self, action_id: str, action_type: str, before_state: Dict) -> str:
        """Create a checkpoint before executing an action."""
        pass
    
    def record_after(self, checkpoint_id: str, after_state: Dict):
        """Record the state after action execution."""
        pass
    
    async def undo(self, action_id: str) -> bool:
        """Attempt to undo an action."""
        pass
    
    def get_undoable(self, limit: int = 20) -> List[Checkpoint]:
        """Get recent undoable actions."""
        pass
```

---

## 3. Local Data Storage

### 3.1 LocalVectorDB

**Purpose:** Store embeddings locally (no cloud).

**File:** `apex/src/storage/local_vector_db.py`

```python
"""
LocalVectorDB - Local semantic search.

Uses ChromaDB or SQLite-vec for local vector storage.
No data leaves the machine for indexing.

Embeddings are generated:
- Locally (using sentence-transformers) - preferred
- Or via API with minimal text (just titles/summaries)
"""

class LocalVectorDB:
    def __init__(self, db_path: str = "~/.apex/vectors"):
        # Use ChromaDB with local persistence
        self._client = chromadb.PersistentClient(path=db_path)
        self._collection = self._client.get_or_create_collection("apex_memory")
    
    def add_document(self, doc_id: str, content: str, metadata: Dict) -> bool:
        """Index a document locally."""
        pass
    
    def search(self, query: str, limit: int = 10) -> List[Dict]:
        """Semantic search (all local)."""
        pass
    
    def delete(self, doc_id: str) -> bool:
        """Remove from index."""
        pass
```

### 3.2 ActionHistoryDB

**Purpose:** Store action history for undo and review.

**File:** `apex/src/storage/action_history.py`

```python
"""
ActionHistoryDB - Track all actions for undo and audit.

Every action Apex takes is logged:
- What was done
- When
- Result
- Reversibility
- User who approved

Users can review: "What did Apex do today?"
"""
```

---

## 4. UI Components

### 4.1 StepPreview Component

Shows each step of a multi-step workflow with full preview.

```html
<!-- Enhanced step preview with inline editing -->
<div class="step-preview">
    <div class="step-header">
        <span class="step-number">Step 1 of 3</span>
        <span class="step-title">📄 Document Found</span>
        <span class="step-status pending">Awaiting Approval</span>
    </div>
    
    <div class="step-content">
        <!-- Document preview -->
        <div class="document-preview">
            <h4>2024-Home-Loan-Agreement.pdf</h4>
            <table class="key-facts">
                <tr><td>Principal:</td><td>$425,000.00</td></tr>
                <tr><td>Rate:</td><td>6.5% APR</td></tr>
                <tr><td>Term:</td><td>30 years</td></tr>
            </table>
        </div>
    </div>
    
    <div class="step-actions">
        <button class="btn-approve">✓ This is correct</button>
        <button class="btn-modify">Find different document</button>
    </div>
</div>
```

### 4.2 InlineEditor Component

Allows editing draft content before approval.

```html
<!-- Inline email editor -->
<div class="inline-editor email-editor">
    <div class="editor-field">
        <label>To:</label>
        <input type="email" value="rob@sagecg.com" />
        <button class="btn-change">Change</button>
    </div>
    <div class="editor-field">
        <label>Subject:</label>
        <input type="text" value="Loan Summary & Amortization" />
    </div>
    <div class="editor-body">
        <label>Message:</label>
        <textarea rows="10">
Hi Rob,

Here's the summary of the home loan...
        </textarea>
    </div>
    <div class="editor-attachments">
        <label>Attachments:</label>
        <div class="attachment">📎 Amortization-Schedule.pdf (42 KB) [Remove]</div>
        <button class="btn-add">+ Add attachment</button>
    </div>
</div>
```

### 4.3 AuditLogViewer

Shows what was sent externally.

```html
<!-- Audit log viewer -->
<div class="audit-log-viewer">
    <h3>🔍 External Transmissions</h3>
    <div class="filter-bar">
        <select class="destination-filter">
            <option value="">All destinations</option>
            <option value="anthropic">Anthropic Claude</option>
            <option value="openai">OpenAI</option>
        </select>
        <input type="date" class="date-filter" />
    </div>
    
    <div class="transmission-list">
        <div class="transmission">
            <span class="time">2:34 PM</span>
            <span class="destination">→ Anthropic Claude</span>
            <span class="preview">"Summarize loan document: Principal $425k..."</span>
            <span class="size">1.2 KB sent</span>
            <button class="btn-details">View full</button>
        </div>
    </div>
</div>
```

---

## 5. Implementation Order

### Sprint 1: Foundation (Week 1-2)
1. **AuditLogger** - Start logging all LLM calls immediately
2. **TrustLevelManager** - Basic trust levels with defaults
3. **ApprovalGateway** - Wire existing orchestrator through gateway

### Sprint 2: Privacy Core (Week 3-4)
4. **RedactionEngine** - SSN, credit card, account number detection
5. **SensitiveMarker** - File/folder marking system
6. **ContextMinimizer** - Document summarization, email minimization

### Sprint 3: Local Storage (Week 5-6)
7. **LocalVectorDB** - ChromaDB setup with local embeddings
8. **ActionHistoryDB** - Action logging for undo
9. **UndoManager** - Basic undo for reversible actions

### Sprint 4: UI Enhancement (Week 7-8)
10. **StepPreview Component** - Enhanced step-by-step UI
11. **InlineEditor Component** - Edit emails/docs before sending
12. **AuditLogViewer** - View external transmissions

### Sprint 5: Integration (Week 9-10)
13. Wire all components together
14. End-to-end testing with real workflows
15. Trust level learning (ASK_ONCE patterns)

---

## 6. Success Criteria

### Privacy Metrics
- [ ] Zero raw document content sent to LLM (only summaries)
- [ ] 100% of external transmissions logged
- [ ] Sensitive files never appear in LLM context
- [ ] SSN/account numbers auto-redacted (100% detection)

### Control Metrics
- [ ] 100% of send/delete actions require approval
- [ ] Undo works for 95% of reversible actions
- [ ] Step previews show accurate representation
- [ ] Inline editing works without data loss

### UX Metrics
- [ ] Approval flow adds <500ms latency
- [ ] Users can review audit log in <3 clicks
- [ ] Trust level customization is intuitive
- [ ] Undo is discoverable and reliable

---

## 7. Files to Create

```
apex/
├── src/
│   ├── privacy/
│   │   ├── __init__.py
│   │   ├── context_minimizer.py    # Minimize LLM context
│   │   ├── redaction.py            # PII redaction
│   │   ├── audit_log.py            # Transmission logging
│   │   └── sensitive_marker.py     # File/folder markers
│   │
│   ├── control/
│   │   ├── __init__.py
│   │   ├── approval_gateway.py     # Central approval gate
│   │   ├── trust_levels.py         # Trust level management
│   │   └── undo_manager.py         # Checkpoint/rollback
│   │
│   └── storage/
│       ├── __init__.py
│       ├── local_vector_db.py      # ChromaDB wrapper
│       └── action_history.py       # Action logging
│
├── ui/
│   ├── components/
│   │   ├── step-preview.html       # Step preview component
│   │   ├── inline-editor.html      # Inline editing
│   │   └── audit-viewer.html       # Audit log viewer
│   └── index.html                  # Enhanced with new components
│
└── tests/
    ├── test_privacy.py             # Privacy layer tests
    ├── test_control.py             # Control layer tests
    └── test_undo.py                # Undo functionality tests
```
