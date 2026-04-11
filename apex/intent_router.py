"""
Intent Router

Fast pre-classifier that sits between the HTTP endpoint and the ReAct agent.
Routes requests into three lanes:

  1. INDEX_DIRECT — Simple lookups answered from the local index in <50ms.
     "What's on my calendar today?" → SQLite query → instant response.
     No LLM call, no tools, no blueprint.

  2. FILTERED — Complex queries that need the LLM, but with a reduced tool set.
     "Send an email to John about the budget" → only EMAIL + CONTACTS tools.
     Cuts 371 tools down to ~20, saving tokens and improving accuracy.

  3. FULL — Ambiguous or multi-domain queries that need everything.
     "Prepare for my meeting with John" → all tools available.
     This is the current behavior, kept as fallback.

Design principles:
  - Trust the AI: use LLM for domain classification when available
  - INDEX_DIRECT stays regex-based for <1ms read-only lookups
  - Keyword matching kept as fallback when LLM is unavailable
  - Conservative: when in doubt, fall through to FILTERED or FULL
"""

import asyncio
import re
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM response cache — avoids repeat API calls for similar messages
# ---------------------------------------------------------------------------

_domain_cache: Dict[str, tuple] = {}  # msg_key → (domains, timestamp)
_CACHE_TTL = 300  # 5 minutes


def _cache_key(msg: str) -> str:
    """Normalize message for cache lookup (lowercase, strip, truncate)."""
    return msg.lower().strip()[:200]


# ---------------------------------------------------------------------------
# LLM client for AI-based domain classification
# ---------------------------------------------------------------------------

_llm_client = None


def set_llm_client(client) -> None:
    """Set the LLM client used for AI-based domain classification."""
    global _llm_client
    _llm_client = client


# ---------------------------------------------------------------------------
# Intent types
# ---------------------------------------------------------------------------

class IntentType:
    INDEX_DIRECT = "index_direct"   # Answer from index, no LLM
    FILTERED = "filtered"           # LLM with subset of tools
    FULL = "full"                   # LLM with all tools


class Intent:
    """Classification result."""
    __slots__ = ("type", "kind", "domains", "params", "confidence")

    def __init__(
        self,
        type: str = IntentType.FULL,
        kind: str = "",              # e.g., "calendar_list", "email_search"
        domains: Optional[List[str]] = None,  # For FILTERED: which primitive domains
        params: Optional[Dict[str, Any]] = None,
        confidence: float = 0.0,
    ):
        self.type = type
        self.kind = kind
        self.domains = domains or []
        self.params = params or {}
        self.confidence = confidence

    def __repr__(self):
        return f"Intent({self.type}, kind={self.kind}, domains={self.domains}, conf={self.confidence:.2f})"


# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------

# Calendar time expressions
_TODAY_PATTERNS = re.compile(
    r"\btoday\b|"
    r"\btoday'?s\b|"
    r"\bthis morning\b|"
    r"\bthis afternoon\b|"
    r"\bthis evening\b|"
    r"\brest of (?:the )?day\b",
    re.IGNORECASE,
)
_TOMORROW_PATTERNS = re.compile(r"\btomorrow\b", re.IGNORECASE)
_THIS_WEEK_PATTERNS = re.compile(
    r"\bthis week\b|"
    r"\brest of (?:the )?week\b|"
    r"\bnext few days\b|"
    r"\bupcoming\b",
    re.IGNORECASE,
)
_DATE_PATTERN = re.compile(
    r"\b\d{4}-\d{1,2}-\d{1,2}\b|"           # 2026-04-10
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{1,2}\b|"  # April 10
    r"\b\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\b",  # 10 April
    re.IGNORECASE,
)

# Domain keyword maps — maps trigger words to primitive domains
_DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "CALENDAR": [
        "calendar", "event", "meeting", "appointment",
        "agenda", "free time", "busy", "slot", "block",
    ],
    "EMAIL": [
        "email", "mail", "inbox", "send", "reply", "forward",
        "draft", "unread", "message from", "message to",
    ],
    "CONTACTS": [
        "contact", "phone number", "email address", "who is",
    ],
    "TASK": [
        "task", "todo", "to-do", "to do", "reminder",
        "due", "checklist", "action item",
    ],
    "FILE": [
        "file", "document", "folder", "drive", "download",
        "upload", "attachment", "spreadsheet", "presentation",
    ],
    "WEB": [
        "search", "google", "look up", "find out", "what is",
        "who is", "weather", "news", "stock",
    ],
    "WEATHER": ["weather", "temperature", "forecast", "rain"],
    "NEWS": ["news", "headline", "article"],
    "KNOWLEDGE": [
        "remember", "recall", "forget", "what do you know",
        "what did i tell you",
    ],
    "MESSAGE": [
        "slack", "discord", "teams", "telegram", "chat",
    ],
    "NOTIFY": ["notify", "alert", "notification", "remind me"],
}

# Direct index query patterns — these can be answered without the LLM
_INDEX_PATTERNS: List[Tuple[re.Pattern, str, Dict[str, Any]]] = []

def _build_index_patterns():
    """Build regex patterns for direct index queries."""
    global _INDEX_PATTERNS

    # Calendar list queries
    cal_list = re.compile(
        r"(?:what(?:'s| is| are)?|show|list|get|any|do i have)"
        r".*?"
        r"(?:on (?:my )?calendar|(?:my )?(?:schedule|agenda|events?|meetings?|appointments?))",
        re.IGNORECASE,
    )
    _INDEX_PATTERNS.append((cal_list, "calendar_list", {"kind": "event"}))

    # Reverse: "my calendar today", "my schedule this week"
    cal_list2 = re.compile(
        r"(?:my )?(?:calendar|schedule|agenda|events?|meetings?)\s+"
        r"(?:today|tomorrow|this week|next week|for)",
        re.IGNORECASE,
    )
    _INDEX_PATTERNS.append((cal_list2, "calendar_list", {"kind": "event"}))

    # Unread emails  
    unread = re.compile(
        r"(?:any |how many |new |unread |check )*(?:emails?|mail|inbox)\b",
        re.IGNORECASE,
    )
    _INDEX_PATTERNS.append((unread, "email_list", {"kind": "email", "status": "unread"}))

    # Task list
    tasks = re.compile(
        r"(?:what(?:'s| is| are)?|show|list|get|any|my)"
        r".*?"
        r"(?:tasks?|to-?dos?|action items?|checklist)",
        re.IGNORECASE,
    )
    _INDEX_PATTERNS.append((tasks, "task_list", {"kind": "task", "status": "pending"}))

    # Contact lookup
    contact = re.compile(
        r"(?:what(?:'s| is)|find|look up|get)"
        r".*?"
        r"(?:phone|email|contact|number|address)"
        r".*?"
        r"(?:for |of )?(\w+)",
        re.IGNORECASE,
    )
    _INDEX_PATTERNS.append((contact, "contact_search", {"kind": "contact"}))

_build_index_patterns()


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

# Compile action-verb patterns at module level (not per-call)
_ACTION_VERBS = re.compile(
    r"\b(?:send|create|make|write|draft|compose|set up|book|"
    r"delete|remove|cancel|update|edit|change|move|rename|forward|reply|"
    r"summarize|analyze|prepare|remind|share|post|publish|invite)\b",
    re.IGNORECASE,
)
_SCHEDULE_VERB = re.compile(r"\bschedule\s+(?:a|an|the|my|our|this)\b", re.IGNORECASE)


def _classify_core(msg_lower: str, today: datetime, detected_domains: List[str]) -> Intent:
    """Shared classification logic used by both async and sync paths."""
    # Skip classification for very short or very long messages
    if len(msg_lower) < 3:
        return Intent(IntentType.FULL, confidence=0.0)
    if len(msg_lower) > 500:
        return Intent(IntentType.FULL, confidence=0.1)

    has_action = bool(_ACTION_VERBS.search(msg_lower)) or bool(_SCHEDULE_VERB.search(msg_lower))
    action_count = len(_ACTION_VERBS.findall(msg_lower))

    # Multi-action requests are often cross-domain workflows; keep routing broad
    # so the LLM can compose the right tool sequence instead of being over-filtered.
    if has_action and action_count >= 2 and len(detected_domains) <= 3:
        return Intent(IntentType.FULL, domains=detected_domains, confidence=0.6)

    # --- Phase 1: Check for direct index queries (read-only lookups only) ---
    # Only shortcut to index when the message targets a SINGLE domain.
    # Multi-domain requests like "check calendar, email, and tasks" need the LLM.
    if not has_action and len(detected_domains) <= 1:
        for pattern, kind, base_params in _INDEX_PATTERNS:
            if pattern.search(msg_lower):
                params = dict(base_params)
                if kind == "calendar_list":
                    after, before = _resolve_time_range(msg_lower, today)
                    if after:
                        params["after"] = after
                    if before:
                        params["before"] = before
                return Intent(
                    type=IntentType.INDEX_DIRECT,
                    kind=kind,
                    params=params,
                    confidence=0.8,
                )

    # --- Phase 2: Route based on detected domains ---
    if detected_domains:
        if len(detected_domains) <= 3:
            return Intent(
                type=IntentType.FILTERED,
                domains=detected_domains,
                confidence=0.85 if _llm_client else 0.7,
            )
        return Intent(IntentType.FULL, domains=detected_domains, confidence=0.4)

    # --- Phase 3: Fallback to FULL ---
    return Intent(IntentType.FULL, confidence=0.2)


async def classify(message: str, today: Optional[datetime] = None) -> Intent:
    """Classify a user message into an intent.

    Uses LLM for domain detection when available, falls back to keyword
    matching otherwise.
    """
    if today is None:
        today = datetime.now()
    msg_lower = message.lower().strip()

    # Try keywords first (instant), only call LLM if keywords find nothing
    detected_domains = _detect_domains_keyword(msg_lower)
    if not detected_domains and _llm_client and len(msg_lower) >= 3:
        detected_domains = await _detect_domains_llm(msg_lower) or []

    return _classify_core(msg_lower, today, detected_domains)


def classify_sync(message: str, today: Optional[datetime] = None) -> Intent:
    """Synchronous classification using keyword matching only.

    Used by benchmarks and tests where LLM calls are not desired.
    """
    if today is None:
        today = datetime.now()
    msg_lower = message.lower().strip()
    detected_domains = _detect_domains_keyword(msg_lower)
    return _classify_core(msg_lower, today, detected_domains)


def _detect_domains_keyword(msg: str) -> List[str]:
    """Detect domains using keyword matching (fast fallback)."""
    scores: Dict[str, int] = {}
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        for kw in keywords:
            if kw in msg:
                scores[domain] = scores.get(domain, 0) + 1

    # Sort by score descending, return domains with score > 0
    return [d for d, _ in sorted(scores.items(), key=lambda x: -x[1]) if scores[d] > 0]


def _get_valid_domains() -> frozenset:
    """All domains supported by the tool filter + keyword map."""
    return frozenset(_DOMAIN_TO_TOOL_PREFIX.keys()) | frozenset(_DOMAIN_KEYWORDS.keys())


async def _detect_domains_llm(msg: str) -> Optional[List[str]]:
    """Classify message into domains using a fast LLM call.

    Results are cached for 5 minutes to avoid duplicate API calls.
    """
    if not _llm_client:
        return None

    # Check cache first
    import time as _time
    key = _cache_key(msg)
    cached = _domain_cache.get(key)
    if cached:
        domains, ts = cached
        if _time.monotonic() - ts < _CACHE_TTL:
            logger.info(f"Domain cache hit for '{msg[:40]}' → {domains}")
            return domains
        del _domain_cache[key]

    valid = _get_valid_domains()
    domain_list = ", ".join(sorted(valid))
    prompt = (
        f"Which 1-3 domains are relevant? Return ONLY comma-separated names.\n\n"
        f"{domain_list}\n\n"
        f"Message: {msg}"
    )

    try:
        if hasattr(_llm_client, "messages"):
            response = await asyncio.to_thread(
                _llm_client.messages.create,
                model="claude-3-5-haiku-20241022",
                max_tokens=50,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
        else:
            response = await asyncio.to_thread(
                _llm_client.chat.completions.create,
                model="gpt-4o-mini",
                max_tokens=50,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.choices[0].message.content.strip()

        domains = [d.strip().upper() for d in text.split(",")]
        result = [d for d in domains if d in valid]
        if result:
            _domain_cache[key] = (result, _time.monotonic())
            # Evict old entries if cache gets large
            if len(_domain_cache) > 200:
                cutoff = _time.monotonic() - _CACHE_TTL
                for k in [k for k, (_, t) in _domain_cache.items() if t < cutoff]:
                    del _domain_cache[k]
            logger.info(f"LLM domains for '{msg[:60]}' → {result}")
            return result
        return None
    except Exception as e:
        logger.warning(f"LLM domain classification failed, using keywords: {e}")
        return None


def _resolve_time_range(
    msg: str, today: datetime
) -> Tuple[Optional[datetime], Optional[datetime]]:
    """Resolve time expressions to (after, before) datetime bounds."""
    start_of_today = today.replace(hour=0, minute=0, second=0, microsecond=0)

    if _TODAY_PATTERNS.search(msg):
        return start_of_today, start_of_today + timedelta(days=1)
    if _TOMORROW_PATTERNS.search(msg):
        return start_of_today + timedelta(days=1), start_of_today + timedelta(days=2)
    if _THIS_WEEK_PATTERNS.search(msg):
        # Rest of week: today through Sunday
        days_to_sunday = 6 - today.weekday()
        return start_of_today, start_of_today + timedelta(days=days_to_sunday + 1)

    # Try to parse explicit dates
    date_match = _DATE_PATTERN.search(msg)
    if date_match:
        try:
            from dateutil import parser as dateparser
            parsed = dateparser.parse(date_match.group(), default=today)
            if parsed:
                day_start = parsed.replace(hour=0, minute=0, second=0, microsecond=0)
                return day_start, day_start + timedelta(days=1)
        except Exception:
            pass

    # Default: today if it's a calendar query with no time reference
    return start_of_today, start_of_today + timedelta(days=1)


# ---------------------------------------------------------------------------
# Index direct handler
# ---------------------------------------------------------------------------

def handle_index_direct(intent: Intent, index) -> Optional[Dict[str, Any]]:
    """Handle an INDEX_DIRECT intent by querying the local index.

    Returns a dict with 'response' (text) and 'data' (structured),
    or None if the index can't answer (triggering LLM fallback).
    """
    if not index:
        return None

    kind = intent.params.get("kind")
    params = intent.params

    try:
        if intent.kind == "calendar_list":
            results = index.query(
                kind="event",
                after=params.get("after"),
                before=params.get("before"),
                limit=params.get("limit", 50),
            )
            if not results:
                # Check if the index has ANY events (might just be no events today)
                total = index.count(kind="event")
                if total == 0:
                    return None  # Index empty, fall through to LLM
                return {
                    "response": "No events found for that time period.",
                    "data": [],
                }
            events = [
                {k: v for k, v in {
                    "id": r.source_id, "summary": r.title,
                    "start": r.timestamp.isoformat() if r.timestamp else "",
                    "end": r.timestamp_end.isoformat() if r.timestamp_end else "",
                    "description": r.body, "location": r.location,
                    "status": r.status, "html_link": r.url,
                    "calendar": (r.labels[0] if r.labels else ""),
                }.items() if v}
                for r in results
            ]
            return {"response": _format_events(events), "data": events}

        elif intent.kind == "email_list":
            status = params.get("status")
            results = index.query(kind="email", status=status, limit=20)
            if not results:
                total = index.count(kind="email")
                if total == 0:
                    return None  # Index empty
                return {"response": "No unread emails.", "data": []}
            emails = [
                {k: v for k, v in {
                    "id": r.source_id, "subject": r.title,
                    "sender": r.participants[0] if r.participants else "",
                    "date": r.timestamp.isoformat() if r.timestamp else "",
                    "snippet": r.body[:200],
                    "status": r.status,
                }.items() if v}
                for r in results
            ]
            return {
                "response": f"You have {len(emails)} unread email{'s' if len(emails) != 1 else ''}.",
                "data": emails,
            }

        elif intent.kind == "task_list":
            status = params.get("status", "pending")
            results = index.query(kind="task", status=status, limit=50)
            if not results:
                total = index.count(kind="task")
                if total == 0:
                    return None
                return {"response": "No open tasks.", "data": []}
            tasks = [
                {k: v for k, v in {
                    "id": r.source_id, "title": r.title,
                    "due": r.timestamp.isoformat() if r.timestamp else None,
                    "status": r.status,
                    "description": r.body[:200] if r.body else "",
                }.items() if v}
                for r in results
            ]
            return {
                "response": f"You have {len(tasks)} open task{'s' if len(tasks) != 1 else ''}.",
                "data": tasks,
            }

        elif intent.kind == "contact_search":
            # Extract search query from the message params
            query = params.get("query", "")
            if query:
                results = index.search(query, kind="contact", limit=5)
            else:
                results = index.query(kind="contact", limit=20)
            if not results:
                return None
            contacts = [
                {k: v for k, v in {
                    "name": r.title,
                    "email": r.participants[0] if r.participants else "",
                    "details": r.body,
                }.items() if v}
                for r in results
            ]
            return {"response": _format_contacts(contacts), "data": contacts}

    except Exception as e:
        logger.error(f"Index direct query failed: {e}")
        return None

    return None


# ---------------------------------------------------------------------------
# Tool filtering
# ---------------------------------------------------------------------------

# Map domain names to tool name prefixes (lowercase of primitive keys)
_DOMAIN_TO_TOOL_PREFIX: Dict[str, List[str]] = {
    "CALENDAR": ["calendar_", "meeting_"],
    "EMAIL": ["email_"],
    "CONTACTS": ["contacts_"],
    "TASK": ["task_"],
    "FILE": ["file_", "document_", "cloud_storage_"],
    "WEB": ["web_", "browser_", "search_"],
    "WEATHER": ["weather_"],
    "NEWS": ["news_"],
    "KNOWLEDGE": ["knowledge_", "intelligence_", "patterns_"],
    "MESSAGE": ["message_", "chat_", "sms_", "telegram_"],
    "NOTIFY": ["notify_"],
    "SPREADSHEET": ["spreadsheet_", "data_"],
    "NOTES": ["notes_", "notion_"],
    "SOCIAL": ["social_", "reddit_", "linkedin_"],
    "MEDIA": ["media_", "photo_", "spotify_"],
}

# Tools that should always be available
_ALWAYS_INCLUDE = ["knowledge_remember", "knowledge_recall"]


def filter_tools(
    all_tools: List[Any],
    domains: List[str],
) -> List[Any]:
    """Filter tools to only those relevant to the detected domains.

    Args:
        all_tools: Full list of Tool objects
        domains: List of domain names (e.g., ["CALENDAR", "CONTACTS"])

    Returns:
        Filtered list of Tool objects
    """
    if not domains:
        return all_tools

    # Build set of allowed prefixes
    prefixes = set()
    for domain in domains:
        for prefix in _DOMAIN_TO_TOOL_PREFIX.get(domain, []):
            prefixes.add(prefix)

    # Always include knowledge tools
    for name in _ALWAYS_INCLUDE:
        prefixes.add(name)

    filtered = []
    for tool in all_tools:
        name = tool.name if hasattr(tool, 'name') else tool.get("name", "")
        if any(name.startswith(p) or name == p for p in prefixes):
            filtered.append(tool)

    # If filtering removed everything, return all (safety net)
    if not filtered:
        return all_tools

    return filtered


# ---------------------------------------------------------------------------
# Response formatters
# ---------------------------------------------------------------------------

def _format_events(events: List[Dict]) -> str:
    """Format calendar events into a readable response."""
    if not events:
        return "No events found."

    lines = []
    for e in events:
        time_str = ""
        if e.get("start"):
            try:
                dt = datetime.fromisoformat(e["start"])
                time_str = dt.strftime("%-I:%M %p") if dt.hour or dt.minute else "All day"
            except (ValueError, TypeError):
                time_str = e["start"]

        parts = [f"**{e.get('summary', 'Untitled')}**"]
        if time_str:
            parts.append(time_str)
        if e.get("location"):
            parts.append(f"@ {e['location']}")
        lines.append(" — ".join(parts))

    header = f"You have {len(events)} event{'s' if len(events) != 1 else ''}:"
    return header + "\n" + "\n".join(f"- {l}" for l in lines)


def _format_contacts(contacts: List[Dict]) -> str:
    """Format contacts into a readable response."""
    if not contacts:
        return "No contacts found."
    lines = []
    for c in contacts:
        parts = [c.get("name", "Unknown")]
        if c.get("email"):
            parts.append(c["email"])
        if c.get("details"):
            parts.append(c["details"])
        lines.append(" — ".join(parts))
    return "\n".join(f"- {l}" for l in lines)
