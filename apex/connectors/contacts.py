"""
Google Contacts Connector (People API)

Real Google Contacts API integration.

Usage:
    from connectors.contacts import ContactsConnector
    
    contacts = ContactsConnector()
    await contacts.connect()
    
    # Search contacts
    results = await contacts.search("John")
    
    # Get contact details
    contact = await contacts.get_contact(resource_name)
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .google_auth import GoogleAuth, get_google_auth

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    HAS_GOOGLE_API = True
except ImportError:
    HAS_GOOGLE_API = False


@dataclass
class Contact:
    """Represents a contact."""
    resource_name: str
    display_name: str
    emails: List[Dict] = field(default_factory=list)
    phones: List[Dict] = field(default_factory=list)
    organizations: List[Dict] = field(default_factory=list)
    addresses: List[Dict] = field(default_factory=list)
    photo_url: Optional[str] = None
    notes: Optional[str] = None
    
    @property
    def primary_email(self) -> Optional[str]:
        """Get primary email address."""
        for email in self.emails:
            if email.get('metadata', {}).get('primary'):
                return email.get('value')
        return self.emails[0].get('value') if self.emails else None
    
    @property
    def primary_phone(self) -> Optional[str]:
        """Get primary phone number."""
        for phone in self.phones:
            if phone.get('metadata', {}).get('primary'):
                return phone.get('value')
        return self.phones[0].get('value') if self.phones else None
    
    @property
    def company(self) -> Optional[str]:
        """Get primary organization/company."""
        if self.organizations:
            return self.organizations[0].get('name')
        return None
    
    @property
    def job_title(self) -> Optional[str]:
        """Get job title."""
        if self.organizations:
            return self.organizations[0].get('title')
        return None
    
    def to_dict(self) -> Dict:
        return {
            "resource_name": self.resource_name,
            "name": self.display_name,
            "email": self.primary_email,
            "phone": self.primary_phone,
            "company": self.company,
            "job_title": self.job_title,
            "emails": [e.get('value') for e in self.emails],
            "phones": [p.get('value') for p in self.phones],
            "photo": self.photo_url,
        }


class ContactsConnector:
    """
    Google People API connector for contacts.
    
    Provides methods for:
    - Listing and searching contacts
    - Getting contact details
    - Creating and updating contacts
    """
    
    def __init__(self, auth: Optional[GoogleAuth] = None):
        self._auth = auth or get_google_auth()
        self._service = None
    
    async def connect(self) -> bool:
        """Connect to Google People API."""
        if not HAS_GOOGLE_API:
            raise ImportError(
                "Google API client not installed. Run:\n"
                "pip install google-api-python-client"
            )
        
        creds = await self._auth.get_credentials(['contacts'])
        if not creds:
            return False
        
        self._service = await asyncio.to_thread(
            build, 'people', 'v1', credentials=creds
        )
        
        return True
    
    @property
    def connected(self) -> bool:
        return self._service is not None
    
    def _parse_contact(self, person: Dict) -> Contact:
        """Parse People API person into Contact."""
        names = person.get('names', [])
        display_name = names[0].get('displayName', '') if names else ''
        
        photos = person.get('photos', [])
        photo_url = photos[0].get('url') if photos else None
        
        biographies = person.get('biographies', [])
        notes = biographies[0].get('value') if biographies else None
        
        return Contact(
            resource_name=person.get('resourceName', ''),
            display_name=display_name,
            emails=person.get('emailAddresses', []),
            phones=person.get('phoneNumbers', []),
            organizations=person.get('organizations', []),
            addresses=person.get('addresses', []),
            photo_url=photo_url,
            notes=notes,
        )
    
    async def list_contacts(
        self,
        max_results: int = 100,
        sort_order: str = 'LAST_MODIFIED_DESCENDING',
    ) -> List[Contact]:
        """
        List all contacts.
        
        Args:
            max_results: Maximum contacts to return
            sort_order: LAST_MODIFIED_ASCENDING, LAST_MODIFIED_DESCENDING, 
                        FIRST_NAME_ASCENDING, LAST_NAME_ASCENDING
        
        Returns:
            List of Contact objects
        """
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
        
        try:
            request = self._service.people().connections().list(
                resourceName='people/me',
                pageSize=max_results,
                sortOrder=sort_order,
                personFields='names,emailAddresses,phoneNumbers,organizations,addresses,photos,biographies',
            )
            result = await asyncio.to_thread(request.execute)
            
            return [
                self._parse_contact(p)
                for p in result.get('connections', [])
            ]
            
        except HttpError as e:
            raise RuntimeError(f"People API error: {e}")
    
    async def search(
        self,
        query: str,
        max_results: int = 20,
    ) -> List[Contact]:
        """
        Search contacts by name, email, or phone.
        
        Args:
            query: Search string
            max_results: Maximum results
        
        Returns:
            List of matching Contact objects
        """
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
        
        try:
            request = self._service.people().searchContacts(
                query=query,
                pageSize=max_results,
                readMask='names,emailAddresses,phoneNumbers,organizations,photos',
            )
            result = await asyncio.to_thread(request.execute)
            
            contacts = []
            for item in result.get('results', []):
                person = item.get('person', {})
                if person:
                    contacts.append(self._parse_contact(person))
            
            return contacts
            
        except HttpError as e:
            # Fallback to listing and filtering if search fails
            all_contacts = await self.list_contacts(max_results=500)
            query_lower = query.lower()
            
            return [
                c for c in all_contacts
                if query_lower in c.display_name.lower()
                or any(query_lower in (e.get('value', '').lower()) for e in c.emails)
                or any(query_lower in (p.get('value', '').lower()) for p in c.phones)
            ][:max_results]
    
    async def get_contact(self, resource_name: str) -> Contact:
        """
        Get a contact by resource name.
        
        Args:
            resource_name: Contact resource name (e.g., 'people/c1234567890')
        
        Returns:
            Contact object
        """
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
        
        request = self._service.people().get(
            resourceName=resource_name,
            personFields='names,emailAddresses,phoneNumbers,organizations,addresses,photos,biographies',
        )
        result = await asyncio.to_thread(request.execute)
        return self._parse_contact(result)
    
    async def find_by_email(self, email: str) -> Optional[Contact]:
        """
        Find a contact by email address.
        
        Args:
            email: Email address to search for
        
        Returns:
            Contact if found, None otherwise
        """
        contacts = await self.search(email, max_results=10)
        
        email_lower = email.lower()
        for contact in contacts:
            for e in contact.emails:
                if e.get('value', '').lower() == email_lower:
                    return contact
        
        return None
    
    async def find_by_name(self, name: str) -> Optional[Contact]:
        """
        Find a contact by name.
        
        Args:
            name: Name to search for
        
        Returns:
            First matching Contact or None
        """
        contacts = await self.search(name, max_results=5)
        
        # Try exact match first
        name_lower = name.lower()
        for contact in contacts:
            if contact.display_name.lower() == name_lower:
                return contact
        
        # Return first partial match
        return contacts[0] if contacts else None
    
    async def create_contact(
        self,
        name: str,
        email: str = None,
        phone: str = None,
        company: str = None,
        job_title: str = None,
    ) -> Contact:
        """
        Create a new contact.
        
        Args:
            name: Full name
            email: Email address
            phone: Phone number
            company: Company/organization name
            job_title: Job title
        
        Returns:
            Created Contact
        """
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
        
        person = {
            'names': [{'givenName': name}],
        }
        
        if email:
            person['emailAddresses'] = [{'value': email}]
        
        if phone:
            person['phoneNumbers'] = [{'value': phone}]
        
        if company or job_title:
            org = {}
            if company:
                org['name'] = company
            if job_title:
                org['title'] = job_title
            person['organizations'] = [org]
        
        try:
            request = self._service.people().createContact(
                body=person,
            )
            result = await asyncio.to_thread(request.execute)
            return self._parse_contact(result)
            
        except HttpError as e:
            raise RuntimeError(f"Failed to create contact: {e}")
    
    async def update_contact(
        self,
        resource_name: str,
        **updates,
    ) -> Contact:
        """
        Update an existing contact.
        
        Args:
            resource_name: Contact resource name
            **updates: Fields to update (name, email, phone, company, job_title)
        
        Returns:
            Updated Contact
        """
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
        
        # Get current contact first
        current = await self.get_contact(resource_name)
        
        # Build update
        person = {}
        update_fields = []
        
        if 'name' in updates:
            person['names'] = [{'givenName': updates['name']}]
            update_fields.append('names')
        
        if 'email' in updates:
            person['emailAddresses'] = [{'value': updates['email']}]
            update_fields.append('emailAddresses')
        
        if 'phone' in updates:
            person['phoneNumbers'] = [{'value': updates['phone']}]
            update_fields.append('phoneNumbers')
        
        if 'company' in updates or 'job_title' in updates:
            org = {}
            if 'company' in updates:
                org['name'] = updates['company']
            if 'job_title' in updates:
                org['title'] = updates['job_title']
            person['organizations'] = [org]
            update_fields.append('organizations')
        
        if not update_fields:
            return current
        
        try:
            request = self._service.people().updateContact(
                resourceName=resource_name,
                body=person,
                updatePersonFields=','.join(update_fields),
            )
            result = await asyncio.to_thread(request.execute)
            return self._parse_contact(result)
            
        except HttpError as e:
            raise RuntimeError(f"Failed to update contact: {e}")
    
    async def delete_contact(self, resource_name: str) -> bool:
        """Delete a contact."""
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
        
        try:
            request = self._service.people().deleteContact(
                resourceName=resource_name,
            )
            await asyncio.to_thread(request.execute)
            return True
            
        except HttpError as e:
            raise RuntimeError(f"Failed to delete contact: {e}")
    
    async def get_other_contacts(
        self,
        max_results: int = 100,
    ) -> List[Contact]:
        """
        Get 'Other Contacts' (auto-created from interactions).
        
        Returns:
            List of Contact objects from Other Contacts
        """
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
        
        try:
            request = self._service.otherContacts().list(
                pageSize=max_results,
                readMask='names,emailAddresses,phoneNumbers',
            )
            result = await asyncio.to_thread(request.execute)
            
            return [
                self._parse_contact(p)
                for p in result.get('otherContacts', [])
            ]
            
        except HttpError as e:
            raise RuntimeError(f"People API error: {e}")
