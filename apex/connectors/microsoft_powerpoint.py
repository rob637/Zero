"""
Microsoft PowerPoint Online Connector

Microsoft Graph API integration for PowerPoint operations.
Manages presentations stored in OneDrive via the Graph API.

Note: The Graph API provides file-level operations for PowerPoint.
For rich slide manipulation, presentations can be managed through
OneDrive and opened in PowerPoint Online via web URLs.

Usage:
    from connectors.microsoft_powerpoint import PowerPointConnector
    
    pptx = PowerPointConnector()
    await pptx.connect()
    
    # Create presentation
    pres = await pptx.create_presentation("Q1 Report")
    
    # List presentations
    files = await pptx.list_presentations()
    
    # Get shareable link
    link = await pptx.get_share_link(item_id)
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .microsoft_graph import GraphClient, get_graph_client, GraphAPIError

logger = logging.getLogger(__name__)

# Required scopes
POWERPOINT_SCOPES = ['Files.ReadWrite']

# MIME type for PowerPoint files
PPTX_MIME = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'


@dataclass
class Presentation:
    """Represents a PowerPoint presentation stored in OneDrive."""
    id: str
    name: str
    web_url: Optional[str] = None
    size: Optional[int] = None
    created: Optional[str] = None
    modified: Optional[str] = None
    slide_count: Optional[int] = None

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "url": self.web_url,
            "size": self.size,
            "created": self.created,
            "modified": self.modified,
            "slide_count": self.slide_count,
        }


class PowerPointConnector:
    """
    Microsoft PowerPoint Online connector via Graph API.
    
    Provides methods for:
    - Creating and managing presentations in OneDrive
    - Listing and searching presentation files
    - Downloading/exporting presentations (PDF, PPTX)
    - Sharing presentations with collaboration links
    - Getting presentation metadata
    
    Presentations are stored as .pptx files in OneDrive and can be
    edited in PowerPoint Online via the web URL.
    """

    def __init__(self, client: Optional[GraphClient] = None):
        self._client = client or get_graph_client()

    async def connect(self) -> bool:
        """Connect to Microsoft Graph API."""
        if not self._client.connected:
            return await self._client.connect(scopes=POWERPOINT_SCOPES)
        return True

    @property
    def connected(self) -> bool:
        return self._client.connected

    def _ensure_connected(self):
        if not self._client.connected:
            raise RuntimeError("Not connected. Call connect() first.")

    def _parse_presentation(self, data: Dict) -> Presentation:
        """Parse a Drive item into a Presentation."""
        return Presentation(
            id=data.get("id", ""),
            name=data.get("name", ""),
            web_url=data.get("webUrl"),
            size=data.get("size"),
            created=data.get("createdDateTime"),
            modified=data.get("lastModifiedDateTime"),
        )

    # === Presentation Management ===

    async def create_presentation(
        self,
        name: str,
        folder_path: str = "/",
    ) -> Presentation:
        """
        Create a new empty PowerPoint presentation in OneDrive.
        
        Args:
            name: Filename (should end in .pptx)
            folder_path: OneDrive folder path (default: root)
        
        Returns:
            Created Presentation object
        """
        self._ensure_connected()

        if not name.endswith('.pptx'):
            name += '.pptx'

        path = f"{folder_path.rstrip('/')}/{name}" if folder_path != "/" else name
        endpoint = f"/me/drive/root:/{path}:/content"

        result = await self._client.put(
            endpoint,
            content=b'',
            content_type=PPTX_MIME,
        )

        return self._parse_presentation(result)

    async def get_presentation(self, item_id: str) -> Presentation:
        """
        Get presentation metadata.
        
        Args:
            item_id: OneDrive item ID
        
        Returns:
            Presentation object
        """
        self._ensure_connected()

        result = await self._client.get(f"/me/drive/items/{item_id}")
        return self._parse_presentation(result)

    async def list_presentations(
        self,
        folder_path: str = None,
        limit: int = 25,
    ) -> List[Presentation]:
        """
        List PowerPoint presentations in OneDrive.
        
        Args:
            folder_path: Optional folder path to search in
            limit: Max results
        
        Returns:
            List of Presentation objects
        """
        self._ensure_connected()

        # Search for .pptx files
        result = await self._client.get(
            "/me/drive/root/search(q='.pptx')",
            params={"$top": limit},
        )

        presentations = []
        for item in result.get("value", []):
            name = item.get("name", "")
            if name.endswith('.pptx'):
                presentations.append(self._parse_presentation(item))

        return presentations

    async def search_presentations(
        self,
        query: str,
        limit: int = 25,
    ) -> List[Presentation]:
        """
        Search for presentations by name or content.
        
        Args:
            query: Search query
            limit: Max results
        
        Returns:
            List of matching Presentation objects
        """
        self._ensure_connected()

        result = await self._client.get(
            f"/me/drive/root/search(q='{query}')",
            params={"$top": limit},
        )

        presentations = []
        for item in result.get("value", []):
            name = item.get("name", "")
            if name.endswith('.pptx') or name.endswith('.ppt'):
                presentations.append(self._parse_presentation(item))

        return presentations

    # === File Operations ===

    async def download(self, item_id: str) -> bytes:
        """
        Download presentation file content.
        
        Args:
            item_id: OneDrive item ID
        
        Returns:
            Raw file bytes
        """
        self._ensure_connected()

        return await self._client.get_raw(
            f"/me/drive/items/{item_id}/content"
        )

    async def export_pdf(self, item_id: str) -> bytes:
        """
        Export presentation as PDF.
        
        Args:
            item_id: OneDrive item ID
        
        Returns:
            PDF file bytes
        """
        self._ensure_connected()

        return await self._client.get_raw(
            f"/me/drive/items/{item_id}/content",
            params={"format": "pdf"},
        )

    async def upload_presentation(
        self,
        name: str,
        content: bytes,
        folder_path: str = "/",
    ) -> Presentation:
        """
        Upload a .pptx file to OneDrive.
        
        Args:
            name: Filename
            content: File content bytes
            folder_path: Target folder path
        
        Returns:
            Created Presentation object
        """
        self._ensure_connected()

        if not name.endswith('.pptx'):
            name += '.pptx'

        path = f"{folder_path.rstrip('/')}/{name}" if folder_path != "/" else name
        endpoint = f"/me/drive/root:/{path}:/content"

        result = await self._client.put(
            endpoint,
            content=content,
            content_type=PPTX_MIME,
        )

        return self._parse_presentation(result)

    # === Sharing ===

    async def get_share_link(
        self,
        item_id: str,
        link_type: str = "edit",
        scope: str = "anonymous",
    ) -> str:
        """
        Create a sharing link for the presentation.
        
        Args:
            item_id: OneDrive item ID
            link_type: "view" or "edit"
            scope: "anonymous", "organization", or "users"
        
        Returns:
            Sharing URL
        """
        self._ensure_connected()

        result = await self._client.post(
            f"/me/drive/items/{item_id}/createLink",
            json_data={
                "type": link_type,
                "scope": scope,
            },
        )

        return result.get("link", {}).get("webUrl", "")

    async def copy_presentation(
        self,
        item_id: str,
        new_name: str,
        folder_id: str = None,
    ) -> Dict:
        """
        Copy a presentation.
        
        Args:
            item_id: Source item ID
            new_name: Name for the copy
            folder_id: Destination folder ID (None = same folder)
        
        Returns:
            Copy operation info
        """
        self._ensure_connected()

        body = {"name": new_name}
        if folder_id:
            body["parentReference"] = {"id": folder_id}

        result = await self._client.post(
            f"/me/drive/items/{item_id}/copy",
            json_data=body,
        )

        return result

    async def delete_presentation(self, item_id: str) -> bool:
        """
        Delete a presentation from OneDrive.
        
        Args:
            item_id: OneDrive item ID
        
        Returns:
            True if deleted
        """
        self._ensure_connected()

        await self._client.delete(f"/me/drive/items/{item_id}")
        return True

    # === Properties ===

    async def get_thumbnails(self, item_id: str) -> List[Dict]:
        """
        Get thumbnail images for presentation slides.
        
        Args:
            item_id: OneDrive item ID
        
        Returns:
            List of thumbnail info dicts with URLs
        """
        self._ensure_connected()

        result = await self._client.get(
            f"/me/drive/items/{item_id}/thumbnails"
        )

        return [
            {
                "id": t.get("id", ""),
                "small": t.get("small", {}).get("url"),
                "medium": t.get("medium", {}).get("url"),
                "large": t.get("large", {}).get("url"),
            }
            for t in result.get("value", [])
        ]

    async def close(self):
        """Close the connector."""
        pass
