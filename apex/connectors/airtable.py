"""
Airtable Connector - Airtable Base & Record Management

Bases, tables, records, and field management via Airtable REST API.

Setup:
    1. Go to https://airtable.com/create/tokens → create a personal access token
    2. Scopes needed: data.records:read, data.records:write, schema.bases:read

    export AIRTABLE_API_KEY="your-pat-token"

    from connectors.airtable import AirtableConnector
    airtable = AirtableConnector(api_key="...")
"""

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

BASE_URL = "https://api.airtable.com/v0"
META_URL = "https://api.airtable.com/v0/meta"


class AirtableConnector:
    """Airtable bases, tables, and records via REST API."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("AIRTABLE_API_KEY", "")
        self.connected = bool(self.api_key)

    async def connect(self) -> bool:
        """Validate Airtable API credentials."""
        self.connected = bool(self.api_key)
        return self.connected

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
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
            return resp.json()

    async def _patch(self, url: str, data: Dict) -> Any:
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.patch(url, headers=self._headers(), json=data)
            resp.raise_for_status()
            return resp.json()

    async def _delete(self, url: str, params: Optional[Dict] = None) -> Any:
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.delete(url, headers=self._headers(), params=params or {})
            resp.raise_for_status()
            return resp.json()

    # ── Bases ──

    async def list_bases(self) -> List[Dict]:
        """List all bases accessible to the token."""
        data = await self._get(f"{META_URL}/bases")
        return [{
            "id": b["id"],
            "name": b["name"],
            "permission_level": b.get("permissionLevel", ""),
        } for b in data.get("bases", [])]

    async def get_base_schema(self, base_id: str) -> Dict:
        """Get the schema (tables and fields) for a base.
        
        Args:
            base_id: Base ID (starts with 'app')
        """
        data = await self._get(f"{META_URL}/bases/{base_id}/tables")
        tables = []
        for t in data.get("tables", []):
            fields = [{
                "id": f["id"],
                "name": f["name"],
                "type": f["type"],
                "description": f.get("description", ""),
            } for f in t.get("fields", [])]
            tables.append({
                "id": t["id"],
                "name": t["name"],
                "description": t.get("description", ""),
                "primary_field_id": t.get("primaryFieldId", ""),
                "fields": fields,
                "field_count": len(fields),
            })
        return {
            "base_id": base_id,
            "table_count": len(tables),
            "tables": tables,
        }

    # ── Records ──

    async def list_records(
        self,
        base_id: str,
        table_name: str,
        view: Optional[str] = None,
        formula: Optional[str] = None,
        sort: Optional[List[Dict]] = None,
        fields: Optional[List[str]] = None,
        max_records: int = 100,
    ) -> List[Dict]:
        """List records from a table.
        
        Args:
            base_id: Base ID
            table_name: Table name or ID
            view: View name or ID to filter by
            formula: Airtable formula to filter records (e.g. "{Status}='Active'")
            sort: Sort list, e.g. [{"field": "Name", "direction": "asc"}]
            fields: List of field names to include (default: all)
            max_records: Max records to return (default 100)
        """
        params: Dict[str, Any] = {"maxRecords": str(max_records)}
        if view:
            params["view"] = view
        if formula:
            params["filterByFormula"] = formula
        if fields:
            for i, f in enumerate(fields):
                params[f"fields[{i}]"] = f
        if sort:
            for i, s in enumerate(sort):
                params[f"sort[{i}][field]"] = s["field"]
                params[f"sort[{i}][direction]"] = s.get("direction", "asc")

        all_records = []
        offset = None

        while True:
            if offset:
                params["offset"] = offset
            data = await self._get(f"{BASE_URL}/{base_id}/{table_name}", params)
            for r in data.get("records", []):
                all_records.append(self._parse_record(r))
            offset = data.get("offset")
            if not offset or len(all_records) >= max_records:
                break

        return all_records[:max_records]

    async def get_record(self, base_id: str, table_name: str, record_id: str) -> Dict:
        """Get a single record.
        
        Args:
            base_id: Base ID
            table_name: Table name or ID
            record_id: Record ID (starts with 'rec')
        """
        data = await self._get(f"{BASE_URL}/{base_id}/{table_name}/{record_id}")
        return self._parse_record(data)

    async def create_records(
        self,
        base_id: str,
        table_name: str,
        records: List[Dict],
    ) -> List[Dict]:
        """Create one or more records. Max 10 per call.
        
        Args:
            base_id: Base ID
            table_name: Table name or ID
            records: List of field dicts, e.g. [{"Name": "Test", "Status": "Active"}]
        """
        payload = {
            "records": [{"fields": r} for r in records[:10]],
        }
        data = await self._post(f"{BASE_URL}/{base_id}/{table_name}", payload)
        return [self._parse_record(r) for r in data.get("records", [])]

    async def update_records(
        self,
        base_id: str,
        table_name: str,
        records: List[Dict],
    ) -> List[Dict]:
        """Update one or more records. Max 10 per call.
        
        Args:
            base_id: Base ID
            table_name: Table name or ID
            records: List of {"id": "recXXX", "fields": {...}} dicts
        """
        payload = {
            "records": [{"id": r["id"], "fields": r["fields"]} for r in records[:10]],
        }
        data = await self._patch(f"{BASE_URL}/{base_id}/{table_name}", payload)
        return [self._parse_record(r) for r in data.get("records", [])]

    async def delete_records(
        self,
        base_id: str,
        table_name: str,
        record_ids: List[str],
    ) -> List[Dict]:
        """Delete one or more records. Max 10 per call.
        
        Args:
            base_id: Base ID
            table_name: Table name or ID
            record_ids: List of record IDs to delete
        """
        params = {f"records[{i}]": rid for i, rid in enumerate(record_ids[:10])}
        data = await self._delete(f"{BASE_URL}/{base_id}/{table_name}", params)
        return [{
            "id": r["id"],
            "deleted": r.get("deleted", True),
        } for r in data.get("records", [])]

    # ── Search / Query ──

    async def search_records(
        self,
        base_id: str,
        table_name: str,
        field: str,
        value: str,
        max_records: int = 20,
    ) -> List[Dict]:
        """Search for records where a field contains a value.
        
        Args:
            base_id: Base ID
            table_name: Table name or ID
            field: Field name to search in
            value: Value to search for (case-insensitive contains)
            max_records: Max results (default 20)
        """
        # Use SEARCH function for case-insensitive partial match
        formula = f'SEARCH(LOWER("{value}"), LOWER({{{field}}}))'
        return await self.list_records(
            base_id=base_id,
            table_name=table_name,
            formula=formula,
            max_records=max_records,
        )

    # ── Helpers ──

    def _parse_record(self, r: Dict) -> Dict:
        """Parse a record into a clean dict."""
        result: Dict[str, Any] = {
            "id": r["id"],
            "fields": r.get("fields", {}),
        }
        if r.get("createdTime"):
            result["created_time"] = r["createdTime"]
        return result
