"""Issue Diagnosis Engine

Analyzes scenario run results to identify root causes and classify failures.

Key principles:
- No hard-coding of specific scenarios
- Works with primitive/connector/orchestration abstractions
- Identifies patterns across step execution, tool calls, and final output
- Provides actionable root cause analysis
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set
import re


class IssueCategory(Enum):
    """Root cause categories for scenario failures."""
    
    # Missing capabilities
    MISSING_TOOL = "missing_tool"  # A required tool wasn't called
    MISSING_CONNECTOR = "missing_connector"  # A connector isn't available
    MISSING_OUTPUT = "missing_output"  # Required output pattern not found
    MISSING_ARTIFACT = "missing_artifact"  # Expected file/artifact wasn't created
    
    # Execution problems
    TOOL_FAILED = "tool_failed"  # A tool call failed
    TIMEOUT = "timeout"  # Scenario exceeded time limit
    TOO_MANY_STEPS = "too_many_steps"  # Exceeded max step threshold
    NO_PROGRESS = "no_progress"  # Orchestration stalled
    
    # Connector issues
    CONNECTOR_UNAVAILABLE = "connector_unavailable"  # Connector not ready/connected
    CONNECTOR_ERROR = "connector_error"  # Connector returned error
    AUTH_FAILED = "auth_failed"  # Authentication/credential issue
    RATE_LIMITED = "rate_limited"  # Hit rate limits
    
    # Orchestration issues
    LOOP_DETECTED = "loop_detected"  # Same steps repeating
    WRONG_MODE = "wrong_mode"  # Orchestration mode not suited for scenario
    PLAN_DIVERGENCE = "plan_divergence"  # Execution deviated from intent
    
    # Prompt/intent issues
    AMBIGUOUS_INTENT = "ambiguous_intent"  # Prompt not clear enough
    OVER_SCOPED = "over_scoped"  # Scenario asks for too much
    MISSING_CONTEXT = "missing_context"  # Prompt missing key info
    
    # Output generation
    INCOMPLETE_RESPONSE = "incomplete_response"  # Response cut off/incomplete
    WRONG_FORMAT = "wrong_format"  # Output format doesn't match expectation
    QUALITY_LOW = "quality_low"  # Output exists but quality is poor
    
    # Approval issues
    APPROVAL_TIMEOUT = "approval_timeout"  # Pending approval not resolved
    TOO_MANY_APPROVALS = "too_many_approvals"  # Exceeded approval budget
    
    # Unknown
    UNKNOWN = "unknown"


@dataclass
class RootCause:
    """Analysis of a single root cause."""
    category: IssueCategory
    confidence: float  # 0.0-1.0, higher = more certain
    signals: List[str] = field(default_factory=list)  # Evidence supporting this cause
    suggested_fixes: List[str] = field(default_factory=list)  # How to fix this issue
    
    def __repr__(self) -> str:
        return (
            f"RootCause({self.category.value}, "
            f"confidence={self.confidence:.2f}, "
            f"signals={len(self.signals)})"
        )


@dataclass
class DiagnosisResult:
    """Complete diagnosis for a scenario run."""
    scenario_id: str
    scenario_name: str
    run_passed: bool
    
    # Detected issues
    detected_issues: List[str]  # Raw issues from run_scenarios.py
    root_causes: List[RootCause] = field(default_factory=list)  # Analyzed root causes
    
    # Detailed analysis
    tools_called: List[str] = field(default_factory=list)
    tools_missing: List[str] = field(default_factory=list)
    failed_steps: List[Dict[str, Any]] = field(default_factory=list)
    error_messages: List[str] = field(default_factory=list)
    
    # Orchestration insights
    total_steps: int = 0
    orchestration_mode: str = ""
    approvals_used: int = 0
    duration_seconds: float = 0.0
    
    # Remediation guidance
    is_remediable: bool = False
    remediation_priority: int = 0  # 1=critical, 2=high, 3=medium, 4=low
    next_steps: List[str] = field(default_factory=list)
    
    def has_connector_issue(self) -> bool:
        """Check if any root cause involves connector problems."""
        return any(
            cat in [IssueCategory.CONNECTOR_UNAVAILABLE, IssueCategory.CONNECTOR_ERROR, 
                   IssueCategory.AUTH_FAILED, IssueCategory.RATE_LIMITED]
            for cat in (rc.category for rc in self.root_causes)
        )
    
    def has_timeout_issue(self) -> bool:
        """Check if timeout or max_steps exceeded."""
        return any(
            cat in [IssueCategory.TIMEOUT, IssueCategory.TOO_MANY_STEPS, IssueCategory.NO_PROGRESS]
            for cat in (rc.category for rc in self.root_causes)
        )
    
    def has_prompt_issue(self) -> bool:
        """Check if issue is in the prompt/intent."""
        return any(
            cat in [IssueCategory.AMBIGUOUS_INTENT, IssueCategory.OVER_SCOPED, IssueCategory.MISSING_CONTEXT]
            for cat in (rc.category for rc in self.root_causes)
        )


class IssueAnalyzer:
    """Analyzes scenario run results to identify root causes."""
    
    # Patterns to detect specific issues
    TIMEOUT_PATTERNS = [
        r"timed\s+out",
        r"timeout",
        r"exceeded time",
        r"wall\s+time",
    ]
    
    MAX_STEPS_PATTERNS = [
        r"maximum number of steps",
        r"max.*steps",
        r"step.*limit",
        r"too many steps",
    ]
    
    NO_PROGRESS_PATTERNS = [
        r"not making progress",
        r"making enough progress",
        r"no further progress",
        r"stuck",
    ]
    
    CONNECTOR_ERROR_PATTERNS = [
        r"connector.*(?:error|failed|unavailable)",
        r"(?:connection|auth).*error",
        r"credential",
        r"unauthorized",
        r"forbidden",
    ]
    
    LOOP_PATTERNS = [
        r"(?:infinite|endless|infinite) loop",
        r"looping",
        r"same step",
        r"repeating",
    ]
    
    def analyze(self, run_data: Dict[str, Any]) -> DiagnosisResult:
        """Analyze a scenario run result and identify root causes.
        
        Args:
            run_data: Result from run_scenarios.py (includes raw payload, issues, etc)
        
        Returns:
            DiagnosisResult with detailed analysis and root causes
        """
        scenario_id = run_data.get("scenario_id", "unknown")
        scenario_name = run_data.get("name", scenario_id)
        run_passed = run_data.get("passed", False)
        
        result = DiagnosisResult(
            scenario_id=scenario_id,
            scenario_name=scenario_name,
            run_passed=run_passed,
            detected_issues=run_data.get("issues", []),
            tools_called=run_data.get("tool_names", []),
            total_steps=run_data.get("failed_steps", 0) + run_data.get("passed_steps", 0),
            duration_seconds=run_data.get("duration_seconds", 0.0),
            approvals_used=run_data.get("approvals_used", 0),
        )
        
        # Extract detailed info from run_data
        raw_payload = run_data.get("run_data", {}).get("raw", {})
        steps = raw_payload.get("steps", [])
        response = raw_payload.get("response", "")
        error = raw_payload.get("error", "")
        orchestration_mode = raw_payload.get("orchestration_mode", "unknown")
        
        result.orchestration_mode = orchestration_mode
        
        # Collect failed steps and error messages
        for step in steps:
            if step.get("status") == "failed":
                result.failed_steps.append(step)
                if step.get("error"):
                    result.error_messages.append(str(step.get("error")))
        
        if error:
            result.error_messages.append(str(error))
        
        # Analyze detected issues and map to root causes
        result.root_causes = self._analyze_issues(
            detected_issues=result.detected_issues,
            tools_called=result.tools_called,
            failed_steps=result.failed_steps,
            error_messages=result.error_messages,
            response_text=response,
            step_count=len(steps),
            orchestration_mode=orchestration_mode,
        )
        
        # Determine if issue is remediable and set priority
        result.is_remediable = self._is_remediable(result.root_causes)
        result.remediation_priority = self._calculate_priority(result.root_causes)
        result.next_steps = self._suggest_next_steps(result.root_causes)
        
        return result
    
    def _analyze_issues(
        self,
        detected_issues: List[str],
        tools_called: List[str],
        failed_steps: List[Dict[str, Any]],
        error_messages: List[str],
        response_text: str,
        step_count: int,
        orchestration_mode: str,
    ) -> List[RootCause]:
        """Map detected issues to root causes with confidence scoring."""
        causes: List[RootCause] = []
        analyzed_set: Set[str] = set()
        
        # Parse detected issues
        for issue in detected_issues:
            if issue in analyzed_set:
                continue
            analyzed_set.add(issue)
            
            # Missing tools
            if issue.startswith("missing_tools:"):
                match = re.search(r"\[(.*?)\]", issue)
                if match:
                    missing = match.group(1)
                    causes.append(RootCause(
                        category=IssueCategory.MISSING_TOOL,
                        confidence=0.95,
                        signals=[f"detected_issue: {issue}"],
                        suggested_fixes=[
                            "Ensure all required connectors are authenticated",
                            "Check that the system has access to these tools",
                            "Verify connector availability in current environment",
                        ],
                    ))
            
            # Forbidden tools used
            elif issue.startswith("used_forbidden_tools:"):
                causes.append(RootCause(
                    category=IssueCategory.WRONG_MODE,
                    confidence=0.9,
                    signals=[f"detected_issue: {issue}"],
                    suggested_fixes=[
                        "Adjust scenario checks to allow necessary tools",
                        "Consider if orchestration mode supports this workflow",
                        "Review prompt to ensure it guides away from forbidden patterns",
                    ],
                ))
            
            # Missing output patterns
            elif issue.startswith("missing_output_patterns:"):
                causes.append(RootCause(
                    category=IssueCategory.MISSING_OUTPUT,
                    confidence=0.85,
                    signals=[f"detected_issue: {issue}"],
                    suggested_fixes=[
                        "Improve prompt to explicitly request the required output",
                        "Check if response format matches expected pattern",
                        "Increase response generation verbosity or time budget",
                    ],
                ))
            
            # Forbidden output patterns found
            elif issue.startswith("forbidden_output_patterns:"):
                causes.append(RootCause(
                    category=IssueCategory.WRONG_FORMAT,
                    confidence=0.85,
                    signals=[f"detected_issue: {issue}"],
                    suggested_fixes=[
                        "Guide prompt to avoid the problematic pattern",
                        "Add more context about expected output format",
                        "Refine prompt to prevent misinterpretations",
                    ],
                ))
            
            # Too many failed steps
            elif issue.startswith("failed_steps_exceeded:"):
                causes.append(RootCause(
                    category=IssueCategory.TOOL_FAILED,
                    confidence=0.80,
                    signals=[f"detected_issue: {issue}"],
                    suggested_fixes=[
                        "Investigate why tool calls are failing",
                        "Check connector health and credentials",
                        "See if specific steps have patterns in their failures",
                    ],
                ))
            
            # Forbidden error patterns
            elif issue.startswith("forbidden_error_pattern:"):
                pattern = issue.split(":", 1)[1].strip()
                causes.append(RootCause(
                    category=self._categorize_error_pattern(pattern),
                    confidence=0.80,
                    signals=[f"detected_issue: {issue}"],
                    suggested_fixes=self._suggest_fixes_for_pattern(pattern),
                ))
            
            # Pending approval not resolved
            elif issue == "pending_approval_not_resolved":
                causes.append(RootCause(
                    category=IssueCategory.APPROVAL_TIMEOUT,
                    confidence=0.95,
                    signals=[f"detected_issue: {issue}"],
                    suggested_fixes=[
                        "Increase max_approvals in scenario config",
                        "Review what approval was requested and if it makes sense",
                        "Consider if prompt needs to be clearer about approval scope",
                    ],
                ))
            
            # Scenario not complete
            elif issue == "scenario_not_complete":
                causes.append(RootCause(
                    category=IssueCategory.INCOMPLETE_RESPONSE,
                    confidence=0.85,
                    signals=[f"detected_issue: {issue}"],
                    suggested_fixes=[
                        "Increase timeout_seconds for this scenario",
                        "Check if orchestration_mode is too restrictive",
                        "Break down prompt into smaller substeps",
                    ],
                ))
        
        # Analyze error message patterns
        for error_msg in error_messages:
            self._analyze_error_message(error_msg, causes, analyzed_set)
        
        # Analyze step failures
        for step in failed_steps:
            self._analyze_failed_step(step, causes, analyzed_set)
        
        # Check for orchestration-specific issues
        if step_count > 30 and orchestration_mode == "fast":
            causes.append(RootCause(
                category=IssueCategory.WRONG_MODE,
                confidence=0.65,
                signals=[f"high_step_count: {step_count}", f"mode: {orchestration_mode}"],
                suggested_fixes=[
                    "Try with orchestration_mode='balanced' or 'strict'",
                    "Fast mode may not handle complex scenarios well",
                ],
            ))
        
        # If no root causes found but issues exist, mark as unknown
        if not causes and detected_issues:
            causes.append(RootCause(
                category=IssueCategory.UNKNOWN,
                confidence=0.5,
                signals=detected_issues[:3],  # Show first 3 issues as signals
                suggested_fixes=[
                    "Review full run data for additional context",
                    "Check system logs for underlying errors",
                    "Enable debug logging for more detail",
                ],
            ))
        
        return causes
    
    def _analyze_error_message(self, error_msg: str, causes: List[RootCause], analyzed_set: Set[str]) -> None:
        """Analyze free-form error messages to identify root causes."""
        error_lower = error_msg.lower()
        
        # Timeout patterns
        for pattern in self.TIMEOUT_PATTERNS:
            if re.search(pattern, error_lower):
                key = f"timeout_detected:{error_msg[:50]}"
                if key not in analyzed_set:
                    analyzed_set.add(key)
                    causes.append(RootCause(
                        category=IssueCategory.TIMEOUT,
                        confidence=0.85,
                        signals=[f"error_message: {error_msg[:100]}"],
                        suggested_fixes=[
                            "Increase timeout_seconds in scenario config",
                            "Optimize prompt to be more concise",
                            "Check system load and resource availability",
                        ],
                    ))
                break
        
        # Max steps patterns
        for pattern in self.MAX_STEPS_PATTERNS:
            if re.search(pattern, error_lower):
                key = f"max_steps_detected:{error_msg[:50]}"
                if key not in analyzed_set:
                    analyzed_set.add(key)
                    causes.append(RootCause(
                        category=IssueCategory.TOO_MANY_STEPS,
                        confidence=0.90,
                        signals=[f"error_message: {error_msg[:100]}"],
                        suggested_fixes=[
                            "Simplify the scenario prompt",
                            "Break scenario into smaller sub-scenarios",
                            "Try orchestration_mode='strict' to be more efficient",
                        ],
                    ))
                break
        
        # No progress patterns
        for pattern in self.NO_PROGRESS_PATTERNS:
            if re.search(pattern, error_lower):
                key = f"no_progress_detected:{error_msg[:50]}"
                if key not in analyzed_set:
                    analyzed_set.add(key)
                    causes.append(RootCause(
                        category=IssueCategory.NO_PROGRESS,
                        confidence=0.80,
                        signals=[f"error_message: {error_msg[:100]}"],
                        suggested_fixes=[
                            "Check for loops in the orchestration",
                            "Consider if prompt is achievable with current tools",
                            "Add more guardrails to prevent tool misuse",
                        ],
                    ))
                break
        
        # Connector error patterns
        for pattern in self.CONNECTOR_ERROR_PATTERNS:
            if re.search(pattern, error_lower):
                key = f"connector_error_detected:{error_msg[:50]}"
                if key not in analyzed_set:
                    analyzed_set.add(key)
                    
                    if "unauthorized" in error_lower or "forbidden" in error_lower:
                        category = IssueCategory.AUTH_FAILED
                    elif "rate" in error_lower or "limit" in error_lower:
                        category = IssueCategory.RATE_LIMITED
                    else:
                        category = IssueCategory.CONNECTOR_ERROR
                    
                    causes.append(RootCause(
                        category=category,
                        confidence=0.80,
                        signals=[f"error_message: {error_msg[:100]}"],
                        suggested_fixes=[
                            "Check connector authentication and credentials",
                            "Verify connector is in good health",
                            "Review connector-specific rate limits and quotas",
                        ],
                    ))
                break
    
    def _analyze_failed_step(self, step: Dict[str, Any], causes: List[RootCause], analyzed_set: Set[str]) -> None:
        """Analyze individual failed steps."""
        step_error = str(step.get("error", "")).lower()
        tool_name = str(step.get("tool", "unknown"))
        
        if not step_error:
            return
        
        key = f"step_error:{tool_name}:{step_error[:30]}"
        if key in analyzed_set:
            return
        analyzed_set.add(key)
        
        # Check for auth/connector issues in step errors
        if any(p in step_error for p in ["unauthorized", "forbidden", "credential", "auth"]):
            causes.append(RootCause(
                category=IssueCategory.AUTH_FAILED,
                confidence=0.85,
                signals=[f"step_tool: {tool_name}", f"error: {step_error[:80]}"],
                suggested_fixes=[
                    f"Verify {tool_name} connector authentication",
                    "Check stored credentials are valid and up-to-date",
                    "Re-authenticate if credentials have expired",
                ],
            ))
        
        # Check for rate limiting
        elif any(p in step_error for p in ["rate limit", "quota", "throttle"]):
            causes.append(RootCause(
                category=IssueCategory.RATE_LIMITED,
                confidence=0.90,
                signals=[f"step_tool: {tool_name}", f"error: {step_error[:80]}"],
                suggested_fixes=[
                    f"Check {tool_name} rate limit quotas",
                    "Add delays between API calls",
                    "Consider distributing load over time",
                ],
            ))
        
        # Generic tool failure
        else:
            causes.append(RootCause(
                category=IssueCategory.TOOL_FAILED,
                confidence=0.75,
                signals=[f"step_tool: {tool_name}", f"error: {step_error[:80]}"],
                suggested_fixes=[
                    f"Investigate {tool_name} connector error",
                    "Check tool-specific logs and diagnostics",
                    "Verify tool has required data/permissions",
                ],
            ))
    
    def _categorize_error_pattern(self, pattern: str) -> IssueCategory:
        """Infer issue category from error pattern regex."""
        pattern_lower = pattern.lower()
        
        if any(p in pattern_lower for p in ["timeout", "time", "exceeded"]):
            return IssueCategory.TIMEOUT
        elif any(p in pattern_lower for p in ["step", "max", "loop"]):
            return IssueCategory.TOO_MANY_STEPS
        elif any(p in pattern_lower for p in ["progress", "stuck"]):
            return IssueCategory.NO_PROGRESS
        else:
            return IssueCategory.UNKNOWN
    
    def _suggest_fixes_for_pattern(self, pattern: str) -> List[str]:
        """Suggest fixes based on a forbidden error pattern."""
        pattern_lower = pattern.lower()
        
        if "timeout" in pattern_lower or "time" in pattern_lower:
            return [
                "Increase timeout_seconds in scenario config",
                "Optimize prompt for faster execution",
                "Check system resources and load",
            ]
        elif "step" in pattern_lower or "max" in pattern_lower:
            return [
                "Simplify scenario prompt",
                "Break into smaller scenarios",
                "Use orchestration_mode='strict'",
            ]
        else:
            return [
                "Review error pattern in scenario checks",
                "Adjust checks to be more forgiving if appropriate",
            ]
    
    def _is_remediable(self, root_causes: List[RootCause]) -> bool:
        """Check if this failure can be automatically remediated."""
        if not root_causes:
            return False
        
        # Matters of configuration/environment can be fixed
        remediable_categories = {
            IssueCategory.TIMEOUT,
            IssueCategory.TOO_MANY_STEPS,
            IssueCategory.WRONG_MODE,
            IssueCategory.AMBIGUOUS_INTENT,
            IssueCategory.APPROVAL_TIMEOUT,
            IssueCategory.INCOMPLETE_RESPONSE,
        }
        
        # Check if any cause is likely remediable
        return any(rc.category in remediable_categories for rc in root_causes)
    
    def _calculate_priority(self, root_causes: List[RootCause]) -> int:
        """Calculate remediation priority (1=critical, 4=low)."""
        if not root_causes:
            return 4
        
        # Critical issues
        critical_categories = {
            IssueCategory.MISSING_TOOL,
            IssueCategory.MISSING_CONNECTOR,
            IssueCategory.AUTH_FAILED,
        }
        
        if any(rc.category in critical_categories for rc in root_causes):
            return 1
        
        # High priority
        high_priority_categories = {
            IssueCategory.CONNECTOR_ERROR,
            IssueCategory.TOOL_FAILED,
            IssueCategory.MISSING_OUTPUT,
        }
        
        if any(rc.category in high_priority_categories for rc in root_causes):
            return 2
        
        # Medium priority
        medium_priority_categories = {
            IssueCategory.TIMEOUT,
            IssueCategory.TOO_MANY_STEPS,
            IssueCategory.NO_PROGRESS,
        }
        
        if any(rc.category in medium_priority_categories for rc in root_causes):
            return 3
        
        return 4
    
    def _suggest_next_steps(self, root_causes: List[RootCause]) -> List[str]:
        """Generate next steps for addressing these root causes."""
        steps = []
        
        for cause in root_causes:
            steps.extend(cause.suggested_fixes)
        
        # Deduplicate and limit to top 5
        unique_steps = []
        seen = set()
        for step in steps:
            if step not in seen:
                unique_steps.append(step)
                seen.add(step)
                if len(unique_steps) >= 5:
                    break
        
        return unique_steps


def create_analyzer() -> IssueAnalyzer:
    """Factory for creating issue analyzer instances."""
    return IssueAnalyzer()
