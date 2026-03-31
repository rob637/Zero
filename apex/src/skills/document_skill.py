"""
Document Skill - Create documents from data

Capabilities:
- Create markdown documents
- Create travel itineraries
- Create summaries and reports
- Save to user's Documents folder

Works with data from other skills (Gmail, file analysis, etc.)
"""

import os
from pathlib import Path
from datetime import datetime

from ..core.skill import (
    Skill, 
    ActionPlan, 
    ProposedAction, 
    ActionType,
    register_skill,
)
from ..core.llm import create_client_from_env


ITINERARY_PROMPT = """You are creating a travel itinerary document.

Given the following email information, create a well-organized travel itinerary in Markdown format.

Include:
- Trip overview (dates, destinations)
- Flight details (if any)
- Hotel/accommodation details (if any)
- Reservations and bookings
- Important confirmation numbers
- Timeline of events

Format it beautifully with headers, bullet points, and clear organization.

Email data:
{email_data}

Create the itinerary document:"""


SUMMARY_PROMPT = """Create a summary document from the following information.

Information:
{data}

Create a well-organized Markdown document summarizing this information:"""


class DocumentSkill(Skill):
    """
    Skill for creating documents from extracted data.
    
    Works in combination with other skills - Gmail extracts emails,
    Document skill turns them into a formatted itinerary.
    """
    
    name = "document"
    description = "Create documents, itineraries, summaries from your data"
    version = "0.1.0"
    
    trigger_phrases = [
        "create",
        "document",
        "itinerary",
        "summary",
        "report",
        "compile",
        "write",
    ]
    
    permissions = [
        "filesystem.write",
    ]
    
    def __init__(self):
        self.llm = create_client_from_env()
        self._documents_folder = self._find_documents_folder()
    
    async def analyze(self, request: str, context: dict) -> ActionPlan:
        """
        Analyze request and propose document creation.
        """
        request_lower = request.lower()
        
        # Determine document type
        if 'itinerary' in request_lower or 'travel' in request_lower:
            doc_type = "itinerary"
            filename = f"Travel_Itinerary_{datetime.now().strftime('%Y%m%d')}.md"
            description = "travel itinerary"
        elif 'summary' in request_lower:
            doc_type = "summary"
            filename = f"Summary_{datetime.now().strftime('%Y%m%d')}.md"
            description = "summary document"
        elif 'report' in request_lower:
            doc_type = "report"
            filename = f"Report_{datetime.now().strftime('%Y%m%d')}.md"
            description = "report"
        else:
            doc_type = "document"
            filename = f"Document_{datetime.now().strftime('%Y%m%d')}.md"
            description = "document"
        
        output_path = self._documents_folder / filename
        
        # Check if we have data in context (from previous skill like Gmail)
        has_data = bool(context.get('email_data') or context.get('data'))
        
        if not has_data:
            return ActionPlan(
                summary=f"Ready to create {description}",
                reasoning="I can create a document, but I need some data first. Try asking me to find emails or analyze files first, then create a document from them.",
                warnings=["No data available yet - search for emails or files first."],
            )
        
        return ActionPlan(
            summary=f"Create {description}: {filename}",
            reasoning=f"I'll compile the information into a well-formatted {description} and save it to your Documents folder.",
            actions=[
                ProposedAction(
                    action_type=ActionType.CREATE_FOLDER,
                    source=f"Create {description}",
                    destination=str(output_path),
                    reason=f"Generate formatted {description} from collected data",
                )
            ],
            warnings=[f"Will be saved to: {output_path}"],
        )
    
    async def execute(self, plan: ActionPlan, approved_indices: list[int]) -> dict:
        """
        Execute document creation.
        """
        if not plan.actions or not approved_indices:
            return {"success": [], "failed": [], "message": "No document to create"}
        
        action = plan.actions[0]
        output_path = Path(action.destination)
        
        # For now, create a template document
        # In real use, this would use LLM to format data from context
        content = self._create_template_document(action.source)
        
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(content, encoding='utf-8')
            
            return {
                "success": [{"action": "created", "path": str(output_path)}],
                "failed": [],
                "message": f"Document created: {output_path}",
                "file_path": str(output_path)
            }
        except Exception as e:
            return {
                "success": [],
                "failed": [{"action": "create", "error": str(e)}],
                "message": f"Failed to create document: {e}"
            }
    
    def _find_documents_folder(self) -> Path:
        """Find the user's Documents folder."""
        home = Path.home()
        
        # Check OneDrive first (Windows)
        if os.name == 'nt':
            for item in home.iterdir():
                if item.is_dir() and item.name.startswith('OneDrive'):
                    docs = item / 'Documents'
                    if docs.exists():
                        return docs
        
        # Standard Documents folder
        docs = home / 'Documents'
        if docs.exists():
            return docs
        
        # Fallback to home
        return home
    
    def _create_template_document(self, doc_type: str) -> str:
        """Create a template document."""
        now = datetime.now().strftime('%B %d, %Y')
        
        if 'itinerary' in doc_type.lower():
            return f"""# Travel Itinerary

**Created:** {now}

---

## Trip Overview

*Add your trip details here*

- **Dates:** 
- **Destination(s):** 

---

## Flights

| Flight | Date | Time | Confirmation |
|--------|------|------|--------------|
| | | | |

---

## Accommodations

| Hotel | Check-in | Check-out | Confirmation |
|-------|----------|-----------|--------------|
| | | | |

---

## Reservations & Activities

- [ ] 

---

## Important Information

- Confirmation numbers
- Contact information
- Notes

---

*Generated by Telic*
"""
        else:
            return f"""# Document

**Created:** {now}

---

## Summary

*Your content here*

---

*Generated by Telic*
"""


# Register the skill
document_skill = DocumentSkill()
register_skill(document_skill)
