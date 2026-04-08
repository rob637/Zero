"""
ReAct Agent - Native function calling orchestration.

This replaces the JSON-plan approach with direct tool calling.
The AI calls tools one at a time, sees results, and decides next steps.
"""

import json
import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Awaitable
from enum import Enum


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
    ):
        self.llm_client = llm_client
        self.tools = {t.name: t for t in tools}
        self.tool_schemas = self._build_tool_schemas(tools)
        self.system_prompt = system_prompt or self._default_system_prompt()
        self.on_step = on_step  # Callback when step starts/completes
        self.state = AgentState()
    
    def _default_system_prompt(self) -> str:
        return """You are a helpful AI assistant that can perform actions on the user's behalf.

Use the available tools to accomplish what the user asks. Call tools ONE AT A TIME, observe the result, then decide what to do next.

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
        
        step = self.state.pending_approval
        self.state.pending_approval = None
        
        if approved:
            # Execute the approved tool
            result = await self._execute_tool(step.tool_call)
            step.result = result
            step.status = StepStatus.COMPLETED
            
            # Add result to messages
            self.state.messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": step.tool_call.id,
                    "content": json.dumps(result) if not isinstance(result, str) else result
                }]
            })
        else:
            step.status = StepStatus.CANCELLED
            step.error = "Cancelled by user"
            
            # Tell AI it was cancelled
            self.state.messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": step.tool_call.id,
                    "content": "Action cancelled by user. Ask if they want to do something else.",
                    "is_error": True
                }]
            })
        
        if self.on_step:
            await self.on_step(step)
        
        return await self._execute_loop()
    
    async def continue_with_input(self, user_input: str) -> AgentState:
        """Continue after user provides additional input."""
        self.state.messages.append({"role": "user", "content": user_input})
        return await self._execute_loop()
    
    async def _execute_loop(self) -> AgentState:
        """Main execution loop."""
        max_iterations = 20  # Safety limit
        
        for _ in range(max_iterations):
            # Call LLM with tools
            response = await self._call_llm()
            
            # Check if AI is done (no tool calls, just text)
            if response.stop_reason == "end_turn":
                self.state.is_complete = True
                self.state.final_response = self._extract_text(response)
                return self.state
            
            # Process tool calls
            tool_calls = self._extract_tool_calls(response)
            
            if not tool_calls:
                # No tool calls and not end_turn - extract any text and finish
                self.state.is_complete = True
                self.state.final_response = self._extract_text(response)
                return self.state
            
            # Execute tool calls (one at a time for side-effect awareness)
            for tc in tool_calls:
                step = Step(tool_call=tc)
                self.state.steps.append(step)
                
                tool = self.tools.get(tc.name)
                if not tool:
                    step.status = StepStatus.FAILED
                    step.error = f"Unknown tool: {tc.name}"
                    self.state.messages.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": tc.id,
                            "content": f"Error: Unknown tool '{tc.name}'",
                            "is_error": True
                        }]
                    })
                    if self.on_step:
                        await self.on_step(step)
                    continue
                
                # Check if approval needed
                if tool.side_effect:
                    step.status = StepStatus.PENDING_APPROVAL
                    step.requires_approval = True
                    self.state.pending_approval = step
                    if self.on_step:
                        await self.on_step(step)
                    return self.state  # Pause for approval
                
                # Execute non-side-effect tool immediately
                if self.on_step:
                    await self.on_step(step)
                
                try:
                    result = await self._execute_tool(tc)
                    step.result = result
                    step.status = StepStatus.COMPLETED
                    
                    self.state.messages.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": tc.id,
                            "content": json.dumps(result) if not isinstance(result, str) else result
                        }]
                    })
                except Exception as e:
                    step.status = StepStatus.FAILED
                    step.error = str(e)
                    self.state.messages.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": tc.id,
                            "content": f"Error: {str(e)}",
                            "is_error": True
                        }]
                    })
                
                if self.on_step:
                    await self.on_step(step)
        
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
        response = await asyncio.to_thread(
            self.llm_client.messages.create,
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=self.system_prompt,
            tools=self.tool_schemas,
            messages=self.state.messages
        )
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
                name=f"{prim_name.lower()}.{op_name}",
                description=description,
                parameters={"properties": properties, "required": required},
                handler=make_handler(primitive, op_name),
                side_effect=has_side_effect
            )
            
            tools.append(tool)
    
    return tools
