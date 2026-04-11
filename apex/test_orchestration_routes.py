import json
import asyncio

from orchestration import PolicyRecommendation
from routes import orchestration as orch_routes


class _StubEvalStore:
    def recommend_mode(self, lookback=200, window=20):
        return PolicyRecommendation(
            mode="balanced",
            reasons=["stable_balanced_operation"],
            summary={"total": 120, "pass_rate": 0.93, "avg_score": 0.86},
            trend={"signals": []},
        )

    def replay_cases(self, limit=100, mode=None):
        lim = max(1, min(limit, 500))
        return [
            {
                "name": f"case_{i}",
                "llm_calls": 4,
                "tool_calls": 9,
                "wall_time_ms": 8000.0,
                "verification": {"satisfied": True, "score": 0.9},
                "orchestration_mode": mode or "balanced",
            }
            for i in range(lim)
        ]

    def recent_runs(self, limit=50, mode=None):
        class _Row:
            def __init__(self, idx: int, row_mode: str):
                self.run_id = f"run_{idx}"
                self.workflow_id = f"wf_{idx}"
                self.session_id = "s_1"
                self.request_text = f"req_{idx}"
                self.created_at = "2026-01-01T00:00:00+00:00"
                self.score = 0.9
                self.success = True
                self.passed_gate = True
                self.llm_calls = 4
                self.tool_calls = 8
                self.wall_time_ms = 8000.0
                self.orchestration_mode = row_mode

        row_mode = mode or "balanced"
        lim = max(1, min(limit, 500))
        return [_Row(i, row_mode) for i in range(lim)]

    def summary(self, lookback=200, mode=None):
        if mode == "strict":
            return {
                "total": 40,
                "pass_rate": 0.96,
                "avg_score": 0.91,
                "avg_latency_ms": 14000.0,
                "avg_llm_calls": 6.0,
                "avg_tool_calls": 10.0,
                "mode": mode,
            }
        if mode == "fast":
            return {
                "total": 50,
                "pass_rate": 0.92,
                "avg_score": 0.88,
                "avg_latency_ms": 9000.0,
                "avg_llm_calls": 4.0,
                "avg_tool_calls": 8.0,
                "mode": mode,
            }
        return {
            "total": 120,
            "pass_rate": 0.96,
            "avg_score": 0.91,
            "avg_latency_ms": 11000.0,
            "avg_llm_calls": 5.0,
            "avg_tool_calls": 9.0,
            "mode": mode,
        }

    def trend(self, window=20, lookback=200, mode=None):
        signals = []
        if mode == "fast":
            signals = ["pass_rate_regression"]
        return {
            "window": window,
            "mode": mode,
            "recent": {},
            "baseline": {},
            "delta": {},
            "signals": signals,
        }


class _RegressionEvalStore(_StubEvalStore):
    def trend(self, window=20, lookback=200, mode=None):
        return {
            "window": window,
            "lookback": lookback,
            "mode": mode,
            "delta": {
                "score": -0.08,
                "pass_rate": -0.1,
                "latency_ms": 2200.0,
                "llm_calls": 1.6,
                "tool_calls": 5.0,
            },
            "signals": ["score_dropping"],
        }

    def replay_cases(self, limit=100, mode=None):
        lim = max(1, min(limit, 5))
        return [
            {
                "name": f"replay_bad_{i}",
                "llm_calls": 9,
                "tool_calls": 35,
                "wall_time_ms": 18000.0,
                "verification": {"satisfied": False, "score": 0.42},
                "orchestration_mode": mode or "balanced",
            }
            for i in range(lim)
        ]


class _AiEngineRegressionEvalStore(_StubEvalStore):
    def summary(self, lookback=200, mode=None):
        return {
            "total": 35,
            "pass_rate": 0.81,
            "avg_score": 0.72,
            "avg_latency_ms": 24000.0,
            "avg_llm_calls": 11.0,
            "avg_tool_calls": 21.0,
            "mode": mode,
        }

    def trend(self, window=20, lookback=200, mode=None):
        return {
            "window": window,
            "mode": mode,
            "delta": {
                "llm_calls": 1.7,
                "tool_calls": 3.8,
            },
            "signals": ["llm_churn_regression"],
        }


class _UiTrustRegressionEvalStore(_StubEvalStore):
    def summary(self, lookback=200, mode=None):
        return {
            "total": 30,
            "pass_rate": 0.78,
            "avg_score": 0.74,
            "avg_latency_ms": 23000.0,
            "avg_llm_calls": 10.0,
            "avg_tool_calls": 18.0,
            "mode": mode,
        }

    def trend(self, window=20, lookback=200, mode=None):
        return {
            "window": window,
            "mode": mode,
            "delta": {"llm_calls": 1.5},
            "signals": ["llm_churn_regression"],
        }

    def replay_cases(self, limit=100, mode=None):
        lim = max(1, min(limit, 8))
        return [
            {
                "name": f"unsafe_{i}",
                "llm_calls": 8,
                "tool_calls": 16,
                "wall_time_ms": 21000.0,
                "verification": {"satisfied": False, "score": 0.4, "issues": ["unsafe_action"]},
                "orchestration_mode": mode or "balanced",
            }
            for i in range(lim)
        ]


class _PerformanceRegressionEvalStore(_StubEvalStore):
    def recent_runs(self, limit=50, mode=None):
        class _Row:
            def __init__(self, idx: int, row_mode: str):
                self.run_id = f"run_{idx}"
                self.workflow_id = f"wf_{idx}"
                self.session_id = "s_1"
                self.request_text = f"req_{idx}"
                self.created_at = "2026-01-01T00:00:00+00:00"
                self.score = 0.82
                self.success = True
                self.passed_gate = True
                self.llm_calls = 8
                self.tool_calls = 15
                self.wall_time_ms = 42000.0
                self.orchestration_mode = row_mode

        row_mode = mode or "balanced"
        lim = max(1, min(limit, 500))
        return [_Row(i, row_mode) for i in range(lim)]

    def summary(self, lookback=200, mode=None):
        return {
            "total": 90,
            "pass_rate": 0.88,
            "avg_score": 0.82,
            "avg_latency_ms": 32000.0,
            "avg_llm_calls": 8.0,
            "avg_tool_calls": 15.0,
            "mode": mode,
        }


class _StubPrimitive:
    def get_operations(self):
        return {"list": "List items", "create": "Create an item"}

    def get_param_schema(self):
        return {
            "list": {
                "limit": {"type": "int", "required": False, "description": "Limit"},
            },
            "create": {
                "name": {"type": "str", "required": True, "description": "Name"},
            },
        }

    def get_available_operations(self):
        return self.get_operations()

    def get_connected_providers(self):
        return ["stub_provider"]


class _StubConnector:
    connected = True

    async def check_health(self):
        class _Health:
            class status:
                value = "connected"

            latency_ms = 120.0

            @staticmethod
            def to_dict():
                return {"status": "connected", "latency_ms": 120.0}

        return _Health()


class _StubEngine:
    def __init__(self):
        self._primitives = {"STUB": _StubPrimitive()}
        self._connectors = {"stub": _StubConnector()}


class _StubServerState:
    @staticmethod
    def get_telic_engine():
        return _StubEngine()


class _FailingConnector:
    connected = False


class _FailingEngine:
    def __init__(self):
        self._primitives = {"BROKEN": _BrokenPrimitive()}
        self._connectors = {"broken": _FailingConnector()}


class _BrokenPrimitive:
    def get_operations(self):
        return {"list": ""}

    def get_param_schema(self):
        return {}

    def get_available_operations(self):
        return {}


class _FailingServerState:
    @staticmethod
    def get_telic_engine():
        return _FailingEngine()


def test_orchestration_policy_recommend_endpoint(monkeypatch):
    monkeypatch.setattr(orch_routes, "_eval_store", _StubEvalStore())

    resp = asyncio.run(orch_routes.orchestration_policy_recommend(lookback=100, window=10))
    payload = json.loads(resp.body)

    assert payload["mode"] == "balanced"
    assert payload["reasons"]
    assert payload["summary"]["total"] == 120


def test_orchestration_replay_run_endpoint(monkeypatch):
    monkeypatch.setattr(orch_routes, "_eval_store", _StubEvalStore())

    req = orch_routes.ReplayRunRequest(limit=8, mode="strict")
    resp = asyncio.run(orch_routes.orchestration_replay_run(req))
    payload = json.loads(resp.body)

    assert payload["total"] == 8
    assert payload["source"] == "eval_store_replay"
    assert payload["mode"] == "strict"
    assert "pass_rate" in payload


def test_orchestration_quality_history_mode_filter(monkeypatch):
    monkeypatch.setattr(orch_routes, "_eval_store", _StubEvalStore())

    resp = asyncio.run(orch_routes.orchestration_quality_history(limit=3, mode="fast"))
    payload = json.loads(resp.body)

    assert payload["total"] == 3
    assert payload["mode"] == "fast"
    assert all(r["orchestration_mode"] == "fast" for r in payload["rows"])


def test_orchestration_quality_scorecard(monkeypatch):
    monkeypatch.setattr(orch_routes, "_eval_store", _StubEvalStore())

    resp = asyncio.run(orch_routes.orchestration_quality_scorecard(lookback=120, window=20))
    payload = json.loads(resp.body)

    assert payload["pillar"] == "orchestration"
    assert "overall" in payload
    assert "by_mode" in payload
    assert payload["overall"]["score_10"] > 0.0
    assert set(payload["by_mode"].keys()) == {"strict", "balanced", "fast"}


def test_orchestration_primitives_contract_quality(monkeypatch):
    monkeypatch.setattr(orch_routes, "ss", _StubServerState())

    resp = asyncio.run(orch_routes.orchestration_primitives_contract_quality())
    payload = json.loads(resp.body)

    assert payload["summary"]["total_primitives"] == 1
    assert payload["summary"]["total_operations"] == 2
    assert payload["summary"]["score_10"] > 0.0


def test_orchestration_connectors_reliability(monkeypatch):
    monkeypatch.setattr(orch_routes, "ss", _StubServerState())

    resp = asyncio.run(orch_routes.orchestration_connectors_reliability())
    payload = json.loads(resp.body)

    assert payload["summary"]["total_connectors"] == 1
    assert payload["summary"]["avg_score_10"] > 0.0
    assert "incident_totals" in payload["summary"]
    assert payload["connectors"][0]["connector"] == "stub"
    assert "incident_counts" in payload["connectors"][0]
    assert "dominant_incident" in payload["connectors"][0]


def test_orchestration_week2_gate_ready(monkeypatch):
    monkeypatch.setattr(orch_routes, "ss", _StubServerState())
    monkeypatch.setattr(orch_routes, "_eval_store", _StubEvalStore())

    resp = asyncio.run(orch_routes.orchestration_week2_gate(lookback=120, window=20))
    payload = json.loads(resp.body)

    assert payload["ready"] is True
    assert payload["failures"] == []
    assert payload["checks"]["primitives_contract"]["ready"] is True
    assert payload["checks"]["connectors_reliability"]["ready"] is True
    assert payload["checks"]["orchestration_score"]["ready"] is True


def test_orchestration_week2_gate_not_ready(monkeypatch):
    monkeypatch.setattr(orch_routes, "ss", _FailingServerState())
    monkeypatch.setattr(orch_routes, "_eval_store", _StubEvalStore())

    resp = asyncio.run(orch_routes.orchestration_week2_gate(lookback=120, window=20))
    payload = json.loads(resp.body)

    assert payload["ready"] is False
    assert payload["failures"]
    assert payload["checks"]["primitives_contract"]["ready"] is False
    assert payload["checks"]["connectors_reliability"]["ready"] is True


def test_orchestration_week3_connectors_gate_ready(monkeypatch):
    monkeypatch.setattr(orch_routes, "ss", _StubServerState())

    resp = asyncio.run(orch_routes.orchestration_week3_connectors_gate())
    payload = json.loads(resp.body)

    assert payload["ready"] is True
    assert payload["failures"] == []
    assert payload["summary"]["total_connectors"] == 1


def test_orchestration_week3_connectors_gate_not_ready(monkeypatch):
    monkeypatch.setattr(orch_routes, "ss", _FailingServerState())

    resp = asyncio.run(orch_routes.orchestration_week3_connectors_gate(min_avg_score_0_1=1.1))
    payload = json.loads(resp.body)

    assert payload["ready"] is False
    assert payload["failures"]
    assert payload["summary"]["total_connectors"] == 1


def test_orchestration_week4_replay_gate_ready(monkeypatch):
    monkeypatch.setattr(orch_routes, "_eval_store", _StubEvalStore())

    resp = asyncio.run(orch_routes.orchestration_week4_replay_gate())
    payload = json.loads(resp.body)

    assert payload["ready"] is True
    assert payload["failures"] == []
    assert payload["replay"]["total"] > 0


def test_orchestration_week4_replay_gate_not_ready(monkeypatch):
    monkeypatch.setattr(orch_routes, "_eval_store", _RegressionEvalStore())

    resp = asyncio.run(orch_routes.orchestration_week4_replay_gate())
    payload = json.loads(resp.body)

    assert payload["ready"] is False
    assert "score_drop_budget_exceeded" in payload["failures"]
    assert "pass_rate_drop_budget_exceeded" in payload["failures"]
    assert "latency_increase_budget_exceeded" in payload["failures"]
    assert "replay_pass_rate_below_target" in payload["failures"]


def test_orchestration_week4_replay_gate_threshold_overrides(monkeypatch):
    monkeypatch.setattr(orch_routes, "_eval_store", _RegressionEvalStore())

    resp = asyncio.run(
        orch_routes.orchestration_week4_replay_gate(
            max_score_drop=1.0,
            max_pass_rate_drop=1.0,
            max_latency_increase_ms=10000.0,
            max_llm_call_increase=10.0,
            max_tool_call_increase=100.0,
            min_replay_pass_rate=0.0,
        )
    )
    payload = json.loads(resp.body)

    assert payload["ready"] is True
    assert payload["failures"] == []


def test_orchestration_week5_ai_engine_gate_ready(monkeypatch):
    monkeypatch.setattr(orch_routes, "_eval_store", _StubEvalStore())

    resp = asyncio.run(orch_routes.orchestration_week5_ai_engine_gate())
    payload = json.loads(resp.body)

    assert payload["ready"] is True
    assert payload["failures"] == []


def test_orchestration_week5_ai_engine_gate_not_ready(monkeypatch):
    monkeypatch.setattr(orch_routes, "_eval_store", _AiEngineRegressionEvalStore())

    resp = asyncio.run(orch_routes.orchestration_week5_ai_engine_gate())
    payload = json.loads(resp.body)

    assert payload["ready"] is False
    assert "insufficient_eval_coverage" in payload["failures"]
    assert "pass_rate_below_target" in payload["failures"]
    assert "avg_score_below_target" in payload["failures"]
    assert "llm_churn_regression_detected" in payload["failures"]


def test_orchestration_week5_benchmark_gate_ready(monkeypatch):
    monkeypatch.setattr(orch_routes, "_eval_store", _StubEvalStore())

    resp = asyncio.run(orch_routes.orchestration_week5_benchmark_gate())
    payload = json.loads(resp.body)

    assert payload["ready"] is True
    assert payload["failures"] == []
    assert payload["replay"]["total"] > 0


def test_orchestration_week5_benchmark_gate_not_ready(monkeypatch):
    monkeypatch.setattr(orch_routes, "_eval_store", _RegressionEvalStore())

    resp = asyncio.run(orch_routes.orchestration_week5_benchmark_gate())
    payload = json.loads(resp.body)

    assert payload["ready"] is False
    assert "combined_benchmark_pass_rate_below_target" in payload["failures"]
    assert "replay_safety_pass_rate_below_target" in payload["failures"]
    assert "replay_churn_below_target" in payload["failures"]


def test_orchestration_week6_ui_trust_gate_ready(monkeypatch):
    monkeypatch.setattr(orch_routes, "_eval_store", _StubEvalStore())

    resp = asyncio.run(orch_routes.orchestration_week6_ui_trust_gate())
    payload = json.loads(resp.body)

    assert payload["ready"] is True
    assert payload["failures"] == []


def test_orchestration_week6_ui_trust_gate_not_ready(monkeypatch):
    monkeypatch.setattr(orch_routes, "_eval_store", _UiTrustRegressionEvalStore())

    resp = asyncio.run(orch_routes.orchestration_week6_ui_trust_gate())
    payload = json.loads(resp.body)

    assert payload["ready"] is False
    assert "replay_safety_pass_rate_below_target" in payload["failures"]
    assert "llm_churn_regression_detected" in payload["failures"]


def test_orchestration_week7_performance_gate_ready(monkeypatch):
    monkeypatch.setattr(orch_routes, "_eval_store", _StubEvalStore())

    resp = asyncio.run(orch_routes.orchestration_week7_performance_gate())
    payload = json.loads(resp.body)

    assert payload["ready"] is True
    assert payload["failures"] == []


def test_orchestration_week7_performance_gate_not_ready(monkeypatch):
    monkeypatch.setattr(orch_routes, "_eval_store", _PerformanceRegressionEvalStore())

    resp = asyncio.run(orch_routes.orchestration_week7_performance_gate())
    payload = json.loads(resp.body)

    assert payload["ready"] is False
    assert "p95_latency_above_target" in payload["failures"]
    assert "p99_latency_above_target" in payload["failures"]


def test_orchestration_week8_launch_gate_not_ready_with_blockers(monkeypatch):
    monkeypatch.setattr(orch_routes, "ss", _StubServerState())
    monkeypatch.setattr(orch_routes, "_eval_store", _StubEvalStore())

    resp = asyncio.run(orch_routes.orchestration_week8_launch_gate(open_p0=1, open_p1=0))
    payload = json.loads(resp.body)

    assert payload["ready"] is False
    assert "p0_clear_not_ready" in payload["failures"]
