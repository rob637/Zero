"""
Microsoft Excel Online Connector

Real Microsoft Graph API integration for Excel workbook operations.
Uses the Graph API workbook endpoints for reading, writing, and managing
spreadsheets stored in OneDrive.

Usage:
    from connectors.microsoft_excel import ExcelConnector
    
    excel = ExcelConnector()
    await excel.connect()
    
    # Read data
    data = await excel.read_range("item_id", "Sheet1!A1:D10")
    
    # Write data
    await excel.write_range("item_id", "Sheet1!A1", [["Name", "Age"], ["Alice", 30]])
    
    # Create new workbook
    wb = await excel.create_workbook("My Report.xlsx")
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .microsoft_graph import GraphClient, get_graph_client, GraphAPIError

logger = logging.getLogger(__name__)

# Required scopes
EXCEL_SCOPES = ['Files.ReadWrite']


@dataclass
class Workbook:
    """Represents an Excel workbook."""
    id: str
    name: str
    web_url: Optional[str] = None
    worksheets: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "url": self.web_url,
            "worksheets": self.worksheets,
        }


@dataclass 
class Worksheet:
    """Represents a worksheet within a workbook."""
    id: str
    name: str
    position: int
    visibility: str = "Visible"

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "position": self.position,
            "visibility": self.visibility,
        }


class ExcelConnector:
    """
    Microsoft Excel Online connector via Graph API.
    
    Provides methods for:
    - Creating and managing workbooks
    - Reading and writing cell data
    - Managing worksheets
    - Working with tables
    - Running calculations
    
    All workbooks are stored in OneDrive. The item_id parameter
    refers to the OneDrive item ID of the .xlsx file.
    """

    def __init__(self, client: Optional[GraphClient] = None):
        self._client = client or get_graph_client()

    async def connect(self) -> bool:
        """Connect to Microsoft Graph API."""
        if not self._client.connected:
            return await self._client.connect(scopes=EXCEL_SCOPES)
        return True

    @property
    def connected(self) -> bool:
        return self._client.connected

    def _ensure_connected(self):
        if not self._client.connected:
            raise RuntimeError("Not connected. Call connect() first.")

    # === Workbook Management ===

    async def create_workbook(
        self,
        name: str,
        folder_path: str = "/",
    ) -> Workbook:
        """
        Create a new empty Excel workbook in OneDrive.
        
        Args:
            name: Filename (should end in .xlsx)
            folder_path: OneDrive folder path (default: root)
        
        Returns:
            Created Workbook object
        """
        self._ensure_connected()

        if not name.endswith('.xlsx'):
            name += '.xlsx'

        # Create empty xlsx via upload
        # Minimal valid xlsx is an empty file created by the API
        path = f"{folder_path.rstrip('/')}/{name}" if folder_path != "/" else name
        endpoint = f"/me/drive/root:/{path}:/content"

        # Upload empty content - Graph API creates a valid xlsx
        result = await self._client.put(
            endpoint,
            content=b'',
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )

        item_id = result.get('id', '')
        return Workbook(
            id=item_id,
            name=result.get('name', name),
            web_url=result.get('webUrl'),
        )

    async def get_workbook_info(self, item_id: str) -> Workbook:
        """
        Get workbook metadata and list of worksheets.
        
        Args:
            item_id: OneDrive item ID of the workbook
        
        Returns:
            Workbook object with worksheet list
        """
        self._ensure_connected()

        # Get file info
        file_info = await self._client.get(f"/me/drive/items/{item_id}")

        # Get worksheets
        ws_data = await self._client.get(
            f"/me/drive/items/{item_id}/workbook/worksheets"
        )
        worksheets = [
            {
                "id": ws.get("id", ""),
                "name": ws.get("name", ""),
                "position": ws.get("position", 0),
                "visibility": ws.get("visibility", "Visible"),
            }
            for ws in ws_data.get("value", [])
        ]

        return Workbook(
            id=item_id,
            name=file_info.get("name", ""),
            web_url=file_info.get("webUrl"),
            worksheets=worksheets,
        )

    # === Worksheet Management ===

    async def list_worksheets(self, item_id: str) -> List[Worksheet]:
        """
        List all worksheets in a workbook.
        
        Args:
            item_id: OneDrive item ID of the workbook
        
        Returns:
            List of Worksheet objects
        """
        self._ensure_connected()

        result = await self._client.get(
            f"/me/drive/items/{item_id}/workbook/worksheets"
        )

        return [
            Worksheet(
                id=ws.get("id", ""),
                name=ws.get("name", ""),
                position=ws.get("position", 0),
                visibility=ws.get("visibility", "Visible"),
            )
            for ws in result.get("value", [])
        ]

    async def add_worksheet(
        self,
        item_id: str,
        name: str,
    ) -> Worksheet:
        """
        Add a new worksheet to the workbook.
        
        Args:
            item_id: OneDrive item ID of the workbook
            name: Sheet name
        
        Returns:
            Created Worksheet object
        """
        self._ensure_connected()

        result = await self._client.post(
            f"/me/drive/items/{item_id}/workbook/worksheets",
            json_data={"name": name},
        )

        return Worksheet(
            id=result.get("id", ""),
            name=result.get("name", name),
            position=result.get("position", 0),
            visibility=result.get("visibility", "Visible"),
        )

    async def delete_worksheet(
        self,
        item_id: str,
        sheet_name: str,
    ) -> bool:
        """
        Delete a worksheet from the workbook.
        
        Args:
            item_id: OneDrive item ID of the workbook
            sheet_name: Name of the sheet to delete
        
        Returns:
            True if deleted
        """
        self._ensure_connected()

        await self._client.delete(
            f"/me/drive/items/{item_id}/workbook/worksheets/{sheet_name}"
        )
        return True

    async def rename_worksheet(
        self,
        item_id: str,
        sheet_name: str,
        new_name: str,
    ) -> bool:
        """
        Rename a worksheet.
        
        Args:
            item_id: OneDrive item ID
            sheet_name: Current sheet name
            new_name: New sheet name
        
        Returns:
            True if renamed
        """
        self._ensure_connected()

        await self._client.patch(
            f"/me/drive/items/{item_id}/workbook/worksheets/{sheet_name}",
            json_data={"name": new_name},
        )
        return True

    # === Reading Data ===

    async def read_range(
        self,
        item_id: str,
        address: str,
        sheet_name: str = None,
    ) -> List[List[Any]]:
        """
        Read data from a range.
        
        Args:
            item_id: OneDrive item ID of the workbook
            address: Range address (e.g., "A1:D10" or "Sheet1!A1:D10")
            sheet_name: Optional sheet name (if not in address)
        
        Returns:
            2D list of cell values
        """
        self._ensure_connected()

        if sheet_name:
            endpoint = (
                f"/me/drive/items/{item_id}/workbook/worksheets"
                f"/{sheet_name}/range(address='{address}')"
            )
        else:
            # Address may include sheet name like "Sheet1!A1:D10"
            endpoint = (
                f"/me/drive/items/{item_id}/workbook/worksheets"
                f"/range(address='{address}')"
            ) if '!' not in address else (
                f"/me/drive/items/{item_id}/workbook/"
                f"worksheets('{address.split('!')[0]}')"
                f"/range(address='{address.split('!')[1]}')"
            )

        result = await self._client.get(endpoint)
        return result.get("values", [])

    async def get_used_range(
        self,
        item_id: str,
        sheet_name: str = "Sheet1",
    ) -> Dict[str, Any]:
        """
        Get the used range (populated area) of a worksheet.
        
        Args:
            item_id: OneDrive item ID
            sheet_name: Worksheet name
        
        Returns:
            Dict with 'address', 'values', 'row_count', 'column_count'
        """
        self._ensure_connected()

        result = await self._client.get(
            f"/me/drive/items/{item_id}/workbook/worksheets"
            f"/{sheet_name}/usedRange"
        )

        return {
            "address": result.get("address", ""),
            "values": result.get("values", []),
            "row_count": result.get("rowCount", 0),
            "column_count": result.get("columnCount", 0),
        }

    # === Writing Data ===

    async def write_range(
        self,
        item_id: str,
        address: str,
        values: List[List[Any]],
        sheet_name: str = None,
    ) -> int:
        """
        Write data to a range.
        
        Args:
            item_id: OneDrive item ID
            address: Range address (e.g., "A1:D5" or "Sheet1!A1:D5")
            values: 2D list of values to write
            sheet_name: Optional sheet name (if not in address)
        
        Returns:
            Number of cells updated
        """
        self._ensure_connected()

        if sheet_name:
            endpoint = (
                f"/me/drive/items/{item_id}/workbook/worksheets"
                f"/{sheet_name}/range(address='{address}')"
            )
        else:
            if '!' in address:
                parts = address.split('!')
                endpoint = (
                    f"/me/drive/items/{item_id}/workbook/"
                    f"worksheets('{parts[0]}')"
                    f"/range(address='{parts[1]}')"
                )
            else:
                endpoint = (
                    f"/me/drive/items/{item_id}/workbook/worksheets"
                    f"/range(address='{address}')"
                )

        await self._client.patch(
            endpoint,
            json_data={"values": values},
        )

        # Estimate cells updated
        return len(values) * (len(values[0]) if values else 0)

    async def append_rows(
        self,
        item_id: str,
        table_name: str,
        values: List[List[Any]],
        sheet_name: str = "Sheet1",
    ) -> int:
        """
        Append rows to a table.
        
        Args:
            item_id: OneDrive item ID
            table_name: Excel table name
            values: Rows to append (list of lists)
            sheet_name: Sheet containing the table
        
        Returns:
            Number of rows added
        """
        self._ensure_connected()

        endpoint = (
            f"/me/drive/items/{item_id}/workbook/worksheets"
            f"/{sheet_name}/tables/{table_name}/rows"
        )

        await self._client.post(
            endpoint,
            json_data={"values": values},
        )

        return len(values)

    async def clear_range(
        self,
        item_id: str,
        address: str,
        sheet_name: str = None,
        apply_to: str = "All",
    ) -> bool:
        """
        Clear a range of cells.
        
        Args:
            item_id: OneDrive item ID
            address: Range address
            sheet_name: Optional sheet name
            apply_to: What to clear ("All", "Formats", "Contents")
        
        Returns:
            True if cleared
        """
        self._ensure_connected()

        if sheet_name:
            endpoint = (
                f"/me/drive/items/{item_id}/workbook/worksheets"
                f"/{sheet_name}/range(address='{address}')/clear"
            )
        else:
            if '!' in address:
                parts = address.split('!')
                endpoint = (
                    f"/me/drive/items/{item_id}/workbook/"
                    f"worksheets('{parts[0]}')"
                    f"/range(address='{parts[1]}')/clear"
                )
            else:
                endpoint = (
                    f"/me/drive/items/{item_id}/workbook/worksheets"
                    f"/range(address='{address}')/clear"
                )

        await self._client.post(endpoint, json_data={"applyTo": apply_to})
        return True

    # === Table Operations ===

    async def list_tables(
        self,
        item_id: str,
        sheet_name: str = None,
    ) -> List[Dict]:
        """
        List tables in a workbook or worksheet.
        
        Args:
            item_id: OneDrive item ID
            sheet_name: Optional worksheet name to filter
        
        Returns:
            List of table info dicts
        """
        self._ensure_connected()

        if sheet_name:
            endpoint = (
                f"/me/drive/items/{item_id}/workbook/worksheets"
                f"/{sheet_name}/tables"
            )
        else:
            endpoint = f"/me/drive/items/{item_id}/workbook/tables"

        result = await self._client.get(endpoint)

        return [
            {
                "id": t.get("id", ""),
                "name": t.get("name", ""),
                "show_headers": t.get("showHeaders", True),
                "show_totals": t.get("showTotals", False),
                "style": t.get("style", ""),
            }
            for t in result.get("value", [])
        ]

    async def create_table(
        self,
        item_id: str,
        address: str,
        has_headers: bool = True,
        sheet_name: str = "Sheet1",
    ) -> Dict:
        """
        Create a table from a range.
        
        Args:
            item_id: OneDrive item ID
            address: Range address (e.g., "A1:D5")
            has_headers: Whether the first row contains headers
            sheet_name: Worksheet name
        
        Returns:
            Created table info
        """
        self._ensure_connected()

        result = await self._client.post(
            f"/me/drive/items/{item_id}/workbook/worksheets"
            f"/{sheet_name}/tables/add",
            json_data={
                "address": address,
                "hasHeaders": has_headers,
            },
        )

        return {
            "id": result.get("id", ""),
            "name": result.get("name", ""),
            "show_headers": result.get("showHeaders", True),
            "style": result.get("style", ""),
        }

    async def get_table_rows(
        self,
        item_id: str,
        table_name: str,
    ) -> List[List[Any]]:
        """
        Get all rows from a table.
        
        Args:
            item_id: OneDrive item ID
            table_name: Table name
        
        Returns:
            2D list of row values
        """
        self._ensure_connected()

        result = await self._client.get(
            f"/me/drive/items/{item_id}/workbook/tables/{table_name}/rows"
        )

        return [row.get("values", []) for row in result.get("value", [])]

    # === Formulas and Calculations ===

    async def calculate(self, item_id: str) -> bool:
        """
        Recalculate the workbook.
        
        Args:
            item_id: OneDrive item ID
        
        Returns:
            True if calculation triggered
        """
        self._ensure_connected()

        await self._client.post(
            f"/me/drive/items/{item_id}/workbook/application/calculate",
            json_data={"calculationType": "Full"},
        )
        return True

    async def close(self):
        """Close the connector."""
        pass
