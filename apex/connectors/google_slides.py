"""
Google Slides Connector

Real Google Slides API integration for presentation operations.

Usage:
    from connectors.google_slides import SlidesConnector
    
    slides = SlidesConnector()
    await slides.connect()
    
    # Create presentation
    pres = await slides.create_presentation("Q1 Report")
    
    # Add slide
    slide = await slides.add_slide(pres.id, "TITLE_AND_BODY")
    
    # Add text to slide
    await slides.add_text(pres.id, slide.id, "Welcome!", 100, 100, 400, 50)
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .google_auth import GoogleAuth, get_google_auth

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    HAS_GOOGLE_API = True
except ImportError:
    HAS_GOOGLE_API = False


# Predefined layouts
SLIDE_LAYOUTS = {
    'BLANK': 'BLANK',
    'TITLE': 'TITLE',
    'TITLE_AND_BODY': 'TITLE_AND_BODY',
    'TITLE_AND_TWO_COLUMNS': 'TITLE_AND_TWO_COLUMNS',
    'TITLE_ONLY': 'TITLE_ONLY',
    'SECTION_HEADER': 'SECTION_HEADER',
    'SECTION_TITLE_AND_DESCRIPTION': 'SECTION_TITLE_AND_DESCRIPTION',
    'ONE_COLUMN_TEXT': 'ONE_COLUMN_TEXT',
    'MAIN_POINT': 'MAIN_POINT',
    'BIG_NUMBER': 'BIG_NUMBER',
}


@dataclass
class Presentation:
    """Represents a Google Slides presentation."""
    id: str
    title: str
    locale: Optional[str] = None
    page_size: Optional[Dict] = None
    slides: List['Slide'] = field(default_factory=list)
    url: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "title": self.title,
            "locale": self.locale,
            "page_size": self.page_size,
            "slides": [s.to_dict() for s in self.slides],
            "url": self.url,
        }


@dataclass
class Slide:
    """Represents a single slide."""
    id: str
    index: int
    layout: Optional[str] = None
    elements: List[Dict] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "index": self.index,
            "layout": self.layout,
            "elements": self.elements,
        }


@dataclass
class PageElement:
    """Represents an element on a slide."""
    id: str
    element_type: str
    position: Tuple[float, float]  # x, y in EMU
    size: Tuple[float, float]  # width, height in EMU
    content: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "type": self.element_type,
            "position": {"x": self.position[0], "y": self.position[1]},
            "size": {"width": self.size[0], "height": self.size[1]},
            "content": self.content,
        }


# EMU (English Metric Units) conversion
EMU_PER_POINT = 12700
EMU_PER_INCH = 914400


def pt_to_emu(pt: float) -> int:
    """Convert points to EMU."""
    return int(pt * EMU_PER_POINT)


def inch_to_emu(inches: float) -> int:
    """Convert inches to EMU."""
    return int(inches * EMU_PER_INCH)


class SlidesConnector:
    """
    Google Slides API connector.
    
    Provides methods for:
    - Creating and managing presentations
    - Adding and arranging slides
    - Adding text, shapes, and images
    - Formatting elements
    """
    
    def __init__(self, auth: Optional[GoogleAuth] = None):
        self._auth = auth or get_google_auth()
        self._service = None
    
    async def connect(self) -> bool:
        """Connect to Google Slides API."""
        if not HAS_GOOGLE_API:
            raise ImportError(
                "Google API client not installed. Run:\n"
                "pip install google-api-python-client"
            )
        
        creds = await self._auth.get_credentials(['slides'])
        if not creds:
            return False
        
        self._service = await asyncio.to_thread(
            build, 'slides', 'v1', credentials=creds, cache_discovery=False
        )
        
        return True
    
    @property
    def connected(self) -> bool:
        return self._service is not None
    
    def _ensure_connected(self):
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
    
    def _parse_presentation(self, data: Dict) -> Presentation:
        """Parse API response into Presentation."""
        slides = []
        for i, slide_data in enumerate(data.get('slides', [])):
            slides.append(Slide(
                id=slide_data['objectId'],
                index=i,
                layout=slide_data.get('slideProperties', {}).get('layoutObjectId'),
                elements=[],
            ))
        
        page_size = data.get('pageSize', {})
        
        return Presentation(
            id=data['presentationId'],
            title=data.get('title', ''),
            locale=data.get('locale'),
            page_size={
                'width': page_size.get('width', {}).get('magnitude'),
                'height': page_size.get('height', {}).get('magnitude'),
            } if page_size else None,
            slides=slides,
            url=f"https://docs.google.com/presentation/d/{data['presentationId']}/edit",
        )
    
    # === Presentation Management ===
    
    async def create_presentation(self, title: str) -> Presentation:
        """
        Create a new presentation.
        
        Args:
            title: Presentation title
        
        Returns:
            Created Presentation object
        """
        self._ensure_connected()
        
        body = {'title': title}
        
        try:
            request = self._service.presentations().create(body=body)
            result = await asyncio.to_thread(request.execute)
            return self._parse_presentation(result)
        except HttpError as e:
            raise RuntimeError(f"Slides API error: {e}")
    
    async def get_presentation(self, presentation_id: str) -> Presentation:
        """
        Get presentation metadata.
        
        Args:
            presentation_id: Presentation ID
        
        Returns:
            Presentation object
        """
        self._ensure_connected()
        
        try:
            request = self._service.presentations().get(
                presentationId=presentation_id
            )
            result = await asyncio.to_thread(request.execute)
            return self._parse_presentation(result)
        except HttpError as e:
            raise RuntimeError(f"Slides API error: {e}")
    
    # === Slide Management ===
    
    async def add_slide(
        self,
        presentation_id: str,
        layout: str = "BLANK",
        insert_at: int = None,
    ) -> Slide:
        """
        Add a new slide.
        
        Args:
            presentation_id: Presentation ID
            layout: Slide layout (BLANK, TITLE, TITLE_AND_BODY, etc.)
            insert_at: Position to insert (None = end)
        
        Returns:
            Created Slide object
        """
        self._ensure_connected()
        
        import uuid
        slide_id = f"slide_{uuid.uuid4().hex[:8]}"
        
        request_body = {
            'objectId': slide_id,
            'slideLayoutReference': {
                'predefinedLayout': SLIDE_LAYOUTS.get(layout, layout)
            }
        }
        
        if insert_at is not None:
            request_body['insertionIndex'] = insert_at
        
        body = {
            'requests': [{
                'createSlide': request_body
            }]
        }
        
        try:
            request = self._service.presentations().batchUpdate(
                presentationId=presentation_id,
                body=body,
            )
            result = await asyncio.to_thread(request.execute)
            
            # Get the actual index from response
            reply = result.get('replies', [{}])[0].get('createSlide', {})
            
            return Slide(
                id=slide_id,
                index=insert_at if insert_at is not None else 0,
                layout=layout,
                elements=[],
            )
        except HttpError as e:
            raise RuntimeError(f"Slides API error: {e}")
    
    async def delete_slide(
        self,
        presentation_id: str,
        slide_id: str,
    ) -> bool:
        """
        Delete a slide.
        
        Args:
            presentation_id: Presentation ID
            slide_id: Slide object ID
        
        Returns:
            True if deleted
        """
        self._ensure_connected()
        
        body = {
            'requests': [{
                'deleteObject': {'objectId': slide_id}
            }]
        }
        
        try:
            request = self._service.presentations().batchUpdate(
                presentationId=presentation_id,
                body=body,
            )
            await asyncio.to_thread(request.execute)
            return True
        except HttpError as e:
            raise RuntimeError(f"Slides API error: {e}")
    
    async def duplicate_slide(
        self,
        presentation_id: str,
        slide_id: str,
    ) -> Slide:
        """
        Duplicate a slide.
        
        Args:
            presentation_id: Presentation ID
            slide_id: Slide to duplicate
        
        Returns:
            New Slide object
        """
        self._ensure_connected()
        
        import uuid
        new_slide_id = f"slide_{uuid.uuid4().hex[:8]}"
        
        body = {
            'requests': [{
                'duplicateObject': {
                    'objectId': slide_id,
                    'objectIds': {slide_id: new_slide_id}
                }
            }]
        }
        
        try:
            request = self._service.presentations().batchUpdate(
                presentationId=presentation_id,
                body=body,
            )
            await asyncio.to_thread(request.execute)
            
            return Slide(id=new_slide_id, index=0, elements=[])
        except HttpError as e:
            raise RuntimeError(f"Slides API error: {e}")
    
    # === Content Operations ===
    
    async def add_text_box(
        self,
        presentation_id: str,
        slide_id: str,
        text: str,
        x: float,
        y: float,
        width: float,
        height: float,
        font_size: int = 18,
    ) -> str:
        """
        Add a text box to a slide.
        
        Args:
            presentation_id: Presentation ID
            slide_id: Slide object ID
            text: Text content
            x, y: Position in points
            width, height: Size in points
            font_size: Font size in points
        
        Returns:
            Created element ID
        """
        self._ensure_connected()
        
        import uuid
        element_id = f"textbox_{uuid.uuid4().hex[:8]}"
        
        body = {
            'requests': [
                {
                    'createShape': {
                        'objectId': element_id,
                        'shapeType': 'TEXT_BOX',
                        'elementProperties': {
                            'pageObjectId': slide_id,
                            'size': {
                                'width': {'magnitude': pt_to_emu(width), 'unit': 'EMU'},
                                'height': {'magnitude': pt_to_emu(height), 'unit': 'EMU'},
                            },
                            'transform': {
                                'scaleX': 1,
                                'scaleY': 1,
                                'translateX': pt_to_emu(x),
                                'translateY': pt_to_emu(y),
                                'unit': 'EMU',
                            },
                        },
                    }
                },
                {
                    'insertText': {
                        'objectId': element_id,
                        'text': text,
                        'insertionIndex': 0,
                    }
                },
                {
                    'updateTextStyle': {
                        'objectId': element_id,
                        'style': {
                            'fontSize': {'magnitude': font_size, 'unit': 'PT'},
                        },
                        'fields': 'fontSize',
                    }
                },
            ]
        }
        
        try:
            request = self._service.presentations().batchUpdate(
                presentationId=presentation_id,
                body=body,
            )
            await asyncio.to_thread(request.execute)
            return element_id
        except HttpError as e:
            raise RuntimeError(f"Slides API error: {e}")
    
    async def add_shape(
        self,
        presentation_id: str,
        slide_id: str,
        shape_type: str,
        x: float,
        y: float,
        width: float,
        height: float,
        fill_color: Dict = None,
    ) -> str:
        """
        Add a shape to a slide.
        
        Args:
            presentation_id: Presentation ID
            slide_id: Slide object ID
            shape_type: Shape type (RECTANGLE, ELLIPSE, TRIANGLE, etc.)
            x, y: Position in points
            width, height: Size in points
            fill_color: RGB dict {red: 0-1, green: 0-1, blue: 0-1}
        
        Returns:
            Created element ID
        """
        self._ensure_connected()
        
        import uuid
        element_id = f"shape_{uuid.uuid4().hex[:8]}"
        
        requests = [
            {
                'createShape': {
                    'objectId': element_id,
                    'shapeType': shape_type,
                    'elementProperties': {
                        'pageObjectId': slide_id,
                        'size': {
                            'width': {'magnitude': pt_to_emu(width), 'unit': 'EMU'},
                            'height': {'magnitude': pt_to_emu(height), 'unit': 'EMU'},
                        },
                        'transform': {
                            'scaleX': 1,
                            'scaleY': 1,
                            'translateX': pt_to_emu(x),
                            'translateY': pt_to_emu(y),
                            'unit': 'EMU',
                        },
                    },
                }
            }
        ]
        
        if fill_color:
            requests.append({
                'updateShapeProperties': {
                    'objectId': element_id,
                    'shapeProperties': {
                        'shapeBackgroundFill': {
                            'solidFill': {
                                'color': {'rgbColor': fill_color}
                            }
                        }
                    },
                    'fields': 'shapeBackgroundFill.solidFill.color',
                }
            })
        
        body = {'requests': requests}
        
        try:
            request = self._service.presentations().batchUpdate(
                presentationId=presentation_id,
                body=body,
            )
            await asyncio.to_thread(request.execute)
            return element_id
        except HttpError as e:
            raise RuntimeError(f"Slides API error: {e}")
    
    async def add_image(
        self,
        presentation_id: str,
        slide_id: str,
        image_url: str,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> str:
        """
        Add an image to a slide.
        
        Args:
            presentation_id: Presentation ID
            slide_id: Slide object ID
            image_url: Public URL of image
            x, y: Position in points
            width, height: Size in points
        
        Returns:
            Created element ID
        """
        self._ensure_connected()
        
        import uuid
        element_id = f"image_{uuid.uuid4().hex[:8]}"
        
        body = {
            'requests': [{
                'createImage': {
                    'objectId': element_id,
                    'url': image_url,
                    'elementProperties': {
                        'pageObjectId': slide_id,
                        'size': {
                            'width': {'magnitude': pt_to_emu(width), 'unit': 'EMU'},
                            'height': {'magnitude': pt_to_emu(height), 'unit': 'EMU'},
                        },
                        'transform': {
                            'scaleX': 1,
                            'scaleY': 1,
                            'translateX': pt_to_emu(x),
                            'translateY': pt_to_emu(y),
                            'unit': 'EMU',
                        },
                    },
                }
            }]
        }
        
        try:
            request = self._service.presentations().batchUpdate(
                presentationId=presentation_id,
                body=body,
            )
            await asyncio.to_thread(request.execute)
            return element_id
        except HttpError as e:
            raise RuntimeError(f"Slides API error: {e}")
    
    async def add_table(
        self,
        presentation_id: str,
        slide_id: str,
        rows: int,
        columns: int,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> str:
        """
        Add a table to a slide.
        
        Args:
            presentation_id: Presentation ID
            slide_id: Slide object ID
            rows: Number of rows
            columns: Number of columns
            x, y: Position in points
            width, height: Size in points
        
        Returns:
            Created table ID
        """
        self._ensure_connected()
        
        import uuid
        table_id = f"table_{uuid.uuid4().hex[:8]}"
        
        body = {
            'requests': [{
                'createTable': {
                    'objectId': table_id,
                    'elementProperties': {
                        'pageObjectId': slide_id,
                        'size': {
                            'width': {'magnitude': pt_to_emu(width), 'unit': 'EMU'},
                            'height': {'magnitude': pt_to_emu(height), 'unit': 'EMU'},
                        },
                        'transform': {
                            'scaleX': 1,
                            'scaleY': 1,
                            'translateX': pt_to_emu(x),
                            'translateY': pt_to_emu(y),
                            'unit': 'EMU',
                        },
                    },
                    'rows': rows,
                    'columns': columns,
                }
            }]
        }
        
        try:
            request = self._service.presentations().batchUpdate(
                presentationId=presentation_id,
                body=body,
            )
            await asyncio.to_thread(request.execute)
            return table_id
        except HttpError as e:
            raise RuntimeError(f"Slides API error: {e}")
    
    # === Text Operations ===
    
    async def update_text(
        self,
        presentation_id: str,
        element_id: str,
        text: str,
        start_index: int = 0,
        end_index: int = None,
    ) -> bool:
        """
        Update text in an element.
        
        Args:
            presentation_id: Presentation ID
            element_id: Element object ID
            text: New text
            start_index: Start position to replace
            end_index: End position (None = to end)
        
        Returns:
            True if updated
        """
        self._ensure_connected()
        
        requests = []
        
        # Delete existing text if range specified
        if end_index is not None and end_index > start_index:
            requests.append({
                'deleteText': {
                    'objectId': element_id,
                    'textRange': {
                        'type': 'FIXED_RANGE',
                        'startIndex': start_index,
                        'endIndex': end_index,
                    }
                }
            })
        elif end_index is None:
            # Delete all text
            requests.append({
                'deleteText': {
                    'objectId': element_id,
                    'textRange': {'type': 'ALL'}
                }
            })
        
        # Insert new text
        requests.append({
            'insertText': {
                'objectId': element_id,
                'text': text,
                'insertionIndex': start_index,
            }
        })
        
        body = {'requests': requests}
        
        try:
            request = self._service.presentations().batchUpdate(
                presentationId=presentation_id,
                body=body,
            )
            await asyncio.to_thread(request.execute)
            return True
        except HttpError as e:
            raise RuntimeError(f"Slides API error: {e}")
    
    async def format_text(
        self,
        presentation_id: str,
        element_id: str,
        start_index: int = 0,
        end_index: int = None,
        bold: bool = None,
        italic: bool = None,
        underline: bool = None,
        font_size: int = None,
        foreground_color: Dict = None,
    ) -> bool:
        """
        Format text in an element.
        
        Args:
            presentation_id: Presentation ID
            element_id: Element object ID
            start_index, end_index: Text range (None end = to end)
            bold, italic, underline: Text style
            font_size: Font size in points
            foreground_color: RGB dict
        
        Returns:
            True if formatted
        """
        self._ensure_connected()
        
        style = {}
        fields = []
        
        if bold is not None:
            style['bold'] = bold
            fields.append('bold')
        if italic is not None:
            style['italic'] = italic
            fields.append('italic')
        if underline is not None:
            style['underline'] = underline
            fields.append('underline')
        if font_size is not None:
            style['fontSize'] = {'magnitude': font_size, 'unit': 'PT'}
            fields.append('fontSize')
        if foreground_color:
            style['foregroundColor'] = {'opaqueColor': {'rgbColor': foreground_color}}
            fields.append('foregroundColor')
        
        if not fields:
            return True
        
        text_range = {'type': 'ALL'}
        if end_index is not None:
            text_range = {
                'type': 'FIXED_RANGE',
                'startIndex': start_index,
                'endIndex': end_index,
            }
        
        body = {
            'requests': [{
                'updateTextStyle': {
                    'objectId': element_id,
                    'textRange': text_range,
                    'style': style,
                    'fields': ','.join(fields),
                }
            }]
        }
        
        try:
            request = self._service.presentations().batchUpdate(
                presentationId=presentation_id,
                body=body,
            )
            await asyncio.to_thread(request.execute)
            return True
        except HttpError as e:
            raise RuntimeError(f"Slides API error: {e}")
    
    # === Element Operations ===
    
    async def delete_element(
        self,
        presentation_id: str,
        element_id: str,
    ) -> bool:
        """
        Delete an element from a slide.
        
        Args:
            presentation_id: Presentation ID
            element_id: Element object ID
        
        Returns:
            True if deleted
        """
        self._ensure_connected()
        
        body = {
            'requests': [{
                'deleteObject': {'objectId': element_id}
            }]
        }
        
        try:
            request = self._service.presentations().batchUpdate(
                presentationId=presentation_id,
                body=body,
            )
            await asyncio.to_thread(request.execute)
            return True
        except HttpError as e:
            raise RuntimeError(f"Slides API error: {e}")
    
    async def move_element(
        self,
        presentation_id: str,
        element_id: str,
        x: float,
        y: float,
    ) -> bool:
        """
        Move an element to new position.
        
        Args:
            presentation_id: Presentation ID
            element_id: Element object ID
            x, y: New position in points
        
        Returns:
            True if moved
        """
        self._ensure_connected()
        
        body = {
            'requests': [{
                'updatePageElementTransform': {
                    'objectId': element_id,
                    'transform': {
                        'scaleX': 1,
                        'scaleY': 1,
                        'translateX': pt_to_emu(x),
                        'translateY': pt_to_emu(y),
                        'unit': 'EMU',
                    },
                    'applyMode': 'ABSOLUTE',
                }
            }]
        }
        
        try:
            request = self._service.presentations().batchUpdate(
                presentationId=presentation_id,
                body=body,
            )
            await asyncio.to_thread(request.execute)
            return True
        except HttpError as e:
            raise RuntimeError(f"Slides API error: {e}")
    
    async def resize_element(
        self,
        presentation_id: str,
        element_id: str,
        width: float,
        height: float,
    ) -> bool:
        """
        Resize an element.
        
        Args:
            presentation_id: Presentation ID
            element_id: Element object ID
            width, height: New size in points
        
        Returns:
            True if resized
        """
        self._ensure_connected()
        
        body = {
            'requests': [{
                'updatePageElementTransform': {
                    'objectId': element_id,
                    'transform': {
                        'scaleX': pt_to_emu(width) / EMU_PER_INCH,  # Approximate scaling
                        'scaleY': pt_to_emu(height) / EMU_PER_INCH,
                        'unit': 'EMU',
                    },
                    'applyMode': 'RELATIVE',
                }
            }]
        }
        
        try:
            request = self._service.presentations().batchUpdate(
                presentationId=presentation_id,
                body=body,
            )
            await asyncio.to_thread(request.execute)
            return True
        except HttpError as e:
            raise RuntimeError(f"Slides API error: {e}")
