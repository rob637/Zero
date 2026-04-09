"""
Stripe connector — customers, charges, invoices, subscriptions, products, prices, payment intents.

Uses Stripe REST API with secret key authentication.
Docs: https://stripe.com/docs/api
"""

from __future__ import annotations

import httpx
from typing import Any

BASE = "https://api.stripe.com/v1"


class StripeConnector:
    """Manages Stripe payment operations via REST API."""

    def __init__(self, secret_key: str | None = None):
        self.secret_key = secret_key
        self.connected = bool(secret_key)

    # ── helpers ──────────────────────────────────────────────

    def _auth(self) -> tuple[str, str]:
        return (self.secret_key, "")

    async def _get(self, path: str, params: dict | None = None) -> Any:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{BASE}{path}", auth=self._auth(), params=params)
            r.raise_for_status()
            return r.json()

    async def _post(self, path: str, data: dict | None = None) -> Any:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{BASE}{path}", auth=self._auth(), data=data)
            r.raise_for_status()
            return r.json()

    async def _delete(self, path: str) -> Any:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.delete(f"{BASE}{path}", auth=self._auth())
            r.raise_for_status()
            return r.json()

    # ── customers ────────────────────────────────────────────

    async def list_customers(self, limit: int = 20, starting_after: str | None = None,
                             email: str | None = None) -> dict:
        """List customers with optional pagination and email filter."""
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if starting_after:
            params["starting_after"] = starting_after
        if email:
            params["email"] = email
        return await self._get("/customers", params)

    async def get_customer(self, customer_id: str) -> dict:
        """Get a single customer by ID."""
        return await self._get(f"/customers/{customer_id}")

    async def create_customer(self, email: str | None = None,
                              name: str | None = None,
                              description: str | None = None,
                              metadata: dict | None = None) -> dict:
        """Create a customer."""
        data: dict[str, Any] = {}
        if email:
            data["email"] = email
        if name:
            data["name"] = name
        if description:
            data["description"] = description
        if metadata:
            for k, v in metadata.items():
                data[f"metadata[{k}]"] = v
        return await self._post("/customers", data)

    async def update_customer(self, customer_id: str, **kwargs) -> dict:
        """Update a customer. Pass email, name, description, metadata, etc."""
        data: dict[str, Any] = {}
        for k, v in kwargs.items():
            if k == "metadata" and isinstance(v, dict):
                for mk, mv in v.items():
                    data[f"metadata[{mk}]"] = mv
            else:
                data[k] = v
        return await self._post(f"/customers/{customer_id}", data)

    async def delete_customer(self, customer_id: str) -> dict:
        """Delete a customer."""
        return await self._delete(f"/customers/{customer_id}")

    # ── products ─────────────────────────────────────────────

    async def list_products(self, limit: int = 20, active: bool | None = None) -> dict:
        """List products."""
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if active is not None:
            params["active"] = str(active).lower()
        return await self._get("/products", params)

    async def get_product(self, product_id: str) -> dict:
        """Get a single product."""
        return await self._get(f"/products/{product_id}")

    async def create_product(self, name: str, description: str | None = None,
                             metadata: dict | None = None) -> dict:
        """Create a product."""
        data: dict[str, Any] = {"name": name}
        if description:
            data["description"] = description
        if metadata:
            for k, v in metadata.items():
                data[f"metadata[{k}]"] = v
        return await self._post("/products", data)

    # ── prices ───────────────────────────────────────────────

    async def list_prices(self, product_id: str | None = None,
                          limit: int = 20) -> dict:
        """List prices, optionally filtered by product."""
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if product_id:
            params["product"] = product_id
        return await self._get("/prices", params)

    async def create_price(self, product_id: str, unit_amount: int,
                           currency: str = "usd",
                           recurring_interval: str | None = None) -> dict:
        """Create a price. unit_amount is in cents. recurring_interval: month, year, etc."""
        data: dict[str, Any] = {
            "product": product_id,
            "unit_amount": unit_amount,
            "currency": currency,
        }
        if recurring_interval:
            data["recurring[interval]"] = recurring_interval
        return await self._post("/prices", data)

    # ── invoices ─────────────────────────────────────────────

    async def list_invoices(self, customer_id: str | None = None,
                            limit: int = 20, status: str | None = None) -> dict:
        """List invoices. status: draft, open, paid, uncollectible, void."""
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if customer_id:
            params["customer"] = customer_id
        if status:
            params["status"] = status
        return await self._get("/invoices", params)

    async def get_invoice(self, invoice_id: str) -> dict:
        """Get a single invoice."""
        return await self._get(f"/invoices/{invoice_id}")

    async def create_invoice(self, customer_id: str,
                             auto_advance: bool = True) -> dict:
        """Create a draft invoice for a customer."""
        data: dict[str, Any] = {
            "customer": customer_id,
            "auto_advance": str(auto_advance).lower(),
        }
        return await self._post("/invoices", data)

    async def finalize_invoice(self, invoice_id: str) -> dict:
        """Finalize a draft invoice."""
        return await self._post(f"/invoices/{invoice_id}/finalize")

    async def void_invoice(self, invoice_id: str) -> dict:
        """Void an invoice."""
        return await self._post(f"/invoices/{invoice_id}/void")

    # ── subscriptions ────────────────────────────────────────

    async def list_subscriptions(self, customer_id: str | None = None,
                                 limit: int = 20,
                                 status: str | None = None) -> dict:
        """List subscriptions. status: active, past_due, canceled, etc."""
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if customer_id:
            params["customer"] = customer_id
        if status:
            params["status"] = status
        return await self._get("/subscriptions", params)

    async def get_subscription(self, sub_id: str) -> dict:
        """Get a single subscription."""
        return await self._get(f"/subscriptions/{sub_id}")

    async def cancel_subscription(self, sub_id: str,
                                  at_period_end: bool = True) -> dict:
        """Cancel a subscription (at period end by default)."""
        if at_period_end:
            return await self._post(f"/subscriptions/{sub_id}",
                                    {"cancel_at_period_end": "true"})
        return await self._delete(f"/subscriptions/{sub_id}")

    # ── payment intents ──────────────────────────────────────

    async def list_payment_intents(self, customer_id: str | None = None,
                                   limit: int = 20) -> dict:
        """List payment intents."""
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if customer_id:
            params["customer"] = customer_id
        return await self._get("/payment_intents", params)

    async def get_payment_intent(self, pi_id: str) -> dict:
        """Get a single payment intent."""
        return await self._get(f"/payment_intents/{pi_id}")

    # ── charges ──────────────────────────────────────────────

    async def list_charges(self, customer_id: str | None = None,
                           limit: int = 20) -> dict:
        """List charges."""
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if customer_id:
            params["customer"] = customer_id
        return await self._get("/charges", params)

    async def get_charge(self, charge_id: str) -> dict:
        """Get a single charge."""
        return await self._get(f"/charges/{charge_id}")

    # ── balance ──────────────────────────────────────────────

    async def get_balance(self) -> dict:
        """Get the current account balance."""
        return await self._get("/balance")
