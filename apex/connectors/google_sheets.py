"""
Google Sheets Connector

Real Google Sheets API integration for spreadsheet operations.

Usage:
    from connectors.google_sheets import SheetsConnector
    
    sheets = SheetsConnector()
    await sheets.connect()
    
    # Read data
    data = await sheets.read_range("spreadsheet_id", "Sheet1!A1:D10")
    
    # Write data
    await sheets.write_range("spreadsheet_id", "Sheet1!A1", [["Name", "Age"], ["Alice", 30]])
    
    # Create new spreadsheet
    sheet = await sheets.create_spreadsheet("My New Sheet")
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from .google_auth import GoogleAuth, get_google_auth

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    HAS_GOOGLE_API = True
except ImportError:
    HAS_GOOGLE_API = False


@dataclass
class Spreadsheet:
    """Represents a Google Spreadsheet."""
    id: str
    title: str
    locale: Optional[str] = None
    time_zone: Optional[str] = None
    sheets: List[Dict] = None
    url: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "title": self.title,
            "locale": self.locale,
            "time_zone": self.time_zone,
            "sheets": self.sheets or [],
            "url": self.url,
        }


@dataclass
class Sheet:
    """Represents a single sheet within a spreadsheet."""
    id: int
    title: str
    index: int
    row_count: int
    column_count: int
    frozen_row_count: int = 0
    frozen_column_count: int = 0
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "title": self.title,
            "index": self.index,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "frozen_rows": self.frozen_row_count,
            "frozen_cols": self.frozen_column_count,
        }


class SheetsConnector:
    """
    Google Sheets API connector.
    
    Provides methods for:
    - Creating and managing spreadsheets
    - Reading and writing cell data
    - Formatting cells
    - Managing sheets within spreadsheets
    """
    
    def __init__(self, auth: Optional[GoogleAuth] = None):
        self._auth = auth or get_google_auth()
        self._service = None
    
    async def connect(self) -> bool:
        """Connect to Google Sheets API."""
        if not HAS_GOOGLE_API:
            raise ImportError(
                "Google API client not installed. Run:\n"
                "pip install google-api-python-client"
            )
        
        creds = await self._auth.get_credentials(['sheets'])
        if not creds:
            return False
        
        self._service = await asyncio.to_thread(
            build, 'sheets', 'v4', credentials=creds, cache_discovery=False
        )
        
        return True
    
    @property
    def connected(self) -> bool:
        return self._service is not None
    
    def _ensure_connected(self):
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
    
    def _parse_spreadsheet(self, data: Dict) -> Spreadsheet:
        """Parse API response into Spreadsheet."""
        props = data.get('properties', {})
        sheets = []
        for sheet in data.get('sheets', []):
            sheet_props = sheet.get('properties', {})
            grid_props = sheet_props.get('gridProperties', {})
            sheets.append({
                'id': sheet_props.get('sheetId'),
                'title': sheet_props.get('title'),
                'index': sheet_props.get('index'),
                'row_count': grid_props.get('rowCount', 1000),
                'column_count': grid_props.get('columnCount', 26),
            })
        
        return Spreadsheet(
            id=data.get('spreadsheetId'),
            title=props.get('title'),
            locale=props.get('locale'),
            time_zone=props.get('timeZone'),
            sheets=sheets,
            url=data.get('spreadsheetUrl'),
        )
    
    # === Spreadsheet Management ===
    
    async def create_spreadsheet(
        self,
        title: str,
        sheets: List[str] = None,
    ) -> Spreadsheet:
        """
        Create a new spreadsheet.
        
        Args:
            title: Spreadsheet title
            sheets: List of sheet names (default: ["Sheet1"])
        
        Returns:
            Created Spreadsheet object
        """
        self._ensure_connected()
        
        sheet_list = sheets or ["Sheet1"]
        body = {
            'properties': {'title': title},
            'sheets': [
                {'properties': {'title': name, 'index': i}}
                for i, name in enumerate(sheet_list)
            ]
        }
        
        try:
            request = self._service.spreadsheets().create(body=body)
            result = await asyncio.to_thread(request.execute)
            return self._parse_spreadsheet(result)
        except HttpError as e:
            raise RuntimeError(f"Sheets API error: {e}")
    
    async def get_spreadsheet(self, spreadsheet_id: str) -> Spreadsheet:
        """
        Get spreadsheet metadata.
        
        Args:
            spreadsheet_id: Spreadsheet ID
        
        Returns:
            Spreadsheet object
        """
        self._ensure_connected()
        
        try:
            request = self._service.spreadsheets().get(spreadsheetId=spreadsheet_id)
            result = await asyncio.to_thread(request.execute)
            return self._parse_spreadsheet(result)
        except HttpError as e:
            raise RuntimeError(f"Sheets API error: {e}")
    
    # === Reading Data ===
    
    async def read_range(
        self,
        spreadsheet_id: str,
        range: str,
        value_render_option: str = "FORMATTED_VALUE",
    ) -> List[List[Any]]:
        """
        Read data from a range.
        
        Args:
            spreadsheet_id: Spreadsheet ID
            range: A1 notation (e.g., "Sheet1!A1:D10")
            value_render_option: How to render values (FORMATTED_VALUE, UNFORMATTED_VALUE, FORMULA)
        
        Returns:
            2D list of cell values
        """
        self._ensure_connected()
        
        try:
            request = self._service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=range,
                valueRenderOption=value_render_option,
            )
            result = await asyncio.to_thread(request.execute)
            return result.get('values', [])
        except HttpError as e:
            raise RuntimeError(f"Sheets API error: {e}")
    
    async def read_multiple_ranges(
        self,
        spreadsheet_id: str,
        ranges: List[str],
    ) -> Dict[str, List[List[Any]]]:
        """
        Read data from multiple ranges.
        
        Args:
            spreadsheet_id: Spreadsheet ID
            ranges: List of A1 notation ranges
        
        Returns:
            Dict mapping range to values
        """
        self._ensure_connected()
        
        try:
            request = self._service.spreadsheets().values().batchGet(
                spreadsheetId=spreadsheet_id,
                ranges=ranges,
            )
            result = await asyncio.to_thread(request.execute)
            
            return {
                vr['range']: vr.get('values', [])
                for vr in result.get('valueRanges', [])
            }
        except HttpError as e:
            raise RuntimeError(f"Sheets API error: {e}")
    
    # === Writing Data ===
    
    async def write_range(
        self,
        spreadsheet_id: str,
        range: str,
        values: List[List[Any]],
        value_input_option: str = "USER_ENTERED",
    ) -> int:
        """
        Write data to a range.
        
        Args:
            spreadsheet_id: Spreadsheet ID
            range: A1 notation starting cell (e.g., "Sheet1!A1")
            values: 2D list of values to write
            value_input_option: How to interpret input (RAW or USER_ENTERED)
        
        Returns:
            Number of cells updated
        """
        self._ensure_connected()
        
        body = {'values': values}
        
        try:
            request = self._service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=range,
                valueInputOption=value_input_option,
                body=body,
            )
            result = await asyncio.to_thread(request.execute)
            return result.get('updatedCells', 0)
        except HttpError as e:
            raise RuntimeError(f"Sheets API error: {e}")
    
    async def append_rows(
        self,
        spreadsheet_id: str,
        range: str,
        values: List[List[Any]],
        value_input_option: str = "USER_ENTERED",
    ) -> int:
        """
        Append rows to a table.
        
        Args:
            spreadsheet_id: Spreadsheet ID
            range: Table range (e.g., "Sheet1!A:D")
            values: Rows to append
            value_input_option: How to interpret input
        
        Returns:
            Number of cells updated
        """
        self._ensure_connected()
        
        body = {'values': values}
        
        try:
            request = self._service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id,
                range=range,
                valueInputOption=value_input_option,
                insertDataOption="INSERT_ROWS",
                body=body,
            )
            result = await asyncio.to_thread(request.execute)
            updates = result.get('updates', {})
            return updates.get('updatedCells', 0)
        except HttpError as e:
            raise RuntimeError(f"Sheets API error: {e}")
    
    async def clear_range(
        self,
        spreadsheet_id: str,
        range: str,
    ) -> str:
        """
        Clear values from a range.
        
        Args:
            spreadsheet_id: Spreadsheet ID
            range: A1 notation range to clear
        
        Returns:
            Cleared range
        """
        self._ensure_connected()
        
        try:
            request = self._service.spreadsheets().values().clear(
                spreadsheetId=spreadsheet_id,
                range=range,
            )
            result = await asyncio.to_thread(request.execute)
            return result.get('clearedRange', range)
        except HttpError as e:
            raise RuntimeError(f"Sheets API error: {e}")
    
    # === Sheet Management ===
    
    async def add_sheet(
        self,
        spreadsheet_id: str,
        title: str,
        row_count: int = 1000,
        column_count: int = 26,
    ) -> Sheet:
        """
        Add a new sheet to spreadsheet.
        
        Args:
            spreadsheet_id: Spreadsheet ID
            title: New sheet title
            row_count: Number of rows
            column_count: Number of columns
        
        Returns:
            Created Sheet object
        """
        self._ensure_connected()
        
        body = {
            'requests': [{
                'addSheet': {
                    'properties': {
                        'title': title,
                        'gridProperties': {
                            'rowCount': row_count,
                            'columnCount': column_count,
                        }
                    }
                }
            }]
        }
        
        try:
            request = self._service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body=body,
            )
            result = await asyncio.to_thread(request.execute)
            reply = result['replies'][0]['addSheet']['properties']
            grid = reply.get('gridProperties', {})
            
            return Sheet(
                id=reply['sheetId'],
                title=reply['title'],
                index=reply.get('index', 0),
                row_count=grid.get('rowCount', row_count),
                column_count=grid.get('columnCount', column_count),
            )
        except HttpError as e:
            raise RuntimeError(f"Sheets API error: {e}")
    
    async def delete_sheet(
        self,
        spreadsheet_id: str,
        sheet_id: int,
    ) -> bool:
        """
        Delete a sheet from spreadsheet.
        
        Args:
            spreadsheet_id: Spreadsheet ID
            sheet_id: Sheet ID (not title)
        
        Returns:
            True if deleted
        """
        self._ensure_connected()
        
        body = {
            'requests': [{
                'deleteSheet': {'sheetId': sheet_id}
            }]
        }
        
        try:
            request = self._service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body=body,
            )
            await asyncio.to_thread(request.execute)
            return True
        except HttpError as e:
            raise RuntimeError(f"Sheets API error: {e}")
    
    async def rename_sheet(
        self,
        spreadsheet_id: str,
        sheet_id: int,
        new_title: str,
    ) -> bool:
        """
        Rename a sheet.
        
        Args:
            spreadsheet_id: Spreadsheet ID
            sheet_id: Sheet ID
            new_title: New sheet title
        
        Returns:
            True if renamed
        """
        self._ensure_connected()
        
        body = {
            'requests': [{
                'updateSheetProperties': {
                    'properties': {
                        'sheetId': sheet_id,
                        'title': new_title,
                    },
                    'fields': 'title',
                }
            }]
        }
        
        try:
            request = self._service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body=body,
            )
            await asyncio.to_thread(request.execute)
            return True
        except HttpError as e:
            raise RuntimeError(f"Sheets API error: {e}")
    
    # === Formatting ===
    
    async def format_cells(
        self,
        spreadsheet_id: str,
        sheet_id: int,
        start_row: int,
        end_row: int,
        start_col: int,
        end_col: int,
        bold: bool = None,
        italic: bool = None,
        background_color: Dict = None,
        text_color: Dict = None,
        font_size: int = None,
        horizontal_alignment: str = None,
    ) -> bool:
        """
        Format cells in a range.
        
        Args:
            spreadsheet_id: Spreadsheet ID
            sheet_id: Sheet ID
            start_row, end_row: Row range (0-indexed)
            start_col, end_col: Column range (0-indexed)
            bold, italic: Text formatting
            background_color: RGB dict {red: 0-1, green: 0-1, blue: 0-1}
            text_color: RGB dict
            font_size: Font size in points
            horizontal_alignment: LEFT, CENTER, RIGHT
        
        Returns:
            True if formatted
        """
        self._ensure_connected()
        
        cell_format = {}
        fields = []
        
        if bold is not None or italic is not None:
            text_format = {}
            if bold is not None:
                text_format['bold'] = bold
                fields.append('userEnteredFormat.textFormat.bold')
            if italic is not None:
                text_format['italic'] = italic
                fields.append('userEnteredFormat.textFormat.italic')
            if font_size is not None:
                text_format['fontSize'] = font_size
                fields.append('userEnteredFormat.textFormat.fontSize')
            cell_format['textFormat'] = text_format
        
        if background_color:
            cell_format['backgroundColor'] = background_color
            fields.append('userEnteredFormat.backgroundColor')
        
        if text_color:
            if 'textFormat' not in cell_format:
                cell_format['textFormat'] = {}
            cell_format['textFormat']['foregroundColor'] = text_color
            fields.append('userEnteredFormat.textFormat.foregroundColor')
        
        if horizontal_alignment:
            cell_format['horizontalAlignment'] = horizontal_alignment
            fields.append('userEnteredFormat.horizontalAlignment')
        
        if not fields:
            return True  # Nothing to format
        
        body = {
            'requests': [{
                'repeatCell': {
                    'range': {
                        'sheetId': sheet_id,
                        'startRowIndex': start_row,
                        'endRowIndex': end_row,
                        'startColumnIndex': start_col,
                        'endColumnIndex': end_col,
                    },
                    'cell': {'userEnteredFormat': cell_format},
                    'fields': ','.join(fields),
                }
            }]
        }
        
        try:
            request = self._service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body=body,
            )
            await asyncio.to_thread(request.execute)
            return True
        except HttpError as e:
            raise RuntimeError(f"Sheets API error: {e}")
    
    # === Utility Methods ===
    
    async def find_and_replace(
        self,
        spreadsheet_id: str,
        find: str,
        replace: str,
        match_case: bool = False,
        match_entire_cell: bool = False,
        sheet_id: int = None,
    ) -> int:
        """
        Find and replace text.
        
        Args:
            spreadsheet_id: Spreadsheet ID
            find: Text to find
            replace: Replacement text
            match_case: Case-sensitive matching
            match_entire_cell: Match entire cell contents
            sheet_id: Limit to specific sheet
        
        Returns:
            Number of occurrences replaced
        """
        self._ensure_connected()
        
        find_replace = {
            'find': find,
            'replacement': replace,
            'matchCase': match_case,
            'matchEntireCell': match_entire_cell,
            'allSheets': sheet_id is None,
        }
        
        if sheet_id is not None:
            find_replace['sheetId'] = sheet_id
        
        body = {
            'requests': [{
                'findReplace': find_replace
            }]
        }
        
        try:
            request = self._service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body=body,
            )
            result = await asyncio.to_thread(request.execute)
            reply = result.get('replies', [{}])[0].get('findReplace', {})
            return reply.get('occurrencesChanged', 0)
        except HttpError as e:
            raise RuntimeError(f"Sheets API error: {e}")
