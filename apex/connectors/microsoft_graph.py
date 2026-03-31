"""
Microsoft Graph API Client

Base HTTP client for all Microsoft Graph API operations.
Provides common functionality:
- Authenticated requests
- Error handling
- Pagination
- Batch requests
- Rate limiting

Usage:
    from microsoft_graph import GraphClient
    
    client = GraphClient()
    await client.connect()
    
    # GET request
    response = await client.get('/me/messages')
    
    # POST request
    response = await client.post('/me/messages', json={...})
    
    # Paginated results
    async for page in client.paginate('/me/messages'):
        for message in page:
            print(message['subject'])
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, AsyncIterator, Dict, List, Optional, Union
from urllib.parse import urljoin, urlencode

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

from .microsoft_auth import MicrosoftAuth, get_microsoft_auth, GRAPH_API_BASE

logger = logging.getLogger(__name__)


@dataclass
class GraphError:
    """Microsoft Graph API error."""
    code: str
    message: str
    status_code: int
    details: Optional[Dict] = None
    
    def __str__(self):
        return f"[{self.status_code}] {self.code}: {self.message}"


class GraphAPIError(Exception):
    """Exception for Graph API errors."""
    
    def __init__(self, error: GraphError):
        self.error = error
        super().__init__(str(error))


class GraphClient:
    """
    Microsoft Graph API HTTP client.
    
    Handles all low-level communication with Microsoft Graph API:
    - Authentication header management
    - Request/response handling
    - Error parsing
    - Pagination
    - Rate limiting and retries
    """
    
    def __init__(
        self,
        auth: Optional[MicrosoftAuth] = None,
        base_url: str = GRAPH_API_BASE,
        timeout: float = 30.0,
        max_retries: int = 3,
    ):
        if not HAS_HTTPX:
            raise ImportError("httpx library required. Run: pip install httpx")
        
        self._auth = auth or get_microsoft_auth()
        self._base_url = base_url
        self._timeout = timeout
        self._max_retries = max_retries
        
        self._client: Optional[httpx.AsyncClient] = None
        self._connected = False
    
    async def connect(self, scopes: List[str] = None) -> bool:
        """
        Connect to Microsoft Graph API.
        
        Performs authentication and creates HTTP client.
        
        Args:
            scopes: List of permission scopes needed
        
        Returns:
            True if connected successfully
        """
        if not self._auth.has_credentials():
            print(self._auth.get_setup_instructions())
            return False
        
        # Get initial token to verify authentication
        token = await self._auth.get_token(scopes)
        if not token:
            return False
        
        # Create HTTP client
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
        )
        
        self._connected = True
        return True
    
    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
        self._connected = False
    
    @property
    def connected(self) -> bool:
        return self._connected
    
    async def _get_headers(self, scopes: List[str] = None) -> Dict[str, str]:
        """Get headers with fresh auth token."""
        return await self._auth.get_headers(scopes)
    
    def _parse_error(self, response: httpx.Response) -> GraphError:
        """Parse error response from Graph API."""
        try:
            error_data = response.json()
            error = error_data.get('error', {})
            return GraphError(
                code=error.get('code', 'UnknownError'),
                message=error.get('message', 'Unknown error occurred'),
                status_code=response.status_code,
                details=error,
            )
        except:
            return GraphError(
                code='ParseError',
                message=response.text[:500],
                status_code=response.status_code,
            )
    
    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Dict = None,
        json_data: Dict = None,
        scopes: List[str] = None,
        retry_count: int = 0,
    ) -> Dict:
        """
        Make an authenticated request to Graph API.
        
        Handles retries, rate limiting, and error parsing.
        """
        if not self._client:
            raise RuntimeError("Not connected. Call connect() first.")
        
        headers = await self._get_headers(scopes)
        
        # Build URL
        url = endpoint if endpoint.startswith('http') else endpoint
        
        try:
            response = await self._client.request(
                method=method,
                url=url,
                params=params,
                json=json_data,
                headers=headers,
            )
            
            # Handle rate limiting
            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 5))
                if retry_count < self._max_retries:
                    logger.warning(f"Rate limited. Waiting {retry_after}s before retry.")
                    await asyncio.sleep(retry_after)
                    return await self._request(
                        method, endpoint, params, json_data, scopes, retry_count + 1
                    )
                raise GraphAPIError(self._parse_error(response))
            
            # Handle server errors with retry
            if response.status_code >= 500 and retry_count < self._max_retries:
                logger.warning(f"Server error {response.status_code}. Retrying...")
                await asyncio.sleep(2 ** retry_count)
                return await self._request(
                    method, endpoint, params, json_data, scopes, retry_count + 1
                )
            
            # Handle errors
            if response.status_code >= 400:
                raise GraphAPIError(self._parse_error(response))
            
            # Return JSON response
            if response.status_code == 204:  # No content
                return {}
            
            return response.json()
            
        except httpx.RequestError as e:
            if retry_count < self._max_retries:
                logger.warning(f"Request error: {e}. Retrying...")
                await asyncio.sleep(2 ** retry_count)
                return await self._request(
                    method, endpoint, params, json_data, scopes, retry_count + 1
                )
            raise
    
    async def get(
        self,
        endpoint: str,
        params: Dict = None,
        scopes: List[str] = None,
    ) -> Dict:
        """Make a GET request."""
        return await self._request('GET', endpoint, params=params, scopes=scopes)
    
    async def post(
        self,
        endpoint: str,
        json_data: Dict = None,
        scopes: List[str] = None,
    ) -> Dict:
        """Make a POST request."""
        return await self._request('POST', endpoint, json_data=json_data, scopes=scopes)
    
    async def patch(
        self,
        endpoint: str,
        json_data: Dict = None,
        scopes: List[str] = None,
    ) -> Dict:
        """Make a PATCH request."""
        return await self._request('PATCH', endpoint, json_data=json_data, scopes=scopes)
    
    async def put(
        self,
        endpoint: str,
        json_data: Dict = None,
        content: bytes = None,
        content_type: str = None,
        params: Dict = None,
        scopes: List[str] = None,
    ) -> Dict:
        """
        Make a PUT request.
        
        Supports both JSON data and raw binary content for file uploads.
        """
        if content is not None:
            # Raw content upload (for file uploads)
            return await self._put_raw(endpoint, content, content_type, params, scopes)
        return await self._request('PUT', endpoint, json_data=json_data, params=params, scopes=scopes)
    
    async def _put_raw(
        self,
        endpoint: str,
        content: bytes,
        content_type: str = None,
        params: Dict = None,
        scopes: List[str] = None,
    ) -> Dict:
        """PUT raw bytes (for file uploads)."""
        if not self._client:
            raise RuntimeError("Not connected. Call connect() first.")
        
        headers = await self._get_headers(scopes)
        if content_type:
            headers['Content-Type'] = content_type
        headers['Content-Length'] = str(len(content))
        
        response = await self._client.put(
            endpoint,
            content=content,
            params=params,
            headers=headers,
        )
        
        if response.status_code >= 400:
            raise GraphAPIError(self._parse_error(response))
        
        if response.status_code == 204:
            return {}
        return response.json()
    
    async def get_raw(
        self,
        endpoint: str,
        params: Dict = None,
        scopes: List[str] = None,
    ) -> bytes:
        """
        GET raw bytes (for file downloads).
        
        Returns the raw response content as bytes.
        """
        if not self._client:
            raise RuntimeError("Not connected. Call connect() first.")
        
        headers = await self._get_headers(scopes)
        
        response = await self._client.get(
            endpoint,
            params=params,
            headers=headers,
        )
        
        if response.status_code >= 400:
            raise GraphAPIError(self._parse_error(response))
        
        return response.content
    
    async def delete(
        self,
        endpoint: str,
        scopes: List[str] = None,
    ) -> Dict:
        """Make a DELETE request."""
        return await self._request('DELETE', endpoint, scopes=scopes)
    
    async def paginate(
        self,
        endpoint: str,
        params: Dict = None,
        scopes: List[str] = None,
        max_pages: int = 100,
        page_size: int = 50,
    ) -> AsyncIterator[List[Dict]]:
        """
        Iterate through paginated results.
        
        Yields pages of items until exhausted or max_pages reached.
        
        Usage:
            async for page in client.paginate('/me/messages'):
                for msg in page:
                    print(msg['subject'])
        """
        params = params or {}
        params['$top'] = page_size
        
        url = endpoint
        pages = 0
        
        while url and pages < max_pages:
            response = await self.get(url, params=params if pages == 0 else None, scopes=scopes)
            
            items = response.get('value', [])
            if items:
                yield items
            
            # Get next page URL
            url = response.get('@odata.nextLink')
            pages += 1
    
    async def get_all(
        self,
        endpoint: str,
        params: Dict = None,
        scopes: List[str] = None,
        max_items: int = 1000,
    ) -> List[Dict]:
        """
        Get all items from a paginated endpoint.
        
        Collects all pages into a single list.
        """
        items = []
        async for page in self.paginate(endpoint, params, scopes):
            items.extend(page)
            if len(items) >= max_items:
                break
        return items[:max_items]
    
    async def batch(
        self,
        requests: List[Dict],
        scopes: List[str] = None,
    ) -> List[Dict]:
        """
        Execute multiple requests in a single batch.
        
        Microsoft Graph supports up to 20 requests per batch.
        
        Args:
            requests: List of request dictionaries with:
                - id: Unique request ID
                - method: HTTP method
                - url: Endpoint URL
                - body: Optional request body
        
        Returns:
            List of response dictionaries
        """
        if len(requests) > 20:
            # Split into multiple batches
            results = []
            for i in range(0, len(requests), 20):
                batch_results = await self.batch(requests[i:i+20], scopes)
                results.extend(batch_results)
            return results
        
        batch_body = {
            'requests': [
                {
                    'id': str(req.get('id', i)),
                    'method': req.get('method', 'GET'),
                    'url': req['url'],
                    **(({'body': req['body']}) if 'body' in req else {}),
                }
                for i, req in enumerate(requests)
            ]
        }
        
        response = await self.post('/$batch', json_data=batch_body, scopes=scopes)
        return response.get('responses', [])
    
    async def get_user_info(self) -> Dict:
        """Get current user's profile information."""
        return await self.get('/me')
    
    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


# Singleton instance
_client_instance: Optional[GraphClient] = None

def get_graph_client() -> GraphClient:
    """Get or create the GraphClient singleton."""
    global _client_instance
    if _client_instance is None:
        _client_instance = GraphClient()
    return _client_instance
