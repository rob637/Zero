"""
Telic ReAct Agent & Session Routes

Handles chat, streaming, session management, and approval flows.
"""
import asyncio
import json
import os
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

import server_state as ss
from server_state import ReactRequest, ReactApproveRequest, get_intelligence_hub
from react_agent import Step, StepStatus, AgentState
from src.control.action_history import ActionStatus
import sessions as session_store

router = APIRouter()


@router.post("/react/chat")
async def react_chat(req: ReactRequest):
    """
    Main chat endpoint - continues the current session.
    
    Unlike before, this ALWAYS continues the same conversation session.
    Use /react/new to start a fresh conversation.
    """
    session = ss.get_user_session(req.session_id)
    
    agent = await ss.get_session_agent(session)
    if not agent:
        return JSONResponse({
            "error": "No API key configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY.",
            "steps": [],
            "pending_approval": None,
            "is_complete": True,
            "response": None,
        })
    
    try:
        print(f"[SESSION] User: {req.message[:80]}...")
        print(f"[SESSION] Conversation history: {len(session.messages)} messages")
        
        # Build context from conversation history for the agent
        if session.messages:
            # Summarize recent conversation for context
            context_lines = []
            for m in session.messages[-10:]:  # Last 10 messages
                role = 'User' if m['role'] == 'user' else 'Assistant'
                content = m['content'][:300] + "..." if len(m['content']) > 300 else m['content']
                context_lines.append(f"{role}: {content}")
            context_summary = "\n".join(context_lines)
            
            full_message = f"""[CONVERSATION CONTEXT - This is a continuation of an ongoing conversation]
Previous messages in this session:
{context_summary}

[CURRENT USER MESSAGE]
{req.message}

Remember: References like "the first one", "send it to him", "the information above" refer to the context above."""
        else:
            full_message = req.message
        
        # Run the agent with context
        state = await agent.run(full_message)
        session.react_state = state
        
        # Record in session history
        session.messages.append({"role": "user", "content": req.message})
        if state.final_response:
            session.messages.append({"role": "assistant", "content": state.final_response})
        
        # Auto-save session
        session.auto_save()
        
        # Log what happened
        for step in state.steps:
            status = "✓" if step.status == StepStatus.COMPLETED else "⏸" if step.status == StepStatus.PENDING_APPROVAL else "✗"
            print(f"[SESSION] {status} {step.tool_call.name}")
        
        if state.pending_approval:
            print(f"[SESSION] Waiting for approval: {state.pending_approval.tool_call.name}")
        
        if state.is_complete:
            print(f"[SESSION] Complete: {state.final_response[:80] if state.final_response else 'No response'}...")
        
        return JSONResponse(ss.state_to_response(state))
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "error": str(e),
            "steps": [],
            "pending_approval": None,
            "is_complete": True,
            "response": f"Error: {str(e)}",
        })


@router.post("/react/chat/stream")
async def react_chat_stream(req: ReactRequest):
    """
    Streaming chat endpoint using Server-Sent Events.
    
    Streams step-by-step progress as the agent works,
    so the UI can show real-time activity instead of waiting.
    """
    import json
    session = ss.get_user_session(req.session_id)

    agent = await ss.get_session_agent(session)
    if not agent:
        async def err():
            yield f"data: {json.dumps({'event': 'error', 'message': 'No API key configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY.'})}\n\n"
        return StreamingResponse(err(), media_type="text/event-stream")

    # Build message with conversation context (same logic as react_chat)
    print(f"[STREAM] User: {req.message[:80]}...")
    print(f"[STREAM] Conversation history: {len(session.messages)} messages")

    if session.messages:
        context_lines = []
        for m in session.messages[-10:]:
            role = 'User' if m['role'] == 'user' else 'Assistant'
            content = m['content'][:300] + "..." if len(m['content']) > 300 else m['content']
            context_lines.append(f"{role}: {content}")
        context_summary = "\n".join(context_lines)

        full_message = f"""[CONVERSATION CONTEXT - This is a continuation of an ongoing conversation]
Previous messages in this session:
{context_summary}

[CURRENT USER MESSAGE]
{req.message}

Remember: References like "the first one", "send it to him", "the information above" refer to the context above."""
    else:
        full_message = req.message

    # Gather intelligence context before running agent
    intel_context = ""
    try:
        hub = get_intelligence_hub()
        intel_parts = []

        # Recall relevant facts from semantic memory
        recalled = await hub.recall(req.message, limit=5, min_relevance=0.3)
        if recalled:
            facts_text = "\n".join(f"- {f.content}" for f, _score in recalled[:5])
            intel_parts.append(f"[MEMORY - Things I remember]\n{facts_text}")

        # Check what patterns are expected now
        expected = await hub.whats_expected_now()
        if expected:
            patterns_text = "\n".join(f"- {p['pattern']}: {p['description']}" for p in expected[:3])
            intel_parts.append(f"[PATTERNS - What usually happens now]\n{patterns_text}")

        # Get proactive suggestions
        suggestions = await hub.get_suggestions(max_suggestions=3)
        if suggestions:
            sugg_text = "\n".join(f"- {s.title}: {s.description}" for s in suggestions[:3])
            intel_parts.append(f"[SUGGESTIONS]\n{sugg_text}")

        if intel_parts:
            intel_context = "\n\n".join(intel_parts) + "\n\n"
            print(f"[INTEL] Injected {len(intel_parts)} intelligence sections")
    except Exception as e:
        print(f"[INTEL] Context gathering failed (non-fatal): {e}")

    # Prepend intelligence context to message
    if intel_context:
        full_message = f"[INTELLIGENCE CONTEXT - Use this to provide better, more personalized responses]\n{intel_context}[USER MESSAGE]\n{full_message}"

    # Save original tools in case we filter them (agent is session-persistent)
    _original_tools = agent.tools
    _original_schemas = agent.tool_schemas
    try:
        from intent_router import classify, handle_index_direct, filter_tools as router_filter_tools, IntentType
        intent = await classify(req.message)
        print(f"[ROUTER] {intent}")

        # Fast path: INDEX_DIRECT — answer from local index, no LLM call
        if intent.type == IntentType.INDEX_DIRECT:
            index_result = handle_index_direct(intent, ss._data_index)
            if index_result:
                print(f"[ROUTER] Index direct hit — skipping LLM entirely")
                async def index_direct_generator():
                    yield f"data: {json.dumps({'event': 'thinking'})}\n\n"
                    response_text = index_result["response"]
                    # Update session history
                    session.messages.append({"role": "user", "content": req.message})
                    session.messages.append({"role": "assistant", "content": response_text})
                    session.auto_save()
                    yield f"data: {json.dumps({'event': 'complete', 'data': {'response': response_text, 'steps': [], 'is_complete': True}})}\n\n"
                return StreamingResponse(
                    index_direct_generator(),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )

        # Filtered path: reduce tool set for focused queries
        if intent.type == IntentType.FILTERED and intent.domains:
            original_count = len(agent.tools)
            filtered_list = router_filter_tools(list(agent.tools.values()), intent.domains)
            agent.tools = {t.name: t for t in filtered_list}
            # Rebuild tool schemas for the filtered set
            agent.tool_schemas = agent._build_tool_schemas(filtered_list)
            print(f"[ROUTER] Filtered tools: {original_count} → {len(agent.tools)} (domains: {intent.domains})")
    except Exception as e:
        print(f"[ROUTER] Intent classification failed (falling through to FULL): {e}")

    # Event queue for SSE
    queue = asyncio.Queue()

    async def on_step(step: Step):
        """Push step events to SSE queue and record observations."""
        data = ss.step_to_sse_dict(step)
        data["id"] = step.tool_call.id  # Unique ID for matching start/complete
        if step.status == StepStatus.RUNNING:
            await queue.put({"event": "tool_start", "step": data})
        elif step.status == StepStatus.COMPLETED:
            await queue.put({"event": "tool_complete", "step": data})

            # Record in action history so the Action History panel shows data
            try:
                ss.action_history.record_action(
                    action_type=step.tool_call.name,
                    payload=step.tool_call.params or {},
                    preview={"title": step.tool_call.name, "result": str(step.result)[:200] if step.result else ""},
                    status=ActionStatus.COMPLETED,
                    triggered_by="user",
                    session_id=session.session_id if session else None,
                    request_text=req.message[:200],
                )
            except Exception:
                pass  # Non-fatal

            # Record observation for intelligence learning
            try:
                # Map tool names to preference analyzer keys
                _ACTION_MAP = {
                    "calendar_create": "schedule_meeting",
                    "email_send": "send_email",
                    "email_draft": "send_email",
                    "document_create": "create_document",
                    "document_write": "create_document",
                    "task_create": "create_task",
                    "task_add": "create_task",
                    "web_search": "search_web",
                }
                raw_action = step.tool_call.name
                action = _ACTION_MAP.get(raw_action, raw_action)
                await hub.observe(action, {
                    "params": step.tool_call.params,
                    "result_preview": str(step.result)[:200] if step.result else None,
                    "user_message": req.message[:200],
                })
            except Exception:
                pass  # Non-fatal
        elif step.status == StepStatus.FAILED:
            await queue.put({"event": "tool_failed", "step": data})
            # Record failed actions too
            try:
                ss.action_history.record_action(
                    action_type=step.tool_call.name,
                    payload=step.tool_call.params or {},
                    preview={"title": step.tool_call.name, "error": str(step.error)[:200] if step.error else ""},
                    status=ActionStatus.FAILED,
                    triggered_by="user",
                    session_id=session.session_id if session else None,
                    request_text=req.message[:200],
                )
            except Exception:
                pass
        elif step.status == StepStatus.PENDING_APPROVAL:
            await queue.put({"event": "approval_needed", "step": data})

    async def on_thinking():
        await queue.put({"event": "thinking"})

    # Synchronous token callback — called from background thread,
    # pushes text deltas to the async SSE queue thread-safely.
    loop = asyncio.get_event_loop()

    def on_token(text: str):
        loop.call_soon_threadsafe(queue.put_nowait, {"event": "text_delta", "text": text})

    # Wire callbacks (save previous to restore later)
    prev_on_step = agent.on_step
    prev_on_thinking = getattr(agent, 'on_thinking', None)
    prev_on_token = getattr(agent, 'on_token', None)
    agent.on_step = on_step
    agent.on_thinking = on_thinking
    agent.on_token = on_token

    async def event_generator():
        # Globals in state module

        # Initial thinking event
        yield f"data: {json.dumps({'event': 'thinking'})}\n\n"

        # Generate execution blueprint (plan) before running
        try:
            engine = ss.get_telic_engine()
            # Build a compact list of available capabilities
            available_tools = []
            for prim_name, primitive in engine._primitives.items():
                ops = primitive.get_available_operations()
                connected = primitive.get_connected_providers()
                if connected:
                    for op_name, desc in ops.items():
                        available_tools.append(f"{prim_name}_{op_name}: {desc}")
            
            tools_summary = "\n".join(available_tools[:80])  # Cap for token efficiency
            
            plan_prompt = f"""Given this user request, output a JSON array of the steps you would take.
Each step: {{"tool": "tool_name", "label": "short human description", "service": "primary service icon name"}}
Service icon names: calendar, gmail, outlook, drive, onedrive, contacts, sheets, slides, photos, spotify, slack, github, discord, todoist, teams, onenote, excel, powerpoint, web, file, task, search, weather, news
Only include steps that require tool calls. Keep it to 2-6 steps. Output ONLY the JSON array, no other text.

Available tools:
{tools_summary}

User request: {req.message}"""

            if os.environ.get("ANTHROPIC_API_KEY"):
                import anthropic
                plan_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
                try:
                    plan_response = plan_client.messages.create(
                        model="claude-haiku-4-20250414",
                        max_tokens=300,
                        messages=[{"role": "user", "content": plan_prompt}]
                    )
                except Exception:
                    # Fallback to sonnet if haiku unavailable
                    plan_response = plan_client.messages.create(
                        model="claude-sonnet-4-20250514",
                        max_tokens=300,
                        messages=[{"role": "user", "content": plan_prompt}]
                    )
                plan_text = plan_response.content[0].text.strip()
            else:
                import openai
                plan_client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
                plan_response = plan_client.chat.completions.create(
                    model="gpt-4o-mini",
                    max_tokens=300,
                    messages=[{"role": "user", "content": plan_prompt}]
                )
                plan_text = plan_response.choices[0].message.content.strip()

            # Parse JSON from response (handle markdown code blocks)
            if plan_text.startswith("```"):
                plan_text = plan_text.split("```")[1]
                if plan_text.startswith("json"):
                    plan_text = plan_text[4:]
                plan_text = plan_text.strip()
            
            plan_steps = json.loads(plan_text)
            if isinstance(plan_steps, list) and len(plan_steps) > 0:
                yield f"data: {json.dumps({'event': 'plan', 'steps': plan_steps})}\n\n"
                print(f"[STREAM] Blueprint: {len(plan_steps)} planned steps")
        except Exception as e:
            import traceback
            print(f"[STREAM] Blueprint generation skipped: {e}")
            traceback.print_exc()

        # Run agent as background task
        task = asyncio.create_task(agent.run(full_message))

        try:
            while not task.done():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"

            # Drain remaining queued events
            while not queue.empty():
                event = await queue.get()
                yield f"data: {json.dumps(event)}\n\n"

            # Final state
            state = task.result()
            session.react_state = state

            # Update session history
            session.messages.append({"role": "user", "content": req.message})
            if state.final_response:
                session.messages.append({"role": "assistant", "content": state.final_response})

            # Auto-save session
            session.auto_save()

            # Intelligence: Remember facts from this interaction
            try:
                completed_tools = [s.tool_call.name for s in state.steps if s.status == StepStatus.COMPLETED]
                if completed_tools:
                    await hub.on_event("task_completed", {
                        "user_message": req.message,
                        "tools_used": completed_tools,
                        "success": state.is_complete,
                    })
            except Exception:
                pass  # Non-fatal

            # Log
            for s in state.steps:
                icon = "✓" if s.status == StepStatus.COMPLETED else "⏸" if s.status == StepStatus.PENDING_APPROVAL else "✗"
                print(f"[STREAM] {icon} {s.tool_call.name}")
            if state.is_complete:
                print(f"[STREAM] Complete: {state.final_response[:80] if state.final_response else 'No response'}...")

            yield f"data: {json.dumps({'event': 'complete', 'data': ss.state_to_response(state)})}\n\n"

        except (Exception, asyncio.CancelledError) as e:
            import traceback
            traceback.print_exc()
            error_msg = "Request was cancelled" if isinstance(e, asyncio.CancelledError) else str(e)
            yield f"data: {json.dumps({'event': 'error', 'message': error_msg})}\n\n"
        finally:
            agent.on_step = prev_on_step
            agent.on_thinking = prev_on_thinking
            agent.on_token = prev_on_token
            # Restore full tool set if it was filtered for this request
            agent.tools = _original_tools
            agent.tool_schemas = _original_schemas

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@router.post("/react/new")
async def react_new_conversation():
    """Start a fresh conversation - saves current session, then clears."""
    session = ss.new_user_session()
    print(f"[SESSION] Started new conversation: {session.session_id}")
    return JSONResponse({"status": "ok", "message": "New conversation started", "session_id": session.session_id})


@router.post("/react/approve")
async def react_approve(req: ReactApproveRequest):
    """
    Approve or reject a pending action.
    
    After approval, the agent continues executing.
    """
    session = ss.get_user_session(req.session_id)
    
    agent = await ss.get_session_agent(session)
    if not agent or not session.react_state:
        return JSONResponse({
            "error": "No pending action",
            "steps": [],
            "pending_approval": None,
            "is_complete": True,
            "response": None,
        })
    
    try:
        action = "Approved" if req.approved else "Rejected"
        if session.react_state.pending_approval:
            print(f"[SESSION] {action}: {session.react_state.pending_approval.tool_call.name}")
        
        # Continue with approval decision
        state = await agent.continue_with_approval(req.approved)
        session.react_state = state
        
        # Record result in session history
        if state.final_response:
            session.messages.append({"role": "assistant", "content": state.final_response})
        
        return JSONResponse(ss.state_to_response(state))
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "error": str(e),
            "steps": [],
            "pending_approval": None,
            "is_complete": True,
            "response": f"Error: {str(e)}",
        })


@router.post("/react/approve/stream")
async def react_approve_stream(req: ReactApproveRequest):
    """
    Streaming version of approve. Returns SSE events as agent continues
    executing after approval, so the UI can show real-time tool progress.
    """
    import json
    session = ss.get_user_session(req.session_id)

    agent = await ss.get_session_agent(session)
    if not agent or not session.react_state:
        async def err():
            yield f"data: {json.dumps({'event': 'error', 'message': 'No pending action'})}\n\n"
        return StreamingResponse(err(), media_type="text/event-stream")

    action = "Approved" if req.approved else "Rejected"
    if session.react_state.pending_approval:
        print(f"[STREAM-APPROVE] {action}: {session.react_state.pending_approval.tool_call.name}")

    if not req.approved:
        # Rejection is instant — no streaming needed
        async def reject_stream():
            state = await agent.continue_with_approval(False)
            session.react_state = state
            yield f"data: {json.dumps({'event': 'complete', 'data': ss.state_to_response(state)})}\n\n"
        return StreamingResponse(reject_stream(), media_type="text/event-stream")

    # Approved — stream the continuation
    queue = asyncio.Queue()

    async def on_step(step):
        data = ss.step_to_sse_dict(step)
        data["id"] = step.tool_call.id
        if step.status == StepStatus.RUNNING:
            await queue.put({"event": "tool_start", "step": data})
        elif step.status == StepStatus.COMPLETED:
            await queue.put({"event": "tool_complete", "step": data})
        elif step.status == StepStatus.FAILED:
            await queue.put({"event": "tool_failed", "step": data})
        elif step.status == StepStatus.PENDING_APPROVAL:
            await queue.put({"event": "approval_needed", "step": data})

    async def on_thinking():
        await queue.put({"event": "thinking"})

    prev_on_step = agent.on_step
    prev_on_thinking = getattr(agent, 'on_thinking', None)
    agent.on_step = on_step
    agent.on_thinking = on_thinking

    async def event_generator():
        yield f"data: {json.dumps({'event': 'thinking'})}\n\n"
        task = asyncio.create_task(agent.continue_with_approval(True))
        try:
            while not task.done():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
            while not queue.empty():
                event = await queue.get()
                yield f"data: {json.dumps(event)}\n\n"
            state = task.result()
            session.react_state = state
            if state.final_response:
                session.messages.append({"role": "assistant", "content": state.final_response})
            session.auto_save()
            yield f"data: {json.dumps({'event': 'complete', 'data': ss.state_to_response(state)})}\n\n"
        except (Exception, asyncio.CancelledError) as e:
            import traceback
            traceback.print_exc()
            error_msg = "Request was cancelled" if isinstance(e, asyncio.CancelledError) else str(e)
            yield f"data: {json.dumps({'event': 'error', 'message': error_msg})}\n\n"
        finally:
            agent.on_step = prev_on_step
            agent.on_thinking = prev_on_thinking

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# /react/continue is now deprecated - /react/chat handles all messages with session context
@router.post("/react/continue")
async def react_continue(req: ReactRequest):
    """
    DEPRECATED: Use /react/chat instead.
    Redirects to /react/chat for backwards compatibility.
    """
    return await react_chat(req)


# ==========================================================
# Session History - save, list, load, delete past conversations
# ==========================================================


@router.get("/sessions")
async def list_sessions(limit: int = 50):
    """List all saved sessions, most recent first."""
    return JSONResponse(session_store.list_sessions(limit))


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """Get a saved session with its full message history."""
    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return JSONResponse(session)


@router.post("/sessions/{session_id}/load")
async def load_session(session_id: str):
    """Load a saved session as the active conversation."""
    # Save current session first if it has messages
    current = ss.get_user_session()
    if current.messages:
        current.auto_save()
    
    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    us = ss.get_user_session(session_id)
    us.messages = session["messages"]
    us.agent = None  # Force agent recreation to pick up new context
    us.react_state = None
    ss._current_session_id = session_id
    print(f"[SESSION] Loaded session {session_id} with {len(us.messages)} messages")
    return JSONResponse({"status": "ok", "session": session})


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a saved session."""
    deleted = session_store.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return JSONResponse({"status": "ok"})

