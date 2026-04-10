"""
Nudge Engine — AI-powered proactive suggestions.

Unlike the rule-based ProactiveMonitor, this asks the LLM to look
at your actual data across services and generate smart nudges like:

  "You have a meeting with Sarah in 30 min — she shared a doc yesterday you haven't opened"
  "3 unread Slack messages mention tomorrow's deadline"
  "Your Todoist task 'Finish proposal' is due today but the Google Doc hasn't changed since Tuesday"

Runs every 5 minutes in the background. Lightweight — one short LLM call per cycle.
"""

import asyncio
import json
import logging
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "sqlite" / "nudges.db"


@dataclass
class Nudge:
    id: str
    title: str
    message: str
    category: str          # meeting_prep, follow_up, deadline, insight, digest
    priority: str          # low, medium, high, urgent
    source_services: List[str]
    suggested_action: Optional[str] = None   # A prompt the user can click to execute
    created_at: str = ""
    expires_at: Optional[str] = None
    dismissed: bool = False
    acted_on: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "message": self.message,
            "category": self.category,
            "priority": self.priority,
            "source_services": self.source_services,
            "suggested_action": self.suggested_action,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "dismissed": self.dismissed,
            "acted_on": self.acted_on,
        }


class NudgeStore:
    """SQLite persistence for nudges."""

    def __init__(self, db_path: Path = DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path))
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self):
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS nudges (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                category TEXT NOT NULL,
                priority TEXT NOT NULL DEFAULT 'medium',
                source_services TEXT NOT NULL DEFAULT '[]',
                suggested_action TEXT,
                created_at TEXT NOT NULL,
                expires_at TEXT,
                dismissed INTEGER NOT NULL DEFAULT 0,
                acted_on INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_nudges_active
                ON nudges(dismissed, created_at DESC);
        """)
        self._db.commit()

    def save(self, nudge: Nudge):
        self._db.execute("""
            INSERT OR REPLACE INTO nudges
            (id, title, message, category, priority, source_services,
             suggested_action, created_at, expires_at, dismissed, acted_on)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            nudge.id, nudge.title, nudge.message, nudge.category, nudge.priority,
            json.dumps(nudge.source_services), nudge.suggested_action,
            nudge.created_at, nudge.expires_at,
            int(nudge.dismissed), int(nudge.acted_on),
        ))
        self._db.commit()

    def get_active(self, limit: int = 20) -> List[Nudge]:
        """Get active (non-dismissed, non-expired) nudges."""
        now = datetime.now().isoformat()
        rows = self._db.execute("""
            SELECT * FROM nudges
            WHERE dismissed = 0
              AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY
                CASE priority
                    WHEN 'urgent' THEN 0
                    WHEN 'high' THEN 1
                    WHEN 'medium' THEN 2
                    WHEN 'low' THEN 3
                END,
                created_at DESC
            LIMIT ?
        """, (now, limit)).fetchall()
        return [self._row_to_nudge(r) for r in rows]

    def dismiss(self, nudge_id: str) -> bool:
        cur = self._db.execute(
            "UPDATE nudges SET dismissed = 1 WHERE id = ?", (nudge_id,)
        )
        self._db.commit()
        return cur.rowcount > 0

    def mark_acted(self, nudge_id: str) -> bool:
        cur = self._db.execute(
            "UPDATE nudges SET acted_on = 1, dismissed = 1 WHERE id = ?", (nudge_id,)
        )
        self._db.commit()
        return cur.rowcount > 0

    def recent_titles(self, hours: int = 24) -> List[str]:
        """Get recent nudge titles to avoid duplicates."""
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        rows = self._db.execute(
            "SELECT title FROM nudges WHERE created_at > ?", (cutoff,)
        ).fetchall()
        return [r["title"] for r in rows]

    def cleanup_old(self, days: int = 7):
        """Remove nudges older than N days."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        self._db.execute("DELETE FROM nudges WHERE created_at < ?", (cutoff,))
        self._db.commit()

    def _row_to_nudge(self, row) -> Nudge:
        return Nudge(
            id=row["id"],
            title=row["title"],
            message=row["message"],
            category=row["category"],
            priority=row["priority"],
            source_services=json.loads(row["source_services"]),
            suggested_action=row["suggested_action"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            dismissed=bool(row["dismissed"]),
            acted_on=bool(row["acted_on"]),
        )


class NudgeEngine:
    """
    Background engine that generates AI-powered nudges.

    Every cycle (default: 5 min), it:
    1. Gathers a lightweight snapshot from connected services
    2. Asks the LLM to analyze it and generate nudges
    3. Deduplicates against recent nudges
    4. Stores new nudges in SQLite
    """

    def __init__(self, store: NudgeStore, check_interval: int = 300):
        self._store = store
        self._check_interval = check_interval  # seconds
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_run: Optional[float] = None
        self._cycles = 0
        self._errors = 0

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"NudgeEngine started (interval: {self._check_interval}s)")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("NudgeEngine stopped")

    async def run_once(self) -> List[Nudge]:
        """Run a single nudge generation cycle. Returns new nudges."""
        return await self._generate_nudges()

    async def _loop(self):
        # Wait a bit on startup for services to connect
        await asyncio.sleep(30)
        while self._running:
            try:
                new_nudges = await self._generate_nudges()
                if new_nudges:
                    logger.info(f"Generated {len(new_nudges)} new nudge(s)")
                self._cycles += 1
                self._last_run = time.time()
            except Exception as e:
                self._errors += 1
                logger.error(f"Nudge cycle error: {e}")
            await asyncio.sleep(self._check_interval)

    async def _gather_snapshot(self) -> Dict[str, Any]:
        """Gather lightweight data snapshot from connected services."""
        snapshot = {}
        now = datetime.now()

        # Import here to avoid circular imports
        import server_state as ss

        # Calendar — next 24h events
        try:
            cal = ss._google_calendar
            if cal and cal.connected:
                events = await cal.get_events(
                    time_min=now.isoformat() + "Z",
                    time_max=(now + timedelta(hours=24)).isoformat() + "Z",
                    max_results=10,
                )
                if events:
                    snapshot["calendar"] = [
                        {
                            "title": e.get("summary", ""),
                            "start": e.get("start", {}).get("dateTime", e.get("start", {}).get("date", "")),
                            "attendees": [a.get("email", "") for a in e.get("attendees", [])[:5]],
                        }
                        for e in events
                    ]
        except Exception as e:
            logger.debug(f"Calendar snapshot failed: {e}")

        # Email — recent unread
        try:
            gmail = ss._gmail_connector
            if gmail:
                messages = await gmail.list_messages(query="is:unread", max_results=10)
                if messages:
                    snapshot["unread_emails"] = [
                        {
                            "from": m.get("from", ""),
                            "subject": m.get("subject", ""),
                            "snippet": m.get("snippet", "")[:100],
                            "date": m.get("date", ""),
                        }
                        for m in messages
                    ]
        except Exception as e:
            logger.debug(f"Email snapshot failed: {e}")

        # Tasks — overdue + due today
        try:
            engine = ss.get_telic_engine()
            if engine:
                for prim in engine._primitives:
                    if prim.name == "TODOIST_LIST_TASKS" or "list_tasks" in prim.name.lower():
                        try:
                            result = await prim.execute()
                            if isinstance(result, dict) and "tasks" in result:
                                tasks = result["tasks"]
                            elif isinstance(result, list):
                                tasks = result
                            else:
                                continue
                            today_str = now.strftime("%Y-%m-%d")
                            relevant = [
                                {"title": t.get("content", t.get("title", "")),
                                 "due": t.get("due", {}).get("date", "") if isinstance(t.get("due"), dict) else str(t.get("due", "")),
                                 "priority": t.get("priority", 1)}
                                for t in tasks[:20]
                                if not t.get("is_completed")
                            ]
                            if relevant:
                                snapshot["tasks"] = relevant[:10]
                        except Exception:
                            pass
                        break
        except Exception as e:
            logger.debug(f"Tasks snapshot failed: {e}")

        # GitHub — recent notifications
        try:
            if os.environ.get("GITHUB_TOKEN"):
                from connectors.github import GitHubConnector
                gh = GitHubConnector()
                if await gh.connect():
                    notifs = await gh.get_notifications(max_results=5)
                    if notifs:
                        snapshot["github"] = [
                            {"title": n.get("subject", {}).get("title", ""),
                             "type": n.get("subject", {}).get("type", ""),
                             "repo": n.get("repository", {}).get("full_name", ""),
                             "reason": n.get("reason", "")}
                            for n in notifs
                        ]
        except Exception as e:
            logger.debug(f"GitHub snapshot failed: {e}")

        # Slack — recent mentions
        try:
            if os.environ.get("SLACK_BOT_TOKEN"):
                from connectors.slack import SlackConnector
                sl = SlackConnector()
                if await sl.connect():
                    mentions = await sl.get_mentions(limit=5)
                    if mentions:
                        snapshot["slack_mentions"] = [
                            {"channel": m.get("channel", ""),
                             "text": m.get("text", "")[:100],
                             "user": m.get("user", "")}
                            for m in mentions
                        ]
        except Exception as e:
            logger.debug(f"Slack snapshot failed: {e}")

        return snapshot

    async def _generate_nudges(self) -> List[Nudge]:
        """Core: gather data, ask LLM, parse nudges."""
        snapshot = await self._gather_snapshot()
        if not snapshot:
            return []

        # Get recent nudge titles to avoid duplicates
        recent = self._store.recent_titles(hours=12)

        # Build the LLM prompt
        now = datetime.now()
        prompt = self._build_prompt(snapshot, recent, now)

        # Call the LLM
        try:
            from llm_factory import create_anthropic_client
            client, mode = create_anthropic_client()
            if not client:
                return []

            model = os.environ.get("TELIC_MODEL", "claude-sonnet-4-20250514")
            # Use haiku for nudges — fast and cheap
            nudge_model = os.environ.get("TELIC_NUDGE_MODEL", "claude-haiku-4-20250414")

            response = client.messages.create(
                model=nudge_model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )

            text = response.content[0].text if response.content else ""
            nudges = self._parse_nudges(text, now)

            # Save new nudges
            for nudge in nudges:
                self._store.save(nudge)

            # Periodic cleanup
            if self._cycles % 50 == 0:
                self._store.cleanup_old()

            return nudges

        except Exception as e:
            logger.error(f"LLM nudge generation failed: {e}")
            return []

    def _build_prompt(self, snapshot: Dict, recent_titles: List[str], now: datetime) -> str:
        today = now.strftime("%A, %B %d, %Y")
        time_str = now.strftime("%I:%M %p")

        data_sections = []
        for key, items in snapshot.items():
            data_sections.append(f"## {key}\n```json\n{json.dumps(items, indent=2, default=str)}\n```")

        data_block = "\n\n".join(data_sections) if data_sections else "No data available."

        recent_block = ""
        if recent_titles:
            recent_block = f"\n\nALREADY SENT (do not repeat):\n" + "\n".join(f"- {t}" for t in recent_titles)

        return f"""TODAY: {today}, {time_str}

You are Ziggy, a proactive AI assistant. Analyze the user's data below and generate 0-3 helpful nudges.

A nudge is a short, actionable insight the user would want to know RIGHT NOW. Focus on:
- Upcoming meetings that need preparation
- Overdue or soon-due tasks
- Unread emails that seem urgent or important
- Cross-service connections (e.g., a meeting attendee also sent an unread email)
- Things that are unusual or need attention

Rules:
- Only generate nudges that are genuinely useful RIGHT NOW
- If nothing interesting, return an empty array — don't force it
- Each nudge should have a suggested_action (a natural language command the user can click)
- Keep messages concise (1-2 sentences max)
- Prioritize: urgent > high > medium > low
{recent_block}

DATA:
{data_block}

Respond with a JSON array ONLY (no other text):
[
  {{
    "title": "Short title",
    "message": "1-2 sentence explanation",
    "category": "meeting_prep|follow_up|deadline|insight|digest",
    "priority": "low|medium|high|urgent",
    "source_services": ["calendar", "email"],
    "suggested_action": "Natural language command the user can click to act on this"
  }}
]

If no nudges are warranted, respond with: []"""

    def _parse_nudges(self, text: str, now: datetime) -> List[Nudge]:
        """Parse LLM response into Nudge objects."""
        # Extract JSON from response (handle markdown code blocks)
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        try:
            items = json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON array in the text
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                try:
                    items = json.loads(text[start:end])
                except json.JSONDecodeError:
                    logger.warning(f"Could not parse nudge response: {text[:200]}")
                    return []
            else:
                return []

        if not isinstance(items, list):
            return []

        nudges = []
        for item in items[:5]:  # Cap at 5 per cycle
            if not isinstance(item, dict) or "title" not in item:
                continue
            nudge = Nudge(
                id=f"nudge_{uuid.uuid4().hex[:12]}",
                title=item.get("title", ""),
                message=item.get("message", ""),
                category=item.get("category", "insight"),
                priority=item.get("priority", "medium"),
                source_services=item.get("source_services", []),
                suggested_action=item.get("suggested_action"),
                created_at=now.isoformat(),
                expires_at=(now + timedelta(hours=12)).isoformat(),
            )
            nudges.append(nudge)

        return nudges

    def get_stats(self) -> dict:
        return {
            "running": self._running,
            "cycles": self._cycles,
            "errors": self._errors,
            "last_run": self._last_run,
            "check_interval": self._check_interval,
        }


# === Singletons ===

_store: Optional[NudgeStore] = None
_engine: Optional[NudgeEngine] = None


def get_nudge_store() -> NudgeStore:
    global _store
    if _store is None:
        _store = NudgeStore()
    return _store


def get_nudge_engine() -> NudgeEngine:
    global _engine
    if _engine is None:
        _engine = NudgeEngine(get_nudge_store())
    return _engine
