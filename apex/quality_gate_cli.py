"""CLI helper to evaluate orchestration quality gates.

Usage:
    python quality_gate_cli.py --base-url http://127.0.0.1:8000 --gate week2 --lookback 200 --window 20
    python quality_gate_cli.py --base-url http://127.0.0.1:8000 --gate week3-connectors
    python quality_gate_cli.py --base-url http://127.0.0.1:8000 --gate week4-replay --lookback 200 --window 20
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Telic orchestration quality gate")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="API base URL")
    parser.add_argument(
        "--gate",
        choices=[
            "week2",
            "week3-connectors",
            "week4-replay",
            "week5-ai-engine",
            "week5-benchmark",
            "week6-ui-trust",
            "week7-performance",
            "week8-launch",
        ],
        default="week2",
        help="Gate to evaluate",
    )
    parser.add_argument("--lookback", type=int, default=200, help="Evaluation lookback window")
    parser.add_argument("--window", type=int, default=20, help="Trend comparison window")
    args = parser.parse_args()

    if args.gate == "week3-connectors":
        url = f"{args.base_url.rstrip('/')}/orchestration/quality/week3-connectors-gate"
    elif args.gate == "week4-replay":
        query = urllib.parse.urlencode(
            {"lookback": args.lookback, "window": args.window, "replay_limit": 100}
        )
        url = f"{args.base_url.rstrip('/')}/orchestration/quality/week4-replay-gate?{query}"
    elif args.gate == "week5-ai-engine":
        query = urllib.parse.urlencode({"lookback": args.lookback, "window": args.window})
        url = f"{args.base_url.rstrip('/')}/orchestration/quality/week5-ai-engine-gate?{query}"
    elif args.gate == "week5-benchmark":
        query = urllib.parse.urlencode({"replay_limit": 100})
        url = f"{args.base_url.rstrip('/')}/orchestration/quality/week5-benchmark-gate?{query}"
    elif args.gate == "week6-ui-trust":
        query = urllib.parse.urlencode({"lookback": args.lookback, "window": args.window, "replay_limit": 100})
        url = f"{args.base_url.rstrip('/')}/orchestration/quality/week6-ui-trust-gate?{query}"
    elif args.gate == "week7-performance":
        query = urllib.parse.urlencode({"lookback": args.lookback})
        url = f"{args.base_url.rstrip('/')}/orchestration/quality/week7-performance-gate?{query}"
    elif args.gate == "week8-launch":
        query = urllib.parse.urlencode({"open_p0": 0, "open_p1": 0})
        url = f"{args.base_url.rstrip('/')}/orchestration/quality/week8-launch-gate?{query}"
    else:
        query = urllib.parse.urlencode({"lookback": args.lookback, "window": args.window})
        url = f"{args.base_url.rstrip('/')}/orchestration/quality/week2-gate?{query}"

    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"HTTP error while checking quality gate: {e.code}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Failed to fetch quality gate: {e}", file=sys.stderr)
        return 2

    print(json.dumps(payload, indent=2))

    if payload.get("ready") is True:
        return 0

    failures = payload.get("failures", [])
    print(f"Quality gate failed: {', '.join(failures) if failures else 'unknown'}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
