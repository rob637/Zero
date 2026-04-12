"""
Telic ReAct Agent & Session Routes

Handles chat, streaming, session management, and approval flows.
"""
import asyncio
import json
import os
import logging
import time as _time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

import server_state as ss
from server_state import ReactRequest, ReactApproveRequest, get_intelligence_hub
from react_agent import Step, StepStatus, AgentState
from src.control.action_history import ActionStatus
import sessions as session_store
from orchestration import (
    ArtifactLedger,
    OrchestrationEvalStore,
    OrchestrationCapabilityGraph,
    QualityGateThresholds,
    ExecutionPolicy,
    InvalidTransitionError,
    OrchestrationStateMachine,
    OutcomeContract,
    check_quality_gate,
    check_side_effect_preconditions,
    evaluate_runtime_snapshot,
    verify_outcome,
    WorkflowPhase,
    WorkflowState,
    extract_artifact_candidates,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default

# ---------------------------------------------------------------------------
# Blueprint cache — same request pattern → same plan, skip LLM call
# ---------------------------------------------------------------------------
_blueprint_cache: Dict[str, tuple] = {}  # key → (plan_steps, timestamp)
_BLUEPRINT_TTL = 300  # 5 minutes
_ENABLE_BLUEPRINT = os.environ.get("TELIC_ENABLE_BLUEPRINT", "0").strip().lower() in {
    "1", "true", "yes", "on"
}
_INTEL_SECTION_TIMEOUT_S = _env_float("TELIC_INTEL_SECTION_TIMEOUT_S", 2.5)
_INTENT_CLASSIFY_TIMEOUT_S = _env_float("TELIC_INTENT_CLASSIFY_TIMEOUT_S", 3.0)
_STREAM_AGENT_TIMEOUT_S = _env_float("TELIC_STREAM_AGENT_TIMEOUT_S", 180.0)
_RESPONSE_BUDGET_MS = _env_float("TELIC_RESPONSE_BUDGET_MS", 18000.0)
_TIGHT_INTEL_TIMEOUT_S = _env_float("TELIC_TIGHT_INTEL_TIMEOUT_S", 1.2)
_TIGHT_MAX_OUTPUT_TOKENS = _env_int("TELIC_TIGHT_MAX_OUTPUT_TOKENS", 900)
_TIGHT_TOOL_TIMEOUT_SECONDS = _env_float("TELIC_TIGHT_TOOL_TIMEOUT_SECONDS", 25.0)

_artifact_ledger = ArtifactLedger(Path(__file__).resolve().parent.parent / "sqlite" / "orchestration.db")
_eval_store = OrchestrationEvalStore(Path(__file__).resolve().parent.parent / "sqlite" / "orchestration.db")
_session_workflow_ids: Dict[str, str] = {}
_session_workflows: Dict[str, WorkflowState] = {}


def _session_key(session_id: Optional[str]) -> str:
    return session_id or "default"


def _get_or_create_workflow_state(
    session_id: Optional[str],
    user_message: str,
    *,
    phase: WorkflowPhase = WorkflowPhase.INIT,
) -> WorkflowState:
    key = _session_key(session_id)
    existing = _session_workflows.get(key)
    if existing is not None:
        return existing

    workflow_id = _session_workflow_ids.get(key) or str(uuid.uuid4())
    _session_workflow_ids[key] = workflow_id
    state = WorkflowState(
        workflow_id=workflow_id,
        session_id=key,
        phase=phase,
        outcome=_build_outcome_contract(user_message),
        policy=ExecutionPolicy(mode=os.environ.get("TELIC_ORCH_MODE", "balanced")),
    )
    _session_workflows[key] = state
    return state


def _build_outcome_contract(user_message: str) -> OutcomeContract:
    msg = user_message.lower()
    artifact_hints: List[str] = []
    side_effect_hints: List[str] = []
    if any(k in msg for k in ["file", "document", "schedule", "report", "spreadsheet", "attachment"]):
        artifact_hints.append("artifact_output")
    if any(k in msg for k in ["email", "send", "forward", "reply", "message"]):
        side_effect_hints.append("communication_send")
    return OutcomeContract(
        user_request=user_message,
        required_artifact_hints=artifact_hints,
        required_side_effect_hints=side_effect_hints,
        constraints={"must_preserve_user_intent": True},
    )


def _build_workflow_meta(
    state: WorkflowState,
    capability_graph: OrchestrationCapabilityGraph,
    verification: Optional[Dict[str, Any]] = None,
    evaluation: Optional[Dict[str, Any]] = None,
    gate: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    artifacts = _artifact_ledger.list_artifacts(state.workflow_id, limit=20)
    return {
        "state": state.to_dict(),
        "capabilities": capability_graph.summary().to_dict(),
        "artifact_count": len(artifacts),
        "artifacts": [
            {
                "artifact_id": a.artifact_id,
                "artifact_type": a.artifact_type,
                "uri": a.uri,
                "tool_name": a.tool_name,
                "created_at": a.created_at,
            }
            for a in artifacts
        ],
        "verification": verification,
        "evaluation": evaluation,
        "quality_gate": gate,
    }


def _record_eval_run(
    *,
    workflow_state: WorkflowState,
    request_text: str,
    evaluation: Dict[str, Any],
    verification: Dict[str, Any],
    gate: Dict[str, Any],
    orchestration_mode: str,
) -> None:
    try:
        _eval_store.record_run(
            workflow_id=workflow_state.workflow_id,
            session_id=workflow_state.session_id,
            request_text=request_text,
            evaluation=evaluation,
            verification=verification,
            gate=gate,
            orchestration_mode=orchestration_mode,
        )
    except Exception as e:
        logger.warning(f"Failed to persist orchestration evaluation: {e}")


def _resolve_orchestration_mode(requested_mode: str) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
    mode = (requested_mode or "").strip().lower()
    if mode in {"strict", "balanced", "fast"}:
        return mode, None
    if mode == "auto":
        try:
            rec = _eval_store.recommend_mode(lookback=200, window=20)
            return rec.mode, {
                "requested": "auto",
                "recommended": rec.mode,
                "reasons": rec.reasons,
                "summary": rec.summary,
                "trend": rec.trend,
            }
        except Exception as e:
            logger.warning(f"Failed to compute orchestration auto mode: {e}")
            return "balanced", {
                "requested": "auto",
                "recommended": "balanced",
                "reasons": ["recommendation_failed_fallback_balanced"],
            }
    return None, None


def _effective_orchestration_mode(applied_mode: Optional[str]) -> str:
    return (applied_mode or os.environ.get("TELIC_ORCH_MODE") or "balanced").strip().lower()


def _mode_rank(mode: str) -> int:
    return {"fast": 0, "balanced": 1, "strict": 2}.get((mode or "balanced").strip().lower(), 1)


def _health_mode_recommendation(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    total = max(1, int(snapshot.get("total_sources", 0) or 0))
    stale = int(snapshot.get("stale_sources", 0) or 0)
    degraded = len(snapshot.get("degraded_sources") or [])
    stale_ratio = stale / total
    degraded_ratio = degraded / total

    reasons: List[str] = []
    if degraded_ratio >= 0.35:
        reasons.append("connector_error_ratio_high")
    if stale_ratio >= 0.55:
        reasons.append("freshness_staleness_ratio_high")
    if reasons:
        return {
            "mode": "strict",
            "reasons": reasons,
            "stale_ratio": round(stale_ratio, 3),
            "degraded_ratio": round(degraded_ratio, 3),
        }

    reasons = []
    if degraded_ratio == 0.0:
        reasons.append("no_degraded_connectors")
    if stale_ratio <= 0.15:
        reasons.append("freshness_within_budget")
    if len(reasons) == 2:
        return {
            "mode": "fast",
            "reasons": reasons,
            "stale_ratio": round(stale_ratio, 3),
            "degraded_ratio": round(degraded_ratio, 3),
        }

    return {
        "mode": "balanced",
        "reasons": ["mixed_reliability_signals"],
        "stale_ratio": round(stale_ratio, 3),
        "degraded_ratio": round(degraded_ratio, 3),
    }


def _semantic_backend() -> str:
    ss_instance = getattr(ss, "_semantic_search", None)
    if not ss_instance:
        return "none"
    try:
        stats = getattr(ss_instance, "stats", {}) or {}
        return str(stats.get("backend") or "none").strip().lower()
    except Exception:
        return "none"


def _confidence_from_runtime(
    *,
    data_health: Dict[str, Any],
    evaluation: Optional[Dict[str, Any]],
    wall_time_ms: float,
) -> Dict[str, Any]:
    score = 0.93
    total = max(1, int(data_health.get("total_sources", 0) or 0))
    stale_ratio = (int(data_health.get("stale_sources", 0) or 0) / total)
    degraded_ratio = (len(data_health.get("degraded_sources") or []) / total)

    score -= min(0.32, stale_ratio * 0.20)
    score -= min(0.38, degraded_ratio * 0.35)

    backend = _semantic_backend()
    if backend == "hash":
        score -= 0.12
    elif backend in {"charhash", "subword"}:
        score -= 0.06
    elif backend == "openai":
        score -= 0.02

    if wall_time_ms > _RESPONSE_BUDGET_MS:
        over = (wall_time_ms - _RESPONSE_BUDGET_MS) / max(_RESPONSE_BUDGET_MS, 1.0)
        score -= min(0.12, over * 0.08)

    if evaluation:
        eval_score = float(evaluation.get("score", 0.0) or 0.0)
        score += max(-0.05, min(0.05, (eval_score - 0.8) * 0.25))

    score = max(0.05, min(0.99, score))
    level = "high" if score >= 0.90 else "medium" if score >= 0.75 else "low"

    reasons: List[str] = []
    if degraded_ratio > 0.0:
        reasons.append("connector_degradation_present")
    if stale_ratio > 0.25:
        reasons.append("source_freshness_mixed")
    if backend in {"hash", "charhash", "subword"}:
        reasons.append(f"semantic_backend_{backend}")
    if wall_time_ms > _RESPONSE_BUDGET_MS:
        reasons.append("latency_budget_exceeded")
    if not reasons:
        reasons.append("runtime_signals_healthy")

    return {
        "score": round(score, 3),
        "level": level,
        "reasons": reasons,
        "response_budget_ms": int(_RESPONSE_BUDGET_MS),
    }


def _build_data_health_snapshot() -> Dict[str, Any]:
    """Build a lightweight freshness/health snapshot from sync state."""
    snapshot: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_sources": 0,
        "fresh_sources": 0,
        "stale_sources": 0,
        "degraded_sources": [],
        "freshness": {},
        "freshest_age_seconds": None,
        "stalest_age_seconds": None,
    }

    index = getattr(ss, "_data_index", None)
    if not index:
        return snapshot

    try:
        states = index.all_sync_states()
    except Exception:
        return snapshot

    now = datetime.now(timezone.utc)
    ages: List[int] = []
    degraded_sources = set()
    stale_count = 0
    fresh_count = 0

    for state in states:
        age_s: Optional[int] = None
        if state.last_sync:
            age_s = max(0, int((now - state.last_sync).total_seconds()))
            ages.append(age_s)

        status_val = getattr(state.status, "value", str(state.status))
        if status_val == "error":
            degraded_sources.add(state.source)

        if age_s is not None:
            if age_s <= 600 and status_val in {"idle", "syncing"}:
                fresh_count += 1
            if age_s > 3600:
                stale_count += 1

        snapshot["freshness"][state.source] = {
            "status": status_val,
            "last_sync": state.last_sync.isoformat() if state.last_sync else None,
            "age_seconds": age_s,
            "item_count": state.item_count,
        }

    sync_engine = getattr(ss, "_sync_engine", None)
    if sync_engine is not None:
        failures = getattr(sync_engine, "_consecutive_failures", {}) or {}
        for source, fail_count in failures.items():
            if fail_count >= 3:
                degraded_sources.add(source)

    snapshot["total_sources"] = len(states)
    snapshot["fresh_sources"] = fresh_count
    snapshot["stale_sources"] = stale_count
    snapshot["degraded_sources"] = sorted(degraded_sources)
    if ages:
        snapshot["freshest_age_seconds"] = min(ages)
        snapshot["stalest_age_seconds"] = max(ages)

    return snapshot


@router.post("/react/chat")
async def react_chat(req: ReactRequest):
    """
    Main chat endpoint - continues the current session.
    
    Unlike before, this ALWAYS continues the same conversation session.
    Use /react/new to start a fresh conversation.
    """
    session = ss.get_user_session(req.session_id)
    prev_orch_mode = os.environ.get("TELIC_ORCH_MODE")
    applied_orch_mode, orch_policy_recommendation = _resolve_orchestration_mode(req.orchestration_mode or "")
    if applied_orch_mode:
        os.environ["TELIC_ORCH_MODE"] = applied_orch_mode
    
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
        logger.info(f"User: {req.message[:80]}...")
        logger.info(f"Conversation history: {len(session.messages)} messages")
        
        # Build context from conversation history for the agent
        if session.messages:
            # Summarize recent conversation for context
            context_lines = []
            for m in session.messages[-6:]:  # Last 6 messages
                role = 'User' if m['role'] == 'user' else 'Assistant'
                content = m['content'][:180] + "..." if len(m['content']) > 180 else m['content']
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
            logger.info(f"{status} {step.tool_call.name}")
        
        if state.pending_approval:
            logger.info(f"Waiting for approval: {state.pending_approval.tool_call.name}")
        
        if state.is_complete:
            logger.info(f"Complete: {state.final_response[:80] if state.final_response else 'No response'}...")

        payload = ss.state_to_response(state)
        payload["meta"] = {
            "data_health": _build_data_health_snapshot(),
            "policy_recommendation": orch_policy_recommendation,
            "applied_orchestration_mode": applied_orch_mode,
        }
        return JSONResponse(payload)
        
    except Exception as e:
        logger.exception("Request error")
        if session and session.react_state:
            payload = ss.state_to_response(session.react_state)
            payload["error"] = str(e)
            payload["response"] = payload.get("response") or f"Error: {str(e)}"
            return JSONResponse(payload)
        return JSONResponse({
            "error": str(e),
            "steps": [],
            "pending_approval": None,
            "is_complete": True,
            "response": f"Error: {str(e)}",
        })
    finally:
        if applied_orch_mode:
            if prev_orch_mode is None:
                os.environ.pop("TELIC_ORCH_MODE", None)
            else:
                os.environ["TELIC_ORCH_MODE"] = prev_orch_mode


@router.post("/react/chat/stream")
async def react_chat_stream(req: ReactRequest):
    """
    Streaming chat endpoint using Server-Sent Events.
    
    Streams step-by-step progress as the agent works,
    so the UI can show real-time activity instead of waiting.
    """
    import json
    request_t0 = _time.perf_counter()
    prev_orch_mode = os.environ.get("TELIC_ORCH_MODE")
    orch_mode_mutated = False
    runtime_orch_mode: Optional[str] = None
    applied_orch_mode, orch_policy_recommendation = _resolve_orchestration_mode(req.orchestration_mode or "")
    if applied_orch_mode:
        os.environ["TELIC_ORCH_MODE"] = applied_orch_mode
        runtime_orch_mode = applied_orch_mode
        orch_mode_mutated = True
    timing: Dict[str, float] = {
        "classify_ms": 0.0,
        "blueprint_ms": 0.0,
        "agent_run_ms": 0.0,
    }
    latency_budget: Dict[str, Any] = {
        "target_ms": int(_RESPONSE_BUDGET_MS),
        "pressure": False,
        "intel_timeout_s": _INTEL_SECTION_TIMEOUT_S,
    }
    agent_knob_restore: Dict[str, Any] = {}
    tool_start_times: Dict[str, float] = {}
    tool_durations: Dict[str, List[float]] = {}

    workflow_state = _get_or_create_workflow_state(
        req.session_id,
        req.message,
        phase=WorkflowPhase.INIT,
    )
    # New user request defines a new orchestration objective for this session.
    workflow_state.outcome = _build_outcome_contract(req.message)
    workflow_state.phase = WorkflowPhase.INIT
    workflow_state.llm_calls = 0
    workflow_state.tool_calls = 0
    workflow_state.last_error = None
    workflow_state.touch()
    workflow_sm = OrchestrationStateMachine(workflow_state)
    _session_workflow_ids[workflow_state.session_id] = workflow_state.workflow_id
    workflow_sm.transition(WorkflowPhase.PLANNING)

    session = ss.get_user_session(req.session_id)

    agent = await ss.get_session_agent(session)
    if not agent:
        async def err():
            yield f"data: {json.dumps({'event': 'error', 'message': 'No API key configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY.'})}\n\n"
        return StreamingResponse(err(), media_type="text/event-stream")

    # Build message with conversation context (same logic as react_chat)
    logger.info(f"User: {req.message[:80]}...")
    logger.info(f"Conversation history: {len(session.messages)} messages")

    if session.messages:
        context_lines = []
        for m in session.messages[-6:]:
            role = 'User' if m['role'] == 'user' else 'Assistant'
            content = m['content'][:180] + "..." if len(m['content']) > 180 else m['content']
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

    data_health_snapshot = _build_data_health_snapshot()
    health_mode = _health_mode_recommendation(data_health_snapshot)
    explicit_mode = (req.orchestration_mode or "").strip().lower() in {"strict", "balanced", "fast"}
    base_mode = _effective_orchestration_mode(applied_orch_mode)
    selected_mode = base_mode
    if not explicit_mode:
        if applied_orch_mode is None:
            selected_mode = health_mode["mode"]
        else:
            selected_mode = health_mode["mode"]
            if _mode_rank(applied_orch_mode) > _mode_rank(selected_mode):
                selected_mode = applied_orch_mode

    if selected_mode != (os.environ.get("TELIC_ORCH_MODE") or "balanced").strip().lower():
        os.environ["TELIC_ORCH_MODE"] = selected_mode
        orch_mode_mutated = True
    runtime_orch_mode = selected_mode

    if orch_policy_recommendation is None:
        orch_policy_recommendation = {
            "requested": req.orchestration_mode or "runtime",
            "recommended": selected_mode,
            "reasons": list(health_mode.get("reasons") or []),
        }
    else:
        merged_reasons = list(orch_policy_recommendation.get("reasons") or [])
        for reason in (health_mode.get("reasons") or []):
            if reason not in merged_reasons:
                merged_reasons.append(reason)
        orch_policy_recommendation["reasons"] = merged_reasons
        orch_policy_recommendation["health_mode"] = health_mode
        orch_policy_recommendation["recommended"] = selected_mode

    total_sources = max(1, int(data_health_snapshot.get("total_sources", 0) or 0))
    degraded_ratio = len(data_health_snapshot.get("degraded_sources") or []) / total_sources
    stale_ratio = int(data_health_snapshot.get("stale_sources", 0) or 0) / total_sources
    latency_pressure = (degraded_ratio + stale_ratio) >= 0.45
    latency_budget["pressure"] = latency_pressure
    if latency_pressure:
        latency_budget["intel_timeout_s"] = min(_INTEL_SECTION_TIMEOUT_S, _TIGHT_INTEL_TIMEOUT_S)
        if hasattr(agent, "MAX_MODEL_OUTPUT_TOKENS"):
            agent_knob_restore["MAX_MODEL_OUTPUT_TOKENS"] = agent.MAX_MODEL_OUTPUT_TOKENS
            agent.MAX_MODEL_OUTPUT_TOKENS = min(int(agent.MAX_MODEL_OUTPUT_TOKENS), _TIGHT_MAX_OUTPUT_TOKENS)
        if hasattr(agent, "TOOL_TIMEOUT_SECONDS"):
            agent_knob_restore["TOOL_TIMEOUT_SECONDS"] = agent.TOOL_TIMEOUT_SECONDS
            agent.TOOL_TIMEOUT_SECONDS = min(float(agent.TOOL_TIMEOUT_SECONDS), _TIGHT_TOOL_TIMEOUT_SECONDS)

    degraded_sources = data_health_snapshot.get("degraded_sources") or []
    if degraded_sources:
        degraded_text = ", ".join(degraded_sources[:10])
        full_message = (
            f"[DATA HEALTH NOTICE]\n"
            f"Some connectors are currently degraded: {degraded_text}.\n"
            f"Prefer cached/indexed data and avoid unnecessary live tool calls for degraded sources "
            f"unless the user explicitly asks for a live refresh. If freshness could affect confidence, "
            f"state that clearly.\n\n"
            f"{full_message}"
        )

    # Gather intelligence context before running agent
    intel_context = ""
    try:
        hub = get_intelligence_hub()
        intel_parts = []

        # Recall relevant facts from semantic memory
        recalled = await asyncio.wait_for(
            hub.recall(req.message, limit=5, min_relevance=0.45),
            timeout=latency_budget["intel_timeout_s"],
        )
        if recalled:
            facts_text = "\n".join(f"- {f.content}" for f, _score in recalled[:5])
            intel_parts.append(
                f"[BACKGROUND MEMORY - Remembered personal facts and preferences. "
                f"These are NOT live calendar events or tasks or email. "
                f"Use them only for personalisation. "
                f"ALWAYS call live tools for real-time requests (briefings, email, calendar, tasks) — "
                f"never substitute these facts for fresh data or skip tool calls because of them.]\n{facts_text}"
            )

        # Check what patterns are expected now
        expected = []
        if not latency_budget["pressure"]:
            expected = await asyncio.wait_for(
                hub.whats_expected_now(),
                timeout=latency_budget["intel_timeout_s"],
            )
        if expected:
            patterns_text = "\n".join(f"- {p['pattern']}: {p['description']}" for p in expected[:3])
            intel_parts.append(f"[PATTERNS - What usually happens now]\n{patterns_text}")

        # Get proactive suggestions
        suggestions = []
        if not latency_budget["pressure"]:
            suggestions = await asyncio.wait_for(
                hub.get_suggestions(max_suggestions=3),
                timeout=latency_budget["intel_timeout_s"],
            )
        if suggestions:
            sugg_text = "\n".join(f"- {s.title}: {s.description}" for s in suggestions[:3])
            intel_parts.append(f"[SUGGESTIONS]\n{sugg_text}")

        if intel_parts:
            intel_context = "\n\n".join(intel_parts) + "\n\n"
            logger.info(f"Injected {len(intel_parts)} intelligence sections")
    except Exception as e:
        logger.warning(f"Context gathering failed (non-fatal): {e}")

    # Prepend intelligence context to message
    if intel_context:
        full_message = f"[INTELLIGENCE CONTEXT - Use this to provide better, more personalized responses]\n{intel_context}[USER MESSAGE]\n{full_message}"

    # Save original tools in case we filter them (agent is session-persistent)
    _original_tools = agent.tools
    _original_schemas = agent.tool_schemas
    try:
        classify_t0 = _time.perf_counter()
        from intent_router import classify, handle_index_direct, filter_tools as router_filter_tools, IntentType
        intent = await asyncio.wait_for(
            classify(req.message),
            timeout=_INTENT_CLASSIFY_TIMEOUT_S,
        )
        timing["classify_ms"] = (_time.perf_counter() - classify_t0) * 1000
        logger.info(f"{intent}")

        # Fast path: INDEX_DIRECT — answer from local index, no LLM call
        if intent.type == IntentType.INDEX_DIRECT:
            index_result = handle_index_direct(intent, ss._data_index)
            if index_result:
                logger.info("Index direct hit — skipping LLM entirely")
                async def index_direct_generator():
                    yield f"data: {json.dumps({'event': 'thinking'})}\n\n"
                    response_text = index_result["response"]
                    # Update session history
                    session.messages.append({"role": "user", "content": req.message})
                    session.messages.append({"role": "assistant", "content": response_text})
                    session.auto_save()
                    payload = {
                        "response": response_text,
                        "steps": [],
                        "is_complete": True,
                        "meta": {"data_health": data_health_snapshot},
                    }
                    yield f"data: {json.dumps({'event': 'complete', 'data': payload})}\n\n"
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
            logger.info(f"Filtered tools: {original_count} → {len(agent.tools)} (domains: {intent.domains})")
    except Exception as e:
        logger.warning(f"Intent classification failed (falling through to FULL): {e}")

    capability_graph = OrchestrationCapabilityGraph.from_tools(list(agent.tools.values()))

    # Event queue for SSE
    queue = asyncio.Queue()

    async def on_step(step: Step):
        """Push step events to SSE queue and record observations."""
        data = ss.step_to_sse_dict(step)
        data["id"] = step.tool_call.id  # Unique ID for matching start/complete
        if step.status == StepStatus.RUNNING:
            try:
                if workflow_state.phase == WorkflowPhase.PLANNING:
                    workflow_sm.transition(WorkflowPhase.EXECUTING)
            except InvalidTransitionError:
                pass
            workflow_state.tool_calls += 1
            workflow_state.touch()
            tool_start_times[step.tool_call.id] = _time.perf_counter()
            await queue.put({"event": "tool_start", "step": data})
        elif step.status == StepStatus.COMPLETED:
            started = tool_start_times.pop(step.tool_call.id, None)
            if started is not None:
                elapsed_ms = (_time.perf_counter() - started) * 1000
                tool_durations.setdefault(step.tool_call.name, []).append(elapsed_ms)
            await queue.put({"event": "tool_complete", "step": data})

            for candidate in extract_artifact_candidates(step.tool_call.name, step.result):
                _artifact_ledger.record_artifact(
                    workflow_id=workflow_state.workflow_id,
                    step_id=step.tool_call.id,
                    tool_name=step.tool_call.name,
                    artifact_type=candidate["artifact_type"],
                    uri=candidate["uri"],
                    metadata=candidate.get("metadata", {}),
                )

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
            started = tool_start_times.pop(step.tool_call.id, None)
            if started is not None:
                elapsed_ms = (_time.perf_counter() - started) * 1000
                tool_durations.setdefault(step.tool_call.name, []).append(elapsed_ms)
            await queue.put({"event": "tool_failed", "step": data})
            try:
                workflow_sm.fail(step.error or f"Tool failed: {step.tool_call.name}")
            except InvalidTransitionError:
                pass
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
            try:
                workflow_sm.transition(WorkflowPhase.WAITING_APPROVAL)
            except InvalidTransitionError:
                pass
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

        # Optional execution blueprint (adds an extra LLM call, so disabled by default)
        if _ENABLE_BLUEPRINT:
            blueprint_t0 = _time.perf_counter()
            # Check cache first to avoid redundant LLM calls
            bp_key = req.message.lower().strip()[:200]
            cached_bp = _blueprint_cache.get(bp_key)
            if cached_bp and (_time.monotonic() - cached_bp[1]) < _BLUEPRINT_TTL:
                plan_steps = cached_bp[0]
                yield f"data: {json.dumps({'event': 'plan', 'steps': plan_steps})}\n\n"
                logger.info(f"Blueprint cache hit: {len(plan_steps)} steps")
                timing["blueprint_ms"] = (_time.perf_counter() - blueprint_t0) * 1000
            else:
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
                    _blueprint_cache[bp_key] = (plan_steps, _time.monotonic())
                    yield f"data: {json.dumps({'event': 'plan', 'steps': plan_steps})}\n\n"
                    logger.info(f"Blueprint: {len(plan_steps)} planned steps")
                timing["blueprint_ms"] = (_time.perf_counter() - blueprint_t0) * 1000
              except Exception as e:
                logger.warning(f"Blueprint generation skipped: {e}")
                logger.exception("Request error")
                timing["blueprint_ms"] = (_time.perf_counter() - blueprint_t0) * 1000
        else:
            timing["blueprint_ms"] = 0.0

        # Run agent as background task
        agent_t0 = _time.perf_counter()
        task = asyncio.create_task(agent.run(full_message))
        stream_deadline = _time.perf_counter() + _STREAM_AGENT_TIMEOUT_S

        try:
            while True:
                # Always flush any pending events first.
                if not queue.empty():
                    event = await queue.get()
                    yield f"data: {json.dumps(event)}\n\n"
                    continue

                # Exit once work is complete and no events remain.
                if task.done():
                    break

                if _time.perf_counter() >= stream_deadline:
                    task.cancel()
                    raise TimeoutError(
                        f"Agent run exceeded {_STREAM_AGENT_TIMEOUT_S:.0f}s timeout"
                    )

                queue_get = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait(
                    {task, queue_get},
                    timeout=2.0,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if queue_get in done:
                    event = queue_get.result()
                    yield f"data: {json.dumps(event)}\n\n"
                else:
                    queue_get.cancel()
                    try:
                        await queue_get
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        pass

                if not done:
                    yield ": heartbeat\n\n"

            # Drain remaining queued events
            while not queue.empty():
                event = await queue.get()
                yield f"data: {json.dumps(event)}\n\n"

            # Final state
            state = task.result()
            timing["agent_run_ms"] = (_time.perf_counter() - agent_t0) * 1000
            session.react_state = state
            workflow_state.llm_calls = state.llm_calls

            try:
                if state.pending_approval:
                    if workflow_state.phase != WorkflowPhase.WAITING_APPROVAL:
                        workflow_sm.transition(WorkflowPhase.WAITING_APPROVAL)
                else:
                    workflow_sm.transition(WorkflowPhase.VERIFYING)
                    workflow_sm.transition(WorkflowPhase.COMPLETED)
            except InvalidTransitionError:
                pass

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
                logger.info(f"{icon} {s.tool_call.name}")
            if state.is_complete:
                logger.info(f"Complete: {state.final_response[:80] if state.final_response else 'No response'}...")

            total_ms = (_time.perf_counter() - request_t0) * 1000
            top_tools = sorted(
                (
                    (name, (sum(vals) / max(len(vals), 1)), len(vals))
                    for name, vals in tool_durations.items() if vals
                ),
                key=lambda x: x[1],
                reverse=True,
            )[:8]
            top_tools_str = ", ".join(
                f"{name}:{avg_ms:.0f}ms(x{count})" for name, avg_ms, count in top_tools
            ) or "none"
            logger.info(
                "Timing profile | total=%.0fms classify=%.0fms blueprint=%.0fms agent=%.0fms "
                "llm_calls=%d tokens(in=%d out=%d cache_read=%d cache_create=%d) cost=$%.4f tools=%s",
                total_ms,
                timing.get("classify_ms", 0.0),
                timing.get("blueprint_ms", 0.0),
                timing.get("agent_run_ms", 0.0),
                state.llm_calls,
                state.input_tokens,
                state.output_tokens,
                state.cache_read_tokens,
                state.cache_creation_tokens,
                state.estimated_cost_usd,
                top_tools_str,
            )

            logger.info(
                "Data freshness | sources=%d fresh=%d stale=%d degraded=%s freshest=%ss stalest=%ss",
                data_health_snapshot.get("total_sources", 0),
                data_health_snapshot.get("fresh_sources", 0),
                data_health_snapshot.get("stale_sources", 0),
                ",".join(data_health_snapshot.get("degraded_sources", [])[:10]) or "none",
                data_health_snapshot.get("freshest_age_seconds"),
                data_health_snapshot.get("stalest_age_seconds"),
            )

            complete_payload = ss.state_to_response(state)
            artifacts = _artifact_ledger.list_artifacts(workflow_state.workflow_id, limit=200)
            verification = verify_outcome(workflow_state.outcome, state, artifacts).to_dict()
            evaluation = evaluate_runtime_snapshot(
                llm_calls=state.llm_calls,
                tool_calls=len(state.steps),
                wall_time_ms=total_ms,
                verification=verification,
            )
            gate = check_quality_gate(evaluation, thresholds=QualityGateThresholds())
            confidence = _confidence_from_runtime(
                data_health=data_health_snapshot,
                evaluation=evaluation.to_dict(),
                wall_time_ms=total_ms,
            )
            _record_eval_run(
                workflow_state=workflow_state,
                request_text=req.message,
                evaluation=evaluation.to_dict(),
                verification=verification,
                gate=gate,
                orchestration_mode=_effective_orchestration_mode(runtime_orch_mode),
            )
            if complete_payload.get("response") and confidence["level"] != "high":
                confidence_line = (
                    f"\n\nConfidence: {confidence['level']} ({int(confidence['score'] * 100)}%) "
                    f"based on runtime reliability signals."
                )
                complete_payload["response"] = (complete_payload.get("response") or "") + confidence_line
            complete_payload["meta"] = {
                "data_health": data_health_snapshot,
                "orchestration": _build_workflow_meta(
                    workflow_state,
                    capability_graph,
                    verification=verification,
                    evaluation=evaluation.to_dict(),
                    gate=gate,
                ),
                "confidence": confidence,
                "latency_budget": latency_budget,
                "policy_recommendation": orch_policy_recommendation,
                "applied_orchestration_mode": runtime_orch_mode,
            }
            if state.pending_approval:
                yield f"data: {json.dumps({'event': 'approval_needed', 'step': ss.step_to_sse_dict(state.pending_approval)})}\n\n"
            yield f"data: {json.dumps({'event': 'complete', 'data': complete_payload})}\n\n"

        except (Exception, asyncio.CancelledError) as e:
            logger.exception("Request error")
            try:
                workflow_sm.fail(str(e))
            except InvalidTransitionError:
                pass
            error_msg = "Request was cancelled" if isinstance(e, asyncio.CancelledError) else str(e)
            yield f"data: {json.dumps({'event': 'error', 'message': error_msg})}\n\n"
            yield f"data: {json.dumps({'event': 'complete', 'data': {'response': f'Error: {error_msg}', 'steps': [], 'pending_approval': None, 'is_complete': True, 'meta': {'data_health': data_health_snapshot}}})}\n\n"
        finally:
            if orch_mode_mutated:
                if prev_orch_mode is None:
                    os.environ.pop("TELIC_ORCH_MODE", None)
                else:
                    os.environ["TELIC_ORCH_MODE"] = prev_orch_mode
            if "MAX_MODEL_OUTPUT_TOKENS" in agent_knob_restore:
                agent.MAX_MODEL_OUTPUT_TOKENS = agent_knob_restore["MAX_MODEL_OUTPUT_TOKENS"]
            if "TOOL_TIMEOUT_SECONDS" in agent_knob_restore:
                agent.TOOL_TIMEOUT_SECONDS = agent_knob_restore["TOOL_TIMEOUT_SECONDS"]
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
    logger.info(f"Started new conversation: {session.session_id}")
    return JSONResponse({"status": "ok", "message": "New conversation started", "session_id": session.session_id})


@router.post("/react/approve")
async def react_approve(req: ReactApproveRequest):
    """
    Approve or reject a pending action.
    
    After approval, the agent continues executing.
    """
    session = ss.get_user_session(req.session_id)
    prev_orch_mode = os.environ.get("TELIC_ORCH_MODE")
    applied_orch_mode, orch_policy_recommendation = _resolve_orchestration_mode(req.orchestration_mode or "")
    if applied_orch_mode:
        os.environ["TELIC_ORCH_MODE"] = applied_orch_mode
    
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
            logger.info(f"{action}: {session.react_state.pending_approval.tool_call.name}")

        workflow_state = _get_or_create_workflow_state(
            req.session_id,
            "approval_continuation",
            phase=WorkflowPhase.WAITING_APPROVAL,
        )
        capability_graph = OrchestrationCapabilityGraph.from_tools(list(agent.tools.values()))

        if req.approved and session.react_state.pending_approval:
            artifacts = _artifact_ledger.list_artifacts(workflow_state.workflow_id, limit=200)
            preflight_issues = check_side_effect_preconditions(
                workflow_state.outcome,
                session.react_state.pending_approval,
                artifacts,
            )
            if preflight_issues:
                verification = verify_outcome(workflow_state.outcome, session.react_state, artifacts).to_dict()
                evaluation = evaluate_runtime_snapshot(
                    llm_calls=getattr(session.react_state, "llm_calls", 0),
                    tool_calls=len(getattr(session.react_state, "steps", []) or []),
                    wall_time_ms=0.0,
                    verification=verification,
                )
                gate = check_quality_gate(evaluation, thresholds=QualityGateThresholds())
                _record_eval_run(
                    workflow_state=workflow_state,
                    request_text="approval_preflight_blocked",
                    evaluation=evaluation.to_dict(),
                    verification={
                        **verification,
                        "issues": verification.get("issues", []) + preflight_issues,
                    },
                    gate=gate,
                    orchestration_mode=_effective_orchestration_mode(applied_orch_mode),
                )
                payload = ss.state_to_response(session.react_state)
                payload["error"] = "Preflight check failed"
                payload["meta"] = {
                    "data_health": _build_data_health_snapshot(),
                    "orchestration": _build_workflow_meta(
                        workflow_state,
                        capability_graph,
                        verification={
                            **verification,
                            "issues": verification.get("issues", []) + preflight_issues,
                        },
                        evaluation=evaluation.to_dict(),
                        gate=gate,
                    ),
                    "policy_recommendation": orch_policy_recommendation,
                    "applied_orchestration_mode": applied_orch_mode,
                }
                return JSONResponse(payload)
        
        # Continue with approval decision
        state = await agent.continue_with_approval(req.approved, updated_params=req.updated_params)
        session.react_state = state
        workflow_state.llm_calls = state.llm_calls
        workflow_state.touch()
        
        # Record result in session history
        if state.final_response:
            session.messages.append({"role": "assistant", "content": state.final_response})

        payload = ss.state_to_response(state)
        artifacts = _artifact_ledger.list_artifacts(workflow_state.workflow_id, limit=200)
        verification = verify_outcome(workflow_state.outcome, state, artifacts).to_dict()
        evaluation = evaluate_runtime_snapshot(
            llm_calls=state.llm_calls,
            tool_calls=len(state.steps),
            wall_time_ms=0.0,
            verification=verification,
        )
        gate = check_quality_gate(evaluation, thresholds=QualityGateThresholds())
        _record_eval_run(
            workflow_state=workflow_state,
            request_text="approval_non_stream",
            evaluation=evaluation.to_dict(),
            verification=verification,
            gate=gate,
            orchestration_mode=_effective_orchestration_mode(applied_orch_mode),
        )
        payload["meta"] = {
            "data_health": _build_data_health_snapshot(),
            "orchestration": _build_workflow_meta(
                workflow_state,
                capability_graph,
                verification=verification,
                evaluation=evaluation.to_dict(),
                gate=gate,
            ),
            "policy_recommendation": orch_policy_recommendation,
            "applied_orchestration_mode": applied_orch_mode,
        }
        return JSONResponse(payload)
        
    except Exception as e:
        logger.exception("Request error")
        return JSONResponse({
            "error": str(e),
            "steps": [],
            "pending_approval": None,
            "is_complete": True,
            "response": f"Error: {str(e)}",
        })
    finally:
        if applied_orch_mode:
            if prev_orch_mode is None:
                os.environ.pop("TELIC_ORCH_MODE", None)
            else:
                os.environ["TELIC_ORCH_MODE"] = prev_orch_mode


@router.post("/react/approve/stream")
async def react_approve_stream(req: ReactApproveRequest):
    """
    Streaming version of approve. Returns SSE events as agent continues
    executing after approval, so the UI can show real-time tool progress.
    """
    import json
    prev_orch_mode = os.environ.get("TELIC_ORCH_MODE")
    applied_orch_mode, orch_policy_recommendation = _resolve_orchestration_mode(req.orchestration_mode or "")
    if applied_orch_mode:
        os.environ["TELIC_ORCH_MODE"] = applied_orch_mode
    session = ss.get_user_session(req.session_id)

    agent = await ss.get_session_agent(session)
    if not agent or not session.react_state:
        async def err():
            yield f"data: {json.dumps({'event': 'error', 'message': 'No pending action'})}\n\n"
        return StreamingResponse(err(), media_type="text/event-stream")

    action = "Approved" if req.approved else "Rejected"
    if session.react_state.pending_approval:
        logger.info(f"{action}: {session.react_state.pending_approval.tool_call.name}")

    if not req.approved:
        # Rejection is instant — no streaming needed
        async def reject_stream():
            state = await agent.continue_with_approval(False, updated_params=req.updated_params)
            session.react_state = state
            payload = ss.state_to_response(state)
            key = _session_key(req.session_id)
            ws = _session_workflows.get(key)
            orchestration_meta = None
            if ws is not None:
                ws.phase = WorkflowPhase.CANCELLED
                ws.touch()
                capability_graph = OrchestrationCapabilityGraph.from_tools(list(agent.tools.values()))
                orchestration_meta = _build_workflow_meta(
                    ws,
                    capability_graph,
                    verification=None,
                    evaluation=None,
                    gate=None,
                )
            payload["meta"] = {
                "data_health": _build_data_health_snapshot(),
                "orchestration": orchestration_meta,
            }
            if state.pending_approval:
                yield f"data: {json.dumps({'event': 'approval_needed', 'step': ss.step_to_sse_dict(state.pending_approval)})}\n\n"
            yield f"data: {json.dumps({'event': 'complete', 'data': payload})}\n\n"
        return StreamingResponse(reject_stream(), media_type="text/event-stream")

    # Approved — stream the continuation
    queue = asyncio.Queue()
    workflow_state = _get_or_create_workflow_state(
        req.session_id,
        "approval_continuation",
        phase=WorkflowPhase.WAITING_APPROVAL,
    )
    workflow_state.phase = WorkflowPhase.WAITING_APPROVAL
    workflow_state.touch()
    workflow_sm = OrchestrationStateMachine(workflow_state)
    capability_graph = OrchestrationCapabilityGraph.from_tools(list(agent.tools.values()))

    preflight_issues: List[str] = []
    if session.react_state and session.react_state.pending_approval:
        artifacts = _artifact_ledger.list_artifacts(workflow_state.workflow_id, limit=200)
        preflight_issues = check_side_effect_preconditions(
            workflow_state.outcome,
            session.react_state.pending_approval,
            artifacts,
        )

    async def on_step(step):
        data = ss.step_to_sse_dict(step)
        data["id"] = step.tool_call.id
        if step.status == StepStatus.RUNNING:
            try:
                workflow_sm.transition(WorkflowPhase.EXECUTING)
            except InvalidTransitionError:
                pass
            workflow_state.tool_calls += 1
            workflow_state.touch()
            await queue.put({"event": "tool_start", "step": data})
        elif step.status == StepStatus.COMPLETED:
            await queue.put({"event": "tool_complete", "step": data})
            for candidate in extract_artifact_candidates(step.tool_call.name, step.result):
                _artifact_ledger.record_artifact(
                    workflow_id=workflow_state.workflow_id,
                    step_id=step.tool_call.id,
                    tool_name=step.tool_call.name,
                    artifact_type=candidate["artifact_type"],
                    uri=candidate["uri"],
                    metadata=candidate.get("metadata", {}),
                )
        elif step.status == StepStatus.FAILED:
            try:
                workflow_sm.fail(step.error or f"Tool failed: {step.tool_call.name}")
            except InvalidTransitionError:
                pass
            await queue.put({"event": "tool_failed", "step": data})
        elif step.status == StepStatus.PENDING_APPROVAL:
            try:
                workflow_sm.transition(WorkflowPhase.WAITING_APPROVAL)
            except InvalidTransitionError:
                pass
            await queue.put({"event": "approval_needed", "step": data})

    async def on_thinking():
        await queue.put({"event": "thinking"})

    prev_on_step = agent.on_step
    prev_on_thinking = getattr(agent, 'on_thinking', None)
    agent.on_step = on_step
    agent.on_thinking = on_thinking

    async def event_generator():
        yield f"data: {json.dumps({'event': 'thinking'})}\n\n"
        if preflight_issues:
            verification = verify_outcome(
                workflow_state.outcome,
                session.react_state,
                _artifact_ledger.list_artifacts(workflow_state.workflow_id, limit=200),
            ).to_dict()
            verification["issues"] = verification.get("issues", []) + preflight_issues
            evaluation = evaluate_runtime_snapshot(
                llm_calls=getattr(session.react_state, "llm_calls", 0),
                tool_calls=len(getattr(session.react_state, "steps", []) or []),
                wall_time_ms=0.0,
                verification=verification,
            )
            gate = check_quality_gate(evaluation, thresholds=QualityGateThresholds())
            _record_eval_run(
                workflow_state=workflow_state,
                request_text="approval_stream_preflight_blocked",
                evaluation=evaluation.to_dict(),
                verification=verification,
                gate=gate,
                orchestration_mode=_effective_orchestration_mode(applied_orch_mode),
            )
            if session.react_state and session.react_state.pending_approval:
                yield f"data: {json.dumps({'event': 'approval_needed', 'step': ss.step_to_sse_dict(session.react_state.pending_approval)})}\n\n"
            payload = ss.state_to_response(session.react_state)
            payload["error"] = "Preflight check failed"
            payload["meta"] = {
                "data_health": _build_data_health_snapshot(),
                "orchestration": _build_workflow_meta(
                    workflow_state,
                    capability_graph,
                    verification=verification,
                    evaluation=evaluation.to_dict(),
                    gate=gate,
                ),
                "policy_recommendation": orch_policy_recommendation,
                "applied_orchestration_mode": applied_orch_mode,
            }
            yield f"data: {json.dumps({'event': 'complete', 'data': payload})}\n\n"
            return
        task = asyncio.create_task(agent.continue_with_approval(True, updated_params=req.updated_params))
        try:
            while True:
                if not queue.empty():
                    event = await queue.get()
                    yield f"data: {json.dumps(event)}\n\n"
                    continue

                if task.done():
                    break

                queue_get = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait(
                    {task, queue_get},
                    timeout=2.0,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if queue_get in done:
                    event = queue_get.result()
                    yield f"data: {json.dumps(event)}\n\n"
                else:
                    queue_get.cancel()
                    try:
                        await queue_get
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        pass

                if not done:
                    yield ": heartbeat\n\n"
            while not queue.empty():
                event = await queue.get()
                yield f"data: {json.dumps(event)}\n\n"
            state = task.result()
            session.react_state = state
            workflow_state.llm_calls = state.llm_calls
            try:
                if state.pending_approval:
                    if workflow_state.phase != WorkflowPhase.WAITING_APPROVAL:
                        workflow_sm.transition(WorkflowPhase.WAITING_APPROVAL)
                else:
                    workflow_sm.transition(WorkflowPhase.VERIFYING)
                    workflow_sm.transition(WorkflowPhase.COMPLETED)
            except InvalidTransitionError:
                pass
            if state.final_response:
                session.messages.append({"role": "assistant", "content": state.final_response})
            session.auto_save()
            payload = ss.state_to_response(state)
            artifacts = _artifact_ledger.list_artifacts(workflow_state.workflow_id, limit=200)
            verification = verify_outcome(workflow_state.outcome, state, artifacts).to_dict()
            evaluation = evaluate_runtime_snapshot(
                llm_calls=state.llm_calls,
                tool_calls=len(state.steps),
                wall_time_ms=0.0,
                verification=verification,
            )
            gate = check_quality_gate(evaluation, thresholds=QualityGateThresholds())
            _record_eval_run(
                workflow_state=workflow_state,
                request_text="approval_stream",
                evaluation=evaluation.to_dict(),
                verification=verification,
                gate=gate,
                orchestration_mode=_effective_orchestration_mode(applied_orch_mode),
            )
            payload["meta"] = {
                "data_health": _build_data_health_snapshot(),
                "orchestration": _build_workflow_meta(
                    workflow_state,
                    capability_graph,
                    verification=verification,
                    evaluation=evaluation.to_dict(),
                    gate=gate,
                ),
                "policy_recommendation": orch_policy_recommendation,
                "applied_orchestration_mode": applied_orch_mode,
            }
            if state.pending_approval:
                yield f"data: {json.dumps({'event': 'approval_needed', 'step': ss.step_to_sse_dict(state.pending_approval)})}\n\n"
            yield f"data: {json.dumps({'event': 'complete', 'data': payload})}\n\n"
        except (Exception, asyncio.CancelledError) as e:
            logger.exception("Request error")
            try:
                workflow_sm.fail(str(e))
            except InvalidTransitionError:
                pass
            error_msg = "Request was cancelled" if isinstance(e, asyncio.CancelledError) else str(e)
            yield f"data: {json.dumps({'event': 'error', 'message': error_msg})}\n\n"
            fallback_state = session.react_state if session and session.react_state else None
            if fallback_state:
                payload = ss.state_to_response(fallback_state)
                payload["error"] = error_msg
                payload["response"] = payload.get("response") or f"Error: {error_msg}"
                yield f"data: {json.dumps({'event': 'complete', 'data': payload})}\n\n"
            else:
                yield f"data: {json.dumps({'event': 'complete', 'data': {'response': f'Error: {error_msg}', 'steps': [], 'pending_approval': None, 'is_complete': True}})}\n\n"
        finally:
            if applied_orch_mode:
                if prev_orch_mode is None:
                    os.environ.pop("TELIC_ORCH_MODE", None)
                else:
                    os.environ["TELIC_ORCH_MODE"] = prev_orch_mode
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
    logger.info(f"Loaded session {session_id} with {len(us.messages)} messages")
    return JSONResponse({"status": "ok", "session": session})


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a saved session."""
    deleted = session_store.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return JSONResponse({"status": "ok"})


@router.post("/prefetch")
async def prefetch():
    """Warm cache on app open — sync connected services in background."""
    sync_engine = ss._sync_engine
    if not sync_engine or not hasattr(sync_engine, '_adapters'):
        return JSONResponse({"status": "ok", "triggered": []})

    triggered = []
    for source in list(sync_engine._adapters.keys()):
        try:
            asyncio.create_task(sync_engine.sync_now(source=source))
            triggered.append(source)
        except Exception:
            pass
    logger.info(f"Prefetch triggered for: {triggered}")
    return JSONResponse({"status": "ok", "triggered": triggered})

