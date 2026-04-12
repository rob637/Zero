"""
Scenario Author Assistant for The Harness

Guides scenario creators to build high-quality test scenarios that:
- Test meaningful cross-connector workflows
- Avoid hard-coding connector/primitive/orchestration specifics
- Define clear success criteria
- Scale to 100s of scenarios
"""

from dataclasses import dataclass
from typing import Optional, List
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ScenarioQuality(Enum):
    """Quality assessment for a scenario."""
    POOR = 1
    FAIR = 2
    GOOD = 3
    EXCELLENT = 4


@dataclass
class ScenarioTemplate:
    """Well-constructed scenario template."""
    category: str  # e.g., "Executive Recap", "Research", "Workflow Automation"
    prompt: str  # The user request
    why_its_good: str  # Educational explanation
    test_coverage: List[str]  # What it tests
    success_criteria: List[str]  # How to judge success
    connector_profile: dict  # Abstract connector needs (not specific connectors)
    estimated_duration_seconds: int
    difficulty_level: str  # "easy", "medium", "hard"


class ScenarioAuthorAssistant:
    """
    Helps scenario authors write high-quality scenarios.
    
    Philosophy:
    - Scenarios describe USER WORKFLOWS, not connector tests
    - Quality is measured by coverage (multi-connector + orchestration)
    - Scenarios must work with evolving connector set (not hard-coded)
    """
    
    PILLARS = {
        'primitives': {
            'description': 'Core AI capabilities (plan, reason, summarize, etc.)',
            'bad_example': 'Test that Google Sheets returns 47 rows',
            'good_example': 'Test reading multi-connector data and creating summary',
        },
        'connectors': {
            'description': 'External integrations (Gmail, Calendar, Todoist, etc.)',
            'bad_example': 'Test Gmail-specific OAuth flow',
            'good_example': 'Test reading unread messages from any mail connector',
        },
        'orchestration': {
            'description': 'Workflow coordination (sequence, parallel, conditional)',
            'bad_example': 'Hard-code: "First call Gmail, then Todoist"',
            'good_example': 'Test smart routing of tasks to appropriate connectors',
        },
    }
    
    CATEGORIES = [
        "Executive Recap",
        "Daily Synthesis",
        "Task Automation",
        "Content Creation",
        "Research & Learning",
        "Travel & Planning",
        "Financial",
        "Creative",
        "Health & Wellness",
        "Team Coordination",
    ]
    
    def __init__(self):
        self.quality_checklist = self._build_quality_checklist()
    
    def _build_quality_checklist(self) -> dict:
        """Define what makes a high-quality scenario."""
        return {
            'user_centric': {
                'name': 'User-Centric Prompt',
                'description': 'Scenario describes what a USER wants, not what a system does',
                'questions': [
                    'Would a real person ask for this?',
                    'Does it solve a real problem?',
                    'Is it under-specified on HOW (good)?',
                    'Is it over-specified on WHICH_CONNECTOR (bad)?',
                ],
            },
            'multi_connector': {
                'name': 'Multi-Connector Coverage',
                'description': 'Scenario naturally requires 2+ connectors working together',
                'questions': [
                    'Does this test single connector in isolation? (avoid)',
                    'Does this require synthesizing data from multiple sources?',
                    'Does it test connector failure handling?',
                ],
            },
            'intelligence_required': {
                'name': 'Tests Primitives/AI',
                'description': 'Scenario exercises reasoning, planning, summarization, etc.',
                'questions': [
                    'Does the prompt require synthesis/summarization?',
                    'Does it need smart prioritization?',
                    'Does it require understanding context across sources?',
                ],
            },
            'measurable_success': {
                'name': 'Clear Success Criteria',
                'description': 'Unambiguous way to judge if scenario passed',
                'questions': [
                    'Can you objectively score success? (not subjective)',
                    'Are criteria testable by a non-human?',
                    'Do they measure quality, not just "did it run"?',
                ],
            },
            'resilience_testing': {
                'name': 'Tests Failure Handling',
                'description': 'Scenario reveals what happens when connectors fail',
                'questions': [
                    'What if one connector is offline?',
                    'What if data is missing/incomplete?',
                    'Does scenario have graceful degradation?',
                ],
            },
            'non_deterministic': {
                'name': 'Real-World Variance',
                'description': 'Scenario works with varying inputs (not brittle)',
                'questions': [
                    'Are success criteria based on exact values? (bad)',
                    'Do they tolerate data variance?',
                    'Does ordering matter? (should not)',
                ],
            },
        }
    
    def analyze_scenario(self, scenario: dict) -> tuple[ScenarioQuality, dict]:
        """
        Analyze a proposed scenario.
        
        Returns:
            (quality_level, detailed_feedback)
        """
        feedback = {}
        scores = {}
        
        # Check prompt quality
        prompt = scenario.get('prompt', '')
        feedback['prompt_analysis'] = self._analyze_prompt(prompt)
        
        # Check coverage against pillars
        coverage = self._check_pillar_coverage(scenario)
        feedback['pillar_coverage'] = coverage
        scores['coverage'] = coverage['score']
        
        # Check success criteria
        criteria = scenario.get('success_criteria', [])
        feedback['success_criteria_analysis'] = self._analyze_criteria(criteria)
        scores['criteria'] = feedback['success_criteria_analysis'].get('score', 0)
        
        # Check connector assumptions
        assumptions = self._find_hard_coded_assumptions(scenario)
        feedback['hard_coded_assumptions'] = assumptions
        scores['assumptions'] = 1.0 if not assumptions else 0.5
        
        # Calculate overall quality
        avg_score = sum(scores.values()) / len(scores) if scores else 0
        quality = self._score_to_quality(avg_score)
        
        return quality, feedback
    
    def _analyze_prompt(self, prompt: str) -> dict:
        """Analyze if prompt is user-centric and flexible."""
        red_flags = []
        green_flags = []
        
        # Red flags
        connector_names = ['Gmail', 'Google Calendar', 'Todoist', 'GitHub', 'Slack']
        for name in connector_names:
            if name in prompt:
                red_flags.append(f"Hard-coded connector name: '{name}'")
        
        if 'API' in prompt or 'call this endpoint' in prompt:
            red_flags.append("Technical implementation details (bad for user-centric)")
        
        # Green flags
        if 'user' in prompt.lower() or 'i' in prompt.lower()[:50]:
            green_flags.append("Prompt is user-centric (from user perspective)")
        
        if any(keyword in prompt.lower() for keyword in ['any', 'all', 'multiple', 'various']):
            green_flags.append("Prompt allows flexibility in connectors")
        
        return {
            'red_flags': red_flags,
            'green_flags': green_flags,
            'score': max(0, 1.0 - (len(red_flags) * 0.2) + (len(green_flags) * 0.15)),
        }
    
    def _check_pillar_coverage(self, scenario: dict) -> dict:
        """Check if scenario tests multiple pillars."""
        connectors_mentioned = scenario.get('connectors_involved', [])
        primitives_used = scenario.get('primitives_used', [])
        orchestration_needed = scenario.get('orchestration_required', False)
        
        coverage = {
            'primitives': len(primitives_used) > 0,
            'connectors': len(connectors_mentioned) >= 2,  # Multi-connector
            'orchestration': orchestration_needed,
        }
        
        num_covered = sum(1 for v in coverage.values() if v)
        
        feedback = []
        if not coverage['primitives']:
            feedback.append("❌ Doesn't test primitives/AI reasoning")
        else:
            feedback.append(f"✓ Tests primitives: {', '.join(primitives_used[:2])}")
        
        if not coverage['connectors']:
            feedback.append("❌ Doesn't involve multiple connectors")
        else:
            feedback.append(f"✓ Tests {len(connectors_mentioned)} connectors")
        
        if not coverage['orchestration']:
            feedback.append("⚠ Doesn't heavily test orchestration")
        else:
            feedback.append("✓ Tests orchestration/workflow")
        
        return {
            'coverage': coverage,
            'feedback': feedback,
            'score': num_covered / 3.0,
        }
    
    def _analyze_criteria(self, criteria: list) -> dict:
        """Analyze success criteria for quality."""
        if not criteria:
            return {'score': 0, 'feedback': 'No success criteria defined'}
        
        issues = []
        for criterion in criteria:
            if isinstance(criterion, str):
                # Check for measurability
                if 'subjective' in criterion.lower():
                    issues.append(f"Subjective criterion (avoid): {criterion[:50]}")
                if 'beautiful' in criterion.lower() or 'good' in criterion.lower():
                    issues.append(f"Vague criterion: {criterion[:50]}")
                if 'exactly' in criterion.lower() or '==' in criterion:
                    issues.append(f"Overly strict criterion: {criterion[:50]}")
        
        quality_score = max(0, 1.0 - (len(issues) * 0.15))
        return {
            'total_criteria': len(criteria),
            'issues': issues,
            'score': quality_score,
        }
    
    def _find_hard_coded_assumptions(self, scenario: dict) -> list:
        """Find assumptions that break when system evolves."""
        assumptions = []
        
        prompt = scenario.get('prompt', '')
        
        # Check for hard-coded connector assumptions
        patterns = [
            ('Google', 'Assumes Google connectors'),
            ('Microsoft', 'Assumes Microsoft connectors'),
            ('specific order', 'Assumes specific execution order'),
            ('first call', 'Hard-codes sequence'),
            ('always ', 'Hard-codes behavior'),
        ]
        
        for pattern, issue in patterns:
            if pattern.lower() in prompt.lower():
                assumptions.append(issue)
        
        return assumptions
    
    def _score_to_quality(self, score: float) -> ScenarioQuality:
        """Convert numeric score to quality level."""
        if score < 0.4:
            return ScenarioQuality.POOR
        elif score < 0.65:
            return ScenarioQuality.FAIR
        elif score < 0.85:
            return ScenarioQuality.GOOD
        else:
            return ScenarioQuality.EXCELLENT
    
    def suggest_improvements(self, scenario: dict, feedback: dict) -> list:
        """Suggest how to improve a scenario."""
        suggestions = []
        
        # Based on red flags
        if feedback['prompt_analysis']['red_flags']:
            suggestions.append({
                'type': 'Make prompt connector-agnostic',
                'example': 'Instead of "Pull from Gmail", say "Pull unread messages"',
                'impact': 'Scenario works as system evolves',
            })
        
        # Based on coverage
        coverage = feedback['pillar_coverage']['coverage']
        if not coverage['connectors']:
            suggestions.append({
                'type': 'Involve more connectors',
                'example': 'Dont just test single data source - synthesize across sources',
                'impact': 'Tests orchestration and synthesis',
            })
        
        if not coverage['primitives']:
            suggestions.append({
                'type': 'Add intelligence requirement',
                'example': 'Add summarization, prioritization, or reasoning step',
                'impact': 'Tests AI capabilities, not just data retrieval',
            })
        
        return suggestions
    
    def generate_scenario_template(self, category: str) -> ScenarioTemplate:
        """Generate a template for creating scenario in a category."""
        templates = {
            'Executive Recap': ScenarioTemplate(
                category='Executive Recap',
                prompt='[USER_REQUEST: Summarize week across all sources - calendar, email, tasks]',
                why_its_good='Tests synthesis, date filtering, cross-connector reliability',
                test_coverage=['Multi-connector read', 'Summarization', 'Date filtering', 'Partial failure handling'],
                success_criteria=[
                    'Includes events from calendar',
                    'Includes tasks from task manager',
                    'Includes email summary',
                    'Missing data doesnt break report',
                ],
                connector_profile={
                    'read_calendar': True,
                    'read_email': True,
                    'read_tasks': True,
                    'write': False,
                    'requires_auth': True,
                },
                estimated_duration_seconds=30,
                difficulty_level='medium',
            ),
        }
        
        return templates.get(category)


def guide_scenario_creation():
    """Interactive guide for creating a scenario."""
    assistant = ScenarioAuthorAssistant()
    
    print("\n" + "="*70)
    print("SCENARIO AUTHOR ASSISTANT - The Harness")
    print("="*70)
    print("\nThis tool guides you to create high-quality scenarios that test")
    print("real workflows across Primitives, Connectors, and Orchestration.")
    print("\n" + "-"*70)
    print("KEY PRINCIPLE: Scenarios describe USER WORKFLOWS, not connector tests")
    print("-"*70)
    
    print("\n📚 Available scenario categories:")
    for i, cat in enumerate(assistant.CATEGORIES, 1):
        print(f"   {i}. {cat}")
    
    return assistant
