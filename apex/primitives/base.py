"""Telic Engine — Base Classes"""

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


# ============================================================
#  LOCAL DATA INDEX (optional — set by server.py at startup)
# ============================================================
_data_index = None  # Will be set to an Index instance by server.py

def set_data_index(index):
    """Called by server.py to make the local index available to primitives."""
    global _data_index
    _data_index = index

def get_data_index():
    """Get the local data index (or None if not initialized)."""
    return _data_index


# ============================================================
#  RESULT TYPES
# ============================================================

@dataclass
class StepResult:
    """Result from a single step."""
    success: bool
    data: Any = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {"success": self.success, "data": self.data, "error": self.error}


# ============================================================
#  PRIMITIVE BASE
# ============================================================



# ============================================================
#  PRIMITIVE BASE
# ============================================================

class Primitive(ABC):
    """Base class for primitives."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        pass
    
    @abstractmethod
    def get_operations(self) -> Dict[str, str]:
        """Return dict of operation_name -> description."""
        pass
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        """Return param schema per operation for LLM guidance.
        
        Override to declare expected parameters so the planner and self-healer
        know the correct format. Format:
        {
            "operation_name": {
                "param_name": {"type": "str|int|float|dict|list", "required": bool, "description": "..."},
                ...
            }
        }
        """
        return {}
    
    def get_available_operations(self) -> Dict[str, str]:
        """Return operations that are actually configured and ready to use.
        
        By default, returns all operations. Override to filter out operations
        that require external providers that aren't connected.
        """
        return self.get_operations()
    
    def get_connected_providers(self) -> List[str]:
        """Return list of connected provider names for this primitive.
        
        Used to enrich tool descriptions so the LLM knows what services
        are available and can route intelligently.
        Auto-detects from _providers dict or _connector attribute.
        """
        if hasattr(self, '_providers') and self._providers:
            return list(self._providers.keys())
        if hasattr(self, '_connector') and self._connector:
            name = getattr(self._connector, 'name', None) or type(self._connector).__name__
            return [name]
        return []
    
    @abstractmethod
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        """Execute an operation."""
        pass


# ============================================================
#  FILE PRIMITIVE
# ============================================================

