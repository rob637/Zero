# Scenario Harness

Run repeatable scenario prompts against the live Telic API and score outcomes automatically.

## Files

- Runner: `apex/tools/run_scenarios.py`
- Scenario spec: `apex/scenarios/regression_scenarios.json`
- Reports: `apex/scenarios/reports/latest/`

## Quick Start

1. Start Telic server on `http://127.0.0.1:8000`.
2. Run all scenarios:

```bash
python apex/tools/run_scenarios.py --base-url http://127.0.0.1:8000 --auto-approve
```

3. Run core gate scenarios (fast must-pass subset):

```bash
python apex/tools/run_scenarios.py --suite core --base-url http://127.0.0.1:8000 --auto-approve
```

4. Run nightly scenarios (broader suite):

```bash
python apex/tools/run_scenarios.py --suite nightly --base-url http://127.0.0.1:8000 --auto-approve
```

5. Run one scenario:

```bash
python apex/tools/run_scenarios.py \
  --scenario-file apex/scenarios/regression_scenarios.json \
  --scenario germany-photo-story \
  --base-url http://127.0.0.1:8000 \
  --auto-approve
```

6. Open reports:

- `apex/scenarios/reports/latest/scenario_report.json`
- `apex/scenarios/reports/latest/scenario_report.md`
- `apex/scenarios/reports/latest/campaign_report.json`
- `apex/scenarios/reports/latest/campaign_report.md`
- `apex/scenarios/reports/latest/harness_report.json`
- `apex/scenarios/reports/latest/harness_report.md`

## First Iteration: 5 Scenarios

For the first real Harness pass, run the current five-scenario set as a single iteration:

```bash
python apex/tools/run_scenarios.py \
  --base-url http://127.0.0.1:8000 \
  --scenario-limit 5 \
  --iterations 1 \
  --auto-approve
```

Recommended output review order:

1. `harness_report.md` for rerun queue and diagnosed failures.
2. `scenario_report.md` for raw scenario pass/fail detail.
3. `campaign_report.md` for iteration trend once you move beyond one pass.

## Iterative Campaign Mode

Run the harness as a multi-iteration campaign that tracks convergence:

```bash
python apex/tools/run_scenarios.py \
  --base-url http://127.0.0.1:8000 \
  --suite core \
  --iterations 6 \
  --target-pass-rate 1.0 \
  --max-no-improvement 2 \
  --rerun-failed-only \
  --auto-approve
```

What this adds:

- Iteration history in `.../iterations/iter-XXX/`
- Campaign-level trend report (`campaign_report.*`)
- Harness-level diagnosis and rerun queue (`harness_report.*`)
- Early stop when pass rate reaches target
- Early stop when no improvement persists
- Optional failed-only reruns for faster triage loops

## Scaling To 100s Of Scenarios

Use suite slicing and limits while you scale scenario volume:

```bash
python apex/tools/run_scenarios.py --suite core --scenario-limit 50 --shuffle --seed 42
python apex/tools/run_scenarios.py --suite nightly --scenario-limit 200 --shuffle --seed 42
```

For multi-file scenario packs:

```bash
python apex/tools/run_scenarios.py \
  --scenario-dir apex/scenarios/packs \
  --scenario-glob "*.json" \
  --suite nightly
```

For distributed shards in CI:

```bash
python apex/tools/run_scenarios.py --suite nightly --shard-total 4 --shard-index 0
python apex/tools/run_scenarios.py --suite nightly --shard-total 4 --shard-index 1
python apex/tools/run_scenarios.py --suite nightly --shard-total 4 --shard-index 2
python apex/tools/run_scenarios.py --suite nightly --shard-total 4 --shard-index 3
```

Recommended ramp:

1. Keep `core` as strict must-pass gate.
2. Expand `nightly` breadth aggressively.
3. Use `--rerun-failed-only` during fix loops.
4. Keep checks capability-based and generic.

## Scenario Schema (JSON)

Each scenario has:

- `id`: unique id
- `name`: display name
- `suites`: list of suite tags (`core`, `nightly`)
- `prompt`: user prompt text
- `timeout_seconds` (optional)
- `orchestration_mode` (optional)
- `max_approvals` (optional)
- `checks`:
  - `required_tools`: list of expected tool names
  - `forbidden_tools`: list of disallowed tool names
  - `required_output_patterns`: regex patterns that must appear in final response
  - `forbidden_output_patterns`: regex patterns that must not appear
  - `forbidden_error_patterns`: regex patterns that must not appear in step errors/results
  - `max_failed_steps`: max allowed failed steps

## Exit Code

- `0`: all scenarios passed (or `--allow-failures` used)
- `1`: one or more scenarios failed
- `2`: invalid scenario input/config
- `3`: blocked by preflight runtime configuration

## Notes

- The harness calls `/react/chat` and follows `/react/approve` when pending approvals exist.
- Use `--auto-approve` for unattended regression runs.
- Use `--suite core` for fast gating and `--suite nightly` for broader coverage.
- Keep checks generic and capability-based (no scenario hard-coding in engine logic).
