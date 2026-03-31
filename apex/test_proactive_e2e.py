"""
End-to-End Tests for Phase 4: Proactive Intelligence

Tests the proactive monitoring system:
- Continuous service monitoring
- Anomaly detection rules
- Alert generation
- Notification delivery

Run with: python -m pytest test_proactive_e2e.py -v
"""

import asyncio
import pytest
from datetime import datetime, timedelta
from typing import Dict, List, Any


# ============================================================================
# Mock Service Adapters
# ============================================================================

class MockEmailAdapter:
    """Mock email service for testing."""
    
    def __init__(self):
        self.messages: List[Dict] = []
        self.poll_count = 0
    
    async def get_recent(self) -> Dict:
        self.poll_count += 1
        return {"messages": self.messages}
    
    def add_message(self, msg: Dict):
        """Add a message (simulates receiving email)."""
        self.messages.append({
            "id": f"msg_{len(self.messages)}",
            "from": msg.get("from", "unknown@example.com"),
            "subject": msg.get("subject", "No Subject"),
            "is_important": msg.get("is_important", False),
            "is_starred": msg.get("is_starred", False),
            "received_at": datetime.now().isoformat(),
            **msg,
        })


class MockCalendarAdapter:
    """Mock calendar service for testing."""
    
    def __init__(self):
        self.events: List[Dict] = []
        self.poll_count = 0
    
    async def get_recent(self) -> Dict:
        self.poll_count += 1
        return {"events": self.events}
    
    def add_event(self, event: Dict):
        """Add an event."""
        self.events.append({
            "id": f"event_{len(self.events)}",
            "title": event.get("title", "Untitled"),
            "start": event.get("start", datetime.now().isoformat()),
            "end": event.get("end"),
            **event,
        })


class MockTaskAdapter:
    """Mock task service for testing."""
    
    def __init__(self):
        self.tasks: List[Dict] = []
        self.poll_count = 0
    
    async def get_recent(self) -> Dict:
        self.poll_count += 1
        return {"tasks": self.tasks}
    
    def add_task(self, task: Dict):
        """Add a task."""
        self.tasks.append({
            "id": f"task_{len(self.tasks)}",
            "title": task.get("title", "Untitled"),
            "due_date": task.get("due_date"),
            "completed": task.get("completed", False),
            **task,
        })


# ============================================================================
# Unit Tests for ProactiveMonitor
# ============================================================================

class TestProactiveMonitorBasics:
    """Test basic ProactiveMonitor functionality."""
    
    def test_import(self):
        """Test that the module imports correctly."""
        from intelligence.proactive_monitor import (
            ProactiveMonitor,
            ProactiveAlert,
            AlertType,
            AlertPriority,
            MonitorState,
        )
        assert ProactiveMonitor is not None
        print("✓ ProactiveMonitor imports correctly")
    
    def test_create_monitor(self):
        """Test creating a monitor instance."""
        from intelligence.proactive_monitor import create_proactive_monitor, MonitorState
        
        monitor = create_proactive_monitor(
            cycle_interval_ms=50,
            poll_interval_seconds=1,
        )
        
        assert monitor is not None
        assert monitor._state == MonitorState.STOPPED
        print("✓ Monitor created successfully")
    
    def test_connect_service(self):
        """Test connecting service adapters."""
        from intelligence.proactive_monitor import create_proactive_monitor
        
        monitor = create_proactive_monitor()
        email = MockEmailAdapter()
        calendar = MockCalendarAdapter()
        
        monitor.connect_service("email", email)
        monitor.connect_service("calendar", calendar)
        
        stats = monitor.get_stats()
        assert "email" in stats["connected_services"]
        assert "calendar" in stats["connected_services"]
        print("✓ Services connected successfully")
    
    def test_vip_contacts(self):
        """Test VIP contact management."""
        from intelligence.proactive_monitor import create_proactive_monitor
        
        monitor = create_proactive_monitor()
        
        monitor.add_vip_contact("boss@company.com")
        monitor.add_vip_contact("CEO@company.com")
        
        assert "boss@company.com" in monitor._vip_contacts
        assert "ceo@company.com" in monitor._vip_contacts  # Should be lowercased
        
        monitor.remove_vip_contact("boss@company.com")
        assert "boss@company.com" not in monitor._vip_contacts
        
        print("✓ VIP contacts managed correctly")


class TestAlertGeneration:
    """Test alert generation from rules."""
    
    @pytest.mark.asyncio
    async def test_important_email_alert(self):
        """Test that important emails trigger alerts."""
        from intelligence.proactive_monitor import (
            create_proactive_monitor,
            AlertType,
        )
        
        monitor = create_proactive_monitor(poll_interval_seconds=0)
        email = MockEmailAdapter()
        monitor.connect_service("email", email)
        
        # Track alerts
        alerts_received = []
        monitor.on_alert(lambda a: alerts_received.append(a))
        
        # First poll - empty
        await monitor._monitoring_cycle()
        
        # Add important email
        email.add_message({
            "from": "boss@company.com",
            "subject": "Urgent: Need your attention",
            "is_important": True,
        })
        
        # Second poll - should trigger alert
        await monitor._monitoring_cycle()
        
        assert len(alerts_received) >= 1
        assert any(a.type == AlertType.IMPORTANT_EMAIL for a in alerts_received)
        print("✓ Important email alert generated")
    
    @pytest.mark.asyncio
    async def test_vip_email_alert(self):
        """Test that emails from VIPs trigger alerts."""
        from intelligence.proactive_monitor import create_proactive_monitor
        
        monitor = create_proactive_monitor(poll_interval_seconds=0)
        email = MockEmailAdapter()
        monitor.connect_service("email", email)
        monitor.add_vip_contact("ceo@company.com")
        
        alerts_received = []
        monitor.on_alert(lambda a: alerts_received.append(a))
        
        # First poll
        await monitor._monitoring_cycle()
        
        # Add email from VIP (not marked important, but from VIP)
        email.add_message({
            "from": "ceo@company.com",
            "subject": "Quick question",
            "is_important": False,
        })
        
        # Second poll
        await monitor._monitoring_cycle()
        
        assert len(alerts_received) >= 1
        print("✓ VIP email alert generated")
    
    @pytest.mark.asyncio
    async def test_meeting_soon_alert(self):
        """Test alert for upcoming meeting."""
        from intelligence.proactive_monitor import (
            create_proactive_monitor,
            AlertType,
        )
        
        monitor = create_proactive_monitor(poll_interval_seconds=0)
        calendar = MockCalendarAdapter()
        monitor.connect_service("calendar", calendar)
        
        alerts_received = []
        monitor.on_alert(lambda a: alerts_received.append(a))
        
        # Add meeting starting in 10 minutes
        meeting_start = datetime.now() + timedelta(minutes=10)
        calendar.add_event({
            "title": "Team Standup",
            "start": meeting_start.isoformat(),
        })
        
        # Poll
        await monitor._monitoring_cycle()
        
        assert len(alerts_received) >= 1
        assert any(a.type == AlertType.MEETING_SOON for a in alerts_received)
        print("✓ Meeting soon alert generated")
    
    @pytest.mark.asyncio  
    async def test_task_overdue_alert(self):
        """Test alert for overdue tasks."""
        from intelligence.proactive_monitor import (
            create_proactive_monitor,
            AlertType,
        )
        
        monitor = create_proactive_monitor(poll_interval_seconds=0)
        tasks = MockTaskAdapter()
        monitor.connect_service("tasks", tasks)
        
        alerts_received = []
        monitor.on_alert(lambda a: alerts_received.append(a))
        
        # Add overdue task
        yesterday = datetime.now() - timedelta(days=1)
        tasks.add_task({
            "title": "Submit report",
            "due_date": yesterday.isoformat(),
            "completed": False,
        })
        
        # Poll
        await monitor._monitoring_cycle()
        
        assert len(alerts_received) >= 1
        assert any(a.type == AlertType.TASK_OVERDUE for a in alerts_received)
        print("✓ Task overdue alert generated")


class TestAlertManagement:
    """Test alert management (acknowledge, dismiss)."""
    
    @pytest.mark.asyncio
    async def test_acknowledge_alert(self):
        """Test acknowledging an alert."""
        from intelligence.proactive_monitor import create_proactive_monitor
        
        monitor = create_proactive_monitor(poll_interval_seconds=0)
        email = MockEmailAdapter()
        monitor.connect_service("email", email)
        
        alerts = []
        monitor.on_alert(lambda a: alerts.append(a))
        
        # Generate an alert
        await monitor._monitoring_cycle()
        email.add_message({"is_important": True, "subject": "Test"})
        await monitor._monitoring_cycle()
        
        assert len(alerts) >= 1
        alert_id = alerts[0].id
        
        # Acknowledge
        result = monitor.acknowledge_alert(alert_id)
        assert result is True
        
        # Check it's acknowledged
        pending = monitor.get_pending_alerts()
        assert len([a for a in pending if a.id == alert_id]) == 0
        
        print("✓ Alert acknowledged correctly")
    
    @pytest.mark.asyncio
    async def test_dismiss_alert(self):
        """Test dismissing an alert."""
        from intelligence.proactive_monitor import create_proactive_monitor
        
        monitor = create_proactive_monitor(poll_interval_seconds=0)
        email = MockEmailAdapter()
        monitor.connect_service("email", email)
        
        alerts = []
        monitor.on_alert(lambda a: alerts.append(a))
        
        # Generate an alert
        await monitor._monitoring_cycle()
        email.add_message({"is_important": True, "subject": "Test"})
        await monitor._monitoring_cycle()
        
        alert_id = alerts[0].id
        
        # Dismiss
        result = monitor.dismiss_alert(alert_id)
        assert result is True
        
        # Check it's in history
        assert len(monitor._alert_history) >= 1
        
        print("✓ Alert dismissed correctly")


class TestMonitoringLoop:
    """Test the monitoring loop."""
    
    @pytest.mark.asyncio
    async def test_start_stop(self):
        """Test starting and stopping the monitor."""
        from intelligence.proactive_monitor import (
            create_proactive_monitor,
            MonitorState,
        )
        
        monitor = create_proactive_monitor(cycle_interval_ms=10)
        
        assert monitor._state == MonitorState.STOPPED
        
        # Start
        await monitor.start()
        await asyncio.sleep(0.05)  # Let it run a bit
        
        assert monitor._state == MonitorState.RUNNING
        assert monitor._cycle_count > 0
        
        # Stop
        await monitor.stop()
        
        assert monitor._state == MonitorState.STOPPED
        
        print("✓ Monitor start/stop works correctly")
    
    @pytest.mark.asyncio
    async def test_cycle_time_target(self):
        """Test that cycle time stays under 100ms target."""
        from intelligence.proactive_monitor import create_proactive_monitor
        
        monitor = create_proactive_monitor(cycle_interval_ms=10)
        
        # Add some services
        email = MockEmailAdapter()
        calendar = MockCalendarAdapter()
        monitor.connect_service("email", email)
        monitor.connect_service("calendar", calendar)
        
        # Track cycle times
        cycle_times = []
        monitor.on_cycle(lambda t: cycle_times.append(t))
        
        # Run several cycles
        for _ in range(10):
            await monitor._monitoring_cycle()
        
        # Check average cycle time
        avg_cycle = sum(cycle_times) / len(cycle_times)
        
        assert avg_cycle < 100, f"Average cycle time {avg_cycle}ms exceeds 100ms target"
        
        print(f"✓ Average cycle time: {avg_cycle:.2f}ms (target: <100ms)")
    
    @pytest.mark.asyncio
    async def test_pause_resume(self):
        """Test pausing and resuming the monitor."""
        from intelligence.proactive_monitor import (
            create_proactive_monitor,
            MonitorState,
        )
        
        monitor = create_proactive_monitor(cycle_interval_ms=10)
        
        await monitor.start()
        await asyncio.sleep(0.02)
        
        # Pause
        monitor.pause()
        assert monitor._state == MonitorState.PAUSED
        
        # Resume
        monitor.resume()
        assert monitor._state == MonitorState.RUNNING
        
        await monitor.stop()
        
        print("✓ Pause/resume works correctly")


class TestStats:
    """Test statistics tracking."""
    
    @pytest.mark.asyncio
    async def test_stats_tracking(self):
        """Test that stats are tracked correctly."""
        from intelligence.proactive_monitor import create_proactive_monitor
        
        monitor = create_proactive_monitor(poll_interval_seconds=0)
        
        email = MockEmailAdapter()
        monitor.connect_service("email", email)
        monitor.add_vip_contact("test@example.com")
        
        # Run some cycles
        for _ in range(5):
            await monitor._monitoring_cycle()
        
        stats = monitor.get_stats()
        
        assert stats["cycle_count"] == 5
        assert stats["connected_services"] == ["email"]
        assert stats["vip_contacts"] == 1
        assert "average_cycle_ms" in stats
        
        print(f"✓ Stats: {stats}")


# ============================================================================
# Integration Tests
# ============================================================================

class TestIntegrationWithIntelligence:
    """Test integration with existing intelligence layer."""
    
    @pytest.mark.asyncio
    async def test_with_semantic_memory(self):
        """Test that alerts can be stored in semantic memory."""
        import tempfile
        import shutil
        from intelligence.semantic_memory import SemanticMemory, FactCategory
        from intelligence.proactive_monitor import create_proactive_monitor
        
        temp_dir = tempfile.mkdtemp()
        
        try:
            memory = SemanticMemory(storage_path=temp_dir)
            monitor = create_proactive_monitor(poll_interval_seconds=0)
            email = MockEmailAdapter()
            monitor.connect_service("email", email)
            
            # When we get an alert, remember it
            async def on_alert(alert):
                await memory.remember(
                    f"Received alert: {alert.title} - {alert.message}",
                    category=FactCategory.CONTEXT,
                    entity=alert.source_service,
                )
            
            alerts = []
            monitor.on_alert(lambda a: alerts.append(a))
            
            # Generate alert
            await monitor._monitoring_cycle()
            email.add_message({"is_important": True, "subject": "Integration Test"})
            await monitor._monitoring_cycle()
            
            # Store in memory
            if alerts:
                await on_alert(alerts[0])
            
            # Recall from memory
            results = await memory.recall("alert")
            
            assert len(results) >= 1
            
            print("✓ Alerts integrate with semantic memory")
            
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.mark.asyncio
    async def test_with_cross_service_intelligence(self):
        """Test that alerts can leverage cross-service intelligence."""
        from intelligence.cross_service import CrossServiceIntelligence
        from intelligence.proactive_monitor import create_proactive_monitor
        
        intel = CrossServiceIntelligence()
        monitor = create_proactive_monitor(poll_interval_seconds=0)
        
        # Learn that bob@acme.com is "Bob from Acme"
        intel.learn_alias("bob", "bob@acme.com")
        intel.learn_alias("bob", "Bob from Acme")
        
        email = MockEmailAdapter()
        monitor.connect_service("email", email)
        monitor.add_vip_contact("bob@acme.com")
        
        alerts = []
        monitor.on_alert(lambda a: alerts.append(a))
        
        # Email from bob
        await monitor._monitoring_cycle()
        email.add_message({
            "from": "bob@acme.com",
            "subject": "Contract Update",
        })
        await monitor._monitoring_cycle()
        
        # Resolve the entity
        if alerts:
            sender = "bob@acme.com"
            resolved = intel.resolve_entity(sender)
            assert resolved == "bob"
        
        print("✓ Alerts integrate with cross-service intelligence")


# ============================================================================
# Performance Tests
# ============================================================================

class TestPerformance:
    """Test performance characteristics."""
    
    @pytest.mark.asyncio
    async def test_many_services(self):
        """Test with many connected services."""
        from intelligence.proactive_monitor import create_proactive_monitor
        
        monitor = create_proactive_monitor(poll_interval_seconds=0)
        
        # Connect 10 services
        for i in range(10):
            adapter = MockEmailAdapter()
            adapter.messages = [{"id": f"msg_{j}", "subject": f"Test {j}"} for j in range(10)]
            monitor.connect_service(f"service_{i}", adapter)
        
        # Run cycles
        import time
        start = time.perf_counter()
        
        for _ in range(100):
            await monitor._monitoring_cycle()
        
        elapsed = (time.perf_counter() - start) * 1000
        avg_cycle = elapsed / 100
        
        assert avg_cycle < 100, f"Average {avg_cycle}ms exceeds 100ms with 10 services"
        
        print(f"✓ 100 cycles with 10 services: avg {avg_cycle:.2f}ms")
    
    @pytest.mark.asyncio
    async def test_many_alerts(self):
        """Test handling many alerts."""
        from intelligence.proactive_monitor import create_proactive_monitor
        
        monitor = create_proactive_monitor(poll_interval_seconds=0)
        email = MockEmailAdapter()
        monitor.connect_service("email", email)
        
        alerts = []
        monitor.on_alert(lambda a: alerts.append(a))
        
        # Generate many alerts
        for i in range(50):
            await monitor._monitoring_cycle()
            email.add_message({
                "is_important": True,
                "subject": f"Important #{i}",
            })
            await monitor._monitoring_cycle()
        
        # All should be processed
        assert len(alerts) >= 50
        
        stats = monitor.get_stats()
        assert stats["alerts_generated"] >= 50
        
        print(f"✓ Generated {len(alerts)} alerts successfully")


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    # Run tests manually for quick verification
    import sys
    sys.path.insert(0, ".")
    
    print("=" * 60)
    print("Phase 4: Proactive Intelligence Tests")
    print("=" * 60)
    
    async def run_quick_tests():
        # Basic tests
        test = TestProactiveMonitorBasics()
        test.test_import()
        test.test_create_monitor()
        test.test_connect_service()
        test.test_vip_contacts()
        
        # Alert tests
        alert_test = TestAlertGeneration()
        await alert_test.test_important_email_alert()
        await alert_test.test_vip_email_alert()
        await alert_test.test_meeting_soon_alert()
        await alert_test.test_task_overdue_alert()
        
        # Management tests
        mgmt_test = TestAlertManagement()
        await mgmt_test.test_acknowledge_alert()
        await mgmt_test.test_dismiss_alert()
        
        # Loop tests
        loop_test = TestMonitoringLoop()
        await loop_test.test_start_stop()
        await loop_test.test_cycle_time_target()
        await loop_test.test_pause_resume()
        
        # Stats test
        stats_test = TestStats()
        await stats_test.test_stats_tracking()
        
        # Integration tests
        int_test = TestIntegrationWithIntelligence()
        await int_test.test_with_semantic_memory()
        await int_test.test_with_cross_service_intelligence()
        
        # Performance tests
        perf_test = TestPerformance()
        await perf_test.test_many_services()
        await perf_test.test_many_alerts()
        
        print("\n" + "=" * 60)
        print("All Phase 4 quick tests passed!")
        print("=" * 60)
    
    asyncio.run(run_quick_tests())
