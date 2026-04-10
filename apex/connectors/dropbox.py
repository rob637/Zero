"""
Dropbox Connector - Cloud Storage Integration

Provides access to Dropbox for file storage, sync, and sharing
via the Dropbox HTTP API v2.

Capabilities:
- File/folder listing
- Upload and download files
- Search files
- Share links
- File metadata

Setup:
    from connectors.dropbox import DropboxConnector
    
    dropbox = DropboxConnector(access_token="...")
    await dropbox.connect()
    
    files = await dropbox.list_files("/Documents")
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class DropboxFile:
    """Dropbox file/folder entry."""
    id: str
    name: str
    path: str
    is_folder: bool
    size: int = 0
    modified: Optional[str] = None
    shared_url: Optional[str] = None

    @classmethod
    def from_api(cls, data: Dict) -> "DropboxFile":
        tag = data.get(".tag", "file")
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            path=data.get("path_display", data.get("path_lower", "")),
            is_folder=(tag == "folder"),
            size=data.get("size", 0),
            modified=data.get("server_modified"),
        )


class DropboxConnector:
    """Dropbox connector via HTTP API v2."""

    API_BASE = "https://api.dropboxapi.com/2"
    CONTENT_BASE = "https://content.dropboxapi.com/2"

    def __init__(self, access_token: Optional[str] = None):
        self._token = access_token or os.environ.get("DROPBOX_ACCESS_TOKEN", "")
        self._http = None

    async def connect(self):
        """Initialize HTTP client."""
        if not self._token:
            raise ValueError("No Dropbox access token. Set DROPBOX_ACCESS_TOKEN.")

        import httpx
        self._http = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=60,
        )

    async def _ensure_client(self):
        if not self._http:
            await self.connect()

    async def list_files(self, path: str = "", limit: int = 100) -> List[DropboxFile]:
        """List files and folders in a path. Use '' for root."""
        await self._ensure_client()
        resp = await self._http.post(
            f"{self.API_BASE}/files/list_folder",
            json={"path": path, "limit": min(limit, 2000)},
        )
        if resp.status_code == 400:
            detail = resp.text[:200] if resp.text else "no details"
            logger.error(f"Dropbox list_folder 400: {detail}")
            return []
        if resp.status_code == 401:
            logger.error("Dropbox token expired or revoked — re-authenticate via OAuth")
            return []
        resp.raise_for_status()
        entries = resp.json().get("entries", [])
        return [DropboxFile.from_api(e) for e in entries]

    async def search(self, query: str, path: str = "", limit: int = 20) -> List[DropboxFile]:
        """Search for files by name."""
        await self._ensure_client()
        body: Dict[str, Any] = {
            "query": query,
            "options": {"max_results": limit},
        }
        if path:
            body["options"]["path"] = path

        resp = await self._http.post(
            f"{self.API_BASE}/files/search_v2",
            json=body,
        )
        resp.raise_for_status()
        matches = resp.json().get("matches", [])
        return [DropboxFile.from_api(m.get("metadata", {}).get("metadata", {})) for m in matches]

    async def download(self, path: str, local_path: str) -> Dict:
        """Download a file from Dropbox."""
        await self._ensure_client()
        import json as _json
        resp = await self._http.post(
            f"{self.CONTENT_BASE}/files/download",
            headers={"Dropbox-API-Arg": _json.dumps({"path": path})},
        )
        resp.raise_for_status()

        from pathlib import Path
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(resp.content)

        return {"path": path, "local_path": local_path, "size": len(resp.content)}

    async def upload(self, local_path: str, dropbox_path: str, overwrite: bool = True) -> DropboxFile:
        """Upload a file to Dropbox."""
        await self._ensure_client()
        import json as _json
        from pathlib import Path

        with open(local_path, "rb") as f:
            data = f.read()

        mode = "overwrite" if overwrite else "add"
        resp = await self._http.post(
            f"{self.CONTENT_BASE}/files/upload",
            headers={
                "Dropbox-API-Arg": _json.dumps({
                    "path": dropbox_path,
                    "mode": mode,
                    "autorename": True,
                }),
                "Content-Type": "application/octet-stream",
            },
            content=data,
        )
        resp.raise_for_status()
        return DropboxFile.from_api(resp.json())

    async def get_metadata(self, path: str) -> DropboxFile:
        """Get metadata for a file or folder."""
        await self._ensure_client()
        resp = await self._http.post(
            f"{self.API_BASE}/files/get_metadata",
            json={"path": path},
        )
        resp.raise_for_status()
        return DropboxFile.from_api(resp.json())

    async def create_shared_link(self, path: str) -> str:
        """Create a shared link for a file."""
        await self._ensure_client()
        resp = await self._http.post(
            f"{self.API_BASE}/sharing/create_shared_link_with_settings",
            json={"path": path},
        )
        resp.raise_for_status()
        return resp.json().get("url", "")

    async def delete(self, path: str) -> bool:
        """Delete a file or folder."""
        await self._ensure_client()
        resp = await self._http.post(
            f"{self.API_BASE}/files/delete_v2",
            json={"path": path},
        )
        return resp.status_code == 200

    async def close(self):
        if self._http:
            await self._http.aclose()
            self._http = None
