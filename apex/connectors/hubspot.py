"""
HubSpot CRM connector — contacts, companies, deals, tickets, notes, lists.

Uses HubSpot CRM API v3 with private app access token authentication.
Docs: https://developers.hubspot.com/docs/api/crm
"""

from __future__ import annotations

import httpx
from typing import Any

BASE = "https://api.hubapi.com"


class HubSpotConnector:
    """Manages HubSpot CRM operations via REST API v3."""

    def __init__(self, access_token: str | None = None):
        self.access_token = access_token
        self.connected = bool(access_token)

    # ── helpers ──────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    async def _get(self, path: str, params: dict | None = None) -> Any:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{BASE}{path}", headers=self._headers(), params=params)
            r.raise_for_status()
            return r.json()

    async def _post(self, path: str, json_body: dict | None = None) -> Any:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{BASE}{path}", headers=self._headers(), json=json_body)
            r.raise_for_status()
            return r.json()

    async def _patch(self, path: str, json_body: dict) -> Any:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.patch(f"{BASE}{path}", headers=self._headers(), json=json_body)
            r.raise_for_status()
            return r.json()

    async def _delete(self, path: str) -> bool:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.delete(f"{BASE}{path}", headers=self._headers())
            r.raise_for_status()
            return True

    # ── contacts ─────────────────────────────────────────────

    async def list_contacts(self, limit: int = 20, after: str | None = None,
                            properties: list[str] | None = None) -> dict:
        """List contacts with optional pagination and property selection."""
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if after:
            params["after"] = after
        if properties:
            params["properties"] = ",".join(properties)
        return await self._get("/crm/v3/objects/contacts", params)

    async def get_contact(self, contact_id: str,
                          properties: list[str] | None = None) -> dict:
        """Get a single contact by ID."""
        params = {}
        if properties:
            params["properties"] = ",".join(properties)
        return await self._get(f"/crm/v3/objects/contacts/{contact_id}", params or None)

    async def create_contact(self, properties: dict) -> dict:
        """Create a contact. properties: {email, firstname, lastname, phone, ...}"""
        return await self._post("/crm/v3/objects/contacts", {"properties": properties})

    async def update_contact(self, contact_id: str, properties: dict) -> dict:
        """Update a contact's properties."""
        return await self._patch(f"/crm/v3/objects/contacts/{contact_id}",
                                 {"properties": properties})

    async def delete_contact(self, contact_id: str) -> bool:
        """Archive (soft-delete) a contact."""
        return await self._delete(f"/crm/v3/objects/contacts/{contact_id}")

    async def search_contacts(self, query: str, limit: int = 10,
                              properties: list[str] | None = None) -> dict:
        """Search contacts by query string."""
        body: dict[str, Any] = {
            "query": query,
            "limit": min(limit, 100),
        }
        if properties:
            body["properties"] = properties
        return await self._post("/crm/v3/objects/contacts/search", body)

    # ── companies ────────────────────────────────────────────

    async def list_companies(self, limit: int = 20, after: str | None = None,
                             properties: list[str] | None = None) -> dict:
        """List companies with optional pagination."""
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if after:
            params["after"] = after
        if properties:
            params["properties"] = ",".join(properties)
        return await self._get("/crm/v3/objects/companies", params)

    async def get_company(self, company_id: str,
                          properties: list[str] | None = None) -> dict:
        """Get a single company by ID."""
        params = {}
        if properties:
            params["properties"] = ",".join(properties)
        return await self._get(f"/crm/v3/objects/companies/{company_id}", params or None)

    async def create_company(self, properties: dict) -> dict:
        """Create a company. properties: {name, domain, industry, ...}"""
        return await self._post("/crm/v3/objects/companies", {"properties": properties})

    async def update_company(self, company_id: str, properties: dict) -> dict:
        """Update a company's properties."""
        return await self._patch(f"/crm/v3/objects/companies/{company_id}",
                                 {"properties": properties})

    async def delete_company(self, company_id: str) -> bool:
        """Archive (soft-delete) a company."""
        return await self._delete(f"/crm/v3/objects/companies/{company_id}")

    async def search_companies(self, query: str, limit: int = 10,
                               properties: list[str] | None = None) -> dict:
        """Search companies by query string."""
        body: dict[str, Any] = {
            "query": query,
            "limit": min(limit, 100),
        }
        if properties:
            body["properties"] = properties
        return await self._post("/crm/v3/objects/companies/search", body)

    # ── deals ────────────────────────────────────────────────

    async def list_deals(self, limit: int = 20, after: str | None = None,
                         properties: list[str] | None = None) -> dict:
        """List deals with optional pagination."""
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if after:
            params["after"] = after
        if properties:
            params["properties"] = ",".join(properties)
        return await self._get("/crm/v3/objects/deals", params)

    async def get_deal(self, deal_id: str,
                       properties: list[str] | None = None) -> dict:
        """Get a single deal by ID."""
        params = {}
        if properties:
            params["properties"] = ",".join(properties)
        return await self._get(f"/crm/v3/objects/deals/{deal_id}", params or None)

    async def create_deal(self, properties: dict) -> dict:
        """Create a deal. properties: {dealname, amount, dealstage, pipeline, ...}"""
        return await self._post("/crm/v3/objects/deals", {"properties": properties})

    async def update_deal(self, deal_id: str, properties: dict) -> dict:
        """Update a deal's properties."""
        return await self._patch(f"/crm/v3/objects/deals/{deal_id}",
                                 {"properties": properties})

    async def delete_deal(self, deal_id: str) -> bool:
        """Archive (soft-delete) a deal."""
        return await self._delete(f"/crm/v3/objects/deals/{deal_id}")

    async def search_deals(self, query: str, limit: int = 10,
                           properties: list[str] | None = None) -> dict:
        """Search deals by query string."""
        body: dict[str, Any] = {
            "query": query,
            "limit": min(limit, 100),
        }
        if properties:
            body["properties"] = properties
        return await self._post("/crm/v3/objects/deals/search", body)

    # ── tickets ──────────────────────────────────────────────

    async def list_tickets(self, limit: int = 20, after: str | None = None,
                           properties: list[str] | None = None) -> dict:
        """List tickets with optional pagination."""
        params: dict[str, Any] = {"limit": min(limit, 100)}
        if after:
            params["after"] = after
        if properties:
            params["properties"] = ",".join(properties)
        return await self._get("/crm/v3/objects/tickets", params)

    async def get_ticket(self, ticket_id: str,
                         properties: list[str] | None = None) -> dict:
        """Get a single ticket by ID."""
        params = {}
        if properties:
            params["properties"] = ",".join(properties)
        return await self._get(f"/crm/v3/objects/tickets/{ticket_id}", params or None)

    async def create_ticket(self, properties: dict) -> dict:
        """Create a ticket. properties: {subject, content, hs_pipeline_stage, ...}"""
        return await self._post("/crm/v3/objects/tickets", {"properties": properties})

    async def update_ticket(self, ticket_id: str, properties: dict) -> dict:
        """Update a ticket's properties."""
        return await self._patch(f"/crm/v3/objects/tickets/{ticket_id}",
                                 {"properties": properties})

    async def delete_ticket(self, ticket_id: str) -> bool:
        """Archive (soft-delete) a ticket."""
        return await self._delete(f"/crm/v3/objects/tickets/{ticket_id}")

    # ── notes (engagements) ──────────────────────────────────

    async def create_note(self, body: str, contact_id: str | None = None,
                          company_id: str | None = None,
                          deal_id: str | None = None) -> dict:
        """Create a note and optionally associate it with a contact, company, or deal."""
        payload: dict[str, Any] = {
            "properties": {
                "hs_note_body": body,
                "hs_timestamp": None,  # API will use current time
            }
        }
        # Build associations
        associations = []
        if contact_id:
            associations.append({
                "to": {"id": contact_id},
                "types": [{"associationCategory": "HUBSPOT_DEFINED",
                           "associationTypeId": 202}]  # note_to_contact
            })
        if company_id:
            associations.append({
                "to": {"id": company_id},
                "types": [{"associationCategory": "HUBSPOT_DEFINED",
                           "associationTypeId": 190}]  # note_to_company
            })
        if deal_id:
            associations.append({
                "to": {"id": deal_id},
                "types": [{"associationCategory": "HUBSPOT_DEFINED",
                           "associationTypeId": 214}]  # note_to_deal
            })
        if associations:
            payload["associations"] = associations
        return await self._post("/crm/v3/objects/notes", payload)

    async def get_note(self, note_id: str) -> dict:
        """Get a note by ID."""
        return await self._get(f"/crm/v3/objects/notes/{note_id}",
                               {"properties": "hs_note_body,hs_timestamp"})

    # ── associations ─────────────────────────────────────────

    async def get_associations(self, object_type: str, object_id: str,
                               to_object_type: str) -> dict:
        """Get associations between objects (e.g. contact→deals)."""
        return await self._get(
            f"/crm/v4/objects/{object_type}/{object_id}/associations/{to_object_type}"
        )

    async def create_association(self, from_type: str, from_id: str,
                                 to_type: str, to_id: str,
                                 association_type_id: int) -> dict:
        """Create an association between two objects."""
        return await self._post(
            f"/crm/v4/objects/{from_type}/{from_id}/associations/{to_type}/{to_id}",
            [{"associationCategory": "HUBSPOT_DEFINED",
              "associationTypeId": association_type_id}]
        )

    # ── pipelines ────────────────────────────────────────────

    async def list_pipelines(self, object_type: str = "deals") -> dict:
        """List pipelines for a given object type (deals or tickets)."""
        return await self._get(f"/crm/v3/pipelines/{object_type}")

    async def get_pipeline_stages(self, object_type: str = "deals",
                                  pipeline_id: str = "default") -> dict:
        """Get stages for a specific pipeline."""
        return await self._get(f"/crm/v3/pipelines/{object_type}/{pipeline_id}/stages")

    # ── owners ───────────────────────────────────────────────

    async def list_owners(self, limit: int = 100, after: str | None = None) -> dict:
        """List HubSpot owners (users who can be assigned to records)."""
        params: dict[str, Any] = {"limit": min(limit, 500)}
        if after:
            params["after"] = after
        return await self._get("/crm/v3/owners", params)
