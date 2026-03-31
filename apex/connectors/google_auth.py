"""
Google OAuth Manager

Handles OAuth 2.0 flow for Google APIs (Gmail, Calendar, Drive, Contacts).

Setup:
1. Go to https://console.cloud.google.com/
2. Create a project
3. Enable APIs: Gmail, Calendar, Drive, People
4. Create OAuth 2.0 credentials (Desktop app)
5. Download credentials.json to ~/.apex/credentials.json

Usage:
    from google_auth import GoogleAuth
    
    auth = GoogleAuth()
    creds = await auth.get_credentials(scopes=['gmail', 'calendar'])
"""

import asyncio
import json
import os
from pathlib import Path
from typing import List, Optional
from datetime import datetime

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    HAS_GOOGLE_AUTH = True
except ImportError:
    HAS_GOOGLE_AUTH = False
    Credentials = None


# Scope definitions
SCOPES = {
    'gmail': [
        'https://www.googleapis.com/auth/gmail.readonly',
        'https://www.googleapis.com/auth/gmail.send',
        'https://www.googleapis.com/auth/gmail.modify',
    ],
    'gmail_readonly': [
        'https://www.googleapis.com/auth/gmail.readonly',
    ],
    'calendar': [
        'https://www.googleapis.com/auth/calendar',
        'https://www.googleapis.com/auth/calendar.events',
    ],
    'calendar_readonly': [
        'https://www.googleapis.com/auth/calendar.readonly',
    ],
    'drive': [
        'https://www.googleapis.com/auth/drive',
        'https://www.googleapis.com/auth/drive.file',
    ],
    'drive_readonly': [
        'https://www.googleapis.com/auth/drive.readonly',
    ],
    'contacts': [
        'https://www.googleapis.com/auth/contacts',
        'https://www.googleapis.com/auth/contacts.readonly',
    ],
    'contacts_readonly': [
        'https://www.googleapis.com/auth/contacts.readonly',
    ],
}


class GoogleAuth:
    """
    Google OAuth 2.0 authentication manager.
    
    Handles credential storage, refresh, and multi-scope authentication.
    """
    
    def __init__(self, storage_path: Optional[str] = None):
        self._storage = Path(storage_path or "~/.apex").expanduser()
        self._storage.mkdir(parents=True, exist_ok=True)
        
        self._credentials_file = self._storage / "google_credentials.json"
        self._token_file = self._storage / "google_token.json"
        
        self._creds: Optional[Credentials] = None
    
    def _resolve_scopes(self, scope_names: List[str]) -> List[str]:
        """Convert scope names to full Google API scopes."""
        all_scopes = []
        for name in scope_names:
            if name in SCOPES:
                all_scopes.extend(SCOPES[name])
            elif name.startswith('https://'):
                all_scopes.append(name)
        return list(set(all_scopes))
    
    def has_credentials_file(self) -> bool:
        """Check if OAuth credentials file exists."""
        return self._credentials_file.exists()
    
    def get_setup_instructions(self) -> str:
        """Return setup instructions for Google OAuth."""
        return f"""
Google API Setup Instructions:

1. Go to https://console.cloud.google.com/
2. Create a new project (or select existing)
3. Enable these APIs:
   - Gmail API
   - Google Calendar API  
   - Google Drive API
   - People API (Contacts)

4. Go to "Credentials" → "Create Credentials" → "OAuth 2.0 Client ID"
5. Set application type to "Desktop app"
6. Download the JSON file
7. Save it as: {self._credentials_file}

The file should look like:
{{
  "installed": {{
    "client_id": "YOUR_CLIENT_ID.apps.googleusercontent.com",
    "client_secret": "YOUR_CLIENT_SECRET",
    ...
  }}
}}
"""
    
    async def get_credentials(
        self, 
        scope_names: List[str] = None,
        force_refresh: bool = False,
    ) -> Optional[Credentials]:
        """
        Get valid Google credentials, authenticating if needed.
        
        Args:
            scope_names: List of scope names (gmail, calendar, drive, contacts)
            force_refresh: Force re-authentication
        
        Returns:
            Google Credentials object or None if authentication fails
        """
        if not HAS_GOOGLE_AUTH:
            raise ImportError(
                "Google auth libraries not installed. Run:\n"
                "pip install google-auth google-auth-oauthlib google-api-python-client"
            )
        
        scope_names = scope_names or ['gmail', 'calendar', 'drive', 'contacts']
        scopes = self._resolve_scopes(scope_names)
        
        # Try to load existing credentials
        if not force_refresh and self._token_file.exists():
            try:
                self._creds = Credentials.from_authorized_user_file(
                    str(self._token_file), scopes
                )
            except Exception:
                self._creds = None
        
        # Refresh if expired
        if self._creds and self._creds.expired and self._creds.refresh_token:
            try:
                self._creds.refresh(Request())
                self._save_token()
                return self._creds
            except Exception:
                self._creds = None
        
        # Return if valid
        if self._creds and self._creds.valid:
            return self._creds
        
        # Need to authenticate
        if not self._credentials_file.exists():
            print(self.get_setup_instructions())
            return None
        
        # Run OAuth flow
        flow = InstalledAppFlow.from_client_secrets_file(
            str(self._credentials_file), scopes
        )
        
        # Run in thread to not block
        self._creds = await asyncio.to_thread(
            flow.run_local_server, port=0
        )
        
        # Save for future use
        self._save_token()
        
        return self._creds
    
    def _save_token(self):
        """Save credentials to token file."""
        if self._creds:
            with open(self._token_file, 'w') as f:
                f.write(self._creds.to_json())
    
    def revoke(self):
        """Revoke stored credentials."""
        if self._token_file.exists():
            self._token_file.unlink()
        self._creds = None
    
    @property
    def authenticated(self) -> bool:
        """Check if we have valid credentials."""
        return self._creds is not None and self._creds.valid


# Singleton for easy access
_auth_instance: Optional[GoogleAuth] = None

def get_google_auth(storage_path: Optional[str] = None) -> GoogleAuth:
    """Get or create the GoogleAuth singleton."""
    global _auth_instance
    if _auth_instance is None:
        _auth_instance = GoogleAuth(storage_path)
    return _auth_instance
