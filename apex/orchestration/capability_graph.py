"""Runtime capability graph for orchestration.

This graph is derived from the currently available tool set and remains generic
for newly added primitives/connectors.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class CapabilitySummary:
    total_tools: int
    side_effect_tools: int
    readonly_tools: int
    domains: Dict[str, int]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_tools": self.total_tools,
            "side_effect_tools": self.side_effect_tools,
            "readonly_tools": self.readonly_tools,
            "domains": self.domains,
        }


class OrchestrationCapabilityGraph:
    """Summarize available orchestration capabilities from tools."""

    def __init__(self, domain_counts: Dict[str, int], side_effect_tools: int, total_tools: int):
        self.domain_counts = domain_counts
        self.side_effect_tools = side_effect_tools
        self.total_tools = total_tools

    @staticmethod
    def _infer_domain(tool_name: str) -> str:
        if "_" not in tool_name:
            return "GENERIC"
        return tool_name.split("_", 1)[0].upper()

    @classmethod
    def from_tools(cls, tools: List[Any]) -> "OrchestrationCapabilityGraph":
        domain_counts: Dict[str, int] = defaultdict(int)
        side_effect_tools = 0

        for t in tools:
            name = getattr(t, "name", "")
            if not name:
                continue
            domain = cls._infer_domain(name)
            domain_counts[domain] += 1
            if bool(getattr(t, "side_effect", False)):
                side_effect_tools += 1

        return cls(
            domain_counts=dict(sorted(domain_counts.items(), key=lambda kv: kv[0])),
            side_effect_tools=side_effect_tools,
            total_tools=len(tools),
        )

    def summary(self) -> CapabilitySummary:
        readonly = max(0, self.total_tools - self.side_effect_tools)
        return CapabilitySummary(
            total_tools=self.total_tools,
            side_effect_tools=self.side_effect_tools,
            readonly_tools=readonly,
            domains=self.domain_counts,
        )
