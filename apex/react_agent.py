"""
ReAct Agent - Native function calling orchestration.

This replaces the JSON-plan approach with direct tool calling.
The AI calls tools one at a time, sees results, and decides next steps.
"""

import json
import asyncio
import logging
import os
import random
import hashlib
from collections import Counter
from dataclasses import dataclass, field, asdict, is_dataclass
from typing import Any, Callable, Dict, List, Optional, Awaitable
from enum import Enum

logger = logging.getLogger(__name__)


async def _retry_with_backoff(fn, max_retries=3, base_delay=1.0):
    """Call fn() with exponential backoff on transient failures.
    
    Retries on rate limits (429), overload (529), and server errors (5xx).
    """
    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except Exception as e:
            err_str = str(e).lower()
            status = getattr(e, 'status_code', None) or getattr(e, 'status', None)
            is_retryable = (
                status in (429, 529, 500, 502, 503)
                or 'rate' in err_str
                or 'overloaded' in err_str
                or 'capacity' in err_str
                or 'timeout' in err_str
            )
            if not is_retryable or attempt == max_retries:
                raise
            delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
            logger.warning(f"LLM call failed (attempt {attempt+1}/{max_retries+1}), retrying in {delay:.1f}s: {e}")
            await asyncio.sleep(delay)


def serialize(obj: Any) -> Any:
    """Convert any object to JSON-serializable form."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (list, tuple)):
        return [serialize(item) for item in obj]
    if isinstance(obj, dict):
        return {k: serialize(v) for k, v in obj.items()}
    if is_dataclass(obj) and not isinstance(obj, type):
        return serialize(asdict(obj))
    if hasattr(obj, '__dict__'):
        return serialize(vars(obj))
    # Fallback
    return str(obj)


class StepStatus(Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PENDING_APPROVAL = "pending_approval"
    CANCELLED = "cancelled"


@dataclass
class ToolCall:
    """A tool call from the AI."""
    id: str
    name: str
    params: Dict[str, Any]


@dataclass
class Step:
    """A single step in the agent's execution."""
    tool_call: ToolCall
    status: StepStatus = StepStatus.RUNNING
    result: Any = None
    error: Optional[str] = None
    requires_approval: bool = False


@dataclass
class Tool:
    """Definition of a tool the AI can call."""
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema
    handler: Callable[[Dict[str, Any]], Awaitable[Any]]
    side_effect: bool = False  # If True, requires user approval


@dataclass
class AgentState:
    """Current state of the agent."""
    messages: List[Dict[str, Any]] = field(default_factory=list)
    steps: List[Step] = field(default_factory=list)
    pending_approval: Optional[Step] = None
    is_complete: bool = False
    final_response: Optional[str] = None
    # Cost tracking
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    llm_calls: int = 0

    @property
    def estimated_cost_usd(self) -> float:
        """Estimate cost (Sonnet 4 pricing: $3/$15 per MTok, cache read $0.30)."""
        return (
            (self.input_tokens * 3.0 / 1_000_000)
            + (self.output_tokens * 15.0 / 1_000_000)
            + (self.cache_read_tokens * 0.30 / 1_000_000)
            + (self.cache_creation_tokens * 3.75 / 1_000_000)
        )


class ReActAgent:
    """
    ReAct Agent using native function calling.
    
    The AI calls tools, sees results, and continues until done.
    Side-effect tools pause for user approval.
    """
    
    def __init__(
        self,
        llm_client: Any,  # Anthropic or OpenAI client
        tools: List[Tool],
        system_prompt: Optional[str] = None,
        on_step: Optional[Callable[[Step], Awaitable[None]]] = None,
        on_thinking: Optional[Callable[[], Awaitable[None]]] = None,
        on_token: Optional[Callable[[str], None]] = None,
    ):
        self.llm_client = llm_client
        self.tools = {t.name: t for t in tools}
        self.tool_schemas = self._build_tool_schemas(tools)
        self.system_prompt = system_prompt or self._default_system_prompt()
        self.on_step = on_step  # Callback when step starts/completes
        self.on_thinking = on_thinking  # Callback before each LLM call
        self.on_token = on_token  # Sync callback for streaming text tokens
        self.state = AgentState()
        # Request-scoped cache for idempotent/read-only tool calls.
        self._readonly_tool_cache: Dict[str, Any] = {}
        self._readonly_tool_cache_hits: int = 0
        # Request-scoped set of executed side-effect signatures to prevent
        # duplicate action loops from repeatedly prompting/executing.
        self._executed_side_effect_signatures: set[str] = set()
        # Tracks the most recently approved side-effect action so we can
        # suppress immediate same-action approval loops without hardcoding.
        self._last_approved_tool_name: Optional[str] = None
        self._steps_len_at_last_approval: int = 0
    
    def _default_system_prompt(self) -> str:
        return """You are a helpful AI assistant that can perform actions on the user's behalf.

Use the available tools to accomplish what the user asks. You can call multiple tools in parallel when the calls are independent of each other.

IMPORTANT BEHAVIORS:
- If a search returns multiple results, ASK the user which one they want before proceeding
- For AMBIGUOUS targets (which contact? which account? which files?): ask. Don't guess identity or scope.
- For IRREVERSIBLE actions (sending emails, creating events, payments): confirm details before executing.
- For CREATIVE tasks (documents, presentations, charts): just start with reasonable defaults. The user can iterate.
- Show computed results (calculations, schedules, etc.) to the user before sending/creating
- Be conversational - explain what you're doing and what you found
- LEARN: When you discover something useful about the user — their preferences, important people, which services/calendars/playlists they care about, how they like things done — use KNOWLEDGE.remember to store it. You have a persistent memory. Use it so you get better over time.

When you have completed the task, respond with a summary of what was done."""
    
    def _build_tool_schemas(self, tools: List[Tool]) -> List[Dict]:
        """Convert tools to Anthropic tool schema format."""
        schemas = []
        for tool in tools:
            schemas.append({
                "name": tool.name,
                "description": tool.description + (" [ACTION - requires approval]" if tool.side_effect else ""),
                "input_schema": {
                    "type": "object",
                    "properties": tool.parameters.get("properties", {}),
                    "required": tool.parameters.get("required", []),
                }
            })
        return schemas
    
    async def run(self, user_message: str) -> AgentState:
        """
        Run the agent with a user message.
        
        Returns the final state. If pending_approval is set,
        caller should get approval and call continue_with_approval().
        """
        self.state = AgentState()
        self._readonly_tool_cache = {}
        self._readonly_tool_cache_hits = 0
        self._executed_side_effect_signatures = set()
        self._last_approved_tool_name = None
        self._steps_len_at_last_approval = 0
        self.state.messages = [
            {"role": "user", "content": user_message}
        ]
        
        return await self._execute_loop()
    
    async def continue_with_approval(self, approved: bool, updated_params: Optional[Dict[str, Any]] = None) -> AgentState:
        """Continue after user approves or rejects a pending action."""
        if not self.state.pending_approval:
            return self.state
        
        # Clear previous response - we're continuing, not repeating
        self.state.is_complete = False
        self.state.final_response = None
        
        step = self.state.pending_approval
        self.state.pending_approval = None
        
        # Find and update the placeholder in the last user message
        tool_use_id = step.tool_call.id
        
        if approved:
            if isinstance(updated_params, dict):
                step.tool_call.params = updated_params
            # Execute the approved tool
            result = await asyncio.wait_for(
                self._execute_tool(step.tool_call),
                timeout=self.TOOL_TIMEOUT_SECONDS,
            )
            sig = self._side_effect_signature(step.tool_call)
            if sig:
                self._executed_side_effect_signatures.add(sig)
            self._last_approved_tool_name = step.tool_call.name
            self._steps_len_at_last_approval = len(self.state.steps)
            step.result = serialize(result)
            step.status = StepStatus.COMPLETED
            
            # Prepare truncated result
            result_str = json.dumps(step.result) if not isinstance(step.result, str) else step.result
            if len(result_str) > self.MAX_TOOL_RESULT_CHARS:
                result_str = result_str[:self.MAX_TOOL_RESULT_CHARS] + f"\n... [truncated, {len(result_str)} chars total]"
            
            new_content = result_str
        else:
            step.status = StepStatus.CANCELLED
            step.error = "Cancelled by user"
            new_content = "Action cancelled by user. Ask if they want to do something else."
        
        # Replace placeholder in last user message (same tool_use_id)
        for msg in reversed(self.state.messages):
            if msg.get("role") == "user" and isinstance(msg.get("content"), list):
                for item in msg["content"]:
                    if item.get("type") == "tool_result" and item.get("tool_use_id") == tool_use_id:
                        item["content"] = new_content
                        if not approved:
                            item["is_error"] = True
                        break
                break
        
        if self.on_step:
            await self.on_step(step)
        
        return await self._execute_loop()
    
    async def continue_with_input(self, user_input: str) -> AgentState:
        """Continue after user provides additional input."""
        # Clear previous response - we're continuing, not repeating
        self.state.is_complete = False
        self.state.final_response = None
        self._last_approved_tool_name = None
        self._steps_len_at_last_approval = 0
        
        self.state.messages.append({"role": "user", "content": user_input})
        return await self._execute_loop()
    
    # Configurable model name
    ANTHROPIC_MODEL = os.environ.get("TELIC_MODEL", "claude-sonnet-4-20250514")
    # Lower default output budget to reduce synthesis latency.
    MAX_MODEL_OUTPUT_TOKENS = int(os.environ.get("TELIC_MAX_OUTPUT_TOKENS", "1200"))

    # Max cost per request (USD). Agent stops gracefully if exceeded.
    MAX_REQUEST_COST_USD = float(os.environ.get("TELIC_MAX_REQUEST_COST", "2.00"))
    # Hard timeout for any single tool call (seconds).
    TOOL_TIMEOUT_SECONDS = float(os.environ.get("TELIC_TOOL_TIMEOUT_SECONDS", "30"))
    # Global cap on orchestration iterations.
    MAX_ITERATIONS = int(os.environ.get("TELIC_MAX_ITERATIONS", "20"))
    MAX_ITERATIONS_STRICT = int(os.environ.get("TELIC_MAX_ITERATIONS_STRICT", "14"))
    MAX_ITERATIONS_BALANCED = int(os.environ.get("TELIC_MAX_ITERATIONS_BALANCED", "20"))
    MAX_ITERATIONS_FAST = int(os.environ.get("TELIC_MAX_ITERATIONS_FAST", "12"))
    # Keep tool results compact to prevent context bloat.
    MAX_TOOL_RESULT_CHARS = int(os.environ.get("TELIC_MAX_TOOL_RESULT_CHARS", "800"))
    MAX_PARALLEL_READ_STRICT = int(os.environ.get("TELIC_MAX_PARALLEL_READ_STRICT", "3"))
    MAX_PARALLEL_READ_BALANCED = int(os.environ.get("TELIC_MAX_PARALLEL_READ_BALANCED", "4"))
    MAX_PARALLEL_READ_FAST = int(os.environ.get("TELIC_MAX_PARALLEL_READ_FAST", "6"))
    # Detect and stop low-novelty loops before hitting max iterations.
    LOW_NOVELTY_WINDOW = int(os.environ.get("TELIC_LOW_NOVELTY_WINDOW", "12"))
    LOW_NOVELTY_MAX_UNIQUE_TOOLS = int(os.environ.get("TELIC_LOW_NOVELTY_MAX_UNIQUE_TOOLS", "3"))
    LOW_NOVELTY_DOMINANT_RATIO = float(os.environ.get("TELIC_LOW_NOVELTY_DOMINANT_RATIO", "0.58"))

    async def _execute_loop(self) -> AgentState:
        """Main execution loop."""
        orch_mode = os.environ.get("TELIC_ORCH_MODE", "balanced").strip().lower()
        if orch_mode == "strict":
            max_iterations = min(self.MAX_ITERATIONS, self.MAX_ITERATIONS_STRICT)
            max_parallel_read = self.MAX_PARALLEL_READ_STRICT
        elif orch_mode == "fast":
            max_iterations = min(self.MAX_ITERATIONS, self.MAX_ITERATIONS_FAST)
            max_parallel_read = self.MAX_PARALLEL_READ_FAST
        else:
            max_iterations = min(self.MAX_ITERATIONS, self.MAX_ITERATIONS_BALANCED)
            max_parallel_read = self.MAX_PARALLEL_READ_BALANCED
        
        for _ in range(max_iterations):
            # Budget guard — stop before burning too much
            if self.state.estimated_cost_usd >= self.MAX_REQUEST_COST_USD:
                self.state.is_complete = True
                self.state.final_response = (
                    f"I've reached the cost limit for this request "
                    f"(${self.state.estimated_cost_usd:.3f} / ${self.MAX_REQUEST_COST_USD:.2f}). "
                    f"The work so far is shown above. You can continue with a follow-up message."
                )
                logger.warning(f"Cost budget exceeded: ${self.state.estimated_cost_usd:.4f}")
                return self.state

            if self._is_low_novelty_loop():
                self.state.is_complete = True
                self.state.final_response = (
                    "I'm not making enough progress with the current signals, so I stopped to avoid looping. "
                    "I can continue if you confirm the exact target file/output, or I can proceed with the best current match."
                )
                logger.warning("Low-novelty loop guard triggered; stopping orchestration early")
                self._log_cache_stats()
                return self.state

            # Trim context window if too large to prevent exceeding token limits.
            # ~4 chars/token average; 180k tokens ≈ 720k chars. Trim at 600k to leave room.
            self._trim_context_window(max_chars=600_000)
            
            # Notify that we're about to call the LLM
            if self.on_thinking:
                await self.on_thinking()
            
            # Call LLM with tools
            response = await self._call_llm()
            
            # Check if AI is done (no tool calls, just text)
            if response.stop_reason == "end_turn":
                self.state.is_complete = True
                self.state.final_response = self._extract_text(response)
                # Add assistant's text response to messages for context continuity
                if self.state.final_response:
                    self.state.messages.append({
                        "role": "assistant",
                        "content": self.state.final_response
                    })
                self._log_cache_stats()
                return self.state
            
            # Process tool calls
            tool_calls = self._extract_tool_calls(response)
            
            if not tool_calls:
                # No tool calls and not end_turn - extract any text and finish
                self.state.is_complete = True
                self.state.final_response = self._extract_text(response)
                if self.state.final_response:
                    self.state.messages.append({
                        "role": "assistant",
                        "content": self.state.final_response
                    })
                self._log_cache_stats()
                return self.state
            
            # IMPORTANT: Add assistant's response (with tool_use) to messages FIRST
            # Anthropic requires tool_result to follow the tool_use in messages
            self.state.messages.append({
                "role": "assistant",
                "content": [{"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.params} for tc in tool_calls]
            })
            
            # Collect all tool results to add as ONE user message
            tool_results = []
            
            # Execute tool calls — parallel for read-only, sequential for side-effects
            readonly_calls = [(tc, self.tools.get(tc.name)) for tc in tool_calls
                              if self.tools.get(tc.name) and not self.tools[tc.name].side_effect]
            sideeffect_calls = [(tc, self.tools.get(tc.name)) for tc in tool_calls
                                if not self.tools.get(tc.name) or self.tools[tc.name].side_effect]
            
            # Run read-only tools in parallel
            async def _run_tool(tc, tool):
                step = Step(tool_call=tc)
                self.state.steps.append(step)
                if not tool:
                    step.status = StepStatus.FAILED
                    step.error = f"Unknown tool: {tc.name}"
                    if self.on_step:
                        await self.on_step(step)
                    return {
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": f"Error: Unknown tool '{tc.name}'",
                        "is_error": True
                    }
                if self.on_step:
                    await self.on_step(step)
                try:
                    cache_key = self._tool_cache_key(tc)
                    if cache_key and cache_key in self._readonly_tool_cache:
                        self._readonly_tool_cache_hits += 1
                        result = self._readonly_tool_cache[cache_key]
                    else:
                        result = await asyncio.wait_for(
                            self._execute_tool(tc),
                            timeout=self.TOOL_TIMEOUT_SECONDS,
                        )
                        if cache_key:
                            self._readonly_tool_cache[cache_key] = result
                    step.result = serialize(result)
                    step.status = StepStatus.COMPLETED
                    result_str = json.dumps(step.result) if not isinstance(step.result, str) else step.result
                    if len(result_str) > self.MAX_TOOL_RESULT_CHARS:
                        result_str = result_str[:self.MAX_TOOL_RESULT_CHARS] + f"\n... [truncated, {len(result_str)} chars total]"
                    if self.on_step:
                        await self.on_step(step)
                    return {
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": result_str
                    }
                except Exception as e:
                    step.status = StepStatus.FAILED
                    step.error = str(e)
                    logger.error(f"Tool {tc.name} failed: {e}", exc_info=True)
                    if self.on_step:
                        await self.on_step(step)
                    return {
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": f"Error: {str(e)}",
                        "is_error": True
                    }
            
            # Parallel execution of read-only tools
            if readonly_calls:
                sem = asyncio.Semaphore(max(1, max_parallel_read))

                async def _run_tool_limited(tc, tool):
                    async with sem:
                        return await _run_tool(tc, tool)

                parallel_results = await asyncio.gather(
                    *[_run_tool_limited(tc, tool) for tc, tool in readonly_calls]
                )
                tool_results.extend(parallel_results)
            
            # Sequential execution of side-effect tools (require approval)
            for tc, tool in sideeffect_calls:
                step = Step(tool_call=tc)
                self.state.steps.append(step)

                if not tool:
                    step.status = StepStatus.FAILED
                    step.error = f"Unknown tool: {tc.name}"
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": f"Error: Unknown tool '{tc.name}'",
                        "is_error": True
                    })
                    if self.on_step:
                        await self.on_step(step)
                    continue

                # Skip duplicate side-effect calls in the same request to avoid
                # repeat approval loops and duplicate external actions.
                side_sig = self._side_effect_signature(tc)
                if side_sig and side_sig in self._executed_side_effect_signatures:
                    step.status = StepStatus.COMPLETED
                    step.result = "Skipped duplicate side-effect action (already executed in this request)."
                    if self.on_step:
                        await self.on_step(step)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": "Skipped duplicate side-effect action (already executed in this request)."
                    })
                    continue

                # Generic loop guard: after approving a side-effect, block the
                # same side-effect from being requested again unless there is
                # new read-only evidence since that approval.
                if self._is_repeat_after_approval_without_new_signal(tc.name):
                    step.status = StepStatus.COMPLETED
                    step.result = (
                        f"Blocked repeated side-effect loop for '{tc.name}'. "
                        "This action was already approved/executed in this request. "
                        "Continue using the existing result, or ask user before creating/sending another."
                    )
                    logger.warning(
                        "Blocked repeated side-effect approval loop for %s",
                        tc.name,
                    )
                    if self.on_step:
                        await self.on_step(step)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": step.result,
                    })
                    continue

                # Side-effect tool — pause for user approval
                if self.on_step:
                    await self.on_step(step)
                step.status = StepStatus.PENDING_APPROVAL
                step.requires_approval = True
                self.state.pending_approval = step
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": "[Awaiting user approval]"
                })
                if self.on_step:
                    await self.on_step(step)
                self.state.messages.append({"role": "user", "content": tool_results})
                return self.state  # Pause for approval
            
            # Add ALL tool results as ONE user message
            if tool_results:
                self.state.messages.append({"role": "user", "content": tool_results})
        
        # Hit iteration limit
        self.state.is_complete = True
        self.state.final_response = "I've reached the maximum number of steps. Please try a simpler request."
        self._log_cache_stats()
        return self.state

    @staticmethod
    def _side_effect_signature(tool_call: ToolCall) -> Optional[str]:
        """Stable signature for side-effect de-duplication.

        Normalizes common volatile metadata keys and large payloads so
        semantically identical actions map to the same signature.
        """

        volatile_keys = {
            "timestamp",
            "time",
            "generated_at",
            "created_at",
            "updated_at",
            "request_id",
            "correlation_id",
            "nonce",
            "trace_id",
        }

        def _normalize(value: Any) -> Any:
            if isinstance(value, dict):
                out = {}
                for k in sorted(value.keys()):
                    lk = str(k).lower()
                    if lk in volatile_keys:
                        continue
                    out[k] = _normalize(value[k])
                return out
            if isinstance(value, list):
                return [_normalize(v) for v in value]
            if isinstance(value, str):
                return value.strip()
            return value

        try:
            norm_params = _normalize(tool_call.params or {})
            # Avoid massive signatures while preserving duplicate semantics.
            if isinstance(norm_params, dict) and "data" in norm_params:
                data_json = json.dumps(norm_params["data"], sort_keys=True, default=str)
                norm_params["data_hash"] = hashlib.sha256(data_json.encode("utf-8")).hexdigest()
                del norm_params["data"]
            params_json = json.dumps(norm_params, sort_keys=True, default=str)
            return f"{tool_call.name}|{params_json}"
        except Exception:
            return None

    def _is_repeat_after_approval_without_new_signal(self, tool_name: str) -> bool:
        """True when the same side-effect repeats immediately after approval.

        This keeps orchestration generic: it does not hardcode scenarios, only
        prevents approval loops when no new read-only evidence has appeared.
        """
        if not self._last_approved_tool_name:
            return False
        if tool_name != self._last_approved_tool_name:
            return False

        for step in self.state.steps[self._steps_len_at_last_approval:]:
            tool = self.tools.get(step.tool_call.name)
            if tool and not tool.side_effect and step.status == StepStatus.COMPLETED:
                return False
        return True

    def _is_low_novelty_loop(self) -> bool:
        """Detect read-only churn where orchestration keeps cycling with little novelty."""
        window = self.LOW_NOVELTY_WINDOW
        if len(self.state.steps) < window:
            return False

        recent = [s for s in self.state.steps[-window:] if s.status == StepStatus.COMPLETED]
        if len(recent) < window:
            return False

        # If any recent completed step is side-effectful, we are still progressing.
        for step in recent:
            tool = self.tools.get(step.tool_call.name)
            if tool and tool.side_effect:
                return False

        names = [s.tool_call.name for s in recent]
        unique_names = set(names)
        if len(unique_names) > self.LOW_NOVELTY_MAX_UNIQUE_TOOLS:
            return False

        dominant = Counter(names).most_common(1)[0][1] / max(len(names), 1)
        if dominant < self.LOW_NOVELTY_DOMINANT_RATIO:
            return False

        # If we've produced explicit completion text recently, don't trip the guard.
        if self.state.final_response:
            return False

        return True

    @staticmethod
    def _tool_cache_key(tool_call: ToolCall) -> Optional[str]:
        """Stable cache key for idempotent read-only tool calls.

        Returns None when params cannot be serialized safely.
        """
        try:
            params_json = json.dumps(tool_call.params or {}, sort_keys=True, default=str)
            return f"{tool_call.name}|{params_json}"
        except Exception:
            return None

    def _log_cache_stats(self) -> None:
        if self._readonly_tool_cache_hits:
            logger.info(
                f"Read-only tool cache hits: {self._readonly_tool_cache_hits} "
                f"(entries={len(self._readonly_tool_cache)})"
            )
    
    async def _call_llm(self) -> Any:
        """Call the LLM with current messages and tools."""
        # This handles both Anthropic and OpenAI-style clients
        if hasattr(self.llm_client, 'messages'):
            # Anthropic client
            return await self._call_anthropic()
        else:
            # OpenAI-style client
            return await self._call_openai()
    
    async def _call_anthropic(self) -> Any:
        """Call Anthropic's Claude API with prompt caching."""
        import time as _time
        _t0 = _time.perf_counter()
        # Calculate context size for logging
        _ctx_size = sum(len(json.dumps(m)) for m in self.state.messages)

        # Build system prompt with cache_control so it's cached across turns.
        # Tools are the biggest token cost — cache them too.
        system_blocks = [
            {
                "type": "text",
                "text": self.system_prompt,
                "cache_control": {"type": "ephemeral"}
            }
        ]

        # Mark the last tool with cache_control so the entire tool list is cached
        cached_tools = list(self.tool_schemas)  # shallow copy
        if cached_tools:
            cached_tools[-1] = {**cached_tools[-1], "cache_control": {"type": "ephemeral"}}

        if self.on_token:
            # Streaming mode — fire on_token for each text chunk so the UI
            # can render the response progressively. on_token is synchronous
            # and called from the background thread.
            on_token = self.on_token
            def _stream_sync():
                with self.llm_client.messages.stream(
                    model=self.ANTHROPIC_MODEL,
                    max_tokens=self.MAX_MODEL_OUTPUT_TOKENS,
                    system=system_blocks,
                    tools=cached_tools,
                    messages=self.state.messages,
                ) as stream:
                    for text in stream.text_stream:
                        on_token(text)
                    return stream.get_final_message()
            response = await asyncio.to_thread(_stream_sync)
        else:
            response = await _retry_with_backoff(lambda: asyncio.to_thread(
                self.llm_client.messages.create,
                model=self.ANTHROPIC_MODEL,
                max_tokens=self.MAX_MODEL_OUTPUT_TOKENS,
                system=system_blocks,
                tools=cached_tools,
                messages=self.state.messages
            ))
        _elapsed = _time.perf_counter() - _t0
        _cache_info = ""
        if hasattr(response, 'usage'):
            u = response.usage
            self.state.input_tokens += getattr(u, 'input_tokens', 0) or 0
            self.state.output_tokens += getattr(u, 'output_tokens', 0) or 0
            _cr = getattr(u, 'cache_creation_input_tokens', 0) or 0
            _ch = getattr(u, 'cache_read_input_tokens', 0) or 0
            self.state.cache_creation_tokens += _cr
            self.state.cache_read_tokens += _ch
            self.state.llm_calls += 1
            if _cr or _ch:
                _cache_info = f" | cache: created={_cr} read={_ch}"
        logger.info(f"LLM call: {_elapsed:.1f}s | context: {_ctx_size:,} chars | usage: {response.usage}{_cache_info}")

        # Audit log: record what was sent to the LLM
        try:
            from src.privacy.audit_log import audit_logger, TransmissionDestination
            _user_msg = self.state.messages[-1].get("content", "")[:200] if self.state.messages else ""
            audit_logger.log_outbound(
                destination=TransmissionDestination.ANTHROPIC,
                content=json.dumps(self.state.messages[-2:], default=str)[:2000],
                triggering_request=_user_msg,
                model=self.ANTHROPIC_MODEL,
                endpoint="messages.create",
            )
        except Exception:
            pass  # Non-fatal

        return response
    
    async def _call_openai(self) -> Any:
        """Call OpenAI-style API (including compatible APIs)."""
        # Convert tool schemas to OpenAI format
        openai_tools = []
        for schema in self.tool_schemas:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": schema["name"],
                    "description": schema["description"],
                    "parameters": schema["input_schema"]
                }
            })
        
        messages = [{"role": "system", "content": self.system_prompt}]
        messages.extend(self._convert_messages_to_openai())
        
        response = await _retry_with_backoff(lambda: asyncio.to_thread(
            self.llm_client.chat.completions.create,
            model="gpt-4o",
            messages=messages,
            max_tokens=self.MAX_MODEL_OUTPUT_TOKENS,
            tools=openai_tools if openai_tools else None
        ))
        return self._wrap_openai_response(response)
    
    def _convert_messages_to_openai(self) -> List[Dict]:
        """Convert Anthropic-style messages to OpenAI format."""
        converted = []
        for msg in self.state.messages:
            if isinstance(msg.get("content"), list):
                # Tool result
                for item in msg["content"]:
                    if item.get("type") == "tool_result":
                        converted.append({
                            "role": "tool",
                            "tool_call_id": item["tool_use_id"],
                            "content": item["content"]
                        })
            else:
                converted.append(msg)
        return converted
    
    def _wrap_openai_response(self, response) -> Any:
        """Wrap OpenAI response to match Anthropic interface."""
        choice = response.choices[0]
        
        class WrappedResponse:
            def __init__(self, choice):
                self.stop_reason = "end_turn" if choice.finish_reason == "stop" else "tool_use"
                self.content = []
                
                if choice.message.content:
                    self.content.append(type('TextBlock', (), {'type': 'text', 'text': choice.message.content})())
                
                if choice.message.tool_calls:
                    for tc in choice.message.tool_calls:
                        self.content.append(type('ToolUse', (), {
                            'type': 'tool_use',
                            'id': tc.id,
                            'name': tc.function.name,
                            'input': json.loads(tc.function.arguments)
                        })())
        
        return WrappedResponse(choice)
    
    def _extract_tool_calls(self, response) -> List[ToolCall]:
        """Extract tool calls from LLM response."""
        calls = []
        for block in response.content:
            if getattr(block, 'type', None) == 'tool_use':
                calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    params=block.input
                ))
        return calls
    
    def _extract_text(self, response) -> str:
        """Extract text content from LLM response."""
        texts = []
        for block in response.content:
            if getattr(block, 'type', None) == 'text':
                texts.append(block.text)
        return "\n".join(texts)
    
    async def _execute_tool(self, tool_call: ToolCall) -> Any:
        """Execute a tool call with a timeout guard."""
        tool = self.tools.get(tool_call.name)
        if not tool:
            raise ValueError(f"Unknown tool: {tool_call.name}")
        
        try:
            return await asyncio.wait_for(tool.handler(tool_call.params), timeout=self.TOOL_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Tool '{tool_call.name}' timed out after {self.TOOL_TIMEOUT_SECONDS:.0f}s")

    def _trim_context_window(self, max_chars: int = 600_000) -> None:
        """Trim conversation history when approaching context limit.

        Keeps the first user message (original request) and the most recent
        messages, dropping the middle.  A summary marker is inserted so the
        AI knows context was trimmed.
        """
        msgs = self.state.messages
        total = sum(len(json.dumps(m)) for m in msgs)
        if total <= max_chars or len(msgs) <= 4:
            return

        # Keep first message (original request) + last N messages
        # Remove from the middle until under budget
        keep_first = 1
        keep_last = len(msgs) // 2  # Start with half
        while keep_last > 2:
            tail = msgs[-keep_last:]
            tail_size = sum(len(json.dumps(m)) for m in tail)
            first_size = len(json.dumps(msgs[0]))
            if first_size + tail_size + 200 <= max_chars:
                break
            keep_last -= 1

        trimmed_count = len(msgs) - keep_first - keep_last
        summary_msg = {
            "role": "user",
            "content": f"[Context trimmed: {trimmed_count} earlier messages removed to stay within limits. Continue with the current task.]"
        }
        self.state.messages = msgs[:keep_first] + [summary_msg] + msgs[-keep_last:]
        logger.info(f"Context trimmed: {total:,} chars -> {sum(len(json.dumps(m)) for m in self.state.messages):,} chars ({trimmed_count} messages dropped)")


def primitives_to_tools(primitives: Dict[str, Any], connected_only: bool = True) -> List[Tool]:
    """
    Convert Apex primitives to ReAct tools.
    
    Each primitive operation becomes a tool.
    When connected_only=True (default), skip primitives that have no
    connected providers — don't send 353 tools when only 12 are live.
    Built-in primitives (search, weather, compute, etc.) are always included.
    """
    # Primitives that work without an external provider connection
    ALWAYS_INCLUDE = {
        "search", "web", "compute", "file", "shell", "clipboard",
        "screenshot", "automation", "document", "data", "database",
        "translate", "knowledge", "intelligence", "patterns", "notify",
        "browser", "weather", "news", "finance", "home", "shopping",
        "devtools",
    }

    tools = []
    skipped = 0
    
    for prim_name, primitive in primitives.items():
        available_ops = primitive.get_available_operations()
        schema = primitive.get_param_schema() or {}
        
        # Get connected providers for description enrichment
        connected = []
        if hasattr(primitive, 'get_connected_providers'):
            connected = primitive.get_connected_providers()
        
        # Skip unconnected external service primitives
        if connected_only and not connected and prim_name.lower() not in ALWAYS_INCLUDE:
            skipped += len(available_ops)
            continue

        provider_suffix = f" [via {', '.join(connected)}]" if connected else ""
        
        for op_name, description in available_ops.items():
            # Determine if this operation has side effects
            side_effect_keywords = [
                "send", "forward", "reply", "create", "write",
                "delete", "move", "update", "post", "remove",
                "archive", "trash", "share", "invite", "publish",
            ]
            has_side_effect = any(kw in op_name.lower() for kw in side_effect_keywords)
            
            # Get parameter schema for this operation
            op_schema = schema.get(op_name, {})
            properties = {}
            required = []
            
            for param_name, param_def in op_schema.items():
                if isinstance(param_def, dict):
                    ptype = param_def.get("type", "string")
                    # Map Python types to JSON Schema types
                    type_map = {"str": "string", "int": "integer", "float": "number", "bool": "boolean", "list": "array", "dict": "object"}
                    json_type = type_map.get(ptype, ptype)
                    
                    prop = {
                        "type": json_type,
                        "description": param_def.get("description", param_name)
                    }
                    properties[param_name] = prop
                    if param_def.get("required", False):
                        required.append(param_name)
            
            # Create handler closure properly
            def make_handler(prim, op):
                async def handler(params: Dict[str, Any]) -> Any:
                    return await prim.execute(op, params)
                return handler
            
            tool = Tool(
                name=f"{prim_name.lower()}_{op_name}",
                description=f"{description}{provider_suffix}",
                parameters={"properties": properties, "required": required},
                handler=make_handler(primitive, op_name),
                side_effect=has_side_effect
            )
            
            tools.append(tool)
    
    if skipped:
        logger.info(f"Tools: {len(tools)} active, {skipped} skipped (no connected provider)")
    return tools
