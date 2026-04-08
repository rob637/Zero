# Connector Infrastructure Buildout Plan

## Executive Summary

Build a complete connector infrastructure that:
1. Makes it **trivially easy** for users to connect services
2. Supports **multiple providers per primitive** (Gmail + Outlook for EMAIL)
3. Provides **central management** of all connections with health monitoring
4. Includes **all connectors** needed for our 36 primitives

---

## Current State

| Metric | Count |
|--------|-------|
| Primitives | 36 |
| Operations | 194 |
| Existing Connectors | 20 |
| Primitives with connectors | 13 (36%) |
| **Gap** | 10 primitives need connectors |

### Existing Connectors
```
Google:     gmail, calendar, contacts, drive, youtube
Microsoft:  outlook, outlook_calendar, onedrive, microsoft_todo, teams
Dev:        github, jira, slack, discord
Other:      todoist, spotify, dropbox, twilio_sms, web_search, desktop_notify
```

### Missing Connectors (by primitive)
```
SPREADSHEET:   google_sheets, excel_online
PRESENTATION:  google_slides, powerpoint_online  
NOTES:         google_keep, onenote
PHOTO:         google_photos, icloud_photos
FINANCE:       plaid, stripe
SOCIAL:        twitter, linkedin
RIDE:          uber, lyft
TRAVEL:        amadeus (flights), booking.com
HOME:          smartthings, hue, homeassistant
SHOPPING:      (no public APIs - use web scraping)
```

---

## Phase 1: ConnectorRegistry (Foundation)
**Time: 2-3 hours | Priority: Critical**

Create central connector management:

```python
class ConnectorRegistry:
    """Central management of all connectors."""
    
    def __init__(self, storage_path: Path):
        self._connectors: Dict[str, Connector] = {}
        self._credentials: CredentialStore = CredentialStore(storage_path)
        self._health: Dict[str, ConnectorHealth] = {}
    
    # Registration
    def register(self, name: str, connector_class: Type[Connector], config: Dict)
    def unregister(self, name: str)
    
    # Connection management  
    def connect(self, name: str) -> bool  # Initiates OAuth or API key setup
    def disconnect(self, name: str)
    def is_connected(self, name: str) -> bool
    def get_status(self, name: str) -> ConnectorHealth
    
    # Provider lookup
    def get_providers_for_primitive(self, primitive: str) -> List[str]
    def get_connector(self, name: str) -> Optional[Connector]
    
    # Health monitoring
    def check_health(self, name: str) -> ConnectorHealth
    def refresh_token(self, name: str) -> bool
```

### Credential Storage (Secure)
```python
class CredentialStore:
    """Encrypted storage for OAuth tokens and API keys."""
    
    def store(self, service: str, credentials: Dict)
    def retrieve(self, service: str) -> Optional[Dict]
    def delete(self, service: str)
    def list_services(self) -> List[str]
    
    # Auto-refresh
    def needs_refresh(self, service: str) -> bool
    def refresh(self, service: str) -> bool
```

---

## Phase 2: OAuth Setup Endpoints
**Time: 3-4 hours | Priority: High**

Add to server.py:

```python
# OAuth initiation
GET  /connect/{provider}          # Redirects to OAuth consent
GET  /connect/{provider}/callback # Handles OAuth callback
POST /connect/{provider}/apikey   # For API-key based services

# Status
GET  /connectors                  # List all connectors + status
GET  /connectors/{name}/status    # Health check
POST /connectors/{name}/refresh   # Force token refresh
DELETE /connectors/{name}         # Disconnect

# Easy setup wizard
GET  /setup                       # Interactive setup wizard page
POST /setup/test/{connector}      # Test a connector
```

### User Experience Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    TELIC SETUP WIZARD                        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Connect your services to unlock Telic's full potential:    │
│                                                              │
│  📧 Email                                                    │
│     [Connect Gmail]  [Connect Outlook]  ✅ Connected         │
│                                                              │
│  📅 Calendar                                                 │
│     [Connect Google Calendar]  [Connect Outlook Calendar]   │
│                                                              │
│  📁 Cloud Storage                                            │
│     [Connect Google Drive]  [Connect OneDrive]  [Dropbox]   │
│                                                              │
│  💬 Messaging                                                │
│     [Connect Slack]  [Connect Teams]  [Connect Discord]     │
│                                                              │
│  ─────────────────────────────────────────────────────────  │
│  Status: 3/12 services connected                             │
│  [Skip for now]  [Continue to Telic →]                      │
└─────────────────────────────────────────────────────────────┘
```

---

## Phase 3: Multi-Provider Primitive Support
**Time: 2-3 hours | Priority: High**

Update primitives to support multiple providers:

```python
class EmailPrimitive(Primitive):
    def __init__(self, providers: Dict[str, EmailProvider]):
        """
        providers = {
            "gmail": GmailConnector(...),
            "outlook": OutlookConnector(...),
        }
        """
        self._providers = providers
    
    async def execute(self, operation: str, params: Dict) -> StepResult:
        # Explicit provider selection
        provider_name = params.get("provider")
        
        if provider_name:
            # Use specific provider
            provider = self._providers.get(provider_name)
            if not provider:
                return StepResult(False, error=f"Provider not connected: {provider_name}")
            return await self._execute_with_provider(operation, params, provider)
        
        # Aggregate mode (for search/list)
        if operation in ("search", "list"):
            return await self._aggregate_across_providers(operation, params)
        
        # Default to first available provider (for send)
        for name, provider in self._providers.items():
            return await self._execute_with_provider(operation, params, provider)
        
        return StepResult(False, error="No email providers connected")
    
    async def _aggregate_across_providers(self, operation, params):
        """Search/list across ALL connected providers."""
        all_results = []
        for name, provider in self._providers.items():
            result = await self._execute_with_provider(operation, params, provider)
            if result.success:
                for item in result.data.get("results", []):
                    item["_provider"] = name  # Tag source
                    all_results.append(item)
        return StepResult(True, data={"results": all_results})
```

---

## Phase 4: Add Missing Connectors
**Time: 8-10 hours | Priority: Medium-High**

### Google Workspace (reuse google_auth.py)
| Connector | API | Complexity |
|-----------|-----|------------|
| google_sheets | Google Sheets API v4 | Medium |
| google_slides | Google Slides API v1 | Medium |
| google_photos | Google Photos Library API | Medium |
| google_keep | No official API - use Tasks | Low |

### Microsoft 365 (reuse microsoft_auth.py)
| Connector | API | Complexity |
|-----------|-----|------------|
| excel_online | Microsoft Graph | Medium |
| powerpoint_online | Microsoft Graph | Medium |
| onenote | Microsoft Graph | Medium |

### Finance
| Connector | API | Complexity |
|-----------|-----|------------|
| plaid | Plaid API | High (requires signup) |
| stripe | Stripe API | Medium |

### Social
| Connector | API | Complexity |
|-----------|-----|------------|
| twitter | Twitter API v2 | Medium |
| linkedin | LinkedIn API | High (restricted) |

### Smart Home
| Connector | API | Complexity |
|-----------|-----|------------|
| smartthings | SmartThings API | Medium |
| hue | Philips Hue Local API | Low |
| homeassistant | Home Assistant REST API | Low |

---

## Phase 5: AI-Assisted Setup
**Time: 2-3 hours | Priority: Medium**

Let Telic help users set up connections:

```
User: "Connect my Gmail"

Telic: "I'll help you connect Gmail. Here's what we need to do:

1. You'll be redirected to Google to sign in
2. Grant Telic permission to read/send emails
3. You'll be redirected back here

[Click here to connect Gmail →]

Or if you prefer, you can:
- Use an App Password (for accounts with 2FA)
- Connect via API key (for Google Workspace admins)"
```

### Conversational Setup
```python
# In planner, detect setup intents
if "connect" in request.lower() and any(s in request.lower() for s in ["gmail", "outlook", "slack"]):
    return [
        PlanStep(primitive="SETUP", operation="initiate", params={"service": detected_service})
    ]
```

---

## Phase 6: Make It EASY
**Time: 3-4 hours | Priority: Critical**

### Option A: Hosted OAuth (Easiest for Users)
We host the OAuth client IDs - user just clicks "Connect":

```
Pros: One-click setup
Cons: We need to register apps with Google, Microsoft, etc.
      Users trust us with tokens
```

### Option B: Bring Your Own Keys
User provides their own API keys/OAuth apps:

```
Pros: User owns their credentials
Cons: More complex setup
```

### Option C: Hybrid (Recommended)
- **Common services** (Google, Microsoft): We provide hosted OAuth
- **Developer services** (GitHub, Jira): User brings own tokens
- **Sensitive services** (Finance): User must bring own keys

### Setup Experience

```
┌─────────────────────────────────────────────────────────────┐
│  🚀 Quick Setup (Recommended)                               │
│                                                              │
│  Connect to Google (Gmail, Calendar, Drive, Photos)         │
│  [One-Click Connect with Google] ← OAuth popup              │
│                                                              │
│  Connect to Microsoft (Outlook, Calendar, OneDrive)         │
│  [One-Click Connect with Microsoft] ← OAuth popup           │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│  🔧 Advanced Setup                                           │
│                                                              │
│  For developers who want to use their own credentials:      │
│  [I'll provide my own API keys]                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Implementation Order

```
Week 1:
├── Day 1-2: ConnectorRegistry + CredentialStore
├── Day 3-4: OAuth endpoints + Setup wizard UI
└── Day 5: Multi-provider primitive support

Week 2:
├── Day 1-2: Google connectors (Sheets, Slides, Photos)
├── Day 3: Microsoft connectors (Excel, PowerPoint, OneNote)
├── Day 4: Social connectors (Twitter)
└── Day 5: Smart Home connectors (SmartThings, Hue)

Week 3:
├── Day 1-2: AI-assisted setup
├── Day 3: Testing + polishing
└── Day 4-5: Documentation
```

---

## Quick Wins (Can Do Today)

1. **ConnectorRegistry skeleton** - Define the interface
2. **`/connectors` endpoint** - Show what's available and connected
3. **Setup wizard page** - Basic HTML to guide users
4. **google_sheets connector** - Low-hanging fruit, reuses google_auth

---

## Questions to Decide

1. **Hosted vs BYOK?** 
   - Do we register OAuth apps with Google/Microsoft?
   - Or require users to create their own?

2. **Token storage?**
   - Encrypt locally with user's master password?
   - Store in OS keychain?
   - Environment variables?

3. **Which connectors first?**
   - Google Sheets (most requested?)
   - Smart Home (differentiator?)
   - Finance (high value but complex)?

---

## Files to Create/Modify

```
apex/
├── connectors/
│   ├── registry.py          # NEW: ConnectorRegistry
│   ├── credentials.py       # NEW: CredentialStore
│   ├── google_sheets.py     # NEW
│   ├── google_slides.py     # NEW
│   ├── google_photos.py     # NEW
│   ├── onenote.py           # NEW
│   ├── twitter.py           # NEW
│   ├── smartthings.py       # NEW
│   └── hue.py               # NEW
├── server.py                 # ADD: /connect endpoints
├── apex_engine.py            # UPDATE: Use ConnectorRegistry
└── ui/
    └── setup.html            # NEW: Setup wizard
```

---

## Success Metrics

- [ ] User can connect Google services in < 30 seconds
- [ ] User can connect Microsoft services in < 30 seconds  
- [ ] All 36 primitives have at least one working connector
- [ ] Aggregate search works across multiple providers
- [ ] Token refresh happens automatically
- [ ] Setup wizard completion rate > 80%
