"""
Automatic Retry Engine for The Harness

Orchestrates diagnosis → remediation → retry cycles until scenarios pass or max retries reached.
Follows pillars: no hard-coding of primitives/connectors/orchestration rules.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from datetime import datetime
import logging

from harness.diagnosis import DiagnosisResult, IssueAnalyzer, IssueCategory
from harness.scenario_remediation_engine import RemediationEngine


logger = logging.getLogger(__name__)


@dataclass
class RetryAttempt:
    """Records a single retry attempt."""
    attempt_number: int
    timestamp: datetime
    diagnosis: dict  # Root cause analysis results
    remediation_applied: str  # Which fix was applied
    result: str  # 'success', 'failed', 'partial'
    error_message: Optional[str] = None
    metrics: dict = field(default_factory=dict)


@dataclass
class ScenarioRetrySession:
    """Tracks a complete retry session for a scenario."""
    scenario_id: str
    scenario_name: str
    max_retries: int
    initial_error: str
    attempts: list = field(default_factory=list)
    final_result: str = "pending"  # 'success', 'exhausted', 'user_intervention'
    total_duration_seconds: float = 0.0
    
    def to_dict(self):
        return {
            'scenario_id': self.scenario_id,
            'scenario_name': self.scenario_name,
            'max_retries': self.max_retries,
            'initial_error': self.initial_error,
            'attempts': [
                {
                    'attempt': a.attempt_number,
                    'timestamp': a.timestamp.isoformat(),
                    'diagnosis': a.diagnosis,
                    'remediation': a.remediation_applied,
                    'result': a.result,
                    'error': a.error_message,
                    'metrics': a.metrics,
                }
                for a in self.attempts
            ],
            'final_result': self.final_result,
            'total_duration_seconds': self.total_duration_seconds,
        }


class ScenarioRetryEngine:
    """
    Orchestrates diagnosis + remediation + retry cycles.
    
    Philosophy:
    - Diagnose root cause (not just symptoms)
    - Apply targeted fix (not restart everything)
    - Retry only changed path (not full scenario re-run)
    - Give up gracefully when pattern repeats
    """
    
    def __init__(self, max_retries: int = 3, timeout_seconds: int = 300):
        self.diagnosis_engine = IssueAnalyzer()
        self.remediation_engine = RemediationEngine()
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
    
    def execute_with_retry(
        self,
        scenario_id: str,
        scenario_name: str,
        scenario_executor,  # Callable that runs scenario, returns (success, result, error)
        context: dict,
    ) -> ScenarioRetrySession:
        """
        Execute scenario with automatic diagnosis, remediation, and retry.
        
        Args:
            scenario_id: Unique identifier for scenario
            scenario_name: Human-readable name
            scenario_executor: Function(context) -> (success: bool, result: dict, error: str)
            context: Initial execution context (connectors, state, etc.)
        
        Returns:
            ScenarioRetrySession with full execution history
        """
        start_time = datetime.now()
        session = ScenarioRetrySession(
            scenario_id=scenario_id,
            scenario_name=scenario_name,
            max_retries=self.max_retries,
            initial_error="",
        )
        
        current_context = context.copy()
        
        # First execution
        logger.info(f"🚀 Starting scenario: {scenario_name}")
        success, result, error = scenario_executor(current_context)
        
        if success:
            session.final_result = "success"
            logger.info(f"✅ Scenario {scenario_name} passed on first attempt")
            session.total_duration_seconds = (datetime.now() - start_time).total_seconds()
            return session
        
        # Failed - enter retry loop
        session.initial_error = error
        logger.warning(f"❌ Scenario {scenario_name} failed: {error}")
        
        for attempt_num in range(1, self.max_retries + 1):
            logger.info(f"\n🔄 Retry attempt {attempt_num}/{self.max_retries}")
            
            # Step 1: Diagnose the issue
            diagnosis_result = self.diagnosis_engine.analyze(
                self._build_run_data(
                    scenario_id=scenario_id,
                    scenario_name=scenario_name,
                    success=False,
                    result=result,
                    error=error,
                    context=current_context,
                )
            )
            diagnosis = self._summarize_diagnosis(diagnosis_result)
            
            logger.info(f"  Root cause: {diagnosis['root_cause']}")
            logger.info(f"  Category: {diagnosis['category']}")
            logger.info(f"  Confidence: {diagnosis['confidence']:.1%}")
            
            # Step 2: Get remediation strategy
            remediation = self.remediation_engine.get_remediation(
                category=diagnosis['category'],
                root_cause=diagnosis['root_cause'],
                context=current_context,
                error_details=diagnosis['error_details'],
            )
            
            logger.info(f"  Applying fix: {remediation.name}")
            logger.info(f"  Actions: {remediation.actions}")
            
            # Step 3: Apply remediation
            remediation_success, updated_context = self.remediation_engine.apply_fix(
                remediation_strategy=remediation,
                context=current_context,
            )
            
            if not remediation_success:
                logger.warning(f"  Remediation failed to apply")
                attempt = RetryAttempt(
                    attempt_number=attempt_num,
                    timestamp=datetime.now(),
                    diagnosis=diagnosis,
                    remediation_applied=remediation.name,
                    result="failed",
                    error_message="Remediation failed to apply",
                )
                session.attempts.append(attempt)
                continue
            
            current_context = updated_context
            
            # Step 4: Retry scenario with fixed context
            logger.info(f"  Retrying scenario with fixes...")
            success, result, error = scenario_executor(current_context)
            
            attempt = RetryAttempt(
                attempt_number=attempt_num,
                timestamp=datetime.now(),
                diagnosis=diagnosis,
                remediation_applied=remediation.name,
                result="success" if success else "failed",
                error_message=error if not success else None,
                metrics={
                    'diagnosis_confidence': diagnosis['confidence'],
                    'remediation_strategy': remediation.name,
                },
            )
            session.attempts.append(attempt)
            
            if success:
                logger.info(f"  ✅ Scenario passed on attempt {attempt_num}")
                session.final_result = "success"
                session.total_duration_seconds = (datetime.now() - start_time).total_seconds()
                return session
            
            # Check if we're in a loop
            if self._is_repeating_error(session.attempts, diagnosis['category']):
                logger.error(f"  🔁 Detected repeating error pattern - giving up")
                session.final_result = "exhausted"
                session.total_duration_seconds = (datetime.now() - start_time).total_seconds()
                return session
            
            logger.warning(f"  Still failing: {error}")
        
        # Exhausted retries
        logger.error(f"❌ Scenario {scenario_name} failed after {self.max_retries} retries")
        session.final_result = "exhausted"
        session.total_duration_seconds = (datetime.now() - start_time).total_seconds()
        return session
    
    def _is_repeating_error(self, attempts: list, current_category: str) -> bool:
        """Detect if we're stuck in a loop diagnosing the same issue."""
        if len(attempts) < 2:
            return False
        
        # If last 2 attempts had same category, we're looping
        if len(attempts) >= 2:
            prev_category = attempts[-2].diagnosis.get('category')
            if prev_category == current_category:
                return True
        
        return False

    def _build_run_data(
        self,
        *,
        scenario_id: str,
        scenario_name: str,
        success: bool,
        result: Dict[str, Any] | None,
        error: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        payload = result if isinstance(result, dict) else {}
        raw = payload.get('raw') if isinstance(payload.get('raw'), dict) else payload
        steps = raw.get('steps', []) if isinstance(raw, dict) else []
        tool_names = payload.get('tool_names') or [str(step.get('tool', '')) for step in steps if step.get('tool')]
        failed_steps = payload.get('failed_steps')
        if failed_steps is None:
            failed_steps = sum(1 for step in steps if step.get('status') == 'failed')
        passed_steps = payload.get('passed_steps')
        if passed_steps is None:
            passed_steps = sum(1 for step in steps if step.get('status') == 'completed')

        issues = list(payload.get('issues', []) or [])
        if raw and isinstance(raw, dict):
            if raw.get('pending_approval'):
                issues.append('pending_approval_not_resolved')
            if raw.get('is_complete') is False:
                issues.append('scenario_not_complete')
        if error and not issues:
            issues.append(error)

        return {
            'scenario_id': scenario_id,
            'name': scenario_name,
            'passed': success,
            'issues': issues,
            'tool_names': [tool for tool in tool_names if tool],
            'failed_steps': int(failed_steps or 0),
            'passed_steps': int(passed_steps or 0),
            'approvals_used': int(payload.get('approvals_used', context.get('approvals_used', 0))),
            'duration_seconds': float(payload.get('duration_seconds', 0.0)),
            'run_data': {
                'raw': raw if isinstance(raw, dict) else {},
            },
        }

    def _summarize_diagnosis(self, diagnosis_result: DiagnosisResult) -> Dict[str, Any]:
        root_causes = sorted(diagnosis_result.root_causes, key=lambda cause: cause.confidence, reverse=True)
        primary = root_causes[0] if root_causes else None
        affected_connectors = [
            str(step.get('tool'))
            for step in diagnosis_result.failed_steps
            if step.get('tool')
        ]
        return {
            'category': primary.category.value if primary else IssueCategory.UNKNOWN.value,
            'confidence': primary.confidence if primary else 0.0,
            'root_cause': primary.category.value if primary else 'unknown',
            'error_details': diagnosis_result.error_messages,
            'affected_connectors': affected_connectors,
            'detected_issues': diagnosis_result.detected_issues,
            'next_steps': diagnosis_result.next_steps,
        }
    
    def generate_report(self, session: ScenarioRetrySession) -> str:
        """Generate human-readable report of retry session."""
        lines = [
            f"\n{'='*70}",
            f"SCENARIO RETRY REPORT: {session.scenario_name}",
            f"{'='*70}",
            f"ID: {session.scenario_id}",
            f"Initial Error: {session.initial_error[:100]}...",
            f"Final Result: {session.final_result.upper()}",
            f"Duration: {session.total_duration_seconds:.1f}s",
            f"Attempts: {len(session.attempts)}/{session.max_retries}",
        ]
        
        if session.attempts:
            lines.append(f"\n{'ATTEMPT HISTORY':^70}")
            lines.append("-" * 70)
            
            for attempt in session.attempts:
                lines.append(f"\nAttempt {attempt.attempt_number}:")
                lines.append(f"  Root Cause: {attempt.diagnosis.get('root_cause')}")
                lines.append(f"  Category: {attempt.diagnosis.get('category')}")
                lines.append(f"  Confidence: {attempt.diagnosis.get('confidence', 0):.0%}")
                lines.append(f"  Fix Applied: {attempt.remediation_applied}")
                lines.append(f"  Result: {attempt.result}")
                if attempt.error_message:
                    lines.append(f"  Error: {attempt.error_message[:80]}")
        
        lines.append(f"\n{'='*70}\n")
        return "\n".join(lines)
