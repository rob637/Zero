"""Generic remediation engine for The Harness.

Applies context-level fixes derived from diagnosis categories. The engine stays
generic so it can scale across scenario sets without encoding scenario-specific
behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from harness.diagnosis import IssueCategory


@dataclass
class RemediationStrategy:
    """Describes a generic remediation that can be applied before retry."""

    name: str
    category: str
    actions: List[str]
    confidence: float
    context_updates: Dict[str, Any] = field(default_factory=dict)
    prompt_suffixes: List[str] = field(default_factory=list)
    retryable: bool = True
    requires_manual_intervention: bool = False


class RemediationEngine:
    """Produces and applies generic scenario remediation strategies."""

    def __init__(self, max_timeout_seconds: int = 900, max_approvals: int = 20):
        self.max_timeout_seconds = max_timeout_seconds
        self.max_approvals = max_approvals

    def get_remediation(
        self,
        category: IssueCategory,
        root_cause: str,
        context: Dict[str, Any],
        error_details: List[str] | None = None,
    ) -> RemediationStrategy:
        """Choose a generic context-level remediation for a diagnosed issue."""
        category = self._normalize_category(category)
        details = error_details or []

        if category in {
            IssueCategory.TIMEOUT,
            IssueCategory.INCOMPLETE_RESPONSE,
        }:
            next_timeout = self._increase_timeout(int(context.get("timeout_seconds", 180)))
            return RemediationStrategy(
                name="increase_time_budget",
                category=category.value,
                confidence=0.85,
                context_updates={"timeout_seconds": next_timeout},
                actions=[
                    f"Increase timeout budget to {next_timeout} seconds",
                    "Retry with more runtime headroom",
                ],
            )

        if category in {
            IssueCategory.TOO_MANY_STEPS,
            IssueCategory.NO_PROGRESS,
            IssueCategory.WRONG_MODE,
            IssueCategory.LOOP_DETECTED,
        }:
            next_mode = self._escalate_mode(str(context.get("orchestration_mode", "balanced")))
            updates: Dict[str, Any] = {"orchestration_mode": next_mode}
            actions = [f"Escalate orchestration mode to '{next_mode}'"]
            if category in {IssueCategory.NO_PROGRESS, IssueCategory.LOOP_DETECTED}:
                updates["retry_focus"] = "reduce_looping"
                actions.append("Favor a more constrained orchestration path")
            return RemediationStrategy(
                name="adjust_orchestration_mode",
                category=category.value,
                confidence=0.80,
                context_updates=updates,
                actions=actions,
            )

        if category in {
            IssueCategory.APPROVAL_TIMEOUT,
            IssueCategory.TOO_MANY_APPROVALS,
        }:
            next_approvals = min(self.max_approvals, int(context.get("max_approvals", 8)) + 4)
            return RemediationStrategy(
                name="increase_approval_budget",
                category=category.value,
                confidence=0.75,
                context_updates={"max_approvals": next_approvals},
                actions=[
                    f"Increase approval budget to {next_approvals}",
                    "Retry while preserving execution state",
                ],
            )

        if category in {
            IssueCategory.MISSING_OUTPUT,
            IssueCategory.WRONG_FORMAT,
            IssueCategory.QUALITY_LOW,
            IssueCategory.AMBIGUOUS_INTENT,
            IssueCategory.MISSING_CONTEXT,
            IssueCategory.PLAN_DIVERGENCE,
        }:
            suffixes = self._build_prompt_guidance(category, root_cause, details)
            return RemediationStrategy(
                name="clarify_execution_contract",
                category=category.value,
                confidence=0.70,
                prompt_suffixes=suffixes,
                actions=[
                    "Append generic execution guidance to the prompt/context",
                    "Retry with clearer outcome expectations",
                ],
            )

        if category in {
            IssueCategory.MISSING_TOOL,
            IssueCategory.MISSING_CONNECTOR,
            IssueCategory.CONNECTOR_UNAVAILABLE,
            IssueCategory.CONNECTOR_ERROR,
            IssueCategory.AUTH_FAILED,
            IssueCategory.RATE_LIMITED,
            IssueCategory.TOOL_FAILED,
        }:
            return RemediationStrategy(
                name="requires_environment_fix",
                category=category.value,
                confidence=0.95,
                retryable=False,
                requires_manual_intervention=True,
                actions=[
                    "Connector or environment issue needs operator attention",
                    "Preserve diagnosis and stop automated retry loop",
                ],
            )

        return RemediationStrategy(
            name="capture_additional_context",
            category=category.value,
            confidence=0.50,
            actions=[
                "Record the failure context for manual review",
                "Avoid repeated retries without a stronger signal",
            ],
            retryable=False,
            requires_manual_intervention=True,
        )

    def _normalize_category(self, category: IssueCategory | str) -> IssueCategory:
        if isinstance(category, IssueCategory):
            return category
        try:
            return IssueCategory(str(category))
        except ValueError:
            return IssueCategory.UNKNOWN

    def apply_fix(
        self,
        remediation_strategy: RemediationStrategy,
        context: Dict[str, Any],
    ) -> Tuple[bool, Dict[str, Any]]:
        """Apply context updates and prompt guidance for a remediation strategy."""
        updated_context = dict(context)

        log = list(updated_context.get("remediation_log", []))
        log.append(
            {
                "name": remediation_strategy.name,
                "category": remediation_strategy.category,
                "actions": remediation_strategy.actions,
            }
        )
        updated_context["remediation_log"] = log

        if not remediation_strategy.retryable:
            updated_context["requires_manual_intervention"] = True
            updated_context["manual_intervention_reason"] = remediation_strategy.category
            return False, updated_context

        for key, value in remediation_strategy.context_updates.items():
            updated_context[key] = value

        if remediation_strategy.prompt_suffixes:
            guidance = "\n".join(remediation_strategy.prompt_suffixes)
            prompt = str(updated_context.get("prompt", "")).strip()
            updated_context["prompt"] = f"{prompt}\n\n{guidance}".strip()

        updated_context["last_remediation"] = remediation_strategy.name
        return True, updated_context

    def _increase_timeout(self, current_timeout: int) -> int:
        if current_timeout <= 0:
            current_timeout = 180
        return min(self.max_timeout_seconds, max(current_timeout + 60, int(current_timeout * 1.5)))

    def _escalate_mode(self, current_mode: str) -> str:
        normalized = current_mode.strip().lower() or "balanced"
        if normalized == "fast":
            return "balanced"
        if normalized == "balanced":
            return "strict"
        return "strict"

    def _build_prompt_guidance(
        self,
        category: IssueCategory,
        root_cause: str,
        error_details: List[str],
    ) -> List[str]:
        guidance = ["Execution guidance:"]

        if category == IssueCategory.MISSING_OUTPUT:
            guidance.append("- Include all required output sections before concluding.")
        elif category == IssueCategory.WRONG_FORMAT:
            guidance.append("- Match the requested output format exactly and avoid extra sections.")
        elif category == IssueCategory.QUALITY_LOW:
            guidance.append("- Improve synthesis quality and completeness before finalizing.")
        else:
            guidance.append("- Restate the intended outcome and satisfy it explicitly.")

        guidance.append(f"- Address diagnosed issue: {root_cause}.")
        if error_details:
            guidance.append(f"- Failure context: {error_details[0][:160]}.")
        return guidance