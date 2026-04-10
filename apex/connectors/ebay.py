"""
eBay connector — product search, item details, and order tracking.

Uses the eBay Browse API (public, requires OAuth client credentials).
Docs: https://developer.ebay.com/api-docs/buy/browse/overview.html

Setup:
    1. Create an eBay Developer account: https://developer.ebay.com/
    2. Create an application to get App ID (Client ID) and Cert ID (Client Secret)
    3. Set EBAY_CLIENT_ID and EBAY_CLIENT_SECRET in .env
"""

from __future__ import annotations

import httpx
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# eBay API endpoints
PRODUCTION_AUTH = "https://api.ebay.com/identity/v1/oauth2/token"
PRODUCTION_API = "https://api.ebay.com"
SANDBOX_AUTH = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
SANDBOX_API = "https://api.sandbox.ebay.com"


class EbayConnector:
    """Manages eBay product search and item operations via Browse API."""

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        sandbox: bool = False,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self._sandbox = sandbox
        self._access_token: str | None = None
        self._auth_url = SANDBOX_AUTH if sandbox else PRODUCTION_AUTH
        self._api_url = SANDBOX_API if sandbox else PRODUCTION_API
        self.connected = False

    async def connect(self) -> bool:
        """Authenticate with eBay using client credentials (application token)."""
        if not self.client_id or not self.client_secret:
            return False
        try:
            self._access_token = await self._get_app_token()
            self.connected = True
            return True
        except Exception as e:
            logger.error(f"eBay auth failed: {e}")
            self.connected = False
            return False

    async def _get_app_token(self) -> str:
        """Get an application-level OAuth token (client credentials grant)."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                self._auth_url,
                auth=(self.client_id, self.client_secret),
                data={
                    "grant_type": "client_credentials",
                    "scope": "https://api.ebay.com/oauth/api_scope",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            data = resp.json()
            return data["access_token"]

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        }

    async def _get(self, path: str, params: dict | None = None) -> Any:
        """Make authenticated GET request. Auto-refreshes token on 401."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self._api_url}{path}",
                headers=self._headers(),
                params=params,
            )
            if resp.status_code == 401:
                # Token expired — refresh and retry
                self._access_token = await self._get_app_token()
                resp = await client.get(
                    f"{self._api_url}{path}",
                    headers=self._headers(),
                    params=params,
                )
            resp.raise_for_status()
            return resp.json()

    # ── Browse API ───────────────────────────────────────────

    async def search_products(
        self,
        query: str,
        limit: int = 20,
        category_id: str | None = None,
        sort: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
    ) -> dict:
        """Search for products on eBay.
        
        Sort options: price, -price, newlyListed, endingSoonest
        """
        params: dict[str, Any] = {
            "q": query,
            "limit": min(limit, 50),
        }
        if category_id:
            params["category_ids"] = category_id
        if sort:
            params["sort"] = sort

        # Price filter
        filters = []
        if min_price is not None:
            filters.append(f"price:[{min_price}..],priceCurrency:USD")
        if max_price is not None:
            filters.append(f"price:[..{max_price}],priceCurrency:USD")
        if min_price is not None and max_price is not None:
            filters = [f"price:[{min_price}..{max_price}],priceCurrency:USD"]
        if filters:
            params["filter"] = ",".join(filters)

        data = await self._get("/buy/browse/v1/item_summary/search", params)

        items = []
        for item in data.get("itemSummaries", []):
            items.append({
                "id": item.get("itemId"),
                "title": item.get("title"),
                "price": item.get("price", {}).get("value"),
                "currency": item.get("price", {}).get("currency"),
                "condition": item.get("condition"),
                "image_url": item.get("image", {}).get("imageUrl"),
                "url": item.get("itemWebUrl"),
                "seller": item.get("seller", {}).get("username"),
                "seller_rating": item.get("seller", {}).get("feedbackPercentage"),
                "shipping": item.get("shippingOptions", [{}])[0].get("shippingCost", {}).get("value") if item.get("shippingOptions") else None,
                "location": item.get("itemLocation", {}).get("country"),
                "buying_options": item.get("buyingOptions", []),
            })

        return {
            "items": items,
            "total": data.get("total", len(items)),
            "offset": data.get("offset", 0),
        }

    async def get_product(self, item_id: str) -> dict:
        """Get detailed information about a specific item."""
        data = await self._get(f"/buy/browse/v1/item/{item_id}")

        return {
            "id": data.get("itemId"),
            "title": data.get("title"),
            "description": data.get("shortDescription") or data.get("description", "")[:500],
            "price": data.get("price", {}).get("value"),
            "currency": data.get("price", {}).get("currency"),
            "condition": data.get("condition"),
            "condition_description": data.get("conditionDescription"),
            "category": data.get("categoryPath"),
            "image_url": data.get("image", {}).get("imageUrl"),
            "additional_images": [img.get("imageUrl") for img in data.get("additionalImages", [])],
            "url": data.get("itemWebUrl"),
            "seller": data.get("seller", {}).get("username"),
            "seller_rating": data.get("seller", {}).get("feedbackPercentage"),
            "seller_score": data.get("seller", {}).get("feedbackScore"),
            "quantity_available": data.get("estimatedAvailabilities", [{}])[0].get("estimatedAvailableQuantity") if data.get("estimatedAvailabilities") else None,
            "shipping_options": [
                {
                    "type": opt.get("shippingServiceCode"),
                    "cost": opt.get("shippingCost", {}).get("value"),
                    "min_days": opt.get("minEstimatedDeliveryDate"),
                    "max_days": opt.get("maxEstimatedDeliveryDate"),
                }
                for opt in data.get("shippingOptions", [])
            ],
            "return_terms": {
                "returnsAccepted": data.get("returnTerms", {}).get("returnsAccepted"),
                "period": data.get("returnTerms", {}).get("returnPeriod", {}).get("value"),
            } if data.get("returnTerms") else None,
            "buying_options": data.get("buyingOptions", []),
        }

    async def search_by_category(
        self,
        category_id: str,
        limit: int = 20,
    ) -> dict:
        """Browse items in a specific eBay category."""
        params = {
            "category_ids": category_id,
            "limit": min(limit, 50),
        }
        data = await self._get("/buy/browse/v1/item_summary/search", params)

        items = []
        for item in data.get("itemSummaries", []):
            items.append({
                "id": item.get("itemId"),
                "title": item.get("title"),
                "price": item.get("price", {}).get("value"),
                "currency": item.get("price", {}).get("currency"),
                "condition": item.get("condition"),
                "url": item.get("itemWebUrl"),
            })

        return {"items": items, "total": data.get("total", len(items))}


def get_ebay_connector(
    client_id: str | None = None,
    client_secret: str | None = None,
    sandbox: bool = False,
) -> EbayConnector:
    """Factory function for eBay connector."""
    return EbayConnector(
        client_id=client_id,
        client_secret=client_secret,
        sandbox=sandbox,
    )
