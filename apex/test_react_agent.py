"""
Test the ReAct agent with mock tools.
"""
import asyncio
import pytest
from react_agent import ReActAgent, Tool, Step, StepStatus


# ============================================================
#  Test Helpers
# ============================================================

def make_mock_tool(name: str, side_effect: bool = False, result: any = None):
    """Create a mock tool for testing."""
    async def handler(params):
        return result or {"status": "ok", "params_received": params}
    
    return Tool(
        name=name,
        description=f"Mock {name} tool",
        parameters={"properties": {"query": {"type": "string"}}, "required": []},
        handler=handler,
        side_effect=side_effect
    )


class MockLLMClient:
    """Mock LLM client for testing."""
    
    def __init__(self, responses):
        """
        responses: list of (stop_reason, content) tuples
        where content is either text or tool_use blocks
        """
        self.responses = responses
        self.call_count = 0
    
    @property
    def messages(self):
        return self
    
    def create(self, **kwargs):
        response = self.responses[min(self.call_count, len(self.responses) - 1)]
        self.call_count += 1
        return response


class MockUsage:
    """Mock usage info."""
    input_tokens = 0
    output_tokens = 0

class MockResponse:
    """Mock Anthropic API response."""
    
    def __init__(self, stop_reason, content):
        self.stop_reason = stop_reason
        self.content = content
        self.usage = MockUsage()


class MockToolUse:
    """Mock tool_use content block."""
    
    def __init__(self, id, name, input):
        self.type = "tool_use"
        self.id = id
        self.name = name
        self.input = input


class MockText:
    """Mock text content block."""
    
    def __init__(self, text):
        self.type = "text"
        self.text = text


# ============================================================
#  Tests
# ============================================================

@pytest.mark.asyncio
async def test_simple_tool_call():
    """Test: AI calls one tool, gets result, responds."""
    
    # Mock responses: 1) call file.search, 2) respond with text
    responses = [
        MockResponse("tool_use", [MockToolUse("1", "file.search", {"query": "test"})]),
        MockResponse("end_turn", [MockText("Found your file!")]),
    ]
    
    tools = [make_mock_tool("file.search", result={"files": ["test.txt"]})]
    
    agent = ReActAgent(
        llm_client=MockLLMClient(responses),
        tools=tools,
    )
    
    state = await agent.run("Find my test file")
    
    assert state.is_complete
    assert len(state.steps) == 1
    assert state.steps[0].status == StepStatus.COMPLETED
    assert state.final_response == "Found your file!"


@pytest.mark.asyncio
async def test_side_effect_requires_approval():
    """Test: Side-effect tool pauses for approval."""
    
    responses = [
        MockResponse("tool_use", [MockToolUse("1", "email.send", {"to": "test@test.com"})]),
    ]
    
    tools = [make_mock_tool("email.send", side_effect=True)]
    
    agent = ReActAgent(
        llm_client=MockLLMClient(responses),
        tools=tools,
    )
    
    state = await agent.run("Send an email")
    
    assert not state.is_complete
    assert state.pending_approval is not None
    assert state.pending_approval.tool_call.name == "email.send"
    assert state.pending_approval.status == StepStatus.PENDING_APPROVAL


@pytest.mark.asyncio
async def test_approval_continues_execution():
    """Test: After approval, execution continues."""
    
    responses = [
        MockResponse("tool_use", [MockToolUse("1", "email.send", {"to": "test@test.com"})]),
        MockResponse("end_turn", [MockText("Email sent!")]),
    ]
    
    tools = [make_mock_tool("email.send", side_effect=True, result={"status": "sent"})]
    
    agent = ReActAgent(
        llm_client=MockLLMClient(responses),
        tools=tools,
    )
    
    # First run - pauses for approval
    state = await agent.run("Send an email")
    assert state.pending_approval is not None
    
    # Approve and continue
    state = await agent.continue_with_approval(True)
    
    assert state.is_complete
    assert state.final_response == "Email sent!"
    assert state.steps[0].status == StepStatus.COMPLETED


@pytest.mark.asyncio
async def test_rejection_tells_ai():
    """Test: Rejection sends error to AI."""
    
    responses = [
        MockResponse("tool_use", [MockToolUse("1", "email.send", {"to": "test@test.com"})]),
        MockResponse("end_turn", [MockText("OK, I cancelled that action.")]),
    ]
    
    tools = [make_mock_tool("email.send", side_effect=True)]
    
    agent = ReActAgent(
        llm_client=MockLLMClient(responses),
        tools=tools,
    )
    
    state = await agent.run("Send an email")
    state = await agent.continue_with_approval(False)
    
    assert state.is_complete
    assert state.steps[0].status == StepStatus.CANCELLED


@pytest.mark.asyncio
async def test_multi_step_flow():
    """Test: Multiple tools called in sequence."""
    
    responses = [
        MockResponse("tool_use", [MockToolUse("1", "file.search", {"query": "doc"})]),
        MockResponse("tool_use", [MockToolUse("2", "file.read", {"path": "/doc.txt"})]),
        MockResponse("end_turn", [MockText("Here's your document content.")]),
    ]
    
    tools = [
        make_mock_tool("file.search", result={"files": ["/doc.txt"]}),
        make_mock_tool("file.read", result={"content": "Hello world"}),
    ]
    
    agent = ReActAgent(
        llm_client=MockLLMClient(responses),
        tools=tools,
    )
    
    state = await agent.run("Find and read my doc")
    
    assert state.is_complete
    assert len(state.steps) == 2
    assert state.steps[0].tool_call.name == "file.search"
    assert state.steps[1].tool_call.name == "file.read"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
