"""
Connector Smoke Tests

Quick validation that connectors import, instantiate, and expose
correct interfaces. No API credentials required.
Tests registry metadata, class instantiation, and safe disconnect.
"""

import asyncio
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


# All connector modules that should be importable
CONNECTOR_MODULES = [
    "connectors.gmail",
    "connectors.calendar",
    "connectors.google_sheets",
    "connectors.todoist",
    "connectors.spotify",
    "connectors.slack",
    "connectors.github",
    "connectors.discord",
    "connectors.drive",
    "connectors.contacts",
    "connectors.outlook",
    "connectors.outlook_calendar",
    "connectors.onedrive",
    "connectors.microsoft_todo",
    "connectors.dropbox",
    "connectors.jira",
    "connectors.notion",
    "connectors.linear",
    "connectors.trello",
    "connectors.hubspot",
    "connectors.stripe",
    "connectors.twilio_sms",
    "connectors.telegram",
    "connectors.reddit",
    "connectors.twitter",
    "connectors.youtube",
    "connectors.weather",
    "connectors.news",
    "connectors.web_search",
    "connectors.zoom",
    "connectors.airtable",
    "connectors.linkedin",
]

# Top connectors that must be in registry
TOP_CONNECTORS = ["gmail", "google_calendar", "google_sheets", "todoist", "spotify"]


def test_import_all():
    """Every connector module should import without errors."""
    failures = []
    for mod_name in CONNECTOR_MODULES:
        try:
            importlib.import_module(mod_name)
        except Exception as e:
            failures.append((mod_name, str(e)))
    if failures:
        for mod, err in failures:
            print(f"  FAIL import {mod}: {err}")
    assert not failures, f"{len(failures)} connector(s) failed to import"
    print(f"  OK: {len(CONNECTOR_MODULES)} modules imported")


def test_registry_metadata():
    """Registry should have complete metadata for all connectors."""
    from connectors.registry import ConnectorRegistry
    registry = ConnectorRegistry()
    all_meta = registry.list_connectors()
    names = [m.name for m in all_meta]

    # Top 5 must be present
    missing = [n for n in TOP_CONNECTORS if n not in names]
    if missing:
        print(f"  FAIL Missing from registry: {missing}")
    assert not missing, f"Top connectors missing: {missing}"

    # All metadata must have required fields
    incomplete = []
    for m in all_meta:
        for field in ["name", "display_name", "provider", "description"]:
            if not getattr(m, field, None):
                incomplete.append((m.name, field))
    if incomplete:
        for name, field in incomplete:
            print(f"  FAIL {name} missing '{field}'")
    assert not incomplete, f"{len(incomplete)} metadata issue(s)"
    print(f"  OK: {len(all_meta)} connectors with complete metadata")


def test_instantiation():
    """Each registered connector class should instantiate with no args."""
    from connectors.registry import ConnectorRegistry
    registry = ConnectorRegistry()

    failures = []
    for meta in registry.list_connectors():
        cls = meta.connector_class
        try:
            instance = cls()
            # Should not think it's connected
            if hasattr(instance, 'connected') and instance.connected:
                failures.append((meta.name, "claims connected with no credentials"))
        except Exception as e:
            failures.append((meta.name, str(e)))
    if failures:
        for name, err in failures:
            print(f"  FAIL {name}: {err}")
    assert not failures, f"{len(failures)} instantiation failure(s)"
    print(f"  OK: All connectors instantiate cleanly")


def test_connect_method():
    """Every connector must have a connect() method."""
    from connectors.registry import ConnectorRegistry
    registry = ConnectorRegistry()

    missing = []
    for meta in registry.list_connectors():
        cls = meta.connector_class
        if not hasattr(cls, 'connect') or not callable(getattr(cls, 'connect')):
            missing.append(meta.name)
    if missing:
        print(f"  FAIL Missing connect(): {missing}")
    assert not missing, f"{len(missing)} connector(s) missing connect()"
    print(f"  OK: All connectors have connect()")


async def test_disconnect_safe():
    """Disconnecting a never-connected connector should not raise."""
    from connectors.registry import ConnectorRegistry
    registry = ConnectorRegistry()

    failures = []
    for meta in registry.list_connectors():
        cls = meta.connector_class
        try:
            instance = cls()
            if hasattr(instance, 'disconnect'):
                await instance.disconnect()
        except Exception as e:
            failures.append((meta.name, str(e)))
    if failures:
        for name, err in failures:
            print(f"  FAIL {name}.disconnect(): {err}")
    assert not failures, f"{len(failures)} disconnect failure(s)"
    print(f"  OK: All connectors disconnect safely")


def test_primitives_declared():
    """Every connector should declare at least one primitive type."""
    from connectors.registry import ConnectorRegistry
    registry = ConnectorRegistry()

    empty = []
    for meta in registry.list_connectors():
        if not meta.primitives:
            empty.append(meta.name)
    if empty:
        print(f"  FAIL No primitives: {empty}")
    assert not empty, f"{len(empty)} connector(s) with no primitives"
    print(f"  OK: All connectors declare primitives")


def test_no_duplicate_names():
    """Registry should not have duplicate connector names."""
    from connectors.registry import ConnectorRegistry
    registry = ConnectorRegistry()
    names = [m.name for m in registry.list_connectors()]
    dupes = [n for n in names if names.count(n) > 1]
    if dupes:
        print(f"  FAIL Duplicates: {set(dupes)}")
    assert not dupes, f"Duplicate names: {set(dupes)}"
    print(f"  OK: No duplicate connector names")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

async def main():
    tests = [
        ("Import all connectors", test_import_all),
        ("Registry metadata", test_registry_metadata),
        ("Instantiation", test_instantiation),
        ("Connect method", test_connect_method),
        ("Disconnect safety", test_disconnect_safe),
        ("Primitives declared", test_primitives_declared),
        ("No duplicate names", test_no_duplicate_names),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            if asyncio.iscoroutinefunction(fn):
                await fn()
            else:
                fn()
            passed += 1
            print(f"✓ {name}")
        except AssertionError as e:
            failed += 1
            print(f"✗ {name}: {e}")
        except Exception as e:
            failed += 1
            print(f"✗ {name}: UNEXPECTED {e}")

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)}")
    return failed == 0


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
