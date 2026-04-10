"""
Local PC File Indexer

Opt-in background scanner that indexes files on the user's PC for instant
local search ("where's that PDF I downloaded last week?").

Design principles:
  - OPT-IN ONLY: User must explicitly enable via settings
  - Non-intrusive: low-priority I/O, batch+sleep, pauses during activity
  - Scoped: Only user directories (Documents, Desktop, Downloads, etc.)
  - Incremental: First scan builds full index, then file watcher handles changes
  - Privacy-first: Files never leave the device. Only metadata + text extracted locally.

Architecture:
  Phase 1 — Metadata scan: os.scandir() for names, paths, sizes, dates (~5-10s)
  Phase 2 — Content extraction: text from .txt, .pdf, .docx, .csv, .md, etc.
  Phase 3 — Embedding: vectors for semantic search ("budget spreadsheet")

Usage:
    scanner = LocalFileScanner(index, settings)
    await scanner.start()          # begins background scan
    await scanner.stop()           # stops scanning + watching
    scanner.status                 # progress/stats dict
"""

import asyncio
import hashlib
import json
import logging
import os
import platform
import stat
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

try:
    from .index import DataObject, Index, ObjectKind
except ImportError:
    from index import DataObject, Index, ObjectKind

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Settings — opt-in control
# ---------------------------------------------------------------------------

@dataclass
class FileIndexSettings:
    """User-controlled settings for local file indexing."""
    enabled: bool = False                  # Must be explicitly opted in
    scan_directories: List[str] = field(default_factory=list)  # User picks dirs
    exclude_patterns: List[str] = field(default_factory=lambda: [
        "node_modules", ".git", "__pycache__", ".venv", "venv",
        ".cache", ".tmp", "AppData/Local/Temp", "Library/Caches",
        "$Recycle.Bin", "System Volume Information",
    ])
    max_file_size_mb: float = 50.0         # Skip files larger than this
    extract_content: bool = True           # Phase 2: read file contents
    embed_content: bool = True             # Phase 3: generate embeddings
    batch_size: int = 500                  # Files per batch before sleeping
    batch_delay_ms: int = 100              # Sleep between batches
    watch_for_changes: bool = True         # Live file watching after scan
    scan_hidden: bool = False              # Skip dotfiles/hidden by default

    @classmethod
    def default_directories(cls) -> List[str]:
        """Platform-specific default user directories."""
        home = str(Path.home())
        system = platform.system()

        if system == "Windows":
            return [
                os.path.join(home, "Documents"),
                os.path.join(home, "Desktop"),
                os.path.join(home, "Downloads"),
                os.path.join(home, "Pictures"),
                os.path.join(home, "Videos"),
                os.path.join(home, "Music"),
                os.path.join(home, "OneDrive"),
            ]
        elif system == "Darwin":
            return [
                os.path.join(home, "Documents"),
                os.path.join(home, "Desktop"),
                os.path.join(home, "Downloads"),
                os.path.join(home, "Pictures"),
                os.path.join(home, "Movies"),
                os.path.join(home, "Music"),
                os.path.join(home, "iCloud Drive"),
            ]
        else:  # Linux
            return [
                os.path.join(home, "Documents"),
                os.path.join(home, "Desktop"),
                os.path.join(home, "Downloads"),
                os.path.join(home, "Pictures"),
                os.path.join(home, "Videos"),
                os.path.join(home, "Music"),
            ]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "scan_directories": self.scan_directories,
            "exclude_patterns": self.exclude_patterns,
            "max_file_size_mb": self.max_file_size_mb,
            "extract_content": self.extract_content,
            "embed_content": self.embed_content,
            "batch_size": self.batch_size,
            "batch_delay_ms": self.batch_delay_ms,
            "watch_for_changes": self.watch_for_changes,
            "scan_hidden": self.scan_hidden,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FileIndexSettings":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Content extractors — pull text from common file types
# ---------------------------------------------------------------------------

# Supported extensions → extractor function name
_TEXT_EXTENSIONS: Set[str] = {
    ".txt", ".md", ".markdown", ".rst", ".log", ".ini", ".cfg", ".conf",
    ".json", ".yaml", ".yml", ".toml", ".xml", ".html", ".htm", ".css",
    ".js", ".ts", ".py", ".java", ".c", ".cpp", ".h", ".cs", ".go",
    ".rs", ".rb", ".php", ".sh", ".bat", ".ps1", ".sql", ".r", ".m",
    ".csv", ".tsv", ".env", ".gitignore", ".dockerfile",
}

# Rich document types that need special extraction
_RICH_EXTENSIONS: Set[str] = {
    ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
    ".odt", ".ods", ".odp", ".rtf", ".epub",
}

# Image extensions with potential EXIF metadata
_IMAGE_EXTENSIONS: Set[str] = {
    ".jpg", ".jpeg", ".png", ".tiff", ".heic", ".heif", ".webp",
}

# File extensions we know are binary/media — skip content extraction
_SKIP_EXTENSIONS: Set[str] = {
    ".exe", ".dll", ".so", ".dylib", ".bin", ".dat", ".db", ".sqlite",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".mp3", ".mp4", ".avi", ".mov", ".mkv", ".flac", ".wav", ".aac",
    ".gif", ".bmp", ".ico", ".svg",
    ".iso", ".img", ".dmg", ".vmdk",
    ".pyc", ".pyo", ".class", ".o", ".obj", ".wasm",
}


def _extract_text_file(path: str, max_bytes: int = 100_000) -> str:
    """Read plain text files."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(max_bytes)
    except Exception:
        return ""


def _extract_csv(path: str, max_bytes: int = 100_000) -> str:
    """Read CSV files — headers + first N rows."""
    try:
        import csv
        lines = []
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if i > 200:
                    break
                lines.append(" | ".join(row))
        return "\n".join(lines)[:max_bytes]
    except Exception:
        return ""


def _extract_pdf(path: str, max_pages: int = 20) -> str:
    """Extract text from PDF files using PyPDF2 or pdfplumber."""
    try:
        import pypdf
        reader = pypdf.PdfReader(path)
        pages = []
        for i, page in enumerate(reader.pages):
            if i >= max_pages:
                break
            text = page.extract_text()
            if text:
                pages.append(text)
        return "\n".join(pages)[:100_000]
    except ImportError:
        pass
    except Exception:
        return ""

    # Fallback: pdfplumber
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            pages = []
            for i, page in enumerate(pdf.pages):
                if i >= max_pages:
                    break
                text = page.extract_text()
                if text:
                    pages.append(text)
            return "\n".join(pages)[:100_000]
    except ImportError:
        return ""
    except Exception:
        return ""


def _extract_docx(path: str) -> str:
    """Extract text from .docx files."""
    try:
        import zipfile
        import xml.etree.ElementTree as ET

        with zipfile.ZipFile(path, "r") as z:
            with z.open("word/document.xml") as f:
                tree = ET.parse(f)
                # Strip namespaces and get all text
                ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                paragraphs = tree.findall(".//w:p", ns)
                text_parts = []
                for p in paragraphs:
                    runs = p.findall(".//w:t", ns)
                    line = "".join(r.text or "" for r in runs)
                    if line.strip():
                        text_parts.append(line)
                return "\n".join(text_parts)[:100_000]
    except Exception:
        return ""


def _extract_xlsx(path: str) -> str:
    """Extract text from .xlsx files — sheet names + cell values."""
    try:
        import zipfile
        import xml.etree.ElementTree as ET

        with zipfile.ZipFile(path, "r") as z:
            # Read shared strings
            strings = []
            try:
                with z.open("xl/sharedStrings.xml") as f:
                    tree = ET.parse(f)
                    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                    for si in tree.findall(".//s:t", ns):
                        strings.append(si.text or "")
            except KeyError:
                pass

            # Read first sheet
            try:
                with z.open("xl/worksheets/sheet1.xml") as f:
                    tree = ET.parse(f)
                    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                    rows = tree.findall(".//s:row", ns)
                    lines = []
                    for row in rows[:200]:
                        cells = row.findall("s:c", ns)
                        values = []
                        for c in cells:
                            v = c.find("s:v", ns)
                            if v is not None and v.text:
                                # If type is 's', look up shared string
                                if c.get("t") == "s":
                                    idx = int(v.text)
                                    values.append(strings[idx] if idx < len(strings) else v.text)
                                else:
                                    values.append(v.text)
                        if values:
                            lines.append(" | ".join(values))
                    return "\n".join(lines)[:100_000]
            except KeyError:
                pass
        return " ".join(strings)[:100_000] if strings else ""
    except Exception:
        return ""


def _extract_image_metadata(path: str) -> str:
    """Extract EXIF metadata from images — GPS location, date, camera, dimensions."""
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS, GPSTAGS
    except ImportError:
        return ""

    parts: list[str] = []
    try:
        with Image.open(path) as img:
            w, h = img.size
            parts.append(f"Image: {w}x{h} {img.format or ''}")

            exif = img.getexif()
            if not exif:
                return " ".join(parts)

            # Camera / device
            make = exif.get(0x010F, "")   # Make
            model = exif.get(0x0110, "")  # Model
            if make or model:
                parts.append(f"Camera: {make} {model}".strip())

            # Date taken
            date = exif.get(0x9003) or exif.get(0x0132)  # DateTimeOriginal or DateTime
            if date:
                parts.append(f"Date: {date}")

            # Description / Title / Comments
            desc = exif.get(0x010E, "")  # ImageDescription
            if desc:
                parts.append(f"Description: {desc}")
            user_comment = exif.get(0x9286, "")  # UserComment
            if user_comment and isinstance(user_comment, str):
                parts.append(f"Comment: {user_comment}")

            # GPS data
            gps_ifd = exif.get_ifd(0x8825)  # GPSInfo IFD
            if gps_ifd:
                lat = _gps_to_decimal(
                    gps_ifd.get(2), gps_ifd.get(1)  # GPSLatitude, GPSLatitudeRef
                )
                lon = _gps_to_decimal(
                    gps_ifd.get(4), gps_ifd.get(3)  # GPSLongitude, GPSLongitudeRef
                )
                if lat is not None and lon is not None:
                    parts.append(f"GPS: {lat:.6f}, {lon:.6f}")
                    place = _reverse_geocode_offline(lat, lon)
                    if place:
                        parts.append(f"Location: {place}")

    except Exception:
        pass

    return " | ".join(parts)


def _gps_to_decimal(
    coords: tuple | None, ref: str | None
) -> float | None:
    """Convert EXIF GPS coordinates (degrees, minutes, seconds) to decimal."""
    if not coords or not ref:
        return None
    try:
        d, m, s = [float(c) for c in coords]
        decimal = d + m / 60 + s / 3600
        if ref in ("S", "W"):
            decimal = -decimal
        return decimal
    except (ValueError, TypeError, ZeroDivisionError):
        return None


def _reverse_geocode_offline(lat: float, lon: float) -> str:
    """Best-effort offline reverse geocode using coarse lat/lon regions.

    Returns continent/region + country-level name. No network calls.
    """
    # Coarse bounding-box lookup — covers major regions people photograph
    _REGIONS = [
        # Africa
        ((-35, -20), (38, 52), "Africa"),
        # Europe
        ((35, -25), (72, 45), "Europe"),
        # North America
        ((15, -170), (72, -50), "North America"),
        # South America
        ((-56, -82), (13, -34), "South America"),
        # Asia
        ((1, 45), (55, 145), "Asia"),
        # Middle East
        ((12, 25), (42, 63), "Middle East"),
        # Oceania / Australia
        ((-50, 110), (0, 180), "Oceania"),
        # Antarctica
        ((-90, -180), (-60, 180), "Antarctica"),
        # Caribbean
        ((10, -90), (27, -58), "Caribbean"),
    ]

    # Finer country-level boxes for popular destinations
    _COUNTRIES = [
        ((25.0, -125.0), (50.0, -66.0), "United States"),
        ((41.0, -5.5), (51.5, 10.0), "France"),
        ((36.0, -9.5), (43.8, 3.4), "Spain"),
        ((35.5, 6.6), (47.1, 18.5), "Italy"),
        ((47.3, 5.9), (55.1, 15.0), "Germany"),
        ((49.9, -8.2), (60.9, 1.8), "United Kingdom"),
        ((24.4, 122.9), (45.6, 153.0), "Japan"),
        ((18.2, 97.3), (53.6, 135.1), "China"),
        ((-8.7, 95.0), (5.9, 141.0), "Indonesia"),
        ((6.0, 68.0), (35.5, 97.4), "India"),
        ((-34.8, 16.5), (-22.1, 32.9), "South Africa"),
        ((-4.7, 29.0), (4.2, 35.0), "East Africa"),
        ((4.0, -1.2), (11.2, 1.2), "Ghana"),
        ((4.2, 2.7), (13.9, 14.7), "Nigeria"),
        ((-1.5, 29.0), (1.5, 30.0), "Rwanda"),
        ((-11.7, 25.0), (5.4, 31.3), "Congo"),
        ((-26.9, -58.0), (5.3, -34.8), "Brazil"),
        ((14.5, -92.0), (32.7, -86.7), "Mexico"),
        ((-47.0, 166.0), (-34.0, 178.5), "New Zealand"),
        ((-44.0, 113.0), (-10.0, 154.0), "Australia"),
        ((33.0, 34.0), (37.3, 36.6), "Turkey"),
        ((25.0, 51.0), (26.3, 56.4), "UAE"),
        ((29.0, 34.2), (33.3, 39.2), "Jordan"),
        ((51.0, -10.5), (55.4, -5.5), "Ireland"),
        ((59.0, 4.5), (71.2, 31.2), "Norway"),
        ((36.4, 19.4), (41.7, 29.7), "Greece"),
        ((-18.3, 43.2), (-12.0, 50.5), "Madagascar"),
        ((-17.8, 25.3), (-8.2, 33.7), "Zambia"),
        ((-26.9, 20.0), (-17.8, 33.0), "Botswana"),
        ((-15.0, 32.7), (-9.4, 35.9), "Malawi"),
        ((-22.4, 29.4), (-15.6, 33.1), "Zimbabwe"),
        ((-1.5, 33.9), (4.2, 41.9), "Kenya"),
        ((-11.7, 29.3), (-1.0, 40.5), "Tanzania"),
        ((-1.4, 29.6), (4.2, 35.0), "Uganda"),
        ((9.4, -17.6), (15.0, -11.4), "Senegal"),
        ((21.3, -17.1), (27.7, -1.0), "Western Sahara"),
        ((27.7, -13.2), (35.9, -1.0), "Morocco"),
        ((19.0, 9.4), (23.5, 16.0), "Niger"),
        ((30.2, 24.7), (31.7, 34.9), "Egypt"),
        ((8.0, -12.3), (15.0, -7.5), "Guinea"),
    ]

    # Try fine-grained first
    for (lat1, lon1), (lat2, lon2), name in _COUNTRIES:
        if lat1 <= lat <= lat2 and lon1 <= lon <= lon2:
            return name

    # Fall back to region
    for (lat1, lon1), (lat2, lon2), name in _REGIONS:
        if lat1 <= lat <= lat2 and lon1 <= lon <= lon2:
            return name

    return ""


def extract_content(path: str, ext: str) -> str:
    """Extract text content from a file based on its extension."""
    ext = ext.lower()

    if ext in _SKIP_EXTENSIONS:
        return ""
    if ext in _IMAGE_EXTENSIONS:
        return _extract_image_metadata(path)
    if ext in (".csv", ".tsv"):
        return _extract_csv(path)
    if ext == ".pdf":
        return _extract_pdf(path)
    if ext in (".docx",):
        return _extract_docx(path)
    if ext in (".xlsx",):
        return _extract_xlsx(path)
    if ext in _TEXT_EXTENSIONS:
        return _extract_text_file(path)
    # Unknown extension — try reading as text, but limit
    try:
        with open(path, "r", encoding="utf-8", errors="strict") as f:
            sample = f.read(1000)
            # If it looks like text, read more
            if sample.isprintable() or "\n" in sample:
                return sample + f.read(99_000)
    except (UnicodeDecodeError, Exception):
        pass
    return ""


# ---------------------------------------------------------------------------
# File metadata helper
# ---------------------------------------------------------------------------

def _file_checksum(path: str, size: int) -> str:
    """Fast checksum based on path + size + mtime. No file reads needed."""
    try:
        mtime = os.path.getmtime(path)
        return hashlib.md5(f"{path}|{size}|{mtime}".encode()).hexdigest()
    except OSError:
        return ""


def _file_to_dataobject(
    path: str,
    stat_result: os.stat_result,
    content: str = "",
    home_dir: str = "",
) -> DataObject:
    """Convert a file path + stat to a DataObject."""
    name = os.path.basename(path)
    ext = os.path.splitext(name)[1].lower()
    size = stat_result.st_size
    mtime = datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc)

    # Build a readable relative path for the body
    display_path = path
    if home_dir and path.startswith(home_dir):
        display_path = "~" + path[len(home_dir):]

    # Body: path info + content snippet
    body_parts = [f"Path: {display_path}"]
    body_parts.append(f"Size: {_human_size(size)}")
    body_parts.append(f"Type: {ext or 'unknown'}")
    if content:
        # First ~500 chars of content for indexing
        snippet = content[:500].strip()
        if snippet:
            body_parts.append(f"Content: {snippet}")

    return DataObject(
        source="local_files",
        source_id=path,  # Full path is unique ID
        kind=ObjectKind.FILE,
        title=name,
        body="\n".join(body_parts),
        timestamp=mtime,
        labels=[ext] if ext else [],
        url=_path_to_url(path),
        raw={
            "path": path,
            "name": name,
            "extension": ext,
            "size": size,
            "modified": mtime.isoformat(),
            "directory": os.path.dirname(path),
        },
    )


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(size) < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _path_to_url(path: str) -> str:
    """Convert file path to file:// URL for opening."""
    from urllib.parse import quote
    if platform.system() == "Windows":
        return "file:///" + quote(path.replace("\\", "/"), safe=":/")
    return "file://" + quote(path, safe="/")


# ---------------------------------------------------------------------------
# Scanner — Phase 1 (metadata) + Phase 2 (content)
# ---------------------------------------------------------------------------

class ScanProgress:
    """Track scan progress for status reporting."""
    def __init__(self):
        self.phase: str = "idle"
        self.files_found: int = 0
        self.files_indexed: int = 0
        self.files_skipped: int = 0
        self.files_with_content: int = 0
        self.directories_scanned: int = 0
        self.errors: int = 0
        self.start_time: float = 0
        self.elapsed_ms: float = 0
        self.current_directory: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "phase": self.phase,
            "files_found": self.files_found,
            "files_indexed": self.files_indexed,
            "files_skipped": self.files_skipped,
            "files_with_content": self.files_with_content,
            "directories_scanned": self.directories_scanned,
            "errors": self.errors,
            "elapsed_ms": round(self.elapsed_ms, 1),
        }


class LocalFileScanner:
    """Background file scanner and indexer.

    Usage:
        settings = FileIndexSettings(enabled=True, scan_directories=[...])
        scanner = LocalFileScanner(index, settings)
        await scanner.start()     # non-blocking, runs in background
        scanner.status            # check progress
        await scanner.stop()      # clean shutdown
    """

    def __init__(
        self,
        index: Index,
        settings: FileIndexSettings,
        semantic_search: Any = None,
    ):
        self._index = index
        self._settings = settings
        self._semantic_search = semantic_search
        self._progress = ScanProgress()
        self._running = False
        self._force = False
        self._scan_task: Optional[asyncio.Task] = None
        self._watcher_task: Optional[asyncio.Task] = None
        self._home = str(Path.home())

    @property
    def status(self) -> Dict[str, Any]:
        return {
            "enabled": self._settings.enabled,
            "running": self._running,
            "progress": self._progress.to_dict(),
            "settings": self._settings.to_dict(),
        }

    async def start(self, force: bool = False) -> bool:
        """Start background scanning. force=True skips checksum dedup."""
        if not self._settings.enabled:
            logger.info("Local file indexing is disabled (opt-in required)")
            return False

        if self._running:
            return True

        self._force = force

        # Validate directories exist
        dirs = self._settings.scan_directories or FileIndexSettings.default_directories()
        valid_dirs = [d for d in dirs if os.path.isdir(d)]
        if not valid_dirs:
            logger.warning("No valid scan directories found")
            return False

        self._settings.scan_directories = valid_dirs
        self._running = True
        self._scan_task = asyncio.create_task(self._run_scan())
        logger.info(f"Local file scanner started: {len(valid_dirs)} directories")
        return True

    async def stop(self):
        """Stop scanning and file watching."""
        self._running = False
        if self._scan_task and not self._scan_task.done():
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass
        if self._watcher_task and not self._watcher_task.done():
            self._watcher_task.cancel()
            try:
                await self._watcher_task
            except asyncio.CancelledError:
                pass
        logger.info("Local file scanner stopped")

    # -------------------------------------------------------------------
    # Internal — scan pipeline
    # -------------------------------------------------------------------

    async def _run_scan(self):
        """Full scan pipeline: metadata → content → embeddings."""
        self._progress.start_time = time.perf_counter()

        try:
            # Phase 1: Metadata scan
            self._progress.phase = "scanning"
            all_files = await self._scan_metadata()

            if not self._running:
                return

            # Phase 2: Content extraction (if enabled)
            if self._settings.extract_content:
                self._progress.phase = "extracting"
                await self._extract_and_index(all_files)
            else:
                # Index metadata only
                await self._index_metadata_only(all_files)

            self._progress.elapsed_ms = (time.perf_counter() - self._progress.start_time) * 1000

            # Phase 3: Embeddings (if enabled + semantic search available)
            if self._settings.embed_content and self._semantic_search:
                self._progress.phase = "embedding"
                try:
                    count = await self._semantic_search.embed_all()
                    logger.info(f"Embedded {count} local file objects")
                except Exception as e:
                    logger.warning(f"Embedding local files failed (non-fatal): {e}")

            self._progress.phase = "complete"
            self._progress.elapsed_ms = (time.perf_counter() - self._progress.start_time) * 1000
            logger.info(
                f"Local file scan complete: {self._progress.files_indexed} files "
                f"in {self._progress.elapsed_ms:.0f}ms"
            )

            # Phase 4: Start file watcher for incremental updates
            if self._settings.watch_for_changes and self._running:
                self._progress.phase = "watching"
                self._watcher_task = asyncio.create_task(self._watch_loop())

        except asyncio.CancelledError:
            self._progress.phase = "cancelled"
            raise
        except Exception as e:
            self._progress.phase = "error"
            logger.error(f"Local file scan failed: {e}")

    async def _scan_metadata(self) -> List[Tuple[str, os.stat_result]]:
        """Phase 1: Walk directories and collect file metadata."""
        all_files: List[Tuple[str, os.stat_result]] = []
        max_size = int(self._settings.max_file_size_mb * 1024 * 1024)

        loop = asyncio.get_event_loop()

        for scan_dir in self._settings.scan_directories:
            if not self._running:
                break

            # Run the blocking I/O in a thread to avoid blocking the event loop
            files = await loop.run_in_executor(
                None, self._walk_directory, scan_dir, max_size
            )
            all_files.extend(files)

        self._progress.files_found = len(all_files)
        logger.info(
            f"Metadata scan: {len(all_files)} files in "
            f"{self._progress.directories_scanned} directories"
        )
        return all_files

    def _walk_directory(
        self, root: str, max_size: int
    ) -> List[Tuple[str, os.stat_result]]:
        """Synchronous directory walk using os.scandir (fast)."""
        files: List[Tuple[str, os.stat_result]] = []
        exclude = set(self._settings.exclude_patterns)

        try:
            for entry in os.scandir(root):
                try:
                    name = entry.name

                    # Skip hidden files unless configured
                    if not self._settings.scan_hidden and name.startswith("."):
                        continue

                    # Skip excluded patterns
                    if name in exclude:
                        continue

                    if entry.is_dir(follow_symlinks=False):
                        # Recurse into subdirectories
                        self._progress.directories_scanned += 1
                        sub_files = self._walk_directory(entry.path, max_size)
                        files.extend(sub_files)
                    elif entry.is_file(follow_symlinks=False):
                        st = entry.stat(follow_symlinks=False)
                        # Skip files that are too large
                        if st.st_size > max_size:
                            self._progress.files_skipped += 1
                            continue
                        # Skip empty files
                        if st.st_size == 0:
                            self._progress.files_skipped += 1
                            continue
                        files.append((entry.path, st))
                except PermissionError:
                    self._progress.errors += 1
                except OSError:
                    self._progress.errors += 1
        except PermissionError:
            self._progress.errors += 1
        except OSError:
            self._progress.errors += 1

        return files

    async def _index_metadata_only(self, files: List[Tuple[str, os.stat_result]]):
        """Index file metadata without content extraction."""
        batch: List[DataObject] = []
        loop = asyncio.get_event_loop()

        for i, (path, st) in enumerate(files):
            if not self._running:
                break

            # Check if already indexed with same checksum (skip if force)
            checksum = _file_checksum(path, st.st_size)
            if not self._force:
                existing = self._index._conn.execute(
                    "SELECT checksum FROM data_objects WHERE id = ?",
                    (f"local_files:{path}",)
                ).fetchone()
                if existing and existing[0] == checksum:
                    self._progress.files_skipped += 1
                    continue

            obj = _file_to_dataobject(path, st, home_dir=self._home)
            obj.checksum = checksum
            batch.append(obj)

            if len(batch) >= self._settings.batch_size:
                self._index.upsert_batch(batch)
                self._progress.files_indexed += len(batch)
                batch.clear()
                # Yield to event loop
                await asyncio.sleep(self._settings.batch_delay_ms / 1000)

        if batch:
            self._index.upsert_batch(batch)
            self._progress.files_indexed += len(batch)

    async def _extract_and_index(self, files: List[Tuple[str, os.stat_result]]):
        """Phase 2: Extract content and index files in batches."""
        batch: List[DataObject] = []
        loop = asyncio.get_event_loop()

        for i, (path, st) in enumerate(files):
            if not self._running:
                break

            # Check if already indexed with same checksum (skip if force)
            checksum = _file_checksum(path, st.st_size)
            if not self._force:
                existing = self._index._conn.execute(
                    "SELECT checksum FROM data_objects WHERE id = ?",
                    (f"local_files:{path}",)
                ).fetchone()
                if existing and existing[0] == checksum:
                    self._progress.files_skipped += 1
                    continue

            # Extract content in thread pool (blocking I/O)
            ext = os.path.splitext(path)[1].lower()
            content = ""
            if ext not in _SKIP_EXTENSIONS:
                try:
                    content = await loop.run_in_executor(
                        None, extract_content, path, ext
                    )
                    if content:
                        self._progress.files_with_content += 1
                except Exception:
                    self._progress.errors += 1

            obj = _file_to_dataobject(path, st, content=content, home_dir=self._home)
            obj.checksum = checksum
            batch.append(obj)

            if len(batch) >= self._settings.batch_size:
                self._index.upsert_batch(batch)
                self._progress.files_indexed += len(batch)
                batch.clear()
                # Yield to event loop — batch delay for non-intrusive scanning
                await asyncio.sleep(self._settings.batch_delay_ms / 1000)

        if batch:
            self._index.upsert_batch(batch)
            self._progress.files_indexed += len(batch)

    # -------------------------------------------------------------------
    # Phase 4: File watcher — incremental updates
    # -------------------------------------------------------------------

    async def _watch_loop(self):
        """Watch for file changes using watchdog (inotify/FSEvents/kqueue).
        
        Falls back to 30s polling if watchdog is not installed.
        """
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
            await self._watch_with_watchdog(Observer, FileSystemEventHandler)
        except ImportError:
            logger.info("watchdog not installed — falling back to 30s polling")
            await self._watch_poll()

    async def _watch_with_watchdog(self, Observer, FileSystemEventHandler):
        """Use watchdog for efficient OS-level file change notifications."""
        import queue
        change_queue = queue.Queue()

        class _Handler(FileSystemEventHandler):
            def on_any_event(self, event):
                if not event.is_directory:
                    change_queue.put(event.src_path)

        observer = Observer()
        handler = _Handler()
        for scan_dir in self._settings.scan_directories:
            if os.path.isdir(scan_dir):
                observer.schedule(handler, scan_dir, recursive=True)

        observer.start()
        logger.info(f"File watcher started (watchdog, {len(self._settings.scan_directories)} dirs)")

        try:
            while self._running:
                # Drain the queue in batches every 5 seconds
                await asyncio.sleep(5)
                if not self._running:
                    break

                paths = set()
                while not change_queue.empty():
                    try:
                        paths.add(change_queue.get_nowait())
                    except queue.Empty:
                        break

                if paths:
                    loop = asyncio.get_event_loop()
                    changes = await loop.run_in_executor(
                        None, self._detect_changes
                    )
                    if changes:
                        await self._process_changes(changes)
        except asyncio.CancelledError:
            pass
        finally:
            observer.stop()
            observer.join(timeout=5)

    async def _watch_poll(self):
        """Fallback: poll for file changes every 30 seconds."""
        logger.info("File watcher started (30s poll interval)")

        while self._running:
            try:
                await asyncio.sleep(30)
                if not self._running:
                    break

                loop = asyncio.get_event_loop()
                changes = await loop.run_in_executor(
                    None, self._detect_changes
                )

                if changes:
                    await self._process_changes(changes)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"File watch error: {e}")
                await asyncio.sleep(60)

    def _detect_changes(self) -> List[Tuple[str, str, Optional[os.stat_result]]]:
        """Detect file changes since last scan.

        Returns list of (path, change_type, stat) where change_type is
        'modified', 'created', or 'deleted'.
        """
        changes: List[Tuple[str, str, Optional[os.stat_result]]] = []
        max_size = int(self._settings.max_file_size_mb * 1024 * 1024)
        seen_paths: Set[str] = set()

        # Check current files on disk
        for scan_dir in self._settings.scan_directories:
            for path, st in self._walk_directory(scan_dir, max_size):
                seen_paths.add(path)
                checksum = _file_checksum(path, st.st_size)
                existing = self._index._conn.execute(
                    "SELECT checksum FROM data_objects WHERE id = ?",
                    (f"local_files:{path}",)
                ).fetchone()

                if not existing:
                    changes.append((path, "created", st))
                elif existing[0] != checksum:
                    changes.append((path, "modified", st))

        # Check for deleted files — files in index but not on disk
        indexed = self._index._conn.execute(
            "SELECT source_id FROM data_objects WHERE source = 'local_files'"
        ).fetchall()
        for row in indexed:
            if row[0] not in seen_paths:
                changes.append((row[0], "deleted", None))

        return changes[:1000]  # Cap at 1000 changes per cycle

    async def _process_changes(
        self, changes: List[Tuple[str, str, Optional[os.stat_result]]]
    ):
        """Process detected file changes."""
        loop = asyncio.get_event_loop()
        to_upsert: List[DataObject] = []
        to_delete: List[str] = []

        for path, change_type, st in changes:
            if change_type == "deleted":
                to_delete.append(f"local_files:{path}")
            else:
                ext = os.path.splitext(path)[1].lower()
                content = ""
                if self._settings.extract_content and ext not in _SKIP_EXTENSIONS:
                    try:
                        content = await loop.run_in_executor(
                            None, extract_content, path, ext
                        )
                    except Exception:
                        pass
                obj = _file_to_dataobject(path, st, content=content, home_dir=self._home)
                obj.checksum = _file_checksum(path, st.st_size)
                to_upsert.append(obj)

        if to_upsert:
            self._index.upsert_batch(to_upsert)
        if to_delete:
            for obj_id in to_delete:
                try:
                    self._index._conn.execute(
                        "DELETE FROM data_objects WHERE id = ?", (obj_id,)
                    )
                except Exception:
                    pass
            self._index._conn.commit()

        # Embed new/modified files
        if to_upsert and self._semantic_search and self._settings.embed_content:
            try:
                await self._semantic_search.embed_objects(to_upsert)
            except Exception as e:
                logger.warning(f"Embedding file changes failed: {e}")

        logger.info(
            f"File watcher: {len(to_upsert)} upserted, "
            f"{len(to_delete)} deleted"
        )


# ---------------------------------------------------------------------------
# Settings persistence — SQLite-backed
# ---------------------------------------------------------------------------

_SETTINGS_KEY = "local_file_index_settings"


def load_settings(index: Index) -> FileIndexSettings:
    """Load settings from the index database."""
    try:
        row = index._conn.execute(
            "SELECT value FROM settings WHERE key = ?", (_SETTINGS_KEY,)
        ).fetchone()
        if row:
            return FileIndexSettings.from_dict(json.loads(row[0]))
    except Exception:
        # Settings table may not exist yet
        try:
            index._conn.execute(
                "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)"
            )
            index._conn.commit()
        except Exception:
            pass
    return FileIndexSettings()


def save_settings(index: Index, settings: FileIndexSettings):
    """Save settings to the index database."""
    try:
        index._conn.execute(
            "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)"
        )
        index._conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (_SETTINGS_KEY, json.dumps(settings.to_dict())),
        )
        index._conn.commit()
    except Exception as e:
        logger.error(f"Failed to save file index settings: {e}")
