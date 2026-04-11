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

## Notes

- The harness calls `/react/chat` and follows `/react/approve` when pending approvals exist.
- Use `--auto-approve` for unattended regression runs.
- Use `--suite core` for fast gating and `--suite nightly` for broader coverage.
- Keep checks generic and capability-based (no scenario hard-coding in engine logic).
