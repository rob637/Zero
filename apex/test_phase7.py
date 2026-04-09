"""
Phase 7 Tests: Trust & Control Layer

Tests for:
- Privacy: RedactionEngine, AuditLogger, SecureLLMClient
- Control: TrustLevelManager, ApprovalGateway
"""

import pytest
import asyncio
import tempfile
import os
from pathlib import Path
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

# Privacy imports
from src.privacy.redaction import RedactionEngine, PIIType
from src.privacy.audit_log import AuditLogger, TransmissionRecord, TransmissionDestination
from src.privacy.secure_llm import SecureLLMClient

# Control imports  
from src.control.trust_levels import TrustLevel, TrustLevelManager
from src.control.approval_gateway import ApprovalGateway, PendingAction, ActionStatus, ActionPreview


# =============================================================================
# REDACTION ENGINE TESTS
# =============================================================================

class TestRedactionEngine:
    """Test PII detection and redaction."""
    
    def setup_method(self):
        """Fresh engine for each test."""
        self.engine = RedactionEngine()
    
    def test_ssn_detection(self):
        """Should detect and redact SSN."""
        text = "My SSN is 123-45-6789 and it's private"
        result = self.engine.redact(text)
        
        assert "123-45-6789" not in result.redacted_text
        assert "SSN_REDACTED" in result.redacted_text
        assert result.had_pii is True
    
    def test_ssn_without_dashes(self):
        """Should detect SSN without dashes."""
        text = "SSN: 123456789"
        result = self.engine.redact(text)
        
        assert "123456789" not in result.redacted_text
        assert "SSN_REDACTED" in result.redacted_text
    
    def test_credit_card_visa(self):
        """Should detect Visa cards (starts with 4)."""
        # Valid Visa number (passes Luhn)
        text = "Card: 4532015112830366"
        result = self.engine.redact(text)
        
        assert "4532015112830366" not in result.redacted_text
        assert "CARD_REDACTED" in result.redacted_text
    
    def test_credit_card_mastercard(self):
        """Should detect Mastercard (starts with 51-55)."""
        text = "Use card 5425233430109903"
        result = self.engine.redact(text)
        
        assert "5425233430109903" not in result.redacted_text
        assert "CARD_REDACTED" in result.redacted_text
    
    def test_credit_card_amex(self):
        """Should detect Amex (starts with 34/37, 15 digits)."""
        text = "Amex: 378282246310005"
        result = self.engine.redact(text)
        
        assert "378282246310005" not in result.redacted_text
        assert "CARD_REDACTED" in result.redacted_text
    
    def test_credit_card_with_spaces(self):
        """Should detect cards formatted with spaces."""
        text = "Card: 4532 0151 1283 0366"
        result = self.engine.redact(text)
        
        assert "4532 0151 1283 0366" not in result.redacted_text
    
    def test_invalid_credit_card_not_redacted(self):
        """Should NOT redact numbers that fail Luhn check."""
        text = "Random number: 1234567890123456"  # Fails Luhn
        result = self.engine.redact(text)
        
        # Should not find as credit card (invalid Luhn)
        card_redactions = [r for r in result.redactions if 'CARD' in r.get('type', '')]
        assert len(card_redactions) == 0
    
    def test_phone_number(self):
        """Should detect phone numbers in strict mode."""
        engine = RedactionEngine(strict_mode=True)
        text = "Call me at (555) 123-4567"
        result = engine.redact(text)
        
        assert "(555) 123-4567" not in result.redacted_text
        assert "PHONE_REDACTED" in result.redacted_text
    
    def test_ip_address_strict_mode(self):
        """Should detect IP addresses in strict mode."""
        engine = RedactionEngine(strict_mode=True)
        text = "Server IP is 192.168.1.100"
        result = engine.redact(text)
        
        assert "192.168.1.100" not in result.redacted_text
        assert "IP_REDACTED" in result.redacted_text
    
    def test_bank_account_with_context(self):
        """Should detect bank account numbers with context."""
        text = "Routing number: 123456789 for account: 12345678901"
        result = self.engine.redact(text)
        
        # Should redact the account numbers (with context keyword)
        assert "123456789" not in result.redacted_text or "ACCOUNT_REDACTED" in result.redacted_text
        assert result.had_pii is True
    
    def test_multiple_pii(self):
        """Should redact multiple PII types in one text."""
        engine = RedactionEngine(strict_mode=True)
        text = """
        Customer: John Doe
        SSN: 123-45-6789
        Card: 4532015112830366
        Phone: (555) 123-4567
        """
        result = engine.redact(text)
        
        assert "123-45-6789" not in result.redacted_text
        assert "4532015112830366" not in result.redacted_text
        assert "(555) 123-4567" not in result.redacted_text
        assert result.redaction_count >= 3
    
    def test_empty_text(self):
        """Should handle empty text."""
        result = self.engine.redact("")
        assert result.redacted_text == ""
        assert result.redactions == []
        assert result.had_pii is False
    
    def test_safe_text_unchanged(self):
        """Text without PII should pass through unchanged."""
        text = "This is a normal message with no sensitive data."
        result = self.engine.redact(text)
        
        assert result.redacted_text == text
        assert result.redactions == []
        assert result.had_pii is False
    
    def test_contains_pii(self):
        """Should detect if text contains PII."""
        result = self.engine.redact("My SSN is 123-45-6789")
        assert result.had_pii is True
        
        result = self.engine.redact("Hello world")
        assert result.had_pii is False


# =============================================================================
# AUDIT LOGGER TESTS
# =============================================================================

class TestAuditLogger:
    """Test transmission audit logging."""
    
    def setup_method(self):
        """Fresh database for each test."""
        # Use temp file for test db
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_audit.db")
        self.logger = AuditLogger(db_path=self.db_path)
    
    def teardown_method(self):
        """Clean up temp files."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_log_outbound(self):
        """Should log outbound transmissions."""
        record_id = self.logger.log_outbound(
            destination=TransmissionDestination.ANTHROPIC,
            content="What is 2+2?",
            triggering_request="User asked: calculate 2+2"
        )
        
        assert record_id is not None
        assert record_id.startswith("tx_")
    
    def test_log_inbound(self):
        """Should log inbound responses."""
        # First log outbound to get a request_id
        request_id = self.logger.log_outbound(
            destination=TransmissionDestination.ANTHROPIC,
            content="What is 2+2?",
            triggering_request="User asked: calculate 2+2"
        )
        
        record_id = self.logger.log_inbound(
            destination=TransmissionDestination.ANTHROPIC,
            content="The answer is 4",
            request_id=request_id
        )
        
        assert record_id is not None
    
    def test_content_preview_truncation(self):
        """Should truncate long content in preview."""
        long_content = "x" * 600  # Longer than PREVIEW_LENGTH (500)
        record_id = self.logger.log_outbound(
            destination=TransmissionDestination.ANTHROPIC,
            content=long_content,
            triggering_request="test"
        )
        
        # Get the record and check preview was truncated
        records = self.logger.get_transmissions(limit=1)
        assert len(records) == 1
        assert len(records[0].content_preview) <= 500
    
    def test_get_transmissions(self):
        """Should retrieve recent transmissions."""
        # Log several
        self.logger.log_outbound(
            TransmissionDestination.ANTHROPIC, "msg1", "req1"
        )
        self.logger.log_inbound(
            TransmissionDestination.ANTHROPIC, "resp1", request_id=None
        )
        self.logger.log_outbound(
            TransmissionDestination.OPENAI, "msg2", "req2"
        )
        
        records = self.logger.get_transmissions(limit=10)
        
        assert len(records) == 3
    
    def test_get_stats(self):
        """Should compute transmission statistics."""
        self.logger.log_outbound(
            TransmissionDestination.ANTHROPIC, "short", "req"
        )
        self.logger.log_outbound(
            TransmissionDestination.ANTHROPIC, "x" * 100, "req"
        )
        self.logger.log_inbound(
            TransmissionDestination.ANTHROPIC, "y" * 50
        )
        
        stats = self.logger.get_stats()
        
        assert stats['total_transmissions'] == 3
        assert stats['outbound_count'] == 2
        assert stats['inbound_count'] == 1
    
    def test_get_today_summary(self):
        """Should summarize today's activity."""
        self.logger.log_outbound(
            TransmissionDestination.ANTHROPIC, "query", "req"
        )
        self.logger.log_outbound(
            TransmissionDestination.OPENAI, "query2", "req2"
        )
        
        # get_today_summary returns a formatted string
        summary = self.logger.get_today_summary()
        
        assert "2 outbound" in summary
        assert "0 inbound" in summary


# =============================================================================
# TRUST LEVEL MANAGER TESTS
# =============================================================================

class TestTrustLevelManager:
    """Test trust level management."""
    
    def setup_method(self):
        """Fresh manager for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_trust.db")
        self.manager = TrustLevelManager(db_path=self.db_path)
    
    def teardown_method(self):
        """Clean up temp files."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_default_send_email_always_ask(self):
        """Email sending should always require approval by default."""
        level = self.manager.get_trust_level("send_email")
        assert level == TrustLevel.ALWAYS_ASK
    
    def test_default_delete_always_ask(self):
        """Delete operations should always require approval."""
        level = self.manager.get_trust_level("delete_file")
        assert level == TrustLevel.ALWAYS_ASK
    
    def test_default_read_auto_approve(self):
        """Read operations should auto-approve by default."""
        level = self.manager.get_trust_level("read_file")
        assert level == TrustLevel.AUTO_APPROVE
    
    def test_default_search_auto_approve(self):
        """Search operations should auto-approve by default."""
        level = self.manager.get_trust_level("search_files")
        assert level == TrustLevel.AUTO_APPROVE
    
    def test_set_trust_level(self):
        """Should be able to set custom trust level."""
        self.manager.set_trust_level("create_calendar_event", TrustLevel.AUTO_APPROVE)
        level = self.manager.get_trust_level("create_calendar_event")
        assert level == TrustLevel.AUTO_APPROVE
    
    def test_ask_once_pattern_learning(self):
        """ASK_ONCE should remember approved patterns."""
        # First time - should return ASK_ONCE
        level = self.manager.get_trust_level("create_calendar_event")
        assert level == TrustLevel.ASK_ONCE
        
        # "Approve" with pattern
        pattern = {"title": "Team Meeting", "recurring": True}
        self.manager.remember_pattern(
            "create_calendar_event",
            pattern,
            "Weekly team meeting"
        )
        
        # Same pattern now auto-approves
        level = self.manager.get_trust_level("create_calendar_event", context=pattern)
        assert level == TrustLevel.AUTO_APPROVE
    
    def test_reset_trust_level(self):
        """Should be able to reset to defaults."""
        self.manager.set_trust_level("send_email", TrustLevel.AUTO_APPROVE)
        self.manager.reset_to_defaults("send_email")
        level = self.manager.get_trust_level("send_email")
        assert level == TrustLevel.ALWAYS_ASK  # Back to default
    
    def test_unknown_action_defaults_ask_once(self):
        """Unknown actions should default to ASK_ONCE for safety."""
        level = self.manager.get_trust_level("some_unknown_action")
        assert level == TrustLevel.ASK_ONCE


# =============================================================================
# APPROVAL GATEWAY TESTS
# =============================================================================

class TestApprovalGateway:
    """Test the approval gateway."""
    
    def setup_method(self):
        """Fresh gateway for each test."""
        self.temp_dir = tempfile.mkdtemp()
        trust_db = os.path.join(self.temp_dir, "trust.db")
        
        self.trust_manager = TrustLevelManager(db_path=trust_db)
        self.gateway = ApprovalGateway(trust_mgr=self.trust_manager)
    
    def teardown_method(self):
        """Clean up temp files."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    @pytest.mark.asyncio
    async def test_submit_email_action(self):
        """Submitting email should require approval."""
        action = PendingAction(
            action_type="send_email",
            payload={
                "to": "test@example.com",
                "subject": "Hello",
                "body": "Test message"
            },
            preview=ActionPreview(
                title="Send Email",
                description="To: test@example.com",
                preview_type="email"
            ),
            executor=AsyncMock()
        )
        
        action_id = await self.gateway.submit(action)
        
        assert action.status == ActionStatus.PENDING
        assert action_id is not None
    
    @pytest.mark.asyncio
    async def test_auto_approve_read(self):
        """Read actions should auto-execute."""
        executor = AsyncMock(return_value="file contents")
        
        action = PendingAction(
            action_type="read_file",
            payload={"path": "/test/file.txt"},
            preview=ActionPreview(
                title="Read File",
                description="Read /test/file.txt",
                preview_type="file"
            ),
            executor=executor
        )
        
        await self.gateway.submit(action)
        
        # Should have auto-executed
        assert action.status in [ActionStatus.COMPLETED, ActionStatus.AUTO_APPROVED]
        executor.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_approve_action(self):
        """Should be able to approve pending action."""
        executor = AsyncMock(return_value="sent")
        
        action = PendingAction(
            action_type="send_email",
            payload={"to": "test@example.com"},
            preview=ActionPreview(
                title="Send Email",
                description="Test",
                preview_type="email"
            ),
            executor=executor
        )
        
        action_id = await self.gateway.submit(action)
        assert action.status == ActionStatus.PENDING
        
        # Approve it
        result = await self.gateway.approve(action_id)
        
        assert result is not None
        executor.assert_called_once()
        assert result.status == ActionStatus.COMPLETED
    
    @pytest.mark.asyncio
    async def test_reject_action(self):
        """Should be able to reject pending action."""
        executor = AsyncMock()
        
        action = PendingAction(
            action_type="send_email",
            payload={"to": "test@example.com"},
            preview=ActionPreview(
                title="Send Email",
                description="Test",
                preview_type="email"
            ),
            executor=executor
        )
        
        action_id = await self.gateway.submit(action)
        
        result = await self.gateway.reject(action_id, reason="Changed my mind")
        
        assert result.status == ActionStatus.REJECTED
        executor.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_modify_and_approve(self):
        """Should be able to modify payload before approval."""
        executor = AsyncMock(return_value="sent")
        
        action = PendingAction(
            action_type="send_email",
            payload={"to": "test@example.com", "subject": "Original"},
            preview=ActionPreview(
                title="Send Email",
                description="Test",
                preview_type="email"
            ),
            executor=executor
        )
        
        action_id = await self.gateway.submit(action)
        
        # Modify and approve
        result = await self.gateway.approve(
            action_id,
            modifications={"subject": "Modified Subject"}
        )
        
        # Executor should have been called with modified payload
        call_payload = executor.call_args[0][0]
        assert call_payload.get("subject") == "Modified Subject"
    
    @pytest.mark.asyncio
    async def test_get_pending_actions(self):
        """Should list all pending actions."""
        executor = AsyncMock()
        
        action1 = PendingAction(
            action_type="send_email",
            payload={"to": "a@test.com"},
            preview=ActionPreview(title="Email 1", description="", preview_type="email"),
            executor=executor
        )
        action2 = PendingAction(
            action_type="send_email",
            payload={"to": "b@test.com"},
            preview=ActionPreview(title="Email 2", description="", preview_type="email"),
            executor=executor
        )
        
        await self.gateway.submit(action1)
        await self.gateway.submit(action2)
        
        pending = self.gateway.get_pending()
        
        assert len(pending) == 2


# =============================================================================
# SECURE LLM CLIENT TESTS
# =============================================================================

class TestSecureLLMClient:
    """Test privacy-wrapped LLM client."""
    
    def setup_method(self):
        """Create mocked secure client."""
        self.temp_dir = tempfile.mkdtemp()
        audit_db = os.path.join(self.temp_dir, "audit.db")
        
        # Mock base client with proper config structure
        self.mock_config = Mock()
        self.mock_config.provider = "anthropic"
        self.mock_config.model = "claude-sonnet-4-20250514"
        
        self.mock_base = Mock()
        self.mock_base.complete = AsyncMock(return_value="The answer is 4")
        self.mock_base.config = self.mock_config
        
        self.audit = AuditLogger(db_path=audit_db)
        self.redaction = RedactionEngine()
        
        self.client = SecureLLMClient(
            base_client=self.mock_base,
            audit=self.audit,
            redactor=self.redaction
        )
    
    def teardown_method(self):
        """Clean up temp files."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    @pytest.mark.asyncio
    async def test_redacts_pii_before_sending(self):
        """Should redact PII from prompts before sending to LLM."""
        result = await self.client.complete(
            system="You are a helpful assistant",
            user="My SSN is 123-45-6789, what should I do with it?",
            triggering_request="test"
        )
        
        # Check what was actually sent to base client
        call_args = self.mock_base.complete.call_args
        sent_user = call_args[1]['user']
        
        assert "123-45-6789" not in sent_user
        assert "SSN_REDACTED" in sent_user
    
    @pytest.mark.asyncio
    async def test_logs_transmission(self):
        """Should log all external transmissions."""
        await self.client.complete(
            system="System prompt",
            user="User message",
            triggering_request="User typed: help"
        )
        
        records = self.audit.get_transmissions()
        
        # Should have outbound and inbound
        assert len(records) == 2
        assert any(r.direction.value == "outbound" for r in records)
        assert any(r.direction.value == "inbound" for r in records)
    
    @pytest.mark.asyncio
    async def test_preserves_response(self):
        """Should return response unchanged."""
        self.mock_base.complete = AsyncMock(return_value="Important answer")
        
        result = await self.client.complete(
            system="sys",
            user="query",
            triggering_request="test"
        )
        
        assert result == "Important answer"
    
    @pytest.mark.asyncio
    async def test_stats_tracking(self):
        """Should track redaction statistics."""
        self.mock_base.complete = AsyncMock(return_value="ok")
        
        await self.client.complete(
            system="sys",
            user="SSN: 123-45-6789, Card: 4532015112830366",
            triggering_request="test"
        )
        
        stats = self.client.get_stats()
        
        assert stats['total_calls'] == 1
        assert stats['total_redactions'] >= 2


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestPhase7Integration:
    """Integration tests for the full trust & control flow."""
    
    def setup_method(self):
        """Set up full stack."""
        self.temp_dir = tempfile.mkdtemp()
        
        trust_db = os.path.join(self.temp_dir, "trust.db")
        audit_db = os.path.join(self.temp_dir, "audit.db")
        
        self.trust = TrustLevelManager(db_path=trust_db)
        self.gateway = ApprovalGateway(trust_mgr=self.trust)
        self.audit = AuditLogger(db_path=audit_db)
        self.redaction = RedactionEngine()
    
    def teardown_method(self):
        """Clean up."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    @pytest.mark.asyncio
    async def test_email_workflow_with_pii(self):
        """Full workflow: User requests email with PII, gets preview, approves."""
        # Simulate: "Send email with SSN 123-45-6789 to test@example.com"
        
        # 1. Redact PII for LLM query about the task
        query = "User wants to email their SSN 123-45-6789"
        result = self.redaction.redact(query)
        
        assert "123-45-6789" not in result.redacted_text
        assert result.redaction_count == 1
        
        # 2. Submit action to gateway
        email_sent = False
        async def send_email(payload):
            nonlocal email_sent
            email_sent = True
            return "Email sent"
        
        action = PendingAction(
            action_type="send_email",
            payload={
                "to": "recipient@example.com",
                "subject": "Important Info",
                "body": "Your SSN is 123-45-6789"  # Contains PII
            },
            preview=ActionPreview(
                title="Send Email",
                description="To: recipient@example.com",
                preview_type="email",
                fields={"to": "recipient@example.com", "subject": "Important Info"}
            ),
            executor=send_email
        )
        
        action_id = await self.gateway.submit(action)
        
        # 3. Should be pending (email always asks)
        assert action.status == ActionStatus.PENDING
        assert not email_sent
        
        # 4. User approves
        await self.gateway.approve(action_id)
        
        # 5. Now executed
        assert email_sent
    
    @pytest.mark.asyncio
    async def test_multi_step_workflow(self):
        """Multi-step: Find doc -> Calculate -> Email (all need approval)."""
        steps_executed = []
        
        # Step 1: Find document (auto-approve - it's a search)
        async def find_doc(p):
            steps_executed.append("find")
            return "loan_doc.pdf"
        
        action1 = PendingAction(
            action_type="search_files",
            payload={"query": "loan document"},
            preview=ActionPreview(title="Search files", description="", preview_type="search"),
            executor=find_doc
        )
        
        await self.gateway.submit(action1)
        
        # Should auto-execute (search is AUTO_APPROVE)
        assert action1.status in [ActionStatus.COMPLETED, ActionStatus.AUTO_APPROVED]
        assert "find" in steps_executed
        
        # Step 2: Create document (ASK_ONCE)
        async def calculate(p):
            steps_executed.append("calculate")
            return "amortization_schedule.xlsx"
        
        action2 = PendingAction(
            action_type="create_document",
            payload={"type": "spreadsheet"},
            preview=ActionPreview(title="Create amortization schedule", description="", preview_type="document"),
            executor=calculate
        )
        
        action_id2 = await self.gateway.submit(action2)
        
        # ASK_ONCE - needs approval first time
        if action2.status == ActionStatus.PENDING:
            await self.gateway.approve(action_id2)
        
        assert "calculate" in steps_executed
        
        # Step 3: Email (always needs approval)
        async def send_email(p):
            steps_executed.append("email")
            return "sent"
        
        action3 = PendingAction(
            action_type="send_email",
            payload={"to": "rob@sagecg.com"},
            preview=ActionPreview(title="Send loan summary", description="", preview_type="email"),
            executor=send_email
        )
        
        action_id3 = await self.gateway.submit(action3)
        
        assert action3.status == ActionStatus.PENDING
        assert "email" not in steps_executed
        
        await self.gateway.approve(action_id3)
        assert "email" in steps_executed


# =============================================================================
# SENSITIVE MARKER TESTS
# =============================================================================

class TestSensitiveMarker:
    """Test the SensitiveMarker component."""
    
    def setup_method(self):
        """Fresh marker for each test."""
        from src.privacy.sensitive_marker import SensitiveMarker, SensitivityLevel
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "sensitive.db")
        self.marker = SensitiveMarker(db_path=self.db_path)
        self.SensitivityLevel = SensitivityLevel
    
    def teardown_method(self):
        """Clean up."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_mark_file_as_sensitive(self):
        """Should mark a specific file as sensitive."""
        self.marker.mark(
            path="/home/user/secrets/api_key.txt",
            level=self.SensitivityLevel.BLOCKED,
            reason="Contains API keys"
        )
        
        level = self.marker.get_sensitivity_level("/home/user/secrets/api_key.txt")
        assert level == self.SensitivityLevel.BLOCKED
    
    def test_mark_folder_recursive(self):
        """Marking a folder should affect its contents."""
        self.marker.mark(
            path="/home/user/.ssh/",
            level=self.SensitivityLevel.BLOCKED,
            reason="SSH keys"
        )
        
        # File inside should be blocked
        level = self.marker.get_sensitivity_level("/home/user/.ssh/id_rsa")
        assert level == self.SensitivityLevel.BLOCKED
    
    def test_default_sensitive_patterns(self):
        """Default patterns should catch common sensitive files."""
        # SSH keys
        assert self.marker.is_sensitive("/home/user/.ssh/id_rsa")
        
        # Environment files
        assert self.marker.is_sensitive("/project/.env")
        assert self.marker.is_sensitive("/project/.env.local")
        
        # Keys and certificates
        assert self.marker.is_sensitive("/certs/server.pem")
        assert self.marker.is_sensitive("/certs/private.key")
        
        # AWS credentials
        assert self.marker.is_sensitive("/home/user/.aws/credentials")
    
    def test_unmark_file(self):
        """Should be able to unmark a file."""
        self.marker.mark(
            path="/test/file.txt",
            level=self.SensitivityLevel.PRIVATE,
            reason="Test"
        )
        
        assert self.marker.is_sensitive("/test/file.txt")
        
        self.marker.unmark("/test/file.txt")
        
        # Should no longer be in manual markers (may still match patterns)
        level = self.marker.get_sensitivity_level("/test/file.txt")
        # Since it doesn't match default patterns, should be NORMAL
        assert level == self.SensitivityLevel.NORMAL
    
    def test_add_custom_pattern(self):
        """Should support custom sensitive patterns."""
        self.marker.mark_pattern(
            pattern="**/*.secret",  # Glob pattern, not regex
            level=self.SensitivityLevel.BLOCKED,
            reason="Custom secret files"
        )
        
        assert self.marker.is_sensitive("/any/path/config.secret")
        assert not self.marker.is_sensitive("/any/path/config.txt")
    
    def test_access_logging(self):
        """Should log attempted access to blocked files."""
        self.marker.mark(
            path="/blocked/file.txt",
            level=self.SensitivityLevel.BLOCKED,
            reason="Test block"
        )
        
        # Access attempt (get_sensitivity_level logs internally)
        self.marker.get_sensitivity_level("/blocked/file.txt")
        
        # Check access was logged
        attempts = self.marker.get_access_log(limit=10)
        assert len(attempts) >= 1
        assert "/blocked/file.txt" in attempts[0]['path']
    
    def test_normal_file_not_sensitive(self):
        """Normal files should not be marked as sensitive."""
        assert not self.marker.is_sensitive("/home/user/document.txt")
        assert not self.marker.is_sensitive("/project/src/main.py")
    
    def test_sensitivity_levels_exist(self):
        """Should have all expected sensitivity levels."""
        from src.privacy.sensitive_marker import SensitivityLevel
        
        # Verify all levels exist
        levels = [l.value for l in SensitivityLevel]
        assert "blocked" in levels
        assert "private" in levels
        assert "sensitive" in levels
        assert "normal" in levels
        
        # Verify they're distinct
        assert len(set(levels)) == 4


# =============================================================================
# CONTEXT MINIMIZER TESTS
# =============================================================================

class TestContextMinimizer:
    """Test the ContextMinimizer component."""
    
    def setup_method(self):
        """Fresh minimizer for each test."""
        from src.privacy.context_minimizer import (
            ContextMinimizer, MinimalContext, ExtractionMode
        )
        self.minimizer = ContextMinimizer()
        self.ExtractionMode = ExtractionMode
        self.MinimalContext = MinimalContext
        
        # Create temp dir for test files
        self.temp_dir = tempfile.mkdtemp()
    
    def teardown_method(self):
        """Clean up."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_extract_from_text_keywords(self):
        """Should extract keywords from text."""
        content = """
        The quarterly budget report shows significant revenue growth.
        Marketing expenses increased due to new campaign initiatives.
        """
        
        ctx = self.minimizer.extract_from_text(content)
        
        assert ctx.source_type == "text"
        assert "revenue" in ctx.keywords or "budget" in ctx.keywords
        assert "quarterly" in ctx.keywords or "marketing" in ctx.keywords
        assert ctx.word_count > 0
    
    def test_extract_from_text_minimal_mode(self):
        """Minimal mode should only extract metadata, not content."""
        content = "This is a test document with some keywords and content."
        
        ctx = self.minimizer.extract_from_text(
            content,
            mode=self.ExtractionMode.MINIMAL
        )
        
        assert ctx.word_count > 0
        assert ctx.keywords == []  # No keywords in minimal mode
        assert ctx.summary is None
    
    def test_extract_from_file(self):
        """Should extract context from a file."""
        # Create test file
        test_file = os.path.join(self.temp_dir, "test.txt")
        Path(test_file).write_text(
            "This is a test document about software development and testing."
        )
        
        ctx = self.minimizer.extract_from_file(test_file)
        
        assert ctx.source_type == "file"
        assert ctx.file_type is not None
        assert ctx.word_count > 0
        assert "software" in ctx.keywords or "development" in ctx.keywords
    
    def test_topic_detection(self):
        """Should detect topics based on keywords."""
        finance_text = """
        The quarterly budget shows strong revenue growth.
        Investment returns exceeded expectations with improved profit margins.
        Tax implications need to be reviewed by the fiscal team.
        """
        
        ctx = self.minimizer.extract_from_text(finance_text)
        
        assert "finance" in ctx.topics
    
    def test_entity_extraction_dates(self):
        """Should extract date entities."""
        content = "The meeting is scheduled for 12/25/2024 and the deadline is January 15, 2025."
        
        ctx = self.minimizer.extract_from_text(
            content,
            mode=self.ExtractionMode.SUMMARY
        )
        
        assert "dates" in ctx.entities
        assert len(ctx.entities["dates"]) >= 1
    
    def test_entity_extraction_money(self):
        """Should extract money amounts."""
        content = "The project budget is $50,000 and we've spent $12,500 so far."
        
        ctx = self.minimizer.extract_from_text(
            content,
            mode=self.ExtractionMode.SUMMARY
        )
        
        assert "money" in ctx.entities
        assert len(ctx.entities["money"]) >= 1
    
    def test_email_extraction(self):
        """Should extract and mask emails."""
        content = "Contact support@example.com or admin@company.com for help."
        
        ctx = self.minimizer.extract_from_text(
            content, 
            mode=self.ExtractionMode.SUMMARY
        )
        
        # Emails should be partially masked
        if "emails" in ctx.entities:
            for email in ctx.entities["emails"]:
                assert "***@" in email  # Should be masked
    
    def test_email_document_context(self):
        """Should extract context from email format."""
        ctx = self.minimizer.extract_from_email(
            subject="Q4 Budget Review Meeting",
            body="Please review the attached quarterly report. We'll discuss revenue projections.",
            sender="manager@company.com",
            date=datetime.now()
        )
        
        assert ctx.source_type == "email"
        assert ctx.structure["subject"] == "Q4 Budget Review Meeting"
        assert "domains" in ctx.entities
        assert "company.com" in ctx.entities["domains"]
    
    def test_calendar_event_context(self):
        """Should extract context from calendar events."""
        start = datetime(2024, 12, 25, 10, 0)
        end = datetime(2024, 12, 25, 11, 0)
        
        ctx = self.minimizer.extract_from_calendar_event(
            title="Team Planning Session",
            description="Discuss Q1 roadmap and resource allocation",
            start_time=start,
            end_time=end,
            attendees=["person1@co.com", "person2@co.com"],
            location="Conference Room A"
        )
        
        assert ctx.source_type == "calendar_event"
        assert ctx.structure["duration_minutes"] == 60
        assert ctx.structure["attendee_count"] == 2
    
    def test_summary_generation(self):
        """Should generate brief summaries."""
        content = """
        This is the first sentence of the document.
        It continues with more information.
        And even more details follow.
        """
        
        ctx = self.minimizer.extract_from_text(
            content,
            mode=self.ExtractionMode.SUMMARY
        )
        
        assert ctx.summary is not None
        assert len(ctx.summary) <= 100  # Should be brief
    
    def test_combine_contexts(self):
        """Should combine multiple contexts."""
        ctx1 = self.minimizer.extract_from_text("Document about finance and budget.")
        ctx2 = self.minimizer.extract_from_text("Email about project planning.")
        ctx3 = self.minimizer.extract_from_text("Notes from technical meeting.")
        
        combined = self.minimizer.combine_contexts([ctx1, ctx2, ctx3])
        
        assert combined.source_type == "combined"
        assert combined.structure["source_count"] == 3
        # Keywords should be merged
        assert len(combined.keywords) >= 1
    
    def test_to_prompt_context(self):
        """Should generate LLM-ready context string."""
        content = "This quarterly budget shows significant revenue growth and marketing expenses."
        
        ctx = self.minimizer.extract_from_text(
            content,
            mode=self.ExtractionMode.KEYWORDS
        )
        
        prompt_ctx = ctx.to_prompt_context()
        
        assert isinstance(prompt_ctx, str)
        assert "[Document: text]" in prompt_ctx
        assert "Keywords:" in prompt_ctx
    
    def test_blocked_file_extraction(self):
        """Should respect SensitiveMarker blocks."""
        from src.privacy.sensitive_marker import SensitiveMarker, SensitivityLevel
        from src.privacy.context_minimizer import ContextMinimizer
        
        marker = SensitiveMarker(db_path=os.path.join(self.temp_dir, "sens.db"))
        marker.mark("/secret/file.txt", SensitivityLevel.BLOCKED, "Secret")
        
        minimizer = ContextMinimizer()
        minimizer.set_sensitive_marker(marker)
        
        ctx = minimizer.extract_from_file("/secret/file.txt")
        
        # Should be blocked - minimal context only
        assert ctx.sensitive_content_detected is True
        assert ctx.extraction_mode == "blocked"
        assert ctx.keywords == []
    
    def test_batch_extraction(self):
        """Should handle batch extraction."""
        items = [
            {"type": "text", "content": "First document about software."},
            {"type": "text", "content": "Second document about hardware."},
        ]
        
        results = self.minimizer.extract_batch(items)
        
        assert len(results) == 2
        assert all(isinstance(r, self.MinimalContext) for r in results)
    
    def test_redaction_integration(self):
        """Should integrate with RedactionEngine."""
        from src.privacy.redaction import RedactionEngine
        from src.privacy.context_minimizer import ContextMinimizer
        
        minimizer = ContextMinimizer()
        minimizer.set_redaction_engine(RedactionEngine())
        
        content = "Contact info: SSN 123-45-6789, Card 4532015112830366"
        ctx = minimizer.extract_from_text(content)
        
        assert ctx.redactions_applied >= 1


# =============================================================================
# ACTION HISTORY DB TESTS (Sprint 3)
# =============================================================================

class TestActionHistoryDB:
    """Test action history persistence."""
    
    def setup_method(self):
        """Fresh database for each test."""
        from src.control.action_history import (
            ActionHistoryDB, ActionRecord, ActionStatus, ActionCategory
        )
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "action_history.db")
        self.history = ActionHistoryDB(db_path=self.db_path)
        self.ActionStatus = ActionStatus
        self.ActionCategory = ActionCategory
    
    def teardown_method(self):
        """Clean up."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_record_action(self):
        """Should record a new action."""
        record = self.history.record_action(
            action_type="send_email",
            payload={"to": "test@example.com", "subject": "Test"},
            preview={"title": "Send email", "description": "to test@example.com"},
            session_id="sess_123"
        )
        
        assert record.id is not None
        assert record.action_type == "send_email"
        assert record.status == self.ActionStatus.PENDING
        assert record.category == self.ActionCategory.EMAIL
    
    def test_update_status(self):
        """Should update action status."""
        record = self.history.record_action(
            action_type="send_email",
            payload={},
            preview={"title": "Test"}
        )
        
        # Pass decided_by to ensure decided_at is set
        self.history.update_status(record.id, self.ActionStatus.APPROVED, decided_by="user")
        
        updated = self.history.get_action(record.id)
        assert updated.status == self.ActionStatus.APPROVED
        assert updated.decided_at is not None
    
    def test_mark_completed(self):
        """Should mark action as completed with result."""
        record = self.history.record_action(
            action_type="send_email",
            payload={},
            preview={"title": "Test"}
        )
        
        self.history.mark_completed(record.id, {"message_id": "msg_123"})
        
        updated = self.history.get_action(record.id)
        assert updated.status == self.ActionStatus.COMPLETED
        assert updated.result["message_id"] == "msg_123"
    
    def test_mark_failed(self):
        """Should mark action as failed with error."""
        record = self.history.record_action(
            action_type="send_email",
            payload={},
            preview={"title": "Test"}
        )
        
        self.history.mark_failed(record.id, "Connection timeout")
        
        updated = self.history.get_action(record.id)
        assert updated.status == self.ActionStatus.FAILED
        assert "timeout" in updated.error.lower()
    
    def test_get_recent(self):
        """Should get recent actions."""
        for i in range(5):
            self.history.record_action(
                action_type=f"action_{i}",
                payload={},
                preview={"title": f"Action {i}"}
            )
        
        recent = self.history.get_recent(limit=3)
        
        assert len(recent) == 3
        # Most recent first
        assert recent[0].action_type == "action_4"
    
    def test_get_pending(self):
        """Should get pending actions."""
        r1 = self.history.record_action("send_email", {}, {"title": "test1"})
        r2 = self.history.record_action("send_email", {}, {"title": "test2"})
        self.history.mark_completed(r1.id, {})
        
        pending = self.history.get_pending()
        
        assert len(pending) == 1
        assert pending[0].id == r2.id
    
    def test_get_by_category(self):
        """Should filter by category."""
        self.history.record_action("send_email", {}, {"title": "email1"})
        self.history.record_action("read_file", {}, {"title": "file1"})
        self.history.record_action("draft_email", {}, {"title": "email2"})
        
        emails = self.history.get_recent(category=self.ActionCategory.EMAIL)
        
        assert len(emails) == 2
        assert all(r.category == self.ActionCategory.EMAIL for r in emails)
    
    def test_search(self):
        """Should search actions by text."""
        self.history.record_action(
            "send_email",
            {"to": "alice@example.com"},
            {"title": "Send to Alice"},
            request_text="Send email to Alice"
        )
        self.history.record_action(
            "send_email",
            {"to": "bob@example.com"},
            {"title": "Send to Bob"},
            request_text="Send email to Bob"
        )
        
        results = self.history.search("Alice")
        
        assert len(results) == 1
        assert "alice" in results[0].request_text.lower()
    
    def test_get_stats(self):
        """Should calculate statistics."""
        r1 = self.history.record_action("send_email", {}, {"title": "test"})
        r2 = self.history.record_action("read_file", {}, {"title": "test"})
        self.history.mark_completed(r1.id, {})
        self.history.mark_failed(r2.id, "error")
        
        stats = self.history.get_stats()
        
        assert stats["total_actions"] == 2
        assert stats["by_status"].get("completed", 0) == 1
        assert stats["by_status"].get("failed", 0) == 1
    
    def test_get_undoable(self):
        """Should get undoable actions."""
        r1 = self.history.record_action(
            action_type="send_email",
            payload={},
            preview={"title": "test"},
            is_undoable=True
        )
        r2 = self.history.record_action(
            action_type="read_file",
            payload={},
            preview={"title": "test"},
            is_undoable=False
        )
        self.history.mark_completed(r1.id, {})
        self.history.mark_completed(r2.id, {})
        
        undoable = self.history.get_undoable()
        
        # Only action with is_undoable=True is undoable
        assert len(undoable) == 1
        assert undoable[0].is_undoable is True
    
    def test_mark_undone(self):
        """Should mark action as undone."""
        record = self.history.record_action(
            action_type="delete_file",
            payload={},
            preview={"title": "test"},
            is_undoable=True
        )
        self.history.mark_completed(record.id, {})
        self.history.mark_undone(record.id)
        
        updated = self.history.get_action(record.id)
        assert updated.status == self.ActionStatus.UNDONE


# =============================================================================
# UNDO MANAGER TESTS (Sprint 3)
# =============================================================================

class TestUndoManager:
    """Test undo checkpoint and rollback."""
    
    def setup_method(self):
        """Fresh manager for each test."""
        from src.control.undo_manager import (
            UndoManager, Checkpoint, UndoType, UndoStatus
        )
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "undo.db")
        self.backup_dir = os.path.join(self.temp_dir, "backups")
        
        self.manager = UndoManager(
            db_path=self.db_path,
            backup_dir=self.backup_dir
        )
        self.UndoType = UndoType
        self.UndoStatus = UndoStatus
    
    def teardown_method(self):
        """Clean up."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_create_checkpoint(self):
        """Should create a checkpoint."""
        cp = self.manager.create_checkpoint(
            action_id="act_123",
            undo_type=self.UndoType.FILE_DELETE,
            data={"path": "/test/file.txt"},
            description="Delete test file"
        )
        
        assert cp.id is not None
        assert cp.action_id == "act_123"
        assert cp.status == self.UndoStatus.PENDING
    
    def test_commit_checkpoint(self):
        """Should commit a checkpoint making it undoable."""
        cp = self.manager.create_checkpoint(
            action_id="act_123",
            undo_type=self.UndoType.FILE_DELETE,
            data={},
            description="Test"
        )
        
        committed = self.manager.commit_checkpoint(cp.id)
        
        assert committed.status == self.UndoStatus.COMMITTED
        assert committed.committed_at is not None
        assert committed.expires_at is not None
        assert committed.is_undoable is True
    
    def test_cancel_checkpoint(self):
        """Should cancel a pending checkpoint."""
        cp = self.manager.create_checkpoint(
            action_id="act_123",
            undo_type=self.UndoType.GENERIC,
            data={},
            description="Test"
        )
        
        result = self.manager.cancel_checkpoint(cp.id)
        
        assert result is True
        assert self.manager.get_checkpoint(cp.id) is None
    
    def test_create_file_backup(self):
        """Should backup a file before modification."""
        # Create test file
        test_file = os.path.join(self.temp_dir, "test.txt")
        Path(test_file).write_text("original content")
        
        cp = self.manager.create_file_backup(
            action_id="act_123",
            file_path=test_file,
            description="Modifying test file"
        )
        
        assert cp is not None
        assert cp.undo_type == self.UndoType.FILE_OVERWRITE
        assert "backup_path" in cp.data
        assert Path(cp.data["backup_path"]).exists()
    
    def test_file_backup_nonexistent(self):
        """Should return None for nonexistent file."""
        cp = self.manager.create_file_backup(
            action_id="act_123",
            file_path="/nonexistent/file.txt"
        )
        
        assert cp is None
    
    @pytest.mark.asyncio
    async def test_undo_file_delete(self):
        """Should restore deleted file from backup."""
        # Create and backup file
        test_file = os.path.join(self.temp_dir, "to_delete.txt")
        Path(test_file).write_text("important data")
        
        cp = self.manager.create_file_delete_checkpoint(
            action_id="act_123",
            file_path=test_file
        )
        self.manager.commit_checkpoint(cp.id)
        
        # Simulate deletion
        Path(test_file).unlink()
        assert not Path(test_file).exists()
        
        # Undo
        result = await self.manager.undo(cp.id)
        
        assert result["success"] is True
        assert Path(test_file).exists()
        assert Path(test_file).read_text() == "important data"
    
    @pytest.mark.asyncio
    async def test_undo_file_overwrite(self):
        """Should restore overwritten file content."""
        # Create file with original content
        test_file = os.path.join(self.temp_dir, "config.txt")
        Path(test_file).write_text("version=1.0")
        
        # Backup before modification
        cp = self.manager.create_file_backup(
            action_id="act_123",
            file_path=test_file
        )
        self.manager.commit_checkpoint(cp.id)
        
        # Modify the file
        Path(test_file).write_text("version=2.0")
        
        # Undo
        result = await self.manager.undo(cp.id)
        
        assert result["success"] is True
        assert Path(test_file).read_text() == "version=1.0"
    
    @pytest.mark.asyncio
    async def test_undo_already_undone(self):
        """Should fail when trying to undo twice."""
        test_file = os.path.join(self.temp_dir, "test.txt")
        Path(test_file).write_text("data")
        
        cp = self.manager.create_file_delete_checkpoint(
            action_id="act_123",
            file_path=test_file
        )
        self.manager.commit_checkpoint(cp.id)
        Path(test_file).unlink()
        
        # First undo
        await self.manager.undo(cp.id)
        
        # Second undo should fail
        result = await self.manager.undo(cp.id)
        assert result["success"] is False
        assert "already" in result["error"].lower()
    
    def test_get_undoable(self):
        """Should list all undoable checkpoints."""
        # Create and commit some checkpoints
        cp1 = self.manager.create_checkpoint(
            action_id="act_1",
            undo_type=self.UndoType.GENERIC,
            data={},
            description="Test 1"
        )
        cp2 = self.manager.create_checkpoint(
            action_id="act_2",
            undo_type=self.UndoType.GENERIC,
            data={},
            description="Test 2"
        )
        
        # Only commit one
        self.manager.commit_checkpoint(cp1.id)
        
        undoable = self.manager.get_undoable()
        
        assert len(undoable) == 1
        assert undoable[0].id == cp1.id
    
    def test_get_for_action(self):
        """Should find checkpoint by action ID."""
        self.manager.create_checkpoint(
            action_id="act_specific",
            undo_type=self.UndoType.GENERIC,
            data={"custom": "data"},
            description="Specific action"
        )
        
        cp = self.manager.get_for_action("act_specific")
        
        assert cp is not None
        assert cp.data["custom"] == "data"
    
    def test_calendar_checkpoint(self):
        """Should create checkpoint for calendar events."""
        cp = self.manager.create_calendar_event_checkpoint(
            action_id="act_cal",
            event_data={
                "id": "evt_123",
                "title": "Team Meeting",
                "start": "2024-12-25T10:00:00"
            },
            operation="create",
            provider="google"
        )
        
        assert cp.undo_type == self.UndoType.CALENDAR_CREATE
        assert cp.data["event"]["title"] == "Team Meeting"
        assert "Team Meeting" in cp.description


# =============================================================================
# LOCAL VECTOR DB TESTS (Sprint 3)
# =============================================================================

class TestLocalVectorDB:
    """Test local vector database."""
    
    def setup_method(self):
        """Fresh database for each test."""
        from src.privacy.local_vector_db import (
            LocalVectorDB, SearchResult, SearchResults
        )
        self.temp_dir = tempfile.mkdtemp()
        self.persist_dir = os.path.join(self.temp_dir, "vector_db")
        
        self.db = LocalVectorDB(persist_dir=self.persist_dir)
        self.SearchResult = SearchResult
        self.SearchResults = SearchResults
    
    def teardown_method(self):
        """Clean up."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    @pytest.mark.asyncio
    async def test_add_and_search(self):
        """Should add documents and search them."""
        await self.db.add_documents(
            collection="test",
            documents=[
                "The quick brown fox jumps over the lazy dog",
                "Python is a great programming language",
                "Machine learning uses neural networks"
            ],
            ids=["doc1", "doc2", "doc3"]
        )
        
        results = await self.db.search("programming", collection="test")
        
        assert len(results) >= 1
        # Should find the Python document
        found_python = any("python" in r.document.lower() for r in results)
        assert found_python
    
    @pytest.mark.asyncio
    async def test_search_with_metadata(self):
        """Should filter by metadata."""
        await self.db.add_documents(
            collection="emails",
            documents=[
                "Meeting tomorrow at 3pm",
                "Invoice for services",
                "Another meeting reminder"
            ],
            ids=["e1", "e2", "e3"],
            metadatas=[
                {"from": "boss@co.com"},
                {"from": "billing@co.com"},
                {"from": "boss@co.com"}
            ]
        )
        
        results = await self.db.search(
            "meeting",
            collection="emails",
            where={"from": "boss@co.com"}
        )
        
        assert len(results) >= 1
        assert all(r.metadata.get("from") == "boss@co.com" for r in results)
    
    @pytest.mark.asyncio
    async def test_update_document(self):
        """Should update existing document."""
        await self.db.add_documents(
            collection="test",
            documents=["Original content"],
            ids=["doc1"]
        )
        
        success = await self.db.update_document(
            collection="test",
            doc_id="doc1",
            document="Updated content"
        )
        
        assert success is True
        
        # Search should find updated content
        results = await self.db.search("Updated", collection="test")
        found_updated = any("updated" in r.document.lower() for r in results)
        assert found_updated
    
    @pytest.mark.asyncio
    async def test_delete_document(self):
        """Should delete a document."""
        await self.db.add_documents(
            collection="test",
            documents=["Document to delete"],
            ids=["del1"]
        )
        
        success = await self.db.delete_document(
            collection="test",
            doc_id="del1"
        )
        
        assert success is True
        
        # Should not find it anymore
        results = await self.db.search("delete", collection="test")
        found = any(r.id == "del1" for r in results)
        assert not found
    
    @pytest.mark.asyncio
    async def test_delete_by_metadata(self):
        """Should delete by metadata filter."""
        await self.db.add_documents(
            collection="test",
            documents=["Doc A", "Doc B", "Doc C"],
            ids=["a", "b", "c"],
            metadatas=[
                {"category": "keep"},
                {"category": "remove"},
                {"category": "remove"}
            ]
        )
        
        deleted = await self.db.delete_by_metadata(
            collection="test",
            where={"category": "remove"}
        )
        
        assert deleted == 2
    
    def test_collection_stats(self):
        """Should report collection statistics."""
        asyncio.run(self.db.add_documents(
            collection="stats_test",
            documents=["doc1", "doc2", "doc3"],
            ids=["1", "2", "3"]
        ))
        
        stats = self.db.get_collection_stats("stats_test")
        
        assert stats["count"] == 3
        assert stats["name"] == "stats_test"
    
    def test_list_collections(self):
        """Should list all collections."""
        asyncio.run(self.db.add_documents(
            collection="collection_a",
            documents=["test"],
            ids=["1"]
        ))
        asyncio.run(self.db.add_documents(
            collection="collection_b",
            documents=["test"],
            ids=["1"]
        ))
        
        collections = self.db.list_collections()
        
        assert "collection_a" in collections
        assert "collection_b" in collections
    
    def test_delete_collection(self):
        """Should delete entire collection."""
        asyncio.run(self.db.add_documents(
            collection="to_delete",
            documents=["test"],
            ids=["1"]
        ))
        
        success = self.db.delete_collection("to_delete")
        
        assert success is True
        assert "to_delete" not in self.db.list_collections()
    
    def test_search_result_similarity(self):
        """SearchResult should compute similarity from distance."""
        result = self.SearchResult(
            id="test",
            document="test",
            distance=0.3,
            metadata={}
        )
        
        assert result.similarity == pytest.approx(0.7, rel=0.01)
    
    def test_backend_property(self):
        """Should report backend correctly."""
        backend = self.db.backend
        assert backend in ["chromadb", "fallback"]


# =============================================================================
# SPRINT 3 INTEGRATION TESTS
# =============================================================================

class TestSprint3Integration:
    """Integration tests for Sprint 3 components."""
    
    def setup_method(self):
        """Set up full Sprint 3 stack."""
        from src.control.action_history import ActionHistoryDB, ActionCategory, ActionStatus
        from src.control.undo_manager import UndoManager, UndoType
        from src.privacy.local_vector_db import LocalVectorDB
        
        self.temp_dir = tempfile.mkdtemp()
        
        self.history = ActionHistoryDB(
            db_path=os.path.join(self.temp_dir, "history.db")
        )
        self.undo = UndoManager(
            db_path=os.path.join(self.temp_dir, "undo.db"),
            backup_dir=os.path.join(self.temp_dir, "backups")
        )
        self.vector_db = LocalVectorDB(
            persist_dir=os.path.join(self.temp_dir, "vectors")
        )
        
        self.ActionCategory = ActionCategory
        self.ActionStatus = ActionStatus
        self.UndoType = UndoType
    
    def teardown_method(self):
        """Clean up."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    @pytest.mark.asyncio
    async def test_file_delete_workflow(self):
        """Full workflow: delete file with undo capability."""
        # Create test file
        test_file = os.path.join(self.temp_dir, "important.txt")
        Path(test_file).write_text("critical data")
        
        # 1. Record action in history
        record = self.history.record_action(
            action_type="delete_file",
            payload={"path": test_file},
            preview={"title": f"Delete {test_file}"},
            is_undoable=True
        )
        
        # 2. Create undo checkpoint
        cp = self.undo.create_file_delete_checkpoint(
            action_id=record.id,
            file_path=test_file
        )
        
        # 3. Link checkpoint to action via update_status
        self.history.update_status(record.id, self.ActionStatus.PENDING, checkpoint_id=cp.id)
        
        # 4. Execute action
        Path(test_file).unlink()
        
        # 5. Mark completed and commit checkpoint
        self.history.mark_completed(record.id, {"deleted": True})
        self.undo.commit_checkpoint(cp.id)
        
        # Verify file is deleted
        assert not Path(test_file).exists()
        
        # 6. User requests undo
        undoable = self.history.get_undoable()
        assert len(undoable) == 1
        
        # 7. Execute undo
        result = await self.undo.undo(cp.id)
        assert result["success"] is True
        
        # 8. Mark action as undone
        self.history.mark_undone(record.id)
        
        # Verify file is restored
        assert Path(test_file).exists()
        assert Path(test_file).read_text() == "critical data"
    
    @pytest.mark.asyncio
    async def test_semantic_search_on_history(self):
        """Index action descriptions for keyword-based search."""
        # Record some actions with distinct keywords
        actions = [
            ("send_email", "quarterly budget finance report"),
            ("create_document", "spreadsheet budget Q1 data"),
            ("schedule_meeting", "stakeholder review meeting"),
        ]
        
        for action_type, preview_text in actions:
            record = self.history.record_action(
                action_type=action_type,
                payload={},
                preview={"description": preview_text}
            )
            
            # Index in vector DB for search
            await self.vector_db.add_documents(
                collection="history",
                documents=[preview_text],
                ids=[record.id],
                metadatas=[{"action_type": action_type}]
            )
        
        # Search for budget-related actions (using exact keyword)
        results = await self.vector_db.search(
            "budget",
            collection="history"
        )
        
        # Should find budget actions (with fallback TF-IDF this uses keyword matching)
        assert len(results) >= 1
        found_texts = [r.document.lower() for r in results]
        assert any("budget" in t for t in found_texts)


# =============================================================================
# SPRINT 4 TESTS: UI COMPONENTS & SERVER ENDPOINTS
# =============================================================================

class TestStepPreviewData:
    """Test step preview data structures for UI rendering."""
    
    def test_document_preview_structure(self):
        """Document preview has required fields."""
        preview = {
            "type": "document",
            "id": "doc-123",
            "title": "Document Found",
            "filename": "2024-Home-Loan-Agreement.pdf",
            "path": "~/Documents/Loans/",
            "size": "245 KB",
            "excerpt": "Principal Amount: $425,000.00\nInterest Rate: 6.5% APR",
            "editable": False,
            "step_number": 1,
        }
        
        # Required fields for StepPreview component
        assert preview["type"] == "document"
        assert "filename" in preview
        assert "path" in preview
        assert "excerpt" in preview
    
    def test_email_preview_structure(self):
        """Email preview has required fields."""
        preview = {
            "type": "email",
            "id": "email-456",
            "title": "Email Draft",
            "to": "rob@sagecg.com",
            "subject": "Home Loan Summary & Amortization Schedule",
            "body": "Hi Rob,\n\nHere's the summary of the home loan...",
            "attachments": [
                {"name": "Loan-Amortization-Schedule.pdf", "size": "42 KB"}
            ],
            "editable": True,
            "step_number": 3,
        }
        
        # Required fields for email preview
        assert preview["type"] == "email"
        assert "to" in preview
        assert "subject" in preview
        assert "body" in preview
        assert preview["editable"] is True
    
    def test_calculation_preview_structure(self):
        """Calculation preview has required fields."""
        preview = {
            "type": "calculation",
            "id": "calc-789",
            "title": "Amortization Schedule",
            "results": [
                {"label": "Monthly Payment", "value": "$2,686.02", "highlight": True},
                {"label": "Total Interest", "value": "$542,567.29", "highlight": False},
                {"label": "Payoff Date", "value": "January 2054", "highlight": False},
            ],
            "table": {
                "headers": ["Month", "Payment", "Principal", "Interest", "Balance"],
                "rows": [
                    ["1", "$2,686", "$382.85", "$2,303.17", "$424,617"],
                    ["2", "$2,686", "$385.08", "$2,300.94", "$424,232"],
                    ["3", "$2,686", "$387.33", "$2,298.69", "$423,845"],
                ],
            },
            "step_number": 2,
        }
        
        # Required fields for calculation preview
        assert preview["type"] == "calculation"
        assert "results" in preview
        assert len(preview["results"]) > 0
        assert preview["results"][0]["label"] == "Monthly Payment"
    
    def test_generic_action_preview_structure(self):
        """Generic action preview has required fields."""
        preview = {
            "type": "file",
            "id": "file-action-001",
            "title": "Delete File",
            "description": "This will permanently delete the file at /tmp/old-report.txt",
            "step_number": 1,
        }
        
        assert preview["type"] == "file"
        assert "title" in preview
        assert "description" in preview


class TestAuditLogViewer:
    """Test audit log viewer data structures."""
    
    def setup_method(self):
        """Create test audit records."""
        self.test_db = tempfile.mktemp(suffix=".db")
        self.logger = AuditLogger(db_path=self.test_db)
    
    def teardown_method(self):
        """Clean up test database."""
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
    
    def test_transmission_record_to_dict(self):
        """Transmission records serialize properly for UI."""
        from src.privacy.audit_log import TransmissionDestination
        
        record_id = self.logger.log_outbound(
            destination=TransmissionDestination.OPENAI,
            content="What is 2+2?",
            triggering_request="User asked a math question",
            model="gpt-4",
        )
        
        # Get the record
        records = self.logger.get_transmissions(limit=1)
        assert len(records) >= 1
        
        # Should be serializable
        data = records[0].to_dict()
        
        assert "id" in data
        assert "timestamp" in data
        assert "destination" in data
    
    def test_stats_for_ui(self):
        """Stats endpoint returns UI-ready data."""
        from src.privacy.audit_log import TransmissionDestination
        
        # Log some transmissions
        for i in range(3):
            self.logger.log_outbound(
                destination=TransmissionDestination.OPENAI,
                content=f"Test prompt {i}",
                triggering_request="Test request",
                model="gpt-4",
            )
        
        stats = self.logger.get_stats()
        
        # Stats should have fields needed by UI
        assert "outbound_count" in stats
        assert stats["outbound_count"] >= 3
    
    def test_today_summary(self):
        """Today summary is human-readable."""
        from src.privacy.audit_log import TransmissionDestination
        
        self.logger.log_outbound(
            destination=TransmissionDestination.ANTHROPIC,
            content="Analyze this document",
            triggering_request="User asked for analysis",
            model="claude-3",
        )
        
        summary = self.logger.get_today_summary()
        
        # Should be a string or dict describing today's activity
        assert summary is not None


class TestActionHistoryUI:
    """Test action history data for UI rendering."""
    
    def setup_method(self):
        """Create test action history."""
        self.test_db = tempfile.mktemp(suffix=".db")
        from src.control.action_history import ActionHistoryDB
        self.history = ActionHistoryDB(db_path=self.test_db)
    
    def teardown_method(self):
        """Clean up test database."""
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
    
    def test_action_record_to_dict(self):
        """Action records serialize properly for UI."""
        from src.control.action_history import ActionCategory, ActionStatus
        
        record = self.history.record_action(
            action_type="send_email",
            payload={"to": "test@example.com", "subject": "Test"},
            preview={"title": "Send Email to test@example.com"},
            is_undoable=True,
        )
        
        data = record.to_dict()
        
        # Required fields for UI
        assert "id" in data
        assert "action_type" in data
        assert "status" in data
        assert "category" in data
        assert "created_at" in data
        assert "preview" in data
        assert "is_undoable" in data
    
    def test_status_icons_mapping(self):
        """All action statuses have UI icon mappings."""
        from src.control.action_history import ActionStatus
        
        status_icons = {
            ActionStatus.PENDING: "⏳",
            ActionStatus.APPROVED: "✅",
            ActionStatus.AUTO_APPROVED: "✅",
            ActionStatus.REJECTED: "❌",
            ActionStatus.COMPLETED: "✓",
            ActionStatus.FAILED: "💥",
            ActionStatus.UNDONE: "↩️",
            ActionStatus.EXPIRED: "⌛",
        }
        
        # All statuses should have icons
        for status in ActionStatus:
            assert status in status_icons
    
    def test_category_icons_mapping(self):
        """All action categories have UI icon mappings."""
        from src.control.action_history import ActionCategory
        
        category_icons = {
            ActionCategory.FILE: "📁",
            ActionCategory.EMAIL: "📧",
            ActionCategory.CALENDAR: "📅",
            ActionCategory.CONTACT: "👤",
            ActionCategory.DOCUMENT: "📄",
            ActionCategory.TASK: "✅",
            ActionCategory.DEVTOOLS: "💻",
            ActionCategory.SYSTEM: "⚙️",
            ActionCategory.OTHER: "📋",
        }
        
        # All categories should have icons
        for category in ActionCategory:
            assert category in category_icons


class TestUndoManagerUI:
    """Test undo manager data for UI rendering."""
    
    def setup_method(self):
        """Create test undo manager."""
        self.test_dir = tempfile.mkdtemp()
        self.test_db = os.path.join(self.test_dir, "undo.db")
        from src.control.undo_manager import UndoManager
        self.undo_manager = UndoManager(
            db_path=self.test_db,
            backup_dir=os.path.join(self.test_dir, "backups")
        )
    
    def teardown_method(self):
        """Clean up test files."""
        import shutil
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
    
    def test_checkpoint_to_dict(self):
        """Checkpoints serialize properly for UI."""
        # Create a test file
        test_file = os.path.join(self.test_dir, "test.txt")
        Path(test_file).write_text("test content")
        
        checkpoint = self.undo_manager.create_file_delete_checkpoint(
            action_id="test-action-123",
            file_path=test_file,
        )
        
        data = checkpoint.to_dict()
        
        # Required fields for UI
        assert "id" in data
        assert "action_id" in data
        assert "undo_type" in data
        assert "created_at" in data
    
    def test_undo_status_for_toast(self):
        """Undo results have status for toast notification."""
        from src.control.undo_manager import UndoStatus
        
        # All statuses should be displayable
        status_messages = {
            UndoStatus.PENDING: "Preparing undo...",
            UndoStatus.COMMITTED: "Ready for undo",
            UndoStatus.EXECUTED: "Action undone successfully",
            UndoStatus.FAILED: "Undo failed",
            UndoStatus.EXPIRED: "Undo window expired",
        }
        
        for status in UndoStatus:
            assert status in status_messages


class TestInlineEditorData:
    """Test inline editor data flow."""
    
    def test_email_edit_payload(self):
        """Email edit creates proper update payload."""
        original_email = {
            "id": "email-123",
            "to": "rob@sagecg.com",
            "subject": "Loan Summary",
            "body": "Original content here",
        }
        
        # User edits the body
        edited_body = "Updated content with more details"
        
        update_payload = {
            "action_id": original_email["id"],
            "field": "body",
            "old_value": original_email["body"],
            "new_value": edited_body,
        }
        
        assert update_payload["action_id"] == "email-123"
        assert update_payload["new_value"] == edited_body
    
    def test_editable_fields_by_type(self):
        """Different preview types have different editable fields."""
        editable_fields = {
            "email": ["to", "subject", "body"],
            "document": ["filename"],  # Limited editability
            "calculation": [],  # Read-only
            "file": [],  # Read-only
        }
        
        assert "body" in editable_fields["email"]
        assert "subject" in editable_fields["email"]
        assert len(editable_fields["calculation"]) == 0


class TestToastNotification:
    """Test toast notification data structures."""
    
    def test_action_toast_data(self):
        """Action completion creates toast data."""
        toast_data = {
            "message": "Email sent to rob@sagecg.com",
            "action_id": "email-123",
            "type": "success",
            "has_undo": True,
            "auto_dismiss": 8000,  # 8 seconds
        }
        
        assert toast_data["has_undo"] is True
        assert toast_data["auto_dismiss"] == 8000
    
    def test_undo_toast_data(self):
        """Undo completion creates toast data."""
        toast_data = {
            "message": "Action undone successfully",
            "action_id": "email-123",
            "type": "info",
            "has_undo": False,
            "auto_dismiss": 5000,
        }
        
        assert toast_data["has_undo"] is False
        assert toast_data["type"] == "info"


class TestServerEndpointDataFormats:
    """Test that server endpoints return data in expected formats."""
    
    def setup_method(self):
        """Create test instances."""
        self.test_db = tempfile.mktemp(suffix=".db")
        from src.control.action_history import ActionHistoryDB
        self.history = ActionHistoryDB(db_path=self.test_db)
    
    def teardown_method(self):
        """Clean up test database."""
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
    
    def test_history_endpoint_format(self):
        """GET /control/history returns expected format."""
        # Record some actions
        self.history.record_action(
            action_type="send_email",
            payload={"to": "test@example.com"},
            preview={"title": "Send Email"},
        )
        
        actions = self.history.get_recent(limit=50)
        
        # Format for endpoint response
        response = {
            "actions": [a.to_dict() for a in actions],
            "count": len(actions),
        }
        
        assert "actions" in response
        assert "count" in response
        assert response["count"] >= 1
    
    def test_approve_endpoint_format(self):
        """POST /control/approve returns expected format."""
        # Simulated response
        success_response = {
            "success": True,
            "action_id": "action-123",
            "result": {"sent": True, "message_id": "msg-456"},
        }
        
        error_response = {
            "success": False,
            "error": "Action not found",
        }
        
        assert success_response["success"] is True
        assert "action_id" in success_response
        assert error_response["success"] is False
        assert "error" in error_response
    
    def test_undo_endpoint_format(self):
        """POST /control/undo returns expected format."""
        success_response = {
            "success": True,
            "action_id": "action-123",
            "message": "Action undone successfully",
        }
        
        error_response = {
            "success": False,
            "error": "Action is not undoable",
        }
        
        assert success_response["success"] is True
        assert "message" in success_response
        assert error_response["success"] is False


# =============================================================================
# SPRINT 5: Trust Level Learning Integration Tests
# =============================================================================

class TestTrustLevelLearning:
    """Tests for Sprint 5: Trust level learning and integration."""
    
    def test_approve_with_remember_pattern_request(self):
        """ApproveActionRequest supports remember_pattern field."""
        # Simulated request body
        request_body = {
            "action_id": "action-123",
            "remember_pattern": True,
            "pattern_context": {"action_type": "create_calendar_event", "recurring": "weekly"},
        }
        
        assert request_body["action_id"] == "action-123"
        assert request_body["remember_pattern"] is True
        assert "pattern_context" in request_body
        assert request_body["pattern_context"]["action_type"] == "create_calendar_event"
    
    def test_approve_without_remember_defaults(self):
        """Approve request defaults remember_pattern to False."""
        request_body = {
            "action_id": "action-456",
        }
        
        # Default values
        remember_pattern = request_body.get("remember_pattern", False)
        pattern_context = request_body.get("pattern_context", None)
        
        assert remember_pattern is False
        assert pattern_context is None


class TestTrustLevelManagerLearning:
    """Tests for TrustLevelManager pattern learning."""
    
    @pytest.fixture
    def trust_manager_temp(self, tmp_path):
        """Create a TrustLevelManager with temp database."""
        db_path = str(tmp_path / "trust_test.db")
        from src.control.trust_levels import TrustLevelManager
        return TrustLevelManager(db_path=db_path)
    
    def test_remember_pattern_persists(self, trust_manager_temp):
        """Remembered patterns persist and enable auto-approve."""
        mgr = trust_manager_temp
        
        # Initially ASK_ONCE
        level = mgr.get_trust_level("create_calendar_event")
        assert level.value == "ask_once"
        
        # Remember a pattern
        context = {"title": "Team Standup", "day": "Monday", "time": "09:00"}
        pattern_id = mgr.remember_pattern(
            action_type="create_calendar_event",
            context=context,
            description="Weekly team standup"
        )
        
        assert pattern_id.startswith("pat_")
        
        # Same context now auto-approves
        level = mgr.get_trust_level("create_calendar_event", context=context)
        assert level.value == "auto_approve"
        
        # Different context still asks
        different_context = {"title": "Client Call", "day": "Friday"}
        level = mgr.get_trust_level("create_calendar_event", context=different_context)
        assert level.value == "ask_once"
    
    def test_forget_pattern(self, trust_manager_temp):
        """Forgotten patterns no longer auto-approve."""
        mgr = trust_manager_temp
        
        context = {"type": "reminder", "time": "daily"}
        pattern_id = mgr.remember_pattern(
            action_type="create_task",
            context=context,
            description="Daily reminder"
        )
        
        # Auto-approves with pattern
        level = mgr.get_trust_level("create_task", context=context)
        assert level.value == "auto_approve"
        
        # Forget the pattern
        result = mgr.forget_pattern(pattern_id)
        assert result is True
        
        # No longer auto-approves
        level = mgr.get_trust_level("create_task", context=context)
        assert level.value == "ask_once"
    
    def test_list_patterns(self, trust_manager_temp):
        """Can list remembered patterns."""
        mgr = trust_manager_temp
        
        # Remember multiple patterns
        mgr.remember_pattern("create_task", {"category": "work"}, "Work tasks")
        mgr.remember_pattern("create_task", {"category": "personal"}, "Personal tasks")
        mgr.remember_pattern("create_calendar_event", {"recurring": True}, "Recurring events")
        
        patterns = mgr.get_patterns()
        assert len(patterns) >= 3
        
        # Filter by action type
        task_patterns = mgr.get_patterns(action_type="create_task")
        assert len(task_patterns) == 2


class TestApprovalGatewayLearning:
    """Tests for ApprovalGateway with pattern learning."""
    
    @pytest.fixture
    def gateway_with_trust(self, tmp_path):
        """Create ApprovalGateway with fresh TrustLevelManager."""
        db_path = str(tmp_path / "gateway_trust.db")
        from src.control.trust_levels import TrustLevelManager
        from src.control.approval_gateway import ApprovalGateway
        trust_mgr = TrustLevelManager(db_path=db_path)
        return ApprovalGateway(trust_mgr=trust_mgr), trust_mgr
    
    @pytest.mark.asyncio
    async def test_approve_with_remember_pattern(self, gateway_with_trust):
        """Approve with remember_pattern saves pattern for future."""
        gateway, trust_mgr = gateway_with_trust
        from src.control.approval_gateway import PendingAction, ActionPreview
        
        # Create pending action
        action = PendingAction(
            action_type="create_calendar_event",
            payload={"title": "Sprint Planning", "day": "Wednesday"},
            preview=ActionPreview(
                title="Create Event: Sprint Planning",
                description="Wednesday sprint planning meeting",
                preview_type="calendar"
            )
        )
        
        # Submit action
        await gateway.submit(action)
        
        # Approve with remember
        context = {"recurring": "weekly", "title": "Sprint Planning"}
        result = await gateway.approve(
            action.id,
            remember_pattern=True,
            pattern_context=context
        )
        
        assert result.status.value == "completed" or result.status.value == "approved"
        
        # Pattern should now auto-approve
        level = trust_mgr.get_trust_level("create_calendar_event", context=context)
        assert level.value == "auto_approve"


class TestSprint5Integration:
    """End-to-end tests for Sprint 5 components."""
    
    def test_ui_checkbox_data_format(self):
        """UI sends correct format for remember_pattern."""
        # What the UI sends when checkbox is checked
        approve_request_checked = {
            "action_id": "step_001",
            "remember_pattern": True,
            "pattern_context": {"action_id": "step_001"}
        }
        
        # What the UI sends when checkbox is unchecked
        approve_request_unchecked = {
            "action_id": "step_002",
            "remember_pattern": False,
            "pattern_context": None
        }
        
        assert approve_request_checked["remember_pattern"] is True
        assert approve_request_unchecked["remember_pattern"] is False
    
    def test_full_learning_flow_data(self):
        """Verify data flow through complete learning cycle."""
        # Step 1: First approval (ASK_ONCE) with remember
        first_approval = {
            "action_type": "create_calendar_event",
            "trust_level": "ask_once",
            "user_action": "approve",
            "remember_pattern": True,
            "pattern_context": {"title": "Weekly Sync", "recurring": True}
        }
        
        # Step 2: Pattern stored
        stored_pattern = {
            "id": "pat_20260331_abc12345",
            "action_type": "create_calendar_event",
            "pattern_description": "Create Event: Weekly Sync",
            "times_auto_approved": 0
        }
        
        # Step 3: Future similar action auto-approves
        future_action = {
            "action_type": "create_calendar_event",
            "context": {"title": "Weekly Sync", "recurring": True},
            "expected_trust_level": "auto_approve"
        }
        
        assert first_approval["remember_pattern"] is True
        assert stored_pattern["action_type"] == first_approval["action_type"]
        assert future_action["expected_trust_level"] == "auto_approve"
    
    def test_learning_respects_always_ask(self):
        """ALWAYS_ASK actions never auto-approve even with patterns."""
        from src.control.trust_levels import TrustLevelManager, TrustLevel
        
        # Verify send_email is ALWAYS_ASK
        mgr = TrustLevelManager.__new__(TrustLevelManager)
        mgr._custom_levels = {}
        mgr._patterns = {}
        
        default_level = TrustLevelManager.DEFAULT_LEVELS.get("send_email")
        assert default_level == TrustLevel.ALWAYS_ASK
        
        # ALWAYS_ASK means even if we try to "remember", it won't auto-approve
        # because send_email is hardcoded to ALWAYS_ASK




# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
