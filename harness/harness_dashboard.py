"""
The Harness Dashboard & Visualization

Real-time monitoring and reporting of scenario test runs.
Shows pass/fail rates, issue patterns, and remediation effectiveness.
"""

from dataclasses import dataclass
from typing import List, Dict, Optional
from datetime import datetime
from collections import defaultdict
import json
import logging

logger = logging.getLogger(__name__)


@dataclass
class ScenarioStats:
    """Rolling statistics for a single scenario."""
    scenario_id: str
    scenario_name: str
    total_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    retries_triggered: int = 0
    fixed_by_remediation: int = 0
    avg_duration_seconds: float = 0.0
    last_run_time: str = ""
    most_common_issue: str = ""
    total_duration_seconds: float = 0.0


@dataclass
class GlobalStats:
    """System-wide statistics."""
    total_scenarios: int = 0
    total_runs: int = 0
    overall_pass_rate: float = 0.0
    avg_retries_per_failure: float = 0.0
    remediation_success_rate: float = 0.0
    most_common_issue_category: str = ""
    most_problematic_connectors: List[str] = None


class HarnessTracking:
    """Tracks all scenario executions for logging and dashboard."""
    
    def __init__(self):
        self.scenario_stats: Dict[str, ScenarioStats] = {}
        self.run_history: List[dict] = []
        self.issue_patterns: Dict[str, int] = defaultdict(int)
        self.connector_failures: Dict[str, int] = defaultdict(int)
        self.remediation_history: List[dict] = []
        self.scenario_issue_patterns: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.iteration_history: List[dict] = []
        self.retry_sessions: int = 0
    
    def record_run(self, session):
        """Record a scenario retry session execution."""
        issue_categories = [attempt.diagnosis.get('category', 'unknown') for attempt in session.attempts]
        affected_connectors: List[str] = []
        for attempt in session.attempts:
            affected_connectors.extend(attempt.diagnosis.get('affected_connectors', []))

        self.record_scenario_result(
            scenario_id=session.scenario_id,
            scenario_name=session.scenario_name,
            result=session.final_result,
            duration_seconds=session.total_duration_seconds,
            attempts=len(session.attempts),
            initial_error=session.initial_error,
            issue_categories=issue_categories,
            affected_connectors=affected_connectors,
            fixed_by_remediation=bool(session.attempts and session.final_result == 'success'),
        )

        if session.attempts:
            self.remediation_history.append(
                {
                    'scenario_id': session.scenario_id,
                    'scenario_name': session.scenario_name,
                    'attempt_count': len(session.attempts),
                    'final_result': session.final_result,
                    'timestamp': datetime.now().isoformat(),
                }
            )

    def record_scenario_result(
        self,
        *,
        scenario_id: str,
        scenario_name: str,
        result: str,
        duration_seconds: float,
        attempts: int = 0,
        initial_error: str = "",
        issue_categories: Optional[List[str]] = None,
        affected_connectors: Optional[List[str]] = None,
        fixed_by_remediation: bool = False,
    ):
        """Record a normalized scenario outcome from a campaign or retry session."""
        if scenario_id not in self.scenario_stats:
            self.scenario_stats[scenario_id] = ScenarioStats(
                scenario_id=scenario_id,
                scenario_name=scenario_name,
            )

        stats = self.scenario_stats[scenario_id]
        stats.total_runs += 1
        stats.last_run_time = datetime.now().isoformat()
        stats.total_duration_seconds += max(duration_seconds, 0.0)
        stats.avg_duration_seconds = stats.total_duration_seconds / stats.total_runs

        if result == 'success':
            stats.successful_runs += 1
        else:
            stats.failed_runs += 1

        if attempts > 0:
            stats.retries_triggered += attempts
            self.retry_sessions += 1

        if fixed_by_remediation:
            stats.fixed_by_remediation += 1

        categories = issue_categories or []
        for category in categories:
            normalized_category = str(category)
            self.issue_patterns[normalized_category] += 1
            self.scenario_issue_patterns[scenario_id][normalized_category] += 1

        if self.scenario_issue_patterns[scenario_id]:
            stats.most_common_issue = max(
                self.scenario_issue_patterns[scenario_id],
                key=self.scenario_issue_patterns[scenario_id].get,
            )

        for connector in affected_connectors or []:
            self.connector_failures[str(connector)] += 1

        self.run_history.append({
            'timestamp': datetime.now().isoformat(),
            'scenario_id': scenario_id,
            'scenario_name': scenario_name,
            'result': result,
            'duration': duration_seconds,
            'attempts': attempts,
            'initial_error': initial_error[:100],
            'issue_categories': categories,
        })

    def record_iteration(self, iteration_summary: dict):
        """Record aggregate campaign iteration data."""
        self.iteration_history.append(iteration_summary)
    
    def get_scenario_stats(self, scenario_id: str) -> ScenarioStats:
        """Get stats for a specific scenario."""
        return self.scenario_stats.get(scenario_id)
    
    def get_global_stats(self) -> GlobalStats:
        """Get system-wide statistics."""
        if not self.scenario_stats:
            return GlobalStats()
        
        total_runs = sum(s.total_runs for s in self.scenario_stats.values())
        successful_runs = sum(s.successful_runs for s in self.scenario_stats.values())
        failed_runs = sum(s.failed_runs for s in self.scenario_stats.values())
        
        pass_rate = successful_runs / total_runs if total_runs > 0 else 0.0
        total_fixed = sum(s.fixed_by_remediation for s in self.scenario_stats.values())
        total_retries = sum(s.retries_triggered for s in self.scenario_stats.values())
        
        return GlobalStats(
            total_scenarios=len(self.scenario_stats),
            total_runs=total_runs,
            overall_pass_rate=pass_rate,
            avg_retries_per_failure=(total_retries / failed_runs) if failed_runs > 0 else 0.0,
            remediation_success_rate=(total_fixed / self.retry_sessions) if self.retry_sessions > 0 else 0.0,
            most_common_issue_category=max(self.issue_patterns, key=self.issue_patterns.get)
            if self.issue_patterns else "",
            most_problematic_connectors=sorted(
                self.connector_failures.items(),
                key=lambda x: x[1],
                reverse=True
            )[:5] if self.connector_failures else [],
        )


class HarnessDashboard:
    """
    Text-based and JSON dashboard for The Harness.
    Shows real-time scenario execution status and patterns.
    """
    
    def __init__(self, tracking: HarnessTracking):
        self.tracking = tracking
    
    def render_summary(self) -> str:
        """Render text summary of all scenarios."""
        stats = self.tracking.get_global_stats()
        
        lines = [
            "\n" + "="*80,
            "THE HARNESS - SCENARIO TEST DASHBOARD",
            "="*80,
            f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "📊 GLOBAL METRICS",
            "-" * 80,
            f"  Total Scenarios:  {stats.total_scenarios}",
            f"  Total Runs:       {stats.total_runs}",
            f"  Pass Rate:        {stats.overall_pass_rate:.1%} ✓",
            f"  Avg Retries/Fail: {stats.avg_retries_per_failure:.2f}",
            f"  Remedy Success:   {stats.remediation_success_rate:.1%}",
            f"  Common Issues:    {stats.most_common_issue_category}",
        ]
        
        if stats.most_problematic_connectors:
            lines.append("\n  Problem Connectors:")
            for conn, count in stats.most_problematic_connectors[:3]:
                lines.append(f"    • {conn}: {count} failures")
        
        return "\n".join(lines)
    
    def render_scenario_detail(self, scenario_id: str) -> str:
        """Render detailed view for one scenario."""
        scenario_stats = self.tracking.get_scenario_stats(scenario_id)
        
        if not scenario_stats:
            return f"No data for scenario: {scenario_id}"
        
        pass_rate = (
            scenario_stats.successful_runs / scenario_stats.total_runs
            if scenario_stats.total_runs > 0
            else 0.0
        )
        
        lines = [
            f"\n{'='*80}",
            f"SCENARIO: {scenario_stats.scenario_name}",
            f"{'='*80}",
            f"ID:                 {scenario_stats.scenario_id}",
            f"Total Runs:         {scenario_stats.total_runs}",
            f"Passed:             {scenario_stats.successful_runs}",
            f"Failed:             {scenario_stats.failed_runs}",
            f"Pass Rate:          {pass_rate:.1%}",
            f"Retries Triggered:  {scenario_stats.retries_triggered}",
            f"Fixed by Remedy:    {scenario_stats.fixed_by_remediation}",
            f"Common Issue:       {scenario_stats.most_common_issue}",
            f"Last Run:           {scenario_stats.last_run_time}",
            f"Avg Duration:       {scenario_stats.avg_duration_seconds:.1f}s",
        ]
        
        return "\n".join(lines)
    
    def render_table(self) -> str:
        """Render all scenarios as table."""
        lines = [
            "\n" + "="*120,
            "  SCENARIO SUMMARY TABLE",
            "="*120,
            f"{'Scenario':<40} {'Runs':>6} {'Passed':>6} {'Rate':>7} {'Retries':>8} {'Fixed':>6}",
            "-"*120,
        ]
        
        for scenario_id, stats in sorted(
            self.tracking.scenario_stats.items(),
            key=lambda x: x[1].total_runs,
            reverse=True
        ):
            pass_rate = (
                stats.successful_runs / stats.total_runs
                if stats.total_runs > 0
                else 0.0
            )
            
            # Rating emoji
            if pass_rate >= 0.9:
                rating = "✅"
            elif pass_rate >= 0.7:
                rating = "⚠️ "
            else:
                rating = "❌"
            
            lines.append(
                f"{stats.scenario_name:<40} {stats.total_runs:>6} "
                f"{stats.successful_runs:>6} {pass_rate:>6.0%} {stats.retries_triggered:>8} "
                f"{stats.fixed_by_remediation:>6} {rating}"
            )
        
        lines.append("="*120)
        return "\n".join(lines)
    
    def export_json(self) -> dict:
        """Export all data as JSON for integration."""
        stats = self.tracking.get_global_stats()
        
        scenarios_data = []
        for scenario_id, scenario_stats in self.tracking.scenario_stats.items():
            pass_rate = (
                scenario_stats.successful_runs / scenario_stats.total_runs
                if scenario_stats.total_runs > 0
                else 0.0
            )
            scenarios_data.append({
                'scenario_id': scenario_id,
                'scenario_name': scenario_stats.scenario_name,
                'total_runs': scenario_stats.total_runs,
                'successful_runs': scenario_stats.successful_runs,
                'failed_runs': scenario_stats.failed_runs,
                'pass_rate': pass_rate,
                'retries_triggered': scenario_stats.retries_triggered,
                'fixed_by_remediation': scenario_stats.fixed_by_remediation,
                'last_run_time': scenario_stats.last_run_time,
                'avg_duration_seconds': scenario_stats.avg_duration_seconds,
                'most_common_issue': scenario_stats.most_common_issue,
            })
        
        return {
            'global_stats': {
                'total_scenarios': stats.total_scenarios,
                'total_runs': stats.total_runs,
                'overall_pass_rate': stats.overall_pass_rate,
                'most_common_issue': stats.most_common_issue_category,
                'problem_connectors': [
                    {'connector': c, 'failure_count': count}
                    for c, count in stats.most_problematic_connectors
                ] if stats.most_problematic_connectors else [],
            },
            'scenarios': scenarios_data,
            'iterations': list(self.tracking.iteration_history),
            'timestamp': datetime.now().isoformat(),
        }
    
    def render_health_check(self) -> dict:
        """Quick health check - identifies scenarios needing attention."""
        health = {
            'timestamp': datetime.now().isoformat(),
            'critical': [],
            'warning': [],
            'healthy': [],
        }
        
        for scenario_id, stats in self.tracking.scenario_stats.items():
            if stats.total_runs == 0:
                continue
            
            pass_rate = stats.successful_runs / stats.total_runs
            
            if pass_rate < 0.5:
                health['critical'].append({
                    'scenario': stats.scenario_name,
                    'pass_rate': f"{pass_rate:.0%}",
                    'issue': 'Consistently failing - needs investigation',
                })
            elif pass_rate < 0.8:
                health['warning'].append({
                    'scenario': stats.scenario_name,
                    'pass_rate': f"{pass_rate:.0%}",
                    'issue': 'Flaky - may indicate orchestration issues',
                })
            else:
                health['healthy'].append(stats.scenario_name)
        
        return health
