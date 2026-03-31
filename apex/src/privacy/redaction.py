"""
RedactionEngine - Strip PII before external transmission.

Detects and redacts:
- Social Security Numbers (XXX-XX-XXXX)
- Credit card numbers (16 digits with various separators)
- Bank account numbers (9-17 digits)
- Phone numbers (optional, configurable)
- Email addresses (optional, configurable)
- Custom patterns (user-defined)

Redacted values are replaced with tokens like [SSN_REDACTED_1]
that maintain text structure while removing sensitive data.

The original values are stored in a secure map that can be used
to restore them after LLM processing if absolutely needed
(but this should be rare - most use cases don't need restoration).
"""

import re
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple, Set
import logging

logger = logging.getLogger(__name__)


class PIIType(Enum):
    """Types of personally identifiable information."""
    SSN = "ssn"                      # Social Security Number
    CREDIT_CARD = "credit_card"      # Credit/debit card numbers
    BANK_ACCOUNT = "bank_account"    # Bank account numbers
    PHONE = "phone"                  # Phone numbers
    EMAIL = "email"                  # Email addresses
    IP_ADDRESS = "ip_address"        # IP addresses
    DATE_OF_BIRTH = "dob"            # Dates that look like DOBs
    DRIVERS_LICENSE = "drivers_license"
    PASSPORT = "passport"
    CUSTOM = "custom"                # User-defined patterns


@dataclass
class RedactionResult:
    """Result of a redaction operation."""
    original_text: str
    redacted_text: str
    redaction_count: int
    redactions: List[Dict]  # List of {type, original, replacement, position}
    had_pii: bool
    
    def to_dict(self) -> Dict:
        return {
            "redaction_count": self.redaction_count,
            "had_pii": self.had_pii,
            "types_found": list(set(r["type"] for r in self.redactions)),
        }


@dataclass
class RedactionPattern:
    """A pattern for detecting PII."""
    pii_type: PIIType
    pattern: re.Pattern
    replacement_template: str  # e.g., "[SSN_REDACTED_{n}]"
    description: str
    enabled: bool = True
    
    # Validation function (optional) - returns True if match is valid
    validator: Optional[callable] = None


class RedactionEngine:
    """
    Redacts PII from text before external transmission.
    
    Usage:
        engine = RedactionEngine()
        
        # Basic redaction
        text = "My SSN is 123-45-6789 and my card is 4111-1111-1111-1111"
        result = engine.redact(text)
        print(result.redacted_text)
        # "My SSN is [SSN_REDACTED_1] and my card is [CARD_REDACTED_1]"
        
        # Check what was found
        print(result.redaction_count)  # 2
        print(result.had_pii)  # True
        
        # Optional: restore (use with caution!)
        restored = engine.restore(result.redacted_text)
        # Only works within same session - map is not persisted for security
    
    Security note:
        The restoration map is kept in memory only and never persisted.
        This is intentional - redacted data should stay redacted.
        If you need the original, you should have it from the source.
    """
    
    def __init__(self, strict_mode: bool = True):
        """
        Initialize the redaction engine.
        
        Args:
            strict_mode: If True, be aggressive about detecting potential PII.
                        If False, only match high-confidence patterns.
        """
        self._strict_mode = strict_mode
        self._patterns: List[RedactionPattern] = []
        self._redaction_map: Dict[str, str] = {}  # token -> original (in-memory only!)
        self._redaction_counter: Dict[PIIType, int] = {}
        self._stats = {
            "total_redactions": 0,
            "by_type": {},
        }
        
        self._setup_default_patterns()
        logger.info(f"RedactionEngine initialized (strict_mode={strict_mode})")
    
    def _setup_default_patterns(self):
        """Setup default PII detection patterns."""
        
        # Social Security Number: XXX-XX-XXXX or XXXXXXXXX
        self._patterns.append(RedactionPattern(
            pii_type=PIIType.SSN,
            pattern=re.compile(
                r'\b(\d{3}[-\s]?\d{2}[-\s]?\d{4})\b'
            ),
            replacement_template="[SSN_REDACTED_{n}]",
            description="Social Security Number",
            validator=self._validate_ssn,
        ))
        
        # Credit Card Numbers (13-19 digits with optional separators)
        # Covers Visa, Mastercard, Amex, Discover, etc.
        self._patterns.append(RedactionPattern(
            pii_type=PIIType.CREDIT_CARD,
            pattern=re.compile(
                r'\b(\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{1,4})\b'
            ),
            replacement_template="[CARD_REDACTED_{n}]",
            description="Credit/Debit Card Number",
            validator=self._validate_credit_card,
        ))
        
        # Also match 16 consecutive digits
        self._patterns.append(RedactionPattern(
            pii_type=PIIType.CREDIT_CARD,
            pattern=re.compile(r'\b(\d{15,16})\b'),
            replacement_template="[CARD_REDACTED_{n}]",
            description="Credit/Debit Card Number (no separators)",
            validator=self._validate_credit_card,
        ))
        
        # Bank Account Numbers (typically 9-17 digits)
        # This is tricky because many numbers could be accounts
        # We look for context clues
        self._patterns.append(RedactionPattern(
            pii_type=PIIType.BANK_ACCOUNT,
            pattern=re.compile(
                r'(?i)(?:account|acct|routing|aba)[:\s#]*(\d{9,17})\b'
            ),
            replacement_template="[ACCOUNT_REDACTED_{n}]",
            description="Bank Account/Routing Number",
        ))
        
        # Phone numbers (US format)
        self._patterns.append(RedactionPattern(
            pii_type=PIIType.PHONE,
            pattern=re.compile(
                r'\b(\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})\b'
            ),
            replacement_template="[PHONE_REDACTED_{n}]",
            description="Phone Number",
            enabled=self._strict_mode,  # Only in strict mode
        ))
        
        # Email addresses (optional - sometimes needed for context)
        self._patterns.append(RedactionPattern(
            pii_type=PIIType.EMAIL,
            pattern=re.compile(
                r'\b([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b'
            ),
            replacement_template="[EMAIL_REDACTED_{n}]",
            description="Email Address",
            enabled=False,  # Disabled by default - often needed for context
        ))
        
        # IP Addresses
        self._patterns.append(RedactionPattern(
            pii_type=PIIType.IP_ADDRESS,
            pattern=re.compile(
                r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b'
            ),
            replacement_template="[IP_REDACTED_{n}]",
            description="IP Address",
            validator=self._validate_ip,
            enabled=self._strict_mode,
        ))
    
    def _validate_ssn(self, match: str) -> bool:
        """Validate that a match looks like a real SSN."""
        # Remove separators
        digits = re.sub(r'[-\s]', '', match)
        
        if len(digits) != 9:
            return False
        
        # SSNs can't start with 000, 666, or 9xx
        area = int(digits[:3])
        if area == 0 or area == 666 or area >= 900:
            return False
        
        # Group can't be 00
        group = int(digits[3:5])
        if group == 0:
            return False
        
        # Serial can't be 0000
        serial = int(digits[5:])
        if serial == 0:
            return False
        
        return True
    
    def _validate_credit_card(self, match: str) -> bool:
        """Validate using Luhn algorithm (checksum for credit cards)."""
        # Remove separators
        digits = re.sub(r'[-\s]', '', match)
        
        if not digits.isdigit():
            return False
        
        if len(digits) < 13 or len(digits) > 19:
            return False
        
        # Luhn algorithm
        total = 0
        reverse_digits = digits[::-1]
        
        for i, digit in enumerate(reverse_digits):
            n = int(digit)
            if i % 2 == 1:
                n *= 2
                if n > 9:
                    n -= 9
            total += n
        
        return total % 10 == 0
    
    def _validate_ip(self, match: str) -> bool:
        """Validate IP address."""
        parts = match.split('.')
        if len(parts) != 4:
            return False
        
        for part in parts:
            try:
                num = int(part)
                if num < 0 or num > 255:
                    return False
            except ValueError:
                return False
        
        return True
    
    def redact(self, text: str) -> RedactionResult:
        """
        Redact all PII from text.
        
        Args:
            text: The text to redact
            
        Returns:
            RedactionResult with redacted text and metadata
        """
        if not text:
            return RedactionResult(
                original_text="",
                redacted_text="",
                redaction_count=0,
                redactions=[],
                had_pii=False,
            )
        
        redacted_text = text
        redactions = []
        
        for pattern in self._patterns:
            if not pattern.enabled:
                continue
            
            # Find all matches
            matches = list(pattern.pattern.finditer(redacted_text))
            
            # Process in reverse order to maintain positions
            for match in reversed(matches):
                matched_text = match.group(1) if match.groups() else match.group(0)
                
                # Validate if validator exists
                if pattern.validator and not pattern.validator(matched_text):
                    continue
                
                # Generate replacement token
                counter = self._redaction_counter.get(pattern.pii_type, 0) + 1
                self._redaction_counter[pattern.pii_type] = counter
                
                replacement = pattern.replacement_template.format(n=counter)
                
                # Store mapping for potential restoration (in-memory only!)
                self._redaction_map[replacement] = matched_text
                
                # Record the redaction
                redactions.append({
                    "type": pattern.pii_type.value,
                    "original_preview": matched_text[:4] + "***",  # Show first 4 chars only
                    "replacement": replacement,
                    "position": match.start(),
                })
                
                # Replace in text
                start, end = match.span()
                redacted_text = redacted_text[:start] + replacement + redacted_text[end:]
        
        # Update stats
        self._stats["total_redactions"] += len(redactions)
        for r in redactions:
            pii_type = r["type"]
            self._stats["by_type"][pii_type] = self._stats["by_type"].get(pii_type, 0) + 1
        
        result = RedactionResult(
            original_text=text,
            redacted_text=redacted_text,
            redaction_count=len(redactions),
            redactions=redactions,
            had_pii=len(redactions) > 0,
        )
        
        if result.had_pii:
            logger.info(f"Redacted {result.redaction_count} PII items: {[r['type'] for r in redactions]}")
        
        return result
    
    def restore(self, redacted_text: str) -> str:
        """
        Restore redacted values (use with extreme caution!).
        
        This only works within the same session - the mapping
        is intentionally not persisted for security.
        
        Args:
            redacted_text: Text with redaction tokens
            
        Returns:
            Text with original values restored
        """
        restored = redacted_text
        
        for token, original in self._redaction_map.items():
            restored = restored.replace(token, original)
        
        return restored
    
    def enable_pattern(self, pii_type: PIIType, enabled: bool = True):
        """Enable or disable a PII pattern type."""
        for pattern in self._patterns:
            if pattern.pii_type == pii_type:
                pattern.enabled = enabled
                logger.info(f"Pattern {pii_type.value} {'enabled' if enabled else 'disabled'}")
    
    def add_custom_pattern(
        self,
        pattern_regex: str,
        replacement: str,
        description: str = "Custom pattern",
    ):
        """
        Add a custom redaction pattern.
        
        Args:
            pattern_regex: Regular expression to match
            replacement: Replacement template (use {n} for counter)
            description: Human-readable description
        """
        self._patterns.append(RedactionPattern(
            pii_type=PIIType.CUSTOM,
            pattern=re.compile(pattern_regex),
            replacement_template=replacement,
            description=description,
        ))
        logger.info(f"Added custom pattern: {description}")
    
    def get_stats(self) -> Dict:
        """Get redaction statistics."""
        return {
            "total_redactions": self._stats["total_redactions"],
            "by_type": dict(self._stats["by_type"]),
            "patterns_enabled": sum(1 for p in self._patterns if p.enabled),
            "patterns_total": len(self._patterns),
        }
    
    def clear_session(self):
        """
        Clear the in-memory restoration map.
        
        Call this at the end of a workflow to ensure no sensitive
        data lingers in memory.
        """
        self._redaction_map.clear()
        logger.debug("Redaction session cleared")


# Global instance for convenience
redaction_engine = RedactionEngine()
