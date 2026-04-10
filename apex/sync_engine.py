"""
Background Sync Engine

Periodically pulls data from connected services into the local Index.
Each source has its own sync adapter that knows how to call the connector
and normalize the results into DataObjects.

Design principles:
  - Non-blocking: runs as an asyncio background task
  - Incremental: uses sync tokens where available (Google syncToken, etc.)
  - Resilient: one source failing doesn't block others
  - Observable: sync states tracked in SQLite for monitoring
  - Configurable: per-source intervals and staleness thresholds
"""

import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Coroutine, Dict, List, Optional

try:
    from .index import (
        DataObject,
        Index,
        ObjectKind,
        SyncState,
        SyncStatus,
        NORMALIZERS,
    )
except ImportError:
    from index import (
        DataObject,
        Index,
        ObjectKind,
        SyncState,
        SyncStatus,
        NORMALIZERS,
    )

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sync adapter protocol
# ---------------------------------------------------------------------------

class SyncAdapter:
    """Knows how to pull data from a specific connector and normalize it.

    Subclass this per connector, or use the generic `ConnectorSyncAdapter`
    for connectors that follow the standard list_* pattern.
    """

    source: str              # Must match a key in NORMALIZERS
    default_interval: int    # Seconds between syncs

    async def fetch(
        self,
        sync_token: Optional[str] = None,
        since: Optional[datetime] = None,
    ) -> tuple[List[DataObject], str]:
        """Pull data and return (objects, new_sync_token).

        If sync_token is provided, do incremental sync.
        If since is provided, pull items modified after that time.
        Return empty string for sync_token if incremental isn't supported.
        """
        raise NotImplementedError


class ConnectorSyncAdapter(SyncAdapter):
    """Generic adapter that works with any connector following the list_* pattern.

    Usage:
        adapter = ConnectorSyncAdapter(
            source="google_calendar",
            connector=calendar_connector,
            fetch_method="list_events",
            fetch_kwargs={"max_results": 250},
            default_interval=300,  # 5 minutes
        )
    """

    def __init__(
        self,
        source: str,
        connector: Any,
        fetch_method: str,
        fetch_kwargs: Optional[Dict[str, Any]] = None,
        default_interval: int = 300,
        normalizer: Optional[Callable] = None,
    ):
        self.source = source
        self._connector = connector
        self._fetch_method = fetch_method
        self._fetch_kwargs = fetch_kwargs or {}
        self.default_interval = default_interval
        self._normalizer = normalizer or NORMALIZERS.get(source)

    async def fetch(
        self,
        sync_token: Optional[str] = None,
        since: Optional[datetime] = None,
    ) -> tuple[List[DataObject], str]:
        method = getattr(self._connector, self._fetch_method)
        kwargs = dict(self._fetch_kwargs)

        # If the connector accepts time bounds, add them
        if since:
            if "time_min" in method.__code__.co_varnames:
                kwargs["time_min"] = since.isoformat()
            elif "after" in method.__code__.co_varnames:
                kwargs["after"] = since.isoformat()

        raw_items = await method(**kwargs)
        if not raw_items:
            return [], ""

        # Normalize
        objects = []
        for item in raw_items:
            item_dict = item.to_dict() if hasattr(item, "to_dict") else item
            if self._normalizer:
                obj = self._normalizer(item_dict, source=self.source)
                objects.append(obj)

        return objects, ""  # No incremental token for generic adapter


class CalendarSyncAdapter(SyncAdapter):
    """Specialized adapter for Google Calendar using syncToken for incremental sync.

    First sync: pulls all events (±90 days), stores syncToken.
    Subsequent syncs: only fetches changes since last sync token.
    Handles deletions (cancelled events removed from index).
    """

    source = "google_calendar"
    default_interval = 300  # 5 minutes

    def __init__(self, connector: Any, default_interval: int = 300):
        self._connector = connector
        self.default_interval = default_interval
        self._normalizer = NORMALIZERS.get("google_calendar")

    async def fetch(
        self,
        sync_token: Optional[str] = None,
        since: Optional[datetime] = None,
    ) -> tuple[List[DataObject], str]:
        if not hasattr(self._connector, 'sync_events'):
            # Fallback to generic list if connector doesn't support sync_events
            raw_items = await self._connector.list_events(max_results=250)
            objects = []
            for item in raw_items:
                item_dict = item.to_dict() if hasattr(item, "to_dict") else item
                if self._normalizer:
                    objects.append(self._normalizer(item_dict, source=self.source))
            return objects, ""

        # Sync all owner/writer calendars
        all_objects = []
        final_tokens = {}  # calendar_id → token
        old_tokens = {}

        # Parse stored sync_token — it's a JSON dict of {cal_id: token}
        if sync_token:
            try:
                import json as _json
                old_tokens = _json.loads(sync_token)
            except (ValueError, TypeError):
                old_tokens = {}

        # Get writable calendars
        calendars = await self._connector.list_calendars()
        cal_ids = [
            c['id'] for c in calendars
            if c.get('accessRole') in ('owner', 'writer')
        ] or ['primary']

        for cal_id in cal_ids:
            cal_token = old_tokens.get(cal_id)
            events, deleted_ids, new_token = await self._connector.sync_events(
                calendar_id=cal_id,
                sync_token=cal_token,
            )

            # Normalize events
            for ev in events:
                item_dict = ev.to_dict() if hasattr(ev, "to_dict") else ev
                if self._normalizer:
                    obj = self._normalizer(item_dict, source=self.source)
                    all_objects.append(obj)

            # Mark deleted events with a sentinel — the sync engine will handle removal
            for did in deleted_ids:
                all_objects.append(DataObject(
                    source=self.source,
                    source_id=did,
                    kind=ObjectKind.EVENT,
                    title="__DELETED__",
                    status="deleted",
                ))

            if new_token:
                final_tokens[cal_id] = new_token

        import json as _json
        combined_token = _json.dumps(final_tokens) if final_tokens else ""
        return all_objects, combined_token


class GmailSyncAdapter(SyncAdapter):
    """Specialized sync adapter for Gmail using the History API.

    Does incremental sync via historyId — only fetches new/deleted messages
    since last sync instead of re-listing everything.
    """

    source = "gmail"
    default_interval = 300  # 5 minutes

    def __init__(self, connector: Any, default_interval: int = 300):
        self._connector = connector
        self.default_interval = default_interval
        self._normalizer = NORMALIZERS.get("gmail")

    async def fetch(
        self,
        sync_token: Optional[str] = None,
        since: Optional[datetime] = None,
    ) -> tuple[List[DataObject], str]:
        result = await self._connector.sync_messages(
            history_id=sync_token or None,
            max_results=100,
        )

        objects = []
        for email in result.get("messages", []):
            item_dict = email.to_dict() if hasattr(email, "to_dict") else email
            if self._normalizer:
                obj = self._normalizer(item_dict, source=self.source)
                objects.append(obj)

        # Mark deleted messages with sentinel for sync engine removal
        for did in result.get("deleted_ids", []):
            objects.append(DataObject(
                source=self.source,
                source_id=did,
                kind=ObjectKind.EMAIL,
                title="__DELETED__",
                status="deleted",
            ))

        new_history_id = result.get("history_id", "")
        return objects, new_history_id


# ---------------------------------------------------------------------------
# SyncEngine — orchestrates all adapters
# ---------------------------------------------------------------------------

class SyncEngine:
    """Background sync engine.

    Usage:
        engine = SyncEngine(index)
        engine.register(calendar_adapter)
        engine.register(gmail_adapter)
        await engine.start()       # Starts background loop
        await engine.sync_now()    # Force immediate sync of all sources
        await engine.stop()        # Graceful shutdown
    """

    def __init__(self, index: Index):
        self._index = index
        self._adapters: Dict[str, SyncAdapter] = {}
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._tick_interval = 30  # Check every 30s which sources need syncing
        self._semantic_search = None  # Set externally after init
        self._consecutive_failures: Dict[str, int] = {}  # source → failure count
        self._last_attempt: Dict[str, float] = {}  # source → monotonic timestamp of last attempt

    def set_semantic_search(self, ss) -> None:
        """Attach semantic search for post-sync embedding."""
        self._semantic_search = ss

    def register(self, adapter: SyncAdapter) -> None:
        """Register a sync adapter."""
        self._adapters[adapter.source] = adapter
        logger.info(f"Sync adapter registered: {adapter.source} (interval={adapter.default_interval}s)")

    async def start(self) -> None:
        """Start the background sync loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"Sync engine started with {len(self._adapters)} adapters")

    async def stop(self) -> None:
        """Stop the background sync loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Sync engine stopped")

    async def sync_now(self, source: Optional[str] = None) -> Dict[str, Any]:
        """Force immediate sync. If source is given, sync only that source."""
        if source:
            if source not in self._adapters:
                return {"error": f"Unknown source: {source}"}
            result = await self._sync_source(source)
            return {source: result}
        else:
            results = {}
            # Run all syncs concurrently
            tasks = {
                s: asyncio.create_task(self._sync_source(s))
                for s in self._adapters
            }
            for s, task in tasks.items():
                try:
                    results[s] = await task
                except Exception as e:
                    results[s] = {"status": "error", "error": str(e)}
            return results

    @property
    def status(self) -> Dict[str, Any]:
        """Get current sync status for all sources."""
        states = self._index.all_sync_states()
        return {
            "running": self._running,
            "adapters": list(self._adapters.keys()),
            "states": {
                s.source: {
                    "last_sync": s.last_sync.isoformat() if s.last_sync else None,
                    "status": s.status.value,
                    "item_count": s.item_count,
                    "error": s.error,
                    "sync_duration_ms": s.sync_duration_ms,
                }
                for s in states
            },
            "index_stats": self._index.stats(),
        }

    # -------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------

    async def _loop(self) -> None:
        """Background loop: check which sources are stale and sync them."""
        # Do initial sync on startup
        await self.sync_now()

        cycles = 0
        while self._running:
            try:
                await asyncio.sleep(self._tick_interval)
                cycles += 1
                for source, adapter in self._adapters.items():
                    # Back off on repeated failures: double interval per failure, max 30 min
                    fails = self._consecutive_failures.get(source, 0)
                    effective_interval = min(
                        adapter.default_interval * (2 ** fails),
                        1800,  # 30 minute cap
                    )
                    # If source has failures, check time since last attempt (not last success)
                    if fails > 0:
                        last = self._last_attempt.get(source, 0)
                        if (time.monotonic() - last) < effective_interval:
                            continue  # Still in backoff window, skip
                    elif not self._index.is_stale(
                        source,
                        max_age=timedelta(seconds=effective_interval)
                    ):
                        continue  # Not stale yet, skip
                    asyncio.create_task(self._sync_source(source))

                # Periodic stale data cleanup — every ~100 cycles (~50 min)
                if cycles % 100 == 0:
                    asyncio.create_task(self._cleanup_stale())

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Sync loop error: {e}")
                await asyncio.sleep(5)

    async def _sync_source(self, source: str) -> Dict[str, Any]:
        """Sync a single source. Returns summary dict."""
        adapter = self._adapters[source]
        state = self._index.get_sync_state(source) or SyncState(source=source)

        # Record attempt time for backoff
        self._last_attempt[source] = time.monotonic()

        # Mark as syncing
        state.status = SyncStatus.SYNCING
        state.error = ""
        self._index.set_sync_state(state)

        t0 = time.perf_counter()
        try:
            objects, new_token = await adapter.fetch(
                sync_token=state.sync_token or None,
                since=state.last_sync,
            )

            # Separate deletions from upserts
            to_upsert = [o for o in objects if o.status != "deleted"]
            to_delete = [o for o in objects if o.status == "deleted"]

            count = self._index.upsert_batch(to_upsert)

            # Remove deleted objects from index
            deleted = 0
            for obj in to_delete:
                try:
                    self._index._conn.execute(
                        "DELETE FROM data_objects WHERE id = ?", (obj.id,)
                    )
                    deleted += 1
                except Exception:
                    pass
            if deleted:
                self._index._conn.commit()

            elapsed_ms = int((time.perf_counter() - t0) * 1000)

            # Update sync state
            state.last_sync = datetime.now(timezone.utc)
            state.status = SyncStatus.IDLE
            state.item_count = count
            state.sync_duration_ms = elapsed_ms
            if new_token:
                state.sync_token = new_token
            self._index.set_sync_state(state)

            logger.info(f"Synced {source}: {count} objects in {elapsed_ms}ms")
            self._consecutive_failures.pop(source, None)  # Reset on success
            self._last_attempt.pop(source, None)  # Back to normal staleness check

            # Embed new/updated objects for semantic search (non-blocking)
            if self._semantic_search and self._semantic_search.ready and to_upsert:
                try:
                    embedded = await self._semantic_search.embed_objects(to_upsert)
                    if embedded:
                        logger.info(f"Embedded {embedded} objects from {source}")
                except Exception as e:
                    logger.warning(f"Post-sync embedding failed for {source}: {e}")

            return {"status": "ok", "count": count, "duration_ms": elapsed_ms}

        except Exception as e:
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            state.status = SyncStatus.ERROR
            state.error = str(e)
            state.sync_duration_ms = elapsed_ms
            self._index.set_sync_state(state)
            logger.error(f"Sync failed for {source}: {e}")
            fails = self._consecutive_failures.get(source, 0) + 1
            self._consecutive_failures[source] = fails
            next_try_s = min(adapter.default_interval * (2 ** fails), 1800)
            if fails >= 3:
                logger.warning(f"Sync {source}: {fails} consecutive failures, backing off to {next_try_s}s")
            return {"status": "error", "error": str(e), "duration_ms": elapsed_ms}

    async def _cleanup_stale(self) -> None:
        """Remove data objects that haven't been refreshed in a long time.

        - Events older than 90 days in the past: remove
        - Emails not seen in 30 days: remove
        - Other objects not synced in 30 days: remove
        """
        try:
            cutoff_events = datetime.now(timezone.utc) - timedelta(days=90)
            cutoff_general = datetime.now(timezone.utc) - timedelta(days=30)

            # Past events older than 90 days
            c1 = self._index._conn.execute(
                "DELETE FROM data_objects WHERE kind = 'event' AND timestamp < ? AND synced_at < ?",
                (cutoff_events.isoformat(), cutoff_events.isoformat())
            ).rowcount

            # Emails/tasks/etc. not synced in 30 days
            c2 = self._index._conn.execute(
                "DELETE FROM data_objects WHERE kind != 'event' AND kind != 'contact' AND synced_at < ?",
                (cutoff_general.isoformat(),)
            ).rowcount

            if c1 or c2:
                self._index._conn.commit()
                logger.info(f"Stale cleanup: removed {c1} old events, {c2} stale objects")
        except Exception as e:
            logger.error(f"Stale cleanup failed: {e}")
