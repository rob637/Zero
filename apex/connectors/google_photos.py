"""
Google Photos Connector

Real Google Photos Library API integration for photo operations.

Usage:
    from connectors.google_photos import PhotosConnector
    
    photos = PhotosConnector()
    await photos.connect()
    
    # List albums
    albums = await photos.list_albums()
    
    # Search photos
    items = await photos.search(date_range=("2024-01-01", "2024-01-31"))
    
    # Upload photo
    await photos.upload("~/vacation.jpg", album_id="album123")
"""

import asyncio
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .google_auth import GoogleAuth, get_google_auth

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    import httpx
    HAS_DEPENDENCIES = True
except ImportError:
    HAS_DEPENDENCIES = False


@dataclass
class Album:
    """Represents a Google Photos album."""
    id: str
    title: str
    product_url: str
    media_items_count: int = 0
    cover_photo_url: Optional[str] = None
    cover_photo_id: Optional[str] = None
    is_writeable: bool = True
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "title": self.title,
            "url": self.product_url,
            "item_count": self.media_items_count,
            "cover_url": self.cover_photo_url,
            "writeable": self.is_writeable,
        }


@dataclass
class MediaItem:
    """Represents a photo or video in Google Photos."""
    id: str
    filename: str
    mime_type: str
    product_url: str
    base_url: str
    creation_time: Optional[datetime] = None
    width: Optional[int] = None
    height: Optional[int] = None
    description: Optional[str] = None
    camera_make: Optional[str] = None
    camera_model: Optional[str] = None
    
    @property
    def is_video(self) -> bool:
        return self.mime_type.startswith('video/')
    
    @property
    def is_photo(self) -> bool:
        return self.mime_type.startswith('image/')
    
    def get_download_url(self, width: int = None, height: int = None) -> str:
        """Get URL with size parameters for downloading."""
        url = self.base_url
        params = []
        if width:
            params.append(f"w{width}")
        if height:
            params.append(f"h{height}")
        if self.is_video:
            params.append("dv")  # Download video
        elif not params:
            params.append("d")  # Original quality
        
        if params:
            url += "=" + "-".join(params)
        return url
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "mime_type": self.mime_type,
            "url": self.product_url,
            "base_url": self.base_url,
            "created": self.creation_time.isoformat() if self.creation_time else None,
            "width": self.width,
            "height": self.height,
            "description": self.description,
            "camera": f"{self.camera_make} {self.camera_model}".strip() if self.camera_make else None,
            "is_video": self.is_video,
        }


@dataclass
class DateRange:
    """Date range for filtering photos."""
    start: date
    end: date
    
    def to_api_format(self) -> Dict:
        return {
            'startDate': {
                'year': self.start.year,
                'month': self.start.month,
                'day': self.start.day,
            },
            'endDate': {
                'year': self.end.year,
                'month': self.end.month,
                'day': self.end.day,
            }
        }


# Content categories for filtering
CONTENT_CATEGORIES = [
    'ANIMALS', 'ARTS', 'BIRTHDAYS', 'CITYSCAPES', 'CRAFTS',
    'DOCUMENTS', 'FASHION', 'FLOWERS', 'FOOD', 'GARDENS',
    'HOLIDAYS', 'HOUSES', 'LANDMARKS', 'LANDSCAPES', 'NIGHT',
    'PEOPLE', 'PERFORMANCES', 'PETS', 'RECEIPTS', 'SCREENSHOTS',
    'SELFIES', 'SPORT', 'TRAVEL', 'UTILITY', 'WEDDINGS', 'WHITEBOARDS'
]

# Media types
MEDIA_TYPES = ['ALL_MEDIA', 'PHOTO', 'VIDEO']


class PhotosConnector:
    """
    Google Photos Library API connector.
    
    Provides methods for:
    - Listing and searching photos
    - Managing albums
    - Uploading media
    - Downloading media
    """
    
    PHOTOS_API_URL = "https://photoslibrary.googleapis.com/v1"
    UPLOAD_URL = "https://photoslibrary.googleapis.com/v1/uploads"
    
    def __init__(self, auth: Optional[GoogleAuth] = None):
        self._auth = auth or get_google_auth()
        self._credentials = None
        self._http_client: Optional[httpx.AsyncClient] = None
    
    async def connect(self) -> bool:
        """Connect to Google Photos API."""
        if not HAS_DEPENDENCIES:
            raise ImportError(
                "Dependencies not installed. Run:\n"
                "pip install google-api-python-client httpx"
            )
        
        self._credentials = await self._auth.get_credentials(['photos'])
        if not self._credentials:
            return False
        
        self._http_client = httpx.AsyncClient(
            base_url=self.PHOTOS_API_URL,
            timeout=60.0,
        )
        
        return True
    
    @property
    def connected(self) -> bool:
        return self._credentials is not None
    
    def _ensure_connected(self):
        if not self._credentials:
            raise RuntimeError("Not connected. Call connect() first.")
    
    async def _get_headers(self) -> Dict[str, str]:
        """Get authorization headers."""
        # Refresh credentials if needed
        if self._credentials.expired:
            await asyncio.to_thread(self._credentials.refresh, None)
        
        return {
            'Authorization': f'Bearer {self._credentials.token}',
            'Content-Type': 'application/json',
        }
    
    def _parse_album(self, data: Dict) -> Album:
        """Parse API response into Album."""
        return Album(
            id=data['id'],
            title=data.get('title', ''),
            product_url=data.get('productUrl', ''),
            media_items_count=int(data.get('mediaItemsCount', 0)),
            cover_photo_url=data.get('coverPhotoBaseUrl'),
            cover_photo_id=data.get('coverPhotoMediaItemId'),
            is_writeable=data.get('isWriteable', True),
        )
    
    def _parse_media_item(self, data: Dict) -> MediaItem:
        """Parse API response into MediaItem."""
        metadata = data.get('mediaMetadata', {})
        photo_meta = metadata.get('photo', {})
        
        created = None
        if 'creationTime' in metadata:
            try:
                created = datetime.fromisoformat(
                    metadata['creationTime'].replace('Z', '+00:00')
                )
            except:
                pass
        
        return MediaItem(
            id=data['id'],
            filename=data.get('filename', ''),
            mime_type=data.get('mimeType', ''),
            product_url=data.get('productUrl', ''),
            base_url=data.get('baseUrl', ''),
            creation_time=created,
            width=int(metadata.get('width', 0)) or None,
            height=int(metadata.get('height', 0)) or None,
            description=data.get('description'),
            camera_make=photo_meta.get('cameraMake'),
            camera_model=photo_meta.get('cameraModel'),
        )
    
    # === Album Operations ===
    
    async def list_albums(
        self,
        max_results: int = 50,
        exclude_non_app_created: bool = False,
    ) -> List[Album]:
        """
        List user's albums.
        
        Args:
            max_results: Maximum albums to return
            exclude_non_app_created: Only show albums created by this app
        
        Returns:
            List of Album objects
        """
        self._ensure_connected()
        
        albums = []
        page_token = None
        
        while len(albums) < max_results:
            params = {
                'pageSize': min(50, max_results - len(albums)),
                'excludeNonAppCreatedData': exclude_non_app_created,
            }
            if page_token:
                params['pageToken'] = page_token
            
            headers = await self._get_headers()
            response = await self._http_client.get('/albums', headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            
            for album_data in data.get('albums', []):
                albums.append(self._parse_album(album_data))
            
            page_token = data.get('nextPageToken')
            if not page_token:
                break
        
        return albums
    
    async def get_album(self, album_id: str) -> Album:
        """
        Get album by ID.
        
        Args:
            album_id: Album ID
        
        Returns:
            Album object
        """
        self._ensure_connected()
        
        headers = await self._get_headers()
        response = await self._http_client.get(f'/albums/{album_id}', headers=headers)
        response.raise_for_status()
        return self._parse_album(response.json())
    
    async def create_album(self, title: str) -> Album:
        """
        Create a new album.
        
        Args:
            title: Album title
        
        Returns:
            Created Album object
        """
        self._ensure_connected()
        
        body = {'album': {'title': title}}
        headers = await self._get_headers()
        response = await self._http_client.post('/albums', headers=headers, json=body)
        response.raise_for_status()
        return self._parse_album(response.json())
    
    async def add_to_album(
        self,
        album_id: str,
        media_item_ids: List[str],
    ) -> int:
        """
        Add media items to album.
        
        Args:
            album_id: Album ID
            media_item_ids: List of media item IDs
        
        Returns:
            Number of items added
        """
        self._ensure_connected()
        
        body = {'mediaItemIds': media_item_ids}
        headers = await self._get_headers()
        response = await self._http_client.post(
            f'/albums/{album_id}:batchAddMediaItems',
            headers=headers,
            json=body,
        )
        response.raise_for_status()
        return len(media_item_ids)
    
    async def remove_from_album(
        self,
        album_id: str,
        media_item_ids: List[str],
    ) -> int:
        """
        Remove media items from album.
        
        Args:
            album_id: Album ID
            media_item_ids: List of media item IDs
        
        Returns:
            Number of items removed
        """
        self._ensure_connected()
        
        body = {'mediaItemIds': media_item_ids}
        headers = await self._get_headers()
        response = await self._http_client.post(
            f'/albums/{album_id}:batchRemoveMediaItems',
            headers=headers,
            json=body,
        )
        response.raise_for_status()
        return len(media_item_ids)
    
    # === Media Item Operations ===
    
    async def list_media_items(
        self,
        max_results: int = 50,
        album_id: str = None,
    ) -> List[MediaItem]:
        """
        List media items.
        
        Args:
            max_results: Maximum items to return
            album_id: Filter by album (optional)
        
        Returns:
            List of MediaItem objects
        """
        self._ensure_connected()
        
        items = []
        page_token = None
        
        while len(items) < max_results:
            if album_id:
                # Use search endpoint for album filtering
                body = {
                    'albumId': album_id,
                    'pageSize': min(100, max_results - len(items)),
                }
                if page_token:
                    body['pageToken'] = page_token
                
                headers = await self._get_headers()
                response = await self._http_client.post(
                    '/mediaItems:search',
                    headers=headers,
                    json=body,
                )
            else:
                params = {
                    'pageSize': min(100, max_results - len(items)),
                }
                if page_token:
                    params['pageToken'] = page_token
                
                headers = await self._get_headers()
                response = await self._http_client.get(
                    '/mediaItems',
                    headers=headers,
                    params=params,
                )
            
            response.raise_for_status()
            data = response.json()
            
            for item_data in data.get('mediaItems', []):
                items.append(self._parse_media_item(item_data))
            
            page_token = data.get('nextPageToken')
            if not page_token:
                break
        
        return items
    
    async def get_media_item(self, item_id: str) -> MediaItem:
        """
        Get media item by ID.
        
        Args:
            item_id: Media item ID
        
        Returns:
            MediaItem object
        """
        self._ensure_connected()
        
        headers = await self._get_headers()
        response = await self._http_client.get(f'/mediaItems/{item_id}', headers=headers)
        response.raise_for_status()
        return self._parse_media_item(response.json())
    
    async def search(
        self,
        date_range: Tuple[str, str] = None,
        categories: List[str] = None,
        media_type: str = None,
        album_id: str = None,
        max_results: int = 50,
    ) -> List[MediaItem]:
        """
        Search for media items.
        
        Args:
            date_range: Tuple of (start_date, end_date) in YYYY-MM-DD format
            categories: List of content categories (PEOPLE, LANDSCAPES, etc.)
            media_type: PHOTO, VIDEO, or ALL_MEDIA
            album_id: Filter by album
            max_results: Maximum items to return
        
        Returns:
            List of matching MediaItem objects
        """
        self._ensure_connected()
        
        filters = {}
        
        if date_range:
            start = date.fromisoformat(date_range[0])
            end = date.fromisoformat(date_range[1])
            filters['dateFilter'] = {
                'ranges': [DateRange(start, end).to_api_format()]
            }
        
        if categories:
            filters['contentFilter'] = {
                'includedContentCategories': categories
            }
        
        if media_type and media_type != 'ALL_MEDIA':
            filters['mediaTypeFilter'] = {
                'mediaTypes': [media_type]
            }
        
        items = []
        page_token = None
        
        while len(items) < max_results:
            body = {
                'pageSize': min(100, max_results - len(items)),
            }
            if filters:
                body['filters'] = filters
            if album_id:
                body['albumId'] = album_id
            if page_token:
                body['pageToken'] = page_token
            
            headers = await self._get_headers()
            response = await self._http_client.post(
                '/mediaItems:search',
                headers=headers,
                json=body,
            )
            response.raise_for_status()
            data = response.json()
            
            for item_data in data.get('mediaItems', []):
                items.append(self._parse_media_item(item_data))
            
            page_token = data.get('nextPageToken')
            if not page_token:
                break
        
        return items
    
    # === Upload Operations ===
    
    async def upload(
        self,
        file_path: str,
        album_id: str = None,
        description: str = None,
    ) -> MediaItem:
        """
        Upload a photo or video.
        
        Args:
            file_path: Path to file
            album_id: Album to add to (optional)
            description: Description text
        
        Returns:
            Created MediaItem object
        """
        self._ensure_connected()
        
        file_path = Path(file_path).expanduser()
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # Step 1: Upload bytes to get upload token
        headers = await self._get_headers()
        headers['Content-Type'] = 'application/octet-stream'
        headers['X-Goog-Upload-Protocol'] = 'raw'
        headers['X-Goog-Upload-File-Name'] = file_path.name
        
        async with httpx.AsyncClient(timeout=300.0) as client:
            with open(file_path, 'rb') as f:
                response = await client.post(
                    self.UPLOAD_URL,
                    headers=headers,
                    content=f.read(),
                )
        response.raise_for_status()
        upload_token = response.text
        
        # Step 2: Create media item
        new_item = {
            'simpleMediaItem': {
                'uploadToken': upload_token,
                'fileName': file_path.name,
            }
        }
        
        body = {'newMediaItems': [new_item]}
        if album_id:
            body['albumId'] = album_id
        
        headers = await self._get_headers()
        response = await self._http_client.post(
            '/mediaItems:batchCreate',
            headers=headers,
            json=body,
        )
        response.raise_for_status()
        
        result = response.json()
        results = result.get('newMediaItemResults', [])
        if results and results[0].get('status', {}).get('message') == 'Success':
            return self._parse_media_item(results[0]['mediaItem'])
        else:
            error = results[0].get('status', {}) if results else {}
            raise RuntimeError(f"Upload failed: {error}")
    
    async def download(
        self,
        item_id: str,
        output_path: str,
        width: int = None,
        height: int = None,
    ) -> str:
        """
        Download a media item.
        
        Args:
            item_id: Media item ID
            output_path: Path to save file
            width: Optional width for resizing
            height: Optional height for resizing
        
        Returns:
            Path to downloaded file
        """
        self._ensure_connected()
        
        # Get media item to get download URL
        item = await self.get_media_item(item_id)
        url = item.get_download_url(width, height)
        
        output_path = Path(output_path).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            
            with open(output_path, 'wb') as f:
                f.write(response.content)
        
        return str(output_path)
    
    # === Batch Operations ===
    
    async def get_media_items_batch(
        self,
        item_ids: List[str],
    ) -> List[MediaItem]:
        """
        Get multiple media items by ID.
        
        Args:
            item_ids: List of media item IDs (max 50)
        
        Returns:
            List of MediaItem objects
        """
        self._ensure_connected()
        
        if len(item_ids) > 50:
            raise ValueError("Maximum 50 items per batch")
        
        params = {'mediaItemIds': item_ids}
        headers = await self._get_headers()
        response = await self._http_client.get(
            '/mediaItems:batchGet',
            headers=headers,
            params=params,
        )
        response.raise_for_status()
        
        items = []
        for result in response.json().get('mediaItemResults', []):
            if 'mediaItem' in result:
                items.append(self._parse_media_item(result['mediaItem']))
        
        return items
