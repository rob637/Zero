"""
Spotify Connector - Music Streaming Integration

Provides access to Spotify for playback control, search,
and library management via the Spotify Web API.

Capabilities:
- Playback control (play, pause, next, prev, volume, shuffle)
- Search (tracks, albums, artists, playlists)
- Library (saved tracks, playlists)
- Currently playing info
- Queue management

Setup:
    from connectors.spotify import SpotifyConnector
    
    spotify = SpotifyConnector(access_token="...")
    await spotify.connect()
    
    await spotify.play(query="Bohemian Rhapsody")
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SPOTIFY_API = "https://api.spotify.com/v1"


@dataclass
class SpotifyTrack:
    """Spotify track."""
    id: str
    name: str
    artist: str
    album: str
    uri: str
    duration_ms: int = 0
    preview_url: Optional[str] = None

    @classmethod
    def from_api(cls, data: Dict) -> "SpotifyTrack":
        artists = data.get("artists", [])
        album = data.get("album", {})
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            artist=artists[0].get("name", "") if artists else "",
            album=album.get("name", ""),
            uri=data.get("uri", ""),
            duration_ms=data.get("duration_ms", 0),
            preview_url=data.get("preview_url"),
        )


class SpotifyConnector:
    """Spotify Web API connector."""

    def __init__(self, access_token: Optional[str] = None):
        self._token = access_token or os.environ.get("SPOTIFY_ACCESS_TOKEN", "")
        self._http = None

    async def connect(self):
        """Initialize HTTP client."""
        if not self._token:
            raise ValueError("No Spotify access token. Set SPOTIFY_ACCESS_TOKEN.")

        import httpx
        self._http = httpx.AsyncClient(
            base_url=SPOTIFY_API,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=30,
        )

    async def _ensure_client(self):
        if not self._http:
            await self.connect()

    # --- Playback Control ---

    async def control(
        self,
        action: str = "play",
        query: Optional[str] = None,
        uri: Optional[str] = None,
    ) -> Dict:
        """Control playback: play, pause, next, previous, volume."""
        await self._ensure_client()

        if action == "play":
            if query:
                # Search and play
                results = await self.search(query, type="track", limit=1)
                if results:
                    uri = results[0].uri
                else:
                    return {"error": f"No results for '{query}'"}

            if uri:
                if "track" in uri:
                    await self._http.put("/me/player/play", json={"uris": [uri]})
                else:
                    await self._http.put("/me/player/play", json={"context_uri": uri})
            else:
                await self._http.put("/me/player/play")

            return {"action": "play", "uri": uri}

        elif action == "pause":
            await self._http.put("/me/player/pause")
            return {"action": "pause"}

        elif action == "next":
            await self._http.post("/me/player/next")
            return {"action": "next"}

        elif action == "previous":
            await self._http.post("/me/player/previous")
            return {"action": "previous"}

        elif action == "volume":
            # uri field used for volume percent in this case
            vol = int(uri) if uri else 50
            await self._http.put("/me/player/volume", params={"volume_percent": vol})
            return {"action": "volume", "volume": vol}

        elif action == "shuffle":
            await self._http.put("/me/player/shuffle", params={"state": "true"})
            return {"action": "shuffle"}

        return {"error": f"Unknown action: {action}"}

    async def now_playing(self) -> Optional[Dict]:
        """Get currently playing track."""
        await self._ensure_client()
        resp = await self._http.get("/me/player/currently-playing")
        if resp.status_code == 204:
            return None
        resp.raise_for_status()
        data = resp.json()
        item = data.get("item")
        if item:
            track = SpotifyTrack.from_api(item)
            return {
                "track": track.name,
                "artist": track.artist,
                "album": track.album,
                "uri": track.uri,
                "is_playing": data.get("is_playing", False),
                "progress_ms": data.get("progress_ms", 0),
                "duration_ms": track.duration_ms,
            }
        return None

    # --- Search ---

    async def search(
        self, query: str, type: str = "track", limit: int = 10
    ) -> List[SpotifyTrack]:
        """Search for tracks, albums, artists, or playlists."""
        await self._ensure_client()
        resp = await self._http.get(
            "/search",
            params={"q": query, "type": type, "limit": min(limit, 50)},
        )
        resp.raise_for_status()
        data = resp.json()

        # Return tracks for track search
        if type == "track":
            items = data.get("tracks", {}).get("items", [])
            return [SpotifyTrack.from_api(t) for t in items]

        # For other types, return raw items
        key = f"{type}s"
        return data.get(key, {}).get("items", [])

    # --- Library ---

    async def saved_tracks(self, limit: int = 20) -> List[SpotifyTrack]:
        """Get user's saved/liked tracks."""
        await self._ensure_client()
        resp = await self._http.get("/me/tracks", params={"limit": min(limit, 50)})
        resp.raise_for_status()
        items = resp.json().get("items", [])
        return [SpotifyTrack.from_api(i.get("track", {})) for i in items]

    async def playlists(self, limit: int = 20) -> List[Dict]:
        """Get user's playlists."""
        await self._ensure_client()
        resp = await self._http.get("/me/playlists", params={"limit": min(limit, 50)})
        resp.raise_for_status()
        return resp.json().get("items", [])

    async def add_to_queue(self, uri: str) -> Dict:
        """Add a track to the playback queue."""
        await self._ensure_client()
        resp = await self._http.post("/me/player/queue", params={"uri": uri})
        resp.raise_for_status()
        return {"queued": uri}

    async def close(self):
        if self._http:
            await self._http.aclose()
            self._http = None
