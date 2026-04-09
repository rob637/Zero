"""
News Connector - NewsAPI.org Integration

Provides access to top headlines, news search, and source discovery.
Uses NewsAPI.org (free tier: 100 requests/day, developer plan available).

Setup:
    export NEWSAPI_KEY="your-key"
    
    # Or
    from connectors.news import NewsConnector
    news = NewsConnector(api_key="your-key")
    headlines = await news.top_headlines(country="us")
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

BASE_URL = "https://newsapi.org/v2"


@dataclass
class Article:
    """News article."""
    title: str
    description: str
    url: str
    source: str
    author: Optional[str] = None
    published_at: Optional[str] = None
    image_url: Optional[str] = None

    def to_dict(self) -> Dict:
        d = {
            "title": self.title,
            "description": self.description,
            "url": self.url,
            "source": self.source,
        }
        if self.author:
            d["author"] = self.author
        if self.published_at:
            d["published_at"] = self.published_at
        if self.image_url:
            d["image_url"] = self.image_url
        return d


class NewsConnector:
    """News search and headlines via NewsAPI.org."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("NEWSAPI_KEY", "")
        self.connected = bool(self.api_key)

    async def connect(self) -> bool:
        """Validate news API credentials."""
        self.connected = bool(self.api_key)
        return self.connected

    async def _get(self, endpoint: str, params: Dict[str, Any]) -> Dict:
        """Make API request."""
        import httpx

        params["apiKey"] = self.api_key
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{BASE_URL}/{endpoint}", params=params)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != "ok":
                raise RuntimeError(data.get("message", "NewsAPI error"))
            return data

    async def top_headlines(
        self,
        country: str = "us",
        category: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = 10,
    ) -> List[Article]:
        """Get top headlines.
        
        Args:
            country: 2-letter country code (us, gb, ca, au, etc.)
            category: business, entertainment, general, health, science, sports, technology
            query: Keywords to filter headlines
            limit: Max articles (default 10)
        """
        params = {"country": country, "pageSize": min(limit, 100)}
        if category:
            params["category"] = category
        if query:
            params["q"] = query

        data = await self._get("top-headlines", params)
        return self._parse_articles(data)

    async def search(
        self,
        query: str,
        sort_by: str = "relevancy",
        language: str = "en",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        sources: Optional[str] = None,
        limit: int = 10,
    ) -> List[Article]:
        """Search all news articles.
        
        Args:
            query: Search keywords (supports AND, OR, NOT operators)
            sort_by: relevancy, popularity, or publishedAt
            language: 2-letter language code (default: en)
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
            sources: Comma-separated source IDs (e.g. "bbc-news,cnn")
            limit: Max articles (default 10)
        """
        params = {
            "q": query,
            "sortBy": sort_by,
            "language": language,
            "pageSize": min(limit, 100),
        }
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        if sources:
            params["sources"] = sources

        data = await self._get("everything", params)
        return self._parse_articles(data)

    async def get_sources(
        self,
        category: Optional[str] = None,
        language: str = "en",
        country: Optional[str] = None,
    ) -> List[Dict]:
        """Get available news sources.
        
        Args:
            category: business, entertainment, general, health, science, sports, technology
            language: 2-letter language code
            country: 2-letter country code
        """
        params = {"language": language}
        if category:
            params["category"] = category
        if country:
            params["country"] = country

        data = await self._get("top-headlines/sources", params)
        sources = data.get("sources", [])
        return [{
            "id": s.get("id", ""),
            "name": s.get("name", ""),
            "description": s.get("description", ""),
            "url": s.get("url", ""),
            "category": s.get("category", ""),
            "language": s.get("language", ""),
            "country": s.get("country", ""),
        } for s in sources]

    # ── Internal helpers ──

    def _parse_articles(self, data: Dict) -> List[Article]:
        """Parse API response into Article list."""
        articles = []
        for item in data.get("articles", []):
            # Skip removed articles
            if item.get("title") == "[Removed]":
                continue
            articles.append(Article(
                title=item.get("title", ""),
                description=item.get("description") or "",
                url=item.get("url", ""),
                source=item.get("source", {}).get("name", ""),
                author=item.get("author"),
                published_at=item.get("publishedAt"),
                image_url=item.get("urlToImage"),
            ))
        return articles
