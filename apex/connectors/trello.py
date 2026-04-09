"""
Trello Connector - Trello Board & Card Management

Boards, lists, cards, checklists, and labels via Trello REST API.

Setup:
    1. Go to https://trello.com/power-ups/admin → generate API key
    2. Generate a token: https://trello.com/1/authorize?expiration=never&scope=read,write&response_type=token&key=YOUR_KEY
    
    export TRELLO_API_KEY="your-api-key"
    export TRELLO_TOKEN="your-token"

    from connectors.trello import TrelloConnector
    trello = TrelloConnector(api_key="...", token="...")
"""

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

BASE_URL = "https://api.trello.com/1"


class TrelloConnector:
    """Trello boards, lists, and cards via REST API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        token: Optional[str] = None,
    ):
        self.api_key = api_key or os.environ.get("TRELLO_API_KEY", "")
        self.token = token or os.environ.get("TRELLO_TOKEN", "")
        self.connected = bool(self.api_key and self.token)

    def _auth(self) -> Dict[str, str]:
        return {"key": self.api_key, "token": self.token}

    async def _get(self, path: str, params: Optional[Dict] = None) -> Any:
        import httpx
        p = {**self._auth(), **(params or {})}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{BASE_URL}{path}", params=p)
            resp.raise_for_status()
            return resp.json()

    async def _post(self, path: str, data: Optional[Dict] = None) -> Any:
        import httpx
        p = {**self._auth(), **(data or {})}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{BASE_URL}{path}", params=p)
            resp.raise_for_status()
            return resp.json()

    async def _put(self, path: str, data: Optional[Dict] = None) -> Any:
        import httpx
        p = {**self._auth(), **(data or {})}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.put(f"{BASE_URL}{path}", params=p)
            resp.raise_for_status()
            return resp.json()

    async def _delete(self, path: str) -> bool:
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.delete(f"{BASE_URL}{path}", params=self._auth())
            resp.raise_for_status()
            return True

    # ── Boards ──

    async def list_boards(self, filter: str = "open") -> List[Dict]:
        """List boards for the authenticated user.
        
        Args:
            filter: 'open', 'closed', 'all' (default: open)
        """
        data = await self._get("/members/me/boards", {
            "filter": filter,
            "fields": "name,desc,url,closed,dateLastActivity,shortUrl",
            "lists": "open",
        })
        return [{
            "id": b["id"],
            "name": b["name"],
            "description": b.get("desc", ""),
            "url": b.get("shortUrl", b.get("url", "")),
            "closed": b.get("closed", False),
            "last_activity": b.get("dateLastActivity", ""),
            "list_count": len(b.get("lists", [])),
        } for b in data]

    async def get_board(self, board_id: str) -> Dict:
        """Get a board with its lists and labels.
        
        Args:
            board_id: Board ID
        """
        data = await self._get(f"/boards/{board_id}", {
            "fields": "name,desc,url,closed,dateLastActivity,shortUrl",
            "lists": "open",
            "list_fields": "name,pos,closed",
            "labels": "all",
            "label_fields": "name,color",
        })
        return {
            "id": data["id"],
            "name": data["name"],
            "description": data.get("desc", ""),
            "url": data.get("shortUrl", data.get("url", "")),
            "closed": data.get("closed", False),
            "lists": [{
                "id": l["id"],
                "name": l["name"],
            } for l in data.get("lists", [])],
            "labels": [{
                "id": l["id"],
                "name": l.get("name", ""),
                "color": l.get("color", ""),
            } for l in data.get("labels", []) if l.get("name")],
        }

    async def create_board(self, name: str, description: Optional[str] = None) -> Dict:
        """Create a new board.
        
        Args:
            name: Board name
            description: Board description
        """
        params: Dict[str, Any] = {"name": name, "defaultLists": "true"}
        if description:
            params["desc"] = description
        data = await self._post("/boards", params)
        return {
            "id": data["id"],
            "name": data["name"],
            "url": data.get("shortUrl", data.get("url", "")),
        }

    # ── Lists ──

    async def get_lists(self, board_id: str) -> List[Dict]:
        """Get all open lists on a board.
        
        Args:
            board_id: Board ID
        """
        data = await self._get(f"/boards/{board_id}/lists", {
            "filter": "open",
            "fields": "name,pos,closed",
            "cards": "open",
            "card_fields": "name",
        })
        return [{
            "id": l["id"],
            "name": l["name"],
            "card_count": len(l.get("cards", [])),
        } for l in data]

    async def create_list(self, board_id: str, name: str) -> Dict:
        """Create a new list on a board.
        
        Args:
            board_id: Board ID
            name: List name
        """
        data = await self._post("/lists", {"name": name, "idBoard": board_id})
        return {"id": data["id"], "name": data["name"]}

    async def archive_list(self, list_id: str) -> Dict:
        """Archive a list.
        
        Args:
            list_id: List ID
        """
        data = await self._put(f"/lists/{list_id}", {"closed": "true"})
        return {"id": data["id"], "name": data["name"], "archived": True}

    # ── Cards ──

    async def get_cards(
        self,
        list_id: Optional[str] = None,
        board_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """Get cards from a list or board.
        
        Args:
            list_id: List ID (gets cards in this list)
            board_id: Board ID (gets all cards on board)
            limit: Max results
        """
        if list_id:
            path = f"/lists/{list_id}/cards"
        elif board_id:
            path = f"/boards/{board_id}/cards"
        else:
            raise ValueError("Provide list_id or board_id")

        data = await self._get(path, {
            "fields": "name,desc,url,closed,due,dueComplete,dateLastActivity,idList,shortUrl,labels,idMembers",
            "limit": str(limit),
            "checklists": "all",
            "checklist_fields": "name",
            "members": "true",
            "member_fields": "fullName",
        })
        return [self._parse_card(c) for c in data]

    async def get_card(self, card_id: str) -> Dict:
        """Get a single card with full details.
        
        Args:
            card_id: Card ID
        """
        data = await self._get(f"/cards/{card_id}", {
            "fields": "name,desc,url,closed,due,dueComplete,dateLastActivity,idList,shortUrl,labels,idMembers",
            "checklists": "all",
            "checklist_fields": "name",
            "checkItem_fields": "name,state",
            "members": "true",
            "member_fields": "fullName",
            "actions": "commentCard",
            "actions_limit": "10",
        })
        result = self._parse_card(data)
        # Add comments
        result["comments"] = [{
            "text": a["data"].get("text", ""),
            "author": a.get("memberCreator", {}).get("fullName", ""),
            "date": a.get("date", ""),
        } for a in data.get("actions", [])]
        # Add checklist details
        result["checklists"] = [{
            "name": cl["name"],
            "items": [{
                "name": ci["name"],
                "complete": ci.get("state") == "complete",
            } for ci in cl.get("checkItems", [])],
        } for cl in data.get("checklists", [])]
        return result

    async def create_card(
        self,
        list_id: str,
        name: str,
        description: Optional[str] = None,
        due: Optional[str] = None,
        labels: Optional[List[str]] = None,
        member_ids: Optional[List[str]] = None,
        position: Optional[str] = None,
    ) -> Dict:
        """Create a new card.
        
        Args:
            list_id: List ID to create card in
            name: Card name/title
            description: Card description (supports markdown)
            due: Due date (ISO 8601 or YYYY-MM-DD)
            labels: List of label IDs
            member_ids: List of member IDs to assign
            position: 'top' or 'bottom' (default: bottom)
        """
        params: Dict[str, Any] = {"idList": list_id, "name": name}
        if description:
            params["desc"] = description
        if due:
            params["due"] = due
        if labels:
            params["idLabels"] = ",".join(labels)
        if member_ids:
            params["idMembers"] = ",".join(member_ids)
        if position:
            params["pos"] = position
        
        data = await self._post("/cards", params)
        return self._parse_card(data)

    async def update_card(
        self,
        card_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        due: Optional[str] = None,
        due_complete: Optional[bool] = None,
        list_id: Optional[str] = None,
        closed: Optional[bool] = None,
    ) -> Dict:
        """Update a card.
        
        Args:
            card_id: Card ID
            name: New name
            description: New description
            due: New due date
            due_complete: Mark due date complete/incomplete
            list_id: Move to a different list
            closed: Archive (True) or unarchive (False)
        """
        params: Dict[str, Any] = {}
        if name is not None:
            params["name"] = name
        if description is not None:
            params["desc"] = description
        if due is not None:
            params["due"] = due
        if due_complete is not None:
            params["dueComplete"] = str(due_complete).lower()
        if list_id is not None:
            params["idList"] = list_id
        if closed is not None:
            params["closed"] = str(closed).lower()
        
        data = await self._put(f"/cards/{card_id}", params)
        return self._parse_card(data)

    async def delete_card(self, card_id: str) -> bool:
        """Permanently delete a card.
        
        Args:
            card_id: Card ID
        """
        return await self._delete(f"/cards/{card_id}")

    async def add_comment(self, card_id: str, text: str) -> Dict:
        """Add a comment to a card.
        
        Args:
            card_id: Card ID
            text: Comment text
        """
        data = await self._post(f"/cards/{card_id}/actions/comments", {"text": text})
        return {
            "id": data.get("id", ""),
            "text": data.get("data", {}).get("text", text),
            "date": data.get("date", ""),
        }

    async def move_card(self, card_id: str, list_id: str) -> Dict:
        """Move a card to a different list.
        
        Args:
            card_id: Card ID
            list_id: Target list ID
        """
        return await self.update_card(card_id, list_id=list_id)

    # ── Checklists ──

    async def add_checklist(self, card_id: str, name: str, items: Optional[List[str]] = None) -> Dict:
        """Add a checklist to a card.
        
        Args:
            card_id: Card ID
            name: Checklist name
            items: List of checklist item names
        """
        data = await self._post("/checklists", {"idCard": card_id, "name": name})
        checklist_id = data["id"]
        
        added_items = []
        for item_name in (items or []):
            item = await self._post(f"/checklists/{checklist_id}/checkItems", {"name": item_name})
            added_items.append({"id": item["id"], "name": item["name"], "complete": False})
        
        return {
            "id": checklist_id,
            "name": data["name"],
            "items": added_items,
        }

    # ── Search ──

    async def search(
        self,
        query: str,
        model_types: str = "cards,boards",
        limit: int = 10,
    ) -> Dict:
        """Search across boards and cards.
        
        Args:
            query: Search text
            model_types: Comma-separated: 'cards', 'boards', 'organizations'
            limit: Max results per type (default 10)
        """
        data = await self._get("/search", {
            "query": query,
            "modelTypes": model_types,
            "cards_limit": str(limit),
            "boards_limit": str(limit),
            "card_fields": "name,desc,url,due,idList,shortUrl,labels",
            "board_fields": "name,desc,url,shortUrl",
        })
        result: Dict[str, Any] = {}
        if "cards" in data:
            result["cards"] = [self._parse_card(c) for c in data["cards"]]
        if "boards" in data:
            result["boards"] = [{
                "id": b["id"],
                "name": b["name"],
                "url": b.get("shortUrl", b.get("url", "")),
            } for b in data["boards"]]
        return result

    # ── Members ──

    async def get_board_members(self, board_id: str) -> List[Dict]:
        """Get members of a board.
        
        Args:
            board_id: Board ID
        """
        data = await self._get(f"/boards/{board_id}/members", {
            "fields": "fullName,username",
        })
        return [{
            "id": m["id"],
            "name": m.get("fullName", ""),
            "username": m.get("username", ""),
        } for m in data]

    # ── Helpers ──

    def _parse_card(self, c: Dict) -> Dict:
        """Parse a card into a clean dict."""
        result: Dict[str, Any] = {
            "id": c["id"],
            "name": c.get("name", ""),
            "url": c.get("shortUrl", c.get("url", "")),
        }
        if c.get("desc"):
            result["description"] = c["desc"][:500]
        if c.get("due"):
            result["due"] = c["due"]
            result["due_complete"] = c.get("dueComplete", False)
        if c.get("closed"):
            result["archived"] = True
        if c.get("labels"):
            result["labels"] = [{
                "name": l.get("name", ""),
                "color": l.get("color", ""),
            } for l in c["labels"] if l.get("name")]
        if c.get("members"):
            result["members"] = [m.get("fullName", "") for m in c["members"]]
        if c.get("dateLastActivity"):
            result["last_activity"] = c["dateLastActivity"]
        if c.get("checklists"):
            result["checklist_count"] = len(c["checklists"])
        return result
