"""
ReAct Agent - Native function calling orchestration.

This replaces the JSON-plan approach with direct tool calling.
The AI calls tools one at a time, sees results, and decides next steps.
"""

import json
import asyncio
import logging
from dataclasses import dataclass, field, asdict, is_dataclass
from typing import Any, Callable, Dict, List, Optional, Awaitable
from enum import Enum

logger = logging.getLogger(__name__)


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
    ):
        self.llm_client = llm_client
        self.tools = {t.name: t for t in tools}
        self.tool_schemas = self._build_tool_schemas(tools)
        self.system_prompt = system_prompt or self._default_system_prompt()
        self.on_step = on_step  # Callback when step starts/completes
        self.on_thinking = on_thinking  # Callback before each LLM call
        self.state = AgentState()
    
    def _default_system_prompt(self) -> str:
        return """You are a helpful AI assistant that can perform actions on the user's behalf.

Use the available tools to accomplish what the user asks. You can call multiple tools in parallel when the calls are independent of each other.

IMPORTANT BEHAVIORS:
- If a search returns multiple results, ASK the user which one they want before proceeding
- If information is unclear or missing, ASK before guessing
- Show computed results (calculations, schedules, etc.) to the user before sending/creating
- Be conversational - explain what you're doing and what you found

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
        self.state.messages = [
            {"role": "user", "content": user_message}
        ]
        
        return await self._execute_loop()
    
    async def continue_with_approval(self, approved: bool) -> AgentState:
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
            # Execute the approved tool
            result = await self._execute_tool(step.tool_call)
            step.result = serialize(result)
            step.status = StepStatus.COMPLETED
            
            # Prepare truncated result
            result_str = json.dumps(step.result) if not isinstance(step.result, str) else step.result
            MAX_RESULT_LEN = 2000
            if len(result_str) > MAX_RESULT_LEN:
                result_str = result_str[:MAX_RESULT_LEN] + f"\n... [truncated, {len(result_str)} chars total]"
            
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
        
        self.state.messages.append({"role": "user", "content": user_input})
        return await self._execute_loop()
    
    async def _execute_loop(self) -> AgentState:
        """Main execution loop."""
        max_iterations = 40  # Safety limit
        
        for _ in range(max_iterations):
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
                return self.state
            
            # IMPORTANT: Add assistant's response (with tool_use) to messages FIRST
            # Anthropic requires tool_result to follow the tool_use in messages
            self.state.messages.append({
                "role": "assistant",
                "content": [{"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.params} for tc in tool_calls]
            })
            
            # Collect all tool results to add as ONE user message
            tool_results = []
            
            # Execute tool calls
            for tc in tool_calls:
                step = Step(tool_call=tc)
                self.state.steps.append(step)
                
                tool = self.tools.get(tc.name)
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
                
                # Check if approval needed - for now, add placeholder and pause
                if tool.side_effect:
                    step.status = StepStatus.PENDING_APPROVAL
                    step.requires_approval = True
                    self.state.pending_approval = step
                    # Add results collected so far, mark remaining as pending
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": "[Awaiting user approval]"
                    })
                    # Store remaining tools to handle after approval
                    if self.on_step:
                        await self.on_step(step)
                    # Add all collected results as ONE message
                    self.state.messages.append({"role": "user", "content": tool_results})
                    return self.state  # Pause for approval
                
                # Execute non-side-effect tool immediately
                if self.on_step:
                    await self.on_step(step)
                
                try:
                    result = await self._execute_tool(tc)
                    step.result = serialize(result)  # Convert to plain data
                    step.status = StepStatus.COMPLETED
                    
                    # Truncate long results to keep context lean
                    result_str = json.dumps(step.result) if not isinstance(step.result, str) else step.result
                    MAX_RESULT_LEN = 2000
                    if len(result_str) > MAX_RESULT_LEN:
                        result_str = result_str[:MAX_RESULT_LEN] + f"\n... [truncated, {len(result_str)} chars total]"
                    
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": result_str
                    })
                except Exception as e:
                    step.status = StepStatus.FAILED
                    step.error = str(e)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": f"Error: {str(e)}",
                        "is_error": True
                    })
                
                if self.on_step:
                    await self.on_step(step)
            
            # Add ALL tool results as ONE user message
            if tool_results:
                self.state.messages.append({"role": "user", "content": tool_results})
        
        # Hit iteration limit
        self.state.is_complete = True
        self.state.final_response = "I've reached the maximum number of steps. Please try a simpler request."
        return self.state
    
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
        """Call Anthropic's Claude API."""
        import time as _time
        _t0 = _time.perf_counter()
        # Calculate context size for logging
        _ctx_size = sum(len(json.dumps(m)) for m in self.state.messages)
        response = await asyncio.to_thread(
            self.llm_client.messages.create,
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=self.system_prompt,
            tools=self.tool_schemas,
            messages=self.state.messages
        )
        _elapsed = _time.perf_counter() - _t0
        logger.info(f"LLM call: {_elapsed:.1f}s | context: {_ctx_size:,} chars | usage: {response.usage}")
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
        
        response = await asyncio.to_thread(
            self.llm_client.chat.completions.create,
            model="gpt-4o",
            messages=messages,
            tools=openai_tools if openai_tools else None
        )
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
        """Execute a tool call."""
        tool = self.tools.get(tool_call.name)
        if not tool:
            raise ValueError(f"Unknown tool: {tool_call.name}")
        
        return await tool.handler(tool_call.params)


def primitives_to_tools(primitives: Dict[str, Any]) -> List[Tool]:
    """
    Convert Apex primitives to ReAct tools.
    
    Each primitive operation becomes a tool.
    """
    tools = []
    
    for prim_name, primitive in primitives.items():
        available_ops = primitive.get_available_operations()
        schema = primitive.get_param_schema() or {}
        
        for op_name, description in available_ops.items():
            # Determine if this operation has side effects
            side_effect_keywords = ["send", "create", "write", "delete", "move", "update", "post", "remove"]
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
                description=description,
                parameters={"properties": properties, "required": required},
                handler=make_handler(primitive, op_name),
                side_effect=has_side_effect
            )
            
            tools.append(tool)
    
    return tools
