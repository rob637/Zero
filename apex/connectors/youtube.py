"""
YouTube Connector - Video Platform Integration

Provides access to YouTube for video search, playlist management,
and channel info via the YouTube Data API v3.

Capabilities:
- Video search
- Channel and playlist info
- Video metadata (title, description, stats)
- Playlist management (list, create, add/remove videos)
- Captions/transcript retrieval

Setup:
    from connectors.youtube import YouTubeConnector
    
    yt = YouTubeConnector(api_key="...")
    await yt.connect()
    
    results = await yt.search("Python tutorial")
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

YOUTUBE_API = "https://www.googleapis.com/youtube/v3"


@dataclass
class YouTubeVideo:
    """YouTube video."""
    id: str
    title: str
    channel: str
    description: str = ""
    published_at: Optional[str] = None
    thumbnail: Optional[str] = None
    url: str = ""
    duration: Optional[str] = None
    view_count: int = 0

    @classmethod
    def from_search(cls, data: Dict) -> "YouTubeVideo":
        snippet = data.get("snippet", {})
        vid_id = data.get("id", {})
        if isinstance(vid_id, dict):
            vid_id = vid_id.get("videoId", "")
        return cls(
            id=vid_id,
            title=snippet.get("title", ""),
            channel=snippet.get("channelTitle", ""),
            description=snippet.get("description", ""),
            published_at=snippet.get("publishedAt"),
            thumbnail=snippet.get("thumbnails", {}).get("default", {}).get("url"),
            url=f"https://youtube.com/watch?v={vid_id}",
        )

    @classmethod
    def from_video(cls, data: Dict) -> "YouTubeVideo":
        snippet = data.get("snippet", {})
        stats = data.get("statistics", {})
        content = data.get("contentDetails", {})
        vid_id = data.get("id", "")
        return cls(
            id=vid_id,
            title=snippet.get("title", ""),
            channel=snippet.get("channelTitle", ""),
            description=snippet.get("description", ""),
            published_at=snippet.get("publishedAt"),
            thumbnail=snippet.get("thumbnails", {}).get("default", {}).get("url"),
            url=f"https://youtube.com/watch?v={vid_id}",
            duration=content.get("duration"),
            view_count=int(stats.get("viewCount", 0)),
        )


class YouTubeConnector:
    """YouTube Data API v3 connector."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        access_token: Optional[str] = None,
    ):
        self._api_key = api_key or os.environ.get("YOUTUBE_API_KEY", "")
        self._access_token = access_token or os.environ.get("YOUTUBE_ACCESS_TOKEN", "")
        self._http = None

    async def connect(self):
        """Initialize HTTP client."""
        if not self._api_key and not self._access_token:
            raise ValueError("YouTube API key or access token required. Set YOUTUBE_API_KEY.")

        import httpx
        headers = {}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"

        self._http = httpx.AsyncClient(
            base_url=YOUTUBE_API,
            headers=headers,
            timeout=30,
        )

    async def _ensure_client(self):
        if not self._http:
            await self.connect()

    def _params(self, **kwargs) -> Dict:
        """Add API key to params if using key auth."""
        params = {k: v for k, v in kwargs.items() if v is not None}
        if self._api_key:
            params["key"] = self._api_key
        return params

    async def search(
        self, query: str, type: str = "video", limit: int = 10
    ) -> List[YouTubeVideo]:
        """Search YouTube."""
        await self._ensure_client()
        resp = await self._http.get(
            "/search",
            params=self._params(
                q=query, type=type, part="snippet",
                maxResults=min(limit, 50),
            ),
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        return [YouTubeVideo.from_search(i) for i in items]

    async def get_video(self, video_id: str) -> YouTubeVideo:
        """Get detailed video info."""
        await self._ensure_client()
        resp = await self._http.get(
            "/videos",
            params=self._params(
                id=video_id,
                part="snippet,contentDetails,statistics",
            ),
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if not items:
            raise ValueError(f"Video not found: {video_id}")
        return YouTubeVideo.from_video(items[0])

    async def list_playlists(self, channel_id: Optional[str] = None, limit: int = 20) -> List[Dict]:
        """List playlists. If no channel_id, lists user's own playlists."""
        await self._ensure_client()
        params = self._params(part="snippet", maxResults=min(limit, 50))
        if channel_id:
            params["channelId"] = channel_id
        else:
            params["mine"] = "true"

        resp = await self._http.get("/playlists", params=params)
        resp.raise_for_status()
        return resp.json().get("items", [])

    async def playlist_items(self, playlist_id: str, limit: int = 50) -> List[YouTubeVideo]:
        """List videos in a playlist."""
        await self._ensure_client()
        resp = await self._http.get(
            "/playlistItems",
            params=self._params(
                playlistId=playlist_id,
                part="snippet",
                maxResults=min(limit, 50),
            ),
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        return [YouTubeVideo.from_search(i) for i in items]

    async def captions(self, video_id: str) -> List[Dict]:
        """List available captions for a video."""
        await self._ensure_client()
        resp = await self._http.get(
            "/captions",
            params=self._params(videoId=video_id, part="snippet"),
        )
        resp.raise_for_status()
        return resp.json().get("items", [])

    async def channel_info(self, channel_id: str) -> Dict:
        """Get channel information."""
        await self._ensure_client()
        resp = await self._http.get(
            "/channels",
            params=self._params(id=channel_id, part="snippet,statistics"),
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        return items[0] if items else {}

    async def close(self):
        if self._http:
            await self._http.aclose()
            self._http = None
