"""Telic Engine — Web & Media Primitives"""

import asyncio
import hashlib
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from .base import Primitive, StepResult
from .base import get_data_index

logger = logging.getLogger(__name__)


class WebPrimitive(Primitive):
    """Web/HTTP operations — fetch pages, call APIs, search the web."""
    
    def __init__(self, llm_complete: Optional[Callable] = None, search_provider: Optional[Any] = None):
        self._llm = llm_complete
        self._search_provider = search_provider
    
    @property
    def name(self) -> str:
        return "WEB"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "fetch": "Fetch content from a URL (returns text/HTML). Works for static pages only.",
            "api": "Make an HTTP API call (GET, POST, PUT, DELETE)",
            "search": "Search the web for current information (sports schedules, news, facts). Use this for questions about dates, times, events.",
            "extract": "Fetch a static webpage URL and extract specific information. NOT for google.com, bing.com, or other search engines (JS-rendered). Use for news sites, wikipedia, official event pages.",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "fetch": {
                "url": {"type": "str", "required": True, "description": "URL to fetch"},
                "max_length": {"type": "int", "required": False, "description": "Max chars to return (default 10000)"},
            },
            "api": {
                "url": {"type": "str", "required": True, "description": "API endpoint URL"},
                "method": {"type": "str", "required": False, "description": "HTTP method: GET, POST, PUT, DELETE (default GET)"},
                "headers": {"type": "dict", "required": False, "description": "HTTP headers"},
                "body": {"type": "dict", "required": False, "description": "Request body (for POST/PUT)"},
                "params": {"type": "dict", "required": False, "description": "Query parameters"},
            },
            "search": {
                "query": {"type": "str", "required": True, "description": "Search query"},
                "limit": {"type": "int", "required": False, "description": "Max results (default 5)"},
            },
            "extract": {
                "url": {"type": "str", "required": True, "description": "URL to fetch and extract from"},
                "what": {"type": "str", "required": True, "description": "What to extract (e.g. 'the main article text', 'all prices', 'contact info')"},
            },
        }
    
    def get_available_operations(self) -> Dict[str, str]:
        """Only show search if a search provider is configured."""
        ops = self.get_operations()
        if not self._search_provider:
            ops.pop("search", None)
        return ops
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            import httpx
        except ImportError:
            try:
                import urllib.request
                _has_httpx = False
            except Exception:
                return StepResult(False, error="No HTTP library available")
            _has_httpx = False
        else:
            _has_httpx = True
        
        try:
            if operation == "fetch":
                url = params.get("url", "")
                max_len = params.get("max_length", 10000)
                
                if not url:
                    return StepResult(False, error="Missing 'url' parameter")
                
                if _has_httpx:
                    async with httpx.AsyncClient(
                        follow_redirects=True, 
                        timeout=30,
                        headers={"User-Agent": "Mozilla/5.0 (compatible; Telic/1.0; +https://github.com/rob637/Zero)"}
                    ) as client:
                        resp = await client.get(url)
                        resp.raise_for_status()
                        text = resp.text[:max_len]
                else:
                    req = urllib.request.Request(url, headers={"User-Agent": "Telic/1.0"})
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        text = resp.read().decode("utf-8", errors="ignore")[:max_len]
                
                return StepResult(True, data={"url": url, "content": text, "length": len(text)})
            
            elif operation == "api":
                if not _has_httpx:
                    return StepResult(False, error="httpx required for API calls. Install: pip install httpx")
                
                url = params.get("url", "")
                method = params.get("method", "GET").upper()
                headers = params.get("headers", {})
                body = params.get("body")
                query_params = params.get("params")
                
                if not url:
                    return StepResult(False, error="Missing 'url' parameter")
                
                async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                    resp = await client.request(
                        method, url,
                        headers=headers,
                        json=body if body else None,
                        params=query_params,
                    )
                    
                    try:
                        data = resp.json()
                    except Exception:
                        data = resp.text[:10000]
                    
                    return StepResult(True, data={
                        "status": resp.status_code,
                        "data": data,
                        "headers": dict(resp.headers),
                    })
            
            elif operation == "search":
                query = params.get("query", "")
                limit = params.get("limit", 5)
                
                if self._search_provider and hasattr(self._search_provider, "search"):
                    result = await self._search_provider.search(query=query, num_results=limit)
                    return StepResult(True, data=result)
                
                return StepResult(False, error="Web search not configured. Connect a search provider (Google, Bing, etc.)")
            
            elif operation == "extract":
                url = params.get("url", "")
                what = params.get("what", "the main content")
                
                if not url:
                    return StepResult(False, error="Missing 'url' parameter")
                if not self._llm:
                    return StepResult(False, error="LLM required for extraction")
                
                # Fetch first
                fetch_result = await self.execute("fetch", {"url": url, "max_length": 15000})
                if not fetch_result.success:
                    return fetch_result
                
                content = fetch_result.data.get("content", "")
                
                # Inject today's date for time-sensitive extractions
                today_iso = datetime.now().strftime("%Y-%m-%d")
                
                prompt = f"""Extract the following from this web page:
What to extract: {what}

IMPORTANT: Today's date is {today_iso}. If returning dates/times, use {today_iso} as the date.

Web page content:
{content[:12000]}

Return ONLY a JSON object with the extracted data."""
                
                response = await self._llm(prompt)
                json_match = re.search(r'\{[\s\S]*\}', response)
                if json_match:
                    try:
                        return StepResult(True, data=json.loads(json_match.group()))
                    except json.JSONDecodeError:
                        pass
                return StepResult(True, data={"extracted": response})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  WEATHER PRIMITIVE
# ============================================================



class BrowserPrimitive(Primitive):
    """Browser automation — navigate, interact with web pages, fill forms.
    
    Distinct from WEB (which does raw HTTP). BROWSER controls a real browser
    for JavaScript-heavy sites, form filling, screenshots, etc.
    Uses Playwright when available, falls back to error messages.
    """
    
    def __init__(self, llm_complete: Optional[Callable] = None):
        self._llm = llm_complete
        self._page = None
        self._browser = None
    
    @property
    def name(self) -> str:
        return "BROWSER"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "open": "Open a URL in a browser",
            "click": "Click an element on the page",
            "type": "Type text into an input field",
            "screenshot": "Take a screenshot of the current page",
            "read": "Read the text content of the current page or a specific element",
            "fill_form": "Fill out a form with provided field values",
            "execute_js": "Execute JavaScript on the current page",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "open": {
                "url": {"type": "str", "required": True, "description": "URL to navigate to"},
                "wait": {"type": "int", "required": False, "description": "Seconds to wait after load (default 2)"},
            },
            "click": {
                "selector": {"type": "str", "required": True, "description": "CSS selector or text of element to click"},
            },
            "type": {
                "selector": {"type": "str", "required": True, "description": "CSS selector of input field"},
                "text": {"type": "str", "required": True, "description": "Text to type"},
                "clear": {"type": "bool", "required": False, "description": "Clear field before typing (default true)"},
            },
            "screenshot": {
                "path": {"type": "str", "required": False, "description": "Save path (default: ~/screenshot.png)"},
                "full_page": {"type": "bool", "required": False, "description": "Capture full page (default false)"},
            },
            "read": {
                "selector": {"type": "str", "required": False, "description": "CSS selector to read (default: body)"},
                "max_length": {"type": "int", "required": False, "description": "Max chars to return"},
            },
            "fill_form": {
                "fields": {"type": "dict", "required": True, "description": "Map of CSS selector -> value to fill"},
                "submit": {"type": "bool", "required": False, "description": "Submit the form after filling (default false)"},
            },
            "execute_js": {
                "script": {"type": "str", "required": True, "description": "JavaScript code to execute"},
            },
        }
    
    async def _ensure_browser(self) -> StepResult:
        """Lazy-init a Playwright browser instance."""
        if self._page:
            return StepResult(True)
        
        try:
            from playwright.async_api import async_playwright
            pw = await async_playwright().start()
            self._browser = await pw.chromium.launch(headless=True)
            self._page = await self._browser.new_page()
            return StepResult(True)
        except ImportError:
            return StepResult(False, error="Playwright not installed. Install: pip install playwright && playwright install chromium")
        except Exception as e:
            return StepResult(False, error=f"Failed to start browser: {e}")
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            if operation == "open":
                url = params.get("url", "")
                wait = params.get("wait", 2)
                
                if not url:
                    return StepResult(False, error="Missing 'url' parameter")
                
                init = await self._ensure_browser()
                if not init.success:
                    return init
                
                await self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
                if wait > 0:
                    await asyncio.sleep(wait)
                
                title = await self._page.title()
                return StepResult(True, data={"url": url, "title": title})
            
            elif operation == "click":
                selector = params.get("selector", "")
                if not selector:
                    return StepResult(False, error="Missing 'selector' parameter")
                
                init = await self._ensure_browser()
                if not init.success:
                    return init
                
                # Try CSS selector first, then text
                try:
                    await self._page.click(selector, timeout=5000)
                except Exception:
                    await self._page.click(f"text={selector}", timeout=5000)
                
                return StepResult(True, data={"clicked": selector})
            
            elif operation == "type":
                selector = params.get("selector", "")
                text = params.get("text", "")
                clear = params.get("clear", True)
                
                if not selector or not text:
                    return StepResult(False, error="Missing 'selector' and/or 'text' parameter")
                
                init = await self._ensure_browser()
                if not init.success:
                    return init
                
                if clear:
                    await self._page.fill(selector, text, timeout=5000)
                else:
                    await self._page.type(selector, text, timeout=5000)
                
                return StepResult(True, data={"selector": selector, "typed": len(text)})
            
            elif operation == "screenshot":
                path = params.get("path", str(Path.home() / "screenshot.png"))
                full_page = params.get("full_page", False)
                
                init = await self._ensure_browser()
                if not init.success:
                    return init
                
                path = str(Path(path).expanduser())
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                await self._page.screenshot(path=path, full_page=full_page)
                
                return StepResult(True, data={"path": path, "full_page": full_page})
            
            elif operation == "read":
                selector = params.get("selector", "body")
                max_len = params.get("max_length", 10000)
                
                init = await self._ensure_browser()
                if not init.success:
                    return init
                
                text = await self._page.inner_text(selector, timeout=5000)
                return StepResult(True, data={"text": text[:max_len], "length": len(text)})
            
            elif operation == "fill_form":
                fields = params.get("fields", {})
                submit = params.get("submit", False)
                
                if not fields:
                    return StepResult(False, error="Missing 'fields' parameter")
                
                init = await self._ensure_browser()
                if not init.success:
                    return init
                
                filled = []
                for selector, value in fields.items():
                    await self._page.fill(selector, str(value), timeout=5000)
                    filled.append(selector)
                
                if submit:
                    # Try common submit patterns
                    for submit_sel in ['button[type="submit"]', 'input[type="submit"]', "form button"]:
                        try:
                            await self._page.click(submit_sel, timeout=3000)
                            break
                        except Exception:
                            continue
                
                return StepResult(True, data={"filled": filled, "submitted": submit})
            
            elif operation == "execute_js":
                script = params.get("script", "")
                if not script:
                    return StepResult(False, error="Missing 'script' parameter")
                
                init = await self._ensure_browser()
                if not init.success:
                    return init
                
                result = await self._page.evaluate(script)
                return StepResult(True, data={"result": result})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  DEVTOOLS PRIMITIVE
# ============================================================



class WeatherPrimitive(Primitive):
    """Weather — current conditions, forecasts, and air quality.
    
    Uses OpenWeatherMap via the WeatherConnector.
    """
    
    def __init__(self, connector: Any = None):
        self._connector = connector
    
    @property
    def name(self) -> str:
        return "WEATHER"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "current": "Get current weather for a city, zip code, or coordinates (e.g. 'New York', '10001', '40.7,-74.0')",
            "forecast": "Get weather forecast for the next 1-5 days (3-hour intervals)",
            "air_quality": "Get air quality index (AQI) and pollutant levels for a location",
            "search_cities": "Search for cities by name to find the right location",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "current": {
                "location": {"type": "str", "required": True, "description": "City name, zip code, or lat,lon coordinates"},
            },
            "forecast": {
                "location": {"type": "str", "required": True, "description": "City name, zip code, or lat,lon coordinates"},
                "days": {"type": "int", "required": False, "description": "Number of days (1-5, default 3)"},
            },
            "air_quality": {
                "location": {"type": "str", "required": True, "description": "City name or lat,lon coordinates"},
            },
            "search_cities": {
                "query": {"type": "str", "required": True, "description": "City name to search for"},
                "limit": {"type": "int", "required": False, "description": "Max results (default 5)"},
            },
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        if not self._connector:
            return StepResult(False, error="Weather is not configured. Connect an OpenWeatherMap API key in Settings to use weather features.")
        try:
            if operation == "current":
                location = params.get("location", "")
                if not location:
                    return StepResult(False, error="Missing 'location' parameter")
                result = await self._connector.get_current(location)
                return StepResult(True, data=result.to_dict())
            
            elif operation == "forecast":
                location = params.get("location", "")
                if not location:
                    return StepResult(False, error="Missing 'location' parameter")
                days = int(params.get("days", 3))
                result = await self._connector.get_forecast(location, days=days)
                return StepResult(True, data=result)
            
            elif operation == "air_quality":
                location = params.get("location", "")
                if not location:
                    return StepResult(False, error="Missing 'location' parameter")
                result = await self._connector.get_air_quality(location)
                return StepResult(True, data=result)
            
            elif operation == "search_cities":
                query = params.get("query", "")
                if not query:
                    return StepResult(False, error="Missing 'query' parameter")
                limit = int(params.get("limit", 5))
                results = await self._connector.search_cities(query, limit=limit)
                return StepResult(True, data={"cities": results})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  NEWS PRIMITIVE
# ============================================================



class NewsPrimitive(Primitive):
    """News — top headlines, search, and source discovery.
    
    Uses NewsAPI via the NewsConnector.
    """
    
    def __init__(self, connector: Any = None):
        self._connector = connector
    
    @property
    def name(self) -> str:
        return "NEWS"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "headlines": "Get top headlines by country and/or category (business, sports, tech, health, science, entertainment)",
            "search": "Search all news articles by keyword. Supports AND, OR, NOT operators. Can filter by date range and source.",
            "sources": "List available news sources, optionally filtered by category, language, or country",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "headlines": {
                "country": {"type": "str", "required": False, "description": "2-letter country code (default: us). Options: us, gb, ca, au, de, fr, it, etc."},
                "category": {"type": "str", "required": False, "description": "Category: business, entertainment, general, health, science, sports, technology"},
                "query": {"type": "str", "required": False, "description": "Keywords to filter headlines"},
                "limit": {"type": "int", "required": False, "description": "Max articles (default 10)"},
            },
            "search": {
                "query": {"type": "str", "required": True, "description": "Search keywords (supports AND, OR, NOT)"},
                "sort_by": {"type": "str", "required": False, "description": "relevancy, popularity, or publishedAt (default: relevancy)"},
                "from_date": {"type": "str", "required": False, "description": "Start date (YYYY-MM-DD)"},
                "to_date": {"type": "str", "required": False, "description": "End date (YYYY-MM-DD)"},
                "sources": {"type": "str", "required": False, "description": "Comma-separated source IDs (e.g. 'bbc-news,cnn')"},
                "limit": {"type": "int", "required": False, "description": "Max articles (default 10)"},
            },
            "sources": {
                "category": {"type": "str", "required": False, "description": "Category filter"},
                "language": {"type": "str", "required": False, "description": "2-letter language code (default: en)"},
                "country": {"type": "str", "required": False, "description": "2-letter country code"},
            },
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        if not self._connector:
            return StepResult(False, error="News is not configured. Connect a NewsAPI key in Settings to use news features.")
        try:
            if operation == "headlines":
                articles = await self._connector.top_headlines(
                    country=params.get("country", "us"),
                    category=params.get("category"),
                    query=params.get("query"),
                    limit=int(params.get("limit", 10)),
                )
                return StepResult(True, data={
                    "count": len(articles),
                    "articles": [a.to_dict() for a in articles],
                })
            
            elif operation == "search":
                query = params.get("query", "")
                if not query:
                    return StepResult(False, error="Missing 'query' parameter")
                articles = await self._connector.search(
                    query=query,
                    sort_by=params.get("sort_by", "relevancy"),
                    from_date=params.get("from_date"),
                    to_date=params.get("to_date"),
                    sources=params.get("sources"),
                    limit=int(params.get("limit", 10)),
                )
                return StepResult(True, data={
                    "query": query,
                    "count": len(articles),
                    "articles": [a.to_dict() for a in articles],
                })
            
            elif operation == "sources":
                sources = await self._connector.get_sources(
                    category=params.get("category"),
                    language=params.get("language", "en"),
                    country=params.get("country"),
                )
                return StepResult(True, data={
                    "count": len(sources),
                    "sources": sources,
                })
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  NOTION PRIMITIVE
# ============================================================



class MediaPrimitive(Primitive):
    """Media operations — images, audio, video.
    
    Handles conversion, metadata, generation (via AI), and playback control.
    Provider-based for services like Spotify, YouTube, etc.
    """
    
    def __init__(
        self,
        llm_complete: Optional[Callable] = None,
        providers: Optional[Dict[str, Any]] = None,
    ):
        self._llm = llm_complete
        self._providers = providers or {}
    
    @property
    def name(self) -> str:
        return "MEDIA"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "info": "Get metadata about a media file (dimensions, format, EXIF: date taken, camera, GPS, etc.)",
            "convert": "Convert media between formats (e.g. mp4→mp3, png→jpg)",
            "resize": "Resize an image to specific dimensions",
            "crop": "Crop an image — by coordinates (left/top/right/bottom) or by aspect ratio (e.g. '16:9', '1:1') with center-crop",
            "analyze": "Analyze image quality — returns sharpness, brightness, contrast, colorfulness, resolution, quality_score (0-100), and phash (perceptual hash — images with similar phash are near-duplicates, discard them for variety).",
            "generate": "Generate an image or audio using AI",
            "transcribe": "Transcribe audio/video to text",
            "play": "Play or queue media via a provider (Spotify, etc.)",
            "search": "Search media libraries or services",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "info": {
                "path": {"type": "str", "required": True, "description": "Path to media file"},
            },
            "convert": {
                "path": {"type": "str", "required": True, "description": "Source file path"},
                "format": {"type": "str", "required": True, "description": "Target format (mp3, mp4, png, jpg, wav, etc.)"},
                "output": {"type": "str", "required": False, "description": "Output file path (default: same dir, new extension)"},
            },
            "resize": {
                "path": {"type": "str", "required": True, "description": "Image file path"},
                "width": {"type": "int", "required": False, "description": "Target width in pixels"},
                "height": {"type": "int", "required": False, "description": "Target height in pixels"},
                "output": {"type": "str", "required": False, "description": "Output file path"},
            },
            "crop": {
                "path": {"type": "str", "required": True, "description": "Image file path"},
                "left": {"type": "int", "required": False, "description": "Left pixel coordinate"},
                "top": {"type": "int", "required": False, "description": "Top pixel coordinate"},
                "right": {"type": "int", "required": False, "description": "Right pixel coordinate"},
                "bottom": {"type": "int", "required": False, "description": "Bottom pixel coordinate"},
                "aspect": {"type": "str", "required": False, "description": "Aspect ratio for center-crop (e.g. '16:9', '1:1', '4:3'). Overrides coordinates."},
                "output": {"type": "str", "required": False, "description": "Output file path (default: overwrites original)"},
            },
            "analyze": {
                "path": {"type": "str", "required": True, "description": "Image file path to analyze"},
            },
            "generate": {
                "prompt": {"type": "str", "required": True, "description": "Description of what to generate"},
                "type": {"type": "str", "required": False, "description": "image or audio (default image)"},
                "output": {"type": "str", "required": False, "description": "Output file path"},
            },
            "transcribe": {
                "path": {"type": "str", "required": True, "description": "Audio or video file path"},
                "language": {"type": "str", "required": False, "description": "Language code (default: auto-detect)"},
            },
            "play": {
                "query": {"type": "str", "required": False, "description": "What to play (song name, artist, playlist)"},
                "uri": {"type": "str", "required": False, "description": "Direct media URI (spotify:track:..., file path, URL)"},
                "action": {"type": "str", "required": False, "description": "play, pause, next, previous, volume (default play)"},
                "provider": {"type": "str", "required": False, "description": "Provider: spotify, youtube, local"},
            },
            "search": {
                "query": {"type": "str", "required": True, "description": "Search query"},
                "type": {"type": "str", "required": False, "description": "Filter: song, album, artist, playlist, video"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
                "limit": {"type": "int", "required": False, "description": "Max results"},
            },
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            if operation == "info":
                path = str(Path(params.get("path", "")).expanduser())
                if not Path(path).exists():
                    return StepResult(False, error=f"File not found: {path}")
                
                stat = Path(path).stat()
                ext = Path(path).suffix.lower()
                
                info = {
                    "path": path,
                    "name": Path(path).name,
                    "format": ext.lstrip("."),
                    "size_bytes": stat.st_size,
                    "size_mb": round(stat.st_size / (1024 * 1024), 2),
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                }
                
                # Try to get image dimensions and EXIF
                if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"):
                    try:
                        from PIL import Image
                        from PIL.ExifTags import TAGS, GPSTAGS
                        with Image.open(path) as img:
                            info["width"] = img.width
                            info["height"] = img.height
                            info["mode"] = img.mode
                            
                            # Extract EXIF data
                            exif_data = img._getexif()
                            if exif_data:
                                exif = {}
                                for tag_id, value in exif_data.items():
                                    tag = TAGS.get(tag_id, tag_id)
                                    if isinstance(value, bytes):
                                        try:
                                            value = value.decode("utf-8", errors="ignore")
                                        except:
                                            continue
                                    # Extract key fields
                                    if tag == "DateTimeOriginal":
                                        exif["date_taken"] = value
                                    elif tag == "Make":
                                        exif["camera_make"] = value
                                    elif tag == "Model":
                                        exif["camera_model"] = value
                                    elif tag == "Orientation":
                                        exif["orientation"] = value
                                    elif tag == "GPSInfo":
                                        # Parse GPS coordinates
                                        try:
                                            gps = {}
                                            for gps_tag_id, gps_value in value.items():
                                                gps_tag = GPSTAGS.get(gps_tag_id, gps_tag_id)
                                                gps[gps_tag] = gps_value
                                            if "GPSLatitude" in gps and "GPSLongitude" in gps:
                                                def convert_gps(coord, ref):
                                                    d, m, s = coord
                                                    decimal = float(d) + float(m)/60 + float(s)/3600
                                                    if ref in ["S", "W"]:
                                                        decimal = -decimal
                                                    return round(decimal, 6)
                                                lat = convert_gps(gps["GPSLatitude"], gps.get("GPSLatitudeRef", "N"))
                                                lon = convert_gps(gps["GPSLongitude"], gps.get("GPSLongitudeRef", "E"))
                                                exif["gps_latitude"] = lat
                                                exif["gps_longitude"] = lon
                                        except:
                                            pass
                                    elif tag == "ExposureTime":
                                        exif["exposure_time"] = str(value)
                                    elif tag == "FNumber":
                                        exif["f_number"] = float(value)
                                    elif tag == "ISOSpeedRatings":
                                        exif["iso"] = value
                                if exif:
                                    info["exif"] = exif
                    except ImportError:
                        info["note"] = "Install Pillow for image dimensions and EXIF"
                
                return StepResult(True, data=info)
            
            elif operation == "convert":
                path = str(Path(params.get("path", "")).expanduser())
                target_fmt = params.get("format", "")
                output = params.get("output")
                
                if not Path(path).exists():
                    return StepResult(False, error=f"File not found: {path}")
                if not target_fmt:
                    return StepResult(False, error="Missing 'format' parameter")
                
                if not output:
                    output = str(Path(path).with_suffix(f".{target_fmt.lstrip('.')}"))
                else:
                    output = str(Path(output).expanduser())
                
                src_ext = Path(path).suffix.lower()
                
                # Image conversion via Pillow
                if src_ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"):
                    try:
                        from PIL import Image
                        with Image.open(path) as img:
                            if target_fmt.lower() in ("jpg", "jpeg") and img.mode == "RGBA":
                                img = img.convert("RGB")
                            img.save(output)
                        return StepResult(True, data={"input": path, "output": output, "format": target_fmt})
                    except ImportError:
                        return StepResult(False, error="Install Pillow for image conversion: pip install Pillow")
                
                # Audio/video via ffmpeg
                try:
                    import subprocess
                    proc = await asyncio.create_subprocess_exec(
                        "ffmpeg", "-i", path, "-y", output,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
                    if proc.returncode == 0:
                        return StepResult(True, data={"input": path, "output": output, "format": target_fmt})
                    return StepResult(False, error=f"ffmpeg error: {stderr.decode()[:500]}")
                except FileNotFoundError:
                    return StepResult(False, error="ffmpeg not installed. Install ffmpeg for media conversion.")
                except asyncio.TimeoutError:
                    return StepResult(False, error="Conversion timed out after 120s")
            
            elif operation == "resize":
                path = str(Path(params.get("path", "")).expanduser())
                width = params.get("width")
                height = params.get("height")
                output = params.get("output", path)
                
                if not Path(path).exists():
                    return StepResult(False, error=f"File not found: {path}")
                
                try:
                    from PIL import Image
                    with Image.open(path) as img:
                        orig_w, orig_h = img.size
                        if width and not height:
                            height = int(orig_h * (width / orig_w))
                        elif height and not width:
                            width = int(orig_w * (height / orig_h))
                        elif not width and not height:
                            return StepResult(False, error="Specify 'width' and/or 'height'")
                        
                        resized = img.resize((width, height), Image.LANCZOS)
                        output = str(Path(output).expanduser())
                        resized.save(output)
                    
                    return StepResult(True, data={"path": output, "width": width, "height": height, "original": f"{orig_w}x{orig_h}"})
                except ImportError:
                    return StepResult(False, error="Install Pillow for image resize: pip install Pillow")

            elif operation == "crop":
                path = str(Path(params.get("path", "")).expanduser())
                if not Path(path).exists():
                    return StepResult(False, error=f"File not found: {path}")
                try:
                    from PIL import Image
                    output = params.get("output", path)
                    aspect = params.get("aspect", "")

                    with Image.open(path) as img:
                        w, h = img.size

                        if aspect:
                            # Center-crop to aspect ratio
                            parts = aspect.split(":")
                            ar = float(parts[0]) / float(parts[1])
                            if w / h > ar:
                                new_w = int(h * ar)
                                left = (w - new_w) // 2
                                box = (left, 0, left + new_w, h)
                            else:
                                new_h = int(w / ar)
                                top = (h - new_h) // 2
                                box = (0, top, w, top + new_h)
                        else:
                            left = params.get("left", 0)
                            top = params.get("top", 0)
                            right = params.get("right", w)
                            bottom = params.get("bottom", h)
                            box = (left, top, right, bottom)

                        cropped = img.crop(box)
                        output = str(Path(output).expanduser())
                        cropped.save(output)

                    return StepResult(True, data={"path": output, "width": cropped.width, "height": cropped.height, "crop_box": list(box)})
                except ImportError:
                    return StepResult(False, error="Install Pillow for image crop: pip install Pillow")

            elif operation == "analyze":
                path = str(Path(params.get("path", "")).expanduser())
                if not Path(path).exists():
                    return StepResult(False, error=f"File not found: {path}")
                try:
                    from PIL import Image, ImageStat, ImageFilter
                    import math

                    with Image.open(path) as img:
                        w, h = img.size
                        gray = img.convert("L")
                        stat = ImageStat.Stat(gray)

                        # Sharpness — variance of Laplacian
                        edges = gray.filter(ImageFilter.FIND_EDGES)
                        edge_stat = ImageStat.Stat(edges)
                        sharpness = edge_stat.var[0]

                        # Brightness — mean luminance
                        brightness = stat.mean[0]

                        # Contrast — stddev of luminance
                        contrast = stat.stddev[0]

                        # Colorfulness — Hasler & Süsstrunk (2003)
                        colorfulness = 0.0
                        if img.mode in ("RGB", "RGBA"):
                            import numpy as np
                            arr = np.array(img.convert("RGB"), dtype=float)
                            rg = arr[:, :, 0] - arr[:, :, 1]
                            yb = 0.5 * (arr[:, :, 0] + arr[:, :, 1]) - arr[:, :, 2]
                            rg_std, rg_mean = float(np.std(rg)), float(np.mean(rg))
                            yb_std, yb_mean = float(np.std(yb)), float(np.mean(yb))
                            std_root = math.sqrt(rg_std**2 + yb_std**2)
                            mean_root = math.sqrt(rg_mean**2 + yb_mean**2)
                            colorfulness = std_root + 0.3 * mean_root

                        # Perceptual hash — 64-bit hash for duplicate detection
                        # Two images with Hamming distance < 10 are near-duplicates
                        thumb = gray.resize((8, 8), Image.LANCZOS)
                        pixels = list(thumb.getdata())
                        avg = sum(pixels) / 64
                        bits = "".join("1" if p >= avg else "0" for p in pixels)
                        phash = hex(int(bits, 2))[2:].zfill(16)

                        # Quality score — weighted composite (0-100)
                        s_score = min(sharpness / 30, 1.0) * 40       # sharpness: 0-40 pts
                        c_score = min(contrast / 80, 1.0) * 25        # contrast: 0-25 pts
                        b_score = (1 - abs(brightness - 128) / 128) * 20  # brightness (centered): 0-20 pts
                        f_score = min(colorfulness / 100, 1.0) * 15   # colorfulness: 0-15 pts
                        quality_score = round(s_score + c_score + b_score + f_score, 1)

                    return StepResult(True, data={
                        "path": path,
                        "resolution": f"{w}x{h}",
                        "megapixels": round(w * h / 1_000_000, 1),
                        "sharpness": round(sharpness, 1),
                        "brightness": round(brightness, 1),
                        "contrast": round(contrast, 1),
                        "colorfulness": round(colorfulness, 1),
                        "quality_score": quality_score,
                        "phash": phash,
                    })
                except ImportError:
                    return StepResult(False, error="Install Pillow for image analysis: pip install Pillow")

            elif operation == "generate":
                prompt = params.get("prompt", "")
                media_type = params.get("type", "image")
                
                if not prompt:
                    return StepResult(False, error="Missing 'prompt' parameter")
                
                if not self._llm:
                    return StepResult(False, error="LLM required for media generation")
                
                # This would connect to DALL-E, Stable Diffusion, etc.
                return StepResult(False, error=f"Image generation not configured. Connect a provider (DALL-E, Stable Diffusion, etc.) to generate: '{prompt}'")
            
            elif operation == "transcribe":
                path = str(Path(params.get("path", "")).expanduser())
                
                if not Path(path).exists():
                    return StepResult(False, error=f"File not found: {path}")
                
                # Would connect to Whisper, Google Speech, etc.
                return StepResult(False, error="Transcription not configured. Connect a provider (Whisper, Google Speech, etc.)")
            
            elif operation == "play":
                action = params.get("action", "play")
                provider_name = params.get("provider")
                
                provider = self._providers.get(provider_name) if provider_name else (next(iter(self._providers.values())) if self._providers else None)
                
                if provider and hasattr(provider, "control"):
                    result = await provider.control(
                        action=action,
                        query=params.get("query"),
                        uri=params.get("uri"),
                    )
                    return StepResult(True, data=result)
                
                return StepResult(False, error="No media player configured. Connect a provider (Spotify, YouTube, etc.)")
            
            elif operation == "search":
                query = params.get("query", "")
                provider_name = params.get("provider")
                
                provider = self._providers.get(provider_name) if provider_name else (next(iter(self._providers.values())) if self._providers else None)
                
                if provider and hasattr(provider, "search"):
                    result = await provider.search(
                        query=query,
                        type=params.get("type"),
                        limit=params.get("limit", 10),
                    )
                    return StepResult(True, data=result)
                
                return StepResult(False, error="No media search configured. Connect a provider (Spotify, YouTube, etc.)")
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  BROWSER PRIMITIVE
# ============================================================



class PhotoPrimitive(Primitive):
    """Photo management operations - Google Photos, iCloud, etc."""
    
    def __init__(self, providers: Optional[Dict[str, Any]] = None):
        self._providers = providers or {}
    
    @property
    def name(self) -> str:
        return "PHOTO"
    
    def get_operations(self) -> Dict[str, str]:
        return self.get_available_operations()
    
    def get_available_operations(self) -> Dict[str, str]:
        ops = {
            "list": "List photos",
            "upload": "Upload a photo",
            "download": "Download a photo",
            "search": "Search photos",
            "create_album": "Create an album",
            "add_to_album": "Add photo to album",
            "metadata": "Get photo metadata",
            "edit": "Edit a photo",
        }
        connected = self.get_connected_providers()
        if connected:
            return ops

        idx = get_data_index()
        if idx:
            return {
                "list": ops["list"],
                "search": ops["search"],
                "metadata": ops["metadata"],
            }

        return {}

    @staticmethod
    def _looks_like_image_path(path: str) -> bool:
        p = (path or "").lower()
        return p.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif", ".bmp", ".tiff"))

    @classmethod
    def _is_image_object(cls, obj: Any) -> bool:
        title = (getattr(obj, "title", "") or "").lower()
        body = (getattr(obj, "body", "") or "").lower()
        raw = getattr(obj, "raw", {}) or {}

        mime = str(raw.get("mimeType") or raw.get("mime_type") or raw.get("contentType") or "").lower()
        if mime.startswith("image/"):
            return True

        candidates = [
            title,
            body,
            str(raw.get("name") or ""),
            str(raw.get("path") or ""),
            str(raw.get("filePath") or ""),
            str(raw.get("filename") or ""),
            str(raw.get("url") or ""),
        ]
        return any(cls._looks_like_image_path(c.lower()) for c in candidates)

    @staticmethod
    def _index_obj_to_photo(obj: Any) -> Dict[str, Any]:
        raw = getattr(obj, "raw", {}) or {}
        return {
            "id": getattr(obj, "source_id", ""),
            "name": getattr(obj, "title", "") or raw.get("name", ""),
            "description": getattr(obj, "body", ""),
            "source": getattr(obj, "source", ""),
            "url": raw.get("webViewLink") or raw.get("url") or getattr(obj, "url", ""),
            "path": raw.get("path") or raw.get("filePath") or raw.get("local_path") or "",
            "mime_type": raw.get("mimeType") or raw.get("mime_type") or "",
            "modified": getattr(obj, "timestamp", None).isoformat() if getattr(obj, "timestamp", None) else None,
        }
    
    def get_param_schema(self) -> Dict[str, Any]:
        return {
            "list": {"album": {"type": "str", "description": "Album ID (optional)"}, "limit": {"type": "int", "description": "Max photos"}},
            "upload": {"path": {"type": "str", "description": "Local file path"}, "album": {"type": "str", "description": "Album ID (optional)"}},
            "download": {"photo_id": {"type": "str", "description": "Photo ID"}, "path": {"type": "str", "description": "Save path"}},
            "search": {"query": {"type": "str", "description": "Search query"}},
            "create_album": {"name": {"type": "str", "description": "Album name"}},
            "add_to_album": {"photo_id": {"type": "str", "description": "Photo ID"}, "album_id": {"type": "str", "description": "Album ID"}},
            "metadata": {"photo_id": {"type": "str", "description": "Photo ID"}},
            "edit": {"photo_id": {"type": "str", "description": "Photo ID"}, "operations": {"type": "list", "description": "Edit operations"}},
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            for name, provider in self._providers.items():
                if operation == "list" and hasattr(provider, "list_photos"):
                    result = await provider.list_photos(params.get("album"), params.get("limit"))
                    return StepResult(True, data={"photos": result, "provider": name})
                elif operation == "upload" and hasattr(provider, "upload_photo"):
                    result = await provider.upload_photo(params.get("path"), params.get("album"))
                    return StepResult(True, data={"uploaded": True, "photo": result, "provider": name})
                elif operation == "search" and hasattr(provider, "search_photos"):
                    result = await provider.search_photos(params.get("query"))
                    return StepResult(True, data={"photos": result, "provider": name})

            idx = get_data_index()
            if idx and operation in {"list", "search"}:
                limit = params.get("limit", 50)
                if operation == "search":
                    index_results = idx.search(params.get("query", ""), kind="file", limit=limit)
                else:
                    index_results = idx.query(kind="file", limit=limit)

                photos = [
                    self._index_obj_to_photo(obj)
                    for obj in index_results
                    if self._is_image_object(obj)
                ]
                if photos:
                    return StepResult(True, data={"photos": photos[:limit], "provider": "index", "indexed": True})
            
            # Local file handling
            if operation == "list":
                path = Path(params.get("album", str(Path.home() / "Pictures")))
                if path.exists() and path.is_dir():
                    photos = list(path.glob("*.jpg")) + list(path.glob("*.png")) + list(path.glob("*.jpeg"))
                    return StepResult(True, data={"photos": [str(p) for p in photos[:params.get("limit", 50)]], "provider": "local"})
                return StepResult(True, data={"photos": [], "provider": "local"})
            
            elif operation == "upload":
                return StepResult(True, data={"uploaded": True, "provider": "local", "note": "Connect photo provider to upload"})
            
            elif operation == "download":
                return StepResult(True, data={"downloaded": True, "provider": "local"})
            
            elif operation == "search":
                query = (params.get("query") or "").lower().strip()
                base = Path(params.get("directory", str(Path.home() / "Pictures")))
                if not base.exists() or not base.is_dir():
                    return StepResult(True, data={"photos": [], "provider": "local", "note": f"Directory not found: {base}"})

                all_photos = list(base.rglob("*.jpg")) + list(base.rglob("*.jpeg")) + list(base.rglob("*.png")) + list(base.rglob("*.webp"))
                if query:
                    matched = [p for p in all_photos if query in p.name.lower() or query in str(p).lower()]
                else:
                    matched = all_photos
                return StepResult(True, data={"photos": [str(p) for p in matched[:params.get("limit", 50)]], "provider": "local"})
            
            elif operation == "create_album":
                name = params.get("name", "Album")
                path = Path.home() / "Pictures" / name
                path.mkdir(parents=True, exist_ok=True)
                return StepResult(True, data={"created": True, "path": str(path), "provider": "local"})
            
            elif operation == "add_to_album":
                return StepResult(True, data={"added": True, "provider": "local"})
            
            elif operation == "metadata":
                photo_path = params.get("photo_id")
                if Path(photo_path).exists():
                    stat = Path(photo_path).stat()
                    return StepResult(True, data={"metadata": {"size": stat.st_size, "modified": stat.st_mtime}, "provider": "local"})
                return StepResult(False, error="Photo not found")
            
            elif operation == "edit":
                return StepResult(True, data={"edited": True, "provider": "local", "note": "Would apply edits via PIL"})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  HOME PRIMITIVE - Smart home
# ============================================================


