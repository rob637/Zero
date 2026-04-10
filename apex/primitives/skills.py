"""
Skills — Local compute primitives that produce creative outputs.

Skills differ from Connectors: connectors talk to external services,
skills CREATE things locally using libraries + LLM intelligence.

Each skill is a Primitive. The planner sees them like any other tool.
"""

import json
import logging
import os
import platform
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .base import Primitive, StepResult, get_data_index

logger = logging.getLogger(__name__)


def _output_dir() -> Path:
    """Get or create the output directory for skill artifacts."""
    if platform.system() == "Windows":
        base = Path.home() / "Documents" / "Ziggy"
    else:
        base = Path.home() / "Ziggy"
    base.mkdir(parents=True, exist_ok=True)
    return base


# ============================================================
#  PHOTO BOOK SKILL
# ============================================================

class PhotoBookSkill(Primitive):
    """Create beautiful PDF photo books from local photos.

    Flow:
    1. Search the local file index for photos matching a query
    2. Read EXIF metadata (location, date, camera)
    3. Ask LLM to generate captions for each photo
    4. Lay out photos + captions into a PDF photo book
    5. Return the PDF path for the user to open/print
    """

    def __init__(self, llm_complete: Optional[Callable] = None):
        self._llm = llm_complete

    @property
    def name(self) -> str:
        return "PHOTO_BOOK"

    def get_operations(self) -> Dict[str, str]:
        return {
            "create": "Create a PDF photo book from local photos. Search by theme, location, date, or event. AI generates captions. Output is a printable PDF.",
            "preview": "Preview what photos would be included in a photo book without generating it.",
        }

    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "create": {
                "query": {"type": "str", "required": True, "description": "What photos to include: a theme, location, date range, or event (e.g. 'Africa vacation', 'summer 2024', 'family beach photos')"},
                "title": {"type": "str", "required": False, "description": "Book title. Auto-generated from query if not provided."},
                "max_photos": {"type": "int", "required": False, "description": "Maximum photos to include (default: 20)"},
                "layout": {"type": "str", "required": False, "description": "Layout style: 'classic' (1 photo/page), 'collage' (2-3 photos/page), 'magazine' (mixed). Default: classic"},
            },
            "preview": {
                "query": {"type": "str", "required": True, "description": "Search query for photos"},
                "max_photos": {"type": "int", "required": False, "description": "Maximum photos to preview (default: 20)"},
            },
        }

    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        if operation == "create":
            return await self._create_book(params)
        elif operation == "preview":
            return await self._preview(params)
        return StepResult(False, error=f"Unknown operation: {operation}")

    async def _find_photos(self, query: str, max_photos: int = 20) -> List[Dict[str, Any]]:
        """Search the local file index for photos matching the query."""
        index = get_data_index()
        if not index:
            return []

        # Search using FTS
        results = index.search(query, source="local_files", limit=max_photos * 3)

        # Filter to image files only
        image_exts = {".jpg", ".jpeg", ".png", ".tiff", ".heic", ".heif", ".webp"}
        photos = []
        for obj in results:
            path = obj.get("source_id", "") or obj.get("raw", {}).get("path", "")
            ext = os.path.splitext(path)[1].lower()
            if ext in image_exts and os.path.isfile(path):
                photos.append({
                    "path": path,
                    "name": os.path.basename(path),
                    "body": obj.get("body", ""),
                    "timestamp": obj.get("timestamp", ""),
                })
                if len(photos) >= max_photos:
                    break

        return photos

    async def _generate_captions(self, photos: List[Dict]) -> List[str]:
        """Ask LLM to generate captions for photos based on metadata."""
        if not self._llm or not photos:
            return [p.get("name", "") for p in photos]

        photo_descriptions = []
        for i, p in enumerate(photos):
            photo_descriptions.append(f"Photo {i+1}: {p['name']}\nMetadata: {p.get('body', 'No metadata')}")

        prompt = f"""Generate short, engaging photo captions for a photo book.

{chr(10).join(photo_descriptions)}

For each photo, write a 1-2 sentence caption that would look great in a printed photo book.
Use the metadata (location, date, camera) to add context when available.
Be warm and descriptive, not generic.

Return a JSON array of strings, one caption per photo. Return ONLY the JSON array."""

        try:
            response = await self._llm(prompt)
            response = response.strip()
            if response.startswith("```"):
                response = response.split("\n", 1)[1] if "\n" in response else response[3:]
                response = response.rsplit("```", 1)[0]
            captions = json.loads(response)
            if isinstance(captions, list) and len(captions) == len(photos):
                return captions
        except Exception as e:
            logger.warning(f"Caption generation failed: {e}")

        # Fallback: use filename
        return [p.get("name", f"Photo {i+1}") for i, p in enumerate(photos)]

    async def _create_book(self, params: Dict[str, Any]) -> StepResult:
        """Create a PDF photo book."""
        query = params.get("query", "")
        if not query:
            return StepResult(False, error="Please specify what photos to include (e.g. 'Africa vacation', 'summer 2024')")

        title = params.get("title", "")
        max_photos = min(params.get("max_photos", 20), 100)
        layout = params.get("layout", "classic")

        # 1. Find photos
        photos = await self._find_photos(query, max_photos)
        if not photos:
            return StepResult(False, error=f"No photos found matching '{query}'. Make sure your Pictures folder is indexed.")

        # 2. Generate captions
        captions = await self._generate_captions(photos)

        # 3. Generate title if not provided
        if not title:
            title = query.title()

        # 4. Build PDF
        try:
            output_path = self._build_pdf(photos, captions, title, layout)
        except ImportError:
            return StepResult(False, error="PDF generation requires the fpdf2 library. Run: pip install fpdf2")
        except Exception as e:
            return StepResult(False, error=f"Failed to create photo book: {e}")

        # 5. Try to open the file
        try:
            if platform.system() == "Windows":
                os.startfile(output_path)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", output_path])
            else:
                subprocess.Popen(["xdg-open", output_path])
        except Exception:
            pass

        return StepResult(True, data={
            "file": str(output_path),
            "title": title,
            "photo_count": len(photos),
            "message": f"Photo book '{title}' created with {len(photos)} photos → {output_path}"
        })

    def _build_pdf(
        self,
        photos: List[Dict],
        captions: List[str],
        title: str,
        layout: str,
    ) -> str:
        """Generate the PDF photo book."""
        from fpdf import FPDF

        pdf = FPDF(orientation="P", unit="mm", format="A4")
        pdf.set_auto_page_break(auto=False)

        # --- Title Page ---
        pdf.add_page()
        pdf.set_fill_color(20, 20, 20)
        pdf.rect(0, 0, 210, 297, "F")
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 36)
        pdf.set_y(120)
        pdf.cell(0, 20, title, align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 14)
        pdf.set_text_color(180, 180, 180)
        pdf.cell(0, 10, datetime.now().strftime("%B %Y"), align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 10, f"{len(photos)} photos", align="C")

        # --- Photo Pages ---
        if layout == "collage":
            self._layout_collage(pdf, photos, captions)
        else:
            self._layout_classic(pdf, photos, captions)

        # Save
        out_dir = _output_dir()
        safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in title).strip()
        filename = f"PhotoBook - {safe_title or 'Untitled'}.pdf"
        output_path = str(out_dir / filename)
        pdf.output(output_path)
        return output_path

    def _layout_classic(self, pdf, photos, captions):
        """One photo per page with caption below."""
        for i, (photo, caption) in enumerate(zip(photos, captions)):
            pdf.add_page()
            pdf.set_fill_color(255, 255, 255)
            pdf.rect(0, 0, 210, 297, "F")

            # Photo — centered, max width 180mm, max height 220mm
            try:
                from PIL import Image
                with Image.open(photo["path"]) as img:
                    w, h = img.size
                    aspect = w / h

                    max_w, max_h = 180, 210
                    if aspect > max_w / max_h:
                        img_w = max_w
                        img_h = max_w / aspect
                    else:
                        img_h = max_h
                        img_w = max_h * aspect

                    x = (210 - img_w) / 2
                    y = 15
                    pdf.image(photo["path"], x=x, y=y, w=img_w, h=img_h)

                    # Caption below photo
                    caption_y = y + img_h + 8
            except Exception:
                caption_y = 230

            pdf.set_y(caption_y)
            pdf.set_text_color(60, 60, 60)
            pdf.set_font("Helvetica", "I", 11)
            pdf.multi_cell(0, 6, caption, align="C")

            # Page number
            pdf.set_y(285)
            pdf.set_text_color(160, 160, 160)
            pdf.set_font("Helvetica", "", 8)
            pdf.cell(0, 5, str(i + 1), align="C")

    def _layout_collage(self, pdf, photos, captions):
        """Two photos per page with captions."""
        pairs = list(zip(photos, captions))
        for i in range(0, len(pairs), 2):
            pdf.add_page()
            pdf.set_fill_color(255, 255, 255)
            pdf.rect(0, 0, 210, 297, "F")

            for slot, idx in enumerate([i, i + 1]):
                if idx >= len(pairs):
                    break
                photo, caption = pairs[idx]
                y_start = 10 + slot * 140

                try:
                    from PIL import Image
                    with Image.open(photo["path"]) as img:
                        w, h = img.size
                        aspect = w / h
                        max_w, max_h = 180, 115
                        if aspect > max_w / max_h:
                            img_w = max_w
                            img_h = max_w / aspect
                        else:
                            img_h = max_h
                            img_w = max_h * aspect

                        x = (210 - img_w) / 2
                        pdf.image(photo["path"], x=x, y=y_start, w=img_w, h=img_h)
                        caption_y = y_start + img_h + 3
                except Exception:
                    caption_y = y_start + 115

                pdf.set_y(caption_y)
                pdf.set_text_color(60, 60, 60)
                pdf.set_font("Helvetica", "I", 10)
                pdf.multi_cell(0, 5, caption, align="C")

            # Page number
            pdf.set_y(285)
            pdf.set_text_color(160, 160, 160)
            pdf.set_font("Helvetica", "", 8)
            pdf.cell(0, 5, str(i // 2 + 1), align="C")

    async def _preview(self, params: Dict[str, Any]) -> StepResult:
        """Preview what photos would be in the book."""
        query = params.get("query", "")
        if not query:
            return StepResult(False, error="Please specify a search query")

        max_photos = min(params.get("max_photos", 20), 100)
        photos = await self._find_photos(query, max_photos)

        if not photos:
            return StepResult(False, error=f"No photos found matching '{query}'")

        return StepResult(True, data={
            "query": query,
            "photo_count": len(photos),
            "photos": [{"name": p["name"], "path": p["path"], "metadata": p.get("body", "")} for p in photos],
            "message": f"Found {len(photos)} photos matching '{query}'. Use photo_book create to generate the PDF."
        })


# ============================================================
#  REPORT SKILL
# ============================================================

class ReportSkill(Primitive):
    """Generate PDF/DOCX reports from data and natural language descriptions.

    Pull data from any connected service, generate charts and narrative,
    output as a professional PDF report.
    """

    def __init__(self, llm_complete: Optional[Callable] = None):
        self._llm = llm_complete

    @property
    def name(self) -> str:
        return "REPORT"

    def get_operations(self) -> Dict[str, str]:
        return {
            "create": "Generate a PDF report. Provide data, a title, and optionally section descriptions. AI writes the narrative and creates charts.",
        }

    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "create": {
                "title": {"type": "str", "required": True, "description": "Report title"},
                "sections": {"type": "list", "required": True, "description": "List of section dicts with 'heading' and 'content' (text, data table, or chart spec)"},
                "data": {"type": "dict", "required": False, "description": "Supporting data (tables, metrics) to include"},
            },
        }

    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        if operation != "create":
            return StepResult(False, error=f"Unknown operation: {operation}")

        title = params.get("title", "Report")
        sections = params.get("sections", [])

        if not sections:
            return StepResult(False, error="Provide at least one section with 'heading' and 'content'")

        try:
            from fpdf import FPDF
        except ImportError:
            return StepResult(False, error="Report generation requires fpdf2. Run: pip install fpdf2")

        try:
            pdf = FPDF(orientation="P", unit="mm", format="A4")
            pdf.set_auto_page_break(auto=True, margin=20)

            # Title page
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 28)
            pdf.set_y(100)
            pdf.cell(0, 15, title, align="C", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 12)
            pdf.set_text_color(120, 120, 120)
            pdf.cell(0, 10, datetime.now().strftime("%B %d, %Y"), align="C")

            # Content pages
            for section in sections:
                pdf.add_page()
                heading = section.get("heading", "")
                content = section.get("content", "")

                pdf.set_text_color(0, 0, 0)
                pdf.set_font("Helvetica", "B", 18)
                pdf.cell(0, 12, heading, new_x="LMARGIN", new_y="NEXT")
                pdf.ln(4)

                pdf.set_font("Helvetica", "", 11)
                if isinstance(content, str):
                    pdf.multi_cell(0, 6, content)
                elif isinstance(content, list):
                    # Render as table
                    if content and isinstance(content[0], dict):
                        headers = list(content[0].keys())
                        col_w = 190 / len(headers)
                        pdf.set_font("Helvetica", "B", 10)
                        for h in headers:
                            pdf.cell(col_w, 8, str(h), border=1)
                        pdf.ln()
                        pdf.set_font("Helvetica", "", 9)
                        for row in content[:50]:
                            for h in headers:
                                pdf.cell(col_w, 7, str(row.get(h, "")), border=1)
                            pdf.ln()

            # Save
            out_dir = _output_dir()
            safe = "".join(c if c.isalnum() or c in " -_" else "" for c in title).strip()
            path = str(out_dir / f"Report - {safe or 'Untitled'}.pdf")
            pdf.output(path)

            try:
                if platform.system() == "Windows":
                    os.startfile(path)
                elif platform.system() == "Darwin":
                    subprocess.Popen(["open", path])
            except Exception:
                pass

            return StepResult(True, data={
                "file": path,
                "title": title,
                "sections": len(sections),
                "message": f"Report '{title}' generated → {path}"
            })
        except Exception as e:
            return StepResult(False, error=f"Report generation failed: {e}")


# ============================================================
#  DATA VIZ SKILL
# ============================================================

class DataVizSkill(Primitive):
    """Create charts and visualizations from data."""

    def __init__(self, llm_complete: Optional[Callable] = None):
        self._llm = llm_complete

    @property
    def name(self) -> str:
        return "DATA_VIZ"

    def get_operations(self) -> Dict[str, str]:
        return {
            "chart": "Create a chart (bar, line, pie, scatter) from data. AI picks the best visualization if not specified.",
        }

    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "chart": {
                "data": {"type": "list", "required": True, "description": "Data to visualize — list of dicts or list of numbers"},
                "chart_type": {"type": "str", "required": False, "description": "Chart type: bar, line, pie, scatter, area. Auto-detected if omitted."},
                "title": {"type": "str", "required": False, "description": "Chart title"},
                "x_field": {"type": "str", "required": False, "description": "Field name for X axis"},
                "y_field": {"type": "str", "required": False, "description": "Field name for Y axis"},
            },
        }

    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        if operation != "chart":
            return StepResult(False, error=f"Unknown operation: {operation}")

        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            return StepResult(False, error="Charts require matplotlib. Run: pip install matplotlib")

        data = params.get("data", [])
        if not data:
            return StepResult(False, error="No data provided")

        chart_type = params.get("chart_type", "bar")
        title = params.get("title", "Chart")
        x_field = params.get("x_field")
        y_field = params.get("y_field")

        try:
            fig, ax = plt.subplots(figsize=(10, 6))

            if isinstance(data[0], dict):
                keys = list(data[0].keys())
                x_key = x_field or keys[0]
                y_key = y_field or (keys[1] if len(keys) > 1 else keys[0])
                x_vals = [d.get(x_key, "") for d in data]
                y_vals = [float(d.get(y_key, 0)) for d in data]
            else:
                x_vals = list(range(len(data)))
                y_vals = [float(v) for v in data]
                x_key, y_key = "Index", "Value"

            if chart_type == "pie":
                ax.pie(y_vals, labels=x_vals, autopct="%1.1f%%")
            elif chart_type == "line":
                ax.plot(x_vals, y_vals, marker="o")
                ax.set_xlabel(x_key)
                ax.set_ylabel(y_key)
            elif chart_type == "scatter":
                ax.scatter(x_vals, y_vals)
                ax.set_xlabel(x_key)
                ax.set_ylabel(y_key)
            else:
                ax.bar(range(len(x_vals)), y_vals, tick_label=[str(x) for x in x_vals])
                ax.set_xlabel(x_key)
                ax.set_ylabel(y_key)
                plt.xticks(rotation=45, ha="right")

            ax.set_title(title)
            plt.tight_layout()

            out_dir = _output_dir()
            safe = "".join(c if c.isalnum() or c in " -_" else "" for c in title).strip()
            path = str(out_dir / f"Chart - {safe or 'chart'}.png")
            fig.savefig(path, dpi=150)
            plt.close(fig)

            try:
                if platform.system() == "Windows":
                    os.startfile(path)
                elif platform.system() == "Darwin":
                    subprocess.Popen(["open", path])
            except Exception:
                pass

            return StepResult(True, data={
                "file": path,
                "title": title,
                "chart_type": chart_type,
                "data_points": len(data),
                "message": f"Chart '{title}' saved → {path}"
            })
        except Exception as e:
            return StepResult(False, error=f"Chart creation failed: {e}")


# ============================================================
#  FILE CONVERTER SKILL
# ============================================================

class FileConverterSkill(Primitive):
    """Convert files between formats."""

    @property
    def name(self) -> str:
        return "CONVERT"

    def get_operations(self) -> Dict[str, str]:
        return {
            "convert": "Convert a file to a different format. Supports: images (resize, format change), CSV↔XLSX, text→PDF.",
        }

    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "convert": {
                "input_path": {"type": "str", "required": True, "description": "Path to the input file"},
                "output_format": {"type": "str", "required": True, "description": "Target format: pdf, png, jpg, xlsx, csv, txt"},
                "resize": {"type": "str", "required": False, "description": "For images: resize to WxH (e.g. '800x600' or '50%')"},
            },
        }

    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        if operation != "convert":
            return StepResult(False, error=f"Unknown operation: {operation}")

        input_path = params.get("input_path", "")
        output_format = params.get("output_format", "").lower().strip(".")
        resize = params.get("resize")

        if not input_path or not os.path.isfile(input_path):
            return StepResult(False, error=f"File not found: {input_path}")
        if not output_format:
            return StepResult(False, error="Specify output_format (e.g. 'pdf', 'png', 'csv')")

        name = os.path.splitext(os.path.basename(input_path))[0]
        out_dir = _output_dir()
        output_path = str(out_dir / f"{name}.{output_format}")
        ext = os.path.splitext(input_path)[1].lower()

        try:
            # Image conversions
            if ext in (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp", ".gif"):
                from PIL import Image
                with Image.open(input_path) as img:
                    if resize:
                        if "%" in resize:
                            pct = float(resize.strip("%")) / 100
                            img = img.resize((int(img.width * pct), int(img.height * pct)))
                        elif "x" in resize.lower():
                            w, h = resize.lower().split("x")
                            img = img.resize((int(w), int(h)))
                    if output_format == "pdf":
                        rgb = img.convert("RGB")
                        rgb.save(output_path)
                    else:
                        img.save(output_path)
                return StepResult(True, data={"file": output_path, "message": f"Converted → {output_path}"})

            # CSV → XLSX
            if ext == ".csv" and output_format == "xlsx":
                import csv
                from io import StringIO
                with open(input_path, "r", encoding="utf-8") as f:
                    reader = list(csv.reader(f))
                # Use fpdf2 or openpyxl if available
                try:
                    import openpyxl
                    wb = openpyxl.Workbook()
                    ws = wb.active
                    for row in reader:
                        ws.append(row)
                    wb.save(output_path)
                    return StepResult(True, data={"file": output_path, "message": f"Converted → {output_path}"})
                except ImportError:
                    return StepResult(False, error="XLSX conversion requires openpyxl. Run: pip install openpyxl")

            # Text/MD → PDF
            if ext in (".txt", ".md", ".log") and output_format == "pdf":
                from fpdf import FPDF
                pdf = FPDF()
                pdf.add_page()
                pdf.set_font("Helvetica", "", 11)
                with open(input_path, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        pdf.multi_cell(0, 6, line.rstrip())
                pdf.output(output_path)
                return StepResult(True, data={"file": output_path, "message": f"Converted → {output_path}"})

            return StepResult(False, error=f"Unsupported conversion: {ext} → .{output_format}")
        except Exception as e:
            return StepResult(False, error=f"Conversion failed: {e}")


# ============================================================
#  EXPENSE REPORT SKILL
# ============================================================

class ExpenseReportSkill(Primitive):
    """Generate expense reports from CSV/data."""

    def __init__(self, llm_complete: Optional[Callable] = None):
        self._llm = llm_complete

    @property
    def name(self) -> str:
        return "EXPENSE_REPORT"

    def get_operations(self) -> Dict[str, str]:
        return {
            "create": "Create an expense report PDF from a CSV file or list of expenses. Categories are auto-detected by AI.",
        }

    def get_param_schema(self) -> Dict[str, Dict[str, Any]]:
        return {
            "create": {
                "source": {"type": "str", "required": False, "description": "Path to CSV/spreadsheet file with expenses"},
                "expenses": {"type": "list", "required": False, "description": "List of expense dicts with 'date', 'description', 'amount', optionally 'category'"},
                "title": {"type": "str", "required": False, "description": "Report title (default: 'Expense Report')"},
                "period": {"type": "str", "required": False, "description": "Reporting period (e.g. 'March 2026')"},
            },
        }

    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        if operation != "create":
            return StepResult(False, error=f"Unknown operation: {operation}")

        try:
            from fpdf import FPDF
        except ImportError:
            return StepResult(False, error="Requires fpdf2. Run: pip install fpdf2")

        expenses = params.get("expenses", [])
        source = params.get("source", "")
        title = params.get("title", "Expense Report")
        period = params.get("period", datetime.now().strftime("%B %Y"))

        # Load from CSV if provided
        if source and os.path.isfile(source):
            import csv
            with open(source, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    expenses.append({
                        "date": row.get("date", row.get("Date", "")),
                        "description": row.get("description", row.get("Description", row.get("vendor", row.get("Vendor", "")))),
                        "amount": row.get("amount", row.get("Amount", "0")),
                        "category": row.get("category", row.get("Category", "")),
                    })

        if not expenses:
            return StepResult(False, error="No expenses provided. Pass a CSV file path or a list of expense dicts.")

        # Calculate totals
        total = sum(float(e.get("amount", 0)) for e in expenses)
        categories = {}
        for e in expenses:
            cat = e.get("category", "Uncategorized")
            categories[cat] = categories.get(cat, 0) + float(e.get("amount", 0))

        # Build PDF
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 22)
        pdf.cell(0, 12, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 12)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 8, f"Period: {period}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 8, f"Total: ${total:,.2f}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)

        # Category summary
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, "Summary by Category", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 11)
        for cat, amt in sorted(categories.items(), key=lambda x: -x[1]):
            pdf.cell(120, 7, cat, border="B")
            pdf.cell(0, 7, f"${amt:,.2f}", border="B", align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)

        # Line items
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, "Line Items", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(30, 7, "Date", border=1)
        pdf.cell(80, 7, "Description", border=1)
        pdf.cell(40, 7, "Category", border=1)
        pdf.cell(30, 7, "Amount", border=1, align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        for e in expenses:
            pdf.cell(30, 6, str(e.get("date", "")), border=1)
            pdf.cell(80, 6, str(e.get("description", ""))[:45], border=1)
            pdf.cell(40, 6, str(e.get("category", "")), border=1)
            pdf.cell(30, 6, f"${float(e.get('amount', 0)):,.2f}", border=1, align="R", new_x="LMARGIN", new_y="NEXT")

        out_dir = _output_dir()
        safe = "".join(c if c.isalnum() or c in " -_" else "" for c in title).strip()
        path = str(out_dir / f"{safe or 'Expense Report'} - {period}.pdf")
        pdf.output(path)

        try:
            if platform.system() == "Windows":
                os.startfile(path)
        except Exception:
            pass

        return StepResult(True, data={
            "file": path,
            "total": total,
            "expense_count": len(expenses),
            "categories": categories,
            "message": f"Expense report generated: {len(expenses)} items, ${total:,.2f} total → {path}"
        })
