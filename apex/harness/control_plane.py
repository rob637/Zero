"""Harness control plane for scenario catalog state and queued runs."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from harness.repair_runner import build_repair_request

logger = logging.getLogger(__name__)

ROOT_DIR = Path("/workspaces/Zero")
APEX_DIR = ROOT_DIR / "apex"
DEFAULT_SCENARIO_FILE = APEX_DIR / "scenarios" / "regression_scenarios.json"
CONTROL_STATE_FILE = APEX_DIR / "scenarios" / "control_plane_state.json"
RUN_REPORTS_DIR = APEX_DIR / "scenarios" / "reports" / "dashboard-runs"
LATEST_REPORTS_DIR = APEX_DIR / "scenarios" / "reports" / "latest"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:
        logger.warning("Failed reading JSON from %s: %s", path, exc)
        return default


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    temp_path.replace(path)


class HarnessControlPlane:
    """Owns mutable harness dashboard state and queued run execution."""

    def __init__(self) -> None:
        self._file_lock = Lock()
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        self._repair_queue: asyncio.Queue[str] = asyncio.Queue()
        self._repair_worker_task: Optional[asyncio.Task] = None
        self._repair_concurrency = 3
        self._repair_semaphore = asyncio.Semaphore(self._repair_concurrency)
        self._active_repair_tasks: Dict[str, asyncio.Task] = {}
        self._repair_workers_in_flight = 0
        self._repair_max_active_observed = 0
        self._max_runs_history = max(20, int(os.environ.get("HARNESS_MAX_RUN_HISTORY", "80")))
        self._max_repairs_history = max(20, int(os.environ.get("HARNESS_MAX_REPAIR_HISTORY", "80")))
        self._run_timeout_seconds = max(60, int(os.environ.get("HARNESS_RUN_TIMEOUT_SECONDS", "2400")))
        self._repair_timeout_seconds = max(60, int(os.environ.get("HARNESS_REPAIR_TIMEOUT_SECONDS", "1800")))
        self._quality_queue_depth_limit = max(4, int(os.environ.get("HARNESS_QUALITY_QUEUE_DEPTH_LIMIT", "30")))
        self._quality_watchdog_horizon_seconds = max(300, int(os.environ.get("HARNESS_QUALITY_WATCHDOG_HORIZON_SECONDS", "86400")))
        self._recover_orphaned_work_after_restart()

    def _recover_orphaned_work_after_restart(self) -> None:
        now = _utc_now()
        recovered_runs = 0
        recovered_repairs = 0

        with self._file_lock:
            state = self._load_state()
            changed = False

            for run in state.get("runs", []):
                status = str(run.get("status", ""))
                if status not in {"queued", "running"}:
                    continue

                run["status"] = "error"
                run["finished_at"] = now
                run["error"] = run.get("error") or f"Recovered after server restart while {status}"
                run["recovery"] = {
                    "recovered": True,
                    "scope": status,
                    "at": now,
                }
                recovered_runs += 1
                changed = True

            for repair in state.get("repairs", []):
                status = str(repair.get("status", ""))
                if status not in {"queued", "in_progress"}:
                    continue

                repair["status"] = "blocked"
                repair["finished_at"] = now
                reason = f"Recovered after server restart while {status}"
                repair["blocked_reason"] = reason
                repair.setdefault("validation", {})
                repair["validation"].update(
                    {
                        "status": "blocked",
                        "improved": False,
                        "reason": reason,
                    }
                )
                repair.setdefault("transitions", []).append(
                    {
                        "status": "blocked",
                        "at": now,
                        "reason": "recovered_after_restart",
                    }
                )
                repair["recovery"] = {
                    "recovered": True,
                    "scope": status,
                    "at": now,
                }
                recovered_repairs += 1
                changed = True

            if changed:
                self._save_state(state)

        if recovered_runs or recovered_repairs:
            logger.warning(
                "Recovered orphaned work after restart: runs=%s repairs=%s",
                recovered_runs,
                recovered_repairs,
            )

    def _parse_timestamp(self, value: Any) -> Optional[datetime]:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except Exception:
            return None

    def _seconds_since(self, value: Any) -> Optional[float]:
        parsed = self._parse_timestamp(value)
        if parsed is None:
            return None
        delta = (datetime.now(timezone.utc) - parsed).total_seconds()
        return max(0.0, float(delta))

    def _apply_watchdogs(self) -> None:
        now = _utc_now()
        with self._file_lock:
            state = self._load_state()
            changed = False

            for run in state.get("runs", []):
                status = str(run.get("status", ""))
                if status not in {"queued", "running"}:
                    continue

                anchor = run.get("started_at") if status == "running" else run.get("created_at")
                if anchor is None:
                    anchor = run.get("created_at") or run.get("started_at")
                age_seconds = self._seconds_since(anchor)
                if age_seconds is None or age_seconds < self._run_timeout_seconds:
                    continue

                scope = "execution" if status == "running" else "queue"
                reason = f"Run watchdog timeout while {scope}"
                run["status"] = "error"
                run["finished_at"] = now
                run["error"] = run.get("error") or reason
                run["watchdog"] = {
                    "timed_out": True,
                    "scope": scope,
                    "age_seconds": round(age_seconds, 2),
                    "at": now,
                }
                changed = True

            for repair in state.get("repairs", []):
                status = str(repair.get("status", ""))
                if status not in {"queued", "in_progress"}:
                    continue

                anchor = repair.get("started_at") if status == "in_progress" else repair.get("created_at")
                if anchor is None:
                    anchor = repair.get("created_at") or repair.get("started_at")
                age_seconds = self._seconds_since(anchor)
                if age_seconds is None or age_seconds < self._repair_timeout_seconds:
                    continue

                reason = f"Repair watchdog timeout while {status}"
                repair["status"] = "blocked"
                repair["finished_at"] = now
                repair["blocked_reason"] = reason
                repair["watchdog"] = {
                    "timed_out": True,
                    "scope": status,
                    "age_seconds": round(age_seconds, 2),
                    "at": now,
                }
                repair.setdefault("validation", {})
                repair["validation"].update(
                    {
                        "status": "blocked",
                        "improved": False,
                        "reason": reason,
                        "policy": {
                            "timeout_seconds": self._repair_timeout_seconds,
                        },
                    }
                )
                repair.setdefault("transitions", []).append(
                    {
                        "status": "blocked",
                        "at": now,
                        "reason": "watchdog_timeout",
                        "age_seconds": round(age_seconds, 2),
                    }
                )
                changed = True

            if changed:
                self._save_state(state)

    def _default_state(self) -> Dict[str, Any]:
        return {
            "scenario_state": {},
            "runs": [],
            "repairs": [],
            "safety": {
                "allow_write_runs": False,
                "updated_at": None,
            },
        }

    def _load_state(self) -> Dict[str, Any]:
        state = _safe_read_json(CONTROL_STATE_FILE, self._default_state())
        if not isinstance(state, dict):
            return self._default_state()
        state.setdefault("scenario_state", {})
        state.setdefault("runs", [])
        state.setdefault("repairs", [])
        state.setdefault("safety", {"allow_write_runs": False, "updated_at": None})
        return state

    def _save_state(self, state: Dict[str, Any]) -> None:
        state["runs"] = self._trim_history(
            state.get("runs", []),
            limit=self._max_runs_history,
            active_statuses={"queued", "running"},
        )
        state["repairs"] = self._trim_history(
            state.get("repairs", []),
            limit=self._max_repairs_history,
            active_statuses={"queued", "in_progress"},
        )
        _atomic_write_json(CONTROL_STATE_FILE, state)

    def _history_timestamp(self, item: Dict[str, Any]) -> str:
        return str(item.get("created_at") or item.get("started_at") or item.get("finished_at") or "")

    def _trim_history(self, items: List[Dict[str, Any]], *, limit: int, active_statuses: set[str]) -> List[Dict[str, Any]]:
        if limit <= 0:
            return []
        if len(items) <= limit:
            return items

        active = [item for item in items if str(item.get("status", "")) in active_statuses]
        terminal = [item for item in items if str(item.get("status", "")) not in active_statuses]

        active_sorted = sorted(active, key=self._history_timestamp, reverse=True)
        terminal_sorted = sorted(terminal, key=self._history_timestamp, reverse=True)

        kept: List[Dict[str, Any]] = active_sorted[:limit]
        if len(kept) < limit:
            kept.extend(terminal_sorted[: limit - len(kept)])
        return kept

    def _load_scenario_spec(self) -> Dict[str, Any]:
        payload = _safe_read_json(DEFAULT_SCENARIO_FILE, {"defaults": {}, "scenarios": []})
        if not isinstance(payload, dict):
            return {"defaults": {}, "scenarios": []}
        payload.setdefault("defaults", {})
        payload.setdefault("scenarios", [])
        return payload

    def _save_scenario_spec(self, payload: Dict[str, Any]) -> None:
        _atomic_write_json(DEFAULT_SCENARIO_FILE, payload)

    def _scenario_ids(self) -> set[str]:
        spec = self._load_scenario_spec()
        return {scenario.get("id") for scenario in spec.get("scenarios", []) if scenario.get("id")}

    def _resolve_target_scenarios(self, request: Dict[str, Any]) -> List[Dict[str, Any]]:
        spec = self._load_scenario_spec()
        scenarios = spec.get("scenarios", [])
        target_type = request.get("target_type", "suite")
        if target_type == "suite":
            suite = request.get("suite")
            return [s for s in scenarios if suite in (s.get("suites") or [])]
        if target_type == "scenario":
            wanted = set(request.get("scenario_ids") or [])
            return [s for s in scenarios if s.get("id") in wanted]
        return scenarios

    def _is_scenario_write_capable(self, scenario: Dict[str, Any]) -> bool:
        required_tools = scenario.get("checks", {}).get("required_tools", []) or []
        risky_tools = [tool for tool in required_tools if self._is_tool_write_capable(tool)]
        prompt_write = self._is_prompt_write_capable(str(scenario.get("prompt", "")))
        return bool(risky_tools or prompt_write)

    def _is_tool_write_capable(self, tool_name: str) -> bool:
        # Generic capability risk classification based on operation verbs.
        risky_tokens = (
            "create",
            "update",
            "delete",
            "remove",
            "send",
            "upload",
            "write",
            "save",
            "share",
            "complete",
            "assign",
            "draft",
            "reply",
            "post",
            "sync_now",
        )
        normalized = (tool_name or "").lower()
        return any(token in normalized for token in risky_tokens)

    def _is_prompt_write_capable(self, prompt: str) -> bool:
        risky_phrases = (
            "create",
            "update",
            "delete",
            "send",
            "save",
            "upload",
            "write",
            "draft",
            "reply",
            "share",
            "post",
            "publish",
            "schedule",
            "organize",
        )
        text = (prompt or "").lower()
        return any(phrase in text for phrase in risky_phrases)

    def assess_run_risk(self, request: Dict[str, Any]) -> Dict[str, Any]:
        targets = self._resolve_target_scenarios(request)
        write_capable: List[Dict[str, Any]] = []
        for scenario in targets:
            required_tools = scenario.get("checks", {}).get("required_tools", []) or []
            risky_tools = [tool for tool in required_tools if self._is_tool_write_capable(tool)]
            prompt_write = self._is_prompt_write_capable(str(scenario.get("prompt", "")))
            if risky_tools or prompt_write:
                write_capable.append(
                    {
                        "id": scenario.get("id"),
                        "name": scenario.get("name", scenario.get("id", "unknown")),
                        "risky_tools": risky_tools,
                        "prompt_write": prompt_write,
                    }
                )

        return {
            "target_count": len(targets),
            "write_capable_count": len(write_capable),
            "write_capable_scenarios": write_capable,
        }

    def _run_baseline_metrics(self, source_run_id: str) -> Dict[str, Any]:
        if source_run_id == "latest":
            campaign = _safe_read_json(LATEST_REPORTS_DIR / "campaign_report.json", {})
            scenario_report = _safe_read_json(LATEST_REPORTS_DIR / "scenario_report.json", {})
        else:
            run = self.get_run(source_run_id)
            if not run:
                return {
                    "source": source_run_id,
                    "pass_rate": 0.0,
                    "passed": 0,
                    "failed": 0,
                    "total": 0,
                    "failed_ids": [],
                }
            campaign = run.get("campaign_report", {})
            scenario_report = run.get("scenario_report", {})

        return {
            "source": source_run_id,
            "pass_rate": float(campaign.get("final_pass_rate", 0.0) or 0.0),
            "passed": int(scenario_report.get("passed", 0) or 0),
            "failed": int(scenario_report.get("failed", 0) or 0),
            "total": int(scenario_report.get("total", 0) or 0),
            "failed_ids": list(campaign.get("final_failed_ids", []) or []),
        }

    def _build_playbook(self, categories: List[str]) -> List[Dict[str, str]]:
        plan: List[Dict[str, str]] = []

        def add(step_id: str, title: str) -> None:
            if all(item["id"] != step_id for item in plan):
                plan.append({"id": step_id, "title": title})

        for category in categories:
            normalized = str(category or "unknown").lower()
            if normalized in {"tool_failed", "missing_tool", "connector_error", "configuration"}:
                add("connector_preflight", "Run connector preflight and credential presence checks")
                add("tool_contract_scan", "Run primitive tool-contract scan")
            if normalized == "missing_output":
                add("evaluator_preflight", "Run evaluator and output-pattern preflight checks")
                add("orchestration_preflight", "Run orchestration configuration preflight checks")

        if not plan:
            add("orchestration_preflight", "Run orchestration configuration preflight checks")
        return plan

    def _execute_playbook_step(self, step_id: str) -> Dict[str, Any]:
        if step_id == "connector_preflight":
            try:
                from connectors.credentials import get_credential_store
                from connectors.registry import get_registry

                registry = get_registry()
                credential_store = get_credential_store()
                total = 0
                with_credentials = 0
                for metadata in registry.list_connectors():
                    total += 1
                    if credential_store.has_valid(metadata.provider):
                        with_credentials += 1
                return {
                    "ok": True,
                    "details": f"connectors={total} with_valid_credentials={with_credentials}",
                }
            except Exception as exc:
                return {"ok": False, "details": f"connector_preflight_failed: {exc}"}

        if step_id == "tool_contract_scan":
            try:
                spec = self._load_scenario_spec()
                missing = 0
                for scenario in spec.get("scenarios", []):
                    if not scenario.get("prompt"):
                        missing += 1
                return {
                    "ok": True,
                    "details": f"scenarios={len(spec.get('scenarios', []))} missing_prompt={missing}",
                }
            except Exception as exc:
                return {"ok": False, "details": f"tool_contract_scan_failed: {exc}"}

        if step_id == "evaluator_preflight":
            try:
                report = _safe_read_json(LATEST_REPORTS_DIR / "harness_report.json", {})
                diagnostics = report.get("campaign_iteration", {}).get("diagnosed_failures", [])
                return {
                    "ok": True,
                    "details": f"diagnosed_failures_available={len(diagnostics)}",
                }
            except Exception as exc:
                return {"ok": False, "details": f"evaluator_preflight_failed: {exc}"}

        if step_id == "orchestration_preflight":
            try:
                spec = self._load_scenario_spec()
                defaults = spec.get("defaults", {}) if isinstance(spec, dict) else {}
                timeout = int(defaults.get("timeout_seconds", 0) or 0)
                return {
                    "ok": True,
                    "details": f"defaults_present={bool(defaults)} timeout_seconds={timeout}",
                }
            except Exception as exc:
                return {"ok": False, "details": f"orchestration_preflight_failed: {exc}"}

        return {"ok": False, "details": f"unknown_playbook_step={step_id}"}

    async def _wait_for_run_completion(self, run_id: str, timeout_seconds: int = 1800) -> Optional[Dict[str, Any]]:
        waited = 0
        while waited < timeout_seconds:
            run = self.get_run(run_id)
            if not run:
                return None
            if run.get("status") in {"passed", "failed", "error"}:
                return run
            await asyncio.sleep(1)
            waited += 1
        return self.get_run(run_id)

    def _repair_delta_metrics(self, before: Dict[str, Any], after_run: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        after_summary = (after_run or {}).get("summary", {})
        after_campaign = (after_run or {}).get("campaign_report", {})
        after = {
            "pass_rate": float(after_summary.get("final_pass_rate", 0.0) or 0.0),
            "passed": int(after_summary.get("passed", 0) or 0),
            "failed": int(after_summary.get("failed", 0) or 0),
            "total": int(after_summary.get("total", 0) or 0),
            "failed_ids": list(after_campaign.get("final_failed_ids", after_summary.get("final_failed_ids", []) or [])),
            "status": (after_run or {}).get("status"),
        }
        return {
            "before": before,
            "after": after,
            "delta": {
                "pass_rate": round(after["pass_rate"] - float(before.get("pass_rate", 0.0) or 0.0), 4),
                "passed": after["passed"] - int(before.get("passed", 0) or 0),
                "failed": after["failed"] - int(before.get("failed", 0) or 0),
            },
        }

    def _evaluate_repair_validation(self, delta: Dict[str, Any], rerun: Dict[str, Any]) -> Dict[str, Any]:
        before = delta.get("before", {})
        after = delta.get("after", {})
        change = delta.get("delta", {})

        if not rerun.get("queued"):
            return {
                "status": "blocked",
                "improved": False,
                "reason": rerun.get("error", "Targeted rerun was not queued"),
                "policy": {
                    "min_pass_rate_delta": 0.02,
                    "require_failed_delta": True,
                },
            }

        if rerun.get("final_status") == "error":
            return {
                "status": "blocked",
                "improved": False,
                "reason": "Targeted rerun errored",
                "policy": {
                    "min_pass_rate_delta": 0.02,
                    "require_failed_delta": True,
                },
            }

        pass_rate_delta = float(change.get("pass_rate", 0.0) or 0.0)
        failed_delta = int(change.get("failed", 0) or 0)
        cleared_failures = int(before.get("failed", 0) or 0) > 0 and int(after.get("failed", 0) or 0) == 0

        improved = bool(cleared_failures or failed_delta < 0 or pass_rate_delta >= 0.02)
        return {
            "status": "validated" if improved else "blocked",
            "improved": improved,
            "reason": (
                "Repair validated: targeted rerun improved measurable outcomes"
                if improved
                else "Repair blocked: no measurable improvement against validation policy"
            ),
            "policy": {
                "min_pass_rate_delta": 0.02,
                "require_failed_delta": True,
                "cleared_failures": cleared_failures,
            },
        }

    def get_repair(self, repair_id: str) -> Optional[Dict[str, Any]]:
        state = self._load_state()
        for repair in state.get("repairs", []):
            if repair.get("id") == repair_id:
                return dict(repair)
        return None

    def _repair_transition(self, repair_id: str, status: str, extra: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        with self._file_lock:
            state = self._load_state()
            for repair in state.get("repairs", []):
                if repair.get("id") != repair_id:
                    continue
                repair["status"] = status
                transitions = repair.setdefault("transitions", [])
                entry = {"status": status, "at": _utc_now()}
                if extra:
                    entry.update(extra)
                    repair.update(extra)
                transitions.append(entry)
                self._save_state(state)
                return dict(repair)
        return None

    def _ensure_repair_worker(self) -> None:
        if self._repair_worker_task is None or self._repair_worker_task.done():
            self._repair_worker_task = asyncio.create_task(self._repair_worker_loop())

    def _track_repair_task(self, repair_id: str, task: asyncio.Task) -> None:
        self._active_repair_tasks[repair_id] = task

        def _done(_: asyncio.Task) -> None:
            self._active_repair_tasks.pop(repair_id, None)

        task.add_done_callback(_done)

    async def _execute_repair_with_limit(self, repair_id: str) -> None:
        async with self._repair_semaphore:
            self._repair_workers_in_flight += 1
            self._repair_max_active_observed = max(self._repair_max_active_observed, self._repair_workers_in_flight)
            try:
                await self._execute_repair(repair_id)
            finally:
                self._repair_workers_in_flight = max(0, self._repair_workers_in_flight - 1)

    async def _repair_worker_loop(self) -> None:
        while True:
            repair_id = await self._repair_queue.get()
            try:
                task = asyncio.create_task(self._execute_repair_with_limit(repair_id))
                self._track_repair_task(repair_id, task)
            except Exception as exc:
                logger.exception("Repair execution failed unexpectedly: %s", exc)
                self._repair_transition(repair_id, "blocked", {"error": str(exc), "finished_at": _utc_now()})
            finally:
                self._repair_queue.task_done()

    async def _execute_repair(self, repair_id: str) -> None:
        state = self._load_state()
        repair = next((item for item in state.get("repairs", []) if item.get("id") == repair_id), None)
        if not repair:
            return

        attempt_count = int(repair.get("attempt_count", 0) or 0) + 1
        self._repair_transition(repair_id, repair.get("status", "queued"), {"attempt_count": attempt_count})

        if not repair.get("eligible_failures"):
            self._repair_transition(
                repair_id,
                "blocked",
                {
                    "started_at": _utc_now(),
                    "finished_at": _utc_now(),
                    "blocked_reason": "No eligible failures for generic remediation",
                    "playbook_results": [],
                },
            )
            return

        self._repair_transition(repair_id, "in_progress", {"started_at": _utc_now()})

        categories = repair.get("failure_categories", [])
        playbook = self._build_playbook(categories)
        playbook_results: List[Dict[str, Any]] = []
        for step in playbook:
            result = self._execute_playbook_step(step["id"])
            playbook_results.append(
                {
                    "id": step["id"],
                    "title": step["title"],
                    "ok": bool(result.get("ok", False)),
                    "details": result.get("details", ""),
                    "at": _utc_now(),
                }
            )

        baseline = self._run_baseline_metrics(str(repair.get("source_run_id") or "latest"))
        self._repair_transition(
            repair_id,
            "in_progress",
            {
                "playbook_results": playbook_results,
                "baseline_metrics": baseline,
            },
        )

        if not all(item.get("ok", False) for item in playbook_results):
            self._repair_transition(
                repair_id,
                "blocked",
                {
                    "finished_at": _utc_now(),
                    "blocked_reason": "One or more remediation playbook steps failed",
                },
            )
            return

        rerun_info: Dict[str, Any] = {"queued": False}
        if repair.get("auto_rerun") and repair.get("scenario_ids"):
            try:
                rerun_run = await self.queue_run(
                    {
                        "target_type": "scenario",
                        "scenario_ids": repair.get("scenario_ids", []),
                        "iterations": 1,
                        "rerun_failed_only": True,
                        "auto_approve": True,
                        "repair_id": repair_id,
                    }
                )
                rerun_id = rerun_run.get("id")
                completed = await self._wait_for_run_completion(str(rerun_id), timeout_seconds=1800)
                rerun_info = {
                    "queued": True,
                    "run_id": rerun_id,
                    "final_status": (completed or {}).get("status"),
                }
                delta = self._repair_delta_metrics(baseline, completed)
                validation = self._evaluate_repair_validation(delta, rerun_info)
                self._repair_transition(
                    repair_id,
                    validation.get("status", "blocked"),
                    {
                        "finished_at": _utc_now(),
                        "rerun": rerun_info,
                        "delta_metrics": delta,
                        "validation": validation,
                    },
                )
                return
            except ValueError as exc:
                rerun_info = {
                    "queued": False,
                    "error": str(exc),
                }

        self._repair_transition(
            repair_id,
            "blocked",
            {
                "finished_at": _utc_now(),
                "rerun": rerun_info,
                "delta_metrics": {
                    "before": baseline,
                    "after": None,
                    "delta": {},
                },
                "validation": self._evaluate_repair_validation({"before": baseline, "after": None, "delta": {}}, rerun_info),
            },
        )

    def get_environment_info(self) -> Dict[str, Any]:
        is_codespaces = os.environ.get("CODESPACES", "").lower() == "true" or bool(
            os.environ.get("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN")
        )
        return {
            "runtime": "codespaces" if is_codespaces else "local",
            "label": "Codespaces" if is_codespaces else "Local",
            "safety_model": "strict-write-guard",
        }

    def get_safety_settings(self) -> Dict[str, Any]:
        state = self._load_state()
        safety = state.get("safety", {})
        return {
            "allow_write_runs": bool(safety.get("allow_write_runs", False)),
            "updated_at": safety.get("updated_at"),
        }

    def update_safety_settings(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        with self._file_lock:
            state = self._load_state()
            safety = state.setdefault("safety", {"allow_write_runs": False, "updated_at": None})
            if "allow_write_runs" in updates and updates["allow_write_runs"] is not None:
                safety["allow_write_runs"] = bool(updates["allow_write_runs"])
            safety["updated_at"] = _utc_now()
            self._save_state(state)
            return {
                "allow_write_runs": bool(safety.get("allow_write_runs", False)),
                "updated_at": safety.get("updated_at"),
            }

    def _load_latest_results(self) -> Dict[str, Dict[str, Any]]:
        report = _safe_read_json(LATEST_REPORTS_DIR / "scenario_report.json", {})
        results = report.get("results", []) if isinstance(report, dict) else []
        by_id: Dict[str, Dict[str, Any]] = {}
        for item in results:
            scenario_id = item.get("id")
            if scenario_id:
                by_id[scenario_id] = item
        return by_id

    def get_scenario_catalog(self) -> Dict[str, Any]:
        spec = self._load_scenario_spec()
        state = self._load_state()
        latest_results = self._load_latest_results()
        scenario_state = state.get("scenario_state", {})

        items: List[Dict[str, Any]] = []
        for scenario in spec.get("scenarios", []):
            scenario_id = scenario.get("id")
            if not scenario_id:
                continue
            persisted = scenario_state.get(scenario_id, {})
            latest = latest_results.get(scenario_id, {})
            items.append(
                {
                    "id": scenario_id,
                    "name": scenario.get("name", scenario_id),
                    "prompt": scenario.get("prompt", ""),
                    "suites": scenario.get("suites", []),
                    "required_tools": scenario.get("checks", {}).get("required_tools", []),
                    "required_output_patterns": scenario.get("checks", {}).get("required_output_patterns", []),
                    "completed": bool(persisted.get("completed", False)),
                    "enabled": bool(persisted.get("enabled", True)),
                    "notes": persisted.get("notes", ""),
                    "last_result": {
                        "passed": latest.get("passed"),
                        "duration_seconds": latest.get("duration_seconds"),
                        "issues": latest.get("issues", []),
                        "tool_names": latest.get("tool_names", []),
                    },
                }
            )

        return {
            "generated_at": _utc_now(),
            "total": len(items),
            "completed": sum(1 for item in items if item["completed"]),
            "enabled": sum(1 for item in items if item["enabled"]),
            "items": items,
        }

    def add_scenario(self, scenario: Dict[str, Any]) -> Dict[str, Any]:
        with self._file_lock:
            payload = self._load_scenario_spec()
            scenarios = payload.get("scenarios", [])

            scenario_id = str(scenario.get("id", "")).strip()
            if not scenario_id:
                raise ValueError("Scenario id is required")
            if scenario_id in {item.get("id") for item in scenarios}:
                raise ValueError(f"Scenario already exists: {scenario_id}")

            name = str(scenario.get("name", "")).strip()
            prompt = str(scenario.get("prompt", "")).strip()
            if not name or not prompt:
                raise ValueError("Scenario name and prompt are required")

            checks = scenario.get("checks") or {}
            normalized = {
                "id": scenario_id,
                "name": name,
                "suites": scenario.get("suites") or ["nightly"],
                "prompt": prompt,
                "checks": {
                    "required_tools": checks.get("required_tools") or [],
                    "required_output_patterns": checks.get("required_output_patterns") or [],
                    "forbidden_error_patterns": checks.get("forbidden_error_patterns") or [],
                    "max_failed_steps": int(checks.get("max_failed_steps", 0) or 0),
                },
            }

            for optional_key in ("orchestration_mode", "timeout_seconds", "max_approvals"):
                if scenario.get(optional_key) is not None:
                    normalized[optional_key] = scenario.get(optional_key)

            scenarios.append(normalized)
            payload["scenarios"] = scenarios
            self._save_scenario_spec(payload)
            return normalized

    def update_scenario_state(self, scenario_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        if scenario_id not in self._scenario_ids():
            raise KeyError(scenario_id)

        with self._file_lock:
            state = self._load_state()
            scenario_state = state.setdefault("scenario_state", {})
            current = scenario_state.setdefault(scenario_id, {"enabled": True, "completed": False, "notes": ""})

            for field in ("enabled", "completed"):
                if field in updates and updates[field] is not None:
                    current[field] = bool(updates[field])
            if "notes" in updates and updates["notes"] is not None:
                current["notes"] = str(updates["notes"])
            current["updated_at"] = _utc_now()

            self._save_state(state)
            return current

    def get_runs(self) -> Dict[str, Any]:
        self._apply_watchdogs()
        state = self._load_state()
        runs = sorted(state.get("runs", []), key=lambda item: item.get("created_at", ""), reverse=True)
        active = next((run for run in runs if run.get("status") == "running"), None)
        queued = [run for run in runs if run.get("status") == "queued"]
        return {
            "generated_at": _utc_now(),
            "active": active,
            "queued": queued,
            "items": runs[:20],
        }

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        self._apply_watchdogs()
        state = self._load_state()
        for run in state.get("runs", []):
            if run.get("id") == run_id:
                details = dict(run)
                out_dir = Path(details.get("out_dir") or "")
                if out_dir.exists():
                    details["campaign_report"] = _safe_read_json(out_dir / "campaign_report.json", {})
                    details["harness_report"] = _safe_read_json(out_dir / "harness_report.json", {})
                    details["scenario_report"] = _safe_read_json(out_dir / "scenario_report.json", {})
                return details
        return None

    def get_run_log(self, run_id: str, *, tail_lines: int = 200) -> Dict[str, Any]:
        run = self.get_run(run_id)
        if not run:
            return {"found": False, "run_id": run_id, "log": ""}

        log_path = Path(run.get("log_path") or "")
        if not log_path.exists():
            return {"found": True, "run_id": run_id, "log": "", "status": run.get("status")}

        try:
            content = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            snippet = "\n".join(content[-max(1, tail_lines):])
        except Exception as exc:
            snippet = f"Unable to read log: {exc}"

        return {
            "found": True,
            "run_id": run_id,
            "status": run.get("status"),
            "log": snippet,
            "line_count": len(content) if 'content' in locals() else 0,
        }

    def get_failure_insights(self) -> Dict[str, Any]:
        self._apply_watchdogs()
        harness = _safe_read_json(LATEST_REPORTS_DIR / "harness_report.json", {})
        campaign = _safe_read_json(LATEST_REPORTS_DIR / "campaign_report.json", {})
        iteration = harness.get("campaign_iteration", {}) if isinstance(harness, dict) else {}
        connector_hotspots = iteration.get("connector_hotspots", {}) if isinstance(iteration, dict) else {}
        issue_categories = iteration.get("issue_categories", {}) if isinstance(iteration, dict) else {}
        diagnosed = iteration.get("diagnosed_failures", []) if isinstance(iteration, dict) else []

        clusters = [
            {"name": key, "count": value, "type": "connector"}
            for key, value in sorted(connector_hotspots.items(), key=lambda item: item[1], reverse=True)
        ]
        clusters.extend(
            {"name": key, "count": value, "type": "category"}
            for key, value in sorted(issue_categories.items(), key=lambda item: item[1], reverse=True)
        )

        state = self._load_state()
        repairs = sorted(state.get("repairs", []), key=lambda item: item.get("created_at", ""), reverse=True)
        repair_metrics = self._compute_repair_metrics(repairs)

        return {
            "generated_at": _utc_now(),
            "latest_failed_ids": campaign.get("final_failed_ids", []),
            "rerun_queue": iteration.get("rerun_queue", []),
            "clusters": clusters,
            "diagnosed_failures": diagnosed,
            "repairs": repairs[:20],
            "repair_metrics": repair_metrics,
        }

    def _compute_repair_metrics(self, repairs: List[Dict[str, Any]]) -> Dict[str, Any]:
        counts = {
            "queued": 0,
            "in_progress": 0,
            "validated": 0,
            "blocked": 0,
            "other": 0,
        }
        completed = 0
        improved = 0
        durations: List[float] = []

        for repair in repairs:
            status = str(repair.get("status", "other"))
            if status in counts:
                counts[status] += 1
            else:
                counts["other"] += 1

            validation = repair.get("validation", {}) or {}
            if status in {"validated", "blocked"}:
                completed += 1
                if bool(validation.get("improved", False)):
                    improved += 1

            started_at = repair.get("started_at")
            finished_at = repair.get("finished_at")
            if started_at and finished_at:
                try:
                    started = datetime.fromisoformat(str(started_at))
                    finished = datetime.fromisoformat(str(finished_at))
                    durations.append(max(0.0, (finished - started).total_seconds()))
                except Exception:
                    pass

        active_count = self._repair_workers_in_flight
        avg_duration = round(sum(durations) / len(durations), 2) if durations else 0.0
        validated_rate = round((counts["validated"] / completed), 4) if completed else 0.0
        improvement_rate = round((improved / completed), 4) if completed else 0.0

        return {
            "queue_depth": self._repair_queue.qsize(),
            "active_workers": active_count,
            "configured_workers": self._repair_concurrency,
            "max_active_observed": self._repair_max_active_observed,
            "status_counts": counts,
            "completed": completed,
            "validated_rate": validated_rate,
            "improvement_rate": improvement_rate,
            "avg_completion_seconds": avg_duration,
        }

    def _summarize_age(self, values: List[float]) -> Dict[str, float]:
        if not values:
            return {
                "max": 0.0,
                "avg": 0.0,
            }
        return {
            "max": round(max(values), 2),
            "avg": round(sum(values) / len(values), 2),
        }

    def get_runtime_diagnostics(self) -> Dict[str, Any]:
        self._apply_watchdogs()
        state = self._load_state()

        runs = state.get("runs", [])
        repairs = state.get("repairs", [])

        queued_run_ids = [item.get("id") for item in runs if item.get("status") == "queued" and item.get("id")]
        running_run_ids = [item.get("id") for item in runs if item.get("status") == "running" and item.get("id")]
        queued_repair_ids = [item.get("id") for item in repairs if item.get("status") == "queued" and item.get("id")]
        active_repair_ids = [item.get("id") for item in repairs if item.get("status") == "in_progress" and item.get("id")]

        queued_run_ages = [
            age
            for age in (self._seconds_since(item.get("created_at")) for item in runs if item.get("status") == "queued")
            if age is not None
        ]
        running_run_ages = [
            age
            for age in (
                self._seconds_since(item.get("started_at") or item.get("created_at"))
                for item in runs
                if item.get("status") == "running"
            )
            if age is not None
        ]
        queued_repair_ages = [
            age
            for age in (self._seconds_since(item.get("created_at")) for item in repairs if item.get("status") == "queued")
            if age is not None
        ]
        active_repair_ages = [
            age
            for age in (
                self._seconds_since(item.get("started_at") or item.get("created_at"))
                for item in repairs
                if item.get("status") == "in_progress"
            )
            if age is not None
        ]

        return {
            "generated_at": _utc_now(),
            "timeouts": {
                "run_seconds": self._run_timeout_seconds,
                "repair_seconds": self._repair_timeout_seconds,
            },
            "retention": {
                "max_run_history": self._max_runs_history,
                "max_repair_history": self._max_repairs_history,
            },
            "runs": {
                "queued": len(queued_run_ids),
                "running": len(running_run_ids),
                "queued_ids": queued_run_ids[:8],
                "running_ids": running_run_ids[:8],
                "queued_age_seconds": self._summarize_age(queued_run_ages),
                "running_age_seconds": self._summarize_age(running_run_ages),
            },
            "repairs": {
                "queued": len(queued_repair_ids),
                "in_progress": len(active_repair_ids),
                "queued_ids": queued_repair_ids[:8],
                "in_progress_ids": active_repair_ids[:8],
                "queued_age_seconds": self._summarize_age(queued_repair_ages),
                "in_progress_age_seconds": self._summarize_age(active_repair_ages),
                "active_task_ids": list(self._active_repair_tasks.keys())[:8],
            },
        }

    def _count_recent_watchdog_timeouts(self, runs: List[Dict[str, Any]], repairs: List[Dict[str, Any]]) -> int:
        cutoff = datetime.now(timezone.utc).timestamp() - self._quality_watchdog_horizon_seconds
        total = 0
        for item in runs + repairs:
            watchdog = item.get("watchdog") if isinstance(item, dict) else None
            if not isinstance(watchdog, dict):
                continue
            if not bool(watchdog.get("timed_out", False)):
                continue
            at = self._parse_timestamp(watchdog.get("at"))
            if at is None:
                continue
            if at.timestamp() >= cutoff:
                total += 1
        return total

    def get_quality_gate_status(self) -> Dict[str, Any]:
        diagnostics = self.get_runtime_diagnostics()
        state = self._load_state()
        repairs = state.get("repairs", [])
        runs = state.get("runs", [])
        insights = self.get_failure_insights()
        metrics = insights.get("repair_metrics", {})

        queue_depth = int(metrics.get("queue_depth", 0) or 0)
        active_workers = int(metrics.get("active_workers", 0) or 0)
        configured_workers = int(metrics.get("configured_workers", 0) or 0)
        max_active_observed = int(metrics.get("max_active_observed", 0) or 0)
        recent_watchdog_timeouts = self._count_recent_watchdog_timeouts(runs, repairs)

        checks = [
            {
                "name": "worker_bound_respected",
                "ok": active_workers <= max(1, configured_workers) and max_active_observed <= max(1, configured_workers),
                "details": f"active={active_workers} max_observed={max_active_observed} configured={configured_workers}",
            },
            {
                "name": "queue_depth_within_limit",
                "ok": queue_depth <= self._quality_queue_depth_limit,
                "details": f"queue_depth={queue_depth} limit={self._quality_queue_depth_limit}",
            },
            {
                "name": "no_recent_watchdog_timeouts",
                "ok": recent_watchdog_timeouts == 0,
                "details": f"recent_timeouts={recent_watchdog_timeouts} horizon_seconds={self._quality_watchdog_horizon_seconds}",
            },
        ]
        ready = all(bool(check.get("ok", False)) for check in checks)

        return {
            "generated_at": _utc_now(),
            "ready_for_scenario_testing": ready,
            "checks": checks,
            "runtime": diagnostics,
            "thresholds": {
                "queue_depth_limit": self._quality_queue_depth_limit,
                "watchdog_horizon_seconds": self._quality_watchdog_horizon_seconds,
            },
        }

    def queue_repair(self, request: Dict[str, Any]) -> Dict[str, Any]:
        source_run_id = str(request.get("source_run_id") or "latest")
        strategy = str(request.get("strategy") or "generic-remediation")
        max_fix_attempts = int(request.get("max_fix_attempts", 1) or 1)
        auto_rerun = bool(request.get("auto_rerun", True))
        notes = str(request.get("notes") or "")

        diagnosed = []
        if source_run_id == "latest":
            insights = self.get_failure_insights()
            diagnosed = insights.get("diagnosed_failures", [])
        else:
            run = self.get_run(source_run_id)
            if not run:
                raise ValueError(f"Unknown run id: {source_run_id}")
            diagnosed = (
                run.get("harness_report", {})
                .get("campaign_iteration", {})
                .get("diagnosed_failures", [])
            )

        if not diagnosed:
            raise ValueError("No diagnosed failures available for repair planning")

        repair = build_repair_request(
            source_run_id=source_run_id,
            diagnosed_failures=diagnosed,
            strategy=strategy,
            max_fix_attempts=max_fix_attempts,
            auto_rerun=auto_rerun,
            notes=notes,
        ).to_dict()
        repair["transitions"] = [{"status": "queued", "at": _utc_now()}]
        repair["playbook_results"] = []
        repair["baseline_metrics"] = None
        repair["delta_metrics"] = None
        repair["rerun"] = None
        repair["attempt_count"] = 0
        repair["started_at"] = None
        repair["finished_at"] = None
        repair["blocked_reason"] = None

        with self._file_lock:
            state = self._load_state()
            state.setdefault("repairs", []).append(repair)
            self._save_state(state)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._repair_queue.put(repair["id"]))
            self._ensure_repair_worker()
        except RuntimeError:
            logger.warning("No running loop when queueing repair %s; deferred execution", repair["id"])

        return repair

    def retry_repair(self, repair_id: str) -> Dict[str, Any]:
        with self._file_lock:
            state = self._load_state()
            repair = next((item for item in state.get("repairs", []) if item.get("id") == repair_id), None)
            if not repair:
                raise ValueError(f"Unknown repair id: {repair_id}")

            status = str(repair.get("status", ""))
            if status not in {"blocked", "validated"}:
                raise ValueError(f"Repair {repair_id} is not retryable from status '{status}'")

            attempts = int(repair.get("attempt_count", 0) or 0)
            max_attempts = max(1, int(repair.get("max_fix_attempts", 1) or 1))
            if attempts >= max_attempts:
                raise ValueError(
                    f"Repair {repair_id} exceeded max attempts ({attempts}/{max_attempts}). Increase max_fix_attempts to retry."
                )

            repair["status"] = "queued"
            repair["blocked_reason"] = None
            repair["started_at"] = None
            repair["finished_at"] = None
            repair.setdefault("transitions", []).append(
                {
                    "status": "queued",
                    "at": _utc_now(),
                    "reason": "manual_retry",
                }
            )
            self._save_state(state)
            queued = dict(repair)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._repair_queue.put(repair_id))
            self._ensure_repair_worker()
        except RuntimeError:
            logger.warning("No running loop when retrying repair %s; deferred execution", repair_id)

        return queued

    async def queue_run(self, request: Dict[str, Any]) -> Dict[str, Any]:
        target_type = request.get("target_type", "suite")
        scenario_ids = request.get("scenario_ids") or []
        suite = request.get("suite")
        read_only_mode = bool(request.get("read_only_mode", False))

        if target_type == "scenario" and not scenario_ids:
            raise ValueError("scenario_ids is required for scenario runs")
        if target_type == "suite" and not suite:
            raise ValueError("suite is required for suite runs")

        if read_only_mode and target_type == "suite":
            suite_targets = self._resolve_target_scenarios({"target_type": "suite", "suite": suite})
            safe_ids = [scenario.get("id") for scenario in suite_targets if scenario.get("id") and not self._is_scenario_write_capable(scenario)]
            if not safe_ids:
                raise ValueError(f"No read-only scenarios available in suite '{suite}'")
            target_type = "scenario"
            scenario_ids = safe_ids

        safety = self.get_safety_settings()
        risk_request = {
            "target_type": target_type,
            "suite": suite,
            "scenario_ids": scenario_ids,
        }
        risk = self.assess_run_risk(risk_request)
        if risk.get("write_capable_count", 0) > 0 and not safety.get("allow_write_runs", False):
            blocked_ids = [item.get("id") for item in risk.get("write_capable_scenarios", [])[:8]]
            raise ValueError(
                "Write-capable scenarios are blocked by safety guard. "
                f"Blocked scenarios: {', '.join(blocked_ids)}. "
                "Enable write-capable runs in Dashboard Safety settings to proceed."
            )

        run_id = f"run-{uuid.uuid4().hex[:12]}"
        record = {
            "id": run_id,
            "target_type": target_type,
            "suite": suite,
            "scenario_ids": scenario_ids,
            "requested_suite": suite,
            "iterations": max(1, int(request.get("iterations", 1) or 1)),
            "rerun_failed_only": bool(request.get("rerun_failed_only", False)),
            "auto_approve": bool(request.get("auto_approve", True)),
            "read_only_mode": read_only_mode,
            "status": "queued",
            "created_at": _utc_now(),
            "started_at": None,
            "finished_at": None,
            "summary": {},
            "log_path": None,
            "out_dir": None,
            "risk": risk,
            "repair_id": request.get("repair_id"),
            "safety_snapshot": {
                "allow_write_runs": bool(safety.get("allow_write_runs", False)),
                "assessed_at": _utc_now(),
                "write_capable_count": risk.get("write_capable_count", 0),
            },
        }

        with self._file_lock:
            state = self._load_state()
            state.setdefault("runs", []).append(record)
            self._save_state(state)

        await self._queue.put(run_id)
        self._ensure_worker()
        return record

    def _ensure_worker(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker_loop())

    async def _worker_loop(self) -> None:
        while True:
            run_id = await self._queue.get()
            try:
                await self._execute_run(run_id)
            except Exception as exc:
                logger.exception("Harness run failed unexpectedly: %s", exc)
                self._update_run(run_id, {"status": "error", "finished_at": _utc_now(), "error": str(exc)})
            finally:
                self._queue.task_done()

    def _update_run(self, run_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        with self._file_lock:
            state = self._load_state()
            for run in state.get("runs", []):
                if run.get("id") == run_id:
                    run.update(updates)
                    self._save_state(state)
                    return run
        return None

    def _build_command(self, run_id: str, run: Dict[str, Any]) -> tuple[List[str], Path, Path]:
        out_dir = RUN_REPORTS_DIR / run_id
        log_path = out_dir / "runner.log"
        command = [
            sys.executable,
            "apex/tools/run_scenarios.py",
            "--base-url",
            "http://127.0.0.1:8000",
            "--scenario-file",
            "apex/scenarios/regression_scenarios.json",
            "--out-dir",
            str(out_dir.relative_to(ROOT_DIR)),
            "--iterations",
            str(run.get("iterations", 1)),
            "--allow-failures",
        ]

        if run.get("auto_approve", True):
            command.append("--auto-approve")
        if run.get("rerun_failed_only"):
            command.append("--rerun-failed-only")

        target_type = run.get("target_type")
        if target_type == "suite":
            command.extend(["--suite", run.get("suite", "core")])
        elif target_type == "scenario":
            for scenario_id in run.get("scenario_ids", []):
                command.extend(["--scenario", scenario_id])

        return command, out_dir, log_path

    async def _execute_run(self, run_id: str) -> None:
        current = self._update_run(run_id, {"status": "running", "started_at": _utc_now()})
        if current is None:
            return

        command, out_dir, log_path = self._build_command(run_id, current)
        out_dir.mkdir(parents=True, exist_ok=True)
        self._update_run(run_id, {"log_path": str(log_path), "out_dir": str(out_dir)})

        env = os.environ.copy()
        env["PYTHONPATH"] = f"{ROOT_DIR}:{APEX_DIR}:{env.get('PYTHONPATH', '')}".rstrip(":")

        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(ROOT_DIR),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        with log_path.open("wb") as log_handle:
            if process.stdout is not None:
                while True:
                    chunk = await process.stdout.readline()
                    if not chunk:
                        break
                    log_handle.write(chunk)
                    log_handle.flush()
            await process.wait()

        campaign = _safe_read_json(out_dir / "campaign_report.json", {})
        scenario_report = _safe_read_json(out_dir / "scenario_report.json", {})
        summary = {
            "final_pass_rate": campaign.get("final_pass_rate", 0),
            "final_failed_ids": campaign.get("final_failed_ids", []),
            "passed": scenario_report.get("passed", 0),
            "failed": scenario_report.get("failed", 0),
            "total": scenario_report.get("total", 0),
        }

        if campaign or scenario_report:
            self._promote_reports(out_dir)

        status = "passed"
        if process.returncode not in (0, None):
            status = "error"
        elif summary.get("final_failed_ids"):
            status = "failed"

        self._update_run(
            run_id,
            {
                "status": status,
                "finished_at": _utc_now(),
                "exit_code": process.returncode,
                "summary": summary,
            },
        )

    def _promote_reports(self, source_dir: Path) -> None:
        if LATEST_REPORTS_DIR.exists():
            shutil.rmtree(LATEST_REPORTS_DIR)
        shutil.copytree(source_dir, LATEST_REPORTS_DIR)


_CONTROL_PLANE: Optional[HarnessControlPlane] = None


def get_harness_control_plane() -> HarnessControlPlane:
    global _CONTROL_PLANE
    if _CONTROL_PLANE is None:
        _CONTROL_PLANE = HarnessControlPlane()
    return _CONTROL_PLANE