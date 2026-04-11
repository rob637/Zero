"""Telic Engine — Communication Primitives"""

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
from .base import get_data_index

logger = logging.getLogger(__name__)


class EmailPrimitive(Primitive):
    """Email operations via Gmail, Outlook, or other providers."""
    
    def __init__(self, providers: Optional[Dict[str, Any]] = None, **kwargs):
        # Support both old single-connector and new multi-provider patterns
        self._providers = providers or {}
        # Legacy compat: if old-style args passed, wrap in provider
        if not self._providers and kwargs.get('connector'):
            connector = kwargs['connector']
            provider_name = 'gmail' if 'Gmail' in type(connector).__name__ else 'outlook'
            self._providers[provider_name] = connector
        self._send = kwargs.get('send_func')
        self._list = kwargs.get('list_func')
        self._read = kwargs.get('read_func')
        self._connector = kwargs.get('connector') or (next(iter(self._providers.values())) if self._providers else None)
    
    @property
    def name(self) -> str:
        return "EMAIL"
    
    def get_operations(self) -> Dict[str, str]:
        ops = {
            "send": "Send an email",
            "draft": "Create a draft email",
            "search": "Search emails",
            "list": "List recent emails",
            "read": "Read a specific email by ID to get its full body content",
        }
        connector = self._resolve_connector()
        if connector:
            ops.update({
                "reply": "Reply to an email",
                "forward": "Forward an email to another recipient",
                "delete": "Permanently delete an email",
                "trash": "Move an email to trash",
                "archive": "Archive an email (remove from inbox)",
                "mark_read": "Mark an email as read",
                "mark_unread": "Mark an email as unread",
                "add_label": "Add a label/folder to an email",
                "remove_label": "Remove a label/folder from an email",
                "get_labels": "List all available labels/folders",
                "get_thread": "Get all messages in an email thread",
            })
        return ops

    def _is_provider_connected(self, provider: Any) -> bool:
        if not provider:
            return False
        if hasattr(provider, 'connected'):
            val = getattr(provider, 'connected')
            return val() if callable(val) else bool(val)
        if hasattr(provider, 'is_connected'):
            val = getattr(provider, 'is_connected')
            return val() if callable(val) else bool(val)
        return True

    def _resolve_connector(self) -> Optional[Any]:
        for provider in self._providers.values():
            if self._is_provider_connected(provider):
                return provider
        if self._connector and self._is_provider_connected(self._connector):
            return self._connector
        return None
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        schema = {
            "send": {
                "to": {"type": "str", "required": True, "description": "Recipient email address"},
                "subject": {"type": "str", "required": True, "description": "Email subject line"},
                "body": {"type": "str", "required": True, "description": "Email body text"},
                "attachments": {"type": "list", "required": False, "description": "List of file paths to attach"},
            },
            "draft": {
                "to": {"type": "str", "required": True, "description": "Recipient email address"},
                "subject": {"type": "str", "required": True, "description": "Email subject line"},
                "body": {"type": "str", "required": True, "description": "Email body text"},
            },
            "search": {
                "query": {"type": "str", "required": True, "description": "Search query using Gmail syntax (e.g. 'from:bob subject:report', 'label:travel', 'in:anywhere Africa trip'). Use label: to search folders."},
                "limit": {"type": "int", "required": False, "description": "Max results (default 10)"},
            },
            "list": {
                "query": {"type": "str", "required": False, "description": "Filter query using Gmail syntax"},
                "limit": {"type": "int", "required": False, "description": "Max results (default 10)"},
            },
            "read": {
                "message_id": {"type": "str", "required": True, "description": "The email message ID (from search/list results)"},
            },
            "reply": {
                "message_id": {"type": "str", "required": True, "description": "ID of the email to reply to"},
                "body": {"type": "str", "required": True, "description": "Reply body text"},
            },
            "forward": {
                "message_id": {"type": "str", "required": True, "description": "ID of the email to forward"},
                "to": {"type": "str", "required": True, "description": "Recipient email address"},
                "body": {"type": "str", "required": False, "description": "Additional message to include"},
            },
            "delete": {
                "message_id": {"type": "str", "required": True, "description": "ID of the email to delete permanently"},
            },
            "trash": {
                "message_id": {"type": "str", "required": True, "description": "ID of the email to move to trash"},
            },
            "archive": {
                "message_id": {"type": "str", "required": True, "description": "ID of the email to archive"},
            },
            "mark_read": {
                "message_id": {"type": "str", "required": True, "description": "ID of the email to mark as read"},
            },
            "mark_unread": {
                "message_id": {"type": "str", "required": True, "description": "ID of the email to mark as unread"},
            },
            "add_label": {
                "message_id": {"type": "str", "required": True, "description": "ID of the email"},
                "label_ids": {"type": "list", "required": True, "description": "Label IDs to add"},
            },
            "remove_label": {
                "message_id": {"type": "str", "required": True, "description": "ID of the email"},
                "label_ids": {"type": "list", "required": True, "description": "Label IDs to remove"},
            },
            "get_labels": {},
            "get_thread": {
                "thread_id": {"type": "str", "required": True, "description": "Thread ID to get all messages for"},
            },
        }
        return schema
    
    def get_available_operations(self) -> Dict[str, str]:
        """Only expose operations that have a live backend or a fresh local index."""
        ops = self.get_operations()
        connector = self._resolve_connector()

        if connector:
            return ops

        idx = get_data_index()
        if idx and not idx.is_stale("gmail"):
            return {
                "search": ops["search"],
                "list": ops["list"],
            }

        return {}
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            if operation == "send":
                connector = self._resolve_connector()
                send_func = self._send or (connector.send_email if connector and hasattr(connector, "send_email") else None)
                if not send_func:
                    return StepResult(False, error="Email sending not configured")
                
                result = await send_func(
                    to=params.get("to"),
                    subject=params.get("subject"),
                    body=params.get("body"),
                    attachments=params.get("attachments"),
                )
                return StepResult(True, data=result)
            
            elif operation == "draft":
                # For now, create draft means just prepare the email
                return StepResult(True, data={
                    "draft": True,
                    "to": params.get("to"),
                    "subject": params.get("subject"),
                    "body": params.get("body"),
                })
            
            elif operation in ["search", "list"]:
                # Try local index first
                idx = get_data_index()
                query_text = params.get("query", "")
                if idx and not idx.is_stale("gmail"):
                    try:
                        if query_text:
                            results = idx.search(query_text, kind="email", limit=params.get("limit", 10))
                        else:
                            results = idx.query(kind="email", limit=params.get("limit", 10))
                        if results:
                            print(f"[EMAIL] Index hit: {len(results)} emails")
                            return StepResult(True, data=[
                                {k: v for k, v in {
                                    "id": r.source_id, "subject": r.title,
                                    "snippet": r.body, "sender": r.participants[0] if r.participants else "",
                                    "to": r.participants[1:], "date": r.timestamp.isoformat() if r.timestamp else "",
                                    "status": r.status, "labels": r.labels,
                                }.items() if v}
                                for r in results
                            ])
                    except Exception as e:
                        print(f"[EMAIL] Index query failed, falling through to API: {e}")

                connector = self._resolve_connector()
                list_func = self._list or (connector.list_messages if connector and hasattr(connector, "list_messages") else None)
                if not list_func:
                    return StepResult(False, error="Email listing not configured")
                
                result = await list_func(
                    query=params.get("query", ""),
                    max_results=params.get("limit", 10),
                )
                return StepResult(True, data=result)
            
            elif operation == "read":
                connector = self._resolve_connector()
                read_func = self._read or (connector.get_message if connector and hasattr(connector, "get_message") else None)
                if not read_func:
                    return StepResult(False, error="Email reading not configured")
                
                message_id = params.get("message_id")
                if not message_id:
                    return StepResult(False, error="message_id is required")
                
                email = await read_func(message_id)
                if hasattr(email, 'to_dict'):
                    return StepResult(True, data=email.to_dict())
                return StepResult(True, data=email)
            
            elif operation == "reply":
                connector = self._resolve_connector()
                if not connector or not hasattr(connector, "reply"):
                    return StepResult(False, error="Reply not supported by this email provider")
                result = await connector.reply(
                    message_id=params["message_id"],
                    body=params["body"],
                    html=params.get("html", False),
                )
                return StepResult(True, data=result)
            
            elif operation == "forward":
                connector = self._resolve_connector()
                if not connector or not hasattr(connector, "forward"):
                    return StepResult(False, error="Forward not supported by this email provider")
                result = await connector.forward(
                    message_id=params["message_id"],
                    to=params["to"],
                    additional_body=params.get("body", ""),
                )
                return StepResult(True, data=result)
            
            elif operation == "delete":
                connector = self._resolve_connector()
                if not connector or not hasattr(connector, "delete_message"):
                    return StepResult(False, error="Delete not supported by this email provider")
                await connector.delete_message(params["message_id"])
                return StepResult(True, data={"deleted": True})
            
            elif operation == "trash":
                connector = self._resolve_connector()
                if not connector or not hasattr(connector, "trash_message"):
                    return StepResult(False, error="Trash not supported by this email provider")
                await connector.trash_message(params["message_id"])
                return StepResult(True, data={"trashed": True})
            
            elif operation == "archive":
                connector = self._resolve_connector()
                if not connector or not hasattr(connector, "archive_message"):
                    return StepResult(False, error="Archive not supported by this email provider")
                await connector.archive_message(params["message_id"])
                return StepResult(True, data={"archived": True})
            
            elif operation == "mark_read":
                connector = self._resolve_connector()
                if not connector or not hasattr(connector, "mark_read"):
                    return StepResult(False, error="Mark read not supported by this email provider")
                await connector.mark_read(params["message_id"])
                return StepResult(True, data={"marked_read": True})
            
            elif operation == "mark_unread":
                connector = self._resolve_connector()
                if not connector or not hasattr(connector, "mark_unread"):
                    return StepResult(False, error="Mark unread not supported by this email provider")
                await connector.mark_unread(params["message_id"])
                return StepResult(True, data={"marked_unread": True})
            
            elif operation == "add_label":
                connector = self._resolve_connector()
                if not connector or not hasattr(connector, "add_label"):
                    return StepResult(False, error="Labels not supported by this email provider")
                await connector.add_label(params["message_id"], params["label_ids"])
                return StepResult(True, data={"labels_added": True})
            
            elif operation == "remove_label":
                connector = self._resolve_connector()
                if not connector or not hasattr(connector, "remove_label"):
                    return StepResult(False, error="Labels not supported by this email provider")
                await connector.remove_label(params["message_id"], params["label_ids"])
                return StepResult(True, data={"labels_removed": True})
            
            elif operation == "get_labels":
                connector = self._resolve_connector()
                if not connector or not hasattr(connector, "get_labels"):
                    return StepResult(False, error="Labels not supported by this email provider")
                result = await connector.get_labels()
                return StepResult(True, data=result)
            
            elif operation == "get_thread":
                connector = self._resolve_connector()
                if not connector or not hasattr(connector, "get_thread"):
                    return StepResult(False, error="Threads not supported by this email provider")
                result = await connector.get_thread(params["thread_id"])
                return StepResult(True, data=result)
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
                
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  CONTACTS PRIMITIVE
# ============================================================



class ContactsPrimitive(Primitive):
    """Contact management.
    
    Local in-memory store by default. Wire in Google Contacts, Outlook, etc.
    via a providers dict.
    """
    
    def __init__(self, providers: Optional[Dict[str, Any]] = None):
        self._contacts: Dict[str, Dict] = {}
        self._providers = providers or {}
    
    @property
    def name(self) -> str:
        return "CONTACTS"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "search": "Find contacts by name or email",
            "add": "Add a contact",
            "list": "List all contacts",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "search": {
                "query": {"type": "str", "required": True, "description": "Name or email to search for"},
                "provider": {"type": "str", "required": False, "description": "Provider: google, microsoft (default: local)"},
            },
            "add": {
                "name": {"type": "str", "required": True, "description": "Contact name"},
                "email": {"type": "str", "required": False, "description": "Email address"},
                "phone": {"type": "str", "required": False, "description": "Phone number"},
                "provider": {"type": "str", "required": False, "description": "Provider: google, microsoft (default: local)"},
            },
            "list": {
                "limit": {"type": "int", "required": False, "description": "Max contacts to return"},
                "provider": {"type": "str", "required": False, "description": "Provider: google, microsoft (default: local)"},
            },
        }
    
    def _get_provider(self, name: Optional[str]) -> Optional[Any]:
        if name and name in self._providers:
            return self._providers[name]
        if self._providers:
            return next(iter(self._providers.values()))
        return None
    
    def add_contact(self, name: str, email: str, phone: Optional[str] = None):
        """Add a contact (can be called directly to seed data)."""
        self._contacts[name.lower()] = {"name": name, "email": email, "phone": phone}
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            provider_name = params.get("provider")
            provider = self._get_provider(provider_name)
            
            if operation == "search":
                query = params.get("query", "").lower()
                
                # Try local index first
                idx = get_data_index()
                if idx and not idx.is_stale("google_contacts"):
                    try:
                        results = idx.search(query, kind="contact", limit=10)
                        if results:
                            print(f"[CONTACTS] Index hit: {len(results)} contacts")
                            return StepResult(True, data=[
                                {k: v for k, v in {
                                    "name": r.title,
                                    "email": r.participants[0] if r.participants else "",
                                    "details": r.body,
                                }.items() if v}
                                for r in results
                            ])
                    except Exception as e:
                        print(f"[CONTACTS] Index query failed, falling through to API: {e}")
                
                if provider and hasattr(provider, "search"):
                    result = await provider.search(query=query)
                    if result:
                        first = result[0]
                        return StepResult(True, data={"name": getattr(first, "name", str(first)), "email": getattr(first, "email", ""), "phone": getattr(first, "phone", "")})
                    return StepResult(True, data=None)
                
                matches = [
                    c for c in self._contacts.values()
                    if query in c["name"].lower() or query in c.get("email", "").lower()
                ]
                if matches:
                    return StepResult(True, data=matches[0])
                return StepResult(True, data=None)
            
            elif operation == "add":
                name = params.get("name")
                email = params.get("email")
                phone = params.get("phone")
                
                if not name:
                    return StepResult(False, error="Name required")
                
                if provider and hasattr(provider, "create_contact"):
                    result = await provider.create_contact(name=name, email=email, phone=phone)
                    return StepResult(True, data={"name": name, "email": email})
                
                self._contacts[name.lower()] = {"name": name, "email": email, "phone": phone}
                return StepResult(True, data={"name": name, "email": email})
            
            elif operation == "list":
                limit = params.get("limit", 100)
                
                # Try local index first
                idx = get_data_index()
                if idx and not idx.is_stale("google_contacts"):
                    try:
                        results = idx.query(kind="contact", limit=limit)
                        if results:
                            print(f"[CONTACTS] Index hit: {len(results)} contacts")
                            return StepResult(True, data=[
                                {k: v for k, v in {
                                    "name": r.title,
                                    "email": r.participants[0] if r.participants else "",
                                    "details": r.body,
                                }.items() if v}
                                for r in results
                            ])
                    except Exception as e:
                        print(f"[CONTACTS] Index query failed, falling through to API: {e}")
                
                if provider and hasattr(provider, "list_contacts"):
                    result = await provider.list_contacts(max_results=limit)
                    return StepResult(True, data=[{"name": getattr(c, "name", str(c)), "email": getattr(c, "email", "")} for c in result])
                
                return StepResult(True, data=list(self._contacts.values())[:limit])
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
                
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  KNOWLEDGE PRIMITIVE (backed by SemanticMemory)
# ============================================================



class MessagePrimitive(Primitive):
    """Messaging across channels — Slack, Teams, Discord, SMS, WhatsApp.
    
    Provider-based: plug in any messaging backend via send_func/list_func.
    The primitive defines the universal interface; providers handle the protocol.
    """
    
    def __init__(
        self,
        send_func: Optional[Callable] = None,
        list_func: Optional[Callable] = None,
        react_func: Optional[Callable] = None,
        providers: Optional[Dict[str, Any]] = None,
    ):
        self._send = send_func
        self._list = list_func
        self._react = react_func
        self._providers = providers or {}
        self._local_messages: List[Dict] = []
    
    @property
    def name(self) -> str:
        return "MESSAGE"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "send": "Send a message to a channel, thread, or person",
            "list": "List recent messages from a channel or conversation",
            "search": "Search messages by keyword across channels",
            "react": "Add a reaction/emoji to a message",
            "reply": "Reply to a specific message in a thread",
            "channels": "List available channels or conversations",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "send": {
                "to": {"type": "str", "required": True, "description": "Channel name, user handle, or phone number"},
                "text": {"type": "str", "required": True, "description": "Message text"},
                "provider": {"type": "str", "required": False, "description": "Provider: slack, teams, discord, sms (default: auto-detect)"},
                "attachments": {"type": "list", "required": False, "description": "List of file paths or URLs to attach"},
            },
            "list": {
                "channel": {"type": "str", "required": True, "description": "Channel name or conversation ID"},
                "limit": {"type": "int", "required": False, "description": "Max messages to return (default 20)"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "search": {
                "query": {"type": "str", "required": True, "description": "Search term"},
                "channel": {"type": "str", "required": False, "description": "Limit search to a specific channel"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "react": {
                "message_id": {"type": "str", "required": True, "description": "Message ID to react to"},
                "emoji": {"type": "str", "required": True, "description": "Emoji name (e.g. thumbsup, heart, check)"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "reply": {
                "message_id": {"type": "str", "required": True, "description": "Message ID to reply to (thread parent)"},
                "text": {"type": "str", "required": True, "description": "Reply text"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "channels": {
                "provider": {"type": "str", "required": False, "description": "Provider name"},
                "limit": {"type": "int", "required": False, "description": "Max channels to return"},
            },
        }
    
    def _get_provider(self, name: Optional[str]) -> Optional[Any]:
        """Look up a messaging provider by name."""
        if name and name in self._providers:
            return self._providers[name]
        # Return first available provider if none specified
        if self._providers:
            return next(iter(self._providers.values()))
        return None
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            provider_name = params.get("provider")
            
            if operation == "send":
                to = params.get("to", "")
                text = params.get("text", "")
                
                if not to or not text:
                    return StepResult(False, error="Missing 'to' and/or 'text' parameter")
                
                if self._send:
                    result = await self._send(to=to, text=text, provider=provider_name, attachments=params.get("attachments"))
                    return StepResult(True, data=result)
                
                provider = self._get_provider(provider_name)
                if provider and hasattr(provider, "send"):
                    result = await provider.send(to=to, text=text, attachments=params.get("attachments"))
                    return StepResult(True, data=result)
                
                # Local fallback — store for testing/UI display
                msg = {
                    "id": f"msg_{len(self._local_messages)}_{int(datetime.now().timestamp())}",
                    "to": to,
                    "text": text,
                    "timestamp": datetime.now().isoformat(),
                    "status": "queued",
                }
                self._local_messages.append(msg)
                return StepResult(True, data=msg)
            
            elif operation == "list":
                channel = params.get("channel", "")
                limit = params.get("limit", 20)
                
                if self._list:
                    result = await self._list(channel=channel, limit=limit, provider=provider_name)
                    return StepResult(True, data=result)
                
                provider = self._get_provider(provider_name)
                if provider and hasattr(provider, "list_messages"):
                    result = await provider.list_messages(channel=channel, limit=limit)
                    return StepResult(True, data=result)
                
                # Local fallback
                msgs = [m for m in self._local_messages if m.get("to") == channel]
                return StepResult(True, data=msgs[-limit:])
            
            elif operation == "search":
                query = params.get("query", "").lower()
                channel = params.get("channel")
                
                provider = self._get_provider(provider_name)
                if provider and hasattr(provider, "search"):
                    result = await provider.search(query=query, channel=channel)
                    return StepResult(True, data=result)
                
                # Local fallback
                matches = [
                    m for m in self._local_messages
                    if query in m.get("text", "").lower()
                    and (not channel or m.get("to") == channel)
                ]
                return StepResult(True, data=matches)
            
            elif operation == "react":
                message_id = params.get("message_id", "")
                emoji = params.get("emoji", "")
                
                if not message_id or not emoji:
                    return StepResult(False, error="Missing 'message_id' and/or 'emoji' parameter")
                
                if self._react:
                    result = await self._react(message_id=message_id, emoji=emoji, provider=provider_name)
                    return StepResult(True, data=result)
                
                provider = self._get_provider(provider_name)
                if provider and hasattr(provider, "react"):
                    result = await provider.react(message_id=message_id, emoji=emoji)
                    return StepResult(True, data=result)
                
                return StepResult(True, data={"message_id": message_id, "emoji": emoji, "status": "queued"})
            
            elif operation == "reply":
                message_id = params.get("message_id", "")
                text = params.get("text", "")
                
                if not message_id or not text:
                    return StepResult(False, error="Missing 'message_id' and/or 'text' parameter")
                
                provider = self._get_provider(provider_name)
                if provider and hasattr(provider, "reply"):
                    result = await provider.reply(message_id=message_id, text=text)
                    return StepResult(True, data=result)
                
                msg = {
                    "id": f"msg_{len(self._local_messages)}_{int(datetime.now().timestamp())}",
                    "reply_to": message_id,
                    "text": text,
                    "timestamp": datetime.now().isoformat(),
                    "status": "queued",
                }
                self._local_messages.append(msg)
                return StepResult(True, data=msg)
            
            elif operation == "channels":
                provider = self._get_provider(provider_name)
                if provider and hasattr(provider, "list_channels"):
                    result = await provider.list_channels(limit=params.get("limit", 50))
                    return StepResult(True, data=result)
                
                return StepResult(True, data=[])
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  MEDIA PRIMITIVE
# ============================================================



class SmsPrimitive(Primitive):
    """SMS/text messaging operations."""
    
    def __init__(self, providers: Optional[Dict[str, Any]] = None):
        self._providers = providers or {}
        self._local_messages: List[Dict] = []
    
    @property
    def name(self) -> str:
        return "SMS"
    
    def get_operations(self) -> Dict[str, str]:
        return self.get_available_operations()
    
    def get_available_operations(self) -> Dict[str, str]:
        return {
            "send": "Send an SMS message",
            "read": "Read SMS messages",
            "search": "Search SMS history",
        }
    
    def get_param_schema(self) -> Dict[str, Any]:
        return {
            "send": {"to": {"type": "str", "description": "Phone number"}, "message": {"type": "str", "description": "Message text"}},
            "read": {"from": {"type": "str", "description": "Phone number (optional)"}, "limit": {"type": "int", "description": "Max messages", "default": 20}},
            "search": {"query": {"type": "str", "description": "Search query"}},
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            if operation == "send":
                to = params.get("to")
                message = params.get("message")
                for name, provider in self._providers.items():
                    if hasattr(provider, "send_sms"):
                        result = await provider.send_sms(to=to, message=message)
                        return StepResult(True, data={"sent": True, "provider": name, "result": result})
                # Local fallback
                msg = {"to": to, "message": message, "timestamp": datetime.now().isoformat()}
                self._local_messages.append(msg)
                return StepResult(True, data={"sent": True, "provider": "local", "message": msg})
            
            elif operation == "read":
                from_num = params.get("from")
                limit = params.get("limit", 20)
                for name, provider in self._providers.items():
                    if hasattr(provider, "read_sms"):
                        result = await provider.read_sms(from_number=from_num, limit=limit)
                        return StepResult(True, data={"messages": result, "provider": name})
                msgs = self._local_messages
                if from_num:
                    msgs = [m for m in msgs if m.get("to") == from_num or m.get("from") == from_num]
                return StepResult(True, data={"messages": msgs[-limit:], "provider": "local"})
            
            elif operation == "search":
                query = params.get("query", "").lower()
                for name, provider in self._providers.items():
                    if hasattr(provider, "search_sms"):
                        result = await provider.search_sms(query=query)
                        return StepResult(True, data={"results": result, "provider": name})
                results = [m for m in self._local_messages if query in m.get("message", "").lower()]
                return StepResult(True, data={"results": results, "provider": "local"})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  SPREADSHEET PRIMITIVE - Excel, Google Sheets
# ============================================================



class TelegramPrimitive(Primitive):
    """Telegram — send messages, photos, documents, manage chats.
    
    Uses the Telegram Bot API via TelegramConnector.
    """
    
    def __init__(self, connector: Any = None):
        self._connector = connector
    
    @property
    def name(self) -> str:
        return "TELEGRAM"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "me": "Get the bot's profile info",
            "send_message": "Send a text message to a chat (supports Markdown/HTML)",
            "edit_message": "Edit a previously sent message",
            "delete_message": "Delete a message",
            "forward_message": "Forward a message to another chat",
            "send_photo": "Send a photo by URL with optional caption",
            "send_document": "Send a document/file by URL with optional caption",
            "get_chat": "Get chat info (title, type, description)",
            "get_member_count": "Get number of members in a chat",
            "get_updates": "Get recent incoming messages and updates",
            "pin_message": "Pin a message in a chat",
            "unpin_message": "Unpin a message or all pinned messages",
        }
    
    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "me": {},
            "send_message": {
                "chat_id": {"type": "str", "required": True, "description": "Chat ID or @channel_username"},
                "text": {"type": "str", "required": True, "description": "Message text (Markdown/HTML)"},
                "parse_mode": {"type": "str", "required": False, "description": "'Markdown', 'MarkdownV2', or 'HTML'"},
                "disable_notification": {"type": "bool", "required": False, "description": "Send silently"},
                "reply_to_message_id": {"type": "int", "required": False, "description": "Reply to message ID"},
            },
            "edit_message": {
                "chat_id": {"type": "str", "required": True, "description": "Chat ID"},
                "message_id": {"type": "int", "required": True, "description": "Message ID to edit"},
                "text": {"type": "str", "required": True, "description": "New text"},
                "parse_mode": {"type": "str", "required": False, "description": "'Markdown', 'MarkdownV2', or 'HTML'"},
            },
            "delete_message": {
                "chat_id": {"type": "str", "required": True, "description": "Chat ID"},
                "message_id": {"type": "int", "required": True, "description": "Message ID"},
            },
            "forward_message": {
                "chat_id": {"type": "str", "required": True, "description": "Target chat ID"},
                "from_chat_id": {"type": "str", "required": True, "description": "Source chat ID"},
                "message_id": {"type": "int", "required": True, "description": "Message ID to forward"},
            },
            "send_photo": {
                "chat_id": {"type": "str", "required": True, "description": "Chat ID"},
                "photo_url": {"type": "str", "required": True, "description": "Photo URL"},
                "caption": {"type": "str", "required": False, "description": "Photo caption"},
            },
            "send_document": {
                "chat_id": {"type": "str", "required": True, "description": "Chat ID"},
                "document_url": {"type": "str", "required": True, "description": "Document URL"},
                "caption": {"type": "str", "required": False, "description": "Document caption"},
            },
            "get_chat": {
                "chat_id": {"type": "str", "required": True, "description": "Chat ID or @username"},
            },
            "get_member_count": {
                "chat_id": {"type": "str", "required": True, "description": "Chat ID"},
            },
            "get_updates": {
                "limit": {"type": "int", "required": False, "description": "Max updates (default 10)"},
            },
            "pin_message": {
                "chat_id": {"type": "str", "required": True, "description": "Chat ID"},
                "message_id": {"type": "int", "required": True, "description": "Message ID to pin"},
            },
            "unpin_message": {
                "chat_id": {"type": "str", "required": True, "description": "Chat ID"},
                "message_id": {"type": "int", "required": False, "description": "Specific message to unpin (omit to unpin all)"},
            },
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        if not self._connector:
            return StepResult(False, error="Telegram is not configured. Connect a Telegram bot token in Settings to use Telegram features.")
        try:
            if operation == "me":
                result = await self._connector.me()
                return StepResult(True, data=result)
            
            elif operation == "send_message":
                result = await self._connector.send_message(
                    chat_id=params["chat_id"],
                    text=params["text"],
                    parse_mode=params.get("parse_mode", "Markdown"),
                    disable_notification=bool(params.get("disable_notification", False)),
                    reply_to_message_id=int(params["reply_to_message_id"]) if params.get("reply_to_message_id") else None,
                )
                return StepResult(True, data=result)
            
            elif operation == "edit_message":
                result = await self._connector.edit_message(
                    chat_id=params["chat_id"],
                    message_id=int(params["message_id"]),
                    text=params["text"],
                    parse_mode=params.get("parse_mode", "Markdown"),
                )
                return StepResult(True, data=result)
            
            elif operation == "delete_message":
                await self._connector.delete_message(params["chat_id"], int(params["message_id"]))
                return StepResult(True, data={"deleted": True})
            
            elif operation == "forward_message":
                result = await self._connector.forward_message(
                    chat_id=params["chat_id"],
                    from_chat_id=params["from_chat_id"],
                    message_id=int(params["message_id"]),
                )
                return StepResult(True, data=result)
            
            elif operation == "send_photo":
                result = await self._connector.send_photo(
                    chat_id=params["chat_id"],
                    photo_url=params["photo_url"],
                    caption=params.get("caption"),
                )
                return StepResult(True, data=result)
            
            elif operation == "send_document":
                result = await self._connector.send_document(
                    chat_id=params["chat_id"],
                    document_url=params["document_url"],
                    caption=params.get("caption"),
                )
                return StepResult(True, data=result)
            
            elif operation == "get_chat":
                result = await self._connector.get_chat(params["chat_id"])
                return StepResult(True, data=result)
            
            elif operation == "get_member_count":
                count = await self._connector.get_chat_member_count(params["chat_id"])
                return StepResult(True, data={"member_count": count})
            
            elif operation == "get_updates":
                results = await self._connector.get_updates(
                    limit=int(params.get("limit", 10)),
                )
                return StepResult(True, data={"count": len(results), "updates": results})
            
            elif operation == "pin_message":
                await self._connector.pin_message(params["chat_id"], int(params["message_id"]))
                return StepResult(True, data={"pinned": True})
            
            elif operation == "unpin_message":
                msg_id = int(params["message_id"]) if params.get("message_id") else None
                await self._connector.unpin_message(params["chat_id"], msg_id)
                return StepResult(True, data={"unpinned": True})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))




class SocialPrimitive(Primitive):
    """Social media operations - Twitter, LinkedIn, Facebook, etc."""
    
    def __init__(self, providers: Optional[Dict[str, Any]] = None):
        self._providers = providers or {}
        self._local_posts: List[Dict] = []
    
    @property
    def name(self) -> str:
        return "SOCIAL"
    
    def get_operations(self) -> Dict[str, str]:
        return self.get_available_operations()
    
    def get_available_operations(self) -> Dict[str, str]:
        return {
            "post": "Create a social media post or tweet",
            "delete_post": "Delete a post or tweet",
            "feed": "Get your feed or timeline",
            "search": "Search posts or tweets",
            "like": "Like a post or tweet",
            "unlike": "Unlike a post or tweet",
            "repost": "Retweet or repost",
            "undo_repost": "Undo a retweet or repost",
            "comment": "Comment on or reply to a post",
            "profile": "Get user profile",
            "followers": "Get followers list",
            "following": "Get following list",
            "follow": "Follow a user",
            "unfollow": "Unfollow a user",
            "bookmarks": "Get bookmarked posts",
            "bookmark": "Bookmark a post",
            "user_posts": "Get posts by a specific user",
        }
    
    def get_param_schema(self) -> Dict[str, Any]:
        return {
            "post": {
                "content": {"type": "str", "required": True, "description": "Post/tweet content"},
                "reply_to": {"type": "str", "required": False, "description": "Post ID to reply to"},
                "provider": {"type": "str", "required": False, "description": "Provider: twitter, linkedin"},
            },
            "delete_post": {
                "post_id": {"type": "str", "required": True, "description": "Post/tweet ID to delete"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "feed": {
                "limit": {"type": "int", "required": False, "description": "Max posts (default 20)"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "search": {
                "query": {"type": "str", "required": True, "description": "Search query"},
                "limit": {"type": "int", "required": False, "description": "Max results"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "like": {
                "post_id": {"type": "str", "required": True, "description": "Post/tweet ID to like"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "unlike": {
                "post_id": {"type": "str", "required": True, "description": "Post/tweet ID to unlike"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "repost": {
                "post_id": {"type": "str", "required": True, "description": "Post/tweet ID to retweet/repost"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "undo_repost": {
                "post_id": {"type": "str", "required": True, "description": "Post/tweet ID to undo retweet"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "comment": {
                "post_id": {"type": "str", "required": True, "description": "Post ID to reply to"},
                "text": {"type": "str", "required": True, "description": "Reply/comment text"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "profile": {
                "username": {"type": "str", "required": False, "description": "Username (defaults to self)"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "followers": {
                "username": {"type": "str", "required": False, "description": "Username (defaults to self)"},
                "limit": {"type": "int", "required": False, "description": "Max results"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "following": {
                "username": {"type": "str", "required": False, "description": "Username (defaults to self)"},
                "limit": {"type": "int", "required": False, "description": "Max results"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "follow": {
                "user_id": {"type": "str", "required": True, "description": "User ID to follow"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "unfollow": {
                "user_id": {"type": "str", "required": True, "description": "User ID to unfollow"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "bookmarks": {
                "limit": {"type": "int", "required": False, "description": "Max results"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "bookmark": {
                "post_id": {"type": "str", "required": True, "description": "Post/tweet ID to bookmark"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
            "user_posts": {
                "username": {"type": "str", "required": False, "description": "Username"},
                "user_id": {"type": "str", "required": False, "description": "User ID"},
                "limit": {"type": "int", "required": False, "description": "Max results"},
                "provider": {"type": "str", "required": False, "description": "Provider name"},
            },
        }
    
    def _get_provider(self, name: Optional[str] = None) -> Optional[Any]:
        if name and name in self._providers:
            return self._providers[name]
        if self._providers:
            return next(iter(self._providers.values()))
        return None
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        try:
            provider = self._get_provider(params.get("provider"))
            
            if operation == "post":
                content = params.get("content", "")
                reply_to = params.get("reply_to")
                if provider and hasattr(provider, "post_tweet"):
                    result = await provider.post_tweet(text=content, reply_to=reply_to)
                    return StepResult(True, data=result)
                elif provider and hasattr(provider, "create_post"):
                    result = await provider.create_post(content)
                    return StepResult(True, data=result)
                post = {"id": f"post_{int(datetime.now().timestamp())}", "content": content, "timestamp": datetime.now().isoformat()}
                self._local_posts.append(post)
                return StepResult(True, data={"posted": True, "post": post, "provider": "local"})
            
            elif operation == "delete_post":
                if provider and hasattr(provider, "delete_tweet"):
                    result = await provider.delete_tweet(params["post_id"])
                    return StepResult(True, data={"deleted": result})
                elif provider and hasattr(provider, "delete_post"):
                    result = await provider.delete_post(params["post_id"])
                    return StepResult(True, data={"deleted": result})
                return StepResult(False, error="Delete not supported")
            
            elif operation == "feed":
                limit = params.get("limit", 20)
                if provider and hasattr(provider, "get_user_tweets"):
                    me = await provider.get_me() if hasattr(provider, "get_me") else None
                    if me:
                        result = await provider.get_user_tweets(user_id=me.id if hasattr(me, 'id') else str(me), max_results=limit)
                        return StepResult(True, data=result)
                return StepResult(True, data={"posts": self._local_posts[-limit:], "provider": "local"})
            
            elif operation == "search":
                query = params.get("query", "")
                limit = params.get("limit", 20)
                if provider and hasattr(provider, "search"):
                    result = await provider.search(query=query, max_results=limit)
                    return StepResult(True, data=result)
                results = [p for p in self._local_posts if query.lower() in p.get("content", "").lower()]
                return StepResult(True, data={"posts": results, "provider": "local"})
            
            elif operation == "like":
                if provider and hasattr(provider, "like_tweet"):
                    result = await provider.like_tweet(params["post_id"])
                    return StepResult(True, data={"liked": result})
                return StepResult(True, data={"liked": True, "provider": "local"})
            
            elif operation == "unlike":
                if provider and hasattr(provider, "unlike_tweet"):
                    result = await provider.unlike_tweet(params["post_id"])
                    return StepResult(True, data={"unliked": result})
                return StepResult(True, data={"unliked": True, "provider": "local"})
            
            elif operation == "repost":
                if provider and hasattr(provider, "retweet"):
                    result = await provider.retweet(params["post_id"])
                    return StepResult(True, data={"reposted": result})
                return StepResult(True, data={"reposted": True, "provider": "local"})
            
            elif operation == "undo_repost":
                if provider and hasattr(provider, "undo_retweet"):
                    result = await provider.undo_retweet(params["post_id"])
                    return StepResult(True, data={"undone": result})
                return StepResult(True, data={"undone": True, "provider": "local"})
            
            elif operation == "comment":
                if provider and hasattr(provider, "post_tweet"):
                    result = await provider.post_tweet(text=params["text"], reply_to=params["post_id"])
                    return StepResult(True, data=result)
                return StepResult(True, data={"commented": True, "provider": "local"})
            
            elif operation == "profile":
                username = params.get("username")
                if provider:
                    if username and hasattr(provider, "get_user"):
                        result = await provider.get_user(username=username)
                        return StepResult(True, data=result)
                    elif hasattr(provider, "get_me"):
                        result = await provider.get_me()
                        return StepResult(True, data=result)
                return StepResult(True, data={"profile": {"name": "Local User"}, "provider": "local"})
            
            elif operation == "followers":
                if provider and hasattr(provider, "get_followers"):
                    user_id = params.get("user_id")
                    if not user_id and hasattr(provider, "get_me"):
                        me = await provider.get_me()
                        user_id = me.id if hasattr(me, 'id') else str(me)
                    result = await provider.get_followers(user_id=user_id, max_results=params.get("limit", 20))
                    return StepResult(True, data=result)
                return StepResult(True, data={"followers": [], "provider": "local"})
            
            elif operation == "following":
                if provider and hasattr(provider, "get_following"):
                    user_id = params.get("user_id")
                    if not user_id and hasattr(provider, "get_me"):
                        me = await provider.get_me()
                        user_id = me.id if hasattr(me, 'id') else str(me)
                    result = await provider.get_following(user_id=user_id, max_results=params.get("limit", 20))
                    return StepResult(True, data=result)
                return StepResult(True, data={"following": [], "provider": "local"})
            
            elif operation == "follow":
                if provider and hasattr(provider, "follow_user"):
                    result = await provider.follow_user(params["user_id"])
                    return StepResult(True, data={"followed": result})
                return StepResult(True, data={"followed": True, "provider": "local"})
            
            elif operation == "unfollow":
                if provider and hasattr(provider, "unfollow_user"):
                    result = await provider.unfollow_user(params["user_id"])
                    return StepResult(True, data={"unfollowed": result})
                return StepResult(True, data={"unfollowed": True, "provider": "local"})
            
            elif operation == "bookmarks":
                if provider and hasattr(provider, "get_bookmarks"):
                    result = await provider.get_bookmarks(max_results=params.get("limit", 20))
                    return StepResult(True, data=result)
                return StepResult(True, data={"bookmarks": [], "provider": "local"})
            
            elif operation == "bookmark":
                if provider and hasattr(provider, "bookmark_tweet"):
                    result = await provider.bookmark_tweet(params["post_id"])
                    return StepResult(True, data={"bookmarked": result})
                return StepResult(True, data={"bookmarked": True, "provider": "local"})
            
            elif operation == "user_posts":
                if provider and hasattr(provider, "get_user_tweets"):
                    result = await provider.get_user_tweets(
                        user_id=params.get("user_id"),
                        max_results=params.get("limit", 20),
                    )
                    return StepResult(True, data=result)
                return StepResult(True, data={"posts": [], "provider": "local"})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  PHOTO PRIMITIVE - Photo management
# ============================================================


