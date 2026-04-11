from orchestration import (
    BenchmarkCase,
    QualityGateThresholds,
    default_benchmark_cases,
    run_benchmarks,
)


def test_benchmark_runner_aggregates_results():
    cases = [
        BenchmarkCase(
            name="good_case",
            llm_calls=5,
            tool_calls=10,
            wall_time_ms=9000,
            verification={"satisfied": True, "score": 0.9},
        ),
        BenchmarkCase(
            name="bad_case",
            llm_calls=22,
            tool_calls=120,
            wall_time_ms=45000,
            verification={"satisfied": False, "score": 0.3},
        ),
    ]

    out = run_benchmarks(cases, thresholds=QualityGateThresholds(min_score=0.7))

    assert out["total"] == 2
    assert out["passed"] == 1
    assert 0.0 <= out["pass_rate"] <= 1.0
    assert out["avg_score"] > 0.0


def test_default_benchmark_suite_exists():
    cases = default_benchmark_cases()
    assert len(cases) >= 3
    assert all(c.name for c in cases)
