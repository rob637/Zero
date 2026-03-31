"""
Event Bus for Apex Integration Platform

Centralized event system for cross-service communication:
- Services emit events when things happen
- Context engine listens and enriches events
- AI reasoner processes enriched events
- Multiple handlers can subscribe to events
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
import uuid

logger = logging.getLogger(__name__)


class EventPriority(Enum):
    """Event priority levels."""
    LOW = 1
    NORMAL = 5
    HIGH = 8
    URGENT = 10


@dataclass
class Event:
    """
    Represents an event from any service.
    
    Events flow through the system:
    1. Service emits event
    2. Context engine enriches with context
    3. AI reasons about action
    4. Orchestrator executes approved actions
    """
    
    # Required fields
    service: str           # Which service: gmail, calendar, drive, etc.
    event_type: str        # What happened: email.received, calendar.created, etc.
    
    # Event data
    data: Dict[str, Any] = field(default_factory=dict)
    
    # Metadata
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
    priority: EventPriority = EventPriority.NORMAL
    
    # Context (added by context engine)
    entities: List[Dict[str, Any]] = field(default_factory=list)
    temporal_context: Dict[str, Any] = field(default_factory=dict)
    related_items: List[Dict[str, Any]] = field(default_factory=list)
    suggested_actions: List[Dict[str, Any]] = field(default_factory=list)
    
    # Processing state
    processed: bool = False
    processing_history: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "service": self.service,
            "event_type": self.event_type,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "priority": self.priority.value,
            "entities": self.entities,
            "temporal_context": self.temporal_context,
            "related_items": self.related_items,
            "suggested_actions": self.suggested_actions,
            "processed": self.processed,
            "processing_history": self.processing_history,
        }
    
    def add_processing_step(self, step: str, result: Any = None):
        """Record a processing step."""
        self.processing_history.append({
            "step": step,
            "timestamp": datetime.now().isoformat(),
            "result": result,
        })


# Type alias for event handlers
EventHandler = Callable[[Event], Awaitable[Optional[Event]]]


class EventBus:
    """
    Central event bus for the integration platform.
    
    Features:
    - Subscribe to specific events or patterns
    - Priority-based event processing
    - Middleware support (for context enrichment)
    - Event history and replay
    """
    
    def __init__(self, history_size: int = 1000):
        """
        Initialize event bus.
        
        Args:
            history_size: Maximum events to keep in history
        """
        # Handlers: pattern -> list of handlers
        self._handlers: Dict[str, List[EventHandler]] = {}
        
        # Middleware: functions that process every event
        self._middleware: List[EventHandler] = []
        
        # Event history
        self._history: List[Event] = []
        self._history_size = history_size
        
        # Processing queue
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        
        # Running state
        self._running = False
        self._processor_task: Optional[asyncio.Task] = None
    
    def subscribe(self, pattern: str, handler: EventHandler) -> None:
        """
        Subscribe to events matching a pattern.
        
        Patterns:
        - "gmail.email.received" - exact match
        - "gmail.*" - all gmail events
        - "*" - all events
        
        Args:
            pattern: Event pattern to match
            handler: Async function to handle events
        """
        if pattern not in self._handlers:
            self._handlers[pattern] = []
        self._handlers[pattern].append(handler)
        logger.debug(f"Handler subscribed to pattern: {pattern}")
    
    def unsubscribe(self, pattern: str, handler: EventHandler) -> bool:
        """Unsubscribe a handler from a pattern."""
        if pattern in self._handlers:
            try:
                self._handlers[pattern].remove(handler)
                return True
            except ValueError:
                pass
        return False
    
    def add_middleware(self, middleware: EventHandler) -> None:
        """
        Add middleware that processes every event.
        
        Middleware runs before handlers and can:
        - Enrich the event with context
        - Filter events (return None to stop processing)
        - Transform events
        
        Args:
            middleware: Async function that processes/transforms events
        """
        self._middleware.append(middleware)
        logger.debug("Middleware added to event bus")
    
    def _match_pattern(self, pattern: str, event_key: str) -> bool:
        """Check if event key matches a pattern."""
        if pattern == "*":
            return True
        
        pattern_parts = pattern.split(".")
        event_parts = event_key.split(".")
        
        for i, p_part in enumerate(pattern_parts):
            if p_part == "*":
                return True  # Wildcard matches rest
            if i >= len(event_parts):
                return False
            if p_part != event_parts[i]:
                return False
        
        return len(pattern_parts) == len(event_parts)
    
    def _get_handlers(self, event: Event) -> List[EventHandler]:
        """Get all handlers matching an event."""
        event_key = f"{event.service}.{event.event_type}"
        handlers = []
        
        for pattern, pattern_handlers in self._handlers.items():
            if self._match_pattern(pattern, event_key):
                handlers.extend(pattern_handlers)
        
        return handlers
    
    async def emit(self, event: Event) -> None:
        """
        Emit an event to the bus.
        
        The event will be:
        1. Added to queue for processing
        2. Run through middleware
        3. Dispatched to matching handlers
        
        Args:
            event: The event to emit
        """
        await self._queue.put(event)
        logger.debug(f"Event emitted: {event.service}.{event.event_type}")
    
    def emit_sync(self, event: Event) -> None:
        """Synchronous emit for non-async contexts."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._queue.put(event))
        except RuntimeError:
            # No running loop, create one temporarily
            asyncio.run(self._queue.put(event))
    
    async def _process_event(self, event: Event) -> None:
        """Process a single event through middleware and handlers."""
        event.add_processing_step("received")
        
        # Run through middleware
        current_event = event
        for middleware in self._middleware:
            try:
                result = await middleware(current_event)
                if result is None:
                    # Middleware filtered out event
                    event.add_processing_step("filtered_by_middleware")
                    return
                current_event = result
            except Exception as e:
                logger.error(f"Middleware error: {e}")
                event.add_processing_step("middleware_error", str(e))
        
        event.add_processing_step("middleware_complete")
        
        # Get matching handlers
        handlers = self._get_handlers(current_event)
        
        if not handlers:
            logger.debug(f"No handlers for event: {current_event.service}.{current_event.event_type}")
            event.add_processing_step("no_handlers")
            return
        
        # Run handlers concurrently
        tasks = [handler(current_event) for handler in handlers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Log any errors
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Handler error: {result}")
                event.add_processing_step(f"handler_{i}_error", str(result))
            else:
                event.add_processing_step(f"handler_{i}_complete", result)
        
        current_event.processed = True
        
        # Add to history
        self._history.append(current_event)
        if len(self._history) > self._history_size:
            self._history.pop(0)
    
    async def _processor_loop(self) -> None:
        """Main event processing loop."""
        while self._running:
            try:
                # Wait for event with timeout
                try:
                    event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                
                # Process event
                await self._process_event(event)
                
            except Exception as e:
                logger.error(f"Event processor error: {e}")
    
    async def start(self) -> None:
        """Start the event processor."""
        if self._running:
            return
        
        self._running = True
        self._processor_task = asyncio.create_task(self._processor_loop())
        logger.info("Event bus started")
    
    async def stop(self) -> None:
        """Stop the event processor."""
        self._running = False
        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass
        logger.info("Event bus stopped")
    
    def get_history(
        self,
        service: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Event]:
        """
        Get recent events from history.
        
        Args:
            service: Filter by service
            event_type: Filter by event type
            limit: Maximum events to return
        
        Returns:
            List of matching events (newest first)
        """
        events = self._history
        
        if service:
            events = [e for e in events if e.service == service]
        
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        
        return list(reversed(events[-limit:]))
    
    def get_stats(self) -> Dict[str, Any]:
        """Get event bus statistics."""
        event_counts: Dict[str, int] = {}
        for event in self._history:
            key = f"{event.service}.{event.event_type}"
            event_counts[key] = event_counts.get(key, 0) + 1
        
        return {
            "total_events": len(self._history),
            "queue_size": self._queue.qsize(),
            "handlers_count": sum(len(h) for h in self._handlers.values()),
            "middleware_count": len(self._middleware),
            "event_counts": event_counts,
            "running": self._running,
        }


# Singleton instance
_event_bus: Optional[EventBus] = None

def get_event_bus() -> EventBus:
    """Get or create the event bus singleton."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


# Common event types for services
class GmailEvents:
    EMAIL_RECEIVED = "email.received"
    EMAIL_SENT = "email.sent"
    EMAIL_READ = "email.read"
    EMAIL_ARCHIVED = "email.archived"
    EMAIL_DELETED = "email.deleted"
    LABEL_ADDED = "label.added"
    LABEL_REMOVED = "label.removed"


class CalendarEvents:
    EVENT_CREATED = "event.created"
    EVENT_UPDATED = "event.updated"
    EVENT_DELETED = "event.deleted"
    EVENT_REMINDER = "event.reminder"
    EVENT_STARTING_SOON = "event.starting_soon"


class DriveEvents:
    FILE_CREATED = "file.created"
    FILE_MODIFIED = "file.modified"
    FILE_DELETED = "file.deleted"
    FILE_SHARED = "file.shared"
    FOLDER_CREATED = "folder.created"


class LocalEvents:
    FILE_CREATED = "file.created"
    FILE_MODIFIED = "file.modified"
    FILE_DELETED = "file.deleted"
    FOLDER_CHANGED = "folder.changed"
    DISK_LOW = "disk.low"
