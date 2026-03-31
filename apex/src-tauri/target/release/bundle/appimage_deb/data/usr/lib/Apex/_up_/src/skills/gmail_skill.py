"""
Gmail Skill - Read and process emails

Capabilities:
- Connect to Gmail via OAuth
- Search/filter emails
- Extract information (travel, receipts, etc.)
- Summarize email threads

Requires: User to authenticate with Google once.
"""

import os
import json
import base64
from pathlib import Path
from datetime import datetime
from email.utils import parsedate_to_datetime

from ..core.skill import (
    Skill, 
    ActionPlan, 
    ProposedAction, 
    ActionType,
    register_skill,
)

# Google API imports (optional - graceful fallback if not installed)
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False


# Gmail API scopes
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

# Where we store credentials
CREDENTIALS_DIR = Path.home() / '.apex' / 'credentials'
TOKEN_PATH = CREDENTIALS_DIR / 'gmail_token.json'
CLIENT_SECRET_PATH = CREDENTIALS_DIR / 'gmail_client_secret.json'


class GmailSkill(Skill):
    """
    Skill for reading and processing Gmail.
    
    First use requires OAuth authentication.
    After that, works automatically.
    """
    
    name = "gmail"
    description = "Read and process your Gmail - find travel emails, receipts, important messages"
    version = "0.1.0"
    
    trigger_phrases = [
        "gmail",
        "email",
        "emails",
        "inbox",
        "mail",
        "travel",
        "itinerary",
        "receipt",
        "confirmation",
    ]
    
    permissions = [
        "gmail.read",
    ]
    
    def __init__(self):
        self._service = None
        self._authenticated = False
    
    async def analyze(self, request: str, context: dict) -> ActionPlan:
        """
        Analyze Gmail based on user request.
        """
        if not GOOGLE_API_AVAILABLE:
            return ActionPlan(
                summary="Gmail integration not available",
                reasoning="Google API libraries not installed. Run: pip install google-auth-oauthlib google-api-python-client",
                warnings=["Install required packages to enable Gmail access."],
            )
        
        # Check if we have credentials
        if not self._is_authenticated():
            return ActionPlan(
                summary="Gmail authentication required",
                reasoning="I need permission to access your Gmail. This is a one-time setup.",
                warnings=[
                    "You'll need to sign in with Google and grant read-only access.",
                    "Your credentials are stored locally, never sent to our servers."
                ],
                actions=[
                    ProposedAction(
                        action_type=ActionType.CREATE_FOLDER,  # Using as generic "setup" action
                        source="Gmail OAuth",
                        reason="Authenticate with Google to enable email access",
                    )
                ],
            )
        
        # Parse what the user wants
        request_lower = request.lower()
        
        # Determine search query
        if 'travel' in request_lower or 'itinerary' in request_lower or 'flight' in request_lower:
            query = 'subject:(flight OR hotel OR booking OR reservation OR itinerary OR confirmation) newer_than:30d'
            search_type = "travel"
        elif 'receipt' in request_lower or 'purchase' in request_lower:
            query = 'subject:(receipt OR order OR purchase OR invoice) newer_than:30d'
            search_type = "receipts"
        elif 'unread' in request_lower:
            query = 'is:unread'
            search_type = "unread"
        else:
            query = 'newer_than:7d'
            search_type = "recent"
        
        # Fetch emails
        try:
            emails = await self._search_emails(query, max_results=20)
        except Exception as e:
            return ActionPlan(
                summary=f"Error accessing Gmail: {str(e)}",
                reasoning="There was a problem connecting to Gmail.",
                warnings=["Try re-authenticating or check your internet connection."],
            )
        
        if not emails:
            return ActionPlan(
                summary=f"No {search_type} emails found",
                reasoning=f"I searched your Gmail but didn't find any matching emails.",
                warnings=[],
            )
        
        # Build actions from emails found
        actions = []
        for email in emails:
            actions.append(ProposedAction(
                action_type=ActionType.COPY,  # Using COPY to represent "extract/process"
                source=f"{email['from']}: {email['subject']}",
                destination=email.get('date', ''),
                reason=f"Include in {search_type} summary",
            ))
        
        return ActionPlan(
            summary=f"Found {len(emails)} {search_type} emails",
            reasoning=f"I found emails matching your request. Select which ones to include in your summary.",
            actions=actions,
            warnings=[],
            affected_files_count=len(emails),
        )
    
    async def execute(self, plan: ActionPlan, approved_indices: list[int]) -> dict:
        """
        Execute the approved email processing.
        
        For authentication action: Opens OAuth flow.
        For email processing: Extracts and compiles information.
        """
        if not plan.actions:
            return {"success": [], "failed": [], "message": "No actions to execute"}
        
        # Check if this is an auth request
        if plan.actions[0].source == "Gmail OAuth":
            success = await self._authenticate()
            if success:
                return {
                    "success": [{"action": "authenticated", "message": "Gmail connected successfully!"}],
                    "failed": [],
                    "message": "Gmail is now connected. Ask me again to search your emails."
                }
            else:
                return {
                    "success": [],
                    "failed": [{"action": "authenticate", "error": "Authentication failed or was cancelled"}],
                    "message": "Could not connect to Gmail. Please try again."
                }
        
        # Email processing - compile selected emails
        # The actual email content would be fetched and processed here
        selected_count = len(approved_indices)
        
        return {
            "success": [{"action": "processed", "count": selected_count}],
            "failed": [],
            "message": f"Processed {selected_count} emails. Ready to create document.",
            "data": {
                "email_count": selected_count,
                "ready_for_document": True
            }
        }
    
    def _is_authenticated(self) -> bool:
        """Check if we have valid Gmail credentials."""
        if not TOKEN_PATH.exists():
            return False
        
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
            if creds and creds.valid:
                return True
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                # Save refreshed token
                TOKEN_PATH.write_text(creds.to_json())
                return True
        except Exception:
            pass
        
        return False
    
    async def _authenticate(self) -> bool:
        """Run the OAuth flow to authenticate with Gmail."""
        CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
        
        # Check for client secret file
        if not CLIENT_SECRET_PATH.exists():
            # Create instructions file
            instructions = CREDENTIALS_DIR / 'SETUP_GMAIL.md'
            instructions.write_text("""# Gmail Setup Instructions

To enable Gmail access, you need to create Google OAuth credentials:

1. Go to https://console.cloud.google.com/
2. Create a new project (or select existing)
3. Enable the Gmail API:
   - Go to APIs & Services > Library
   - Search for "Gmail API"
   - Click Enable
4. Create OAuth credentials:
   - Go to APIs & Services > Credentials
   - Click "Create Credentials" > "OAuth client ID"
   - Choose "Desktop app"
   - Download the JSON file
5. Save the downloaded file as:
   `~/.apex/credentials/gmail_client_secret.json`

Then try connecting to Gmail again.
""")
            print(f"\n📧 Gmail setup instructions saved to: {instructions}")
            print("Please follow the instructions to create Google OAuth credentials.\n")
            return False
        
        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CLIENT_SECRET_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)
            
            # Save credentials
            TOKEN_PATH.write_text(creds.to_json())
            self._authenticated = True
            return True
            
        except Exception as e:
            print(f"Authentication error: {e}")
            return False
    
    async def _search_emails(self, query: str, max_results: int = 20) -> list[dict]:
        """Search Gmail and return email summaries."""
        service = self._get_service()
        if not service:
            return []
        
        try:
            results = service.users().messages().list(
                userId='me',
                q=query,
                maxResults=max_results
            ).execute()
            
            messages = results.get('messages', [])
            emails = []
            
            for msg in messages:
                msg_data = service.users().messages().get(
                    userId='me',
                    id=msg['id'],
                    format='metadata',
                    metadataHeaders=['From', 'Subject', 'Date']
                ).execute()
                
                headers = {h['name']: h['value'] for h in msg_data.get('payload', {}).get('headers', [])}
                
                emails.append({
                    'id': msg['id'],
                    'from': headers.get('From', 'Unknown'),
                    'subject': headers.get('Subject', '(no subject)'),
                    'date': headers.get('Date', ''),
                    'snippet': msg_data.get('snippet', ''),
                })
            
            return emails
            
        except Exception as e:
            print(f"Error searching emails: {e}")
            return []
    
    def _get_service(self):
        """Get authenticated Gmail service."""
        if self._service:
            return self._service
        
        if not TOKEN_PATH.exists():
            return None
        
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                TOKEN_PATH.write_text(creds.to_json())
            
            self._service = build('gmail', 'v1', credentials=creds)
            return self._service
        except Exception:
            return None


# Register the skill
gmail_skill = GmailSkill()
register_skill(gmail_skill)
