# Harness Sprint: 2-Day Execution Plan

Purpose: build an automated Harness loop that scales to hundreds or thousands of scenarios without hard-coded scenario logic.

## Core Principle

- We do not code scenario-specific handling.
- The product runtime must remain generic: primitives, connectors, orchestration, and the AI engine must handle scenarios through capability metadata and reasoning.
- The Harness may contain engineering for execution, diagnosis, triage, reporting, and repair loops, but not scenario-specific special cases.

## Non-Negotiables

- No "if scenario == X" logic in planner, primitives, connectors, or orchestration.
- No prompt rule pile that maps intents to tools by hand.
- Fixes must improve generic capability behavior, connector reliability, orchestration control, or evaluation quality.
- Scenario definitions remain prompts plus generic checks.

## Sprint Goal

By the end of this sprint, we can run large scenario sets in an automated loop, classify failures generically, prioritize reruns, and create a clean path for autonomous repair work.

## What We Are Building

### 1. Execution Loop

- Run scenario packs in bulk.
- Support suite slicing, sharding, rerun-failed-only, and convergence tracking.
- Produce machine-readable reports for dashboards and repair workers.

### 2. Diagnosis Loop

- Classify failures by root cause category.
- Separate connector/auth failures from primitive/orchestration/AI failures.
- Produce prioritized rerun queues and remediation guidance.

### 3. Repair Loop

- Feed diagnosed failures into a coding/repair workflow.
- Make only generic fixes at the primitive, connector, orchestration, or evaluation layer.
- Re-run targeted scenarios after each fix.

### 4. Control Plane

- Dashboard shows campaign health, scenario status, connector status, failure clusters, and rerun queues.
- Remote execution support is for Harness operations, not for hard-coded scenario logic.

## Explicitly Out Of Scope

- Encoding bespoke behavior for specific scenarios.
- Adding planner rules for named scenarios.
- Hard-wiring tool selection to prompt phrases.
- Treating user personal accounts as the only long-term regression environment.

## 2-Day Sprint Plan

### Day 1 Morning: Harness Ground Truth

- Validate current bulk-run path against core and nightly suites.
- Lock report schema for campaign, harness, and scenario outputs.
- Ensure dashboard is reading the same canonical report fields used by the CLI.

Exit criteria:

- A full run produces stable JSON reports.
- Dashboard displays accurate pass rate, pass/fail counts, and scenario rows.
- Failure categories are visible without reading raw logs.

### Day 1 Afternoon: Generic Failure Classification

- Tighten diagnosis categories and confidence signals.
- Distinguish these classes cleanly:
  - connector/auth/environment
  - primitive behavior
  - orchestration/loop/progress
  - output-quality or missing-output
  - evaluation/schema mismatch
- Ensure rerun queues are driven by generic failure signatures.

Exit criteria:

- Latest harness report shows normalized diagnosed failures.
- Top failure signatures are useful for repair prioritization.
- No scenario-specific classification code is introduced.

### Day 2 Morning: Autonomous Repair Pipeline Skeleton

- Create a repair-runner contract that consumes diagnosed failures.
- Define safe auto-fix eligibility rules:
  - only generic code paths
  - only high-confidence remediable issues
  - mandatory targeted rerun after change
- Persist repair attempts and outcomes.

Exit criteria:

- There is a concrete machine-readable input/output contract for repair runs.
- We can launch a targeted repair attempt against failing scenarios.
- The system records before/after pass-rate deltas.

### Day 2 Afternoon: Remote Regression Operating Model

- Define the remote Harness runtime for Codespaces/CI.
- Separate local-product runtime from regression-lab runtime.
- Specify connector strategy for regression environments:
  - dedicated test tenants where possible
  - seeded data accounts
  - personal-account runs only when explicitly needed

Exit criteria:

- We have an executable operating model for large-scale regression runs.
- Scenario packs can be sharded in remote environments.
- Dashboard/control-plane direction is clear.

## Acceptance Criteria

- Harness supports large scenario packs without scenario-specific code.
- Failures are classified generically and prioritized automatically.
- A repair loop can consume diagnosed failures and run targeted reruns.
- Dashboard/reporting reflects the same canonical run data.
- The app architecture continues to rely on AI reasoning over primitives and connectors, not bespoke workflows.

## Architecture Guardrails

When something fails, choose one of these fixes:

- Improve primitive description or schema.
- Improve connector reliability, health, auth, fallback, or error normalization.
- Improve orchestration state handling, loop control, or verification.
- Improve evaluator/reporting accuracy.
- Improve AI engine prompting only at a generic capability level.

Never choose these fixes:

- Add a special case for one scenario.
- Add a phrase-to-tool rule for one prompt family.
- Patch output checks to hide a genuine system weakness.

## Immediate Work Queue

1. Stabilize the dashboard and canonical report path.
2. Normalize diagnosed failure categories and confidence.
3. Add a repair-runner contract and result schema.
4. Run the failing core scenario through the new loop.
5. Expand scenario packs and prepare remote sharding.

## Definition Of Done For This Sprint

We are done when the Harness can run bulk scenarios, explain failures generically, feed those failures into a repair workflow, and improve pass rate without introducing scenario hard-coding.