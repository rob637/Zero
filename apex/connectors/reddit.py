"""
Reddit Connector - Reddit Posts, Comments & Subreddits

Browse, search, post, and comment via Reddit's OAuth API.

Setup:
    1. Go to https://www.reddit.com/prefs/apps → Create app (script type)
    2. Note client_id (under app name) and client_secret
    3. Generate a refresh token or use username/password auth
    
    export REDDIT_CLIENT_ID="your-client-id"
    export REDDIT_CLIENT_SECRET="your-client-secret"
    export REDDIT_USERNAME="your-username"
    export REDDIT_PASSWORD="your-password"

    from connectors.reddit import RedditConnector
    reddit = RedditConnector()
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

OAUTH_URL = "https://oauth.reddit.com"
AUTH_URL = "https://www.reddit.com/api/v1/access_token"
USER_AGENT = "Ziggy:AI-OS:v1.0 (by /u/ziggy_ai)"


class RedditConnector:
    """Reddit posts, comments, and subreddits via OAuth API."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        refresh_token: Optional[str] = None,
    ):
        self.client_id = client_id or os.environ.get("REDDIT_CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get("REDDIT_CLIENT_SECRET", "")
        self.username = username or os.environ.get("REDDIT_USERNAME", "")
        self.password = password or os.environ.get("REDDIT_PASSWORD", "")
        self.refresh_token = refresh_token or os.environ.get("REDDIT_REFRESH_TOKEN", "")
        self._access_token = ""
        self._token_expires = 0
        self.connected = bool(self.client_id and self.client_secret)

    async def _get_token(self) -> str:
        """Get or refresh OAuth access token."""
        if self._access_token and time.time() < self._token_expires:
            return self._access_token

        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            if self.refresh_token:
                data = {"grant_type": "refresh_token", "refresh_token": self.refresh_token}
            else:
                data = {
                    "grant_type": "password",
                    "username": self.username,
                    "password": self.password,
                }
            resp = await client.post(
                AUTH_URL,
                auth=(self.client_id, self.client_secret),
                data=data,
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            result = resp.json()
            self._access_token = result["access_token"]
            self._token_expires = time.time() + result.get("expires_in", 3600) - 60
            return self._access_token

    async def _get(self, path: str, params: Optional[Dict] = None) -> Any:
        import httpx
        token = await self._get_token()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{OAUTH_URL}{path}",
                headers={"Authorization": f"bearer {token}", "User-Agent": USER_AGENT},
                params=params or {},
            )
            resp.raise_for_status()
            return resp.json()

    async def _post(self, path: str, data: Optional[Dict] = None) -> Any:
        import httpx
        token = await self._get_token()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{OAUTH_URL}{path}",
                headers={"Authorization": f"bearer {token}", "User-Agent": USER_AGENT},
                data=data or {},
            )
            resp.raise_for_status()
            return resp.json()

    # ── User ──

    async def me(self) -> Dict:
        """Get the current authenticated user's profile."""
        data = await self._get("/api/v1/me")
        return {
            "name": data.get("name", ""),
            "id": data.get("id", ""),
            "comment_karma": data.get("comment_karma", 0),
            "link_karma": data.get("link_karma", 0),
            "created_utc": data.get("created_utc"),
            "has_verified_email": data.get("has_verified_email", False),
        }

    # ── Subreddits ──

    async def get_subreddit(self, name: str) -> Dict:
        """Get subreddit info.
        
        Args:
            name: Subreddit name (without /r/)
        """
        data = await self._get(f"/r/{name}/about")
        d = data.get("data", {})
        return {
            "name": d.get("display_name", ""),
            "title": d.get("title", ""),
            "description": (d.get("public_description", "") or "")[:500],
            "subscribers": d.get("subscribers", 0),
            "active_users": d.get("accounts_active", 0),
            "created_utc": d.get("created_utc"),
            "nsfw": d.get("over18", False),
            "url": f"https://reddit.com/r/{d.get('display_name', name)}",
        }

    async def get_posts(
        self,
        subreddit: str,
        sort: str = "hot",
        time_filter: str = "day",
        limit: int = 25,
    ) -> List[Dict]:
        """Get posts from a subreddit.
        
        Args:
            subreddit: Subreddit name (without /r/)
            sort: 'hot', 'new', 'top', 'rising', 'controversial'
            time_filter: For 'top'/'controversial': 'hour', 'day', 'week', 'month', 'year', 'all'
            limit: Max posts (default 25, max 100)
        """
        params: Dict[str, Any] = {"limit": min(limit, 100)}
        if sort in ("top", "controversial"):
            params["t"] = time_filter
        
        data = await self._get(f"/r/{subreddit}/{sort}", params)
        return [self._parse_post(p["data"]) for p in data.get("data", {}).get("children", []) if p.get("kind") == "t3"]

    async def get_post(self, subreddit: str, post_id: str, comment_limit: int = 10) -> Dict:
        """Get a post with top comments.
        
        Args:
            subreddit: Subreddit name
            post_id: Post ID (the alphanumeric part, not full name)
            comment_limit: Max top-level comments (default 10)
        """
        data = await self._get(f"/r/{subreddit}/comments/{post_id}", {"limit": comment_limit})
        
        # First listing is the post, second is comments
        post_data = data[0]["data"]["children"][0]["data"]
        result = self._parse_post(post_data)
        result["selftext"] = post_data.get("selftext", "")[:2000]
        
        comments = []
        for c in data[1]["data"]["children"]:
            if c.get("kind") != "t1":
                continue
            cd = c["data"]
            comments.append({
                "id": cd.get("id", ""),
                "author": cd.get("author", "[deleted]"),
                "body": (cd.get("body", "") or "")[:500],
                "score": cd.get("score", 0),
                "created_utc": cd.get("created_utc"),
            })
        result["comments"] = comments
        return result

    # ── Search ──

    async def search(
        self,
        query: str,
        subreddit: Optional[str] = None,
        sort: str = "relevance",
        time_filter: str = "all",
        limit: int = 25,
    ) -> List[Dict]:
        """Search for posts.
        
        Args:
            query: Search query
            subreddit: Limit to subreddit (optional)
            sort: 'relevance', 'hot', 'top', 'new', 'comments'
            time_filter: 'hour', 'day', 'week', 'month', 'year', 'all'
            limit: Max results (default 25)
        """
        path = f"/r/{subreddit}/search" if subreddit else "/search"
        params = {
            "q": query,
            "sort": sort,
            "t": time_filter,
            "limit": min(limit, 100),
            "restrict_sr": "true" if subreddit else "false",
        }
        data = await self._get(path, params)
        return [self._parse_post(p["data"]) for p in data.get("data", {}).get("children", []) if p.get("kind") == "t3"]

    # ── Posting ──

    async def submit_post(
        self,
        subreddit: str,
        title: str,
        text: Optional[str] = None,
        url: Optional[str] = None,
    ) -> Dict:
        """Submit a new post.
        
        Args:
            subreddit: Target subreddit
            title: Post title
            text: Self-post body text (for text posts)
            url: URL to share (for link posts)
        """
        data: Dict[str, Any] = {
            "sr": subreddit,
            "title": title,
            "api_type": "json",
        }
        if url:
            data["kind"] = "link"
            data["url"] = url
        else:
            data["kind"] = "self"
            data["text"] = text or ""

        result = await self._post("/api/submit", data)
        json_data = result.get("json", {}).get("data", {})
        return {
            "id": json_data.get("id", ""),
            "name": json_data.get("name", ""),
            "url": json_data.get("url", ""),
        }

    async def add_comment(self, parent_fullname: str, text: str) -> Dict:
        """Add a comment to a post or reply to a comment.
        
        Args:
            parent_fullname: Full name of parent (e.g. "t3_abc123" for post, "t1_xyz" for comment)
            text: Comment body (supports markdown)
        """
        result = await self._post("/api/comment", {
            "thing_id": parent_fullname,
            "text": text,
            "api_type": "json",
        })
        comment = result.get("json", {}).get("data", {}).get("things", [{}])[0].get("data", {})
        return {
            "id": comment.get("id", ""),
            "name": comment.get("name", ""),
            "body": comment.get("body", text),
        }

    # ── User Content ──

    async def get_user_posts(self, username: Optional[str] = None, limit: int = 25) -> List[Dict]:
        """Get a user's submitted posts.
        
        Args:
            username: Reddit username (default: authenticated user)
            limit: Max posts (default 25)
        """
        user = username or self.username or "me"
        path = f"/user/{user}/submitted" if user != "me" else "/user/me/submitted"
        data = await self._get(path, {"limit": min(limit, 100)})
        return [self._parse_post(p["data"]) for p in data.get("data", {}).get("children", []) if p.get("kind") == "t3"]

    async def get_saved(self, limit: int = 25) -> List[Dict]:
        """Get the user's saved posts and comments.
        
        Args:
            limit: Max items (default 25)
        """
        data = await self._get("/user/me/saved", {"limit": min(limit, 100)})
        items = []
        for item in data.get("data", {}).get("children", []):
            d = item["data"]
            if item["kind"] == "t3":
                items.append(self._parse_post(d))
            elif item["kind"] == "t1":
                items.append({
                    "type": "comment",
                    "id": d.get("id", ""),
                    "author": d.get("author", ""),
                    "body": (d.get("body", "") or "")[:500],
                    "subreddit": d.get("subreddit", ""),
                    "score": d.get("score", 0),
                    "link_title": d.get("link_title", ""),
                })
        return items

    # ── Helpers ──

    def _parse_post(self, d: Dict) -> Dict:
        """Parse a post into a clean dict."""
        result: Dict[str, Any] = {
            "id": d.get("id", ""),
            "title": d.get("title", ""),
            "subreddit": d.get("subreddit", ""),
            "author": d.get("author", "[deleted]"),
            "score": d.get("score", 0),
            "num_comments": d.get("num_comments", 0),
            "url": d.get("url", ""),
            "permalink": f"https://reddit.com{d.get('permalink', '')}",
            "created_utc": d.get("created_utc"),
        }
        if d.get("is_self"):
            result["type"] = "text"
            if d.get("selftext"):
                result["preview"] = d["selftext"][:300]
        else:
            result["type"] = "link"
        if d.get("link_flair_text"):
            result["flair"] = d["link_flair_text"]
        if d.get("over_18"):
            result["nsfw"] = True
        if d.get("stickied"):
            result["stickied"] = True
        return result
