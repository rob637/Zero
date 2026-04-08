"""
Connector Template - OAuth Provider

Copy this file to create a new OAuth-based connector.

Steps:
1. Copy this file to `connectors/{service_name}.py`
2. Replace all TEMPLATE markers with your service specifics
3. Implement the operations for your service's API
4. Register in connectors/__init__.py
5. Add to setup UI

Usage:
    from connectors.example import ExampleConnector
    
    conn = ExampleConnector()
    await conn.connect(access_token="...")
    
    results = await conn.list_items()
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from .base import (
    ConnectorHealth,
    ConnectorStatus,
    AuthType,
    ProviderType,
)

logger = logging.getLogger(__name__)


# =============================================================================
# TEMPLATE: Change these values
# =============================================================================

CONNECTOR_NAME = "example"          # Unique ID: "gmail", "outlook", "slack"
CONNECTOR_DISPLAY = "Example"       # Human name: "Gmail", "Outlook", "Slack"
PROVIDER = ProviderType.CUSTOM      # ProviderType.GOOGLE, .MICROSOFT, .SLACK, etc.
API_BASE_URL = "https://api.example.com/v1"

# Primitives this connector supports
PRIMITIVES = ["EMAIL", "MESSAGE"]   # ["EMAIL"], ["CALENDAR"], ["FILES"], ["TASK"], etc.

# OAuth scopes required
SCOPES = [
    "read",
    "write",
]


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class ExampleItem:
    """
    Data model for items from this service.
    
    TEMPLATE: Replace with your service's data model.
    Examples: Email, CalendarEvent, File, Task, Message, Contact
    """
    id: str
    title: str
    content: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_api(cls, data: Dict) -> "ExampleItem":
        """Parse API response into dataclass."""
        return cls(
            id=data.get("id", ""),
            title=data.get("title", data.get("name", "")),
            content=data.get("content", data.get("body", "")),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None,
            metadata=data,
        )
    
    def to_dict(self) -> Dict:
        """Convert to JSON-serializable dict."""
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# =============================================================================
# Connector Implementation
# =============================================================================

class ExampleConnector:
    """
    Connector for Example Service.
    
    TEMPLATE: Replace with your service name and description.
    
    Capabilities:
    - List items
    - Get item details
    - Create items
    - Update items
    - Delete items
    - Search items
    """
    
    # Metadata (used by registry)
    name = CONNECTOR_NAME
    display_name = CONNECTOR_DISPLAY
    provider = PROVIDER
    primitives = PRIMITIVES
    scopes = SCOPES
    auth_type = AuthType.OAUTH2
    
    def __init__(self):
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._http_client: Optional[httpx.AsyncClient] = None
        self._user_info: Optional[Dict] = None
    
    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------
    
    async def connect(
        self,
        access_token: str,
        refresh_token: Optional[str] = None,
    ) -> bool:
        """
        Connect to the service.
        
        Args:
            access_token: OAuth access token
            refresh_token: Optional refresh token for auto-renewal
            
        Returns:
            True if connected successfully
        """
        self._access_token = access_token
        self._refresh_token = refresh_token
        
        # Create HTTP client with auth header
        self._http_client = httpx.AsyncClient(
            base_url=API_BASE_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        
        # Verify connection by fetching user info
        try:
            self._user_info = await self._get_user_info()
            logger.info(f"[{CONNECTOR_NAME}] Connected as {self._user_info}")
            return True
        except Exception as e:
            logger.error(f"[{CONNECTOR_NAME}] Connection failed: {e}")
            return False
    
    async def disconnect(self) -> None:
        """Disconnect and clean up."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        self._access_token = None
        self._refresh_token = None
        self._user_info = None
    
    async def health_check(self) -> ConnectorHealth:
        """Check connection health."""
        if not self._http_client:
            return ConnectorHealth.DISCONNECTED
        
        try:
            # TEMPLATE: Replace with a lightweight API call
            response = await self._http_client.get("/me")
            if response.status_code == 200:
                return ConnectorHealth.HEALTHY
            elif response.status_code == 401:
                return ConnectorHealth.AUTH_REQUIRED
            else:
                return ConnectorHealth.UNHEALTHY
        except Exception:
            return ConnectorHealth.UNHEALTHY
    
    @property
    def connected(self) -> bool:
        return self._http_client is not None
    
    @property
    def status(self) -> ConnectorStatus:
        return ConnectorStatus(
            connected=self.connected,
            health=ConnectorHealth.HEALTHY if self.connected else ConnectorHealth.DISCONNECTED,
            user=self._user_info.get("email") if self._user_info else None,
        )
    
    # -------------------------------------------------------------------------
    # Internal Helpers
    # -------------------------------------------------------------------------
    
    async def _get_user_info(self) -> Dict:
        """
        Fetch current user info from API.
        
        TEMPLATE: Replace with your service's user info endpoint.
        """
        response = await self._http_client.get("/me")
        response.raise_for_status()
        return response.json()
    
    async def _request(
        self,
        method: str,
        path: str,
        **kwargs,
    ) -> httpx.Response:
        """
        Make an API request with error handling.
        
        Handles:
        - Rate limiting (429)
        - Token refresh (401)
        - Retries
        """
        if not self._http_client:
            raise RuntimeError(f"{CONNECTOR_NAME} not connected")
        
        response = await self._http_client.request(method, path, **kwargs)
        
        # Handle 401 - token expired
        if response.status_code == 401 and self._refresh_token:
            # TODO: Refresh token via broker
            pass
        
        # Handle 429 - rate limited
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", "5"))
            logger.warning(f"Rate limited, waiting {retry_after}s")
            await asyncio.sleep(retry_after)
            return await self._request(method, path, **kwargs)
        
        return response
    
    # -------------------------------------------------------------------------
    # Operations
    # -------------------------------------------------------------------------
    
    async def list_items(
        self,
        limit: int = 50,
        page_token: Optional[str] = None,
    ) -> List[ExampleItem]:
        """
        List items from the service.
        
        TEMPLATE: Replace with your service's list endpoint.
        """
        params = {"limit": limit}
        if page_token:
            params["page_token"] = page_token
        
        response = await self._request("GET", "/items", params=params)
        response.raise_for_status()
        
        data = response.json()
        items = data.get("items", data.get("data", []))
        
        return [ExampleItem.from_api(item) for item in items]
    
    async def get_item(self, item_id: str) -> Optional[ExampleItem]:
        """
        Get a single item by ID.
        
        TEMPLATE: Replace with your service's get endpoint.
        """
        response = await self._request("GET", f"/items/{item_id}")
        
        if response.status_code == 404:
            return None
        
        response.raise_for_status()
        return ExampleItem.from_api(response.json())
    
    async def create_item(
        self,
        title: str,
        content: Optional[str] = None,
        **kwargs,
    ) -> ExampleItem:
        """
        Create a new item.
        
        TEMPLATE: Replace with your service's create endpoint.
        """
        payload = {
            "title": title,
            "content": content,
            **kwargs,
        }
        
        response = await self._request("POST", "/items", json=payload)
        response.raise_for_status()
        
        return ExampleItem.from_api(response.json())
    
    async def update_item(
        self,
        item_id: str,
        **updates,
    ) -> ExampleItem:
        """
        Update an existing item.
        
        TEMPLATE: Replace with your service's update endpoint.
        """
        response = await self._request("PATCH", f"/items/{item_id}", json=updates)
        response.raise_for_status()
        
        return ExampleItem.from_api(response.json())
    
    async def delete_item(self, item_id: str) -> bool:
        """
        Delete an item.
        
        TEMPLATE: Replace with your service's delete endpoint.
        """
        response = await self._request("DELETE", f"/items/{item_id}")
        return response.status_code in (200, 204)
    
    async def search(
        self,
        query: str,
        limit: int = 20,
    ) -> List[ExampleItem]:
        """
        Search for items.
        
        TEMPLATE: Replace with your service's search endpoint.
        """
        response = await self._request(
            "GET",
            "/items/search",
            params={"q": query, "limit": limit},
        )
        response.raise_for_status()
        
        data = response.json()
        items = data.get("items", data.get("results", []))
        
        return [ExampleItem.from_api(item) for item in items]


# =============================================================================
# Primitive Adapter
# =============================================================================

class ExamplePrimitive:
    """
    Adapts the connector to the primitive interface.
    
    This allows the connector to be used via the engine's primitive system.
    
    TEMPLATE: Map your connector methods to primitive operations.
    """
    
    def __init__(self, connector: ExampleConnector):
        self._connector = connector
    
    @property
    def name(self) -> str:
        # Return the primary primitive this connector implements
        return PRIMITIVES[0] if PRIMITIVES else "EXAMPLE"
    
    def get_operations(self) -> Dict[str, str]:
        """Return available operations."""
        return {
            "list": "List items",
            "get": "Get item by ID",
            "create": "Create new item",
            "update": "Update existing item",
            "delete": "Delete item",
            "search": "Search items",
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> Dict:
        """Execute a primitive operation."""
        try:
            if operation == "list":
                items = await self._connector.list_items(
                    limit=params.get("limit", 50),
                )
                return {"success": True, "data": [i.to_dict() for i in items]}
            
            elif operation == "get":
                item = await self._connector.get_item(params["id"])
                if item:
                    return {"success": True, "data": item.to_dict()}
                return {"success": False, "error": "Item not found"}
            
            elif operation == "create":
                item = await self._connector.create_item(
                    title=params.get("title", ""),
                    content=params.get("content"),
                    **{k: v for k, v in params.items() if k not in ("title", "content")},
                )
                return {"success": True, "data": item.to_dict()}
            
            elif operation == "update":
                item = await self._connector.update_item(
                    params["id"],
                    **{k: v for k, v in params.items() if k != "id"},
                )
                return {"success": True, "data": item.to_dict()}
            
            elif operation == "delete":
                success = await self._connector.delete_item(params["id"])
                return {"success": success}
            
            elif operation == "search":
                items = await self._connector.search(
                    query=params.get("query", ""),
                    limit=params.get("limit", 20),
                )
                return {"success": True, "data": [i.to_dict() for i in items]}
            
            else:
                return {"success": False, "error": f"Unknown operation: {operation}"}
                
        except Exception as e:
            logger.error(f"[{CONNECTOR_NAME}] {operation} failed: {e}")
            return {"success": False, "error": str(e)}
