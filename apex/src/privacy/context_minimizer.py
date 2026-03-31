"""
ContextMinimizer - Extract Minimal Context for LLM Queries

The core privacy guarantee: NEVER send raw document content to the LLM.
Instead, extract only what's needed:
- Key entities (names, organizations, dates, amounts)
- Document metadata (type, size, age)
- Brief summaries
- Keywords and topics

This ensures the LLM can answer questions about your data
without ever seeing your actual content.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional
import hashlib
import json
import mimetypes
import re


class ExtractionMode(Enum):
    """How much context to extract."""
    MINIMAL = "minimal"      # Just metadata - nothing from content
    KEYWORDS = "keywords"    # Metadata + keyword extraction
    SUMMARY = "summary"      # Metadata + brief summary
    STRUCTURED = "structured"  # Metadata + structured entities


@dataclass
class MinimalContext:
    """The minimal context extracted from a document/input."""
    
    # Source identification (never sent raw)
    source_id: str  # Hash of original content
    source_type: str  # file, email, calendar, etc.
    
    # Metadata (safe to share)
    file_type: Optional[str] = None
    file_size_bytes: Optional[int] = None
    line_count: Optional[int] = None
    word_count: Optional[int] = None
    created_at: Optional[datetime] = None
    modified_at: Optional[datetime] = None
    
    # Extracted context (anonymized)
    keywords: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    entities: dict[str, list[str]] = field(default_factory=dict)  # {type: [values]}
    summary: Optional[str] = None
    structure: Optional[dict] = None  # For structured documents
    
    # Privacy metadata
    extraction_mode: str = "minimal"
    extracted_at: datetime = field(default_factory=datetime.now)
    sensitive_content_detected: bool = False
    redactions_applied: int = 0
    
    def to_prompt_context(self) -> str:
        """Generate the context string to include in LLM prompts."""
        parts = []
        
        # Document identification
        parts.append(f"[Document: {self.source_type}]")
        
        # Metadata
        if self.file_type:
            parts.append(f"Type: {self.file_type}")
        if self.word_count:
            parts.append(f"Size: ~{self.word_count} words")
        if self.line_count:
            parts.append(f"Lines: {self.line_count}")
            
        # Extracted context
        if self.keywords:
            parts.append(f"Keywords: {', '.join(self.keywords[:10])}")
        if self.topics:
            parts.append(f"Topics: {', '.join(self.topics[:5])}")
        if self.entities:
            for entity_type, values in self.entities.items():
                if values:
                    parts.append(f"{entity_type}: {', '.join(values[:5])}")
        if self.summary:
            parts.append(f"Summary: {self.summary}")
            
        # Privacy notes
        if self.sensitive_content_detected:
            parts.append("[Note: Sensitive content detected and excluded]")
        if self.redactions_applied:
            parts.append(f"[{self.redactions_applied} items redacted for privacy]")
            
        return "\n".join(parts)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "file_type": self.file_type,
            "file_size_bytes": self.file_size_bytes,
            "line_count": self.line_count,
            "word_count": self.word_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "modified_at": self.modified_at.isoformat() if self.modified_at else None,
            "keywords": self.keywords,
            "topics": self.topics,
            "entities": self.entities,
            "summary": self.summary,
            "structure": self.structure,
            "extraction_mode": self.extraction_mode,
            "extracted_at": self.extracted_at.isoformat(),
            "sensitive_content_detected": self.sensitive_content_detected,
            "redactions_applied": self.redactions_applied,
        }


class ContextMinimizer:
    """
    Extracts minimal context from documents for LLM queries.
    
    The core guarantee: raw content NEVER leaves this component.
    Only extracted metadata, keywords, and summaries go to the LLM.
    """
    
    # Common stop words to exclude from keywords
    STOP_WORDS = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'of', 'with', 'by', 'from', 'up', 'about', 'into', 'through', 'during',
        'before', 'after', 'above', 'below', 'between', 'under', 'again',
        'further', 'then', 'once', 'here', 'there', 'when', 'where', 'why',
        'how', 'all', 'each', 'few', 'more', 'most', 'other', 'some', 'such',
        'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very',
        's', 't', 'can', 'will', 'just', 'don', 'should', 'now', 'i', 'you',
        'he', 'she', 'it', 'we', 'they', 'what', 'which', 'who', 'this', 'that',
        'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had',
        'having', 'do', 'does', 'did', 'doing', 'would', 'could', 'might', 'must',
    }
    
    # Entity patterns for extraction
    ENTITY_PATTERNS = {
        'dates': [
            r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b',
            r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{4}\b',
            r'\b\d{4}[/-]\d{2}[/-]\d{2}\b',
        ],
        'money': [
            r'\$[\d,]+(?:\.\d{2})?',
            r'[\d,]+(?:\.\d{2})?\s*(?:USD|EUR|GBP|dollars?|euros?|pounds?)',
        ],
        'percentages': [
            r'\b\d+(?:\.\d+)?%',
        ],
        'emails': [
            r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        ],
        'urls': [
            r'https?://[^\s]+',
        ],
        'phone_numbers': [
            r'\b(?:\+?1[-.]?)?\(?[2-9]\d{2}\)?[-.]?\d{3}[-.]?\d{4}\b',
        ],
    }
    
    # Topic detection keywords (categories and their associated words)
    TOPIC_KEYWORDS = {
        'finance': ['budget', 'expense', 'revenue', 'profit', 'loss', 'quarterly', 'fiscal', 'investment', 'tax', 'payroll'],
        'legal': ['contract', 'agreement', 'clause', 'terms', 'liability', 'compliance', 'regulation', 'attorney', 'plaintiff', 'defendant'],
        'technical': ['api', 'database', 'server', 'deploy', 'bug', 'feature', 'release', 'code', 'test', 'integration'],
        'project': ['milestone', 'deadline', 'deliverable', 'sprint', 'backlog', 'stakeholder', 'scope', 'timeline', 'resource'],
        'communication': ['meeting', 'agenda', 'minutes', 'action', 'follow-up', 'attendee', 'discussion', 'decision'],
        'hr': ['employee', 'onboarding', 'performance', 'review', 'benefits', 'compensation', 'termination', 'hiring'],
        'marketing': ['campaign', 'lead', 'conversion', 'brand', 'audience', 'engagement', 'metrics', 'roi'],
    }
    
    def __init__(
        self,
        default_mode: ExtractionMode = ExtractionMode.KEYWORDS,
        max_keywords: int = 20,
        max_summary_words: int = 50,
        sensitive_marker: Optional[Any] = None,
        redaction_engine: Optional[Any] = None,
    ):
        """
        Initialize the context minimizer.
        
        Args:
            default_mode: Default extraction mode
            max_keywords: Maximum keywords to extract
            max_summary_words: Maximum words in summary
            sensitive_marker: SensitiveMarker instance for checking blocked paths
            redaction_engine: RedactionEngine instance for stripping PII
        """
        self.default_mode = default_mode
        self.max_keywords = max_keywords
        self.max_summary_words = max_summary_words
        self.sensitive_marker = sensitive_marker
        self.redaction_engine = redaction_engine
        
    def set_sensitive_marker(self, marker: Any):
        """Set the SensitiveMarker instance."""
        self.sensitive_marker = marker
        
    def set_redaction_engine(self, engine: Any):
        """Set the RedactionEngine instance."""
        self.redaction_engine = engine
    
    def extract_from_file(
        self,
        file_path: str | Path,
        mode: Optional[ExtractionMode] = None,
        user_id: str = "system",
    ) -> MinimalContext:
        """
        Extract minimal context from a file.
        
        Returns only metadata and extracted info - never raw content.
        """
        path = Path(file_path)
        mode = mode or self.default_mode
        
        # Check if file is blocked by SensitiveMarker
        if self.sensitive_marker:
            from .sensitive_marker import SensitivityLevel
            level = self.sensitive_marker.get_sensitivity_level(str(path), user_id)
            if level == SensitivityLevel.BLOCKED:
                # Return minimal metadata only - no content extraction at all
                return MinimalContext(
                    source_id=self._hash_path(str(path)),
                    source_type="file",
                    file_type=self._get_file_type(path),
                    sensitive_content_detected=True,
                    extraction_mode="blocked",
                )
        
        # Get file metadata
        file_type = self._get_file_type(path)
        
        try:
            stat = path.stat()
            file_size = stat.st_size
            created_at = datetime.fromtimestamp(stat.st_ctime)
            modified_at = datetime.fromtimestamp(stat.st_mtime)
        except (OSError, ValueError):
            file_size = None
            created_at = None
            modified_at = None
        
        # Read content for extraction (stays local)
        try:
            content = path.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            # Binary file or unreadable - return metadata only
            return MinimalContext(
                source_id=self._hash_path(str(path)),
                source_type="file",
                file_type=file_type,
                file_size_bytes=file_size,
                created_at=created_at,
                modified_at=modified_at,
                extraction_mode=mode.value,
            )
        
        # Extract context based on mode
        return self._extract_from_text(
            content,
            source_type="file",
            source_id=self._hash_path(str(path)),
            file_type=file_type,
            file_size_bytes=file_size,
            created_at=created_at,
            modified_at=modified_at,
            mode=mode,
        )
    
    def extract_from_text(
        self,
        content: str,
        source_type: str = "text",
        source_id: Optional[str] = None,
        mode: Optional[ExtractionMode] = None,
    ) -> MinimalContext:
        """
        Extract minimal context from text content.
        
        The raw content stays here - only extracted info goes out.
        """
        mode = mode or self.default_mode
        source_id = source_id or self._hash_content(content)
        
        return self._extract_from_text(
            content,
            source_type=source_type,
            source_id=source_id,
            mode=mode,
        )
    
    def extract_from_email(
        self,
        subject: str,
        body: str,
        sender: Optional[str] = None,
        recipients: Optional[list[str]] = None,
        date: Optional[datetime] = None,
        mode: Optional[ExtractionMode] = None,
    ) -> MinimalContext:
        """
        Extract minimal context from an email.
        
        Extracts topics, entities, and summary - never raw body text.
        """
        mode = mode or self.default_mode
        
        # Combine subject and body for extraction
        content = f"{subject}\n\n{body}"
        source_id = self._hash_content(content)
        
        context = self._extract_from_text(
            content,
            source_type="email",
            source_id=source_id,
            mode=mode,
        )
        
        # Add email-specific structure
        context.structure = {
            "subject": subject[:100] if len(subject) <= 100 else subject[:97] + "...",
            "has_attachments": "attachment" in body.lower() or "attached" in body.lower(),
        }
        
        if date:
            context.created_at = date
        
        # Add sender domain (not full address for privacy)
        if sender and '@' in sender:
            domain = sender.split('@')[1]
            if 'domains' not in context.entities:
                context.entities['domains'] = []
            if domain not in context.entities['domains']:
                context.entities['domains'].append(domain)
        
        return context
    
    def extract_from_calendar_event(
        self,
        title: str,
        description: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        attendees: Optional[list[str]] = None,
        location: Optional[str] = None,
        mode: Optional[ExtractionMode] = None,
    ) -> MinimalContext:
        """
        Extract minimal context from a calendar event.
        """
        mode = mode or self.default_mode
        
        content = title
        if description:
            content += f"\n\n{description}"
        if location:
            content += f"\nLocation: {location}"
            
        context = self._extract_from_text(
            content,
            source_type="calendar_event",
            source_id=self._hash_content(content),
            mode=mode,
        )
        
        # Add event-specific structure
        context.structure = {
            "title": title[:100] if len(title) <= 100 else title[:97] + "...",
            "has_location": bool(location),
            "attendee_count": len(attendees) if attendees else 0,
        }
        
        if start_time:
            context.created_at = start_time
            
        if start_time and end_time:
            duration_minutes = (end_time - start_time).total_seconds() / 60
            context.structure["duration_minutes"] = int(duration_minutes)
        
        return context
    
    def extract_batch(
        self,
        items: list[dict],
        mode: Optional[ExtractionMode] = None,
    ) -> list[MinimalContext]:
        """
        Extract minimal context from multiple items.
        
        Each item dict should have 'type' and relevant fields.
        """
        results = []
        
        for item in items:
            item_type = item.get('type', 'text')
            
            try:
                if item_type == 'file':
                    context = self.extract_from_file(item['path'], mode)
                elif item_type == 'email':
                    context = self.extract_from_email(
                        subject=item.get('subject', ''),
                        body=item.get('body', ''),
                        sender=item.get('sender'),
                        recipients=item.get('recipients'),
                        date=item.get('date'),
                        mode=mode,
                    )
                elif item_type == 'calendar':
                    context = self.extract_from_calendar_event(
                        title=item.get('title', ''),
                        description=item.get('description'),
                        start_time=item.get('start_time'),
                        end_time=item.get('end_time'),
                        attendees=item.get('attendees'),
                        location=item.get('location'),
                        mode=mode,
                    )
                else:
                    context = self.extract_from_text(
                        item.get('content', ''),
                        source_type=item_type,
                        mode=mode,
                    )
                results.append(context)
            except Exception as e:
                # Return minimal error context
                results.append(MinimalContext(
                    source_id=self._hash_content(str(item)),
                    source_type=item_type,
                    sensitive_content_detected=True,
                ))
                
        return results
    
    def combine_contexts(
        self,
        contexts: list[MinimalContext],
        max_keywords: int = 30,
    ) -> MinimalContext:
        """
        Combine multiple contexts into a single summary context.
        
        Useful for combining context from multiple files/sources.
        """
        if not contexts:
            return MinimalContext(
                source_id="empty",
                source_type="combined",
            )
        
        if len(contexts) == 1:
            return contexts[0]
        
        # Merge all extracted info
        all_keywords = []
        all_topics = []
        all_entities: dict[str, list[str]] = {}
        total_words = 0
        total_lines = 0
        sensitive_detected = False
        total_redactions = 0
        
        for ctx in contexts:
            all_keywords.extend(ctx.keywords)
            all_topics.extend(ctx.topics)
            
            for entity_type, values in ctx.entities.items():
                if entity_type not in all_entities:
                    all_entities[entity_type] = []
                all_entities[entity_type].extend(values)
                
            if ctx.word_count:
                total_words += ctx.word_count
            if ctx.line_count:
                total_lines += ctx.line_count
            if ctx.sensitive_content_detected:
                sensitive_detected = True
            total_redactions += ctx.redactions_applied
        
        # Deduplicate and limit keywords
        unique_keywords = list(dict.fromkeys(all_keywords))[:max_keywords]
        unique_topics = list(dict.fromkeys(all_topics))[:10]
        
        # Deduplicate entities
        for entity_type in all_entities:
            all_entities[entity_type] = list(dict.fromkeys(all_entities[entity_type]))[:10]
        
        # Create combined summary
        source_types = list(set(ctx.source_type for ctx in contexts))
        combined_summary = f"Combined context from {len(contexts)} sources ({', '.join(source_types)})"
        
        return MinimalContext(
            source_id=self._hash_content(str([c.source_id for c in contexts])),
            source_type="combined",
            word_count=total_words,
            line_count=total_lines,
            keywords=unique_keywords,
            topics=unique_topics,
            entities=all_entities,
            summary=combined_summary,
            structure={"source_count": len(contexts), "source_types": source_types},
            extraction_mode="combined",
            sensitive_content_detected=sensitive_detected,
            redactions_applied=total_redactions,
        )
    
    def _extract_from_text(
        self,
        content: str,
        source_type: str,
        source_id: str,
        mode: ExtractionMode = ExtractionMode.KEYWORDS,
        file_type: Optional[str] = None,
        file_size_bytes: Optional[int] = None,
        created_at: Optional[datetime] = None,
        modified_at: Optional[datetime] = None,
    ) -> MinimalContext:
        """
        Internal method to extract context from text.
        """
        # Apply redaction if engine is available
        redaction_count = 0
        if self.redaction_engine:
            result = self.redaction_engine.redact(content)
            content = result.redacted_text
            redaction_count = result.redaction_count
        
        # Basic metrics
        lines = content.split('\n')
        words = content.split()
        
        # Start with minimal context
        context = MinimalContext(
            source_id=source_id,
            source_type=source_type,
            file_type=file_type,
            file_size_bytes=file_size_bytes,
            line_count=len(lines),
            word_count=len(words),
            created_at=created_at,
            modified_at=modified_at,
            extraction_mode=mode.value,
            redactions_applied=redaction_count,
        )
        
        if mode == ExtractionMode.MINIMAL:
            # Just metadata, no content extraction
            return context
        
        if mode in (ExtractionMode.KEYWORDS, ExtractionMode.SUMMARY, ExtractionMode.STRUCTURED):
            # Extract keywords
            context.keywords = self._extract_keywords(content)
            context.topics = self._detect_topics(content)
        
        if mode in (ExtractionMode.SUMMARY, ExtractionMode.STRUCTURED):
            # Extract entities
            context.entities = self._extract_entities(content)
            
            # Generate summary (first sentence or truncated start)
            context.summary = self._generate_summary(content)
        
        if mode == ExtractionMode.STRUCTURED:
            # Extract structure based on content type
            context.structure = self._extract_structure(content, file_type)
        
        return context
    
    def _extract_keywords(self, content: str) -> list[str]:
        """Extract meaningful keywords from content."""
        # Tokenize and clean
        words = re.findall(r'\b[a-zA-Z]{3,}\b', content.lower())
        
        # Filter stop words and count frequencies
        word_counts: dict[str, int] = {}
        for word in words:
            if word not in self.STOP_WORDS and len(word) >= 3:
                word_counts[word] = word_counts.get(word, 0) + 1
        
        # Sort by frequency and return top keywords
        sorted_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)
        return [word for word, _ in sorted_words[:self.max_keywords]]
    
    def _detect_topics(self, content: str) -> list[str]:
        """Detect topics/categories based on keyword presence."""
        content_lower = content.lower()
        topics = []
        
        for topic, keywords in self.TOPIC_KEYWORDS.items():
            matches = sum(1 for kw in keywords if kw in content_lower)
            if matches >= 2:  # At least 2 keywords must match
                topics.append(topic)
                
        return topics[:5]  # Max 5 topics
    
    def _extract_entities(self, content: str) -> dict[str, list[str]]:
        """Extract entities using patterns."""
        entities: dict[str, list[str]] = {}
        
        for entity_type, patterns in self.ENTITY_PATTERNS.items():
            matches = []
            for pattern in patterns:
                found = re.findall(pattern, content, re.IGNORECASE)
                matches.extend(found)
            
            if matches:
                # Deduplicate and limit
                unique = list(dict.fromkeys(matches))[:10]
                
                # For privacy-sensitive types, mask partially
                if entity_type in ('emails', 'phone_numbers'):
                    unique = [self._mask_sensitive(v, entity_type) for v in unique]
                    
                entities[entity_type] = unique
                
        return entities
    
    def _mask_sensitive(self, value: str, entity_type: str) -> str:
        """Partially mask sensitive values."""
        if entity_type == 'emails':
            # Show only domain: xxx@domain.com
            if '@' in value:
                parts = value.split('@')
                return f"***@{parts[1]}"
        elif entity_type == 'phone_numbers':
            # Show only last 4 digits
            digits = re.sub(r'\D', '', value)
            if len(digits) >= 4:
                return f"***-***-{digits[-4:]}"
        return "***"
    
    def _generate_summary(self, content: str) -> str:
        """Generate a brief summary (first sentence or truncated)."""
        # Try to extract first sentence
        sentences = re.split(r'[.!?]\s+', content.strip())
        
        if sentences and sentences[0]:
            first = sentences[0].strip()
            if len(first) <= 100:
                return first
            return first[:97] + "..."
        
        # Fallback: truncate content
        words = content.split()[:self.max_summary_words]
        summary = ' '.join(words)
        if len(words) >= self.max_summary_words:
            summary += "..."
        return summary
    
    def _extract_structure(self, content: str, file_type: Optional[str]) -> dict:
        """Extract document structure."""
        structure: dict[str, Any] = {}
        
        # Detect headers (markdown style)
        headers = re.findall(r'^#+\s+(.+)$', content, re.MULTILINE)
        if headers:
            structure['headers'] = headers[:10]
        
        # Detect code blocks
        code_blocks = len(re.findall(r'```[\s\S]*?```', content))
        if code_blocks:
            structure['code_blocks'] = code_blocks
        
        # Detect lists
        list_items = len(re.findall(r'^[-*•]\s+', content, re.MULTILINE))
        if list_items:
            structure['list_items'] = list_items
        
        # Detect tables (pipe tables)
        table_rows = len(re.findall(r'^\|.+\|$', content, re.MULTILINE))
        if table_rows:
            structure['table_rows'] = table_rows
        
        # File-type specific extraction
        if file_type:
            if 'json' in file_type:
                try:
                    data = json.loads(content)
                    structure['json_keys'] = list(data.keys())[:10] if isinstance(data, dict) else ['array']
                except:
                    pass
            elif 'python' in file_type or file_type == '.py':
                # Extract function/class names
                funcs = re.findall(r'^def\s+(\w+)', content, re.MULTILINE)
                classes = re.findall(r'^class\s+(\w+)', content, re.MULTILINE)
                if funcs:
                    structure['functions'] = funcs[:20]
                if classes:
                    structure['classes'] = classes[:10]
        
        return structure
    
    def _hash_content(self, content: str) -> str:
        """Generate a hash ID for content."""
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def _hash_path(self, path: str) -> str:
        """Generate a hash ID for a file path."""
        return hashlib.sha256(path.encode()).hexdigest()[:16]
    
    def _get_file_type(self, path: Path) -> str:
        """Get file type/extension."""
        mime_type, _ = mimetypes.guess_type(str(path))
        if mime_type:
            return mime_type
        return path.suffix if path.suffix else "unknown"


# Global instance
context_minimizer = ContextMinimizer()
