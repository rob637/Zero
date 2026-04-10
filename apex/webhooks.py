"""
Webhook Receiver Framework

Handles real-time push notifications from external services, keeping
the local index fresh without polling.

Supported providers:
  - Google Calendar/Gmail: Push notifications via Pub/Sub or watch channels
  - Slack: Events API (message.created, channel.joined, etc.)
  - GitHub: Webhooks (push, PR, issue events)

Architecture:
  WebhookManager   — Registers/renews webhook subscriptions
  Webhook handlers — Per-provider endpoint handlers (verify + process)
  Event processor  — Converts webhook payloads to sync triggers

Security:
  - Google: Channel tokens verified against registered channels
  - Slack: Signing secret verification (HMAC-SHA256)
  - GitHub: Webhook secret verification (HMAC-SHA256)

Local development:
  Webhooks require a public URL. For local dev, use:
    - ngrok/cloudflared tunnel (set WEBHOOK_BASE_URL env var)
    - OR rely on polling (webhooks are an optimization, not required)

Usage:
    from apex.webhooks import WebhookManager, get_webhook_manager

    manager = get_webhook_manager(sync_engine)
    await manager.setup_google_watch()   # Register push notifications
    manager.register_routes(app)         # Add webhook endpoints to FastAPI
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _get_webhook_base_url() -> Optional[str]:
    """Get the public base URL for webhook callbacks.

    Set WEBHOOK_BASE_URL env var when using a tunnel:
      WEBHOOK_BASE_URL=https://abc123.ngrok.io

    Returns None if no public URL is configured (webhooks disabled,
    fallback to polling).
    """
    url = os.environ.get("WEBHOOK_BASE_URL", "").rstrip("/")
    if url and url.startswith("https://"):
        return url
    return None


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class WebhookChannel:
    """A registered webhook subscription."""
    id: str                      # Our unique channel ID
    provider: str                # google, slack, github
    resource: str                # What we're watching (e.g., "calendar", "gmail")
    expiration: Optional[datetime] = None  # When the subscription expires
    token: str = ""              # Verification token
    resource_id: str = ""        # Provider's resource ID (for renewal)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_expired(self) -> bool:
        if not self.expiration:
            return False
        return datetime.now(timezone.utc) >= self.expiration

    @property
    def needs_renewal(self) -> bool:
        """True if channel expires within 1 hour."""
        if not self.expiration:
            return False
        return datetime.now(timezone.utc) >= self.expiration - timedelta(hours=1)


@dataclass
class WebhookEvent:
    """A processed webhook event ready for the sync engine."""
    provider: str
    resource: str                # Which source to sync (maps to sync adapter name)
    event_type: str              # e.g., "sync", "deleted", "created"
    resource_id: Optional[str] = None   # Specific resource that changed
    data: Dict[str, Any] = field(default_factory=dict)
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Event processor — converts webhook events to sync triggers
# ---------------------------------------------------------------------------

class EventProcessor:
    """Processes webhook events and triggers appropriate syncs."""

    def __init__(self, sync_engine):
        self._sync_engine = sync_engine
        self._debounce: Dict[str, float] = {}  # source → last trigger time
        self._debounce_interval = 5.0  # Don't re-sync same source within 5s

    async def process(self, event: WebhookEvent) -> None:
        """Process a webhook event and trigger sync if needed."""
        source = event.resource
        now = time.monotonic()

        # Debounce: don't re-sync the same source too frequently
        last_trigger = self._debounce.get(source, 0)
        if now - last_trigger < self._debounce_interval:
            logger.debug(f"Webhook debounced for {source} (last {now - last_trigger:.1f}s ago)")
            return

        self._debounce[source] = now
        logger.info(f"Webhook trigger: {event.provider}/{source} ({event.event_type})")

        # Trigger sync for this source
        try:
            result = await self._sync_engine.sync_now(source=source)
            logger.info(f"Webhook-triggered sync result for {source}: {result}")
        except Exception as e:
            logger.error(f"Webhook-triggered sync failed for {source}: {e}")


# ---------------------------------------------------------------------------
# Provider-specific handlers
# ---------------------------------------------------------------------------

class GoogleHandler:
    """Handles Google Calendar and Gmail push notifications.

    Google uses a watch/push model:
    1. We call calendar.events.watch() or gmail.users.watch()
    2. Google sends POST to our webhook URL when data changes
    3. We trigger a sync for the affected source

    Calendar watch channels expire after ~7 days.
    Gmail watch uses Pub/Sub and expires after ~7 days.
    """

    CALENDAR_WATCH_ENDPOINT = "/webhooks/google/calendar"
    GMAIL_WATCH_ENDPOINT = "/webhooks/google/gmail"

    def __init__(self, processor: EventProcessor):
        self._processor = processor
        self._channels: Dict[str, WebhookChannel] = {}  # channel_id → channel

    async def setup_calendar_watch(
        self,
        calendar_connector,
        webhook_url: str,
    ) -> Optional[WebhookChannel]:
        """Register a watch channel for Google Calendar changes.

        Uses the Calendar API's events.watch() method.
        """
        try:
            channel_id = f"ziggy-cal-{uuid.uuid4().hex[:12]}"
            token = uuid.uuid4().hex

            service = calendar_connector._service
            if not service:
                logger.warning("Calendar connector not connected, skipping watch setup")
                return None

            body = {
                "id": channel_id,
                "type": "web_hook",
                "address": webhook_url,
                "token": token,
                "expiration": int((datetime.now(timezone.utc) + timedelta(days=7)).timestamp() * 1000),
            }

            # Watch primary calendar
            result = service.events().watch(
                calendarId="primary", body=body
            ).execute()

            channel = WebhookChannel(
                id=channel_id,
                provider="google",
                resource="google_calendar",
                token=token,
                resource_id=result.get("resourceId", ""),
                expiration=datetime.fromtimestamp(
                    int(result.get("expiration", 0)) / 1000,
                    tz=timezone.utc,
                ),
            )
            self._channels[channel_id] = channel
            logger.info(
                f"Google Calendar watch registered: {channel_id}, "
                f"expires {channel.expiration}"
            )
            return channel

        except Exception as e:
            logger.error(f"Failed to setup Calendar watch: {e}")
            return None

    async def setup_gmail_watch(
        self,
        gmail_connector,
        topic_name: Optional[str] = None,
    ) -> Optional[WebhookChannel]:
        """Register a watch for Gmail changes.

        Uses gmail.users.watch() with a Cloud Pub/Sub topic.
        NOTE: Requires a GCP project with Pub/Sub configured.
        For local dev, this is optional — polling handles it.
        """
        try:
            service = gmail_connector._service
            if not service:
                logger.warning("Gmail connector not connected, skipping watch setup")
                return None

            # Need a Pub/Sub topic configured
            topic = topic_name or os.environ.get("GMAIL_PUBSUB_TOPIC")
            if not topic:
                logger.info("No GMAIL_PUBSUB_TOPIC configured, skipping Gmail watch")
                return None

            result = service.users().watch(
                userId="me",
                body={
                    "topicName": topic,
                    "labelIds": ["INBOX"],
                }
            ).execute()

            channel_id = f"ziggy-gmail-{uuid.uuid4().hex[:12]}"
            channel = WebhookChannel(
                id=channel_id,
                provider="google",
                resource="gmail",
                resource_id=str(result.get("historyId", "")),
                expiration=datetime.fromtimestamp(
                    int(result.get("expiration", 0)) / 1000,
                    tz=timezone.utc,
                ),
            )
            self._channels[channel_id] = channel
            logger.info(f"Gmail watch registered: {channel_id}")
            return channel

        except Exception as e:
            logger.error(f"Failed to setup Gmail watch: {e}")
            return None

    async def handle_calendar_notification(self, headers: Dict, body: bytes) -> bool:
        """Handle an incoming Google Calendar push notification."""
        channel_id = headers.get("x-goog-channel-id", "")
        resource_state = headers.get("x-goog-resource-state", "")
        channel_token = headers.get("x-goog-channel-token", "")

        # Verify channel is one we registered
        channel = self._channels.get(channel_id)
        if not channel:
            logger.warning(f"Unknown calendar channel: {channel_id}")
            return False

        # Verify token
        if channel.token and channel.token != channel_token:
            logger.warning(f"Token mismatch for channel {channel_id}")
            return False

        # "sync" state is the initial verification — just acknowledge
        if resource_state == "sync":
            logger.info(f"Calendar watch confirmed: {channel_id}")
            return True

        # "exists" or "not_exists" means something changed
        await self._processor.process(WebhookEvent(
            provider="google",
            resource="google_calendar",
            event_type=resource_state,
        ))
        return True

    async def handle_gmail_notification(self, data: Dict) -> bool:
        """Handle an incoming Gmail push notification (from Pub/Sub)."""
        try:
            import base64
            history_id = None
            message_data = data.get("message", {}).get("data", "")
            if message_data:
                decoded = json.loads(base64.b64decode(message_data))
                history_id = decoded.get("historyId")
                logger.info(f"Gmail notification: historyId={history_id}")

            await self._processor.process(WebhookEvent(
                provider="google",
                resource="gmail",
                event_type="sync",
                data={"historyId": history_id} if history_id else {},
            ))
            return True
        except Exception as e:
            logger.error(f"Gmail notification handling failed: {e}")
            return False

    async def stop_watch(self, channel_id: str, calendar_connector=None) -> bool:
        """Stop a watch channel."""
        channel = self._channels.pop(channel_id, None)
        if not channel:
            return False

        try:
            if calendar_connector and channel.resource == "google_calendar":
                service = calendar_connector._service
                if service:
                    service.channels().stop(body={
                        "id": channel.id,
                        "resourceId": channel.resource_id,
                    }).execute()
            logger.info(f"Watch stopped: {channel_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to stop watch {channel_id}: {e}")
            return False


class SlackHandler:
    """Handles Slack Events API notifications.

    Slack Events API flow:
    1. Register our webhook URL in Slack app settings
    2. Slack sends a challenge request — we echo it back
    3. Slack sends event payloads (message, reaction, etc.)
    4. We verify signature and trigger sync

    Security: HMAC-SHA256 verification using SLACK_SIGNING_SECRET
    """

    ENDPOINT = "/webhooks/slack/events"

    def __init__(self, processor: EventProcessor):
        self._processor = processor
        self._signing_secret = os.environ.get("SLACK_SIGNING_SECRET", "")

    def verify_signature(self, timestamp: str, body: bytes, signature: str) -> bool:
        """Verify Slack request signature (HMAC-SHA256)."""
        if not self._signing_secret:
            logger.warning("SLACK_SIGNING_SECRET not set, skipping verification")
            return True  # Allow in dev mode

        # Check timestamp freshness (within 5 minutes)
        try:
            ts = int(timestamp)
            if abs(time.time() - ts) > 300:
                logger.warning("Slack request timestamp too old")
                return False
        except (ValueError, TypeError):
            return False

        sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
        computed = "v0=" + hmac.new(
            self._signing_secret.encode(),
            sig_basestring.encode(),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(computed, signature)

    async def handle_event(self, headers: Dict, body: bytes) -> Dict:
        """Handle an incoming Slack event.

        Returns a response dict (for challenge verification or acknowledgment).
        """
        # Verify signature
        timestamp = headers.get("x-slack-request-timestamp", "")
        signature = headers.get("x-slack-signature", "")
        if not self.verify_signature(timestamp, body, signature):
            return {"error": "Invalid signature"}

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return {"error": "Invalid JSON"}

        # Handle URL verification challenge
        if payload.get("type") == "url_verification":
            return {"challenge": payload.get("challenge", "")}

        # Handle event callbacks
        if payload.get("type") == "event_callback":
            event = payload.get("event", {})
            event_type = event.get("type", "")

            # Map Slack events to sync triggers
            sync_events = {
                "message", "message.channels", "message.groups",
                "message.im", "message.mpim",
                "channel_created", "channel_archive",
                "member_joined_channel", "reaction_added",
            }

            if event_type in sync_events:
                await self._processor.process(WebhookEvent(
                    provider="slack",
                    resource="slack",
                    event_type=event_type,
                    data={"channel": event.get("channel", "")},
                ))

        return {"ok": True}


class GitHubHandler:
    """Handles GitHub webhook events.

    Covers: push, pull_request, issues, issue_comment, release, etc.

    Security: HMAC-SHA256 verification using GITHUB_WEBHOOK_SECRET
    """

    ENDPOINT = "/webhooks/github"

    def __init__(self, processor: EventProcessor):
        self._processor = processor
        self._secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")

    def verify_signature(self, body: bytes, signature: str) -> bool:
        """Verify GitHub webhook signature."""
        if not self._secret:
            return True  # Allow in dev mode

        if not signature.startswith("sha256="):
            return False

        expected = hmac.new(
            self._secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(f"sha256={expected}", signature)

    async def handle_event(self, headers: Dict, body: bytes) -> bool:
        """Handle an incoming GitHub webhook event."""
        signature = headers.get("x-hub-signature-256", "")
        if not self.verify_signature(body, signature):
            logger.warning("GitHub webhook signature verification failed")
            return False

        event_type = headers.get("x-github-event", "")

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return False

        # Ping event — just acknowledge
        if event_type == "ping":
            logger.info("GitHub webhook ping received")
            return True

        # Map GitHub events to sync triggers
        github_sync_events = {
            "push", "pull_request", "issues", "issue_comment",
            "release", "create", "delete", "star", "fork",
            "pull_request_review", "pull_request_review_comment",
        }

        if event_type in github_sync_events:
            await self._processor.process(WebhookEvent(
                provider="github",
                resource="github",
                event_type=event_type,
                data={
                    "action": payload.get("action", ""),
                    "repo": payload.get("repository", {}).get("full_name", ""),
                },
            ))

        return True


# ---------------------------------------------------------------------------
# Smart pre-fetch — proactive sync based on user patterns
# ---------------------------------------------------------------------------

class SmartPrefetch:
    """Proactively syncs data based on detected user patterns.

    Examples:
    - User checks calendar every morning at 8am → pre-sync at 7:55am
    - User checks email after every meeting → sync email when meeting ends
    - User asks about tasks on Mondays → pre-sync tasks Sunday night

    Uses the intelligence hub's pattern detection if available.
    """

    def __init__(self, sync_engine):
        self._sync_engine = sync_engine
        self._task: Optional[asyncio.Task] = None
        self._running = False
        # Built-in common-sense prefetch rules
        self._rules: List[Dict] = [
            {
                "name": "morning_calendar",
                "source": "google_calendar",
                "hours": [7, 8],  # Sync calendar at 7am and 8am
                "description": "Pre-sync calendar for morning check",
            },
            {
                "name": "morning_email",
                "source": "gmail",
                "hours": [7, 8, 9],  # Sync email early morning
                "description": "Pre-sync email for morning inbox",
            },
            {
                "name": "workday_tasks",
                "source": "todoist",
                "hours": [8, 12, 17],  # Sync tasks at start, lunch, end of day
                "description": "Pre-sync tasks at key work transitions",
            },
        ]
        self._last_prefetch: Dict[str, int] = {}  # rule_name → last trigger hour

    async def start(self) -> None:
        """Start the prefetch loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Smart prefetch started")

    async def stop(self) -> None:
        """Stop the prefetch loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        """Check every minute if any prefetch rules should trigger."""
        while self._running:
            try:
                await asyncio.sleep(60)
                now = datetime.now()
                current_hour = now.hour

                for rule in self._rules:
                    source = rule["source"]
                    # Only trigger if the source has a registered adapter
                    if source not in self._sync_engine._adapters:
                        continue

                    if current_hour in rule["hours"]:
                        last = self._last_prefetch.get(rule["name"], -1)
                        if last != current_hour:
                            self._last_prefetch[rule["name"]] = current_hour
                            logger.info(f"Prefetch trigger: {rule['name']} ({rule['description']})")
                            asyncio.create_task(
                                self._sync_engine.sync_now(source=source)
                            )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Prefetch loop error: {e}")
                await asyncio.sleep(60)


# ---------------------------------------------------------------------------
# Webhook Manager — ties it all together
# ---------------------------------------------------------------------------

class WebhookManager:
    """Manages all webhook subscriptions and handlers.

    Usage:
        manager = WebhookManager(sync_engine)
        manager.register_routes(app)              # Add endpoints
        await manager.setup_all()                  # Register subscriptions
        await manager.start_prefetch()             # Start smart prefetch
    """

    def __init__(self, sync_engine, db_path: Optional[str] = None):
        self._sync_engine = sync_engine
        self._processor = EventProcessor(sync_engine)
        self._google = GoogleHandler(self._processor)
        self._slack = SlackHandler(self._processor)
        self._github = GitHubHandler(self._processor)
        self._prefetch = SmartPrefetch(sync_engine)
        self._channels: List[WebhookChannel] = []
        self._renewal_task: Optional[asyncio.Task] = None
        self._db_path = db_path or str(Path(__file__).parent / "sqlite" / "webhooks.db")
        self._init_db()
        self._load_channels()

    # -- SQLite persistence --------------------------------------------------

    def _init_db(self) -> None:
        """Create the webhook_channels table if it doesn't exist."""
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS webhook_channels (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    expiration TEXT,
                    token TEXT DEFAULT '',
                    resource_id TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def _save_channel(self, channel: WebhookChannel) -> None:
        """Insert or update a channel in SQLite."""
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO webhook_channels "
                "(id, provider, resource, expiration, token, resource_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    channel.id,
                    channel.provider,
                    channel.resource,
                    channel.expiration.isoformat() if channel.expiration else None,
                    channel.token,
                    channel.resource_id,
                    channel.created_at.isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _delete_channel(self, channel_id: str) -> None:
        """Remove a channel from SQLite."""
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute("DELETE FROM webhook_channels WHERE id = ?", (channel_id,))
            conn.commit()
        finally:
            conn.close()

    def _load_channels(self) -> None:
        """Load non-expired channels from SQLite on startup."""
        conn = sqlite3.connect(self._db_path)
        try:
            rows = conn.execute(
                "SELECT id, provider, resource, expiration, token, resource_id, created_at "
                "FROM webhook_channels"
            ).fetchall()
        finally:
            conn.close()

        for row in rows:
            expiration = datetime.fromisoformat(row[3]) if row[3] else None
            channel = WebhookChannel(
                id=row[0],
                provider=row[1],
                resource=row[2],
                expiration=expiration,
                token=row[4] or "",
                resource_id=row[5] or "",
                created_at=datetime.fromisoformat(row[6]),
            )
            if channel.is_expired:
                self._delete_channel(channel.id)
                continue
            self._channels.append(channel)
            # Restore Google handler's lookup dict for notification verification
            if channel.provider == "google":
                self._google._channels[channel.id] = channel

        if self._channels:
            logger.info(f"Restored {len(self._channels)} webhook channel(s) from database")

    def register_routes(self, app) -> None:
        """Register webhook endpoint routes with FastAPI."""
        from fastapi import Request
        from fastapi.responses import JSONResponse

        @app.post("/webhooks/google/calendar")
        async def google_calendar_webhook(request: Request):
            """Google Calendar push notification receiver."""
            headers = dict(request.headers)
            body = await request.body()
            ok = await self._google.handle_calendar_notification(headers, body)
            return JSONResponse({"ok": ok}, status_code=200 if ok else 403)

        @app.post("/webhooks/google/gmail")
        async def google_gmail_webhook(request: Request):
            """Gmail push notification receiver (via Pub/Sub)."""
            body = await request.body()
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                return JSONResponse({"error": "invalid json"}, status_code=400)
            ok = await self._google.handle_gmail_notification(data)
            return JSONResponse({"ok": ok})

        @app.post("/webhooks/slack/events")
        async def slack_events_webhook(request: Request):
            """Slack Events API receiver."""
            headers = dict(request.headers)
            body = await request.body()
            result = await self._slack.handle_event(headers, body)
            return JSONResponse(result)

        @app.post("/webhooks/github")
        async def github_webhook(request: Request):
            """GitHub webhook receiver."""
            headers = dict(request.headers)
            body = await request.body()
            ok = await self._github.handle_event(headers, body)
            return JSONResponse({"ok": ok}, status_code=200 if ok else 403)

        @app.get("/webhooks/status")
        async def webhook_status():
            """Get status of all webhook subscriptions."""
            base_url = _get_webhook_base_url()
            return JSONResponse({
                "enabled": base_url is not None,
                "base_url": base_url,
                "channels": [
                    {
                        "id": ch.id,
                        "provider": ch.provider,
                        "resource": ch.resource,
                        "expires": ch.expiration.isoformat() if ch.expiration else None,
                        "expired": ch.is_expired,
                    }
                    for ch in self._channels
                ],
                "prefetch_rules": [
                    {"name": r["name"], "source": r["source"], "hours": r["hours"]}
                    for r in self._prefetch._rules
                ],
            })

        logger.info("Webhook routes registered")

    async def setup_all(
        self,
        calendar_connector=None,
        gmail_connector=None,
    ) -> Dict[str, Any]:
        """Set up all available webhook subscriptions.

        Only registers webhooks if WEBHOOK_BASE_URL is configured.
        Reuses persisted channels that haven't expired yet.
        Returns a summary of what was set up.
        """
        base_url = _get_webhook_base_url()
        if not base_url:
            logger.info("No WEBHOOK_BASE_URL configured — real-time webhooks disabled, using polling")
            return {"enabled": False, "reason": "No WEBHOOK_BASE_URL set"}

        results = {}

        # Resources already restored from DB
        existing_resources = {ch.resource for ch in self._channels if not ch.is_expired}

        # Google Calendar watch
        if calendar_connector:
            if "google_calendar" in existing_resources:
                results["google_calendar"] = "restored"
                logger.info("Reusing persisted Google Calendar webhook channel")
            else:
                webhook_url = f"{base_url}{GoogleHandler.CALENDAR_WATCH_ENDPOINT}"
                channel = await self._google.setup_calendar_watch(
                    calendar_connector, webhook_url
                )
                if channel:
                    self._channels.append(channel)
                    self._save_channel(channel)
                    results["google_calendar"] = "active"
                else:
                    results["google_calendar"] = "failed"

        # Gmail watch (requires Pub/Sub topic)
        if gmail_connector:
            if "gmail" in existing_resources:
                results["gmail"] = "restored"
                logger.info("Reusing persisted Gmail webhook channel")
            else:
                channel = await self._google.setup_gmail_watch(gmail_connector)
                if channel:
                    self._channels.append(channel)
                    self._save_channel(channel)
                    results["gmail"] = "active"
                else:
                    results["gmail"] = "skipped (no Pub/Sub topic)"

        # Start channel renewal loop
        self._renewal_task = asyncio.create_task(self._renewal_loop(
            calendar_connector=calendar_connector,
            gmail_connector=gmail_connector,
        ))

        return {"enabled": True, "channels": results}

    async def start_prefetch(self) -> None:
        """Start the smart prefetch engine."""
        await self._prefetch.start()

    async def stop(self) -> None:
        """Stop all webhook subscriptions and prefetch."""
        await self._prefetch.stop()
        if self._renewal_task:
            self._renewal_task.cancel()
            try:
                await self._renewal_task
            except asyncio.CancelledError:
                pass

    async def _renewal_loop(
        self,
        calendar_connector=None,
        gmail_connector=None,
    ) -> None:
        """Periodically check and renew expiring webhook channels."""
        while True:
            try:
                await asyncio.sleep(3600)  # Check every hour
                for channel in list(self._channels):
                    if channel.needs_renewal and not channel.is_expired:
                        logger.info(f"Renewing webhook channel: {channel.id}")
                        if channel.resource == "google_calendar" and calendar_connector:
                            base_url = _get_webhook_base_url()
                            if base_url:
                                # Stop old channel, create new one
                                await self._google.stop_watch(
                                    channel.id, calendar_connector
                                )
                                self._delete_channel(channel.id)
                                new_ch = await self._google.setup_calendar_watch(
                                    calendar_connector,
                                    f"{base_url}{GoogleHandler.CALENDAR_WATCH_ENDPOINT}",
                                )
                                if new_ch:
                                    self._channels.remove(channel)
                                    self._channels.append(new_ch)
                                    self._save_channel(new_ch)
                        elif channel.resource == "gmail" and gmail_connector:
                            self._delete_channel(channel.id)
                            new_ch = await self._google.setup_gmail_watch(
                                gmail_connector
                            )
                            if new_ch:
                                self._channels.remove(channel)
                                self._channels.append(new_ch)
                                self._save_channel(new_ch)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Webhook renewal error: {e}")
                await asyncio.sleep(300)


# ---------------------------------------------------------------------------
# Module-level accessor
# ---------------------------------------------------------------------------

_webhook_manager: Optional[WebhookManager] = None


def get_webhook_manager(sync_engine=None) -> Optional[WebhookManager]:
    """Get or create the global WebhookManager."""
    global _webhook_manager
    if _webhook_manager is None and sync_engine is not None:
        _webhook_manager = WebhookManager(sync_engine)
    return _webhook_manager
