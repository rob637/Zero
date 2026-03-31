"""
ApprovalGateway - Every action flows through here.

This is the enforcement layer for human-in-the-loop control.
No action executes without:
1. Passing through the gateway
2. Getting appropriate approval (based on trust level)
3. Being logged for audit

The gateway also:
- Queues actions for batched approval
- Groups related actions together (workflow steps)
- Provides rich previews for each action type
- Supports inline editing before approval
- Tracks action history for undo

Usage:
    gateway = ApprovalGateway()
    
    # Submit an action
    action_id = await gateway.submit(PendingAction(
        action_type="send_email",
        payload={"to": "rob@sagecg.com", "subject": "Loan Info", "body": "..."},
        preview={"type": "email", "to": "rob@sagecg.com", "subject": "Loan Info"},
    ))
    
    # For ALWAYS_ASK actions, this will be queued for user approval
    # For AUTO_APPROVE actions, it executes immediately
    
    # User approves (optionally with modifications)
    result = await gateway.approve(action_id, modifications={"body": "Updated text..."})
    
    # Or user rejects
    await gateway.reject(action_id, reason="Wrong recipient")
"""

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Awaitable
import logging

from .trust_levels import TrustLevel, TrustLevelManager, trust_manager

logger = logging.getLogger(__name__)


class ActionStatus(Enum):
    """Status of an action in the gateway."""
    PENDING = "pending"              # Awaiting approval
    APPROVED = "approved"            # User approved
    REJECTED = "rejected"            # User rejected
    EXECUTING = "executing"          # Currently executing
    COMPLETED = "completed"          # Successfully executed
    FAILED = "failed"                # Execution failed
    AUTO_APPROVED = "auto_approved"  # Automatically approved by trust level
    EXPIRED = "expired"              # Pending too long, expired


class RiskLevel(Enum):
    """Risk level of an action."""
    LOW = "low"           # Read-only, no side effects
    MEDIUM = "medium"     # Creates/modifies but reversible
    HIGH = "high"         # Sends externally or deletes
    CRITICAL = "critical" # Financial, irreversible, public


@dataclass
class ActionPreview:
    """
    Preview information for displaying an action to the user.
    
    This is what the user sees in the approval UI.
    """
    title: str
    description: str
    preview_type: str  # "email", "document", "calendar", "file", "calculation", etc.
    
    # Type-specific preview data
    fields: Dict[str, Any] = field(default_factory=dict)
    
    # Attachments or related items
    attachments: List[Dict] = field(default_factory=list)
    
    # Warnings or important notes
    warnings: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "title": self.title,
            "description": self.description,
            "preview_type": self.preview_type,
            "fields": self.fields,
            "attachments": self.attachments,
            "warnings": self.warnings,
        }


@dataclass
class PendingAction:
    """
    An action pending approval in the gateway.
    
    Contains everything needed to:
    1. Display the action to the user
    2. Execute when approved
    3. Track for audit/undo
    """
    # Identity
    id: str = ""
    action_type: str = ""  # e.g., "send_email", "delete_file", "create_event"
    
    # What to execute
    payload: Dict[str, Any] = field(default_factory=dict)
    
    # What to show the user
    preview: ActionPreview = None
    
    # Risk and reversibility
    risk_level: RiskLevel = RiskLevel.MEDIUM
    reversible: bool = True
    
    # Timing
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None  # Auto-expire if not approved
    approved_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    
    # Status tracking
    status: ActionStatus = ActionStatus.PENDING
    
    # Execution
    executor: Optional[Callable[[Dict], Awaitable[Dict]]] = None
    result: Optional[Dict] = None
    error: Optional[str] = None
    
    # Workflow context
    workflow_id: Optional[str] = None
    step_number: Optional[int] = None
    
    # Modifications
    modifications: Optional[Dict] = None  # User edits before approval
    
    def __post_init__(self):
        if not self.id:
            self.id = self._generate_id()
        if self.expires_at is None:
            # Default: expire after 1 hour if not approved
            self.expires_at = datetime.now() + timedelta(hours=1)
    
    def _generate_id(self) -> str:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        return f"action_{timestamp}"
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "action_type": self.action_type,
            "status": self.status.value,
            "risk_level": self.risk_level.value,
            "reversible": self.reversible,
            "preview": self.preview.to_dict() if self.preview else None,
            "created_at": self.created_at.isoformat(),
            "workflow_id": self.workflow_id,
            "step_number": self.step_number,
            "has_modifications": self.modifications is not None,
        }


class ApprovalGateway:
    """
    Central gate that all actions flow through.
    
    This is the enforcement layer for human-in-the-loop control.
    It ensures:
    1. Every action is logged
    2. Trust levels are enforced
    3. Users can preview/edit before approval
    4. Actions can be undone (if reversible)
    
    The gateway integrates with:
    - TrustLevelManager: To determine approval requirements
    - AuditLogger: To log all actions
    - UndoManager: To enable rollback
    """
    
    def __init__(
        self,
        trust_mgr: Optional[TrustLevelManager] = None,
        audit_logger = None,
    ):
        """
        Initialize the approval gateway.
        
        Args:
            trust_mgr: TrustLevelManager instance (default: global)
            audit_logger: AuditLogger instance for action logging
        """
        self._trust = trust_mgr or trust_manager
        self._audit = audit_logger
        
        # Pending actions
        self._pending: Dict[str, PendingAction] = {}
        
        # Completed actions (for history/undo)
        self._history: List[PendingAction] = []
        self._max_history = 100
        
        # Callbacks
        self._on_pending: List[Callable[[PendingAction], None]] = []
        self._on_approved: List[Callable[[PendingAction], None]] = []
        self._on_rejected: List[Callable[[PendingAction], None]] = []
        self._on_executed: List[Callable[[PendingAction, Dict], None]] = []
        
        logger.info("ApprovalGateway initialized")
    
    async def submit(
        self,
        action: PendingAction,
        context: Optional[Dict] = None,
    ) -> str:
        """
        Submit an action for approval.
        
        Based on trust level:
        - ALWAYS_ASK: Queue for user approval
        - ASK_ONCE: Queue, but offer to remember
        - AUTO_APPROVE: Execute immediately
        
        Args:
            action: The action to submit
            context: Context for trust level checking (for pattern matching)
            
        Returns:
            Action ID for tracking
        """
        # Get trust level
        trust_level = self._trust.get_trust_level(action.action_type, context)
        
        logger.info(
            f"Action submitted: {action.action_type} "
            f"(trust: {trust_level.value}, risk: {action.risk_level.value})"
        )
        
        if trust_level == TrustLevel.AUTO_APPROVE:
            # Execute immediately
            action.status = ActionStatus.AUTO_APPROVED
            action.approved_at = datetime.now()
            
            if action.executor:
                try:
                    action.status = ActionStatus.EXECUTING
                    action.result = await action.executor(action.payload)
                    action.status = ActionStatus.COMPLETED
                    action.executed_at = datetime.now()
                    
                    self._add_to_history(action)
                    self._trigger_executed(action, action.result)
                    
                except Exception as e:
                    action.status = ActionStatus.FAILED
                    action.error = str(e)
                    logger.error(f"Auto-approved action failed: {e}")
            
            return action.id
        
        # Queue for approval
        action.status = ActionStatus.PENDING
        self._pending[action.id] = action
        
        self._trigger_pending(action)
        
        logger.debug(f"Action queued for approval: {action.id}")
        return action.id
    
    async def approve(
        self,
        action_id: str,
        modifications: Optional[Dict] = None,
        remember_pattern: bool = False,
        pattern_context: Optional[Dict] = None,
    ) -> PendingAction:
        """
        Approve an action, optionally with modifications.
        
        Args:
            action_id: ID of action to approve
            modifications: Optional modifications to apply before execution
            remember_pattern: If ASK_ONCE, remember this pattern for future
            pattern_context: Context to remember for pattern matching
            
        Returns:
            Updated PendingAction with result
        """
        action = self._pending.get(action_id)
        if not action:
            raise ValueError(f"Action not found: {action_id}")
        
        if action.status != ActionStatus.PENDING:
            raise ValueError(f"Action not pending: {action.status.value}")
        
        # Apply modifications
        if modifications:
            action.modifications = modifications
            # Merge into payload
            action.payload = {**action.payload, **modifications}
        
        # Update status
        action.status = ActionStatus.APPROVED
        action.approved_at = datetime.now()
        
        self._trigger_approved(action)
        
        # Remember pattern if requested (for ASK_ONCE)
        if remember_pattern and pattern_context:
            trust_level = self._trust.get_trust_level(action.action_type)
            if trust_level == TrustLevel.ASK_ONCE:
                description = action.preview.title if action.preview else action.action_type
                self._trust.remember_pattern(
                    action.action_type,
                    pattern_context,
                    description,
                )
        
        # Execute
        if action.executor:
            try:
                action.status = ActionStatus.EXECUTING
                action.result = await action.executor(action.payload)
                action.status = ActionStatus.COMPLETED
                action.executed_at = datetime.now()
                
                self._trigger_executed(action, action.result)
                
            except Exception as e:
                action.status = ActionStatus.FAILED
                action.error = str(e)
                logger.error(f"Action execution failed: {e}")
        
        # Move to history
        del self._pending[action_id]
        self._add_to_history(action)
        
        logger.info(f"Action approved and executed: {action_id} -> {action.status.value}")
        return action
    
    async def reject(
        self,
        action_id: str,
        reason: Optional[str] = None,
    ) -> PendingAction:
        """
        Reject an action.
        
        Args:
            action_id: ID of action to reject
            reason: Optional reason for rejection
            
        Returns:
            Updated PendingAction
        """
        action = self._pending.get(action_id)
        if not action:
            raise ValueError(f"Action not found: {action_id}")
        
        action.status = ActionStatus.REJECTED
        action.error = reason
        
        # Move to history
        del self._pending[action_id]
        self._add_to_history(action)
        
        self._trigger_rejected(action)
        
        logger.info(f"Action rejected: {action_id} - {reason or 'no reason'}")
        return action
    
    def get_pending(self) -> List[PendingAction]:
        """Get all pending actions awaiting approval."""
        now = datetime.now()
        pending = []
        
        for action in list(self._pending.values()):
            # Check expiration
            if action.expires_at and now > action.expires_at:
                action.status = ActionStatus.EXPIRED
                del self._pending[action.id]
                self._add_to_history(action)
                continue
            
            pending.append(action)
        
        # Sort by creation time (oldest first)
        pending.sort(key=lambda a: a.created_at)
        return pending
    
    def get_pending_by_workflow(self, workflow_id: str) -> List[PendingAction]:
        """Get pending actions for a specific workflow."""
        return [
            a for a in self.get_pending()
            if a.workflow_id == workflow_id
        ]
    
    def get_action(self, action_id: str) -> Optional[PendingAction]:
        """Get an action by ID (pending or history)."""
        if action_id in self._pending:
            return self._pending[action_id]
        
        for action in self._history:
            if action.id == action_id:
                return action
        
        return None
    
    def get_history(
        self,
        limit: int = 20,
        status: Optional[ActionStatus] = None,
    ) -> List[PendingAction]:
        """
        Get action history.
        
        Args:
            limit: Maximum actions to return
            status: Filter by status
            
        Returns:
            List of completed actions (newest first)
        """
        history = self._history.copy()
        
        if status:
            history = [a for a in history if a.status == status]
        
        # Newest first
        history.reverse()
        return history[:limit]
    
    def _add_to_history(self, action: PendingAction):
        """Add an action to history."""
        self._history.append(action)
        
        # Trim if needed
        while len(self._history) > self._max_history:
            self._history.pop(0)
    
    # === Callback Registration ===
    
    def on_pending(self, callback: Callable[[PendingAction], None]):
        """Register callback for when action is queued for approval."""
        self._on_pending.append(callback)
    
    def on_approved(self, callback: Callable[[PendingAction], None]):
        """Register callback for when action is approved."""
        self._on_approved.append(callback)
    
    def on_rejected(self, callback: Callable[[PendingAction], None]):
        """Register callback for when action is rejected."""
        self._on_rejected.append(callback)
    
    def on_executed(self, callback: Callable[[PendingAction, Dict], None]):
        """Register callback for when action is executed."""
        self._on_executed.append(callback)
    
    def _trigger_pending(self, action: PendingAction):
        for cb in self._on_pending:
            try:
                cb(action)
            except Exception as e:
                logger.error(f"Callback error (pending): {e}")
    
    def _trigger_approved(self, action: PendingAction):
        for cb in self._on_approved:
            try:
                cb(action)
            except Exception as e:
                logger.error(f"Callback error (approved): {e}")
    
    def _trigger_rejected(self, action: PendingAction):
        for cb in self._on_rejected:
            try:
                cb(action)
            except Exception as e:
                logger.error(f"Callback error (rejected): {e}")
    
    def _trigger_executed(self, action: PendingAction, result: Dict):
        for cb in self._on_executed:
            try:
                cb(action, result)
            except Exception as e:
                logger.error(f"Callback error (executed): {e}")
    
    # === Stats ===
    
    def get_stats(self) -> Dict:
        """Get gateway statistics."""
        pending = self.get_pending()
        
        status_counts = {}
        for action in self._history:
            status = action.status.value
            status_counts[status] = status_counts.get(status, 0) + 1
        
        return {
            "pending_count": len(pending),
            "history_count": len(self._history),
            "by_status": status_counts,
            "oldest_pending": pending[0].created_at.isoformat() if pending else None,
        }


# === Preview Builders ===

def build_email_preview(
    to: str,
    subject: str,
    body: str,
    attachments: List[Dict] = None,
) -> ActionPreview:
    """Build a preview for an email action."""
    return ActionPreview(
        title=f"Email to {to}",
        description=f"Subject: {subject}",
        preview_type="email",
        fields={
            "to": to,
            "subject": subject,
            "body": body,
            "body_preview": body[:200] + "..." if len(body) > 200 else body,
        },
        attachments=attachments or [],
        warnings=[] if "@" in to else ["Invalid email address"],
    )


def build_document_preview(
    filename: str,
    content_preview: str,
    source: Optional[str] = None,
) -> ActionPreview:
    """Build a preview for a document."""
    return ActionPreview(
        title=f"📄 {filename}",
        description=f"Found in: {source}" if source else "Document found",
        preview_type="document",
        fields={
            "filename": filename,
            "source": source,
            "content_preview": content_preview,
        },
    )


def build_calculation_preview(
    title: str,
    inputs: Dict[str, Any],
    outputs: Dict[str, Any],
) -> ActionPreview:
    """Build a preview for a calculation."""
    return ActionPreview(
        title=f"📊 {title}",
        description="Calculation result",
        preview_type="calculation",
        fields={
            "inputs": inputs,
            "outputs": outputs,
        },
    )


def build_calendar_preview(
    title: str,
    start: datetime,
    end: datetime,
    attendees: List[str] = None,
) -> ActionPreview:
    """Build a preview for a calendar event."""
    return ActionPreview(
        title=f"📅 {title}",
        description=f"{start.strftime('%B %d, %Y at %I:%M %p')}",
        preview_type="calendar",
        fields={
            "title": title,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "duration_minutes": int((end - start).total_seconds() / 60),
            "attendees": attendees or [],
        },
    )


# Global instance for convenience
approval_gateway = ApprovalGateway()
