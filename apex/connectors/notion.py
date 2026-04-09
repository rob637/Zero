"""
Notion Connector - Notion API Integration

Full CRUD for Notion pages, databases, and blocks.
Uses the official Notion API (v2022-06-28).

Setup:
    1. Create an integration at https://www.notion.so/my-integrations
    2. Get the Internal Integration Token
    3. Share pages/databases with your integration
    
    export NOTION_API_KEY="your-integration-token"

    from connectors.notion import NotionConnector
    notion = NotionConnector(api_key="your-key")
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

BASE_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class NotionConnector:
    """Notion workspace operations via the official API."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("NOTION_API_KEY", "")
        self.connected = bool(self.api_key)

    async def connect(self) -> bool:
        """Validate Notion API credentials."""
        self.connected = bool(self.api_key)
        return self.connected

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_VERSION,
        }

    async def _request(self, method: str, endpoint: str, json_data: Optional[Dict] = None, params: Optional[Dict] = None) -> Dict:
        """Make API request."""
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(
                method,
                f"{BASE_URL}/{endpoint}",
                headers=self._headers(),
                json=json_data,
                params=params,
            )
            resp.raise_for_status()
            return resp.json()

    # ── Search ──

    async def search(self, query: str = "", filter_type: Optional[str] = None, limit: int = 10) -> List[Dict]:
        """Search across all pages and databases shared with the integration.
        
        Args:
            query: Search text (empty returns recent pages)
            filter_type: "page" or "database" to filter results
            limit: Max results (default 10)
        """
        body: Dict[str, Any] = {"page_size": min(limit, 100)}
        if query:
            body["query"] = query
        if filter_type in ("page", "database"):
            body["filter"] = {"value": filter_type, "property": "object"}
        if not query:
            body["sort"] = {"direction": "descending", "timestamp": "last_edited_time"}

        data = await self._request("POST", "search", json_data=body)
        results = []
        for item in data.get("results", []):
            results.append(self._parse_result(item))
        return results

    # ── Pages ──

    async def get_page(self, page_id: str) -> Dict:
        """Get a page's properties.
        
        Args:
            page_id: The page ID (UUID, with or without dashes)
        """
        data = await self._request("GET", f"pages/{page_id}")
        return self._parse_result(data)

    async def create_page(
        self,
        parent_id: str,
        title: str,
        content: Optional[str] = None,
        properties: Optional[Dict] = None,
        parent_type: str = "page",
    ) -> Dict:
        """Create a new page.
        
        Args:
            parent_id: Parent page ID or database ID
            title: Page title
            content: Optional markdown-like content for the page body
            properties: Optional additional properties (for database pages)
            parent_type: "page" or "database" (default: page)
        """
        if parent_type == "database":
            parent = {"database_id": parent_id}
            # For database pages, title goes in properties
            props = properties or {}
            if "Name" not in props and "title" not in props:
                props["Name"] = {"title": [{"text": {"content": title}}]}
            body = {"parent": parent, "properties": props}
        else:
            parent = {"page_id": parent_id}
            body = {
                "parent": parent,
                "properties": {
                    "title": {"title": [{"text": {"content": title}}]},
                },
            }

        # Add content as blocks
        if content:
            body["children"] = self._text_to_blocks(content)

        data = await self._request("POST", "pages", json_data=body)
        return self._parse_result(data)

    async def update_page(self, page_id: str, properties: Dict) -> Dict:
        """Update a page's properties.
        
        Args:
            page_id: The page ID
            properties: Property values to update (Notion property format)
        """
        data = await self._request("PATCH", f"pages/{page_id}", json_data={"properties": properties})
        return self._parse_result(data)

    async def archive_page(self, page_id: str) -> Dict:
        """Archive (soft-delete) a page.
        
        Args:
            page_id: The page ID to archive
        """
        data = await self._request("PATCH", f"pages/{page_id}", json_data={"archived": True})
        return self._parse_result(data)

    async def restore_page(self, page_id: str) -> Dict:
        """Restore an archived page.
        
        Args:
            page_id: The page ID to restore
        """
        data = await self._request("PATCH", f"pages/{page_id}", json_data={"archived": False})
        return self._parse_result(data)

    # ── Page Content (Blocks) ──

    async def get_page_content(self, page_id: str) -> List[Dict]:
        """Get the content blocks of a page.
        
        Args:
            page_id: The page ID
        
        Returns list of content blocks (paragraphs, headings, lists, etc.)
        """
        data = await self._request("GET", f"blocks/{page_id}/children", params={"page_size": 100})
        blocks = []
        for block in data.get("results", []):
            blocks.append(self._parse_block(block))
        return blocks

    async def append_content(self, page_id: str, content: str) -> List[Dict]:
        """Append content blocks to a page.
        
        Args:
            page_id: The page ID
            content: Text content to append (supports simple markdown)
        """
        blocks = self._text_to_blocks(content)
        data = await self._request("PATCH", f"blocks/{page_id}/children", json_data={"children": blocks})
        return [self._parse_block(b) for b in data.get("results", [])]

    async def delete_block(self, block_id: str) -> Dict:
        """Delete a content block.
        
        Args:
            block_id: The block ID to delete
        """
        data = await self._request("DELETE", f"blocks/{block_id}")
        return {"id": block_id, "deleted": True}

    # ── Databases ──

    async def list_databases(self, limit: int = 10) -> List[Dict]:
        """List all databases shared with the integration.
        
        Args:
            limit: Max results (default 10)
        """
        return await self.search(filter_type="database", limit=limit)

    async def get_database(self, database_id: str) -> Dict:
        """Get database schema and metadata.
        
        Args:
            database_id: The database ID
        """
        data = await self._request("GET", f"databases/{database_id}")
        return {
            "id": data.get("id", ""),
            "title": self._extract_title(data),
            "description": self._extract_rich_text(data.get("description", [])),
            "properties": {
                name: {
                    "type": prop.get("type", ""),
                    "name": name,
                }
                for name, prop in data.get("properties", {}).items()
            },
            "created_time": data.get("created_time", ""),
            "last_edited_time": data.get("last_edited_time", ""),
            "url": data.get("url", ""),
        }

    async def query_database(
        self,
        database_id: str,
        filter_obj: Optional[Dict] = None,
        sorts: Optional[List[Dict]] = None,
        limit: int = 20,
    ) -> List[Dict]:
        """Query a database with optional filters and sorting.
        
        Args:
            database_id: The database ID
            filter_obj: Notion filter object (see Notion API docs)
            sorts: List of sort objects [{property: "Name", direction: "ascending"}]
            limit: Max results (default 20)
        """
        body: Dict[str, Any] = {"page_size": min(limit, 100)}
        if filter_obj:
            body["filter"] = filter_obj
        if sorts:
            body["sorts"] = sorts

        data = await self._request("POST", f"databases/{database_id}/query", json_data=body)
        return [self._parse_result(item) for item in data.get("results", [])]

    async def create_database(
        self,
        parent_page_id: str,
        title: str,
        properties: Dict[str, Dict],
    ) -> Dict:
        """Create a new database (inline in a page).
        
        Args:
            parent_page_id: Parent page ID
            title: Database title
            properties: Property schema, e.g. {"Name": {"title": {}}, "Status": {"select": {"options": [{"name": "Todo"}, {"name": "Done"}]}}}
        """
        body = {
            "parent": {"page_id": parent_page_id},
            "title": [{"text": {"content": title}}],
            "properties": properties,
        }
        data = await self._request("POST", "databases", json_data=body)
        return {
            "id": data.get("id", ""),
            "title": title,
            "url": data.get("url", ""),
            "created_time": data.get("created_time", ""),
        }

    # ── Users ──

    async def list_users(self, limit: int = 20) -> List[Dict]:
        """List all users in the workspace.
        
        Args:
            limit: Max results (default 20)
        """
        data = await self._request("GET", "users", params={"page_size": min(limit, 100)})
        return [{
            "id": u.get("id", ""),
            "name": u.get("name", ""),
            "type": u.get("type", ""),
            "email": u.get("person", {}).get("email", "") if u.get("type") == "person" else "",
            "avatar_url": u.get("avatar_url", ""),
        } for u in data.get("results", [])]

    # ── Comments ──

    async def get_comments(self, page_id: str) -> List[Dict]:
        """Get comments on a page.
        
        Args:
            page_id: The page ID
        """
        data = await self._request("GET", "comments", params={"block_id": page_id})
        return [{
            "id": c.get("id", ""),
            "text": self._extract_rich_text(c.get("rich_text", [])),
            "created_by": c.get("created_by", {}).get("id", ""),
            "created_time": c.get("created_time", ""),
        } for c in data.get("results", [])]

    async def add_comment(self, page_id: str, text: str) -> Dict:
        """Add a comment to a page.
        
        Args:
            page_id: The page ID
            text: Comment text
        """
        body = {
            "parent": {"page_id": page_id},
            "rich_text": [{"text": {"content": text}}],
        }
        data = await self._request("POST", "comments", json_data=body)
        return {
            "id": data.get("id", ""),
            "text": text,
            "created_time": data.get("created_time", ""),
        }

    # ── Internal Helpers ──

    def _parse_result(self, item: Dict) -> Dict:
        """Parse a page or database result into a clean dict."""
        obj_type = item.get("object", "page")
        result = {
            "id": item.get("id", ""),
            "type": obj_type,
            "title": self._extract_title(item),
            "url": item.get("url", ""),
            "created_time": item.get("created_time", ""),
            "last_edited_time": item.get("last_edited_time", ""),
            "archived": item.get("archived", False),
        }

        # Extract property values for database pages
        if obj_type == "page" and item.get("properties"):
            props = {}
            for name, prop in item["properties"].items():
                value = self._extract_property_value(prop)
                if value is not None:
                    props[name] = value
            result["properties"] = props

        return result

    def _extract_title(self, item: Dict) -> str:
        """Extract title from a page or database."""
        # Database title
        if isinstance(item.get("title"), list):
            return self._extract_rich_text(item["title"])

        # Page title from properties
        props = item.get("properties", {})
        for name, prop in props.items():
            if prop.get("type") == "title":
                return self._extract_rich_text(prop.get("title", []))

        return ""

    def _extract_rich_text(self, rich_text: List[Dict]) -> str:
        """Extract plain text from rich text array."""
        return "".join(t.get("plain_text", "") for t in rich_text)

    def _extract_property_value(self, prop: Dict) -> Any:
        """Extract a readable value from a Notion property."""
        ptype = prop.get("type", "")

        if ptype == "title":
            return self._extract_rich_text(prop.get("title", []))
        elif ptype == "rich_text":
            return self._extract_rich_text(prop.get("rich_text", []))
        elif ptype == "number":
            return prop.get("number")
        elif ptype == "select":
            sel = prop.get("select")
            return sel.get("name", "") if sel else None
        elif ptype == "multi_select":
            return [s.get("name", "") for s in prop.get("multi_select", [])]
        elif ptype == "status":
            s = prop.get("status")
            return s.get("name", "") if s else None
        elif ptype == "date":
            d = prop.get("date")
            if d:
                return {"start": d.get("start"), "end": d.get("end")}
            return None
        elif ptype == "checkbox":
            return prop.get("checkbox")
        elif ptype == "url":
            return prop.get("url")
        elif ptype == "email":
            return prop.get("email")
        elif ptype == "phone_number":
            return prop.get("phone_number")
        elif ptype == "formula":
            f = prop.get("formula", {})
            return f.get(f.get("type", ""))
        elif ptype == "relation":
            return [r.get("id", "") for r in prop.get("relation", [])]
        elif ptype == "people":
            return [p.get("name", p.get("id", "")) for p in prop.get("people", [])]
        elif ptype == "files":
            files = prop.get("files", [])
            return [f.get("name", f.get("external", {}).get("url", "")) for f in files]
        elif ptype == "created_time":
            return prop.get("created_time")
        elif ptype == "last_edited_time":
            return prop.get("last_edited_time")

        return None

    def _parse_block(self, block: Dict) -> Dict:
        """Parse a block into a readable dict."""
        btype = block.get("type", "unsupported")
        result = {
            "id": block.get("id", ""),
            "type": btype,
            "has_children": block.get("has_children", False),
        }

        block_data = block.get(btype, {})
        if isinstance(block_data, dict):
            # Extract text content
            rich_text = block_data.get("rich_text", [])
            if rich_text:
                result["text"] = self._extract_rich_text(rich_text)

            # Special fields
            if btype == "to_do":
                result["checked"] = block_data.get("checked", False)
            elif btype == "code":
                result["language"] = block_data.get("language", "")
            elif btype in ("image", "file", "video", "pdf"):
                file_obj = block_data.get("file") or block_data.get("external")
                if file_obj:
                    result["url"] = file_obj.get("url", "")
            elif btype == "bookmark":
                result["url"] = block_data.get("url", "")
            elif btype == "embed":
                result["url"] = block_data.get("url", "")

        return result

    def _text_to_blocks(self, content: str) -> List[Dict]:
        """Convert text content to Notion blocks.
        
        Supports simple formatting:
        - Lines starting with # → heading_1
        - Lines starting with ## → heading_2
        - Lines starting with ### → heading_3
        - Lines starting with - or * → bulleted_list_item
        - Lines starting with 1. → numbered_list_item
        - Lines starting with [ ] or [x] → to_do
        - Lines starting with > → quote
        - Lines starting with ``` → code block
        - Everything else → paragraph
        """
        blocks = []
        lines = content.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i]

            # Code block
            if line.startswith("```"):
                lang = line[3:].strip() or "plain text"
                code_lines = []
                i += 1
                while i < len(lines) and not lines[i].startswith("```"):
                    code_lines.append(lines[i])
                    i += 1
                blocks.append({
                    "object": "block",
                    "type": "code",
                    "code": {
                        "rich_text": [{"text": {"content": "\n".join(code_lines)}}],
                        "language": lang,
                    },
                })
                i += 1
                continue

            # Headings
            if line.startswith("### "):
                blocks.append(self._text_block("heading_3", line[4:]))
            elif line.startswith("## "):
                blocks.append(self._text_block("heading_2", line[3:]))
            elif line.startswith("# "):
                blocks.append(self._text_block("heading_1", line[2:]))
            # Lists
            elif line.startswith("- ") or line.startswith("* "):
                blocks.append(self._text_block("bulleted_list_item", line[2:]))
            elif len(line) > 2 and line[0].isdigit() and line[1:3] in (". ", ") "):
                blocks.append(self._text_block("numbered_list_item", line[3:]))
            # Todo
            elif line.startswith("[x] ") or line.startswith("[X] "):
                blocks.append({
                    "object": "block",
                    "type": "to_do",
                    "to_do": {
                        "rich_text": [{"text": {"content": line[4:]}}],
                        "checked": True,
                    },
                })
            elif line.startswith("[ ] "):
                blocks.append({
                    "object": "block",
                    "type": "to_do",
                    "to_do": {
                        "rich_text": [{"text": {"content": line[4:]}}],
                        "checked": False,
                    },
                })
            # Quote
            elif line.startswith("> "):
                blocks.append(self._text_block("quote", line[2:]))
            # Divider
            elif line.strip() in ("---", "***", "___"):
                blocks.append({"object": "block", "type": "divider", "divider": {}})
            # Paragraph (skip empty lines)
            elif line.strip():
                blocks.append(self._text_block("paragraph", line))

            i += 1

        return blocks

    def _text_block(self, block_type: str, text: str) -> Dict:
        """Create a simple text block."""
        return {
            "object": "block",
            "type": block_type,
            block_type: {
                "rich_text": [{"text": {"content": text}}],
            },
        }
