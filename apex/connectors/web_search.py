"""
Web Search Connector - Internet Search Integration

Provides web search via Google Custom Search API or Bing Web Search API.
Falls back gracefully between providers.

Capabilities:
- Web search (Google or Bing)
- Image search
- News search

Setup:
    from connectors.web_search import WebSearchConnector
    
    # Google Custom Search
    search = WebSearchConnector(
        provider="google",
        api_key="...",
        cx="..."  # Custom Search Engine ID
    )
    
    # Or Bing
    search = WebSearchConnector(
        provider="bing",
        api_key="...",
    )
    
    results = await search.search("Python AI programming")
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Web search result."""
    title: str
    url: str
    snippet: str
    source: str = ""
    date: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source": self.source,
            "date": self.date,
        }


class WebSearchConnector:
    """Web search via Google Custom Search or Bing."""

    def __init__(
        self,
        provider: str = "google",
        api_key: Optional[str] = None,
        cx: Optional[str] = None,
    ):
        self._provider = provider.lower()
        self._http = None

        if self._provider == "google":
            self._api_key = api_key or os.environ.get("GOOGLE_SEARCH_API_KEY", "")
            self._cx = cx or os.environ.get("GOOGLE_SEARCH_CX", "")
        elif self._provider == "bing":
            self._api_key = api_key or os.environ.get("BING_SEARCH_API_KEY", "")
        else:
            self._api_key = api_key or ""

    async def connect(self):
        """Initialize HTTP client."""
        if not self._api_key:
            raise ValueError(
                f"No API key for {self._provider} search. "
                f"Set {'GOOGLE_SEARCH_API_KEY' if self._provider == 'google' else 'BING_SEARCH_API_KEY'}."
            )

        import httpx
        self._http = httpx.AsyncClient(timeout=30)

    async def _ensure_client(self):
        if not self._http:
            await self.connect()

    async def search(self, query: str, limit: int = 5) -> List[SearchResult]:
        """Search the web."""
        await self._ensure_client()

        if self._provider == "google":
            return await self._google_search(query, limit)
        elif self._provider == "bing":
            return await self._bing_search(query, limit)
        else:
            raise ValueError(f"Unknown search provider: {self._provider}")

    async def _google_search(self, query: str, limit: int) -> List[SearchResult]:
        """Google Custom Search API."""
        resp = await self._http.get(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": self._api_key,
                "cx": self._cx,
                "q": query,
                "num": min(limit, 10),
            },
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        return [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=item.get("snippet", ""),
                source="google",
            )
            for item in items
        ]

    async def _bing_search(self, query: str, limit: int) -> List[SearchResult]:
        """Bing Web Search API."""
        resp = await self._http.get(
            "https://api.bing.microsoft.com/v7.0/search",
            headers={"Ocp-Apim-Subscription-Key": self._api_key},
            params={"q": query, "count": min(limit, 50)},
        )
        resp.raise_for_status()
        pages = resp.json().get("webPages", {}).get("value", [])
        return [
            SearchResult(
                title=p.get("name", ""),
                url=p.get("url", ""),
                snippet=p.get("snippet", ""),
                source="bing",
                date=p.get("dateLastCrawled"),
            )
            for p in pages
        ]

    async def image_search(self, query: str, limit: int = 5) -> List[Dict]:
        """Search for images."""
        await self._ensure_client()

        if self._provider == "google":
            resp = await self._http.get(
                "https://www.googleapis.com/customsearch/v1",
                params={
                    "key": self._api_key,
                    "cx": self._cx,
                    "q": query,
                    "searchType": "image",
                    "num": min(limit, 10),
                },
            )
            resp.raise_for_status()
            return [
                {"title": i.get("title", ""), "url": i.get("link", ""), "thumbnail": i.get("image", {}).get("thumbnailLink", "")}
                for i in resp.json().get("items", [])
            ]

        elif self._provider == "bing":
            resp = await self._http.get(
                "https://api.bing.microsoft.com/v7.0/images/search",
                headers={"Ocp-Apim-Subscription-Key": self._api_key},
                params={"q": query, "count": min(limit, 50)},
            )
            resp.raise_for_status()
            return [
                {"title": i.get("name", ""), "url": i.get("contentUrl", ""), "thumbnail": i.get("thumbnailUrl", "")}
                for i in resp.json().get("value", [])
            ]

        return []

    async def news_search(self, query: str, limit: int = 5) -> List[SearchResult]:
        """Search for news articles."""
        await self._ensure_client()

        if self._provider == "bing":
            resp = await self._http.get(
                "https://api.bing.microsoft.com/v7.0/news/search",
                headers={"Ocp-Apim-Subscription-Key": self._api_key},
                params={"q": query, "count": min(limit, 50)},
            )
            resp.raise_for_status()
            return [
                SearchResult(
                    title=a.get("name", ""),
                    url=a.get("url", ""),
                    snippet=a.get("description", ""),
                    source=a.get("provider", [{}])[0].get("name", "bing"),
                    date=a.get("datePublished"),
                )
                for a in resp.json().get("value", [])
            ]

        # Google doesn't have a separate news endpoint in Custom Search
        # but can use the regular search with tbm=nws style filtering
        return await self.search(query + " news", limit)

    async def close(self):
        if self._http:
            await self._http.aclose()
            self._http = None
