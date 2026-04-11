import asyncio
import json

import pytest

import intent_router
import server_state as ss
from react_agent import AgentState
from routes import react as react_routes


class _Session:
    def __init__(self, session_id: str = "s-test"):
        self.session_id = session_id
        self.messages = []
        self.react_state = AgentState()

    def auto_save(self):
        return None


class _Hub:
    async def recall(self, message, limit=5, min_relevance=0.3):
        return []

    async def whats_expected_now(self):
        return []

    async def get_suggestions(self, max_suggestions=3):
        return []

    async def observe(self, action, payload):
        return None

    async def on_event(self, event, payload):
        return None


class _FailRunAgent:
    def __init__(self):
        self.tools = {}
        self.tool_schemas = []
        self.on_step = None
        self.on_thinking = None
        self.on_token = None

    def _build_tool_schemas(self, tools):
        return []

    async def run(self, message):
        raise RuntimeError("stream exploded")


class _FailApproveAgent(_FailRunAgent):
    async def continue_with_approval(self, approved, updated_params=None):
        raise RuntimeError("approval stream exploded")


async def _collect_sse_events(streaming_response, timeout_s=5.0):
    events = []

    async def _collect():
        async for chunk in streaming_response.body_iterator:
            text = chunk.decode() if isinstance(chunk, (bytes, bytearray)) else str(chunk)
            for line in text.splitlines():
                if not line.startswith("data: "):
                    continue
                payload = json.loads(line[6:])
                events.append(payload)
                if payload.get("event") == "complete":
                    return

    await asyncio.wait_for(_collect(), timeout=timeout_s)
    return events


@pytest.mark.asyncio
async def test_chat_stream_emits_complete_after_error(monkeypatch):
    session = _Session()
    agent = _FailRunAgent()

    monkeypatch.setattr(react_routes, "get_intelligence_hub", lambda: _Hub())
    monkeypatch.setattr(react_routes, "_session_workflows", {})
    monkeypatch.setattr(react_routes, "_session_workflow_ids", {})
    monkeypatch.setattr(react_routes.ss, "get_user_session", lambda session_id=None: session)

    async def _get_session_agent(_session):
        return agent

    monkeypatch.setattr(react_routes.ss, "get_session_agent", _get_session_agent)

    async def _classify(_message):
        return intent_router.Intent(type=intent_router.IntentType.FULL)

    monkeypatch.setattr(intent_router, "classify", _classify)

    req = ss.ReactRequest(message="morning brief", session_id="s-test")
    response = await react_routes.react_chat_stream(req)
    events = await _collect_sse_events(response)

    assert any(e.get("event") == "error" for e in events)
    assert any(e.get("event") == "complete" for e in events)
    complete = [e for e in events if e.get("event") == "complete"][-1]
    assert complete["data"].get("is_complete") is True
    assert "stream exploded" in complete["data"].get("response", "")


@pytest.mark.asyncio
async def test_approve_stream_emits_complete_after_error(monkeypatch):
    session = _Session()
    session.react_state = AgentState()
    agent = _FailApproveAgent()

    monkeypatch.setattr(react_routes, "_session_workflows", {})
    monkeypatch.setattr(react_routes, "_session_workflow_ids", {})
    monkeypatch.setattr(react_routes.ss, "get_user_session", lambda session_id=None: session)

    async def _get_session_agent(_session):
        return agent

    monkeypatch.setattr(react_routes.ss, "get_session_agent", _get_session_agent)

    req = ss.ReactApproveRequest(approved=True, session_id="s-test")
    response = await react_routes.react_approve_stream(req)
    events = await _collect_sse_events(response)

    assert any(e.get("event") == "error" for e in events)
    assert any(e.get("event") == "complete" for e in events)
    complete = [e for e in events if e.get("event") == "complete"][-1]
    assert complete["data"].get("is_complete") is True
    assert "approval stream exploded" in complete["data"].get("response", "")
