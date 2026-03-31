"""
Control Layer - Human-in-the-Loop for Apex

This module implements the core control principles:
1. Apex PROPOSES, you APPROVE - nothing executes without confirmation
2. Trust levels - configure what needs approval vs auto-approve
3. Undo capability - checkpoint before actions, rollback on request
4. Action history - review everything Apex has done

Components:
- TrustLevelManager: Manages per-action trust levels (🔴🟡🟢)
- ApprovalGateway: Central gate all actions flow through
- UndoManager: Checkpoint and rollback for reversible actions
- ActionHistoryDB: Complete audit trail of all actions
"""

from .trust_levels import TrustLevel, TrustLevelManager, trust_manager
from .approval_gateway import (
    PendingAction,
    ActionStatus,
    ApprovalGateway,
    approval_gateway,
)
from .action_history import (
    ActionRecord,
    ActionStatus as HistoryActionStatus,
    ActionCategory,
    ActionHistoryDB,
    action_history,
)
from .undo_manager import (
    Checkpoint,
    UndoType,
    UndoStatus,
    UndoManager,
    undo_manager,
)

__all__ = [
    'TrustLevel',
    'TrustLevelManager',
    'trust_manager',
    'PendingAction',
    'ActionStatus',
    'ApprovalGateway',
    'approval_gateway',
    'ActionRecord',
    'HistoryActionStatus',
    'ActionCategory',
    'ActionHistoryDB',
    'action_history',
    'Checkpoint',
    'UndoType',
    'UndoStatus',
    'UndoManager',
    'undo_manager',
]
