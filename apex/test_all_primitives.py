"""
Comprehensive test suite for all 36 primitives and 194 operations.
Tests each operation in local/fallback mode to verify:
1. Operation exists and is callable
2. Accepts expected parameters
3. Returns StepResult without crashing
4. StepResult has proper structure (success bool, data or error)
"""

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Tuple

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from apex.apex_engine import Apex, StepResult


# Test parameters for each primitive's operations
# These are minimal valid params that should work in local/fallback mode
TEST_PARAMS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "AUTOMATION": {
        "create": {"name": "test_rule", "trigger": {"type": "schedule", "cron": "0 9 * * *"}, "action": {"primitive": "NOTIFY", "operation": "alert", "params": {"message": "Test"}}},
        "list": {},
        "enable": {"rule_id": "test_rule"},
        "disable": {"rule_id": "test_rule"},
        "delete": {"rule_id": "test_rule"},
        "run": {"rule_id": "test_rule"},
    },
    "BROWSER": {
        "open": {"url": "https://example.com"},
        "click": {"selector": "#button"},
        "type": {"selector": "#input", "text": "test"},
        "screenshot": {"path": "/tmp/screenshot.png"},
        "read": {"url": "https://example.com"},
        "fill_form": {"url": "https://example.com", "fields": {"name": "test"}},
        "execute_js": {"script": "return 1+1"},
    },
    "CALENDAR": {
        "create": {"title": "Test Event", "start": (datetime.now() + timedelta(days=1)).isoformat(), "end": (datetime.now() + timedelta(days=1, hours=1)).isoformat()},
        "list": {"limit": 5},
        "search": {"query": "test"},
        "delete": {"event_id": "test_event"},
        "availability": {"start": datetime.now().isoformat(), "end": (datetime.now() + timedelta(days=7)).isoformat()},
    },
    "CHAT": {
        "send": {"channel": "general", "message": "Hello"},
        "read": {"channel": "general", "limit": 10},
        "search": {"query": "test"},
        "react": {"message_id": "msg123", "emoji": "👍"},
        "reply": {"message_id": "msg123", "text": "Reply"},
        "channels": {},
        "create_channel": {"name": "test-channel", "members": []},
    },
    "CLIPBOARD": {
        "copy": {"content": "test content"},
        "paste": {},
        "history": {"limit": 5},
        "clear": {},
    },
    "CLOUD_STORAGE": {
        "list": {"limit": 10},
        "search": {"query": "test"},
        "download": {"file_id": "test_file", "local_path": "/tmp/test.txt"},
        "upload": {"local_path": "/tmp/test.txt", "remote_path": "/test.txt"},
        "create_folder": {"name": "test_folder"},
        "delete": {"file_id": "test_file"},
        "share": {"file_id": "test_file", "email": "test@example.com"},
    },
    "COMPUTE": {
        "formula": {"name": "sum", "inputs": [1, 2, 3]},
        "calculate": {"expression": "2 + 2"},
        "aggregate": {"data": [1, 2, 3, 4, 5], "function": "sum"},
    },
    "CONTACTS": {
        "search": {"query": "John"},
        "add": {"name": "John Doe", "email": "john@example.com"},
        "list": {"limit": 10},
    },
    "DATA": {
        "query": {"source": "test", "query": "SELECT * FROM test"},
        "transform": {"data": [{"a": 1}, {"a": 2}], "operations": [{"type": "filter", "field": "a", "value": 1}]},
        "load": {"source": "/tmp/test.json"},
        "store": {"data": {"key": "value"}, "destination": "/tmp/output.json"},
        "merge": {"sources": [{"a": 1}, {"b": 2}]},
    },
    "DATABASE": {
        "query": {"sql": "SELECT 1"},
        "execute": {"sql": "CREATE TABLE IF NOT EXISTS test (id INTEGER)"},
        "tables": {},
        "schema": {"table": "test"},
        "connect": {"connection_string": "sqlite:///test.db"},
    },
    "DEVTOOLS": {
        "list_issues": {"repo": "test/repo"},
        "get_issue": {"repo": "test/repo", "issue_number": 1},
        "create_issue": {"repo": "test/repo", "title": "Test Issue", "body": "Test body"},
        "update_issue": {"repo": "test/repo", "issue_number": 1, "state": "closed"},
        "comment": {"repo": "test/repo", "issue_number": 1, "body": "Comment"},
        "list_prs": {"repo": "test/repo"},
        "create_pr": {"repo": "test/repo", "title": "Test PR", "head": "feature", "base": "main"},
        "list_repos": {},
    },
    "DOCUMENT": {
        "parse": {"path": "/tmp/test.txt", "content": "Hello world"},
        "extract": {"content": "John Doe, john@example.com, 555-1234", "schema": {"name": "string", "email": "string", "phone": "string"}},
        "create": {"format": "txt", "content": "Test content", "path": "/tmp/output.txt"},
        "summarize": {"content": "This is a long document that needs to be summarized. It contains many important points."},
    },
    "EMAIL": {
        "send": {"to": "test@example.com", "subject": "Test", "body": "Test body"},
        "draft": {"to": "test@example.com", "subject": "Draft", "body": "Draft body"},
        "search": {"query": "test"},
        "list": {"limit": 10},
    },
    "FILE": {
        "search": {"query": "*.txt", "path": "/tmp"},
        "read": {"path": "/tmp/test_file.txt"},
        "write": {"path": "/tmp/test_file.txt", "content": "test content"},
        "list": {"path": "/tmp"},
        "info": {"path": "/tmp"},
        "exists": {"path": "/tmp"},
    },
    "FINANCE": {
        "balance": {"account": "checking"},
        "transactions": {"account": "checking", "limit": 10},
        "categorize": {"transaction_id": "tx123", "category": "groceries"},
        "spending": {"period": "month"},
        "budget": {"category": "food", "amount": 500, "period": "month"},
        "send": {"to": "friend@example.com", "amount": 10.00, "note": "Lunch"},
        "request": {"from": "friend@example.com", "amount": 10.00, "note": "Lunch"},
    },
    "HOME": {
        "devices": {},
        "state": {"device_id": "light_1"},
        "set": {"device_id": "light_1", "state": {"brightness": 50}},
        "on": {"device_id": "light_1"},
        "off": {"device_id": "light_1"},
        "temperature": {"device_id": "thermostat_1", "temperature": 72},
        "routine": {"routine_name": "goodnight"},
    },
    "KNOWLEDGE": {
        "remember": {"content": "Test fact to remember", "tags": ["test"]},
        "recall": {"query": "test"},
        "forget": {"memory_id": "test_memory"},
    },
    "MEDIA": {
        "info": {"path": "/tmp/test.mp3"},
        "convert": {"path": "/tmp/test.mp3", "format": "wav"},
        "resize": {"path": "/tmp/test.jpg", "width": 100, "height": 100},
        "generate": {"prompt": "A beautiful sunset"},
        "transcribe": {"path": "/tmp/audio.mp3"},
        "play": {"query": "test song"},
        "search": {"query": "test"},
    },
    "MEETING": {
        "schedule": {"title": "Test Meeting", "start": (datetime.now() + timedelta(days=1)).isoformat(), "duration": 30, "attendees": ["test@example.com"]},
        "join": {"meeting_id": "meet_123"},
        "cancel": {"meeting_id": "meet_123"},
        "list": {"limit": 5},
        "recording": {"meeting_id": "meet_123"},
        "transcript": {"meeting_id": "meet_123"},
    },
    "MESSAGE": {
        "send": {"channel": "general", "message": "Hello", "provider": "slack"},
        "list": {"channel": "general", "limit": 10},
        "search": {"query": "test"},
        "react": {"message_id": "msg123", "emoji": "thumbsup"},
        "reply": {"message_id": "msg123", "text": "Reply"},
        "channels": {},
    },
    "NOTES": {
        "create": {"title": "Test Note", "content": "Note content", "tags": ["test"]},
        "read": {"note_id": "note_123"},
        "update": {"note_id": "note_123", "content": "Updated content"},
        "delete": {"note_id": "note_123"},
        "search": {"query": "test"},
        "list": {},
    },
    "NOTIFY": {
        "alert": {"message": "Test alert", "title": "Test"},
        "remind": {"message": "Test reminder", "when": (datetime.now() + timedelta(hours=1)).isoformat()},
        "list": {},
        "cancel": {"reminder_id": "rem_123"},
    },
    "PHOTO": {
        "list": {"limit": 10},
        "upload": {"path": "/tmp/test.jpg"},
        "download": {"photo_id": "photo_123", "path": "/tmp/downloaded.jpg"},
        "search": {"query": "sunset"},
        "create_album": {"name": "Test Album"},
        "add_to_album": {"photo_id": "photo_123", "album_id": "album_123"},
        "metadata": {"photo_id": "/tmp/test.jpg"},
        "edit": {"photo_id": "photo_123", "operations": [{"type": "rotate", "degrees": 90}]},
    },
    "PRESENTATION": {
        "create": {"name": "Test Presentation"},
        "add_slide": {"file": "pres_123", "layout": "title", "content": {"title": "Slide 1"}},
        "update_slide": {"file": "pres_123", "slide_id": "slide_1", "content": {"title": "Updated"}},
        "export": {"file": "pres_123", "format": "pdf"},
        "get_text": {"file": "/tmp/test.pptx"},
    },
    "RIDE": {
        "estimate": {"pickup": "123 Main St", "dropoff": "456 Oak Ave"},
        "request": {"pickup": "123 Main St", "dropoff": "456 Oak Ave", "type": "standard"},
        "cancel": {"ride_id": "ride_123"},
        "track": {"ride_id": "ride_123"},
        "history": {"limit": 5},
    },
    "SCREENSHOT": {
        "capture": {"path": "/tmp/screenshot.png"},
        "window": {"window_name": "Terminal", "path": "/tmp/window.png"},
        "list": {},
    },
    "SEARCH": {
        "all": {"query": "test", "limit": 10},
        "files": {"query": "test", "path": "/tmp"},
        "email": {"query": "test"},
        "calendar": {"query": "meeting"},
        "tasks": {"query": "todo"},
        "knowledge": {"query": "remembered"},
        "messages": {"query": "hello"},
    },
    "SHELL": {
        "run": {"command": "echo hello"},
        "script": {"script": "echo hello\necho world"},
    },
    "SHOPPING": {
        "search": {"query": "laptop"},
        "product": {"product_id": "prod_123"},
        "add_to_cart": {"product_id": "prod_123", "quantity": 1},
        "cart": {},
        "track": {"order_id": "order_123"},
        "orders": {"limit": 5},
        "reorder": {"order_id": "order_123"},
        "price_alert": {"product_id": "prod_123", "target_price": 99.99},
    },
    "SMS": {
        "send": {"to": "+15551234567", "message": "Test message"},
        "read": {"limit": 10},
        "search": {"query": "test"},
    },
    "SOCIAL": {
        "post": {"content": "Test post"},
        "feed": {"limit": 10},
        "search": {"query": "test"},
        "like": {"post_id": "post_123"},
        "comment": {"post_id": "post_123", "text": "Nice!"},
        "share": {"post_id": "post_123"},
        "profile": {},
        "notifications": {},
    },
    "SPREADSHEET": {
        "read": {"file": "/tmp/test.csv", "sheet": "Sheet1", "range": "A1:D10"},
        "write": {"file": "/tmp/test.csv", "data": [["a", "b"], [1, 2]], "sheet": "Sheet1"},
        "create": {"name": "Test Spreadsheet", "data": [["Header1", "Header2"], [1, 2]]},
        "add_sheet": {"file": "sheet_123", "name": "New Sheet"},
        "formula": {"file": "sheet_123", "cell": "A1", "formula": "=SUM(B1:B10)"},
        "format": {"file": "sheet_123", "range": "A1:D10", "format": {"bold": True}},
        "chart": {"file": "sheet_123", "data_range": "A1:B10", "chart_type": "bar"},
    },
    "TASK": {
        "create": {"title": "Test Task", "description": "Task description"},
        "list": {"limit": 10},
        "update": {"task_id": "task_123", "title": "Updated Task"},
        "complete": {"task_id": "task_123"},
        "delete": {"task_id": "task_123"},
        "search": {"query": "test"},
    },
    "TRANSLATE": {
        "translate": {"text": "Hello world", "target": "es"},
        "detect": {"text": "Bonjour le monde"},
        "languages": {},
    },
    "TRAVEL": {
        "search_flights": {"origin": "JFK", "destination": "LAX", "date": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")},
        "search_hotels": {"location": "New York", "checkin": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"), "checkout": (datetime.now() + timedelta(days=32)).strftime("%Y-%m-%d"), "guests": 2},
        "book": {"type": "flight", "id": "flight_123"},
        "cancel": {"booking_id": "booking_123"},
        "itinerary": {},
        "checkin": {"booking_id": "booking_123"},
    },
    "WEB": {
        "fetch": {"url": "https://example.com"},
        "api": {"url": "https://api.example.com/data", "method": "GET"},
        "extract": {"url": "https://example.com", "selector": "h1"},
    },
}


async def _check_operation(primitive_name: str, operation: str, params: Dict[str, Any], engine: Apex) -> Tuple[bool, str]:
    """Test a single operation and return (success, message). Named with _ to avoid pytest pickup."""
    try:
        prim = engine._primitives.get(primitive_name)
        if not prim:
            return False, f"Primitive not found: {primitive_name}"
        
        # Verify operation exists
        available_ops = prim.get_available_operations()
        if operation not in available_ops:
            return False, f"Operation not available: {operation}"
        
        # Execute operation
        result = await prim.execute(operation, params)
        
        # Verify result structure
        if not isinstance(result, StepResult):
            return False, f"Invalid return type: {type(result)}"
        
        if not hasattr(result, 'success'):
            return False, "StepResult missing 'success' attribute"
        
        # Success can be True or False - we just want no crash
        if result.success:
            return True, "OK"
        else:
            # Failed but didn't crash - still a valid test
            error = getattr(result, 'error', 'Unknown error')
            # Some failures are expected (e.g., file not found, no provider)
            if any(x in str(error).lower() for x in ['not found', 'not available', 'no provider', 'not installed', 'not configured', 'not supported', 'fallback']):
                return True, f"OK (expected: {error[:50]})"
            return True, f"OK (failed: {error[:50]})"
            
    except Exception as e:
        return False, f"EXCEPTION: {type(e).__name__}: {str(e)[:100]}"


async def run_all_tests():
    """Run tests for all primitives and operations."""
    print("=" * 70)
    print("COMPREHENSIVE PRIMITIVE TEST SUITE")
    print(f"Testing {len(TEST_PARAMS)} primitives")
    print("=" * 70)
    print()
    
    # Initialize engine
    print("Initializing Apex engine...")
    engine = Apex()
    print(f"Loaded {len(engine._primitives)} primitives")
    print()
    
    # Track results
    total_tests = 0
    passed = 0
    failed = 0
    failures: List[Tuple[str, str, str]] = []
    
    # Create test file for FILE primitive
    test_file = Path("/tmp/test_file.txt")
    test_file.write_text("test content for file operations")
    
    # Test each primitive
    for prim_name in sorted(TEST_PARAMS.keys()):
        ops = TEST_PARAMS[prim_name]
        print(f"\n{prim_name} ({len(ops)} operations):")
        print("-" * 40)
        
        for op_name, params in ops.items():
            total_tests += 1
            success, message = await _check_operation(prim_name, op_name, params, engine)
            
            if success:
                passed += 1
                print(f"  ✅ {op_name}: {message}")
            else:
                failed += 1
                failures.append((prim_name, op_name, message))
                print(f"  ❌ {op_name}: {message}")
    
    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"Total tests: {total_tests}")
    print(f"Passed: {passed} ({100*passed/total_tests:.1f}%)")
    print(f"Failed: {failed} ({100*failed/total_tests:.1f}%)")
    
    if failures:
        print(f"\nFAILURES ({len(failures)}):")
        print("-" * 40)
        for prim, op, msg in failures:
            print(f"  {prim}.{op}: {msg}")
    
    print("\n" + "=" * 70)
    
    # Cleanup
    if test_file.exists():
        test_file.unlink()
    
    return passed, failed


if __name__ == "__main__":
    passed, failed = asyncio.run(run_all_tests())
    sys.exit(0 if failed == 0 else 1)
