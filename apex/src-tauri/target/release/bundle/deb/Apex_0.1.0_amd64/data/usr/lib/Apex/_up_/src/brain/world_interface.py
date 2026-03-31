"""
World Interface - How the Brain Connects to Reality

This is the bridge between cognition and action.
The brain thinks. The world interface DOES.

Without this, the brain is just philosophy.
With this, the brain is ALIVE.

Architecture:
    ┌─────────────────────────────────────────────────────────────┐
    │                      COGNITIVE CORE                         │
    │                                                             │
    │    Thinking ─────▶ Intentions ─────▶ Action Requests       │
    │        ▲                                    │               │
    │        │                                    ▼               │
    │    Perceptions ◀─────────────────── WORLD INTERFACE        │
    │                                            │                │
    └────────────────────────────────────────────┼────────────────┘
                                                 │
                    ┌────────────────────────────┼────────────────┐
                    │                            ▼                │
                    │   ┌─────────────────────────────────────┐  │
                    │   │          SERVICE ADAPTERS           │  │
                    │   │                                     │  │
                    │   │  ┌───────┐ ┌───────┐ ┌───────────┐ │  │
                    │   │  │ Gmail │ │Calendar│ │   Files   │ │  │
                    │   │  └───────┘ └───────┘ └───────────┘ │  │
                    │   │  ┌───────┐ ┌───────┐ ┌───────────┐ │  │
                    │   │  │ Drive │ │ Notion │ │  Browser  │ │  │
                    │   │  └───────┘ └───────┘ └───────────┘ │  │
                    │   └─────────────────────────────────────┘  │
                    │                    THE WORLD               │
                    └────────────────────────────────────────────┘
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set
from pathlib import Path
import json

logger = logging.getLogger(__name__)


class ServiceType(Enum):
    """Types of services the brain can interact with."""
    EMAIL = "email"
    CALENDAR = "calendar"
    FILES = "files"
    CLOUD_STORAGE = "cloud_storage"
    NOTES = "notes"
    TASKS = "tasks"
    COMMUNICATION = "communication"
    BROWSER = "browser"
    SYSTEM = "system"


class ActionResult(Enum):
    """Result of attempting an action."""
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    NEEDS_AUTH = "needs_auth"
    RATE_LIMITED = "rate_limited"
    NOT_AVAILABLE = "not_available"


@dataclass
class WorldAction:
    """
    An action the brain wants to take in the world.
    """
    id: str
    service_type: ServiceType
    operation: str              # "read", "write", "search", "create", "delete", "update"
    target: str                 # What to act on
    parameters: Dict[str, Any] = field(default_factory=dict)
    
    # Execution
    executed: bool = False
    result: Optional[ActionResult] = None
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    executed_at: Optional[datetime] = None
    duration_ms: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "service_type": self.service_type.value,
            "operation": self.operation,
            "target": self.target,
            "parameters": self.parameters,
            "executed": self.executed,
            "result": self.result.value if self.result else None,
            "error": self.error,
        }


@dataclass
class WorldObservation:
    """
    Something observed from the world.
    
    This is how the brain learns about what's happening.
    """
    id: str
    source: str                 # Which service/source
    observation_type: str       # "event", "change", "state", "alert"
    content: Dict[str, Any]
    
    # Relevance
    importance: float = 0.5
    urgency: float = 0.0        # 0 = not urgent, 1 = immediate
    
    # Metadata
    observed_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "type": self.observation_type,
            "content": self.content,
            "importance": self.importance,
            "urgency": self.urgency,
            "observed_at": self.observed_at.isoformat(),
        }


# Type aliases
ServiceAdapter = Callable[[WorldAction], Awaitable[WorldAction]]
ObservationCallback = Callable[[WorldObservation], Awaitable[None]]


class WorldInterface:
    """
    The World Interface - how the brain interacts with reality.
    
    This is the critical bridge that transforms thought into action
    and reality into perception.
    
    Responsibilities:
    1. Translate cognitive intentions into service calls
    2. Execute actions across services
    3. Monitor services for relevant changes
    4. Feed observations back to the brain
    5. Manage permissions and rate limits
    6. Track action history for learning
    """
    
    def __init__(self, storage_path: Optional[Path] = None):
        self._storage_path = storage_path
        
        # Service adapters: service_type -> adapter function
        self._adapters: Dict[ServiceType, ServiceAdapter] = {}
        
        # Observation callbacks
        self._observation_callbacks: List[ObservationCallback] = []
        
        # Action history for learning
        self._action_history: List[WorldAction] = []
        self._max_history = 1000
        
        # Observation queue
        self._observation_queue: asyncio.Queue[WorldObservation] = asyncio.Queue()
        
        # Rate limiting per service
        self._rate_limits: Dict[ServiceType, Dict] = {}
        self._call_counts: Dict[ServiceType, List[datetime]] = {}
        
        # Monitoring tasks
        self._monitors: Dict[str, asyncio.Task] = {}
        self._running = False
        
        # Permission tracking
        self._permissions: Dict[ServiceType, Set[str]] = {}  # service -> allowed operations
        
        logger.info("World interface initialized")
    
    # === Service Registration ===
    
    def register_adapter(
        self,
        service_type: ServiceType,
        adapter: ServiceAdapter,
        rate_limit: Optional[Dict] = None,
        permissions: Optional[Set[str]] = None,
    ):
        """
        Register a service adapter.
        
        Args:
            service_type: Type of service
            adapter: Async function that executes actions
            rate_limit: {"calls": int, "period_seconds": int}
            permissions: Set of allowed operations
        """
        self._adapters[service_type] = adapter
        
        if rate_limit:
            self._rate_limits[service_type] = rate_limit
            self._call_counts[service_type] = []
        
        if permissions:
            self._permissions[service_type] = permissions
        else:
            # Default: read-only
            self._permissions[service_type] = {"read", "search", "list"}
        
        logger.info(f"Registered adapter for {service_type.value}")
    
    def grant_permission(self, service_type: ServiceType, operation: str):
        """Grant permission for an operation on a service."""
        if service_type not in self._permissions:
            self._permissions[service_type] = set()
        self._permissions[service_type].add(operation)
        logger.info(f"Granted {operation} permission for {service_type.value}")
    
    def revoke_permission(self, service_type: ServiceType, operation: str):
        """Revoke permission for an operation."""
        if service_type in self._permissions:
            self._permissions[service_type].discard(operation)
    
    # === Action Execution ===
    
    async def execute(self, action: WorldAction) -> WorldAction:
        """
        Execute an action in the world.
        
        This is where thought becomes reality.
        """
        # Check if adapter exists
        if action.service_type not in self._adapters:
            action.executed = True
            action.result = ActionResult.NOT_AVAILABLE
            action.error = f"No adapter for {action.service_type.value}"
            return action
        
        # Check permission
        permitted_ops = self._permissions.get(action.service_type, set())
        if action.operation not in permitted_ops:
            action.executed = True
            action.result = ActionResult.FAILED
            action.error = f"Operation '{action.operation}' not permitted for {action.service_type.value}"
            logger.warning(f"Permission denied: {action.operation} on {action.service_type.value}")
            return action
        
        # Check rate limit
        if not self._check_rate_limit(action.service_type):
            action.executed = True
            action.result = ActionResult.RATE_LIMITED
            action.error = "Rate limit exceeded"
            return action
        
        # Execute through adapter
        start_time = datetime.now()
        
        try:
            adapter = self._adapters[action.service_type]
            action = await adapter(action)
            action.executed = True
            action.executed_at = datetime.now()
            action.duration_ms = (action.executed_at - start_time).total_seconds() * 1000
            
            if action.result is None:
                action.result = ActionResult.SUCCESS
                
        except Exception as e:
            action.executed = True
            action.executed_at = datetime.now()
            action.result = ActionResult.FAILED
            action.error = str(e)
            logger.error(f"Action failed: {e}")
        
        # Record in history
        self._record_action(action)
        
        return action
    
    async def execute_batch(self, actions: List[WorldAction]) -> List[WorldAction]:
        """Execute multiple actions, respecting dependencies."""
        results = []
        for action in actions:
            result = await self.execute(action)
            results.append(result)
            # Small delay between actions
            await asyncio.sleep(0.1)
        return results
    
    def _check_rate_limit(self, service_type: ServiceType) -> bool:
        """Check if we're within rate limits."""
        if service_type not in self._rate_limits:
            return True
        
        limit = self._rate_limits[service_type]
        calls = self._call_counts.get(service_type, [])
        
        # Clean old calls
        cutoff = datetime.now() - timedelta(seconds=limit["period_seconds"])
        calls = [c for c in calls if c > cutoff]
        self._call_counts[service_type] = calls
        
        # Check limit
        if len(calls) >= limit["calls"]:
            return False
        
        # Record this call
        calls.append(datetime.now())
        return True
    
    def _record_action(self, action: WorldAction):
        """Record action in history for learning."""
        self._action_history.append(action)
        
        # Trim history
        while len(self._action_history) > self._max_history:
            self._action_history.pop(0)
    
    # === Observation Handling ===
    
    def add_observation_callback(self, callback: ObservationCallback):
        """Add callback for observations."""
        self._observation_callbacks.append(callback)
    
    async def observe(self, observation: WorldObservation):
        """
        Receive an observation from the world.
        
        This is how reality reaches the brain.
        """
        await self._observation_queue.put(observation)
        
        # Notify callbacks
        for callback in self._observation_callbacks:
            try:
                await callback(observation)
            except Exception as e:
                logger.error(f"Observation callback error: {e}")
    
    async def get_observation(self, timeout: float = 0.1) -> Optional[WorldObservation]:
        """Get next observation from queue."""
        try:
            return await asyncio.wait_for(
                self._observation_queue.get(),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            return None
    
    # === World Monitoring ===
    
    async def start_monitoring(self):
        """Start monitoring all registered services."""
        self._running = True
        
        for service_type in self._adapters:
            task = asyncio.create_task(self._monitor_service(service_type))
            self._monitors[service_type.value] = task
        
        logger.info("World monitoring started")
    
    async def stop_monitoring(self):
        """Stop all monitoring."""
        self._running = False
        
        for task in self._monitors.values():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        self._monitors.clear()
        logger.info("World monitoring stopped")
    
    async def _monitor_service(self, service_type: ServiceType):
        """Monitor a service for changes."""
        while self._running:
            try:
                # Create a check action
                check_action = WorldAction(
                    id=f"monitor_{service_type.value}_{datetime.now().timestamp()}",
                    service_type=service_type,
                    operation="check",
                    target="status",
                )
                
                # Execute check (adapter should return state changes)
                result = await self.execute(check_action)
                
                # If there are observations in the output, emit them
                if result.output and "observations" in result.output:
                    for obs_data in result.output["observations"]:
                        observation = WorldObservation(
                            id=f"obs_{datetime.now().timestamp()}",
                            source=service_type.value,
                            observation_type=obs_data.get("type", "change"),
                            content=obs_data,
                            importance=obs_data.get("importance", 0.5),
                            urgency=obs_data.get("urgency", 0.0),
                        )
                        await self.observe(observation)
                
                # Wait before next check (longer for less critical services)
                await asyncio.sleep(60)  # Check every minute
                
            except Exception as e:
                logger.error(f"Monitor error for {service_type.value}: {e}")
                await asyncio.sleep(120)  # Back off on error
    
    # === Query Interface ===
    
    async def query(
        self,
        service_type: ServiceType,
        query: str,
        parameters: Optional[Dict] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Query a service for information.
        
        Convenience method for read operations.
        """
        action = WorldAction(
            id=f"query_{datetime.now().timestamp()}",
            service_type=service_type,
            operation="search",
            target=query,
            parameters=parameters or {},
        )
        
        result = await self.execute(action)
        
        if result.result == ActionResult.SUCCESS:
            return result.output
        return None
    
    async def get_state(self, service_type: ServiceType) -> Optional[Dict[str, Any]]:
        """Get current state of a service."""
        action = WorldAction(
            id=f"state_{datetime.now().timestamp()}",
            service_type=service_type,
            operation="read",
            target="state",
        )
        
        result = await self.execute(action)
        
        if result.result == ActionResult.SUCCESS:
            return result.output
        return None
    
    # === Statistics ===
    
    def get_stats(self) -> Dict[str, Any]:
        """Get world interface statistics."""
        action_counts = {}
        success_rates = {}
        
        for action in self._action_history:
            service = action.service_type.value
            action_counts[service] = action_counts.get(service, 0) + 1
            
            if action.result == ActionResult.SUCCESS:
                if service not in success_rates:
                    success_rates[service] = {"success": 0, "total": 0}
                success_rates[service]["success"] += 1
                success_rates[service]["total"] += 1
            elif action.result in [ActionResult.FAILED, ActionResult.PARTIAL]:
                if service not in success_rates:
                    success_rates[service] = {"success": 0, "total": 0}
                success_rates[service]["total"] += 1
        
        # Calculate rates
        for service, data in success_rates.items():
            if data["total"] > 0:
                success_rates[service]["rate"] = data["success"] / data["total"]
        
        return {
            "registered_services": list(self._adapters.keys()),
            "action_counts": action_counts,
            "success_rates": success_rates,
            "total_actions": len(self._action_history),
            "observation_queue_size": self._observation_queue.qsize(),
            "active_monitors": list(self._monitors.keys()),
        }
    
    def get_action_history(
        self,
        service_type: Optional[ServiceType] = None,
        operation: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get action history for learning."""
        actions = self._action_history
        
        if service_type:
            actions = [a for a in actions if a.service_type == service_type]
        
        if operation:
            actions = [a for a in actions if a.operation == operation]
        
        return [a.to_dict() for a in actions[-limit:]]


# Singleton
_world_interface: Optional[WorldInterface] = None

def get_world_interface() -> WorldInterface:
    """Get or create the world interface singleton."""
    global _world_interface
    if _world_interface is None:
        _world_interface = WorldInterface()
    return _world_interface
