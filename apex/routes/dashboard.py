"""Harness Dashboard API Routes"""

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
import json
import logging
from pathlib import Path

from pydantic import BaseModel, Field

from harness.control_plane import get_harness_control_plane

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class ScenarioStateUpdate(BaseModel):
    enabled: Optional[bool] = None
    completed: Optional[bool] = None
    notes: Optional[str] = None


class ScenarioCreateRequest(BaseModel):
    id: str
    name: str
    prompt: str
    suites: List[str] = Field(default_factory=lambda: ["nightly"])
    orchestration_mode: Optional[str] = None
    timeout_seconds: Optional[int] = None
    max_approvals: Optional[int] = None
    checks: Dict[str, Any] = Field(default_factory=dict)


class RunQueueRequest(BaseModel):
    target_type: Literal["all", "suite", "scenario"] = "suite"
    suite: Optional[str] = None
    scenario_ids: List[str] = Field(default_factory=list)
    iterations: int = 1
    rerun_failed_only: bool = False
    auto_approve: bool = True
    read_only_mode: bool = False


class RepairQueueRequest(BaseModel):
    source_run_id: str = "latest"
    strategy: str = "generic-remediation"
    max_fix_attempts: int = 1
    auto_rerun: bool = True
    notes: str = ""


class SafetyUpdateRequest(BaseModel):
    allow_write_runs: bool


def get_latest_campaign_report():
    path = Path("/workspaces/Zero/apex/scenarios/reports/latest/campaign_report.json")
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except:
            pass
    return {}


def get_latest_harness_report():
    path = Path("/workspaces/Zero/apex/scenarios/reports/latest/harness_report.json")
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except:
            pass
    return {}


def _build_scenario_rows() -> List[Dict[str, Any]]:
    report = get_latest_campaign_report()
    harness = get_latest_harness_report()
    scenario_rows = report.get("scenario_results") or []
    if scenario_rows:
        return scenario_rows
    if harness.get("scenarios"):
        return [
            {
                "scenario_name": item.get("scenario_name", item.get("scenario_id", "Unknown")),
                "success": bool(item.get("successful_runs", 0) > 0 and item.get("failed_runs", 0) == 0),
                "duration_seconds": item.get("avg_duration_seconds", 0),
                "issues": [item.get("most_common_issue")] if item.get("most_common_issue") else [],
            }
            for item in harness["scenarios"]
        ]
    return []


@router.get("/api/campaign/latest")
async def get_latest_campaign():
    return get_latest_campaign_report() or {"status": "no_campaigns_run"}


@router.get("/api/scenarios")
async def get_scenarios():
    return get_harness_control_plane().get_scenario_catalog()


@router.get("/api/environment")
async def get_environment():
    return get_harness_control_plane().get_environment_info()


@router.get("/api/safety")
async def get_safety():
    return get_harness_control_plane().get_safety_settings()


@router.patch("/api/safety")
async def update_safety(payload: SafetyUpdateRequest):
    updated = get_harness_control_plane().update_safety_settings(payload.model_dump())
    return {"ok": True, "safety": updated}


@router.post("/api/scenarios")
async def create_scenario(payload: ScenarioCreateRequest):
    try:
        scenario = get_harness_control_plane().add_scenario(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "scenario": scenario}


@router.patch("/api/scenarios/{scenario_id}")
async def update_scenario(scenario_id: str, payload: ScenarioStateUpdate):
    try:
        state = get_harness_control_plane().update_scenario_state(scenario_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown scenario: {scenario_id}") from exc
    return {"ok": True, "state": state}


@router.get("/api/runs")
async def get_runs():
    return get_harness_control_plane().get_runs()


@router.post("/api/runs")
async def queue_run(payload: RunQueueRequest):
    try:
        run = await get_harness_control_plane().queue_run(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "run": run}


@router.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    run = get_harness_control_plane().get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Unknown run: {run_id}")
    return run


@router.get("/api/runs/{run_id}/log")
async def get_run_log(run_id: str, tail: int = 200):
    payload = get_harness_control_plane().get_run_log(run_id, tail_lines=tail)
    if not payload.get("found"):
        raise HTTPException(status_code=404, detail=f"Unknown run: {run_id}")
    return payload


@router.get("/api/failures/latest")
async def get_failure_insights():
    return get_harness_control_plane().get_failure_insights()


@router.get("/api/repairs")
async def get_repairs():
    insights = get_harness_control_plane().get_failure_insights()
    return {
        "generated_at": insights.get("generated_at"),
        "items": insights.get("repairs", []),
    }


@router.get("/api/repairs/{repair_id}")
async def get_repair(repair_id: str):
    repair = get_harness_control_plane().get_repair(repair_id)
    if not repair:
        raise HTTPException(status_code=404, detail=f"Unknown repair: {repair_id}")
    return repair


@router.get("/api/runtime/diagnostics")
async def get_runtime_diagnostics():
    return get_harness_control_plane().get_runtime_diagnostics()


@router.get("/api/quality/gate")
async def get_quality_gate():
    return get_harness_control_plane().get_quality_gate_status()


@router.post("/api/repairs")
async def queue_repair(payload: RepairQueueRequest):
    try:
        repair = get_harness_control_plane().queue_repair(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "repair": repair}


@router.post("/api/repairs/{repair_id}/retry")
async def retry_repair(repair_id: str):
    try:
        repair = get_harness_control_plane().retry_repair(repair_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "repair": repair}


@router.get("/api/connectors/status")
async def get_connectors_status():
    try:
        from connectors.credentials import get_credential_store
        from connectors.registry import get_registry

        registry = get_registry()
        credential_store = get_credential_store()
        result = {}
        for metadata in registry.list_connectors():
            instance = registry.get_connector(metadata.name)
            provider = metadata.provider
            has_token = credential_store.has_valid(provider)
            has_client_credentials = (
                credential_store.has(f"{provider}:client") or not metadata.requires_client_creds
            )
            connected = bool(getattr(instance, "is_connected", False)) or bool(has_token)
            result[metadata.name] = {
                "name": metadata.display_name,
                "provider": provider,
                "connected": connected,
                "has_credentials": bool(has_token),
                "has_client_credentials": bool(has_client_credentials),
                "enabled": bool(has_token),
            }
        return result
    except Exception as exc:
        logger.warning("Connector status unavailable: %s", exc)
        return {}


@router.get("/", response_class=HTMLResponse)
async def dashboard_html():
    report = get_latest_campaign_report()
    harness = get_latest_harness_report()

    scenarios_html = '<p style="color: #666;">No scenarios run yet</p>'
    scenario_rows = _build_scenario_rows()

    if scenario_rows:
        parts = []
        for r in scenario_rows:
            status = 'PASS' if r.get('success') else 'FAIL'
            html = f'<div class="scenario-result {status.lower()}"><div class="scenario-name">{r.get("scenario_name", "Unknown")} <span class="status-badge status-{status.lower()}">{status}</span></div><div class="scenario-meta"><span>Duration: {r.get("duration_seconds", 0):.1f}s</span></div>'
            if r.get('issues'):
                html += '<div class="issue-list">'
                for issue in r['issues'][:3]:
                    html += f'<div class="issue">Warning {issue}</div>'
                html += '</div>'
            html += '</div>'
            parts.append(html)
        scenarios_html = ''.join(parts)
    
    rate = float(report.get('final_pass_rate', harness.get('summary', {}).get('overall_pass_rate', 0)) or 0) * 100.0
    final_iter = (report.get('iterations') or [{}])[-1]
    passed = final_iter.get('passed', 0)
    if not passed and harness.get('scenarios'):
        passed = sum(1 for s in harness['scenarios'] if s.get('successful_runs', 0) > 0 and s.get('failed_runs', 0) == 0)
    total = report.get('summary', {}).get('total_scenarios', harness.get('summary', {}).get('total_scenarios', 0))
    if not total:
        total = final_iter.get('total', 0)
    iters = report.get('iterations_executed', len(report.get('iterations', [])))
    
    return f"""<!DOCTYPE html>
<html>
<head>
<title>Harness Dashboard</title>
<style>
body{{background:#0f1419;color:#e0e0e0;font-family:system-ui;margin:0;padding:20px}}
.container{{max-width:1400px;margin:0 auto}}
h1{{font-size:28px;margin-bottom:20px;color:#fff}}
h2{{font-size:18px;margin:30px 0 15px;color:#bbb;text-transform:uppercase}}
.card{{background:#1a1f29;border:1px solid #2a3040;border-radius:8px;padding:20px;margin-bottom:20px}}
.metric{{display:inline-block;margin-right:40px;margin-bottom:15px}}
.metric-label{{font-size:12px;color:#888;text-transform:uppercase}}
.metric-value{{font-size:24px;font-weight:600;color:#fff}}
.grid{{display:grid;grid-template-columns:repeat(12,1fr);gap:20px}}
.span-8{{grid-column:span 8}}
.span-4{{grid-column:span 4}}
.span-12{{grid-column:span 12}}
.scenario-result{{background:#242d39;border-left:3px solid #4a7c9e;padding:15px;margin-bottom:10px;border-radius:4px}}
.scenario-result.pass{{border-left-color:#22863a}}
.scenario-result.fail{{border-left-color:#6f2a2a}}
.scenario-name{{font-weight:500;margin-bottom:8px}}
.status-badge{{display:inline-block;padding:4px 12px;border-radius:4px;font-size:12px;font-weight:600;text-transform:uppercase}}
.status-pass{{background:#22863a;color:#85e89d}}
.status-fail{{background:#6f2a2a;color:#f97583}}
.status-queued{{background:#5b4b17;color:#f5d76e}}
.status-running{{background:#003b73;color:#79b8ff}}
.issue{{font-size:11px;color:#d4a574;margin:4px 0}}
.connector-list{{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px}}
.connector-item{{background:#242d39;padding:12px;border-radius:4px;text-align:center;border:1px solid #333;font-size:12px}}
.connector-item.connected{{border-color:#22863a;background:#1a3a1a}}
.action-buttons{{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px}}
.button{{background:#0366d6;color:white;padding:10px 16px;border:none;border-radius:4px;text-decoration:none;font-size:13px;cursor:pointer}}
.button.secondary{{background:#30363d}}
.button.warn{{background:#8b5e00}}
.button:hover{{filter:brightness(1.08)}}
.badge{{display:inline-block;padding:4px 10px;border-radius:999px;font-size:11px;font-weight:700;text-transform:uppercase;margin-right:8px}}
.badge.codespaces{{background:#0f3d66;color:#9dd9ff}}
.badge.local{{background:#234020;color:#8be28f}}
.badge.safety-on{{background:#6f2a2a;color:#ffb4b4}}
.badge.safety-off{{background:#1f5124;color:#9ef3a3}}
.run-list,.scenario-table{{width:100%;border-collapse:collapse}}
.run-list td,.run-list th,.scenario-table td,.scenario-table th{{padding:10px 8px;border-bottom:1px solid #2a3040;vertical-align:top;text-align:left;font-size:13px}}
.muted{{color:#8b949e;font-size:12px}}
.scenario-actions{{display:flex;gap:8px;align-items:center}}
.pill{{display:inline-block;padding:3px 8px;background:#30363d;border-radius:999px;margin-right:6px;font-size:11px}}
.small-input,.large-input,.textarea{{width:100%;box-sizing:border-box;background:#0d1117;border:1px solid #30363d;color:#e6edf3;border-radius:6px;padding:10px}}
.textarea{{min-height:100px;resize:vertical}}
.log-view{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;background:#0b1016;border:1px solid #30363d;border-radius:6px;padding:12px;max-height:320px;overflow:auto;white-space:pre-wrap;font-size:12px}}
.form-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}}
.form-grid .full{{grid-column:1 / -1}}
.empty{{color:#8b949e;font-size:13px}}
@media (max-width: 1000px){{
    .span-8,.span-4,.span-12{{grid-column:span 12}}
    .form-grid{{grid-template-columns:1fr}}
}}
</style>
</head>
<body>
<div class="container">
<h1>Harness Dashboard</h1>
<div style="margin-bottom:14px">
<span class="badge" id="env-badge">ENV</span>
<span class="badge" id="safety-badge">SAFETY</span>
<span class="muted" id="env-detail"></span>
</div>
<div class="action-buttons">
<button class="button" onclick="queueSuite('core')">Run Core Suite</button>
<button class="button secondary" onclick="queueSuite('nightly')">Run Nightly Suite</button>
<button class="button secondary" onclick="queueSuiteReadOnly('core')">Run Core Read-Only</button>
<button class="button secondary" onclick="queueSuiteReadOnly('nightly')">Run Nightly Read-Only</button>
<button class="button warn" onclick="queueFailed()">Rerun Failed</button>
<a class="button secondary" href="/docs" target="_blank">API Docs</a>
</div>
<div class="card">
<h2>Campaign Status</h2>
<div class="metric"><div class="metric-label">Pass Rate</div><div class="metric-value">{rate:.1f}%</div></div>
<div class="metric"><div class="metric-label">Passed</div><div class="metric-value">{passed}/{total}</div></div>
<div class="metric"><div class="metric-label">Iterations</div><div class="metric-value">{iters}</div></div>
</div>
<div class="grid">
<div class="span-8">
<h2>Scenario Results</h2>
<div class="card">{scenarios_html}</div>
</div>
<div class="span-4">
<h2>Run Queue</h2>
<div class="card" id="run-queue">Loading...</div>
</div>
</div>
<div class="grid">
<div class="span-8">
<h2>Run Details</h2>
<div class="card" id="run-detail">Select a run to inspect details and logs.</div>
</div>
<div class="span-4">
<h2>Failure Clusters</h2>
<div class="card" id="failure-clusters">Loading...</div>
</div>
</div>
<div class="grid">
<div class="span-12">
<h2>Diagnosed Failures</h2>
<div class="card" id="diagnosed-failures">Loading...</div>
</div>
</div>
<div class="grid">
<div class="span-12">
<h2>Repair SLOs</h2>
<div class="card" id="repair-metrics">Loading...</div>
</div>
</div>
<div class="grid">
<div class="span-12">
<h2>Runtime Diagnostics</h2>
<div class="card" id="runtime-diagnostics">Loading...</div>
</div>
</div>
<div class="grid">
<div class="span-12">
<h2>Scenario Readiness Gate</h2>
<div class="card" id="quality-gate">Loading...</div>
</div>
</div>
<div class="grid">
<div class="span-12">
<h2>Scenario Catalog</h2>
<div class="card" id="scenario-catalog">Loading...</div>
</div>
</div>
<div class="grid">
<div class="span-8">
<h2>Add Scenario</h2>
<div class="card">
<form id="scenario-form">
<div class="form-grid">
<div><input class="small-input" name="id" placeholder="scenario-id" required></div>
<div><input class="small-input" name="name" placeholder="Scenario name" required></div>
<div class="full"><textarea class="textarea" name="prompt" placeholder="Scenario prompt" required></textarea></div>
<div><input class="small-input" name="suites" placeholder="core,nightly or nightly"></div>
<div><input class="small-input" name="required_tools" placeholder="required tools, comma separated"></div>
<div class="full"><input class="large-input" name="required_output_patterns" placeholder="required output patterns, comma separated"></div>
<div class="full"><button class="button" type="submit">Add Scenario</button></div>
</div>
</form>
<div id="scenario-form-message" class="muted" style="margin-top:12px"></div>
</div>
</div>
<div class="span-4">
<h2>Repair Queue</h2>
<div class="card" id="repair-queue">
<div class="muted" style="margin-bottom:12px">Queue generic repair planning from diagnosed failures.</div>
<button class="button warn" onclick="queueRepairLatest()">Queue Repair From Latest Failures</button>
<div id="repair-status" class="muted" style="margin-top:10px"></div>
<div id="repair-items" style="margin-top:14px"></div>
<div id="repair-detail" style="margin-top:14px"></div>
</div>
<h2>Safety Controls</h2>
<div class="card" id="safety-controls">
<label><input type="checkbox" id="allow-write-toggle"> Allow write-capable scenario runs</label>
<div class="muted" style="margin-top:10px">When disabled, runs with write-capable required tools are blocked server-side.</div>
</div>
<h2>Connector Status</h2>
<div class="card">
<div class="connector-list" id="connectors">Loading...</div>
</div>
</div>
</div>
<script>
const latestCampaign = {json.dumps(report)};

async function api(path, options = {{}}) {{
    const response = await fetch(path, {{
        headers: {{'Content-Type': 'application/json'}},
        ...options,
    }});
    if (!response.ok) {{
        const body = await response.json().catch(() => ({{detail: 'Request failed'}}));
        throw new Error(body.detail || 'Request failed');
    }}
    return response.json();
}}

function renderConnectors(data) {{
    const html = Object.entries(data).map(([name, status]) => `
        <div class="connector-item ${{status.connected ? 'connected' : ''}}">
            <div>${{name}}</div>
            <span class="status-badge status-${{status.connected ? 'pass' : 'fail'}}">${{status.connected ? 'CONNECTED' : 'OFFLINE'}}</span>
        </div>
    `).join('');
    document.getElementById('connectors').innerHTML = html || '<div class="empty">No connectors found</div>';
}}

function renderEnvironment(env, safety) {{
        const envBadge = document.getElementById('env-badge');
        const safetyBadge = document.getElementById('safety-badge');
        const envDetail = document.getElementById('env-detail');
        const runtime = env?.runtime || 'local';
        envBadge.className = `badge ${{runtime === 'codespaces' ? 'codespaces' : 'local'}}`;
        envBadge.textContent = runtime === 'codespaces' ? 'Codespaces Runtime' : 'Local Runtime';

        const writesAllowed = !!safety?.allow_write_runs;
        safetyBadge.className = `badge ${{writesAllowed ? 'safety-off' : 'safety-on'}}`;
        safetyBadge.textContent = writesAllowed ? 'Write Runs Enabled' : 'Write Runs Blocked';
        envDetail.textContent = writesAllowed
            ? 'Safety guard relaxed for write-capable scenarios.'
            : 'Safety guard active: write-capable scenario runs are blocked.';

        const toggle = document.getElementById('allow-write-toggle');
        if (toggle) toggle.checked = writesAllowed;
}}

function renderRuns(payload) {{
    const active = payload.active;
    const queued = payload.queued || [];
    const items = payload.items || [];
    const activeHtml = active ? `
        <div style="margin-bottom:14px">
            <div><strong>${{active.id}}</strong> <span class="status-badge status-running">RUNNING</span></div>
            <div class="muted">${{active.target_type}} ${{active.suite || (active.scenario_ids || []).join(', ')}}</div>
        </div>
    ` : '<div class="empty" style="margin-bottom:14px">No active run</div>';
    const queuedHtml = queued.length ? queued.map(run => `
        <div style="margin-bottom:8px"><span class="status-badge status-queued">QUEUED</span> ${{run.target_type}} ${{run.suite || (run.scenario_ids || []).join(', ')}}</div>
    `).join('') : '<div class="empty">Queue empty</div>';
    const historyRows = items.slice(0, 8).map(run => `
        <tr>
            <td>${{run.id}}</td>
            <td><span class="status-badge status-${{run.status === 'passed' ? 'pass' : (run.status === 'failed' ? 'fail' : (run.status || 'queued'))}}">${{run.status}}</span></td>
            <td>${{run.summary?.passed ?? '-'}}/${{run.summary?.total ?? '-'}}</td>
            <td>${{run.read_only_mode ? '<span class="pill">read-only</span>' : '<span class="muted">standard</span>'}}</td>
            <td><button class="button secondary" onclick="loadRunDetail('${{run.id}}')">Inspect</button></td>
        </tr>
    `).join('');
    document.getElementById('run-queue').innerHTML = `
        <div><strong>Active</strong></div>
        ${{activeHtml}}
        <div><strong>Queued</strong></div>
        ${{queuedHtml}}
        <div style="margin-top:16px"><strong>Recent Runs</strong></div>
                <table class="run-list">
                    <thead><tr><th>Run</th><th>Status</th><th>Pass</th><th>Mode</th><th></th></tr></thead>
                    <tbody>${{historyRows || '<tr><td colspan="5" class="empty">No runs yet</td></tr>'}}</tbody>
        </table>
    `;
}}

function renderFailureInsights(payload) {{
        const clusters = payload.clusters || [];
        const diagnosed = payload.diagnosed_failures || [];
        const metrics = payload.repair_metrics || {{}};
        const statusCounts = metrics.status_counts || {{}};
        const clusterHtml = clusters.length ? clusters.slice(0, 10).map(item => `
            <div style="display:flex;justify-content:space-between;margin-bottom:8px">
                <span><span class="pill">${{item.type}}</span>${{item.name}}</span>
                <strong>${{item.count}}</strong>
            </div>
        `).join('') : '<div class="empty">No failure clusters yet</div>';
        document.getElementById('failure-clusters').innerHTML = `
            <div class="muted" style="margin-bottom:8px">Rerun queue: ${{(payload.rerun_queue || []).join(', ') || 'empty'}}</div>
            ${{clusterHtml}}
        `;

        const diagnosedRows = diagnosed.map(item => `
            <tr>
                <td><strong>${{item.scenario_name}}</strong><div class="muted">${{item.scenario_id}}</div></td>
                <td><span class="pill">${{item.category}}</span> conf=${{(Number(item.confidence || 0) * 100).toFixed(0)}}%</td>
                <td>${{(item.issues || []).slice(0, 2).join(' | ') || 'none'}}</td>
                <td>${{(item.next_steps || []).slice(0, 2).join(' | ') || 'none'}}</td>
            </tr>
        `).join('');
        document.getElementById('diagnosed-failures').innerHTML = `
            <table class="scenario-table">
                <thead><tr><th>Scenario</th><th>Category</th><th>Issues</th><th>Suggested Next Steps</th></tr></thead>
                <tbody>${{diagnosedRows || '<tr><td colspan="4" class="empty">No diagnosed failures</td></tr>'}}</tbody>
            </table>
        `;

        document.getElementById('repair-metrics').innerHTML = `
            <div class="metric"><div class="metric-label">Queue Depth</div><div class="metric-value">${{metrics.queue_depth ?? 0}}</div></div>
            <div class="metric"><div class="metric-label">Active Workers</div><div class="metric-value">${{metrics.active_workers ?? 0}}/${{metrics.configured_workers ?? 0}}</div></div>
            <div class="metric"><div class="metric-label">Peak Workers</div><div class="metric-value">${{metrics.max_active_observed ?? 0}}</div></div>
            <div class="metric"><div class="metric-label">Validated Rate</div><div class="metric-value">${{((metrics.validated_rate ?? 0) * 100).toFixed(1)}}%</div></div>
            <div class="metric"><div class="metric-label">Improvement Rate</div><div class="metric-value">${{((metrics.improvement_rate ?? 0) * 100).toFixed(1)}}%</div></div>
            <div class="metric"><div class="metric-label">Avg Completion</div><div class="metric-value">${{Number(metrics.avg_completion_seconds ?? 0).toFixed(1)}}s</div></div>
            <div class="muted" style="margin-top:10px">status: queued=${{statusCounts.queued ?? 0}} · in_progress=${{statusCounts.in_progress ?? 0}} · validated=${{statusCounts.validated ?? 0}} · blocked=${{statusCounts.blocked ?? 0}}</div>
        `;
}}

function renderRepairs(payload) {{
        const items = payload.items || [];
        const html = items.slice(0, 6).map(item => `
            <div style="padding:10px;border:1px solid #2a3040;border-radius:6px;margin-bottom:8px">
                <div><strong>${{item.id}}</strong> <span class="status-badge status-${{item.status === 'queued' ? 'queued' : (item.status === 'in_progress' ? 'running' : (item.status === 'validated' ? 'pass' : 'fail'))}}">${{item.status}}</span></div>
                <div class="muted">${{item.strategy}} · scenarios: ${{(item.scenario_ids || []).join(', ')}}</div>
                <div class="muted">attempt=${{item.attempt_count || 0}}/${{item.max_fix_attempts || 1}} · eligible=${{(item.eligible_failures || []).length}} blocked=${{(item.blocked_failures || []).length}}</div>
                <div class="muted">playbook steps=${{(item.playbook_results || []).length}} · rerun=${{item.rerun?.run_id || 'none'}} · improved=${{item.validation?.improved ? 'yes' : 'no'}}</div>
                <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap">
                    <button class="button secondary" onclick="loadRepairDetail('${{item.id}}')">Inspect</button>
                    <button class="button secondary" onclick="retryRepair('${{item.id}}')">Retry</button>
                </div>
            </div>
        `).join('');
        document.getElementById('repair-items').innerHTML = html || '<div class="empty">No repair requests yet</div>';
}}

function renderRuntimeDiagnostics(payload) {{
    const runs = payload.runs || {{}};
    const repairs = payload.repairs || {{}};
    const timeouts = payload.timeouts || {{}};
    const runQueuedAge = runs.queued_age_seconds || {{}};
    const runActiveAge = runs.running_age_seconds || {{}};
    const repairQueuedAge = repairs.queued_age_seconds || {{}};
    const repairActiveAge = repairs.in_progress_age_seconds || {{}};

    document.getElementById('runtime-diagnostics').innerHTML = `
        <div class="metric"><div class="metric-label">Run Queue</div><div class="metric-value">${{runs.queued ?? 0}}</div></div>
        <div class="metric"><div class="metric-label">Running</div><div class="metric-value">${{runs.running ?? 0}}</div></div>
        <div class="metric"><div class="metric-label">Repair Queue</div><div class="metric-value">${{repairs.queued ?? 0}}</div></div>
        <div class="metric"><div class="metric-label">Repairs Active</div><div class="metric-value">${{repairs.in_progress ?? 0}}</div></div>
        <div class="muted" style="margin-top:8px">run queued age (avg/max): ${{Number(runQueuedAge.avg ?? 0).toFixed(1)}}s / ${{Number(runQueuedAge.max ?? 0).toFixed(1)}}s · run active age (avg/max): ${{Number(runActiveAge.avg ?? 0).toFixed(1)}}s / ${{Number(runActiveAge.max ?? 0).toFixed(1)}}s</div>
        <div class="muted" style="margin-top:6px">repair queued age (avg/max): ${{Number(repairQueuedAge.avg ?? 0).toFixed(1)}}s / ${{Number(repairQueuedAge.max ?? 0).toFixed(1)}}s · repair active age (avg/max): ${{Number(repairActiveAge.avg ?? 0).toFixed(1)}}s / ${{Number(repairActiveAge.max ?? 0).toFixed(1)}}s</div>
        <div class="muted" style="margin-top:6px">timeouts: run=${{timeouts.run_seconds ?? 0}}s · repair=${{timeouts.repair_seconds ?? 0}}s</div>
        <div class="muted" style="margin-top:6px">running ids: ${{(runs.running_ids || []).join(', ') || 'none'}} · active repair task ids: ${{(repairs.active_task_ids || []).join(', ') || 'none'}}</div>
    `;
}}

function renderQualityGate(payload) {{
    const ready = !!payload.ready_for_scenario_testing;
    const checks = payload.checks || [];
    const checkRows = checks.map(check => `
        <div style="display:flex;justify-content:space-between;margin-top:8px">
            <span>${{check.name}}</span>
            <span class="status-badge status-${{check.ok ? 'pass' : 'fail'}}">${{check.ok ? 'PASS' : 'FAIL'}}</span>
        </div>
        <div class="muted">${{check.details || ''}}</div>
    `).join('');
    document.getElementById('quality-gate').innerHTML = `
        <div style="margin-bottom:8px">
            <span class="status-badge status-${{ready ? 'pass' : 'fail'}}">${{ready ? 'READY FOR SCENARIO TESTING' : 'NOT READY'}}</span>
        </div>
        <div class="muted">This gate is computed from bounded concurrency, queue pressure, and recent watchdog timeout signals.</div>
        ${{checkRows || '<div class="empty">No checks available</div>'}}
    `;
}}

async function loadRepairDetail(repairId) {{
    const repair = await api(`/dashboard/api/repairs/${{repairId}}`);
    const transitions = (repair.transitions || []).map(t => `${{t.status}} @ ${{t.at}}`).join(' -> ');
    const steps = (repair.playbook_results || []).map(s => `<li>${{s.ok ? 'OK' : 'FAIL'}} · ${{s.title}} · ${{s.details}}</li>`).join('');
    const delta = repair.delta_metrics?.delta || {{}};
    document.getElementById('repair-detail').innerHTML = `
        <div style="padding:10px;border:1px solid #2a3040;border-radius:6px;background:#111827">
            <div><strong>Repair Detail</strong> · ${{repair.id}}</div>
            <div class="muted">status=${{repair.status}} · attempts=${{repair.attempt_count || 0}}/${{repair.max_fix_attempts || 1}}</div>
            <div class="muted">validation=${{repair.validation?.reason || 'n/a'}}</div>
            <div class="muted">delta: pass_rate=${{delta.pass_rate ?? 'n/a'}} failed=${{delta.failed ?? 'n/a'}} passed=${{delta.passed ?? 'n/a'}}</div>
            <div class="muted">transitions: ${{transitions || 'none'}}</div>
            <ul>${{steps || '<li class="muted">No playbook steps</li>'}}</ul>
        </div>
    `;
}}

async function retryRepair(repairId) {{
    try {{
        await api(`/dashboard/api/repairs/${{repairId}}/retry`, {{method: 'POST'}});
        document.getElementById('repair-status').textContent = `Retry queued: ${{repairId}}`;
        refreshDashboard();
    }} catch (error) {{
        document.getElementById('repair-status').textContent = error.message;
    }}
}}

async function loadRunDetail(runId) {{
        const [run, log] = await Promise.all([
            api(`/dashboard/api/runs/${{runId}}`),
            api(`/dashboard/api/runs/${{runId}}/log?tail=220`),
        ]);
        const campaign = run.campaign_report || {{}};
        const failed = campaign.final_failed_ids || [];
        const diagnosed = run.harness_report?.campaign_iteration?.diagnosed_failures || [];
        const safety = run.safety_snapshot || {{}};
        const writeCapableCount = Number(safety.write_capable_count || 0);
        const safetyMode = safety.allow_write_runs ? 'write-enabled' : 'write-blocked';
        const diagnosedList = diagnosed.slice(0, 3).map(d => `<li>${{d.scenario_id}}: ${{d.category}} (${{(Number(d.confidence || 0) * 100).toFixed(0)}}%)</li>`).join('');
        document.getElementById('run-detail').innerHTML = `
            <div style="margin-bottom:10px"><strong>${{run.id}}</strong> <span class="status-badge status-${{run.status === 'passed' ? 'pass' : (run.status === 'failed' ? 'fail' : 'running')}}">${{run.status}}</span></div>
            <div class="muted" style="margin-bottom:10px">pass=${{run.summary?.passed ?? '-'}}/${{run.summary?.total ?? '-'}} · failed ids=${{failed.join(', ') || 'none'}}</div>
            <div class="muted" style="margin-bottom:10px">safety snapshot: ${{safetyMode}} · write-capable targets=${{writeCapableCount}} · read-only mode=${{run.read_only_mode ? 'on' : 'off'}}</div>
            <div style="margin-bottom:8px"><strong>Diagnosed Failures</strong></div>
            <ul>${{diagnosedList || '<li class="muted">None</li>'}}</ul>
            <div style="margin:10px 0 6px"><strong>Runner Log (tail)</strong></div>
            <div class="log-view">${{(log.log || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') || 'No log output yet'}}</div>
        `;
}}

function renderCatalog(payload) {{
    const rows = (payload.items || []).map(item => {{
        const result = item.last_result || {{}};
        const status = result.passed === true ? 'pass' : (result.passed === false ? 'fail' : 'queued');
        const statusLabel = result.passed === true ? 'PASS' : (result.passed === false ? 'FAIL' : 'UNRUN');
        const suites = (item.suites || []).map(suite => `<span class="pill">${{suite}}</span>`).join('');
        const tools = (item.required_tools || []).slice(0, 4).map(tool => `<span class="pill">${{tool}}</span>`).join('');
        return `
            <tr>
                <td>
                    <div><strong>${{item.name}}</strong></div>
                    <div class="muted">${{item.id}}</div>
                    <div style="margin-top:6px">${{suites}}</div>
                </td>
                <td>${{tools || '<span class="muted">No required tools</span>'}}</td>
                <td><span class="status-badge status-${{status}}">${{statusLabel}}</span></td>
                <td>
                    <label><input type="checkbox" ${{item.enabled ? 'checked' : ''}} onchange="updateScenario('${{item.id}}', {{enabled: this.checked}})"> enabled</label><br>
                    <label><input type="checkbox" ${{item.completed ? 'checked' : ''}} onchange="updateScenario('${{item.id}}', {{completed: this.checked}})"> complete</label>
                </td>
                <td>
                    <div class="scenario-actions">
                        <button class="button secondary" onclick="queueScenario('${{item.id}}')">Run</button>
                    </div>
                    <div class="muted" style="margin-top:8px">${{(result.issues || []).slice(0, 2).join(' | ') || 'No recent issues'}}</div>
                </td>
            </tr>
        `;
    }}).join('');
    document.getElementById('scenario-catalog').innerHTML = `
        <div class="muted" style="margin-bottom:12px">${{payload.completed}} completed · ${{payload.enabled}} enabled · ${{payload.total}} total</div>
        <table class="scenario-table">
            <thead><tr><th>Scenario</th><th>Required Tools</th><th>Last Result</th><th>Tracking</th><th>Actions</th></tr></thead>
            <tbody>${{rows || '<tr><td colspan="5" class="empty">No scenarios found</td></tr>'}}</tbody>
        </table>
    `;
}}

async function refreshDashboard() {{
    const [connectors, runs, scenarios, failures, repairs, diagnostics, qualityGate, environment, safety] = await Promise.all([
        api('/dashboard/api/connectors/status'),
        api('/dashboard/api/runs'),
        api('/dashboard/api/scenarios'),
        api('/dashboard/api/failures/latest'),
        api('/dashboard/api/repairs'),
        api('/dashboard/api/runtime/diagnostics'),
        api('/dashboard/api/quality/gate'),
        api('/dashboard/api/environment'),
        api('/dashboard/api/safety'),
    ]);
    renderConnectors(connectors);
    renderEnvironment(environment, safety);
    renderRuns(runs);
    renderCatalog(scenarios);
    renderFailureInsights(failures);
    renderRepairs(repairs);
    renderRuntimeDiagnostics(diagnostics);
    renderQualityGate(qualityGate);
    const defaultRun = runs.active?.id || runs.items?.[0]?.id;
    if (defaultRun) {{
      loadRunDetail(defaultRun).catch(error => console.error(error));
    }}
}}

async function queueSuite(suite) {{
    await api('/dashboard/api/runs', {{method: 'POST', body: JSON.stringify({{target_type: 'suite', suite, iterations: 1, auto_approve: true}})}});
    refreshDashboard();
}}

async function queueSuiteReadOnly(suite) {{
    await api('/dashboard/api/runs', {{method: 'POST', body: JSON.stringify({{target_type: 'suite', suite, iterations: 1, auto_approve: true, read_only_mode: true}})}});
    refreshDashboard();
}}

async function queueScenario(id) {{
    await api('/dashboard/api/runs', {{method: 'POST', body: JSON.stringify({{target_type: 'scenario', scenario_ids: [id], iterations: 1, auto_approve: true}})}});
    refreshDashboard();
}}

async function queueFailed() {{
    const failed = latestCampaign.final_failed_ids || [];
    if (!failed.length) {{
        alert('No failed scenarios in the latest campaign report.');
        return;
    }}
    await api('/dashboard/api/runs', {{method: 'POST', body: JSON.stringify({{target_type: 'scenario', scenario_ids: failed, iterations: 1, rerun_failed_only: true, auto_approve: true}})}});
    refreshDashboard();
}}

async function updateScenario(id, payload) {{
    await api(`/dashboard/api/scenarios/${{id}}`, {{method: 'PATCH', body: JSON.stringify(payload)}});
    refreshDashboard();
}}

async function queueRepairLatest() {{
        try {{
            const res = await api('/dashboard/api/repairs', {{
                method: 'POST',
                body: JSON.stringify({{source_run_id: 'latest', strategy: 'generic-remediation', max_fix_attempts: 2, auto_rerun: true}}),
            }});
            document.getElementById('repair-status').textContent = `Queued repair: ${{res.repair.id}}`;
            refreshDashboard();
        }} catch (error) {{
            document.getElementById('repair-status').textContent = error.message;
        }}
}}

document.getElementById('allow-write-toggle').addEventListener('change', async (event) => {{
        try {{
            await api('/dashboard/api/safety', {{
                method: 'PATCH',
                body: JSON.stringify({{allow_write_runs: event.target.checked}}),
            }});
            refreshDashboard();
        }} catch (error) {{
            event.target.checked = !event.target.checked;
            alert(error.message);
        }}
}});

document.getElementById('scenario-form').addEventListener('submit', async (event) => {{
    event.preventDefault();
    const form = new FormData(event.target);
    const csv = (value) => String(value || '').split(',').map(item => item.trim()).filter(Boolean);
    const payload = {{
        id: form.get('id'),
        name: form.get('name'),
        prompt: form.get('prompt'),
        suites: csv(form.get('suites') || 'nightly'),
        checks: {{
            required_tools: csv(form.get('required_tools')),
            required_output_patterns: csv(form.get('required_output_patterns')),
            forbidden_error_patterns: ['timed out after', 'maximum number of steps', 'not making enough progress'],
            max_failed_steps: 0,
        }},
    }};

    try {{
        await api('/dashboard/api/scenarios', {{method: 'POST', body: JSON.stringify(payload)}});
        document.getElementById('scenario-form').reset();
        document.getElementById('scenario-form-message').textContent = 'Scenario added.';
        refreshDashboard();
    }} catch (error) {{
        document.getElementById('scenario-form-message').textContent = error.message;
    }}
}});

refreshDashboard().catch(error => console.error(error));
setInterval(() => refreshDashboard().catch(error => console.error(error)), 15000);
</script>
</div>
</body>
</html>"""
