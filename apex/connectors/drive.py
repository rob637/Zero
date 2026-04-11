"""
Google Drive Connector

Real Google Drive API integration for file operations.

Usage:
    from connectors.drive import DriveConnector
    
    drive = DriveConnector()
    await drive.connect()
    
    # List files
    files = await drive.list_files(query="name contains 'report'")
    
    # Download file
    content = await drive.download_file(file_id)
    
    # Upload file  
    await drive.upload_file("~/document.pdf", folder_id="...")
"""

import asyncio
import io
import mimetypes
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, BinaryIO

from .google_auth import GoogleAuth, get_google_auth

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
    HAS_GOOGLE_API = True
except ImportError:
    HAS_GOOGLE_API = False


# MIME type mappings
GOOGLE_MIME_TYPES = {
    'document': 'application/vnd.google-apps.document',
    'spreadsheet': 'application/vnd.google-apps.spreadsheet',
    'presentation': 'application/vnd.google-apps.presentation',
    'folder': 'application/vnd.google-apps.folder',
    'form': 'application/vnd.google-apps.form',
    'drawing': 'application/vnd.google-apps.drawing',
}

EXPORT_FORMATS = {
    'application/vnd.google-apps.document': {
        'pdf': 'application/pdf',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'txt': 'text/plain',
        'html': 'text/html',
    },
    'application/vnd.google-apps.spreadsheet': {
        'pdf': 'application/pdf',
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'csv': 'text/csv',
    },
    'application/vnd.google-apps.presentation': {
        'pdf': 'application/pdf',
        'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    },
}


@dataclass
class DriveFile:
    """Represents a Google Drive file."""
    id: str
    name: str
    mime_type: str
    size: Optional[int]
    created_time: Optional[datetime]
    modified_time: Optional[datetime]
    parents: List[str]
    web_view_link: Optional[str] = None
    web_content_link: Optional[str] = None
    owners: List[Dict] = None
    shared: bool = False
    starred: bool = False
    trashed: bool = False
    
    @property
    def is_folder(self) -> bool:
        return self.mime_type == GOOGLE_MIME_TYPES['folder']
    
    @property
    def is_google_doc(self) -> bool:
        return self.mime_type.startswith('application/vnd.google-apps.')
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "mime_type": self.mime_type,
            "size": self.size,
            "modified": self.modified_time.isoformat() if self.modified_time else None,
            "web_link": self.web_view_link,
            "is_folder": self.is_folder,
        }


class DriveConnector:
    """
    Google Drive API connector.
    
    Provides methods for:
    - Listing and searching files
    - Downloading and uploading files
    - Creating folders
    - Managing permissions
    """
    
    def __init__(self, auth: Optional[GoogleAuth] = None):
        self._auth = auth or get_google_auth()
        self._service = None
    
    async def connect(self) -> bool:
        """Connect to Google Drive API."""
        if not HAS_GOOGLE_API:
            raise ImportError(
                "Google API client not installed. Run:\n"
                "pip install google-api-python-client"
            )
        
        creds = await self._auth.get_credentials(['drive'])
        if not creds:
            return False
        
        self._service = await asyncio.to_thread(
            build, 'drive', 'v3', credentials=creds
        )
        
        return True
    
    @property
    def connected(self) -> bool:
        return self._service is not None
    
    def _parse_file(self, file_data: Dict) -> DriveFile:
        """Parse Drive API file into DriveFile."""
        created = file_data.get('createdTime')
        modified = file_data.get('modifiedTime')
        
        return DriveFile(
            id=file_data['id'],
            name=file_data.get('name', ''),
            mime_type=file_data.get('mimeType', ''),
            size=int(file_data['size']) if file_data.get('size') else None,
            created_time=datetime.fromisoformat(created.replace('Z', '+00:00')) if created else None,
            modified_time=datetime.fromisoformat(modified.replace('Z', '+00:00')) if modified else None,
            parents=file_data.get('parents', []),
            web_view_link=file_data.get('webViewLink'),
            web_content_link=file_data.get('webContentLink'),
            owners=file_data.get('owners', []),
            shared=file_data.get('shared', False),
            starred=file_data.get('starred', False),
            trashed=file_data.get('trashed', False),
        )
    
    async def list_files(
        self,
        query: str = None,
        folder_id: str = None,
        mime_type: str = None,
        max_results: int = 50,
        order_by: str = 'modifiedTime desc',
        include_trashed: bool = False,
    ) -> List[DriveFile]:
        """
        List files in Google Drive.
        
        Args:
            query: Drive search query
            folder_id: Filter by parent folder
            mime_type: Filter by MIME type (or shorthand: 'folder', 'document', etc.)
            max_results: Maximum files to return
            order_by: Sort order
            include_trashed: Include trashed files
        
        Returns:
            List of DriveFile objects
        """
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
        
        # Build query
        q_parts = []
        
        if query:
            q_parts.append(query)
        
        if folder_id:
            q_parts.append(f"'{folder_id}' in parents")
        
        if mime_type:
            # Convert shorthand to full MIME type
            if mime_type in GOOGLE_MIME_TYPES:
                mime_type = GOOGLE_MIME_TYPES[mime_type]
            q_parts.append(f"mimeType = '{mime_type}'")
        
        if not include_trashed:
            q_parts.append("trashed = false")
        
        q = " and ".join(q_parts) if q_parts else None
        
        try:
            request = self._service.files().list(
                q=q,
                pageSize=max_results,
                orderBy=order_by,
                fields="files(id, name, mimeType, size, modifiedTime, parents, webViewLink)",
            )
            result = await asyncio.to_thread(request.execute)
            
            return [self._parse_file(f) for f in result.get('files', [])]
            
        except HttpError as e:
            # Some callers pass a file id/path as folder_id. If parent query is invalid,
            # retry once without folder filter so callers still get usable results.
            if folder_id and getattr(e, "resp", None) and getattr(e.resp, "status", None) == 400:
                retry_parts = [p for p in q_parts if p != f"'{folder_id}' in parents"]
                retry_q = " and ".join(retry_parts) if retry_parts else None
                request = self._service.files().list(
                    q=retry_q,
                    pageSize=max_results,
                    orderBy=order_by,
                    fields="files(id, name, mimeType, size, modifiedTime, parents, webViewLink)",
                )
                result = await asyncio.to_thread(request.execute)
                return [self._parse_file(f) for f in result.get('files', [])]
            raise RuntimeError(f"Drive API error: {e}")
    
    async def search(
        self,
        name_contains: str = None,
        full_text: str = None,
        mime_type: str = None,
        max_results: int = 20,
    ) -> List[DriveFile]:
        """
        Search for files.
        
        Args:
            name_contains: File name contains this string
            full_text: Full-text search in file content
            mime_type: Filter by type
        
        Returns:
            List of matching DriveFile objects
        """
        q_parts = []
        
        if name_contains:
            q_parts.append(f"name contains '{name_contains}'")
        
        if full_text:
            q_parts.append(f"fullText contains '{full_text}'")
        
        query = " and ".join(q_parts) if q_parts else None
        
        return await self.list_files(
            query=query,
            mime_type=mime_type,
            max_results=max_results,
        )
    
    async def get_file(self, file_id: str) -> DriveFile:
        """Get file metadata by ID."""
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
        
        request = self._service.files().get(
            fileId=file_id,
            fields="id, name, mimeType, size, createdTime, modifiedTime, parents, webViewLink, webContentLink, owners, shared, starred, trashed",
        )
        result = await asyncio.to_thread(request.execute)
        return self._parse_file(result)
    
    async def download_file(
        self,
        file_id: str,
        export_format: str = None,
    ) -> bytes:
        """
        Download a file's content.
        
        Args:
            file_id: File ID
            export_format: For Google Docs, format to export (pdf, docx, txt, xlsx, csv, etc.)
        
        Returns:
            File content as bytes
        """
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
        
        # Get file info first
        file_info = await self.get_file(file_id)
        
        try:
            if file_info.is_google_doc:
                # Need to export Google Docs/Sheets/etc.
                formats = EXPORT_FORMATS.get(file_info.mime_type, {})
                
                if not export_format:
                    # Default to PDF
                    export_format = 'pdf'
                
                export_mime = formats.get(export_format)
                if not export_mime:
                    raise ValueError(
                        f"Cannot export {file_info.mime_type} to {export_format}. "
                        f"Available: {list(formats.keys())}"
                    )
                
                request = self._service.files().export_media(
                    fileId=file_id,
                    mimeType=export_mime,
                )
            else:
                # Regular file download
                request = self._service.files().get_media(fileId=file_id)
            
            # Download
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)
            
            done = False
            while not done:
                status, done = await asyncio.to_thread(downloader.next_chunk)
            
            return buffer.getvalue()
            
        except HttpError as e:
            raise RuntimeError(f"Failed to download: {e}")
    
    async def download_to_file(
        self,
        file_id: str,
        local_path: str,
        export_format: str = None,
    ) -> str:
        """
        Download a file to local filesystem.
        
        Returns:
            Path to downloaded file
        """
        content = await self.download_file(file_id, export_format)
        
        path = Path(local_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'wb') as f:
            f.write(content)
        
        return str(path)
    
    async def upload_file(
        self,
        local_path: str,
        name: str = None,
        folder_id: str = None,
        mime_type: str = None,
    ) -> DriveFile:
        """
        Upload a file to Google Drive.
        
        Args:
            local_path: Path to local file
            name: Name in Drive (default: local filename)
            folder_id: Parent folder ID
            mime_type: MIME type (will be guessed if not provided)
        
        Returns:
            Created DriveFile
        """
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
        
        path = Path(local_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {local_path}")
        
        name = name or path.name
        mime_type = mime_type or mimetypes.guess_type(str(path))[0] or 'application/octet-stream'
        
        file_metadata = {'name': name}
        if folder_id:
            file_metadata['parents'] = [folder_id]
        
        media = MediaFileUpload(str(path), mimetype=mime_type, resumable=True)
        
        try:
            request = self._service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, name, mimeType, size, createdTime, modifiedTime, parents, webViewLink',
            )
            result = await asyncio.to_thread(request.execute)
            return self._parse_file(result)
            
        except HttpError as e:
            raise RuntimeError(f"Failed to upload: {e}")
    
    async def create_folder(
        self,
        name: str,
        parent_id: str = None,
    ) -> DriveFile:
        """
        Create a folder in Google Drive.
        
        Args:
            name: Folder name
            parent_id: Parent folder ID (root if not specified)
        
        Returns:
            Created DriveFile representing the folder
        """
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
        
        file_metadata = {
            'name': name,
            'mimeType': GOOGLE_MIME_TYPES['folder'],
        }
        if parent_id:
            file_metadata['parents'] = [parent_id]
        
        try:
            request = self._service.files().create(
                body=file_metadata,
                fields='id, name, mimeType, createdTime, modifiedTime, parents, webViewLink',
            )
            result = await asyncio.to_thread(request.execute)
            return self._parse_file(result)
            
        except HttpError as e:
            raise RuntimeError(f"Failed to create folder: {e}")
    
    async def delete_file(self, file_id: str) -> bool:
        """Delete a file (moves to trash)."""
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
        
        try:
            request = self._service.files().update(
                fileId=file_id,
                body={'trashed': True},
            )
            await asyncio.to_thread(request.execute)
            return True
            
        except HttpError as e:
            raise RuntimeError(f"Failed to delete: {e}")
    
    async def move_file(
        self,
        file_id: str,
        new_folder_id: str,
    ) -> DriveFile:
        """Move a file to a different folder."""
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
        
        # Get current parents
        file_info = await self.get_file(file_id)
        previous_parents = ','.join(file_info.parents)
        
        try:
            request = self._service.files().update(
                fileId=file_id,
                addParents=new_folder_id,
                removeParents=previous_parents,
                fields='id, name, mimeType, parents, webViewLink',
            )
            result = await asyncio.to_thread(request.execute)
            return self._parse_file(result)
            
        except HttpError as e:
            raise RuntimeError(f"Failed to move: {e}")
    
    async def get_storage_quota(self) -> Dict:
        """Get storage quota information."""
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
        
        request = self._service.about().get(fields="storageQuota")
        result = await asyncio.to_thread(request.execute)
        
        quota = result.get('storageQuota', {})
        return {
            'limit': int(quota.get('limit', 0)),
            'usage': int(quota.get('usage', 0)),
            'usage_in_drive': int(quota.get('usageInDrive', 0)),
            'usage_in_trash': int(quota.get('usageInDriveTrash', 0)),
        }
