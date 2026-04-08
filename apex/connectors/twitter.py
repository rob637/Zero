"""
Twitter/X Connector

Twitter API v2 integration for social media operations.

Usage:
    from connectors.twitter import TwitterConnector
    
    twitter = TwitterConnector()
    await twitter.connect()
    
    # Post tweet
    tweet = await twitter.post_tweet("Hello world!")
    
    # Search tweets
    results = await twitter.search("python programming")
    
    # Get user timeline
    tweets = await twitter.get_user_tweets("elonmusk")
"""

import asyncio
import os
import time
import hmac
import hashlib
import base64
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from urllib.parse import quote, urlencode

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


@dataclass
class Tweet:
    """Represents a tweet."""
    id: str
    text: str
    author_id: str
    created_at: Optional[datetime] = None
    conversation_id: Optional[str] = None
    in_reply_to_user_id: Optional[str] = None
    reply_settings: Optional[str] = None
    lang: Optional[str] = None
    source: Optional[str] = None
    public_metrics: Optional[Dict] = None
    author: Optional['User'] = None
    
    @property
    def likes(self) -> int:
        return self.public_metrics.get('like_count', 0) if self.public_metrics else 0
    
    @property
    def retweets(self) -> int:
        return self.public_metrics.get('retweet_count', 0) if self.public_metrics else 0
    
    @property
    def replies(self) -> int:
        return self.public_metrics.get('reply_count', 0) if self.public_metrics else 0
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "text": self.text,
            "author_id": self.author_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "conversation_id": self.conversation_id,
            "lang": self.lang,
            "likes": self.likes,
            "retweets": self.retweets,
            "replies": self.replies,
            "author": self.author.to_dict() if self.author else None,
        }


@dataclass
class User:
    """Represents a Twitter user."""
    id: str
    username: str
    name: str
    description: Optional[str] = None
    profile_image_url: Optional[str] = None
    verified: bool = False
    protected: bool = False
    location: Optional[str] = None
    url: Optional[str] = None
    created_at: Optional[datetime] = None
    public_metrics: Optional[Dict] = None
    
    @property
    def followers(self) -> int:
        return self.public_metrics.get('followers_count', 0) if self.public_metrics else 0
    
    @property
    def following(self) -> int:
        return self.public_metrics.get('following_count', 0) if self.public_metrics else 0
    
    @property
    def tweet_count(self) -> int:
        return self.public_metrics.get('tweet_count', 0) if self.public_metrics else 0
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "username": self.username,
            "name": self.name,
            "description": self.description,
            "profile_image": self.profile_image_url,
            "verified": self.verified,
            "protected": self.protected,
            "location": self.location,
            "url": self.url,
            "followers": self.followers,
            "following": self.following,
            "tweets": self.tweet_count,
        }


@dataclass
class DirectMessage:
    """Represents a direct message."""
    id: str
    text: str
    sender_id: str
    recipient_id: str
    created_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "text": self.text,
            "sender_id": self.sender_id,
            "recipient_id": self.recipient_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class TwitterConnector:
    """
    Twitter API v2 connector.
    
    Requires OAuth 1.0a credentials:
    - TWITTER_API_KEY (Consumer Key)
    - TWITTER_API_SECRET (Consumer Secret)
    - TWITTER_ACCESS_TOKEN
    - TWITTER_ACCESS_SECRET
    
    Or OAuth 2.0 Bearer Token:
    - TWITTER_BEARER_TOKEN
    
    Provides methods for:
    - Posting and deleting tweets
    - Searching tweets
    - Getting user info and timelines
    - Managing likes and retweets
    - Direct messages
    """
    
    BASE_URL = "https://api.twitter.com/2"
    
    def __init__(
        self,
        api_key: str = None,
        api_secret: str = None,
        access_token: str = None,
        access_secret: str = None,
        bearer_token: str = None,
    ):
        if not HAS_HTTPX:
            raise ImportError("httpx library required. Run: pip install httpx")
        
        self._api_key = api_key or os.getenv('TWITTER_API_KEY')
        self._api_secret = api_secret or os.getenv('TWITTER_API_SECRET')
        self._access_token = access_token or os.getenv('TWITTER_ACCESS_TOKEN')
        self._access_secret = access_secret or os.getenv('TWITTER_ACCESS_SECRET')
        self._bearer_token = bearer_token or os.getenv('TWITTER_BEARER_TOKEN')
        
        self._client: Optional[httpx.AsyncClient] = None
        self._user_id: Optional[str] = None
    
    def has_credentials(self) -> bool:
        """Check if credentials are available."""
        has_oauth1 = all([
            self._api_key,
            self._api_secret,
            self._access_token,
            self._access_secret,
        ])
        has_bearer = bool(self._bearer_token)
        return has_oauth1 or has_bearer
    
    def get_setup_instructions(self) -> str:
        """Get setup instructions."""
        return """
Twitter API Setup:

1. Create a Twitter Developer account at https://developer.twitter.com

2. Create a project and app

3. Get your API credentials

4. Set environment variables:

   For OAuth 1.0a (full access including posting):
   export TWITTER_API_KEY=your-api-key
   export TWITTER_API_SECRET=your-api-secret
   export TWITTER_ACCESS_TOKEN=your-access-token
   export TWITTER_ACCESS_SECRET=your-access-secret

   For OAuth 2.0 (read-only):
   export TWITTER_BEARER_TOKEN=your-bearer-token
"""
    
    async def connect(self) -> bool:
        """Connect to Twitter API."""
        if not self.has_credentials():
            print(self.get_setup_instructions())
            return False
        
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=30.0,
        )
        
        # Verify credentials and get user ID
        try:
            me = await self.get_me()
            self._user_id = me.id
            return True
        except Exception as e:
            print(f"Failed to connect: {e}")
            return False
    
    @property
    def connected(self) -> bool:
        return self._client is not None and self._user_id is not None
    
    def _ensure_connected(self):
        if not self._client:
            raise RuntimeError("Not connected. Call connect() first.")
    
    def _generate_oauth_signature(
        self,
        method: str,
        url: str,
        params: Dict,
    ) -> str:
        """Generate OAuth 1.0a signature."""
        # Sort and encode parameters
        sorted_params = sorted(params.items())
        param_string = urlencode(sorted_params, quote_via=quote)
        
        # Create signature base string
        base_string = f"{method.upper()}&{quote(url, safe='')}&{quote(param_string, safe='')}"
        
        # Create signing key
        signing_key = f"{quote(self._api_secret, safe='')}&{quote(self._access_secret, safe='')}"
        
        # Generate signature
        signature = hmac.new(
            signing_key.encode('utf-8'),
            base_string.encode('utf-8'),
            hashlib.sha1
        ).digest()
        
        return base64.b64encode(signature).decode('utf-8')
    
    def _get_oauth_header(self, method: str, url: str, params: Dict = None) -> str:
        """Generate OAuth 1.0a Authorization header."""
        oauth_params = {
            'oauth_consumer_key': self._api_key,
            'oauth_nonce': secrets.token_hex(16),
            'oauth_signature_method': 'HMAC-SHA1',
            'oauth_timestamp': str(int(time.time())),
            'oauth_token': self._access_token,
            'oauth_version': '1.0',
        }
        
        # Combine with request params for signature
        all_params = {**oauth_params, **(params or {})}
        signature = self._generate_oauth_signature(method, url, all_params)
        oauth_params['oauth_signature'] = signature
        
        # Format header
        header_params = ', '.join(
            f'{quote(k, safe="")}="{quote(v, safe="")}"'
            for k, v in sorted(oauth_params.items())
        )
        return f'OAuth {header_params}'
    
    async def _get_headers(self, method: str = "GET", url: str = "", params: Dict = None) -> Dict:
        """Get request headers with authentication."""
        if self._bearer_token:
            return {'Authorization': f'Bearer {self._bearer_token}'}
        else:
            full_url = f"{self.BASE_URL}{url}" if not url.startswith('http') else url
            return {'Authorization': self._get_oauth_header(method, full_url, params)}
    
    def _parse_datetime(self, dt_str: str) -> Optional[datetime]:
        """Parse Twitter datetime string."""
        if not dt_str:
            return None
        try:
            return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        except:
            return None
    
    def _parse_tweet(self, data: Dict, users: Dict = None) -> Tweet:
        """Parse API response into Tweet."""
        author = None
        if users and data.get('author_id') in users:
            author = self._parse_user(users[data['author_id']])
        
        return Tweet(
            id=data['id'],
            text=data.get('text', ''),
            author_id=data.get('author_id', ''),
            created_at=self._parse_datetime(data.get('created_at')),
            conversation_id=data.get('conversation_id'),
            in_reply_to_user_id=data.get('in_reply_to_user_id'),
            reply_settings=data.get('reply_settings'),
            lang=data.get('lang'),
            source=data.get('source'),
            public_metrics=data.get('public_metrics'),
            author=author,
        )
    
    def _parse_user(self, data: Dict) -> User:
        """Parse API response into User."""
        return User(
            id=data['id'],
            username=data.get('username', ''),
            name=data.get('name', ''),
            description=data.get('description'),
            profile_image_url=data.get('profile_image_url'),
            verified=data.get('verified', False),
            protected=data.get('protected', False),
            location=data.get('location'),
            url=data.get('url'),
            created_at=self._parse_datetime(data.get('created_at')),
            public_metrics=data.get('public_metrics'),
        )
    
    # === User Operations ===
    
    async def get_me(self) -> User:
        """
        Get authenticated user info.
        
        Returns:
            User object for authenticated user
        """
        self._ensure_connected()
        
        params = {
            'user.fields': 'created_at,description,location,profile_image_url,public_metrics,url,verified',
        }
        
        headers = await self._get_headers("GET", "/users/me", params)
        response = await self._client.get('/users/me', headers=headers, params=params)
        response.raise_for_status()
        
        return self._parse_user(response.json()['data'])
    
    async def get_user(self, username: str = None, user_id: str = None) -> User:
        """
        Get user by username or ID.
        
        Args:
            username: Twitter username (without @)
            user_id: Twitter user ID
        
        Returns:
            User object
        """
        self._ensure_connected()
        
        if not username and not user_id:
            raise ValueError("Must provide username or user_id")
        
        params = {
            'user.fields': 'created_at,description,location,profile_image_url,public_metrics,url,verified',
        }
        
        if username:
            endpoint = f'/users/by/username/{username}'
        else:
            endpoint = f'/users/{user_id}'
        
        headers = await self._get_headers("GET", endpoint, params)
        response = await self._client.get(endpoint, headers=headers, params=params)
        response.raise_for_status()
        
        return self._parse_user(response.json()['data'])
    
    async def get_followers(
        self,
        user_id: str = None,
        max_results: int = 100,
    ) -> List[User]:
        """
        Get user's followers.
        
        Args:
            user_id: User ID (default: authenticated user)
            max_results: Maximum followers to return
        
        Returns:
            List of User objects
        """
        self._ensure_connected()
        
        user_id = user_id or self._user_id
        
        params = {
            'max_results': min(1000, max_results),
            'user.fields': 'created_at,description,profile_image_url,public_metrics,verified',
        }
        
        headers = await self._get_headers("GET", f'/users/{user_id}/followers', params)
        response = await self._client.get(
            f'/users/{user_id}/followers',
            headers=headers,
            params=params,
        )
        response.raise_for_status()
        
        return [self._parse_user(u) for u in response.json().get('data', [])]
    
    async def get_following(
        self,
        user_id: str = None,
        max_results: int = 100,
    ) -> List[User]:
        """
        Get users that user is following.
        
        Args:
            user_id: User ID (default: authenticated user)
            max_results: Maximum users to return
        
        Returns:
            List of User objects
        """
        self._ensure_connected()
        
        user_id = user_id or self._user_id
        
        params = {
            'max_results': min(1000, max_results),
            'user.fields': 'created_at,description,profile_image_url,public_metrics,verified',
        }
        
        headers = await self._get_headers("GET", f'/users/{user_id}/following', params)
        response = await self._client.get(
            f'/users/{user_id}/following',
            headers=headers,
            params=params,
        )
        response.raise_for_status()
        
        return [self._parse_user(u) for u in response.json().get('data', [])]
    
    async def follow_user(self, target_user_id: str) -> bool:
        """
        Follow a user.
        
        Args:
            target_user_id: User ID to follow
        
        Returns:
            True if following
        """
        self._ensure_connected()
        
        headers = await self._get_headers("POST", f'/users/{self._user_id}/following')
        headers['Content-Type'] = 'application/json'
        
        response = await self._client.post(
            f'/users/{self._user_id}/following',
            headers=headers,
            json={'target_user_id': target_user_id},
        )
        response.raise_for_status()
        
        return response.json().get('data', {}).get('following', False)
    
    async def unfollow_user(self, target_user_id: str) -> bool:
        """
        Unfollow a user.
        
        Args:
            target_user_id: User ID to unfollow
        
        Returns:
            True if unfollowed
        """
        self._ensure_connected()
        
        headers = await self._get_headers("DELETE", f'/users/{self._user_id}/following/{target_user_id}')
        response = await self._client.delete(
            f'/users/{self._user_id}/following/{target_user_id}',
            headers=headers,
        )
        response.raise_for_status()
        
        return not response.json().get('data', {}).get('following', True)
    
    # === Tweet Operations ===
    
    async def post_tweet(
        self,
        text: str,
        reply_to: str = None,
        quote_tweet_id: str = None,
        poll_options: List[str] = None,
        poll_duration_minutes: int = None,
    ) -> Tweet:
        """
        Post a tweet.
        
        Args:
            text: Tweet text (max 280 characters)
            reply_to: Tweet ID to reply to
            quote_tweet_id: Tweet ID to quote
            poll_options: List of poll options (2-4)
            poll_duration_minutes: Poll duration (5-10080)
        
        Returns:
            Created Tweet object
        """
        self._ensure_connected()
        
        if not self._api_key:
            raise RuntimeError("OAuth 1.0a credentials required for posting")
        
        body = {'text': text}
        
        if reply_to:
            body['reply'] = {'in_reply_to_tweet_id': reply_to}
        
        if quote_tweet_id:
            body['quote_tweet_id'] = quote_tweet_id
        
        if poll_options:
            body['poll'] = {
                'options': poll_options,
                'duration_minutes': poll_duration_minutes or 1440,  # default 24 hours
            }
        
        headers = await self._get_headers("POST", "/tweets")
        headers['Content-Type'] = 'application/json'
        
        response = await self._client.post('/tweets', headers=headers, json=body)
        response.raise_for_status()
        
        return self._parse_tweet(response.json()['data'])
    
    async def delete_tweet(self, tweet_id: str) -> bool:
        """
        Delete a tweet.
        
        Args:
            tweet_id: Tweet ID to delete
        
        Returns:
            True if deleted
        """
        self._ensure_connected()
        
        if not self._api_key:
            raise RuntimeError("OAuth 1.0a credentials required for deleting")
        
        headers = await self._get_headers("DELETE", f"/tweets/{tweet_id}")
        response = await self._client.delete(f'/tweets/{tweet_id}', headers=headers)
        response.raise_for_status()
        
        return response.json().get('data', {}).get('deleted', False)
    
    async def get_tweet(self, tweet_id: str) -> Tweet:
        """
        Get tweet by ID.
        
        Args:
            tweet_id: Tweet ID
        
        Returns:
            Tweet object
        """
        self._ensure_connected()
        
        params = {
            'tweet.fields': 'author_id,conversation_id,created_at,lang,public_metrics,reply_settings,source',
            'expansions': 'author_id',
            'user.fields': 'name,username,profile_image_url,verified',
        }
        
        headers = await self._get_headers("GET", f"/tweets/{tweet_id}", params)
        response = await self._client.get(f'/tweets/{tweet_id}', headers=headers, params=params)
        response.raise_for_status()
        
        data = response.json()
        users = {u['id']: u for u in data.get('includes', {}).get('users', [])}
        
        return self._parse_tweet(data['data'], users)
    
    async def get_user_tweets(
        self,
        username: str = None,
        user_id: str = None,
        max_results: int = 10,
        exclude_retweets: bool = False,
        exclude_replies: bool = False,
    ) -> List[Tweet]:
        """
        Get user's tweets.
        
        Args:
            username: Twitter username
            user_id: Twitter user ID
            max_results: Maximum tweets to return (5-100)
            exclude_retweets: Exclude retweets
            exclude_replies: Exclude replies
        
        Returns:
            List of Tweet objects
        """
        self._ensure_connected()
        
        if username:
            user = await self.get_user(username=username)
            user_id = user.id
        elif not user_id:
            user_id = self._user_id
        
        excludes = []
        if exclude_retweets:
            excludes.append('retweets')
        if exclude_replies:
            excludes.append('replies')
        
        params = {
            'max_results': min(100, max(5, max_results)),
            'tweet.fields': 'author_id,conversation_id,created_at,lang,public_metrics',
            'expansions': 'author_id',
            'user.fields': 'name,username,profile_image_url,verified',
        }
        if excludes:
            params['exclude'] = ','.join(excludes)
        
        headers = await self._get_headers("GET", f"/users/{user_id}/tweets", params)
        response = await self._client.get(f'/users/{user_id}/tweets', headers=headers, params=params)
        response.raise_for_status()
        
        data = response.json()
        users = {u['id']: u for u in data.get('includes', {}).get('users', [])}
        
        return [self._parse_tweet(t, users) for t in data.get('data', [])]
    
    async def search(
        self,
        query: str,
        max_results: int = 10,
        sort_order: str = "recency",
    ) -> List[Tweet]:
        """
        Search recent tweets.
        
        Args:
            query: Search query
            max_results: Maximum results (10-100)
            sort_order: "recency" or "relevancy"
        
        Returns:
            List of matching Tweet objects
        """
        self._ensure_connected()
        
        params = {
            'query': query,
            'max_results': min(100, max(10, max_results)),
            'sort_order': sort_order,
            'tweet.fields': 'author_id,conversation_id,created_at,lang,public_metrics',
            'expansions': 'author_id',
            'user.fields': 'name,username,profile_image_url,verified',
        }
        
        headers = await self._get_headers("GET", "/tweets/search/recent", params)
        response = await self._client.get('/tweets/search/recent', headers=headers, params=params)
        response.raise_for_status()
        
        data = response.json()
        users = {u['id']: u for u in data.get('includes', {}).get('users', [])}
        
        return [self._parse_tweet(t, users) for t in data.get('data', [])]
    
    # === Engagement ===
    
    async def like_tweet(self, tweet_id: str) -> bool:
        """
        Like a tweet.
        
        Args:
            tweet_id: Tweet ID to like
        
        Returns:
            True if liked
        """
        self._ensure_connected()
        
        if not self._api_key:
            raise RuntimeError("OAuth 1.0a credentials required for liking")
        
        headers = await self._get_headers("POST", f"/users/{self._user_id}/likes")
        headers['Content-Type'] = 'application/json'
        
        response = await self._client.post(
            f'/users/{self._user_id}/likes',
            headers=headers,
            json={'tweet_id': tweet_id},
        )
        response.raise_for_status()
        
        return response.json().get('data', {}).get('liked', False)
    
    async def unlike_tweet(self, tweet_id: str) -> bool:
        """
        Unlike a tweet.
        
        Args:
            tweet_id: Tweet ID to unlike
        
        Returns:
            True if unliked
        """
        self._ensure_connected()
        
        if not self._api_key:
            raise RuntimeError("OAuth 1.0a credentials required for unliking")
        
        headers = await self._get_headers("DELETE", f"/users/{self._user_id}/likes/{tweet_id}")
        response = await self._client.delete(
            f'/users/{self._user_id}/likes/{tweet_id}',
            headers=headers,
        )
        response.raise_for_status()
        
        return not response.json().get('data', {}).get('liked', True)
    
    async def retweet(self, tweet_id: str) -> bool:
        """
        Retweet a tweet.
        
        Args:
            tweet_id: Tweet ID to retweet
        
        Returns:
            True if retweeted
        """
        self._ensure_connected()
        
        if not self._api_key:
            raise RuntimeError("OAuth 1.0a credentials required for retweeting")
        
        headers = await self._get_headers("POST", f"/users/{self._user_id}/retweets")
        headers['Content-Type'] = 'application/json'
        
        response = await self._client.post(
            f'/users/{self._user_id}/retweets',
            headers=headers,
            json={'tweet_id': tweet_id},
        )
        response.raise_for_status()
        
        return response.json().get('data', {}).get('retweeted', False)
    
    async def undo_retweet(self, tweet_id: str) -> bool:
        """
        Undo a retweet.
        
        Args:
            tweet_id: Tweet ID to un-retweet
        
        Returns:
            True if undone
        """
        self._ensure_connected()
        
        if not self._api_key:
            raise RuntimeError("OAuth 1.0a credentials required")
        
        headers = await self._get_headers("DELETE", f"/users/{self._user_id}/retweets/{tweet_id}")
        response = await self._client.delete(
            f'/users/{self._user_id}/retweets/{tweet_id}',
            headers=headers,
        )
        response.raise_for_status()
        
        return not response.json().get('data', {}).get('retweeted', True)
    
    async def get_liked_tweets(
        self,
        user_id: str = None,
        max_results: int = 10,
    ) -> List[Tweet]:
        """
        Get user's liked tweets.
        
        Args:
            user_id: User ID (default: authenticated user)
            max_results: Maximum tweets to return
        
        Returns:
            List of Tweet objects
        """
        self._ensure_connected()
        
        user_id = user_id or self._user_id
        
        params = {
            'max_results': min(100, max(5, max_results)),
            'tweet.fields': 'author_id,conversation_id,created_at,lang,public_metrics',
            'expansions': 'author_id',
            'user.fields': 'name,username,profile_image_url,verified',
        }
        
        headers = await self._get_headers("GET", f"/users/{user_id}/liked_tweets", params)
        response = await self._client.get(
            f'/users/{user_id}/liked_tweets',
            headers=headers,
            params=params,
        )
        response.raise_for_status()
        
        data = response.json()
        users = {u['id']: u for u in data.get('includes', {}).get('users', [])}
        
        return [self._parse_tweet(t, users) for t in data.get('data', [])]
    
    # === Bookmarks ===
    
    async def bookmark_tweet(self, tweet_id: str) -> bool:
        """
        Bookmark a tweet.
        
        Args:
            tweet_id: Tweet ID to bookmark
        
        Returns:
            True if bookmarked
        """
        self._ensure_connected()
        
        if not self._api_key:
            raise RuntimeError("OAuth 1.0a credentials required")
        
        headers = await self._get_headers("POST", f"/users/{self._user_id}/bookmarks")
        headers['Content-Type'] = 'application/json'
        
        response = await self._client.post(
            f'/users/{self._user_id}/bookmarks',
            headers=headers,
            json={'tweet_id': tweet_id},
        )
        response.raise_for_status()
        
        return response.json().get('data', {}).get('bookmarked', False)
    
    async def remove_bookmark(self, tweet_id: str) -> bool:
        """
        Remove bookmark from tweet.
        
        Args:
            tweet_id: Tweet ID
        
        Returns:
            True if removed
        """
        self._ensure_connected()
        
        if not self._api_key:
            raise RuntimeError("OAuth 1.0a credentials required")
        
        headers = await self._get_headers("DELETE", f"/users/{self._user_id}/bookmarks/{tweet_id}")
        response = await self._client.delete(
            f'/users/{self._user_id}/bookmarks/{tweet_id}',
            headers=headers,
        )
        response.raise_for_status()
        
        return not response.json().get('data', {}).get('bookmarked', True)
    
    async def get_bookmarks(self, max_results: int = 10) -> List[Tweet]:
        """
        Get bookmarked tweets.
        
        Args:
            max_results: Maximum tweets to return
        
        Returns:
            List of Tweet objects
        """
        self._ensure_connected()
        
        params = {
            'max_results': min(100, max(1, max_results)),
            'tweet.fields': 'author_id,conversation_id,created_at,lang,public_metrics',
            'expansions': 'author_id',
            'user.fields': 'name,username,profile_image_url,verified',
        }
        
        headers = await self._get_headers("GET", f"/users/{self._user_id}/bookmarks", params)
        response = await self._client.get(
            f'/users/{self._user_id}/bookmarks',
            headers=headers,
            params=params,
        )
        response.raise_for_status()
        
        data = response.json()
        users = {u['id']: u for u in data.get('includes', {}).get('users', [])}
        
        return [self._parse_tweet(t, users) for t in data.get('data', [])]
