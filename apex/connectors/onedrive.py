"""
OneDrive Connector (Microsoft Graph API)

Full Microsoft OneDrive cloud storage integration:
- List and search files/folders
- Upload/download files
- Create folders
- Move/copy/delete items
- Share files and folders
- Sync status

Usage:
    from connectors.onedrive import OneDriveConnector
    
    drive = OneDriveConnector()
    await drive.connect()
    
    # List files in root
    items = await drive.list_items()
    
    # Upload file
    await drive.upload_file("local/file.pdf", "/Documents/file.pdf")
    
    # Download file
    content = await drive.download_file("/Documents/file.pdf")
    
    # Search
    results = await drive.search("quarterly report")
"""

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional, Tuple, Union
import hashlib
import mimetypes

from .microsoft_graph import GraphClient, get_graph_client, GraphAPIError

import logging
logger = logging.getLogger(__name__)


# Size thresholds
SIMPLE_UPLOAD_MAX = 4 * 1024 * 1024  # 4 MB - use simple upload
LARGE_FILE_THRESHOLD = 4 * 1024 * 1024  # Above 4 MB use upload session
CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB chunks for resumable upload


@dataclass
class DriveItem:
    """Represents a file or folder in OneDrive."""
    id: str
    name: str
    path: str
    is_folder: bool
    size: int = 0
    created_datetime: Optional[datetime] = None
    modified_datetime: Optional[datetime] = None
    created_by: Optional[str] = None
    modified_by: Optional[str] = None
    mime_type: Optional[str] = None
    web_url: Optional[str] = None
    download_url: Optional[str] = None
    parent_id: Optional[str] = None
    parent_path: Optional[str] = None
    shared: bool = False
    shared_scope: Optional[str] = None
    children_count: int = 0
    quota_used: int = 0
    
    def to_dict(self) -> Dict:
        d = {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "type": "folder" if self.is_folder else "file",
            "size": self.size,
            "modified": self.modified_datetime.isoformat() if self.modified_datetime else None,
        }
        if self.web_url:
            d["web_url"] = self.web_url
        return d


@dataclass
class DriveQuota:
    """Drive storage quota information."""
    total: int
    used: int
    remaining: int
    deleted: int
    state: str  # normal, nearing, critical, exceeded
    
    @property
    def used_percent(self) -> float:
        return (self.used / self.total * 100) if self.total else 0


class OneDriveConnector:
    """
    Microsoft OneDrive connector via Graph API.
    
    Provides full cloud storage functionality:
    - List, search, navigate files and folders
    - Upload/download with resumable support
    - Create, move, copy, delete items
    - Share files and manage permissions
    """
    
    def __init__(self, client: Optional[GraphClient] = None):
        self._client = client or get_graph_client()
        self._connected = False
        self._drive_id: Optional[str] = None
    
    async def connect(self) -> bool:
        """Connect to OneDrive via Microsoft Graph API."""
        if not self._client.connected:
            success = await self._client.connect(['files'])
            if not success:
                return False
        
        try:
            # Get user's default drive
            drive = await self._client.get("/me/drive", scopes=['files'])
            self._drive_id = drive.get('id')
            self._connected = True
            return True
        except GraphAPIError as e:
            logger.error(f"Failed to connect to OneDrive: {e}")
            return False
    
    @property
    def connected(self) -> bool:
        return self._connected
    
    @property
    def drive_id(self) -> Optional[str]:
        return self._drive_id
    
    def _parse_datetime(self, dt_str: str) -> Optional[datetime]:
        """Parse ISO datetime string."""
        if not dt_str:
            return None
        try:
            return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        except:
            return None
    
    def _parse_item(self, item: Dict) -> DriveItem:
        """Parse Graph API item into DriveItem."""
        is_folder = 'folder' in item
        
        parent_ref = item.get('parentReference', {})
        parent_path = parent_ref.get('path', '')
        # Path format: /drive/root:/path/to/parent
        if ':/root:' in parent_path:
            parent_path = parent_path.split(':/root:')[-1]
        elif ':/' in parent_path:
            parent_path = parent_path.split(':/')[-1]
        
        # Build full path
        name = item.get('name', '')
        full_path = f"{parent_path}/{name}".replace('//', '/')
        if not full_path.startswith('/'):
            full_path = '/' + full_path
        
        # Created/modified by
        created_by = None
        modified_by = None
        if 'createdBy' in item:
            user = item['createdBy'].get('user', {})
            created_by = user.get('displayName') or user.get('email')
        if 'lastModifiedBy' in item:
            user = item['lastModifiedBy'].get('user', {})
            modified_by = user.get('displayName') or user.get('email')
        
        # File info
        file_info = item.get('file', {})
        
        # Sharing info
        shared = 'shared' in item
        shared_scope = None
        if shared:
            shared_scope = item['shared'].get('scope')
        
        return DriveItem(
            id=item.get('id', ''),
            name=name,
            path=full_path,
            is_folder=is_folder,
            size=item.get('size', 0),
            created_datetime=self._parse_datetime(item.get('createdDateTime')),
            modified_datetime=self._parse_datetime(item.get('lastModifiedDateTime')),
            created_by=created_by,
            modified_by=modified_by,
            mime_type=file_info.get('mimeType'),
            web_url=item.get('webUrl'),
            download_url=item.get('@microsoft.graph.downloadUrl'),
            parent_id=parent_ref.get('id'),
            parent_path=parent_path,
            shared=shared,
            shared_scope=shared_scope,
            children_count=item.get('folder', {}).get('childCount', 0),
        )
    
    async def get_quota(self) -> DriveQuota:
        """Get drive storage quota information."""
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        drive = await self._client.get("/me/drive", scopes=['files'])
        quota = drive.get('quota', {})
        
        return DriveQuota(
            total=quota.get('total', 0),
            used=quota.get('used', 0),
            remaining=quota.get('remaining', 0),
            deleted=quota.get('deleted', 0),
            state=quota.get('state', 'normal'),
        )
    
    async def list_items(
        self,
        path: str = "/",
        max_results: int = 100,
        include_children: bool = True,
    ) -> List[DriveItem]:
        """
        List items in a folder.
        
        Args:
            path: Folder path (e.g., "/Documents", "/")
            max_results: Maximum items to return
            include_children: Include child item count for folders
        
        Returns:
            List of DriveItem objects
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        # Build endpoint
        if path == "/" or path == "":
            endpoint = "/me/drive/root/children"
        else:
            # URL encode the path properly
            clean_path = path.strip('/').replace(' ', '%20')
            endpoint = f"/me/drive/root:/{clean_path}:/children"
        
        params = {
            '$top': max_results,
            '$orderby': 'name asc',
            '$select': 'id,name,size,createdDateTime,lastModifiedDateTime,'
                      'createdBy,lastModifiedBy,file,folder,parentReference,'
                      'webUrl,shared',
        }
        
        result = await self._client.get(endpoint, params=params, scopes=['files'])
        return [self._parse_item(item) for item in result.get('value', [])]
    
    async def get_item(self, path: str = None, item_id: str = None) -> DriveItem:
        """
        Get a single item by path or ID.
        
        Args:
            path: Item path (e.g., "/Documents/report.pdf")
            item_id: Item ID (alternative to path)
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        if item_id:
            endpoint = f"/me/drive/items/{item_id}"
        elif path:
            clean_path = path.strip('/').replace(' ', '%20')
            if clean_path:
                endpoint = f"/me/drive/root:/{clean_path}"
            else:
                endpoint = "/me/drive/root"
        else:
            raise ValueError("Either path or item_id must be provided")
        
        params = {
            '$select': 'id,name,size,createdDateTime,lastModifiedDateTime,'
                      'createdBy,lastModifiedBy,file,folder,parentReference,'
                      'webUrl,shared,@microsoft.graph.downloadUrl',
        }
        
        result = await self._client.get(endpoint, params=params, scopes=['files'])
        return self._parse_item(result)
    
    async def search(
        self,
        query: str,
        max_results: int = 50,
    ) -> List[DriveItem]:
        """
        Search for files and folders.
        
        Args:
            query: Search query (searches filenames and content)
            max_results: Maximum results
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        params = {
            '$top': max_results,
            '$select': 'id,name,size,createdDateTime,lastModifiedDateTime,'
                      'file,folder,parentReference,webUrl',
        }
        
        # Use search endpoint
        result = await self._client.get(
            f"/me/drive/root/search(q='{query}')",
            params=params,
            scopes=['files'],
        )
        
        return [self._parse_item(item) for item in result.get('value', [])]
    
    async def download_file(
        self,
        path: str = None,
        item_id: str = None,
    ) -> bytes:
        """
        Download a file's content.
        
        Args:
            path: File path
            item_id: File ID (alternative to path)
        
        Returns:
            File content as bytes
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        # First get the item to get download URL
        item = await self.get_item(path=path, item_id=item_id)
        
        if item.is_folder:
            raise ValueError("Cannot download a folder")
        
        # Use download URL if available
        if item.download_url:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get(item.download_url)
                response.raise_for_status()
                return response.content
        
        # Otherwise use content endpoint
        if item_id:
            endpoint = f"/me/drive/items/{item_id}/content"
        else:
            clean_path = path.strip('/').replace(' ', '%20')
            endpoint = f"/me/drive/root:/{clean_path}:/content"
        
        # Get raw content
        return await self._client.get_raw(endpoint, scopes=['files'])
    
    async def download_to_file(
        self,
        remote_path: str = None,
        item_id: str = None,
        local_path: str = None,
    ) -> str:
        """
        Download a file to local filesystem.
        
        Args:
            remote_path: OneDrive file path
            item_id: File ID (alternative to path)
            local_path: Local destination path (optional, uses filename from OneDrive)
        
        Returns:
            Local file path
        """
        item = await self.get_item(path=remote_path, item_id=item_id)
        
        if not local_path:
            local_path = item.name
        
        content = await self.download_file(path=remote_path, item_id=item_id)
        
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        with open(local_path, 'wb') as f:
            f.write(content)
        
        return local_path
    
    async def upload_file(
        self,
        local_path: str,
        remote_path: str,
        conflict_behavior: str = "rename",  # rename, replace, fail
    ) -> DriveItem:
        """
        Upload a file to OneDrive.
        
        Uses simple upload for files <= 4MB, resumable upload for larger files.
        
        Args:
            local_path: Path to local file
            remote_path: Destination path in OneDrive (e.g., "/Documents/file.pdf")
            conflict_behavior: What to do if file exists (rename, replace, fail)
        
        Returns:
            Created DriveItem
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        path = Path(local_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {local_path}")
        
        file_size = path.stat().st_size
        
        if file_size <= SIMPLE_UPLOAD_MAX:
            return await self._simple_upload(path, remote_path, conflict_behavior)
        else:
            return await self._resumable_upload(path, remote_path, conflict_behavior)
    
    async def _simple_upload(
        self,
        local_path: Path,
        remote_path: str,
        conflict_behavior: str,
    ) -> DriveItem:
        """Simple upload for small files (< 4MB)."""
        clean_path = remote_path.strip('/').replace(' ', '%20')
        endpoint = f"/me/drive/root:/{clean_path}:/content"
        
        params = {'@microsoft.graph.conflictBehavior': conflict_behavior}
        
        with open(local_path, 'rb') as f:
            content = f.read()
        
        # Determine content type
        mime_type, _ = mimetypes.guess_type(str(local_path))
        if not mime_type:
            mime_type = 'application/octet-stream'
        
        result = await self._client.put(
            endpoint,
            content=content,
            content_type=mime_type,
            params=params,
            scopes=['files'],
        )
        
        return self._parse_item(result)
    
    async def _resumable_upload(
        self,
        local_path: Path,
        remote_path: str,
        conflict_behavior: str,
    ) -> DriveItem:
        """Resumable upload for large files (> 4MB)."""
        clean_path = remote_path.strip('/').replace(' ', '%20')
        
        # Create upload session
        session_url = f"/me/drive/root:/{clean_path}:/createUploadSession"
        
        session_data = {
            "item": {
                "@microsoft.graph.conflictBehavior": conflict_behavior,
            }
        }
        
        session = await self._client.post(session_url, json_data=session_data, scopes=['files'])
        upload_url = session.get('uploadUrl')
        
        if not upload_url:
            raise GraphAPIError("Failed to create upload session")
        
        # Upload in chunks
        import httpx
        
        file_size = local_path.stat().st_size
        
        async with httpx.AsyncClient(timeout=300) as client:
            with open(local_path, 'rb') as f:
                offset = 0
                while offset < file_size:
                    chunk = f.read(CHUNK_SIZE)
                    chunk_size = len(chunk)
                    end_byte = offset + chunk_size - 1
                    
                    headers = {
                        'Content-Length': str(chunk_size),
                        'Content-Range': f'bytes {offset}-{end_byte}/{file_size}',
                    }
                    
                    response = await client.put(upload_url, content=chunk, headers=headers)
                    
                    if response.status_code == 200 or response.status_code == 201:
                        # Upload complete
                        return self._parse_item(response.json())
                    elif response.status_code == 202:
                        # More chunks needed
                        offset += chunk_size
                    else:
                        raise GraphAPIError(f"Upload failed: {response.status_code}")
        
        raise GraphAPIError("Upload did not complete successfully")
    
    async def upload_content(
        self,
        content: bytes,
        remote_path: str,
        conflict_behavior: str = "rename",
    ) -> DriveItem:
        """
        Upload content directly to OneDrive.
        
        Args:
            content: File content as bytes
            remote_path: Destination path
            conflict_behavior: rename, replace, or fail
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        clean_path = remote_path.strip('/').replace(' ', '%20')
        endpoint = f"/me/drive/root:/{clean_path}:/content"
        
        params = {'@microsoft.graph.conflictBehavior': conflict_behavior}
        
        result = await self._client.put(
            endpoint,
            content=content,
            content_type='application/octet-stream',
            params=params,
            scopes=['files'],
        )
        
        return self._parse_item(result)
    
    async def create_folder(self, path: str, name: str) -> DriveItem:
        """
        Create a new folder.
        
        Args:
            path: Parent folder path (e.g., "/Documents")
            name: New folder name
        
        Returns:
            Created DriveItem
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        if path == "/" or path == "":
            endpoint = "/me/drive/root/children"
        else:
            clean_path = path.strip('/').replace(' ', '%20')
            endpoint = f"/me/drive/root:/{clean_path}:/children"
        
        folder_data = {
            "name": name,
            "folder": {},
            "@microsoft.graph.conflictBehavior": "fail",
        }
        
        result = await self._client.post(endpoint, json_data=folder_data, scopes=['files'])
        return self._parse_item(result)
    
    async def delete_item(self, path: str = None, item_id: str = None) -> bool:
        """
        Delete a file or folder.
        
        Args:
            path: Item path
            item_id: Item ID (alternative to path)
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        if item_id:
            endpoint = f"/me/drive/items/{item_id}"
        elif path:
            clean_path = path.strip('/').replace(' ', '%20')
            endpoint = f"/me/drive/root:/{clean_path}"
        else:
            raise ValueError("Either path or item_id must be provided")
        
        await self._client.delete(endpoint, scopes=['files'])
        return True
    
    async def move_item(
        self,
        source_path: str = None,
        source_id: str = None,
        dest_folder_path: str = None,
        dest_folder_id: str = None,
        new_name: str = None,
    ) -> DriveItem:
        """
        Move or rename a file/folder.
        
        Args:
            source_path: Source item path
            source_id: Source item ID
            dest_folder_path: Destination folder path
            dest_folder_id: Destination folder ID
            new_name: New name (for rename)
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        # Get source item ID if needed
        if not source_id:
            item = await self.get_item(path=source_path)
            source_id = item.id
        
        update = {}
        
        # Set new parent
        if dest_folder_path or dest_folder_id:
            if dest_folder_id:
                update["parentReference"] = {"id": dest_folder_id}
            else:
                dest_item = await self.get_item(path=dest_folder_path)
                update["parentReference"] = {"id": dest_item.id}
        
        # Set new name
        if new_name:
            update["name"] = new_name
        
        result = await self._client.patch(
            f"/me/drive/items/{source_id}",
            json_data=update,
            scopes=['files'],
        )
        
        return self._parse_item(result)
    
    async def copy_item(
        self,
        source_path: str = None,
        source_id: str = None,
        dest_folder_path: str = None,
        dest_folder_id: str = None,
        new_name: str = None,
    ) -> str:
        """
        Copy a file/folder.
        
        Note: Copy is async. Returns the monitoring URL to check status.
        
        Args:
            source_path: Source item path
            source_id: Source item ID
            dest_folder_path: Destination folder path
            dest_folder_id: Destination folder ID
            new_name: Name for the copy
        
        Returns:
            Monitor URL to check copy status
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        # Get source item if needed
        if not source_id:
            item = await self.get_item(path=source_path)
            source_id = item.id
            if not new_name:
                new_name = item.name
        
        copy_data = {}
        
        # Set destination
        if dest_folder_id:
            copy_data["parentReference"] = {"id": dest_folder_id}
        elif dest_folder_path:
            dest_item = await self.get_item(path=dest_folder_path)
            copy_data["parentReference"] = {"id": dest_item.id}
        
        if new_name:
            copy_data["name"] = new_name
        
        # Copy endpoint returns 202 Accepted with Location header
        result = await self._client.post(
            f"/me/drive/items/{source_id}/copy",
            json_data=copy_data,
            scopes=['files'],
        )
        
        # Result might have monitor URL
        return result.get('monitor_url', 'Copy initiated')
    
    async def create_share_link(
        self,
        path: str = None,
        item_id: str = None,
        link_type: str = "view",  # view, edit, embed
        scope: str = "anonymous",  # anonymous, organization
        expiration: datetime = None,
        password: str = None,
    ) -> Dict:
        """
        Create a sharing link for a file/folder.
        
        Args:
            path: Item path
            item_id: Item ID
            link_type: view (read-only), edit, or embed
            scope: anonymous (anyone) or organization (org users only)
            expiration: When link expires
            password: Optional password protection
        
        Returns:
            Dict with sharing link info
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        if not item_id:
            item = await self.get_item(path=path)
            item_id = item.id
        
        share_data = {
            "type": link_type,
            "scope": scope,
        }
        
        if expiration:
            share_data["expirationDateTime"] = expiration.isoformat()
        if password:
            share_data["password"] = password
        
        result = await self._client.post(
            f"/me/drive/items/{item_id}/createLink",
            json_data=share_data,
            scopes=['files'],
        )
        
        link = result.get('link', {})
        return {
            'url': link.get('webUrl'),
            'type': link.get('type'),
            'scope': link.get('scope'),
            'expiration': link.get('expirationDateTime'),
            'id': result.get('id'),
        }
