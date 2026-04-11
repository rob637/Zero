from dataclasses import dataclass

from .contracts import ExecutionPolicy, OutcomeContract, WorkflowPhase, WorkflowState
from .state_machine import InvalidTransitionError, OrchestrationStateMachine
from .artifact_ledger import ArtifactLedger, ArtifactRecord, extract_artifact_candidates
from .capability_graph import CapabilitySummary, OrchestrationCapabilityGraph
from .verifier import VerificationResult, check_side_effect_preconditions, verify_outcome
from .evaluator import EvaluationResult, check_quality_gate, evaluate_runtime_snapshot
try:
    from .evaluator import QualityGateThresholds
except ImportError:
    @dataclass
    class QualityGateThresholds:  # Backward-compat for older evaluator.py copies.
        min_score: float = 0.75
        min_efficiency: float = 0.25
        min_latency: float = 0.15
        min_churn: float = 0.15
from .benchmark_runner import BenchmarkCase, default_benchmark_cases, load_cases_from_json, run_benchmarks
from .eval_store import EvaluationRun, OrchestrationEvalStore, PolicyRecommendation
from .primitive_audit import audit_primitives

__all__ = [
    "ExecutionPolicy",
    "OutcomeContract",
    "WorkflowPhase",
    "WorkflowState",
    "InvalidTransitionError",
    "OrchestrationStateMachine",
    "ArtifactLedger",
    "ArtifactRecord",
    "extract_artifact_candidates",
    "CapabilitySummary",
    "OrchestrationCapabilityGraph",
    "VerificationResult",
    "check_side_effect_preconditions",
    "verify_outcome",
    "EvaluationResult",
    "QualityGateThresholds",
    "check_quality_gate",
    "evaluate_runtime_snapshot",
    "BenchmarkCase",
    "run_benchmarks",
    "default_benchmark_cases",
    "load_cases_from_json",
    "EvaluationRun",
    "OrchestrationEvalStore",
    "PolicyRecommendation",
    "audit_primitives",
]
