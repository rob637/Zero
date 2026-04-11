"""Telic Engine — Third-Party Services Primitives"""

import asyncio
import hashlib
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from .base import Primitive, StepResult

logger = logging.getLogger(__name__)


class NotionPrimitive(Primitive):
    """Notion — pages, databases, content blocks, and search.
    
    Uses the Notion API via NotionConnector.
    """
    
    def __init__(self, connector: Any = None):
        self._connector = connector
    
    @property
    def name(self) -> str:
        return "NOTION"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "search": "Search across all Notion pages and databases. Can filter by type (page/database).",
            "get_page": "Get a page's properties and metadata by ID",
            "get_page_content": "Get the content blocks (text, lists, headings) of a page",
            "create_page": "Create a new page under a parent page or database. Supports markdown-like content.",
            "update_page": "Update a page's properties",
            "append_content": "Add text content to the bottom of an existing page",
            "archive_page": "Archive (soft-delete) a page",
            "list_databases": "List all databases shared with the integration",
            "get_database": "Get a database's schema and metadata",
            "query_database": "Query a database with optional filters and sorting",
            "create_database": "Create a new inline database in a page",
            "add_comment": "Add a comment to a page",
            "get_comments": "Get all comments on a page",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "search": {
                "query": {"type": "str", "required": False, "description": "Search text (empty = recent pages)"},
                "filter_type": {"type": "str", "required": False, "description": "'page' or 'database'"},
                "limit": {"type": "int", "required": False, "description": "Max results (default 10)"},
            },
            "get_page": {
                "page_id": {"type": "str", "required": True, "description": "Page ID"},
            },
            "get_page_content": {
                "page_id": {"type": "str", "required": True, "description": "Page ID"},
            },
            "create_page": {
                "parent_id": {"type": "str", "required": True, "description": "Parent page ID or database ID"},
                "title": {"type": "str", "required": True, "description": "Page title"},
                "content": {"type": "str", "required": False, "description": "Page body content (markdown-like)"},
                "parent_type": {"type": "str", "required": False, "description": "'page' or 'database' (default: page)"},
            },
            "update_page": {
                "page_id": {"type": "str", "required": True, "description": "Page ID"},
                "properties": {"type": "dict", "required": True, "description": "Properties to update (Notion format)"},
            },
            "append_content": {
                "page_id": {"type": "str", "required": True, "description": "Page ID"},
                "content": {"type": "str", "required": True, "description": "Text to append"},
            },
            "archive_page": {
                "page_id": {"type": "str", "required": True, "description": "Page ID to archive"},
            },
            "list_databases": {
                "limit": {"type": "int", "required": False, "description": "Max results (default 10)"},
            },
            "get_database": {
                "database_id": {"type": "str", "required": True, "description": "Database ID"},
            },
            "query_database": {
                "database_id": {"type": "str", "required": True, "description": "Database ID"},
                "filter": {"type": "dict", "required": False, "description": "Notion filter object"},
                "sorts": {"type": "list", "required": False, "description": "Sort objects [{property, direction}]"},
                "limit": {"type": "int", "required": False, "description": "Max results (default 20)"},
            },
            "create_database": {
                "parent_page_id": {"type": "str", "required": True, "description": "Parent page ID"},
                "title": {"type": "str", "required": True, "description": "Database title"},
                "properties": {"type": "dict", "required": True, "description": "Property schema"},
            },
            "add_comment": {
                "page_id": {"type": "str", "required": True, "description": "Page ID"},
                "text": {"type": "str", "required": True, "description": "Comment text"},
            },
            "get_comments": {
                "page_id": {"type": "str", "required": True, "description": "Page ID"},
            },
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        if not self._connector:
            return StepResult(False, error="Notion is not configured. Connect Notion in Settings to use Notion features.")
        try:
            if operation == "search":
                results = await self._connector.search(
                    query=params.get("query", ""),
                    filter_type=params.get("filter_type"),
                    limit=int(params.get("limit", 10)),
                )
                return StepResult(True, data={"count": len(results), "results": results})
            
            elif operation == "get_page":
                result = await self._connector.get_page(params["page_id"])
                return StepResult(True, data=result)
            
            elif operation == "get_page_content":
                blocks = await self._connector.get_page_content(params["page_id"])
                return StepResult(True, data={"blocks": blocks})
            
            elif operation == "create_page":
                result = await self._connector.create_page(
                    parent_id=params["parent_id"],
                    title=params["title"],
                    content=params.get("content"),
                    parent_type=params.get("parent_type", "page"),
                )
                return StepResult(True, data=result)
            
            elif operation == "update_page":
                result = await self._connector.update_page(params["page_id"], params["properties"])
                return StepResult(True, data=result)
            
            elif operation == "append_content":
                blocks = await self._connector.append_content(params["page_id"], params["content"])
                return StepResult(True, data={"appended_blocks": len(blocks)})
            
            elif operation == "archive_page":
                result = await self._connector.archive_page(params["page_id"])
                return StepResult(True, data=result)
            
            elif operation == "list_databases":
                results = await self._connector.list_databases(limit=int(params.get("limit", 10)))
                return StepResult(True, data={"count": len(results), "databases": results})
            
            elif operation == "get_database":
                result = await self._connector.get_database(params["database_id"])
                return StepResult(True, data=result)
            
            elif operation == "query_database":
                results = await self._connector.query_database(
                    database_id=params["database_id"],
                    filter_obj=params.get("filter"),
                    sorts=params.get("sorts"),
                    limit=int(params.get("limit", 20)),
                )
                return StepResult(True, data={"count": len(results), "results": results})
            
            elif operation == "create_database":
                result = await self._connector.create_database(
                    parent_page_id=params["parent_page_id"],
                    title=params["title"],
                    properties=params["properties"],
                )
                return StepResult(True, data=result)
            
            elif operation == "add_comment":
                result = await self._connector.add_comment(params["page_id"], params["text"])
                return StepResult(True, data=result)
            
            elif operation == "get_comments":
                comments = await self._connector.get_comments(params["page_id"])
                return StepResult(True, data={"count": len(comments), "comments": comments})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  LINEAR PRIMITIVE
# ============================================================



class LinearPrimitive(Primitive):
    """Linear — issue tracking, projects, cycles, and teams.
    
    Uses the Linear GraphQL API via LinearConnector.
    """
    
    def __init__(self, connector: Any = None):
        self._connector = connector
    
    @property
    def name(self) -> str:
        return "LINEAR"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "list_issues": "List issues with optional filters by team, status, or assignee",
            "get_issue": "Get a single issue by ID or identifier (e.g. ENG-123)",
            "create_issue": "Create a new issue in a team with title, description, priority, labels, etc.",
            "update_issue": "Update an issue's title, description, status, priority, assignee, or due date",
            "add_comment": "Add a comment to an issue",
            "search_issues": "Full-text search across all issues",
            "list_teams": "List all teams with members, statuses, and labels",
            "list_cycles": "List cycles (sprints) with progress info",
            "list_projects": "List projects with progress and team info",
            "me": "Get the current authenticated user and their recent assigned issues",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "list_issues": {
                "team_key": {"type": "str", "required": False, "description": "Team key to filter (e.g. 'ENG')"},
                "status": {"type": "str", "required": False, "description": "Status name (e.g. 'In Progress', 'Done', 'Todo')"},
                "assignee": {"type": "str", "required": False, "description": "Assignee name or 'me' for current user"},
                "limit": {"type": "int", "required": False, "description": "Max results (default 20)"},
            },
            "get_issue": {
                "issue_id": {"type": "str", "required": True, "description": "Issue UUID or identifier like 'ENG-123'"},
            },
            "create_issue": {
                "title": {"type": "str", "required": True, "description": "Issue title"},
                "team_key": {"type": "str", "required": True, "description": "Team key (e.g. 'ENG'). Use list_teams to find available teams."},
                "description": {"type": "str", "required": False, "description": "Issue description (supports markdown)"},
                "priority": {"type": "int", "required": False, "description": "0=No priority, 1=Urgent, 2=High, 3=Medium, 4=Low"},
                "status": {"type": "str", "required": False, "description": "Status name (e.g. 'Todo', 'In Progress')"},
                "labels": {"type": "list", "required": False, "description": "List of label names"},
                "due_date": {"type": "str", "required": False, "description": "Due date (YYYY-MM-DD)"},
                "estimate": {"type": "int", "required": False, "description": "Story points estimate"},
            },
            "update_issue": {
                "issue_id": {"type": "str", "required": True, "description": "Issue UUID"},
                "title": {"type": "str", "required": False, "description": "New title"},
                "description": {"type": "str", "required": False, "description": "New description"},
                "status": {"type": "str", "required": False, "description": "New status name"},
                "priority": {"type": "int", "required": False, "description": "New priority (0-4)"},
                "due_date": {"type": "str", "required": False, "description": "New due date (YYYY-MM-DD)"},
                "estimate": {"type": "int", "required": False, "description": "New estimate"},
            },
            "add_comment": {
                "issue_id": {"type": "str", "required": True, "description": "Issue UUID"},
                "body": {"type": "str", "required": True, "description": "Comment text (supports markdown)"},
            },
            "search_issues": {
                "query": {"type": "str", "required": True, "description": "Search text"},
                "limit": {"type": "int", "required": False, "description": "Max results (default 20)"},
            },
            "list_teams": {},
            "list_cycles": {
                "team_key": {"type": "str", "required": False, "description": "Filter by team key"},
                "limit": {"type": "int", "required": False, "description": "Max results (default 5)"},
            },
            "list_projects": {
                "limit": {"type": "int", "required": False, "description": "Max results (default 10)"},
            },
            "me": {},
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        if not self._connector:
            return StepResult(False, error="Linear is not configured. Connect Linear in Settings to use Linear features.")
        try:
            if operation == "list_issues":
                results = await self._connector.list_issues(
                    team_key=params.get("team_key"),
                    status=params.get("status"),
                    assignee=params.get("assignee"),
                    limit=int(params.get("limit", 20)),
                )
                return StepResult(True, data={"count": len(results), "issues": results})
            
            elif operation == "get_issue":
                result = await self._connector.get_issue(params["issue_id"])
                return StepResult(True, data=result)
            
            elif operation == "create_issue":
                result = await self._connector.create_issue(
                    title=params["title"],
                    team_key=params["team_key"],
                    description=params.get("description"),
                    priority=int(params["priority"]) if params.get("priority") is not None else None,
                    status=params.get("status"),
                    labels=params.get("labels"),
                    due_date=params.get("due_date"),
                    estimate=int(params["estimate"]) if params.get("estimate") is not None else None,
                )
                return StepResult(True, data=result)
            
            elif operation == "update_issue":
                result = await self._connector.update_issue(
                    issue_id=params["issue_id"],
                    title=params.get("title"),
                    description=params.get("description"),
                    status=params.get("status"),
                    priority=int(params["priority"]) if params.get("priority") is not None else None,
                    due_date=params.get("due_date"),
                    estimate=int(params["estimate"]) if params.get("estimate") is not None else None,
                )
                return StepResult(True, data=result)
            
            elif operation == "add_comment":
                result = await self._connector.add_comment(params["issue_id"], params["body"])
                return StepResult(True, data=result)
            
            elif operation == "search_issues":
                results = await self._connector.search_issues(
                    query=params["query"],
                    limit=int(params.get("limit", 20)),
                )
                return StepResult(True, data={"count": len(results), "issues": results})
            
            elif operation == "list_teams":
                results = await self._connector.list_teams()
                return StepResult(True, data={"count": len(results), "teams": results})
            
            elif operation == "list_cycles":
                results = await self._connector.list_cycles(
                    team_key=params.get("team_key"),
                    limit=int(params.get("limit", 5)),
                )
                return StepResult(True, data={"count": len(results), "cycles": results})
            
            elif operation == "list_projects":
                results = await self._connector.list_projects(
                    limit=int(params.get("limit", 10)),
                )
                return StepResult(True, data={"count": len(results), "projects": results})
            
            elif operation == "me":
                result = await self._connector.me()
                return StepResult(True, data=result)
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  TRELLO PRIMITIVE
# ============================================================



class TrelloPrimitive(Primitive):
    """Trello — boards, lists, cards, checklists, and search.
    
    Uses the Trello REST API via TrelloConnector.
    """
    
    def __init__(self, connector: Any = None):
        self._connector = connector
    
    @property
    def name(self) -> str:
        return "TRELLO"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "list_boards": "List all boards for the authenticated user",
            "get_board": "Get a board with its lists, labels, and metadata",
            "create_board": "Create a new board",
            "get_lists": "Get all lists on a board",
            "create_list": "Create a new list on a board",
            "get_cards": "Get cards from a list or board",
            "get_card": "Get a single card with comments, checklists, and full details",
            "create_card": "Create a new card in a list with name, description, due date, labels",
            "update_card": "Update a card's name, description, due date, list, or archive status",
            "move_card": "Move a card to a different list",
            "delete_card": "Permanently delete a card",
            "add_comment": "Add a comment to a card",
            "add_checklist": "Add a checklist with items to a card",
            "search": "Search across boards and cards",
            "get_board_members": "Get members of a board",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "list_boards": {
                "filter": {"type": "str", "required": False, "description": "'open', 'closed', or 'all' (default: open)"},
            },
            "get_board": {
                "board_id": {"type": "str", "required": True, "description": "Board ID"},
            },
            "create_board": {
                "name": {"type": "str", "required": True, "description": "Board name"},
                "description": {"type": "str", "required": False, "description": "Board description"},
            },
            "get_lists": {
                "board_id": {"type": "str", "required": True, "description": "Board ID"},
            },
            "create_list": {
                "board_id": {"type": "str", "required": True, "description": "Board ID"},
                "name": {"type": "str", "required": True, "description": "List name"},
            },
            "get_cards": {
                "list_id": {"type": "str", "required": False, "description": "List ID (get cards in this list)"},
                "board_id": {"type": "str", "required": False, "description": "Board ID (get all cards on board)"},
                "limit": {"type": "int", "required": False, "description": "Max results (default 50)"},
            },
            "get_card": {
                "card_id": {"type": "str", "required": True, "description": "Card ID"},
            },
            "create_card": {
                "list_id": {"type": "str", "required": True, "description": "List ID to create card in"},
                "name": {"type": "str", "required": True, "description": "Card name/title"},
                "description": {"type": "str", "required": False, "description": "Card description (markdown)"},
                "due": {"type": "str", "required": False, "description": "Due date (ISO 8601 or YYYY-MM-DD)"},
                "labels": {"type": "list", "required": False, "description": "List of label IDs"},
                "position": {"type": "str", "required": False, "description": "'top' or 'bottom'"},
            },
            "update_card": {
                "card_id": {"type": "str", "required": True, "description": "Card ID"},
                "name": {"type": "str", "required": False, "description": "New name"},
                "description": {"type": "str", "required": False, "description": "New description"},
                "due": {"type": "str", "required": False, "description": "New due date"},
                "due_complete": {"type": "bool", "required": False, "description": "Mark due date complete"},
                "list_id": {"type": "str", "required": False, "description": "Move to different list"},
                "closed": {"type": "bool", "required": False, "description": "Archive (true) or unarchive (false)"},
            },
            "move_card": {
                "card_id": {"type": "str", "required": True, "description": "Card ID"},
                "list_id": {"type": "str", "required": True, "description": "Target list ID"},
            },
            "delete_card": {
                "card_id": {"type": "str", "required": True, "description": "Card ID"},
            },
            "add_comment": {
                "card_id": {"type": "str", "required": True, "description": "Card ID"},
                "text": {"type": "str", "required": True, "description": "Comment text"},
            },
            "add_checklist": {
                "card_id": {"type": "str", "required": True, "description": "Card ID"},
                "name": {"type": "str", "required": True, "description": "Checklist name"},
                "items": {"type": "list", "required": False, "description": "List of checklist item names"},
            },
            "search": {
                "query": {"type": "str", "required": True, "description": "Search text"},
                "model_types": {"type": "str", "required": False, "description": "Comma-separated: 'cards', 'boards' (default: both)"},
                "limit": {"type": "int", "required": False, "description": "Max results per type (default 10)"},
            },
            "get_board_members": {
                "board_id": {"type": "str", "required": True, "description": "Board ID"},
            },
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        if not self._connector:
            return StepResult(False, error="Trello is not configured. Connect Trello in Settings to use Trello features.")
        try:
            if operation == "list_boards":
                results = await self._connector.list_boards(
                    filter=params.get("filter", "open"),
                )
                return StepResult(True, data={"count": len(results), "boards": results})
            
            elif operation == "get_board":
                result = await self._connector.get_board(params["board_id"])
                return StepResult(True, data=result)
            
            elif operation == "create_board":
                result = await self._connector.create_board(
                    name=params["name"],
                    description=params.get("description"),
                )
                return StepResult(True, data=result)
            
            elif operation == "get_lists":
                results = await self._connector.get_lists(params["board_id"])
                return StepResult(True, data={"count": len(results), "lists": results})
            
            elif operation == "create_list":
                result = await self._connector.create_list(params["board_id"], params["name"])
                return StepResult(True, data=result)
            
            elif operation == "get_cards":
                results = await self._connector.get_cards(
                    list_id=params.get("list_id"),
                    board_id=params.get("board_id"),
                    limit=int(params.get("limit", 50)),
                )
                return StepResult(True, data={"count": len(results), "cards": results})
            
            elif operation == "get_card":
                result = await self._connector.get_card(params["card_id"])
                return StepResult(True, data=result)
            
            elif operation == "create_card":
                result = await self._connector.create_card(
                    list_id=params["list_id"],
                    name=params["name"],
                    description=params.get("description"),
                    due=params.get("due"),
                    labels=params.get("labels"),
                    position=params.get("position"),
                )
                return StepResult(True, data=result)
            
            elif operation == "update_card":
                result = await self._connector.update_card(
                    card_id=params["card_id"],
                    name=params.get("name"),
                    description=params.get("description"),
                    due=params.get("due"),
                    due_complete=params.get("due_complete"),
                    list_id=params.get("list_id"),
                    closed=params.get("closed"),
                )
                return StepResult(True, data=result)
            
            elif operation == "move_card":
                result = await self._connector.move_card(params["card_id"], params["list_id"])
                return StepResult(True, data=result)
            
            elif operation == "delete_card":
                await self._connector.delete_card(params["card_id"])
                return StepResult(True, data={"deleted": True})
            
            elif operation == "add_comment":
                result = await self._connector.add_comment(params["card_id"], params["text"])
                return StepResult(True, data=result)
            
            elif operation == "add_checklist":
                result = await self._connector.add_checklist(
                    card_id=params["card_id"],
                    name=params["name"],
                    items=params.get("items"),
                )
                return StepResult(True, data=result)
            
            elif operation == "search":
                results = await self._connector.search(
                    query=params["query"],
                    model_types=params.get("model_types", "cards,boards"),
                    limit=int(params.get("limit", 10)),
                )
                return StepResult(True, data=results)
            
            elif operation == "get_board_members":
                results = await self._connector.get_board_members(params["board_id"])
                return StepResult(True, data={"count": len(results), "members": results})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  AIRTABLE PRIMITIVE
# ============================================================



class AirtablePrimitive(Primitive):
    """Airtable — bases, tables, and records.
    
    Uses the Airtable REST API via AirtableConnector.
    """
    
    def __init__(self, connector: Any = None):
        self._connector = connector
    
    @property
    def name(self) -> str:
        return "AIRTABLE"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "list_bases": "List all Airtable bases accessible to the token",
            "get_base_schema": "Get the schema (tables and fields) for a base",
            "list_records": "List records from a table with optional filters, sorting, and field selection",
            "get_record": "Get a single record by ID",
            "create_records": "Create one or more records in a table (max 10 per call)",
            "update_records": "Update one or more records (max 10 per call)",
            "delete_records": "Delete one or more records by ID (max 10 per call)",
            "search_records": "Search for records where a field contains a value",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "list_bases": {},
            "get_base_schema": {
                "base_id": {"type": "str", "required": True, "description": "Base ID (starts with 'app')"},
            },
            "list_records": {
                "base_id": {"type": "str", "required": True, "description": "Base ID"},
                "table_name": {"type": "str", "required": True, "description": "Table name or ID"},
                "view": {"type": "str", "required": False, "description": "View name or ID to filter by"},
                "formula": {"type": "str", "required": False, "description": "Airtable formula filter (e.g. \"{Status}='Active'\")"},
                "sort": {"type": "list", "required": False, "description": "Sort list [{field, direction}]"},
                "fields": {"type": "list", "required": False, "description": "Field names to include"},
                "max_records": {"type": "int", "required": False, "description": "Max records (default 100)"},
            },
            "get_record": {
                "base_id": {"type": "str", "required": True, "description": "Base ID"},
                "table_name": {"type": "str", "required": True, "description": "Table name or ID"},
                "record_id": {"type": "str", "required": True, "description": "Record ID (starts with 'rec')"},
            },
            "create_records": {
                "base_id": {"type": "str", "required": True, "description": "Base ID"},
                "table_name": {"type": "str", "required": True, "description": "Table name or ID"},
                "records": {"type": "list", "required": True, "description": "List of field dicts, e.g. [{\"Name\": \"Test\"}]"},
            },
            "update_records": {
                "base_id": {"type": "str", "required": True, "description": "Base ID"},
                "table_name": {"type": "str", "required": True, "description": "Table name or ID"},
                "records": {"type": "list", "required": True, "description": "List of {id, fields} dicts"},
            },
            "delete_records": {
                "base_id": {"type": "str", "required": True, "description": "Base ID"},
                "table_name": {"type": "str", "required": True, "description": "Table name or ID"},
                "record_ids": {"type": "list", "required": True, "description": "List of record IDs to delete"},
            },
            "search_records": {
                "base_id": {"type": "str", "required": True, "description": "Base ID"},
                "table_name": {"type": "str", "required": True, "description": "Table name or ID"},
                "field": {"type": "str", "required": True, "description": "Field name to search in"},
                "value": {"type": "str", "required": True, "description": "Value to search for"},
                "max_records": {"type": "int", "required": False, "description": "Max results (default 20)"},
            },
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        if not self._connector:
            return StepResult(False, error="Airtable is not configured. Connect Airtable in Settings to use Airtable features.")
        try:
            if operation == "list_bases":
                results = await self._connector.list_bases()
                return StepResult(True, data={"count": len(results), "bases": results})
            
            elif operation == "get_base_schema":
                result = await self._connector.get_base_schema(params["base_id"])
                return StepResult(True, data=result)
            
            elif operation == "list_records":
                results = await self._connector.list_records(
                    base_id=params["base_id"],
                    table_name=params["table_name"],
                    view=params.get("view"),
                    formula=params.get("formula"),
                    sort=params.get("sort"),
                    fields=params.get("fields"),
                    max_records=int(params.get("max_records", 100)),
                )
                return StepResult(True, data={"count": len(results), "records": results})
            
            elif operation == "get_record":
                result = await self._connector.get_record(
                    params["base_id"], params["table_name"], params["record_id"],
                )
                return StepResult(True, data=result)
            
            elif operation == "create_records":
                results = await self._connector.create_records(
                    base_id=params["base_id"],
                    table_name=params["table_name"],
                    records=params["records"],
                )
                return StepResult(True, data={"count": len(results), "records": results})
            
            elif operation == "update_records":
                results = await self._connector.update_records(
                    base_id=params["base_id"],
                    table_name=params["table_name"],
                    records=params["records"],
                )
                return StepResult(True, data={"count": len(results), "records": results})
            
            elif operation == "delete_records":
                results = await self._connector.delete_records(
                    base_id=params["base_id"],
                    table_name=params["table_name"],
                    record_ids=params["record_ids"],
                )
                return StepResult(True, data={"count": len(results), "deleted": results})
            
            elif operation == "search_records":
                results = await self._connector.search_records(
                    base_id=params["base_id"],
                    table_name=params["table_name"],
                    field=params["field"],
                    value=params["value"],
                    max_records=int(params.get("max_records", 20)),
                )
                return StepResult(True, data={"count": len(results), "records": results})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  ZOOM PRIMITIVE
# ============================================================



class ZoomPrimitive(Primitive):
    """Zoom — meetings, recordings, participants, and user profile.
    
    Uses the Zoom REST API via ZoomConnector.
    """
    
    def __init__(self, connector: Any = None):
        self._connector = connector
    
    @property
    def name(self) -> str:
        return "ZOOM"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "me": "Get the current Zoom user's profile",
            "list_meetings": "List meetings (scheduled, live, upcoming, or past)",
            "get_meeting": "Get full meeting details including join URL and settings",
            "create_meeting": "Schedule a new meeting with topic, time, duration, and settings",
            "update_meeting": "Update a meeting's topic, time, duration, or agenda",
            "delete_meeting": "Delete/cancel a meeting",
            "get_participants": "Get participants from a past meeting",
            "list_recordings": "List cloud recordings with download links",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "me": {},
            "list_meetings": {
                "type": {"type": "str", "required": False, "description": "'scheduled', 'live', 'upcoming', or 'previous_meetings'"},
                "page_size": {"type": "int", "required": False, "description": "Results per page (default 30, max 300)"},
            },
            "get_meeting": {
                "meeting_id": {"type": "str", "required": True, "description": "Meeting ID"},
            },
            "create_meeting": {
                "topic": {"type": "str", "required": True, "description": "Meeting title"},
                "start_time": {"type": "str", "required": False, "description": "Start time ISO 8601 (e.g. 2026-04-15T10:00:00Z)"},
                "duration": {"type": "int", "required": False, "description": "Duration in minutes (default 60)"},
                "timezone": {"type": "str", "required": False, "description": "Timezone (e.g. America/New_York)"},
                "agenda": {"type": "str", "required": False, "description": "Meeting description/agenda"},
                "password": {"type": "str", "required": False, "description": "Meeting password"},
                "waiting_room": {"type": "bool", "required": False, "description": "Enable waiting room"},
            },
            "update_meeting": {
                "meeting_id": {"type": "str", "required": True, "description": "Meeting ID"},
                "topic": {"type": "str", "required": False, "description": "New topic"},
                "start_time": {"type": "str", "required": False, "description": "New start time (ISO 8601)"},
                "duration": {"type": "int", "required": False, "description": "New duration in minutes"},
                "agenda": {"type": "str", "required": False, "description": "New agenda"},
            },
            "delete_meeting": {
                "meeting_id": {"type": "str", "required": True, "description": "Meeting ID"},
            },
            "get_participants": {
                "meeting_id": {"type": "str", "required": True, "description": "Past meeting UUID"},
            },
            "list_recordings": {
                "from_date": {"type": "str", "required": False, "description": "Start date (YYYY-MM-DD)"},
                "to_date": {"type": "str", "required": False, "description": "End date (YYYY-MM-DD)"},
            },
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        if not self._connector:
            return StepResult(False, error="Zoom is not configured. Connect Zoom in Settings to use Zoom features.")
        try:
            if operation == "me":
                result = await self._connector.me()
                return StepResult(True, data=result)
            
            elif operation == "list_meetings":
                results = await self._connector.list_meetings(
                    type=params.get("type", "scheduled"),
                    page_size=int(params.get("page_size", 30)),
                )
                return StepResult(True, data={"count": len(results), "meetings": results})
            
            elif operation == "get_meeting":
                result = await self._connector.get_meeting(params["meeting_id"])
                return StepResult(True, data=result)
            
            elif operation == "create_meeting":
                result = await self._connector.create_meeting(
                    topic=params["topic"],
                    start_time=params.get("start_time"),
                    duration=int(params.get("duration", 60)),
                    timezone=params.get("timezone"),
                    agenda=params.get("agenda"),
                    password=params.get("password"),
                    waiting_room=bool(params.get("waiting_room", False)),
                )
                return StepResult(True, data=result)
            
            elif operation == "update_meeting":
                await self._connector.update_meeting(
                    meeting_id=params["meeting_id"],
                    topic=params.get("topic"),
                    start_time=params.get("start_time"),
                    duration=int(params["duration"]) if params.get("duration") else None,
                    agenda=params.get("agenda"),
                )
                return StepResult(True, data={"updated": True})
            
            elif operation == "delete_meeting":
                await self._connector.delete_meeting(params["meeting_id"])
                return StepResult(True, data={"deleted": True})
            
            elif operation == "get_participants":
                results = await self._connector.get_meeting_participants(params["meeting_id"])
                return StepResult(True, data={"count": len(results), "participants": results})
            
            elif operation == "list_recordings":
                results = await self._connector.list_recordings(
                    from_date=params.get("from_date"),
                    to_date=params.get("to_date"),
                )
                return StepResult(True, data={"count": len(results), "recordings": results})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  LINKEDIN PRIMITIVE
# ============================================================



class LinkedInPrimitive(Primitive):
    """LinkedIn — profile, posts, shares, and organization search.
    
    Uses the LinkedIn REST API via LinkedInConnector.
    """
    
    def __init__(self, connector: Any = None):
        self._connector = connector
    
    @property
    def name(self) -> str:
        return "LINKEDIN"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "me": "Get the current LinkedIn user's profile",
            "create_post": "Create a text or article post on LinkedIn",
            "get_posts": "Get the current user's recent posts",
            "delete_post": "Delete a post",
            "get_organization": "Get company/organization details by ID",
            "search_companies": "Search for companies by keywords",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "me": {},
            "create_post": {
                "text": {"type": "str", "required": True, "description": "Post text content"},
                "visibility": {"type": "str", "required": False, "description": "'PUBLIC' or 'CONNECTIONS' (default: PUBLIC)"},
                "article_url": {"type": "str", "required": False, "description": "URL to share as an article"},
                "article_title": {"type": "str", "required": False, "description": "Title for the article link"},
                "article_description": {"type": "str", "required": False, "description": "Description for the article link"},
            },
            "get_posts": {
                "limit": {"type": "int", "required": False, "description": "Max posts (default 10)"},
            },
            "delete_post": {
                "post_urn": {"type": "str", "required": True, "description": "Post URN (e.g. urn:li:ugcPost:123456)"},
            },
            "get_organization": {
                "org_id": {"type": "str", "required": True, "description": "Organization ID (numeric)"},
            },
            "search_companies": {
                "keywords": {"type": "str", "required": True, "description": "Search keywords"},
                "limit": {"type": "int", "required": False, "description": "Max results (default 10)"},
            },
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        if not self._connector:
            return StepResult(False, error="LinkedIn is not configured. Connect LinkedIn in Settings to use LinkedIn features.")
        try:
            if operation == "me":
                result = await self._connector.me()
                return StepResult(True, data=result)
            
            elif operation == "create_post":
                result = await self._connector.create_post(
                    text=params["text"],
                    visibility=params.get("visibility", "PUBLIC"),
                    article_url=params.get("article_url"),
                    article_title=params.get("article_title"),
                    article_description=params.get("article_description"),
                )
                return StepResult(True, data=result)
            
            elif operation == "get_posts":
                results = await self._connector.get_posts(
                    limit=int(params.get("limit", 10)),
                )
                return StepResult(True, data={"count": len(results), "posts": results})
            
            elif operation == "delete_post":
                await self._connector.delete_post(params["post_urn"])
                return StepResult(True, data={"deleted": True})
            
            elif operation == "get_organization":
                result = await self._connector.get_organization(params["org_id"])
                return StepResult(True, data=result)
            
            elif operation == "search_companies":
                results = await self._connector.search_companies(
                    keywords=params["keywords"],
                    limit=int(params.get("limit", 10)),
                )
                return StepResult(True, data={"count": len(results), "companies": results})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  REDDIT PRIMITIVE
# ============================================================



class RedditPrimitive(Primitive):
    """Reddit — posts, comments, subreddits, and search.
    
    Uses the Reddit OAuth API via RedditConnector.
    """
    
    def __init__(self, connector: Any = None):
        self._connector = connector
    
    @property
    def name(self) -> str:
        return "REDDIT"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "me": "Get the current Reddit user's profile and karma",
            "get_subreddit": "Get subreddit info (subscribers, description, etc.)",
            "get_posts": "Get posts from a subreddit (hot, new, top, rising)",
            "get_post": "Get a single post with top comments",
            "search": "Search for posts across Reddit or within a subreddit",
            "submit_post": "Submit a new text or link post to a subreddit",
            "add_comment": "Add a comment to a post or reply to a comment",
            "get_user_posts": "Get a user's submitted posts",
            "get_saved": "Get the user's saved posts and comments",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "me": {},
            "get_subreddit": {
                "name": {"type": "str", "required": True, "description": "Subreddit name (without /r/)"},
            },
            "get_posts": {
                "subreddit": {"type": "str", "required": True, "description": "Subreddit name"},
                "sort": {"type": "str", "required": False, "description": "'hot', 'new', 'top', 'rising', 'controversial'"},
                "time_filter": {"type": "str", "required": False, "description": "For top/controversial: 'hour','day','week','month','year','all'"},
                "limit": {"type": "int", "required": False, "description": "Max posts (default 25)"},
            },
            "get_post": {
                "subreddit": {"type": "str", "required": True, "description": "Subreddit name"},
                "post_id": {"type": "str", "required": True, "description": "Post ID"},
                "comment_limit": {"type": "int", "required": False, "description": "Max top-level comments (default 10)"},
            },
            "search": {
                "query": {"type": "str", "required": True, "description": "Search query"},
                "subreddit": {"type": "str", "required": False, "description": "Limit to subreddit"},
                "sort": {"type": "str", "required": False, "description": "'relevance', 'hot', 'top', 'new', 'comments'"},
                "time_filter": {"type": "str", "required": False, "description": "'hour','day','week','month','year','all'"},
                "limit": {"type": "int", "required": False, "description": "Max results (default 25)"},
            },
            "submit_post": {
                "subreddit": {"type": "str", "required": True, "description": "Target subreddit"},
                "title": {"type": "str", "required": True, "description": "Post title"},
                "text": {"type": "str", "required": False, "description": "Self-post body text"},
                "url": {"type": "str", "required": False, "description": "URL for link post"},
            },
            "add_comment": {
                "parent_fullname": {"type": "str", "required": True, "description": "Parent full name (e.g. t3_abc123)"},
                "text": {"type": "str", "required": True, "description": "Comment body (markdown)"},
            },
            "get_user_posts": {
                "username": {"type": "str", "required": False, "description": "Reddit username (default: current user)"},
                "limit": {"type": "int", "required": False, "description": "Max posts (default 25)"},
            },
            "get_saved": {
                "limit": {"type": "int", "required": False, "description": "Max items (default 25)"},
            },
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        if not self._connector:
            return StepResult(False, error="Reddit is not configured. Connect Reddit in Settings to use Reddit features.")
        try:
            if operation == "me":
                result = await self._connector.me()
                return StepResult(True, data=result)
            
            elif operation == "get_subreddit":
                result = await self._connector.get_subreddit(params["name"])
                return StepResult(True, data=result)
            
            elif operation == "get_posts":
                results = await self._connector.get_posts(
                    subreddit=params["subreddit"],
                    sort=params.get("sort", "hot"),
                    time_filter=params.get("time_filter", "day"),
                    limit=int(params.get("limit", 25)),
                )
                return StepResult(True, data={"count": len(results), "posts": results})
            
            elif operation == "get_post":
                result = await self._connector.get_post(
                    subreddit=params["subreddit"],
                    post_id=params["post_id"],
                    comment_limit=int(params.get("comment_limit", 10)),
                )
                return StepResult(True, data=result)
            
            elif operation == "search":
                results = await self._connector.search(
                    query=params["query"],
                    subreddit=params.get("subreddit"),
                    sort=params.get("sort", "relevance"),
                    time_filter=params.get("time_filter", "all"),
                    limit=int(params.get("limit", 25)),
                )
                return StepResult(True, data={"count": len(results), "posts": results})
            
            elif operation == "submit_post":
                result = await self._connector.submit_post(
                    subreddit=params["subreddit"],
                    title=params["title"],
                    text=params.get("text"),
                    url=params.get("url"),
                )
                return StepResult(True, data=result)
            
            elif operation == "add_comment":
                result = await self._connector.add_comment(params["parent_fullname"], params["text"])
                return StepResult(True, data=result)
            
            elif operation == "get_user_posts":
                results = await self._connector.get_user_posts(
                    username=params.get("username"),
                    limit=int(params.get("limit", 25)),
                )
                return StepResult(True, data={"count": len(results), "posts": results})
            
            elif operation == "get_saved":
                results = await self._connector.get_saved(
                    limit=int(params.get("limit", 25)),
                )
                return StepResult(True, data={"count": len(results), "items": results})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  TELEGRAM PRIMITIVE
# ============================================================



class HubSpotPrimitive(Primitive):
    """HubSpot CRM — contacts, companies, deals, tickets, notes, pipelines.
    
    Uses HubSpot CRM API v3 via HubSpotConnector.
    """

    def __init__(self, connector=None):
        self._c = connector
        self._connector = connector

    @property
    def name(self) -> str:
        return "HUBSPOT"

    def get_operations(self) -> Dict[str, str]:
        return {
            "list_contacts": "List HubSpot contacts",
            "get_contact": "Get a HubSpot contact by ID",
            "create_contact": "Create a new HubSpot contact",
            "update_contact": "Update a HubSpot contact",
            "delete_contact": "Delete a HubSpot contact",
            "search_contacts": "Search HubSpot contacts",
            "list_companies": "List HubSpot companies",
            "get_company": "Get a HubSpot company by ID",
            "create_company": "Create a new HubSpot company",
            "update_company": "Update a HubSpot company",
            "delete_company": "Delete a HubSpot company",
            "search_companies": "Search HubSpot companies",
            "list_deals": "List HubSpot deals",
            "get_deal": "Get a HubSpot deal by ID",
            "create_deal": "Create a new HubSpot deal",
            "update_deal": "Update a HubSpot deal",
            "delete_deal": "Delete a HubSpot deal",
            "search_deals": "Search HubSpot deals",
            "list_tickets": "List HubSpot tickets",
            "get_ticket": "Get a HubSpot ticket by ID",
            "create_ticket": "Create a new HubSpot ticket",
            "update_ticket": "Update a HubSpot ticket",
            "delete_ticket": "Delete a HubSpot ticket",
            "create_note": "Create a note on a HubSpot record",
            "get_note": "Get a HubSpot note by ID",
            "get_associations": "Get associations between HubSpot objects",
            "create_association": "Create an association between HubSpot objects",
            "list_pipelines": "List HubSpot pipelines",
            "get_pipeline_stages": "Get stages of a HubSpot pipeline",
            "list_owners": "List HubSpot owners",
        }

    async def execute(self, operation: str, params: dict) -> StepResult:
        if not self._c:
            return StepResult(False, error="HubSpot is not configured. Connect HubSpot in Settings to use HubSpot CRM features.")
        op = operation.lower().strip()
        try:
            if op == "list_contacts":
                data = await self._c.list_contacts(
                    limit=params.get("limit", 20),
                    after=params.get("after"),
                    properties=params.get("properties"),
                )
                return StepResult(True, data=data)

            elif op == "get_contact":
                data = await self._c.get_contact(
                    str(params["contact_id"]),
                    properties=params.get("properties"),
                )
                return StepResult(True, data=data)

            elif op == "create_contact":
                data = await self._c.create_contact(params.get("properties", {}))
                return StepResult(True, data=data)

            elif op == "update_contact":
                data = await self._c.update_contact(
                    str(params["contact_id"]),
                    params.get("properties", {}),
                )
                return StepResult(True, data=data)

            elif op == "delete_contact":
                await self._c.delete_contact(str(params["contact_id"]))
                return StepResult(True, data={"deleted": True})

            elif op == "search_contacts":
                data = await self._c.search_contacts(
                    params["query"],
                    limit=params.get("limit", 10),
                    properties=params.get("properties"),
                )
                return StepResult(True, data=data)

            elif op == "list_companies":
                data = await self._c.list_companies(
                    limit=params.get("limit", 20),
                    after=params.get("after"),
                    properties=params.get("properties"),
                )
                return StepResult(True, data=data)

            elif op == "get_company":
                data = await self._c.get_company(
                    str(params["company_id"]),
                    properties=params.get("properties"),
                )
                return StepResult(True, data=data)

            elif op == "create_company":
                data = await self._c.create_company(params.get("properties", {}))
                return StepResult(True, data=data)

            elif op == "update_company":
                data = await self._c.update_company(
                    str(params["company_id"]),
                    params.get("properties", {}),
                )
                return StepResult(True, data=data)

            elif op == "delete_company":
                await self._c.delete_company(str(params["company_id"]))
                return StepResult(True, data={"deleted": True})

            elif op == "search_companies":
                data = await self._c.search_companies(
                    params["query"],
                    limit=params.get("limit", 10),
                    properties=params.get("properties"),
                )
                return StepResult(True, data=data)

            elif op == "list_deals":
                data = await self._c.list_deals(
                    limit=params.get("limit", 20),
                    after=params.get("after"),
                    properties=params.get("properties"),
                )
                return StepResult(True, data=data)

            elif op == "get_deal":
                data = await self._c.get_deal(
                    str(params["deal_id"]),
                    properties=params.get("properties"),
                )
                return StepResult(True, data=data)

            elif op == "create_deal":
                data = await self._c.create_deal(params.get("properties", {}))
                return StepResult(True, data=data)

            elif op == "update_deal":
                data = await self._c.update_deal(
                    str(params["deal_id"]),
                    params.get("properties", {}),
                )
                return StepResult(True, data=data)

            elif op == "delete_deal":
                await self._c.delete_deal(str(params["deal_id"]))
                return StepResult(True, data={"deleted": True})

            elif op == "search_deals":
                data = await self._c.search_deals(
                    params["query"],
                    limit=params.get("limit", 10),
                    properties=params.get("properties"),
                )
                return StepResult(True, data=data)

            elif op == "list_tickets":
                data = await self._c.list_tickets(
                    limit=params.get("limit", 20),
                    after=params.get("after"),
                    properties=params.get("properties"),
                )
                return StepResult(True, data=data)

            elif op == "get_ticket":
                data = await self._c.get_ticket(
                    str(params["ticket_id"]),
                    properties=params.get("properties"),
                )
                return StepResult(True, data=data)

            elif op == "create_ticket":
                data = await self._c.create_ticket(params.get("properties", {}))
                return StepResult(True, data=data)

            elif op == "update_ticket":
                data = await self._c.update_ticket(
                    str(params["ticket_id"]),
                    params.get("properties", {}),
                )
                return StepResult(True, data=data)

            elif op == "delete_ticket":
                await self._c.delete_ticket(str(params["ticket_id"]))
                return StepResult(True, data={"deleted": True})

            elif op == "create_note":
                data = await self._c.create_note(
                    params["body"],
                    contact_id=params.get("contact_id"),
                    company_id=params.get("company_id"),
                    deal_id=params.get("deal_id"),
                )
                return StepResult(True, data=data)

            elif op == "get_note":
                data = await self._c.get_note(str(params["note_id"]))
                return StepResult(True, data=data)

            elif op == "get_associations":
                data = await self._c.get_associations(
                    params["object_type"],
                    str(params["object_id"]),
                    params["to_object_type"],
                )
                return StepResult(True, data=data)

            elif op == "create_association":
                data = await self._c.create_association(
                    params["from_type"],
                    str(params["from_id"]),
                    params["to_type"],
                    str(params["to_id"]),
                    int(params["association_type_id"]),
                )
                return StepResult(True, data=data)

            elif op == "list_pipelines":
                data = await self._c.list_pipelines(
                    object_type=params.get("object_type", "deals"),
                )
                return StepResult(True, data=data)

            elif op == "get_pipeline_stages":
                data = await self._c.get_pipeline_stages(
                    object_type=params.get("object_type", "deals"),
                    pipeline_id=params.get("pipeline_id", "default"),
                )
                return StepResult(True, data=data)

            elif op == "list_owners":
                data = await self._c.list_owners(
                    limit=params.get("limit", 100),
                    after=params.get("after"),
                )
                return StepResult(True, data=data)

            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))




class StripePrimitive(Primitive):
    """Stripe — customers, charges, invoices, subscriptions, products, payments.
    
    Uses Stripe REST API via StripeConnector.
    """

    def __init__(self, connector=None):
        self._c = connector
        self._connector = connector

    @property
    def name(self) -> str:
        return "STRIPE"

    def get_operations(self) -> Dict[str, str]:
        return {
            "list_customers": "List Stripe customers",
            "get_customer": "Get a Stripe customer by ID",
            "create_customer": "Create a new Stripe customer",
            "update_customer": "Update a Stripe customer",
            "delete_customer": "Delete a Stripe customer",
            "list_products": "List Stripe products",
            "get_product": "Get a Stripe product by ID",
            "create_product": "Create a new Stripe product",
            "list_prices": "List prices for a product",
            "create_price": "Create a price for a product",
            "list_invoices": "List Stripe invoices",
            "get_invoice": "Get a Stripe invoice by ID",
            "create_invoice": "Create a new invoice for a customer",
            "finalize_invoice": "Finalize a draft invoice",
            "void_invoice": "Void an invoice",
            "list_subscriptions": "List subscriptions",
            "get_subscription": "Get a subscription by ID",
            "cancel_subscription": "Cancel a subscription",
            "list_payment_intents": "List payment intents",
            "get_payment_intent": "Get a payment intent by ID",
            "list_charges": "List charges",
            "get_charge": "Get a charge by ID",
            "get_balance": "Get Stripe account balance",
        }

    async def execute(self, operation: str, params: dict) -> StepResult:
        if not self._c:
            return StepResult(False, error="Stripe is not configured. Connect Stripe in Settings to use Stripe features.")
        op = operation.lower().strip()
        try:
            if op == "list_customers":
                data = await self._c.list_customers(
                    limit=params.get("limit", 20),
                    starting_after=params.get("starting_after"),
                    email=params.get("email"),
                )
                return StepResult(True, data=data)

            elif op == "get_customer":
                data = await self._c.get_customer(str(params["customer_id"]))
                return StepResult(True, data=data)

            elif op == "create_customer":
                data = await self._c.create_customer(
                    email=params.get("email"),
                    name=params.get("name"),
                    description=params.get("description"),
                    metadata=params.get("metadata"),
                )
                return StepResult(True, data=data)

            elif op == "update_customer":
                cid = str(params["customer_id"])
                data = await self._c.update_customer(
                    cid,
                    name=params.get("name"),
                    email=params.get("email"),
                    description=params.get("description"),
                    metadata=params.get("metadata"),
                )
                return StepResult(True, data=data)

            elif op == "delete_customer":
                data = await self._c.delete_customer(str(params["customer_id"]))
                return StepResult(True, data=data)

            elif op == "list_products":
                data = await self._c.list_products(
                    limit=params.get("limit", 20),
                    active=params.get("active"),
                )
                return StepResult(True, data=data)

            elif op == "get_product":
                data = await self._c.get_product(str(params["product_id"]))
                return StepResult(True, data=data)

            elif op == "create_product":
                data = await self._c.create_product(
                    name=params["name"],
                    description=params.get("description"),
                    metadata=params.get("metadata"),
                )
                return StepResult(True, data=data)

            elif op == "list_prices":
                data = await self._c.list_prices(
                    product_id=params.get("product_id"),
                    limit=params.get("limit", 20),
                )
                return StepResult(True, data=data)

            elif op == "create_price":
                data = await self._c.create_price(
                    product_id=str(params["product_id"]),
                    unit_amount=int(params["unit_amount"]),
                    currency=params.get("currency", "usd"),
                    recurring_interval=params.get("recurring_interval"),
                )
                return StepResult(True, data=data)

            elif op == "list_invoices":
                data = await self._c.list_invoices(
                    customer_id=params.get("customer_id"),
                    limit=params.get("limit", 20),
                    status=params.get("status"),
                )
                return StepResult(True, data=data)

            elif op == "get_invoice":
                data = await self._c.get_invoice(str(params["invoice_id"]))
                return StepResult(True, data=data)

            elif op == "create_invoice":
                data = await self._c.create_invoice(
                    customer_id=str(params["customer_id"]),
                    auto_advance=params.get("auto_advance", True),
                )
                return StepResult(True, data=data)

            elif op == "finalize_invoice":
                data = await self._c.finalize_invoice(str(params["invoice_id"]))
                return StepResult(True, data=data)

            elif op == "void_invoice":
                data = await self._c.void_invoice(str(params["invoice_id"]))
                return StepResult(True, data=data)

            elif op == "list_subscriptions":
                data = await self._c.list_subscriptions(
                    customer_id=params.get("customer_id"),
                    limit=params.get("limit", 20),
                    status=params.get("status"),
                )
                return StepResult(True, data=data)

            elif op == "get_subscription":
                data = await self._c.get_subscription(str(params["subscription_id"]))
                return StepResult(True, data=data)

            elif op == "cancel_subscription":
                data = await self._c.cancel_subscription(
                    str(params["subscription_id"]),
                    at_period_end=params.get("at_period_end", True),
                )
                return StepResult(True, data=data)

            elif op == "list_payment_intents":
                data = await self._c.list_payment_intents(
                    customer_id=params.get("customer_id"),
                    limit=params.get("limit", 20),
                )
                return StepResult(True, data=data)

            elif op == "get_payment_intent":
                data = await self._c.get_payment_intent(str(params["payment_intent_id"]))
                return StepResult(True, data=data)

            elif op == "list_charges":
                data = await self._c.list_charges(
                    customer_id=params.get("customer_id"),
                    limit=params.get("limit", 20),
                )
                return StepResult(True, data=data)

            elif op == "get_charge":
                data = await self._c.get_charge(str(params["charge_id"]))
                return StepResult(True, data=data)

            elif op == "get_balance":
                data = await self._c.get_balance()
                return StepResult(True, data=data)

            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  NOTIFY PRIMITIVE
# ============================================================



class DevToolsPrimitive(Primitive):
    """Developer tools — GitHub, Jira, and other dev platforms.
    
    Provider-based: plug in GitHub, Jira, or any dev platform connector.
    """
    
    def __init__(self, providers: Optional[Dict[str, Any]] = None):
        self._providers = providers or {}
    
    @property
    def name(self) -> str:
        return "DEVTOOLS"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "list_issues": "List issues or tickets from a project",
            "get_issue": "Get details of a specific issue or ticket",
            "create_issue": "Create a new issue or ticket",
            "update_issue": "Update an existing issue or ticket",
            "comment": "Add a comment to an issue or PR",
            "list_prs": "List pull requests or merge requests",
            "create_pr": "Create a pull request",
            "list_repos": "List repositories or projects",
            "search": "Search issues, PRs, or repositories",
            "list_notifications": "List GitHub notifications",
            "review_requests": "List PRs awaiting your review",
            "list_commits": "List recent commits in a repository",
            "list_branches": "List branches in a repository",
            "list_workflow_runs": "List CI/CD workflow runs (GitHub Actions)",
            "activity_summary": "Get a summary of your dev activity",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "list_issues": {
                "repo": {"type": "str", "required": False, "description": "Repository or project key (e.g. 'owner/repo' or 'PROJ')"},
                "state": {"type": "str", "required": False, "description": "Filter: open, closed, all (default open)"},
                "limit": {"type": "int", "required": False, "description": "Max results (default 20)"},
                "provider": {"type": "str", "required": False, "description": "Provider: github, jira (default: auto)"},
            },
            "get_issue": {
                "repo": {"type": "str", "required": False, "description": "Repository or project key"},
                "issue_id": {"type": "str", "required": True, "description": "Issue number or key (e.g. '42' or 'PROJ-123')"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "create_issue": {
                "repo": {"type": "str", "required": False, "description": "Repository or project key"},
                "title": {"type": "str", "required": True, "description": "Issue title"},
                "body": {"type": "str", "required": False, "description": "Issue description/body"},
                "labels": {"type": "list", "required": False, "description": "Labels/tags"},
                "assignee": {"type": "str", "required": False, "description": "Assignee username"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "update_issue": {
                "repo": {"type": "str", "required": False, "description": "Repository or project key"},
                "issue_id": {"type": "str", "required": True, "description": "Issue number or key"},
                "title": {"type": "str", "required": False, "description": "New title"},
                "body": {"type": "str", "required": False, "description": "New body"},
                "state": {"type": "str", "required": False, "description": "New state: open or closed"},
                "labels": {"type": "list", "required": False, "description": "Updated labels"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "comment": {
                "repo": {"type": "str", "required": False, "description": "Repository or project key"},
                "issue_id": {"type": "str", "required": True, "description": "Issue/PR number or key"},
                "body": {"type": "str", "required": True, "description": "Comment text"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "list_prs": {
                "repo": {"type": "str", "required": False, "description": "Repository (e.g. 'owner/repo')"},
                "state": {"type": "str", "required": False, "description": "Filter: open, closed, all (default open)"},
                "limit": {"type": "int", "required": False, "description": "Max results"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "create_pr": {
                "repo": {"type": "str", "required": False, "description": "Repository (e.g. 'owner/repo')"},
                "title": {"type": "str", "required": True, "description": "PR title"},
                "body": {"type": "str", "required": False, "description": "PR description"},
                "head": {"type": "str", "required": True, "description": "Source branch"},
                "base": {"type": "str", "required": False, "description": "Target branch (default: main)"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "list_repos": {
                "limit": {"type": "int", "required": False, "description": "Max results"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "search": {
                "query": {"type": "str", "required": True, "description": "Search query"},
                "type": {"type": "str", "required": False, "description": "Search type: issues, repos (default issues)"},
                "limit": {"type": "int", "required": False, "description": "Max results"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "list_notifications": {
                "all": {"type": "bool", "required": False, "description": "Include read notifications"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "review_requests": {
                "limit": {"type": "int", "required": False, "description": "Max results"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "list_commits": {
                "repo": {"type": "str", "required": True, "description": "Repository (e.g. 'owner/repo')"},
                "branch": {"type": "str", "required": False, "description": "Branch or SHA"},
                "limit": {"type": "int", "required": False, "description": "Max results"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "list_branches": {
                "repo": {"type": "str", "required": True, "description": "Repository (e.g. 'owner/repo')"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "list_workflow_runs": {
                "repo": {"type": "str", "required": True, "description": "Repository (e.g. 'owner/repo')"},
                "status": {"type": "str", "required": False, "description": "Filter: completed, in_progress, queued"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "activity_summary": {
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
        }
    
    def _get_provider(self, name: Optional[str]) -> Optional[Any]:
        if name and name in self._providers:
            return self._providers[name]
        if self._providers:
            return next(iter(self._providers.values()))
        return None
    
    @staticmethod
    def _split_repo(repo_str: str):
        """Split 'owner/repo' into (owner, repo). Returns ('', '') if invalid."""
        if "/" in repo_str:
            parts = repo_str.split("/", 1)
            return parts[0], parts[1]
        return "", repo_str
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            provider_name = params.get("provider")
            provider = self._get_provider(provider_name)
            
            if not provider:
                return StepResult(False, error="No devtools provider configured. Connect GitHub, Jira, etc.")
            
            repo_str = params.get("repo", "")
            owner, repo = self._split_repo(repo_str) if repo_str else ("", "")
            
            if operation == "list_issues":
                if hasattr(provider, "list_issues"):
                    result = await provider.list_issues(
                        owner, repo,
                        state=params.get("state", "open"),
                        per_page=params.get("limit", 20),
                    )
                    return StepResult(True, data=result)
                return StepResult(False, error="Provider does not support list_issues")
            
            elif operation == "get_issue":
                issue_id = params.get("issue_id", "")
                if hasattr(provider, "get_issue"):
                    result = await provider.get_issue(owner, repo, int(issue_id))
                    return StepResult(True, data=result)
                return StepResult(False, error="Provider does not support get_issue")
            
            elif operation == "create_issue":
                if hasattr(provider, "create_issue"):
                    result = await provider.create_issue(
                        owner, repo,
                        title=params.get("title", ""),
                        body=params.get("body", ""),
                        labels=params.get("labels"),
                        assignees=[params["assignee"]] if params.get("assignee") else None,
                    )
                    return StepResult(True, data=result)
                return StepResult(False, error="Provider does not support create_issue")
            
            elif operation == "update_issue":
                if hasattr(provider, "update_issue"):
                    result = await provider.update_issue(
                        owner, repo,
                        number=int(params.get("issue_id", 0)),
                        title=params.get("title"),
                        body=params.get("body"),
                        state=params.get("state"),
                        labels=params.get("labels"),
                    )
                    return StepResult(True, data=result)
                return StepResult(False, error="Provider does not support update_issue")
            
            elif operation == "comment":
                if hasattr(provider, "add_comment"):
                    result = await provider.add_comment(
                        owner, repo,
                        issue_number=int(params.get("issue_id", 0)),
                        body=params.get("body", ""),
                    )
                    return StepResult(True, data=result)
                return StepResult(False, error="Provider does not support add_comment")
            
            elif operation == "list_prs":
                if hasattr(provider, "list_pull_requests"):
                    result = await provider.list_pull_requests(
                        owner, repo,
                        state=params.get("state", "open"),
                    )
                    return StepResult(True, data=result)
                return StepResult(False, error="Provider does not support list_prs")
            
            elif operation == "create_pr":
                if hasattr(provider, "create_pull_request"):
                    result = await provider.create_pull_request(
                        owner, repo,
                        title=params.get("title", ""),
                        head=params.get("head", ""),
                        base=params.get("base", "main"),
                        body=params.get("body", ""),
                    )
                    return StepResult(True, data=result)
                return StepResult(False, error="Provider does not support create_pr")
            
            elif operation == "list_repos":
                if hasattr(provider, "list_repos"):
                    result = await provider.list_repos(per_page=params.get("limit", 20))
                    return StepResult(True, data=result)
                return StepResult(False, error="Provider does not support list_repos")
            
            elif operation == "search":
                search_type = params.get("type", "issues")
                query = params.get("query", "")
                limit = params.get("limit", 20)
                if search_type == "repos" and hasattr(provider, "search_repos"):
                    result = await provider.search_repos(query, per_page=limit)
                    return StepResult(True, data=result)
                elif hasattr(provider, "search_issues"):
                    result = await provider.search_issues(query, per_page=limit)
                    return StepResult(True, data=result)
                return StepResult(False, error="Provider does not support search")
            
            elif operation == "list_notifications":
                if hasattr(provider, "list_notifications"):
                    result = await provider.list_notifications(
                        all=params.get("all", False),
                    )
                    return StepResult(True, data=result)
                return StepResult(False, error="Provider does not support list_notifications")
            
            elif operation == "review_requests":
                if hasattr(provider, "get_review_requests"):
                    result = await provider.get_review_requests(
                        per_page=params.get("limit", 20),
                    )
                    return StepResult(True, data=result)
                return StepResult(False, error="Provider does not support review_requests")
            
            elif operation == "list_commits":
                if hasattr(provider, "list_commits"):
                    result = await provider.list_commits(
                        owner, repo,
                        sha=params.get("branch"),
                        per_page=params.get("limit", 20),
                    )
                    return StepResult(True, data=result)
                return StepResult(False, error="Provider does not support list_commits")
            
            elif operation == "list_branches":
                if hasattr(provider, "list_branches"):
                    result = await provider.list_branches(owner, repo)
                    return StepResult(True, data=result)
                return StepResult(False, error="Provider does not support list_branches")
            
            elif operation == "list_workflow_runs":
                if hasattr(provider, "list_workflow_runs"):
                    result = await provider.list_workflow_runs(
                        owner, repo,
                        status=params.get("status"),
                        per_page=params.get("limit", 10),
                    )
                    return StepResult(True, data=result)
                return StepResult(False, error="Provider does not support list_workflow_runs")
            
            elif operation == "activity_summary":
                if hasattr(provider, "get_activity_summary"):
                    result = await provider.get_activity_summary()
                    return StepResult(True, data=result)
                return StepResult(False, error="Provider does not support activity_summary")
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  CLOUD STORAGE PRIMITIVE
# ============================================================



class CloudStoragePrimitive(Primitive):
    """Cloud storage operations — Google Drive, OneDrive, Dropbox.
    
    Provider-based: plug in any cloud storage connector.
    """
    
    def __init__(self, providers: Optional[Dict[str, Any]] = None):
        self._providers = providers or {}
    
    @property
    def name(self) -> str:
        return "CLOUD_STORAGE"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "list": "List files and folders in cloud storage",
            "search": "Search for files by name or content",
            "download": "Download a file from cloud storage",
            "upload": "Upload a file to cloud storage",
            "create_folder": "Create a folder in cloud storage",
            "delete": "Delete a file or folder from cloud storage",
            "share": "Share a file or folder with others",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "list": {
                "path": {"type": "str", "required": False, "description": "Folder path or ID (default: root)"},
                "limit": {"type": "int", "required": False, "description": "Max results"},
                "provider": {"type": "str", "required": False, "description": "Provider: google_drive, onedrive, dropbox"},
            },
            "search": {
                "query": {"type": "str", "required": True, "description": "Search query (file name or content)"},
                "limit": {"type": "int", "required": False, "description": "Max results"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "download": {
                "file_id": {"type": "str", "required": True, "description": "File ID or path in cloud storage"},
                "local_path": {"type": "str", "required": True, "description": "Local path to save the file"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "upload": {
                "local_path": {"type": "str", "required": True, "description": "Local file path to upload"},
                "remote_path": {"type": "str", "required": False, "description": "Destination path in cloud storage"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "create_folder": {
                "name": {"type": "str", "required": True, "description": "Folder name"},
                "parent": {"type": "str", "required": False, "description": "Parent folder ID or path"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "delete": {
                "file_id": {"type": "str", "required": True, "description": "File or folder ID to delete"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "share": {
                "file_id": {"type": "str", "required": True, "description": "File or folder ID to share"},
                "email": {"type": "str", "required": True, "description": "Email of person to share with"},
                "role": {"type": "str", "required": False, "description": "Permission: viewer, editor, commenter (default viewer)"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
        }
    
    def _get_provider(self, name: Optional[str]) -> Optional[Any]:
        if name and name in self._providers:
            return self._providers[name]
        if self._providers:
            return next(iter(self._providers.values()))
        return None
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            provider_name = params.get("provider")
            provider = self._get_provider(provider_name)
            
            if not provider:
                return StepResult(False, error="No cloud storage provider configured. Connect Google Drive, OneDrive, or Dropbox.")
            
            if operation == "list":
                if hasattr(provider, "list_files"):
                    result = await provider.list_files(
                        folder_id=params.get("path"),
                        max_results=params.get("limit", 50),
                    )
                    return StepResult(True, data=result)
                return StepResult(False, error="Provider does not support list_files")
            
            elif operation == "search":
                if hasattr(provider, "search_files"):
                    result = await provider.search_files(
                        query=params.get("query", ""),
                        max_results=params.get("limit", 20),
                    )
                    return StepResult(True, data=result)
                if hasattr(provider, "list_files"):
                    query = (params.get("query", "") or "").lower().strip()
                    items = await provider.list_files(max_results=max(100, params.get("limit", 20)))
                    if not query:
                        return StepResult(True, data=items[: params.get("limit", 20)])
                    filtered = []
                    for item in items:
                        name = ""
                        if isinstance(item, dict):
                            name = str(item.get("name", ""))
                        else:
                            name = str(getattr(item, "name", ""))
                        if query in name.lower():
                            filtered.append(item)
                    return StepResult(True, data=filtered[: params.get("limit", 20)])
                return StepResult(False, error="Provider does not support search_files")
            
            elif operation == "download":
                if hasattr(provider, "download_file"):
                    result = await provider.download_file(
                        file_id=params.get("file_id", ""),
                        local_path=params.get("local_path", ""),
                    )
                    return StepResult(True, data=result)
                return StepResult(False, error="Provider does not support download_file")
            
            elif operation == "upload":
                if hasattr(provider, "upload_file"):
                    result = await provider.upload_file(
                        local_path=params.get("local_path", ""),
                        remote_path=params.get("remote_path"),
                    )
                    return StepResult(True, data=result)
                return StepResult(False, error="Provider does not support upload_file")
            
            elif operation == "create_folder":
                if hasattr(provider, "create_folder"):
                    result = await provider.create_folder(
                        name=params.get("name", ""),
                        parent_id=params.get("parent"),
                    )
                    return StepResult(True, data=result)
                return StepResult(False, error="Provider does not support create_folder")
            
            elif operation == "delete":
                if hasattr(provider, "delete_file"):
                    result = await provider.delete_file(file_id=params.get("file_id", ""))
                    return StepResult(True, data=result)
                return StepResult(False, error="Provider does not support delete_file")
            
            elif operation == "share":
                if hasattr(provider, "share_file"):
                    result = await provider.share_file(
                        file_id=params.get("file_id", ""),
                        email=params.get("email", ""),
                        role=params.get("role", "viewer"),
                    )
                    return StepResult(True, data=result)
                return StepResult(False, error="Provider does not support share_file")
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  CLIPBOARD PRIMITIVE
# ============================================================


