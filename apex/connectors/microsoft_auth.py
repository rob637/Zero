"""
Microsoft Authentication Manager (MSAL)

Handles OAuth 2.0 authentication for Microsoft 365 services:
- Outlook Mail
- Outlook Calendar
- OneDrive
- Microsoft To-Do
- Microsoft Graph API

Setup:
1. Go to https://portal.azure.com/
2. Navigate to Azure Active Directory → App registrations
3. Create new registration:
   - Name: "Apex Personal Assistant"
   - Supported account types: "Personal Microsoft accounts only" (for personal)
     OR "Accounts in any organizational directory and personal" (for both)
   - Redirect URI: "http://localhost" (Mobile and desktop applications)
4. Note the Application (client) ID
5. Go to Authentication → Add platform → Mobile and desktop applications
   - Add "http://localhost" as redirect URI
   - Enable "Allow public client flows"
6. Go to API permissions → Add permissions:
   - Microsoft Graph:
     - Mail.Read, Mail.Send, Mail.ReadWrite
     - Calendars.Read, Calendars.ReadWrite
     - Files.Read, Files.ReadWrite
     - Tasks.Read, Tasks.ReadWrite
     - User.Read
     - Contacts.Read
7. Save client_id to ~/.apex/microsoft_credentials.json:
   {"client_id": "YOUR_CLIENT_ID"}

Usage:
    from microsoft_auth import MicrosoftAuth
    
    auth = MicrosoftAuth()
    token = await auth.get_token(scopes=['Mail.Read', 'Calendar.Read'])
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timedelta

try:
    import msal
    HAS_MSAL = True
except ImportError:
    HAS_MSAL = False

logger = logging.getLogger(__name__)


# Microsoft Graph API scopes
SCOPES = {
    # Mail
    'mail': ['Mail.Read', 'Mail.Send', 'Mail.ReadWrite'],
    'mail_readonly': ['Mail.Read'],
    'mail_send': ['Mail.Send'],
    
    # Calendar
    'calendar': ['Calendars.Read', 'Calendars.ReadWrite'],
    'calendar_readonly': ['Calendars.Read'],
    
    # OneDrive/Files
    'files': ['Files.Read', 'Files.ReadWrite', 'Files.Read.All'],
    'files_readonly': ['Files.Read', 'Files.Read.All'],
    
    # Tasks (To-Do)
    'tasks': ['Tasks.Read', 'Tasks.ReadWrite'],
    'tasks_readonly': ['Tasks.Read'],
    
    # Contacts
    'contacts': ['Contacts.Read', 'Contacts.ReadWrite'],
    'contacts_readonly': ['Contacts.Read'],
    
    # User profile
    'user': ['User.Read'],
}

# Default scopes for full access
DEFAULT_SCOPES = [
    'User.Read',
    'Mail.Read', 'Mail.Send', 'Mail.ReadWrite',
    'Calendars.Read', 'Calendars.ReadWrite',
    'Files.Read', 'Files.ReadWrite',
    'Tasks.Read', 'Tasks.ReadWrite',
    'Contacts.Read',
    'offline_access',  # For refresh tokens
]

# Microsoft Graph API base URL
GRAPH_API_BASE = 'https://graph.microsoft.com/v1.0'


class MicrosoftAuth:
    """
    Microsoft authentication manager using MSAL.
    
    Handles:
    - Interactive authentication (opens browser)
    - Token caching and refresh
    - Multiple scope management
    """
    
    def __init__(self, storage_path: Optional[str] = None):
        self._storage = Path(storage_path or "~/.apex").expanduser()
        self._storage.mkdir(parents=True, exist_ok=True)
        
        self._credentials_file = self._storage / "microsoft_credentials.json"
        self._token_cache_file = self._storage / "microsoft_token_cache.json"
        
        self._client_id: Optional[str] = None
        self._app: Optional['msal.PublicClientApplication'] = None
        self._token_cache: Optional['msal.SerializableTokenCache'] = None
        self._account: Optional[Dict] = None
        
        self._load_credentials()
    
    def _load_credentials(self):
        """Load client credentials from file."""
        if self._credentials_file.exists():
            try:
                with open(self._credentials_file) as f:
                    creds = json.load(f)
                self._client_id = creds.get('client_id')
            except Exception as e:
                logger.warning(f"Failed to load Microsoft credentials: {e}")
    
    def _init_msal_app(self):
        """Initialize MSAL application with token cache."""
        if not HAS_MSAL:
            raise ImportError(
                "MSAL library not installed. Run:\n"
                "pip install msal"
            )
        
        if not self._client_id:
            raise ValueError("No client_id configured. See setup instructions.")
        
        # Initialize token cache
        self._token_cache = msal.SerializableTokenCache()
        
        # Load existing cache
        if self._token_cache_file.exists():
            try:
                with open(self._token_cache_file) as f:
                    self._token_cache.deserialize(f.read())
            except Exception:
                pass
        
        # Create MSAL app
        self._app = msal.PublicClientApplication(
            client_id=self._client_id,
            authority="https://login.microsoftonline.com/consumers",  # Personal accounts
            token_cache=self._token_cache,
        )
    
    def _save_token_cache(self):
        """Persist token cache to disk."""
        if self._token_cache and self._token_cache.has_state_changed:
            with open(self._token_cache_file, 'w') as f:
                f.write(self._token_cache.serialize())
    
    def has_credentials(self) -> bool:
        """Check if client credentials are configured."""
        return self._client_id is not None
    
    def get_setup_instructions(self) -> str:
        """Return setup instructions for Microsoft OAuth."""
        return f"""
Microsoft 365 API Setup Instructions:

1. Go to https://portal.azure.com/
2. Navigate to Azure Active Directory → App registrations
3. Click "New registration":
   - Name: "Apex Personal Assistant"
   - Supported account types: Choose based on your needs:
     * "Personal Microsoft accounts only" - for @outlook.com, @hotmail.com
     * "Accounts in any organizational directory and personal" - for work + personal
   - Redirect URI: Select "Public client/native (mobile & desktop)"
     * Add: http://localhost
   
4. After creation, copy the "Application (client) ID"

5. Go to "Authentication":
   - Under "Advanced settings", set "Allow public client flows" to "Yes"
   - Save

6. Go to "API permissions" → "Add a permission" → "Microsoft Graph":
   - Delegated permissions:
     * User.Read
     * Mail.Read, Mail.Send, Mail.ReadWrite
     * Calendars.Read, Calendars.ReadWrite
     * Files.Read, Files.ReadWrite
     * Tasks.Read, Tasks.ReadWrite
     * Contacts.Read
     * offline_access

7. Create credentials file at: {self._credentials_file}

   {{
       "client_id": "YOUR_APPLICATION_CLIENT_ID"
   }}

The file should contain only your client_id (no client_secret needed for public clients).
"""
    
    def _resolve_scopes(self, scope_names: List[str]) -> List[str]:
        """Convert scope names to Microsoft Graph API scopes."""
        all_scopes = set()
        
        for name in scope_names:
            if name in SCOPES:
                all_scopes.update(SCOPES[name])
            elif '.' in name:  # Already a full scope
                all_scopes.add(name)
        
        # Always include offline_access for refresh tokens
        all_scopes.add('offline_access')
        
        return list(all_scopes)
    
    async def get_token(
        self,
        scope_names: List[str] = None,
        force_refresh: bool = False,
    ) -> Optional[str]:
        """
        Get a valid access token, authenticating if needed.
        
        Args:
            scope_names: List of scope names (mail, calendar, files, tasks)
            force_refresh: Force re-authentication
        
        Returns:
            Access token string or None if authentication fails
        """
        if not self._app:
            self._init_msal_app()
        
        scopes = self._resolve_scopes(scope_names or ['user', 'mail', 'calendar', 'files', 'tasks'])
        
        # Try to get token silently first
        if not force_refresh:
            accounts = self._app.get_accounts()
            if accounts:
                result = await asyncio.to_thread(
                    self._app.acquire_token_silent,
                    scopes,
                    account=accounts[0],
                )
                if result and 'access_token' in result:
                    self._account = accounts[0]
                    self._save_token_cache()
                    return result['access_token']
        
        # Need interactive authentication
        print("\n🔐 Opening browser for Microsoft authentication...")
        print("   Please sign in with your Microsoft account.\n")
        
        try:
            # Use device code flow for better compatibility
            flow = self._app.initiate_device_flow(scopes=scopes)
            
            if 'user_code' in flow:
                print(f"   To sign in, visit: {flow['verification_uri']}")
                print(f"   Enter this code: {flow['user_code']}")
                print("\n   Waiting for authentication...")
                
                result = await asyncio.to_thread(
                    self._app.acquire_token_by_device_flow,
                    flow,
                )
            else:
                # Fallback to interactive browser flow
                result = await asyncio.to_thread(
                    self._app.acquire_token_interactive,
                    scopes=scopes,
                )
                
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            return None
        
        if result and 'access_token' in result:
            accounts = self._app.get_accounts()
            if accounts:
                self._account = accounts[0]
            self._save_token_cache()
            return result['access_token']
        
        if 'error' in result:
            logger.error(f"Authentication error: {result.get('error_description', result['error'])}")
        
        return None
    
    async def get_headers(self, scope_names: List[str] = None) -> Dict[str, str]:
        """Get HTTP headers with authorization token."""
        token = await self.get_token(scope_names)
        if not token:
            raise RuntimeError("Not authenticated. Call get_token() first.")
        
        return {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        }
    
    @property
    def authenticated(self) -> bool:
        """Check if we have a cached account."""
        if not self._app:
            try:
                self._init_msal_app()
            except:
                return False
        return len(self._app.get_accounts()) > 0
    
    @property
    def user_info(self) -> Optional[Dict]:
        """Get cached user account info."""
        return self._account
    
    def sign_out(self):
        """Sign out and clear cached tokens."""
        if self._app:
            accounts = self._app.get_accounts()
            for account in accounts:
                self._app.remove_account(account)
        
        if self._token_cache_file.exists():
            self._token_cache_file.unlink()
        
        self._account = None


# Singleton instance
_auth_instance: Optional[MicrosoftAuth] = None

def get_microsoft_auth(storage_path: Optional[str] = None) -> MicrosoftAuth:
    """Get or create the MicrosoftAuth singleton."""
    global _auth_instance
    if _auth_instance is None:
        _auth_instance = MicrosoftAuth(storage_path)
    return _auth_instance
