"""
Microsoft Contacts Connector

Microsoft Graph API integration for contacts/people management.
Mirrors the Google Contacts connector for Microsoft 365 parity.

Usage:
    from connectors.microsoft_contacts import MicrosoftContactsConnector
    
    contacts = MicrosoftContactsConnector()
    await contacts.connect()
    
    # List contacts
    all_contacts = await contacts.list_contacts()
    
    # Search
    results = await contacts.search("John")
    
    # Create contact
    contact = await contacts.create_contact(
        given_name="Jane", surname="Doe",
        email="jane@example.com",
    )
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .microsoft_graph import GraphClient, get_graph_client, GraphAPIError

logger = logging.getLogger(__name__)

# Required scopes
CONTACTS_SCOPES = ['Contacts.Read', 'Contacts.ReadWrite']


@dataclass
class MicrosoftContact:
    """Represents a Microsoft 365 contact."""
    id: str
    display_name: str
    given_name: Optional[str] = None
    surname: Optional[str] = None
    emails: List[Dict] = field(default_factory=list)
    phones: List[Dict] = field(default_factory=list)
    company: Optional[str] = None
    job_title: Optional[str] = None
    department: Optional[str] = None
    addresses: List[Dict] = field(default_factory=list)
    birthday: Optional[str] = None
    notes: Optional[str] = None

    @property
    def primary_email(self) -> Optional[str]:
        """Get primary email address."""
        if self.emails:
            return self.emails[0].get("address")
        return None

    @property
    def primary_phone(self) -> Optional[str]:
        """Get primary phone number."""
        if self.phones:
            return self.phones[0]
        return None

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.display_name,
            "given_name": self.given_name,
            "surname": self.surname,
            "email": self.primary_email,
            "phone": self.primary_phone,
            "company": self.company,
            "job_title": self.job_title,
            "department": self.department,
            "emails": [e.get("address") for e in self.emails],
            "phones": self.phones,
            "birthday": self.birthday,
        }

    @classmethod
    def from_api(cls, data: Dict) -> "MicrosoftContact":
        """Parse Graph API contact response."""
        emails = data.get("emailAddresses", [])
        
        # Collect phone numbers from various fields
        phones = []
        for field_name in ("businessPhones", "homePhones", "mobilePhone"):
            val = data.get(field_name)
            if isinstance(val, list):
                phones.extend(val)
            elif isinstance(val, str) and val:
                phones.append(val)

        addresses = []
        for addr_field in ("homeAddress", "businessAddress", "otherAddress"):
            addr = data.get(addr_field)
            if addr and any(addr.values()):
                addresses.append({
                    "type": addr_field.replace("Address", ""),
                    "street": addr.get("street", ""),
                    "city": addr.get("city", ""),
                    "state": addr.get("state", ""),
                    "postal_code": addr.get("postalCode", ""),
                    "country": addr.get("countryOrRegion", ""),
                })

        return cls(
            id=data.get("id", ""),
            display_name=data.get("displayName", ""),
            given_name=data.get("givenName"),
            surname=data.get("surname"),
            emails=emails,
            phones=phones,
            company=data.get("companyName"),
            job_title=data.get("jobTitle"),
            department=data.get("department"),
            addresses=addresses,
            birthday=data.get("birthday"),
            notes=data.get("personalNotes"),
        )


class MicrosoftContactsConnector:
    """
    Microsoft Contacts connector via Graph API.
    
    Provides methods for:
    - Listing and searching contacts
    - Getting contact details
    - Creating and updating contacts
    - Deleting contacts
    """

    def __init__(self, client: Optional[GraphClient] = None):
        self._client = client or get_graph_client()

    async def connect(self) -> bool:
        """Connect to Microsoft Graph API."""
        if not self._client.connected:
            return await self._client.connect(scopes=CONTACTS_SCOPES)
        return True

    @property
    def connected(self) -> bool:
        return self._client.connected

    def _ensure_connected(self):
        if not self._client.connected:
            raise RuntimeError("Not connected. Call connect() first.")

    # === Listing and Searching ===

    async def list_contacts(
        self,
        limit: int = 50,
        skip: int = 0,
        order_by: str = "displayName",
    ) -> List[MicrosoftContact]:
        """
        List all contacts.
        
        Args:
            limit: Max contacts to return
            skip: Number of contacts to skip (pagination)
            order_by: Sort field
        
        Returns:
            List of MicrosoftContact objects
        """
        self._ensure_connected()

        result = await self._client.get(
            "/me/contacts",
            params={
                "$top": limit,
                "$skip": skip,
                "$orderby": order_by,
            },
        )

        return [
            MicrosoftContact.from_api(c)
            for c in result.get("value", [])
        ]

    async def search(self, query: str, limit: int = 25) -> List[MicrosoftContact]:
        """
        Search contacts by name, email, or other fields.
        
        Args:
            query: Search query string
            limit: Max results
        
        Returns:
            List of matching contacts
        """
        self._ensure_connected()

        result = await self._client.get(
            "/me/contacts",
            params={
                "$filter": (
                    f"contains(displayName,'{query}') or "
                    f"contains(givenName,'{query}') or "
                    f"contains(surname,'{query}')"
                ),
                "$top": limit,
            },
        )

        return [
            MicrosoftContact.from_api(c)
            for c in result.get("value", [])
        ]

    async def find_by_email(self, email: str) -> Optional[MicrosoftContact]:
        """
        Find a contact by email address.
        
        Args:
            email: Email address to search for
        
        Returns:
            MicrosoftContact or None
        """
        self._ensure_connected()

        result = await self._client.get(
            "/me/contacts",
            params={
                "$filter": f"emailAddresses/any(e:e/address eq '{email}')",
                "$top": 1,
            },
        )

        contacts = result.get("value", [])
        if contacts:
            return MicrosoftContact.from_api(contacts[0])
        return None

    async def find_by_name(self, name: str) -> List[MicrosoftContact]:
        """
        Find contacts by name (partial match).
        
        Args:
            name: Name to search for
        
        Returns:
            List of matching contacts
        """
        return await self.search(name)

    # === CRUD Operations ===

    async def get_contact(self, contact_id: str) -> MicrosoftContact:
        """
        Get a single contact by ID.
        
        Args:
            contact_id: Contact ID
        
        Returns:
            MicrosoftContact object
        """
        self._ensure_connected()

        result = await self._client.get(f"/me/contacts/{contact_id}")
        return MicrosoftContact.from_api(result)

    async def create_contact(
        self,
        given_name: str,
        surname: str = "",
        email: str = None,
        phone: str = None,
        company: str = None,
        job_title: str = None,
        department: str = None,
        notes: str = None,
    ) -> MicrosoftContact:
        """
        Create a new contact.
        
        Args:
            given_name: First name
            surname: Last name
            email: Email address
            phone: Phone number
            company: Company name
            job_title: Job title
            department: Department
            notes: Personal notes
        
        Returns:
            Created MicrosoftContact
        """
        self._ensure_connected()

        body: Dict[str, Any] = {
            "givenName": given_name,
            "surname": surname,
        }

        if email:
            body["emailAddresses"] = [{"address": email, "name": f"{given_name} {surname}".strip()}]
        if phone:
            body["mobilePhone"] = phone
        if company:
            body["companyName"] = company
        if job_title:
            body["jobTitle"] = job_title
        if department:
            body["department"] = department
        if notes:
            body["personalNotes"] = notes

        result = await self._client.post("/me/contacts", json_data=body)
        return MicrosoftContact.from_api(result)

    async def update_contact(
        self,
        contact_id: str,
        given_name: str = None,
        surname: str = None,
        email: str = None,
        phone: str = None,
        company: str = None,
        job_title: str = None,
        department: str = None,
        notes: str = None,
    ) -> MicrosoftContact:
        """
        Update an existing contact.
        
        Args:
            contact_id: Contact ID
            given_name: Updated first name
            surname: Updated last name
            email: Updated email
            phone: Updated phone
            company: Updated company
            job_title: Updated job title
            department: Updated department
            notes: Updated notes
        
        Returns:
            Updated MicrosoftContact
        """
        self._ensure_connected()

        body: Dict[str, Any] = {}
        if given_name is not None:
            body["givenName"] = given_name
        if surname is not None:
            body["surname"] = surname
        if email is not None:
            body["emailAddresses"] = [{"address": email}]
        if phone is not None:
            body["mobilePhone"] = phone
        if company is not None:
            body["companyName"] = company
        if job_title is not None:
            body["jobTitle"] = job_title
        if department is not None:
            body["department"] = department
        if notes is not None:
            body["personalNotes"] = notes

        result = await self._client.patch(
            f"/me/contacts/{contact_id}",
            json_data=body,
        )
        return MicrosoftContact.from_api(result)

    async def delete_contact(self, contact_id: str) -> bool:
        """
        Delete a contact.
        
        Args:
            contact_id: Contact ID
        
        Returns:
            True if deleted
        """
        self._ensure_connected()

        await self._client.delete(f"/me/contacts/{contact_id}")
        return True

    async def close(self):
        """Close the connector."""
        pass
