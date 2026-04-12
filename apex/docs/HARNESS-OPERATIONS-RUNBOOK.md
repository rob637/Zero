# Harness Operations Runbook

## Purpose

Operate the scenario harness with high reliability and no scenario-specific engine logic.

This runbook covers:
- startup and smoke checks,
- readiness gate interpretation,
- reliability test execution,
- queue/repair troubleshooting,
- safe reset procedures.

## Principles

- Keep engine logic generic and capability-driven.
- Do not add hard-coded scenario mappings.
- Prefer improving diagnostics, tests, and primitive descriptions over special-case logic.

## Local Startup

From repo root:

```bash
cd /workspaces/Zero/apex
PYTHONPATH=/workspaces/Zero:/workspaces/Zero/apex python -m uvicorn server:app --host 127.0.0.1 --port 8000
```

## Dashboard URLs

- Dashboard: http://127.0.0.1:8000/dashboard/
- API docs: http://127.0.0.1:8000/docs

## Acceptance Smoke Checks

From repo root:

```bash
python - <<'PY'
import json, urllib.request
base='http://127.0.0.1:8000'
for path in [
    '/health',
    '/dashboard/api/environment',
    '/dashboard/api/safety',
    '/dashboard/api/runtime/diagnostics',
    '/dashboard/api/quality/gate',
    '/dashboard/api/failures/latest',
]:
    with urllib.request.urlopen(base + path, timeout=8) as r:
        payload=json.loads(r.read().decode('utf-8'))
    print(path, 'ok')
    if path.endswith('/quality/gate'):
        print('  ready_for_scenario_testing=', payload.get('ready_for_scenario_testing'))
        print('  checks=', [(c.get('name'), c.get('ok')) for c in payload.get('checks', [])])
PY
```

## Reliability Test Suite

From repo root:

```bash
pytest -q test_harness_control_plane.py test_harness_burnin.py
```

The suite validates:
- watchdog transitions,
- bounded repair concurrency,
- retention behavior,
- runtime diagnostics invariants,
- quality-gate logic,
- queue-drain burn-in behavior.

## Scenario Readiness Gate

Endpoint:

- `GET /dashboard/api/quality/gate`

The gate returns `ready_for_scenario_testing` and check details:
- `worker_bound_respected`
- `queue_depth_within_limit`
- `no_recent_watchdog_timeouts`

If readiness is false due to `no_recent_watchdog_timeouts`, this can be caused by historical watchdog records in persisted state.

## Diagnostics Endpoints

- `GET /dashboard/api/failures/latest`
  - includes `repair_metrics` (active/configured workers, queue depth, rates, peak worker usage)
- `GET /dashboard/api/runtime/diagnostics`
  - includes run/repair queue and age summaries
  - includes retention and timeout settings

## Tunable Environment Variables

- `HARNESS_RUN_TIMEOUT_SECONDS`
- `HARNESS_REPAIR_TIMEOUT_SECONDS`
- `HARNESS_MAX_RUN_HISTORY`
- `HARNESS_MAX_REPAIR_HISTORY`
- `HARNESS_QUALITY_QUEUE_DEPTH_LIMIT`
- `HARNESS_QUALITY_WATCHDOG_HORIZON_SECONDS`

## Safe State Reset (Local Dev Only)

Use this only when you need to clear stale local runtime state:

```bash
rm -f /workspaces/Zero/apex/scenarios/control_plane_state.json
```

Then restart the server and rerun smoke checks.

## CI Gates

Workflow:

- `.github/workflows/quality-gates.yml`

Includes:
- orchestration quality tests,
- harness control-plane reliability tests,
- API startup and quality gate CLI checks.

## Start Scenario Testing

When all are true:
- reliability tests are green,
- dashboard APIs are healthy,
- readiness gate checks pass,
- safety mode is set for intended run type (standard or read-only).

Then begin with dashboard suite runs and monitor:
- Repair SLOs panel,
- Runtime Diagnostics panel,
- Quality Gate panel.
