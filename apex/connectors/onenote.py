"""
Microsoft OneNote Connector

Real Microsoft Graph API integration for OneNote operations.

Usage:
    from connectors.onenote import OneNoteConnector
    
    onenote = OneNoteConnector()
    await onenote.connect()
    
    # List notebooks
    notebooks = await onenote.list_notebooks()
    
    # Create page
    page = await onenote.create_page(section_id, "My Notes", "<p>Content here</p>")
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from .microsoft_graph import GraphClient

# Required scopes for OneNote
ONENOTE_SCOPES = [
    'Notes.Read',
    'Notes.ReadWrite',
    'Notes.Create',
]


@dataclass
class Notebook:
    """Represents a OneNote notebook."""
    id: str
    display_name: str
    created: Optional[datetime] = None
    modified: Optional[datetime] = None
    is_default: bool = False
    is_shared: bool = False
    sections_url: Optional[str] = None
    section_groups_url: Optional[str] = None
    links: Optional[Dict] = None
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.display_name,
            "created": self.created.isoformat() if self.created else None,
            "modified": self.modified.isoformat() if self.modified else None,
            "is_default": self.is_default,
            "is_shared": self.is_shared,
            "web_url": self.links.get('oneNoteWebUrl', {}).get('href') if self.links else None,
        }


@dataclass
class Section:
    """Represents a OneNote section."""
    id: str
    display_name: str
    created: Optional[datetime] = None
    modified: Optional[datetime] = None
    is_default: bool = False
    parent_notebook_id: Optional[str] = None
    parent_section_group_id: Optional[str] = None
    pages_url: Optional[str] = None
    links: Optional[Dict] = None
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.display_name,
            "created": self.created.isoformat() if self.created else None,
            "modified": self.modified.isoformat() if self.modified else None,
            "is_default": self.is_default,
            "notebook_id": self.parent_notebook_id,
            "web_url": self.links.get('oneNoteWebUrl', {}).get('href') if self.links else None,
        }


@dataclass
class SectionGroup:
    """Represents a OneNote section group."""
    id: str
    display_name: str
    created: Optional[datetime] = None
    modified: Optional[datetime] = None
    parent_notebook_id: Optional[str] = None
    parent_section_group_id: Optional[str] = None
    sections_url: Optional[str] = None
    section_groups_url: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.display_name,
            "created": self.created.isoformat() if self.created else None,
            "modified": self.modified.isoformat() if self.modified else None,
            "notebook_id": self.parent_notebook_id,
        }


@dataclass
class Page:
    """Represents a OneNote page."""
    id: str
    title: str
    created: Optional[datetime] = None
    modified: Optional[datetime] = None
    level: int = 0
    order: int = 0
    parent_section_id: Optional[str] = None
    content_url: Optional[str] = None
    links: Optional[Dict] = None
    content: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "title": self.title,
            "created": self.created.isoformat() if self.created else None,
            "modified": self.modified.isoformat() if self.modified else None,
            "level": self.level,
            "order": self.order,
            "section_id": self.parent_section_id,
            "web_url": self.links.get('oneNoteWebUrl', {}).get('href') if self.links else None,
        }


class OneNoteConnector:
    """
    Microsoft OneNote API connector via Graph API.
    
    Provides methods for:
    - Managing notebooks, sections, and section groups
    - Creating and reading pages
    - Searching notes
    - Working with page content
    """
    
    def __init__(self, client: Optional[GraphClient] = None):
        self._client = client or GraphClient()
    
    async def connect(self) -> bool:
        """Connect to Microsoft Graph API."""
        return await self._client.connect(ONENOTE_SCOPES)
    
    @property
    def connected(self) -> bool:
        return self._client.connected
    
    def _ensure_connected(self):
        if not self._client.connected:
            raise RuntimeError("Not connected. Call connect() first.")
    
    def _parse_datetime(self, dt_str: str) -> Optional[datetime]:
        """Parse ISO datetime string."""
        if not dt_str:
            return None
        try:
            return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        except:
            return None
    
    def _parse_notebook(self, data: Dict) -> Notebook:
        """Parse API response into Notebook."""
        return Notebook(
            id=data['id'],
            display_name=data.get('displayName', ''),
            created=self._parse_datetime(data.get('createdDateTime')),
            modified=self._parse_datetime(data.get('lastModifiedDateTime')),
            is_default=data.get('isDefault', False),
            is_shared=data.get('isShared', False),
            sections_url=data.get('sectionsUrl'),
            section_groups_url=data.get('sectionGroupsUrl'),
            links=data.get('links'),
        )
    
    def _parse_section(self, data: Dict) -> Section:
        """Parse API response into Section."""
        parent = data.get('parentNotebook', {})
        parent_group = data.get('parentSectionGroup', {})
        return Section(
            id=data['id'],
            display_name=data.get('displayName', ''),
            created=self._parse_datetime(data.get('createdDateTime')),
            modified=self._parse_datetime(data.get('lastModifiedDateTime')),
            is_default=data.get('isDefault', False),
            parent_notebook_id=parent.get('id'),
            parent_section_group_id=parent_group.get('id'),
            pages_url=data.get('pagesUrl'),
            links=data.get('links'),
        )
    
    def _parse_section_group(self, data: Dict) -> SectionGroup:
        """Parse API response into SectionGroup."""
        parent = data.get('parentNotebook', {})
        parent_group = data.get('parentSectionGroup', {})
        return SectionGroup(
            id=data['id'],
            display_name=data.get('displayName', ''),
            created=self._parse_datetime(data.get('createdDateTime')),
            modified=self._parse_datetime(data.get('lastModifiedDateTime')),
            parent_notebook_id=parent.get('id'),
            parent_section_group_id=parent_group.get('id'),
            sections_url=data.get('sectionsUrl'),
            section_groups_url=data.get('sectionGroupsUrl'),
        )
    
    def _parse_page(self, data: Dict) -> Page:
        """Parse API response into Page."""
        parent = data.get('parentSection', {})
        return Page(
            id=data['id'],
            title=data.get('title', ''),
            created=self._parse_datetime(data.get('createdDateTime')),
            modified=self._parse_datetime(data.get('lastModifiedDateTime')),
            level=data.get('level', 0),
            order=data.get('order', 0),
            parent_section_id=parent.get('id'),
            content_url=data.get('contentUrl'),
            links=data.get('links'),
        )
    
    # === Notebook Operations ===
    
    async def list_notebooks(self) -> List[Notebook]:
        """
        List all notebooks.
        
        Returns:
            List of Notebook objects
        """
        self._ensure_connected()
        
        notebooks = []
        async for page in self._client.paginate('/me/onenote/notebooks'):
            for item in page:
                notebooks.append(self._parse_notebook(item))
        
        return notebooks
    
    async def get_notebook(self, notebook_id: str) -> Notebook:
        """
        Get notebook by ID.
        
        Args:
            notebook_id: Notebook ID
        
        Returns:
            Notebook object
        """
        self._ensure_connected()
        
        data = await self._client.get(f'/me/onenote/notebooks/{notebook_id}')
        return self._parse_notebook(data)
    
    async def create_notebook(self, name: str) -> Notebook:
        """
        Create a new notebook.
        
        Args:
            name: Notebook display name
        
        Returns:
            Created Notebook object
        """
        self._ensure_connected()
        
        data = await self._client.post(
            '/me/onenote/notebooks',
            json={'displayName': name}
        )
        return self._parse_notebook(data)
    
    # === Section Operations ===
    
    async def list_sections(
        self,
        notebook_id: str = None,
    ) -> List[Section]:
        """
        List sections.
        
        Args:
            notebook_id: Filter by notebook (optional)
        
        Returns:
            List of Section objects
        """
        self._ensure_connected()
        
        if notebook_id:
            endpoint = f'/me/onenote/notebooks/{notebook_id}/sections'
        else:
            endpoint = '/me/onenote/sections'
        
        sections = []
        async for page in self._client.paginate(endpoint):
            for item in page:
                sections.append(self._parse_section(item))
        
        return sections
    
    async def get_section(self, section_id: str) -> Section:
        """
        Get section by ID.
        
        Args:
            section_id: Section ID
        
        Returns:
            Section object
        """
        self._ensure_connected()
        
        data = await self._client.get(f'/me/onenote/sections/{section_id}')
        return self._parse_section(data)
    
    async def create_section(
        self,
        notebook_id: str,
        name: str,
    ) -> Section:
        """
        Create a new section.
        
        Args:
            notebook_id: Parent notebook ID
            name: Section display name
        
        Returns:
            Created Section object
        """
        self._ensure_connected()
        
        data = await self._client.post(
            f'/me/onenote/notebooks/{notebook_id}/sections',
            json={'displayName': name}
        )
        return self._parse_section(data)
    
    # === Section Group Operations ===
    
    async def list_section_groups(
        self,
        notebook_id: str = None,
    ) -> List[SectionGroup]:
        """
        List section groups.
        
        Args:
            notebook_id: Filter by notebook (optional)
        
        Returns:
            List of SectionGroup objects
        """
        self._ensure_connected()
        
        if notebook_id:
            endpoint = f'/me/onenote/notebooks/{notebook_id}/sectionGroups'
        else:
            endpoint = '/me/onenote/sectionGroups'
        
        groups = []
        async for page in self._client.paginate(endpoint):
            for item in page:
                groups.append(self._parse_section_group(item))
        
        return groups
    
    async def create_section_group(
        self,
        notebook_id: str,
        name: str,
    ) -> SectionGroup:
        """
        Create a new section group.
        
        Args:
            notebook_id: Parent notebook ID
            name: Section group display name
        
        Returns:
            Created SectionGroup object
        """
        self._ensure_connected()
        
        data = await self._client.post(
            f'/me/onenote/notebooks/{notebook_id}/sectionGroups',
            json={'displayName': name}
        )
        return self._parse_section_group(data)
    
    # === Page Operations ===
    
    async def list_pages(
        self,
        section_id: str = None,
        max_results: int = 100,
    ) -> List[Page]:
        """
        List pages.
        
        Args:
            section_id: Filter by section (optional)
            max_results: Maximum pages to return
        
        Returns:
            List of Page objects
        """
        self._ensure_connected()
        
        if section_id:
            endpoint = f'/me/onenote/sections/{section_id}/pages'
        else:
            endpoint = '/me/onenote/pages'
        
        pages = []
        async for page_data in self._client.paginate(endpoint):
            for item in page_data:
                pages.append(self._parse_page(item))
                if len(pages) >= max_results:
                    return pages
        
        return pages
    
    async def get_page(self, page_id: str) -> Page:
        """
        Get page by ID.
        
        Args:
            page_id: Page ID
        
        Returns:
            Page object
        """
        self._ensure_connected()
        
        data = await self._client.get(f'/me/onenote/pages/{page_id}')
        return self._parse_page(data)
    
    async def get_page_content(self, page_id: str) -> str:
        """
        Get page HTML content.
        
        Args:
            page_id: Page ID
        
        Returns:
            HTML content string
        """
        self._ensure_connected()
        
        # Get raw content (HTML)
        response = await self._client.get(
            f'/me/onenote/pages/{page_id}/content',
            headers={'Accept': 'text/html'}
        )
        return response
    
    async def create_page(
        self,
        section_id: str,
        title: str,
        content: str,
    ) -> Page:
        """
        Create a new page.
        
        Args:
            section_id: Parent section ID
            title: Page title
            content: HTML content (body only, will be wrapped)
        
        Returns:
            Created Page object
        """
        self._ensure_connected()
        
        # Construct OneNote HTML
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>{title}</title>
</head>
<body>
{content}
</body>
</html>"""
        
        data = await self._client.post(
            f'/me/onenote/sections/{section_id}/pages',
            content=html.encode('utf-8'),
            headers={'Content-Type': 'text/html'},
        )
        return self._parse_page(data)
    
    async def update_page(
        self,
        page_id: str,
        content: str,
        target: str = "body",
        action: str = "replace",
    ) -> bool:
        """
        Update page content.
        
        Args:
            page_id: Page ID
            content: New HTML content
            target: Target element (body, #id, etc.)
            action: Action (replace, append, prepend, insert)
        
        Returns:
            True if updated
        """
        self._ensure_connected()
        
        patch_data = [{
            'target': target,
            'action': action,
            'content': content,
        }]
        
        await self._client.patch(
            f'/me/onenote/pages/{page_id}/content',
            json=patch_data,
        )
        return True
    
    async def delete_page(self, page_id: str) -> bool:
        """
        Delete a page.
        
        Args:
            page_id: Page ID
        
        Returns:
            True if deleted
        """
        self._ensure_connected()
        
        await self._client.delete(f'/me/onenote/pages/{page_id}')
        return True
    
    async def copy_page(
        self,
        page_id: str,
        target_section_id: str,
    ) -> Dict:
        """
        Copy a page to another section.
        
        Args:
            page_id: Page ID to copy
            target_section_id: Destination section ID
        
        Returns:
            Operation info
        """
        self._ensure_connected()
        
        data = await self._client.post(
            f'/me/onenote/pages/{page_id}/copyToSection',
            json={'id': target_section_id}
        )
        return data
    
    # === Search ===
    
    async def search(
        self,
        query: str,
        max_results: int = 25,
    ) -> List[Page]:
        """
        Search for pages.
        
        Note: Uses Microsoft Search API, requires additional permissions.
        
        Args:
            query: Search query
            max_results: Maximum results
        
        Returns:
            List of matching Page objects
        """
        self._ensure_connected()
        
        # Use filter on pages endpoint
        # Note: Full search requires Microsoft Search API
        endpoint = f"/me/onenote/pages?$filter=contains(title,'{query}')"
        
        pages = []
        try:
            async for page_data in self._client.paginate(endpoint):
                for item in page_data:
                    pages.append(self._parse_page(item))
                    if len(pages) >= max_results:
                        return pages
        except:
            # Filter may not be supported, fall back to listing all
            all_pages = await self.list_pages(max_results=max_results * 2)
            return [p for p in all_pages if query.lower() in p.title.lower()][:max_results]
        
        return pages
    
    # === Quick Notes ===
    
    async def create_quick_note(
        self,
        content: str,
    ) -> Page:
        """
        Create a quick note in the default notebook.
        
        Args:
            content: Note content (plain text or HTML)
        
        Returns:
            Created Page object
        """
        self._ensure_connected()
        
        # Get default notebook
        notebooks = await self.list_notebooks()
        default = next((n for n in notebooks if n.is_default), None)
        
        if not default:
            raise RuntimeError("No default notebook found")
        
        # Get first section
        sections = await self.list_sections(default.id)
        if not sections:
            # Create a section
            section = await self.create_section(default.id, "Quick Notes")
        else:
            section = sections[0]
        
        # Create page with timestamp title
        title = f"Quick Note - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        return await self.create_page(section.id, title, f"<p>{content}</p>")
