"""
LinkedIn Connector - LinkedIn Profile & Posts

Profile, posts, shares, and organization info via LinkedIn REST API v2.

Setup:
    1. Go to https://www.linkedin.com/developers/apps → Create App
    2. Request products: "Share on LinkedIn", "Sign In with LinkedIn using OpenID Connect"
    3. Generate an OAuth 2.0 access token with scopes: openid, profile, email, w_member_social
    
    export LINKEDIN_ACCESS_TOKEN="your-access-token"

    from connectors.linkedin import LinkedInConnector
    linkedin = LinkedInConnector(access_token="...")
"""

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

BASE_URL = "https://api.linkedin.com/v2"
REST_URL = "https://api.linkedin.com/rest"


class LinkedInConnector:
    """LinkedIn profile, posts, and shares via REST API."""

    def __init__(self, access_token: Optional[str] = None):
        self.access_token = access_token or os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
        self.connected = bool(self.access_token)
        self._person_urn = ""

    async def connect(self) -> bool:
        """Validate LinkedIn API credentials."""
        self.connected = bool(self.access_token)
        return self.connected

    def _headers(self, version: str = "202304") -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "LinkedIn-Version": version,
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }

    async def _get(self, url: str, params: Optional[Dict] = None) -> Any:
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=self._headers(), params=params or {})
            resp.raise_for_status()
            return resp.json()

    async def _post(self, url: str, data: Dict) -> Any:
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=self._headers(), json=data)
            resp.raise_for_status()
            return resp.json() if resp.content else {}

    async def _get_person_urn(self) -> str:
        """Get the current user's person URN."""
        if self._person_urn:
            return self._person_urn
        profile = await self.me()
        self._person_urn = f"urn:li:person:{profile['id']}"
        return self._person_urn

    # ── Profile ──

    async def me(self) -> Dict:
        """Get the current authenticated user's profile."""
        data = await self._get(f"{BASE_URL}/userinfo")
        return {
            "id": data.get("sub", ""),
            "name": data.get("name", ""),
            "email": data.get("email", ""),
            "picture": data.get("picture", ""),
            "locale": data.get("locale", ""),
        }

    # ── Posts ──

    async def create_post(
        self,
        text: str,
        visibility: str = "PUBLIC",
        article_url: Optional[str] = None,
        article_title: Optional[str] = None,
        article_description: Optional[str] = None,
    ) -> Dict:
        """Create a text or article post on LinkedIn.
        
        Args:
            text: Post text content
            visibility: 'PUBLIC' or 'CONNECTIONS'
            article_url: URL to share as an article
            article_title: Title for the article link
            article_description: Description for the article link
        """
        author = await self._get_person_urn()
        
        body: Dict[str, Any] = {
            "author": author,
            "lifecycleState": "PUBLISHED",
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": visibility,
            },
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE",
                },
            },
        }

        if article_url:
            share = body["specificContent"]["com.linkedin.ugc.ShareContent"]
            share["shareMediaCategory"] = "ARTICLE"
            media: Dict[str, Any] = {
                "status": "READY",
                "originalUrl": article_url,
            }
            if article_title:
                media["title"] = {"text": article_title}
            if article_description:
                media["description"] = {"text": article_description}
            share["media"] = [media]

        data = await self._post(f"{BASE_URL}/ugcPosts", body)
        return {
            "id": data.get("id", ""),
            "status": "published",
            "visibility": visibility,
        }

    async def get_posts(self, limit: int = 10) -> List[Dict]:
        """Get the current user's recent posts.
        
        Args:
            limit: Max posts to return (default 10)
        """
        author = await self._get_person_urn()
        data = await self._get(f"{BASE_URL}/ugcPosts", {
            "q": "authors",
            "authors": f"List({author})",
            "count": str(limit),
        })
        posts = []
        for p in data.get("elements", []):
            share = p.get("specificContent", {}).get("com.linkedin.ugc.ShareContent", {})
            post: Dict[str, Any] = {
                "id": p.get("id", ""),
                "text": share.get("shareCommentary", {}).get("text", ""),
                "created_at": p.get("created", {}).get("time"),
                "visibility": p.get("visibility", {}).get("com.linkedin.ugc.MemberNetworkVisibility", ""),
                "lifecycle_state": p.get("lifecycleState", ""),
            }
            media = share.get("media", [])
            if media:
                post["media"] = [{
                    "url": m.get("originalUrl", ""),
                    "title": m.get("title", {}).get("text", ""),
                } for m in media]
            posts.append(post)
        return posts

    async def delete_post(self, post_urn: str) -> bool:
        """Delete a post.
        
        Args:
            post_urn: Post URN (e.g. "urn:li:ugcPost:123456")
        """
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.delete(
                f"{BASE_URL}/ugcPosts/{post_urn}",
                headers=self._headers(),
            )
            resp.raise_for_status()
            return True

    # ── Network ──

    async def get_connections_count(self) -> Dict:
        """Get the current user's network statistics."""
        data = await self._get(f"{BASE_URL}/networkSizes/urn:li:person:me", {
            "edgeType": "CompanyFollowedByMember",
        })
        return {
            "first_degree_size": data.get("firstDegreeSize", 0),
        }

    # ── Organization ──

    async def get_organization(self, org_id: str) -> Dict:
        """Get organization details.
        
        Args:
            org_id: Organization ID (numeric)
        """
        data = await self._get(f"{BASE_URL}/organizations/{org_id}")
        return {
            "id": data.get("id"),
            "name": data.get("localizedName", ""),
            "vanity_name": data.get("vanityName", ""),
            "description": data.get("localizedDescription", "")[:500] if data.get("localizedDescription") else "",
            "website": data.get("localizedWebsite", ""),
            "industry": data.get("localizedSpecialties", []),
            "staff_count_range": data.get("staffCountRange", ""),
        }

    async def search_companies(self, keywords: str, limit: int = 10) -> List[Dict]:
        """Search for companies/organizations.
        
        Args:
            keywords: Search keywords
            limit: Max results (default 10)
        """
        data = await self._get(f"{BASE_URL}/search/blended", {
            "q": "all",
            "keywords": keywords,
            "count": str(limit),
            "filters": "List(resultType->COMPANIES)",
        })
        results = []
        for elem in data.get("elements", []):
            for e in elem.get("elements", []):
                info = e.get("title", {}).get("text", "")
                results.append({
                    "name": info,
                    "url": e.get("navigationUrl", ""),
                    "headline": e.get("headline", {}).get("text", ""),
                })
        return results[:limit]
