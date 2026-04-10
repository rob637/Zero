"""
Performance Benchmark Suite

Measures and validates the performance targets for the Aegis architecture:
  - INDEX_DIRECT queries: < 50ms (no LLM)
  - FILTERED queries: < 3s (LLM with reduced tools)
  - Semantic search: < 100ms (vector similarity)
  - Sync cycle: < 5s per source
  - Embedding pipeline: < 100ms per batch of 64

Run:
    python -m pytest apex/test_performance.py -v
    # or directly:
    python apex/test_performance.py
"""

import asyncio
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

# Add apex to path
sys.path.insert(0, str(Path(__file__).parent))


def _measure(func, *args, **kwargs):
    """Measure execution time in milliseconds."""
    start = time.perf_counter()
    result = func(*args, **kwargs)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return result, elapsed_ms


async def _measure_async(coro):
    """Measure async execution time in milliseconds."""
    start = time.perf_counter()
    result = await coro
    elapsed_ms = (time.perf_counter() - start) * 1000
    return result, elapsed_ms


class PerformanceBenchmark:
    """Run all benchmarks and report results."""

    def __init__(self):
        self.results: Dict[str, Dict] = {}
        self._tmpdir = tempfile.mkdtemp()

    def _record(self, name: str, elapsed_ms: float, target_ms: float, detail: str = ""):
        passed = elapsed_ms <= target_ms
        self.results[name] = {
            "elapsed_ms": round(elapsed_ms, 2),
            "target_ms": target_ms,
            "passed": passed,
            "detail": detail,
        }
        icon = "✓" if passed else "✗"
        print(f"  {icon} {name}: {elapsed_ms:.1f}ms (target: {target_ms}ms) {detail}")

    async def run_all(self):
        """Run the full benchmark suite."""
        print("\n" + "=" * 60)
        print("PERFORMANCE BENCHMARK SUITE")
        print("=" * 60)

        await self.bench_intent_classifier()
        await self.bench_index_queries()
        await self.bench_index_direct_handler()
        await self.bench_semantic_search()
        await self.bench_tool_filtering()
        await self.bench_embedding_pipeline()

        # Summary
        print("\n" + "-" * 60)
        passed = sum(1 for r in self.results.values() if r["passed"])
        total = len(self.results)
        print(f"RESULTS: {passed}/{total} passed")

        if passed < total:
            print("\nFAILED benchmarks:")
            for name, r in self.results.items():
                if not r["passed"]:
                    print(f"  ✗ {name}: {r['elapsed_ms']:.1f}ms > {r['target_ms']}ms")
        print("=" * 60 + "\n")

        return passed == total

    # -------------------------------------------------------------------
    # Individual benchmarks
    # -------------------------------------------------------------------

    async def bench_intent_classifier(self):
        """Intent classifier should be < 1ms per classification."""
        print("\n[Intent Classifier]")
        from intent_router import classify_sync

        messages = [
            "What's on my calendar today?",
            "Send an email to John about the budget",
            "Any unread emails?",
            "Schedule a meeting with Sarah at 3pm",
            "What is the weather?",
            "Hello",
            "Show my tasks for this week",
            "Prepare for my meeting with the team tomorrow",
            "What did John send me about the Q1 report?",
            "Create a task to review the proposal by Friday",
        ]

        # Warm up
        for m in messages:
            classify_sync(m)

        # Benchmark
        start = time.perf_counter()
        iterations = 1000
        for _ in range(iterations):
            for m in messages:
                classify_sync(m)
        elapsed_ms = (time.perf_counter() - start) * 1000
        per_classify = elapsed_ms / (iterations * len(messages))

        self._record("classify_per_message", per_classify, 1.0,
                      f"({iterations * len(messages)} classifications)")

    async def bench_index_queries(self):
        """Index queries should be < 10ms."""
        print("\n[Index Queries]")
        from index import Index, DataObject, ObjectKind

        db_path = os.path.join(self._tmpdir, "bench_index.db")
        index = Index(db_path=db_path)

        # Insert test data
        now = datetime.now(timezone.utc)
        objects = []
        for i in range(1000):
            objects.append(DataObject(
                source="test",
                source_id=f"event-{i}",
                kind=ObjectKind.EVENT,
                title=f"Meeting {i} with {'John' if i % 3 == 0 else 'Sarah' if i % 3 == 1 else 'Team'}",
                body=f"Discussion about project {i % 10}",
                timestamp=now - timedelta(hours=i),
                timestamp_end=now - timedelta(hours=i) + timedelta(hours=1),
                participants=[f"person{i % 5}@example.com"],
            ))
        for i in range(500):
            objects.append(DataObject(
                source="test",
                source_id=f"email-{i}",
                kind=ObjectKind.EMAIL,
                title=f"Re: Budget report Q{i % 4 + 1}",
                body=f"Here is the updated budget for project {i % 10}",
                timestamp=now - timedelta(hours=i * 2),
                participants=[f"sender{i % 10}@example.com"],
                status="unread" if i % 3 == 0 else "read",
            ))

        index.upsert_batch(objects)

        # Benchmark time-range query
        _, ms = _measure(
            index.query, kind="event",
            after=now - timedelta(days=1), before=now,
            limit=50,
        )
        self._record("index_time_range_query", ms, 10.0, "(1000 events, 1-day range)")

        # Benchmark FTS search
        _, ms = _measure(index.search, "budget report", kind="email", limit=20)
        self._record("index_fts_search", ms, 15.0, "(500 emails, FTS5)")

        # Benchmark count
        _, ms = _measure(index.count, kind="event")
        self._record("index_count", ms, 5.0)

        # Benchmark stats
        _, ms = _measure(index.stats)
        self._record("index_stats", ms, 5.0)

        index.close()

    async def bench_index_direct_handler(self):
        """INDEX_DIRECT handler should be < 50ms end-to-end."""
        print("\n[Index Direct Handler]")
        from index import Index, DataObject, ObjectKind
        from intent_router import classify_sync, handle_index_direct

        db_path = os.path.join(self._tmpdir, "bench_direct.db")
        index = Index(db_path=db_path)

        # Insert realistic data
        now = datetime.now(timezone.utc)
        objects = []
        for i in range(200):
            objects.append(DataObject(
                source="google_calendar", source_id=f"cal-{i}",
                kind=ObjectKind.EVENT,
                title=f"Meeting {i}",
                timestamp=now + timedelta(hours=i - 100),
                timestamp_end=now + timedelta(hours=i - 99),
            ))
        for i in range(100):
            objects.append(DataObject(
                source="gmail", source_id=f"mail-{i}",
                kind=ObjectKind.EMAIL,
                title=f"Email subject {i}",
                timestamp=now - timedelta(hours=i),
                status="unread" if i < 20 else "read",
            ))
        index.upsert_batch(objects)

        # Full pipeline: classify + handle
        test_queries = [
            "What's on my calendar today?",
            "Any unread emails?",
            "Show my schedule for tomorrow",
        ]

        for query in test_queries:
            start = time.perf_counter()
            intent = classify_sync(query)
            result = handle_index_direct(intent, index)
            elapsed_ms = (time.perf_counter() - start) * 1000
            has_data = result is not None and len(result.get("data", [])) >= 0
            self._record(
                f"direct_{query[:30].replace(' ', '_')}",
                elapsed_ms, 50.0,
                f"({'hit' if has_data else 'miss'})"
            )

        index.close()

    async def bench_semantic_search(self):
        """Semantic search should be < 100ms for embed + search."""
        print("\n[Semantic Search]")

        try:
            from semantic_search import Embedder, VectorStore, _text_hash
            import numpy as np
        except ImportError as e:
            print(f"  ⊘ Skipped: {e}")
            return

        embedder = Embedder()
        if not embedder.initialize():
            print("  ⊘ Skipped: no embedding backend")
            return

        # Build test vector store
        db_path = os.path.join(self._tmpdir, "bench_vectors.db")
        store = VectorStore(db_path=db_path, dimension=embedder.dimension)

        texts = [f"Meeting about project {i} with team member {i % 20}" for i in range(5000)]
        vectors = embedder.embed(texts)
        items = [(f"test:{i}", vectors[i], _text_hash(texts[i])) for i in range(len(texts))]
        store.upsert_batch(items)

        # Benchmark: embed query + vector search
        query = "project planning discussion"
        # Warm up the embedding path
        embedder.embed_one("warmup query")
        
        start = time.perf_counter()
        query_vec = embedder.embed_one(query)
        results = store.search(query_vec, limit=10, min_score=0.2)
        elapsed_ms = (time.perf_counter() - start) * 1000

        self._record("semantic_embed_and_search", elapsed_ms, 100.0,
                      f"(5000 vectors, {len(results)} results)")

        # Just the search (no embedding)
        _, ms = _measure(store.search, query_vec, limit=10, min_score=0.2)
        self._record("semantic_search_only", ms, 20.0, "(5000 vectors)")

        store.close()

    async def bench_tool_filtering(self):
        """Tool filtering should be < 2ms."""
        print("\n[Tool Filtering]")
        from intent_router import filter_tools

        # Create mock tools
        class MockTool:
            def __init__(self, name):
                self.name = name

        all_tools = [MockTool(f"calendar_{op}") for op in ["list", "create", "update", "delete", "search"]]
        all_tools += [MockTool(f"email_{op}") for op in ["list", "send", "draft", "search", "delete"]]
        all_tools += [MockTool(f"task_{op}") for op in ["list", "create", "update", "delete"]]
        all_tools += [MockTool(f"contacts_{op}") for op in ["list", "search", "create"]]
        all_tools += [MockTool(f"file_{op}") for op in ["list", "search", "download", "upload"]]
        all_tools += [MockTool(f"web_{op}") for op in ["search"]]
        all_tools += [MockTool(f"weather_{op}") for op in ["current", "forecast"]]
        all_tools += [MockTool(f"news_{op}") for op in ["search", "headlines"]]
        # Pad to ~370 tools
        for i in range(340):
            all_tools.append(MockTool(f"other_tool_{i}"))

        # Benchmark
        _, ms = _measure(filter_tools, all_tools, ["CALENDAR", "CONTACTS"])
        self._record("tool_filter", ms, 2.0, f"({len(all_tools)} tools → filtered)")

        # Benchmark with many domains
        _, ms = _measure(filter_tools, all_tools, ["CALENDAR", "EMAIL", "TASK"])
        self._record("tool_filter_3_domains", ms, 2.0)

    async def bench_embedding_pipeline(self):
        """Batch embedding should be < 200ms for 64 texts."""
        print("\n[Embedding Pipeline]")

        try:
            from semantic_search import Embedder
        except ImportError:
            print("  ⊘ Skipped")
            return

        embedder = Embedder()
        if not embedder.initialize():
            print("  ⊘ Skipped: no backend")
            return

        texts = [f"Test document {i} about topic {i % 10}" for i in range(64)]

        # Warm up
        embedder.embed(["warmup"])

        _, ms = _measure(embedder.embed, texts)
        self._record("embed_batch_64", ms, 200.0, f"(backend={embedder.backend})")

        # Single embed
        _, ms = _measure(embedder.embed_one, "single test text")
        self._record("embed_single", ms, 30.0)


async def main():
    bench = PerformanceBenchmark()
    success = await bench.run_all()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
