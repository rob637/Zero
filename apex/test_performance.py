"""
Performance tests — guard against startup and execution regressions.

Run:  python -m pytest test_performance.py -v
"""
import asyncio
import time
import pytest


# ============================================================
#  Import & Startup Performance
# ============================================================

class TestStartupPerformance:
    """Engine should start fast — no heavy imports at module level."""

    def test_engine_import_under_2s(self):
        """Importing apex_engine should take < 2s (no litellm/chromadb at load)."""
        import importlib, sys
        # Force re-import by removing cached module
        mods_to_remove = [k for k in sys.modules if k.startswith('apex_engine')]
        saved = {k: sys.modules.pop(k) for k in mods_to_remove}
        try:
            t0 = time.perf_counter()
            importlib.import_module('apex_engine')
            elapsed = time.perf_counter() - t0
            # Allow generous headroom, but catch 5s+ regressions
            assert elapsed < 2.0, f"apex_engine import took {elapsed:.2f}s (limit: 2s)"
        finally:
            # Restore modules
            sys.modules.update(saved)

    def test_engine_instantiation_under_500ms(self):
        """Creating an Apex instance should be fast — no network calls."""
        from apex_engine import Apex
        t0 = time.perf_counter()
        engine = Apex()
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.5, f"Apex() took {elapsed:.2f}s (limit: 0.5s)"

    def test_primitives_to_tools_under_100ms(self):
        """Converting 200+ primitives to tool schemas should be near-instant."""
        from apex_engine import Apex
        from react_agent import primitives_to_tools
        engine = Apex()
        t0 = time.perf_counter()
        tools = primitives_to_tools(engine._primitives)
        elapsed = time.perf_counter() - t0
        assert len(tools) >= 200, f"Expected 200+ tools, got {len(tools)}"
        assert elapsed < 0.1, f"primitives_to_tools took {elapsed:.3f}s (limit: 0.1s)"


# ============================================================
#  Primitive Execution Performance
# ============================================================

class TestPrimitivePerformance:
    """Local primitives should execute in milliseconds."""

    @pytest.mark.asyncio
    async def test_file_list_under_200ms(self):
        """FILE.list on a local dir should be fast."""
        import os
        from apex_engine import Apex
        engine = Apex()
        prim = engine._primitives["FILE"]
        t0 = time.perf_counter()
        result = await prim.execute("list", {"directory": os.path.expanduser("~")})
        elapsed = time.perf_counter() - t0
        assert result.success, f"FILE.list failed: {result.error}"
        assert elapsed < 0.2, f"FILE.list took {elapsed:.3f}s (limit: 0.2s)"

    @pytest.mark.asyncio
    async def test_compute_calculate_under_100ms(self):
        """COMPUTE.calculate should be near-instant."""
        from apex_engine import Apex
        engine = Apex()
        prim = engine._primitives["COMPUTE"]
        t0 = time.perf_counter()
        result = await prim.execute("calculate", {"expression": "2 + 2 * 10"})
        elapsed = time.perf_counter() - t0
        assert result.success, f"COMPUTE.calculate failed: {result.error}"
        assert elapsed < 0.1, f"COMPUTE.calculate took {elapsed:.3f}s (limit: 0.1s)"

    @pytest.mark.asyncio
    async def test_knowledge_store_under_200ms(self):
        """KNOWLEDGE.remember should be fast (local persistence)."""
        from apex_engine import Apex
        engine = Apex()
        prim = engine._primitives["KNOWLEDGE"]
        t0 = time.perf_counter()
        result = await prim.execute("remember", {"content": "perf test fact", "category": "test"})
        elapsed = time.perf_counter() - t0
        assert result.success, f"KNOWLEDGE.remember failed: {result.error}"
        assert elapsed < 0.2, f"KNOWLEDGE.remember took {elapsed:.3f}s (limit: 0.2s)"

    @pytest.mark.asyncio
    async def test_knowledge_recall_under_200ms(self):
        """KNOWLEDGE.recall should be fast."""
        from apex_engine import Apex
        engine = Apex()
        prim = engine._primitives["KNOWLEDGE"]
        # Store first
        await prim.execute("remember", {"content": "perf test fact", "category": "test"})
        t0 = time.perf_counter()
        result = await prim.execute("recall", {"query": "perf test"})
        elapsed = time.perf_counter() - t0
        assert result.success, f"KNOWLEDGE.recall failed: {result.error}"
        assert elapsed < 0.2, f"KNOWLEDGE.recall took {elapsed:.3f}s (limit: 0.2s)"


# ============================================================
#  Tool Count Regression
# ============================================================

class TestToolCount:
    """Guard against primitives or tools silently disappearing."""

    def test_minimum_primitive_count(self):
        """We should have at least 35 primitives registered."""
        from apex_engine import Apex
        engine = Apex()
        count = len(engine._primitives)
        assert count >= 35, f"Only {count} primitives registered (expected ≥ 35)"

    def test_minimum_tool_count(self):
        """We should have at least 200 tools available."""
        from apex_engine import Apex
        from react_agent import primitives_to_tools
        engine = Apex()
        tools = primitives_to_tools(engine._primitives)
        assert len(tools) >= 200, f"Only {len(tools)} tools (expected ≥ 200)"

    def test_all_primitives_have_operations(self):
        """Every registered primitive should have at least 1 operation."""
        from apex_engine import Apex
        engine = Apex()
        empty = [name for name, p in engine._primitives.items() if len(p.get_operations()) == 0]
        assert not empty, f"Primitives with no operations: {empty}"


# ============================================================
#  ReAct Agent Performance (mock LLM)
# ============================================================

class MockUsage:
    input_tokens = 0
    output_tokens = 0

class MockTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text

class MockToolBlock:
    def __init__(self, id, name, input):
        self.type = "tool_use"
        self.id = id
        self.name = name
        self.input = input

class MockResp:
    def __init__(self, stop_reason, content):
        self.stop_reason = stop_reason
        self.content = content
        self.usage = MockUsage()

class MockClient:
    def __init__(self, responses):
        self.responses = responses
        self.call_count = 0
    @property
    def messages(self):
        return self
    def create(self, **kw):
        r = self.responses[min(self.call_count, len(self.responses) - 1)]
        self.call_count += 1
        return r


class TestAgentPerformance:
    """ReAct agent should be fast when LLM is mocked out."""

    @pytest.mark.asyncio
    async def test_single_tool_call_under_500ms(self):
        """One tool call + response should complete quickly with mock LLM."""
        from react_agent import ReActAgent, Tool

        async def handler(params):
            return {"ok": True}

        tool = Tool(
            name="test.echo",
            description="Echo test",
            parameters={"properties": {"q": {"type": "string"}}, "required": []},
            handler=handler,
            side_effect=False,
        )

        responses = [
            MockResp("tool_use", [MockToolBlock("1", "test.echo", {"q": "hi"})]),
            MockResp("end_turn", [MockTextBlock("Done!")]),
        ]

        agent = ReActAgent(llm_client=MockClient(responses), tools=[tool])
        t0 = time.perf_counter()
        state = await agent.run("test")
        elapsed = time.perf_counter() - t0
        assert state.is_complete
        assert elapsed < 0.5, f"Single tool call took {elapsed:.3f}s (limit: 0.5s)"

    @pytest.mark.asyncio
    async def test_five_tool_calls_under_1s(self):
        """Five sequential tool calls should still be fast with mock LLM."""
        from react_agent import ReActAgent, Tool

        async def handler(params):
            return {"n": params.get("n", 0)}

        tool = Tool(
            name="test.count",
            description="Count",
            parameters={"properties": {"n": {"type": "integer"}}, "required": []},
            handler=handler,
            side_effect=False,
        )

        responses = [
            MockResp("tool_use", [MockToolBlock(str(i), "test.count", {"n": i})])
            for i in range(5)
        ] + [
            MockResp("end_turn", [MockTextBlock("Counted to 5")]),
        ]

        agent = ReActAgent(llm_client=MockClient(responses), tools=[tool])
        t0 = time.perf_counter()
        state = await agent.run("count to 5")
        elapsed = time.perf_counter() - t0
        assert state.is_complete
        assert len(state.steps) == 5
        assert elapsed < 1.0, f"Five tool calls took {elapsed:.3f}s (limit: 1s)"
