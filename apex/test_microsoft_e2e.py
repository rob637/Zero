"""
End-to-End Tests for Microsoft Services Integration

Tests the complete Microsoft 365 integration:
- Outlook Mail
- Outlook Calendar
- OneDrive
- Microsoft To-Do
- Unified service abstraction

Run with: python -m pytest test_microsoft_e2e.py -v

For interactive testing without pytest:
    python test_microsoft_e2e.py
"""

import asyncio
import os
from datetime import datetime, timedelta, date
from pathlib import Path
import tempfile
import sys

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))


# ============================================================================
# Unit Tests (No Authentication Required)
# ============================================================================

def test_outlook_email_dataclass():
    """Test OutlookEmail dataclass parsing."""
    from connectors.outlook import OutlookEmail
    
    email = OutlookEmail(
        id="test-123",
        conversation_id="conv-456",
        subject="Test Subject",
        sender={"name": "Alice", "email": "alice@example.com"},
        to_recipients=[{"name": "Bob", "email": "bob@example.com"}],
        cc_recipients=[],
        received_datetime=datetime(2024, 1, 15, 10, 30),
        sent_datetime=datetime(2024, 1, 15, 10, 29),
        body_preview="This is a test...",
    )
    
    assert email.id == "test-123"
    assert email.sender_email == "alice@example.com"
    assert email.sender_name == "Alice"
    
    d = email.to_dict()
    assert d["subject"] == "Test Subject"
    assert "alice@example.com" in d["sender"]
    print("✓ OutlookEmail dataclass works correctly")


def test_calendar_event_dataclass():
    """Test CalendarEvent dataclass parsing."""
    from connectors.outlook_calendar import CalendarEvent
    
    event = CalendarEvent(
        id="event-123",
        subject="Team Meeting",
        start=datetime(2024, 1, 15, 10, 0),
        end=datetime(2024, 1, 15, 11, 0),
        location="Conference Room A",
        attendees=[
            {"name": "Bob", "email": "bob@example.com", "type": "required", "response": "accepted"}
        ],
    )
    
    assert event.id == "event-123"
    assert event.subject == "Team Meeting"
    assert len(event.attendees) == 1
    
    d = event.to_dict()
    assert d["location"] == "Conference Room A"
    print("✓ CalendarEvent dataclass works correctly")


def test_drive_item_dataclass():
    """Test DriveItem dataclass parsing."""
    from connectors.onedrive import DriveItem
    
    item = DriveItem(
        id="item-123",
        name="report.pdf",
        path="/Documents/report.pdf",
        is_folder=False,
        size=1024 * 500,  # 500 KB
        created_datetime=datetime(2024, 1, 10),
        modified_datetime=datetime(2024, 1, 15),
        mime_type="application/pdf",
    )
    
    assert item.id == "item-123"
    assert item.is_folder == False
    assert item.size == 512000
    
    d = item.to_dict()
    assert d["type"] == "file"
    assert d["name"] == "report.pdf"
    print("✓ DriveItem dataclass works correctly")


def test_todo_task_dataclass():
    """Test TodoTask dataclass parsing."""
    from connectors.microsoft_todo import TodoTask
    
    task = TodoTask(
        id="task-123",
        title="Buy groceries",
        list_id="list-456",
        importance="high",
        due_date=date(2024, 1, 20),
        checklist_items=[
            {"id": "check-1", "text": "Milk", "is_checked": False},
            {"id": "check-2", "text": "Eggs", "is_checked": True},
        ],
    )
    
    assert task.id == "task-123"
    assert task.importance == "high"
    assert len(task.checklist_items) == 2
    
    d = task.to_dict()
    assert d["title"] == "Buy groceries"
    assert d["due_date"] == "2024-01-20"
    print("✓ TodoTask dataclass works correctly")


def test_recurrence_helpers():
    """Test recurrence pattern helper functions."""
    from connectors.outlook_calendar import daily_recurrence, weekly_recurrence, monthly_recurrence
    from connectors.microsoft_todo import daily_recurrence as todo_daily
    
    # Calendar recurrence
    daily = daily_recurrence(interval=1, count=10)
    assert daily["pattern"]["type"] == "daily"
    assert daily["range"]["numberOfOccurrences"] == 10
    
    weekly = weekly_recurrence(days=["monday", "wednesday"], interval=1)
    assert weekly["pattern"]["type"] == "weekly"
    assert "monday" in weekly["pattern"]["daysOfWeek"]
    
    monthly = monthly_recurrence(day_of_month=15)
    assert monthly["pattern"]["dayOfMonth"] == 15
    
    # To-Do recurrence
    todo = todo_daily(interval=2)
    assert todo["pattern"]["interval"] == 2
    
    print("✓ Recurrence helpers work correctly")


def test_unified_service_imports():
    """Test unified service abstraction imports."""
    from connectors.unified import (
        UnifiedServices,
        Provider,
        EmailService,
        CalendarService,
        FileService,
        TaskService,
        GoogleEmailService,
        MicrosoftEmailService,
    )
    
    # Test Provider enum
    assert Provider.GOOGLE.value == "google"
    assert Provider.MICROSOFT.value == "microsoft"
    
    print("✓ Unified service imports work correctly")


def test_graph_error_classes():
    """Test Graph API error handling classes."""
    from connectors.microsoft_graph import GraphError, GraphAPIError
    
    error = GraphError(
        code="ResourceNotFound",
        message="The requested resource was not found",
        status_code=404,
    )
    
    assert error.code == "ResourceNotFound"
    assert "404" in str(error)
    
    exc = GraphAPIError(error)
    assert "ResourceNotFound" in str(exc)
    
    print("✓ Graph error classes work correctly")


# ============================================================================
# Integration Tests (Require Authentication)
# ============================================================================

async def test_microsoft_auth_setup():
    """Test Microsoft authentication setup."""
    from connectors.microsoft_auth import MicrosoftAuth
    
    auth = MicrosoftAuth()
    
    # Check if credentials are configured
    has_creds = auth.has_credentials()
    
    if not has_creds:
        print(f"⚠ Microsoft credentials not configured.")
        print(f"  To test with real Microsoft account:")
        print(f"  1. Create Azure AD app at https://portal.azure.com")
        print(f"  2. Set environment variables:")
        print(f"     AZURE_CLIENT_ID=your-client-id")
        print(f"     AZURE_TENANT_ID=your-tenant-id")
        return False
    
    # Get setup instructions (should return empty since creds exist)
    instructions = auth.get_setup_instructions()
    print("✓ Microsoft auth credentials configured")
    return True


async def test_outlook_connection():
    """Test Outlook connection (requires auth)."""
    from connectors.outlook import OutlookConnector
    
    outlook = OutlookConnector()
    connected = await outlook.connect()
    
    if not connected:
        print("⚠ Could not connect to Outlook (auth required)")
        return False
    
    assert outlook.user_email is not None
    print(f"✓ Connected to Outlook as: {outlook.user_email}")
    return True


async def test_outlook_list_messages():
    """Test listing Outlook messages."""
    from connectors.outlook import OutlookConnector
    
    outlook = OutlookConnector()
    if not await outlook.connect():
        print("⚠ Skipping (auth required)")
        return
    
    messages = await outlook.list_messages(max_results=5)
    
    print(f"✓ Retrieved {len(messages)} messages from Outlook")
    for msg in messages[:3]:
        print(f"  - {msg.subject[:50]}... from {msg.sender_email}")


async def test_calendar_connection():
    """Test Outlook Calendar connection."""
    from connectors.outlook_calendar import OutlookCalendarConnector
    
    calendar = OutlookCalendarConnector()
    connected = await calendar.connect()
    
    if not connected:
        print("⚠ Could not connect to Outlook Calendar (auth required)")
        return False
    
    print(f"✓ Connected to Outlook Calendar (timezone: {calendar.timezone})")
    return True


async def test_calendar_list_events():
    """Test listing calendar events."""
    from connectors.outlook_calendar import OutlookCalendarConnector
    
    calendar = OutlookCalendarConnector()
    if not await calendar.connect():
        print("⚠ Skipping (auth required)")
        return
    
    events = await calendar.list_events(max_results=5)
    
    print(f"✓ Retrieved {len(events)} upcoming events")
    for event in events[:3]:
        print(f"  - {event.subject} at {event.start}")


async def test_onedrive_connection():
    """Test OneDrive connection."""
    from connectors.onedrive import OneDriveConnector
    
    drive = OneDriveConnector()
    connected = await drive.connect()
    
    if not connected:
        print("⚠ Could not connect to OneDrive (auth required)")
        return False
    
    # Get quota
    quota = await drive.get_quota()
    used_gb = quota.used / (1024**3)
    total_gb = quota.total / (1024**3)
    print(f"✓ Connected to OneDrive ({used_gb:.1f} GB / {total_gb:.1f} GB used)")
    return True


async def test_onedrive_list_files():
    """Test listing OneDrive files."""
    from connectors.onedrive import OneDriveConnector
    
    drive = OneDriveConnector()
    if not await drive.connect():
        print("⚠ Skipping (auth required)")
        return
    
    items = await drive.list_items("/", max_results=10)
    
    print(f"✓ Retrieved {len(items)} items from OneDrive root")
    for item in items[:5]:
        icon = "📁" if item.is_folder else "📄"
        print(f"  {icon} {item.name}")


async def test_todo_connection():
    """Test Microsoft To-Do connection."""
    from connectors.microsoft_todo import MicrosoftTodoConnector
    
    todo = MicrosoftTodoConnector()
    connected = await todo.connect()
    
    if not connected:
        print("⚠ Could not connect to Microsoft To-Do (auth required)")
        return False
    
    lists = await todo.get_lists()
    print(f"✓ Connected to Microsoft To-Do ({len(lists)} task lists)")
    return True


async def test_todo_list_tasks():
    """Test listing To-Do tasks."""
    from connectors.microsoft_todo import MicrosoftTodoConnector
    
    todo = MicrosoftTodoConnector()
    if not await todo.connect():
        print("⚠ Skipping (auth required)")
        return
    
    tasks = await todo.list_tasks(max_results=10)
    
    print(f"✓ Retrieved {len(tasks)} active tasks")
    for task in tasks[:5]:
        due = f" (due {task.due_date})" if task.due_date else ""
        print(f"  - {task.title}{due}")


# ============================================================================
# Workflow Tests
# ============================================================================

async def test_unified_services_workflow():
    """Test unified services with available providers."""
    from connectors.unified import UnifiedServices
    
    services = UnifiedServices()
    providers = await services.connect(google=False, microsoft=True)
    
    if not providers.any_connected:
        print("⚠ No providers connected (auth required)")
        return
    
    print(f"✓ Unified services connected:")
    print(f"  Microsoft: {providers.microsoft}")
    
    # Test email service
    if services.email:
        print(f"  Email provider: {services.email.provider.value}")
    
    # Test calendar service
    if services.calendar:
        print(f"  Calendar provider: {services.calendar.provider.value}")
    
    # Test file service
    if services.files:
        print(f"  File provider: {services.files.provider.value}")
    
    # Test task service
    if services.tasks:
        print(f"  Task provider: {services.tasks.provider.value}")


async def test_full_workflow():
    """
    Test a full workflow using Microsoft services.
    
    This mimics the loan calculation workflow from Phase 1,
    but using Microsoft services instead of Google.
    """
    from connectors.unified import UnifiedServices
    
    services = UnifiedServices()
    providers = await services.connect(google=False, microsoft=True)
    
    if not providers.microsoft:
        print("⚠ Microsoft not connected - skipping full workflow test")
        return True  # Return True so it doesn't count as failure
    
    print("\n🔄 Running full workflow test...")
    
    # Step 1: Create a task to track the workflow
    print("  Step 1: Creating task to track workflow...")
    if services.tasks:
        task = await services.tasks.create_task(
            title="[TEST] Process loan calculation",
            due_date=date.today(),
            notes="Auto-generated test task",
        )
        print(f"    Created task: {task['title']}")
    
    # Step 2: Create test document content
    print("  Step 2: Creating test document...")
    calculation = """
    Loan Calculation Results
    ========================
    Principal: $300,000
    Rate: 6.5%
    Term: 30 years
    Monthly Payment: $1,896.20
    Total Interest: $382,632
    """
    
    # Step 3: Upload to OneDrive
    print("  Step 3: Uploading to OneDrive...")
    if services.files:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(calculation)
            temp_path = f.name
        
        try:
            result = await services.files.upload(
                local_path=temp_path,
                remote_path="/apex-test-calculation.txt",
            )
            print(f"    Uploaded: {result['name']}")
        finally:
            os.unlink(temp_path)
    
    # Step 4: Create calendar event
    print("  Step 4: Creating calendar event...")
    if services.calendar:
        event = await services.calendar.create_event(
            title="[TEST] Review Loan Calculation",
            start=datetime.now() + timedelta(hours=1),
            end=datetime.now() + timedelta(hours=2),
            description="Review the loan calculation results",
        )
        print(f"    Created event: {event['subject']}")
        
        # Clean up - delete the test event
        await services.calendar.delete_event(event['id'])
        print("    Cleaned up test event")
    
    # Step 5: Complete the task
    print("  Step 5: Completing task...")
    if services.tasks and 'task' in dir():
        result = await services.tasks.complete_task(task['id'])
        print(f"    Completed: {result['title']}")
        
        # Clean up - delete the test task
        await services.tasks.delete_task(task['id'])
        print("    Cleaned up test task")
    
    # Step 6: Clean up OneDrive file
    print("  Step 6: Cleaning up...")
    if services.files:
        await services.files.delete("/apex-test-calculation.txt")
        print("    Cleaned up test file")
    
    print("\n✅ Full workflow test completed successfully!")


# ============================================================================
# Test Runner
# ============================================================================

def run_unit_tests():
    """Run unit tests (no auth required)."""
    print("\n" + "="*60)
    print("UNIT TESTS (No Authentication Required)")
    print("="*60 + "\n")
    
    tests = [
        test_outlook_email_dataclass,
        test_calendar_event_dataclass,
        test_drive_item_dataclass,
        test_todo_task_dataclass,
        test_recurrence_helpers,
        test_unified_service_imports,
        test_graph_error_classes,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"✗ {test.__name__}: {e}")
            failed += 1
    
    print(f"\nUnit Tests: {passed} passed, {failed} failed")
    return failed == 0


async def run_integration_tests():
    """Run integration tests (auth required)."""
    print("\n" + "="*60)
    print("INTEGRATION TESTS (Authentication Required)")
    print("="*60 + "\n")
    
    # Check if auth is configured
    if not await test_microsoft_auth_setup():
        print("\n⚠ Skipping integration tests (no credentials)")
        return True
    
    tests = [
        test_outlook_connection,
        test_outlook_list_messages,
        test_calendar_connection,
        test_calendar_list_events,
        test_onedrive_connection,
        test_onedrive_list_files,
        test_todo_connection,
        test_todo_list_tasks,
        test_unified_services_workflow,
    ]
    
    passed = 0
    failed = 0
    skipped = 0
    
    for test in tests:
        try:
            result = await test()
            if result is False:
                skipped += 1
            else:
                passed += 1
        except Exception as e:
            print(f"✗ {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print(f"\nIntegration Tests: {passed} passed, {failed} failed, {skipped} skipped")
    return failed == 0


async def run_workflow_tests():
    """Run workflow tests."""
    print("\n" + "="*60)
    print("WORKFLOW TESTS")
    print("="*60 + "\n")
    
    try:
        await test_full_workflow()
        return True
    except Exception as e:
        print(f"✗ Workflow test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("TELIC - Microsoft 365 Integration Tests")
    print("="*60)
    
    all_passed = True
    
    # Run unit tests
    all_passed = run_unit_tests() and all_passed
    
    # Run integration tests
    all_passed = await run_integration_tests() and all_passed
    
    # Run workflow tests
    all_passed = await run_workflow_tests() and all_passed
    
    print("\n" + "="*60)
    if all_passed:
        print("✅ ALL TESTS PASSED")
    else:
        print("❌ SOME TESTS FAILED")
    print("="*60 + "\n")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
