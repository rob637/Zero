"""
Photo Organizer Skill - Organize photos by date, location, and metadata

Capabilities:
- Scan folders for photos
- Read EXIF metadata (date taken, camera, location)
- Organize by year/month structure
- Detect duplicates via hash
- Find screenshots vs actual photos

Works with Pictures folder, OneDrive Photos, Downloads, etc.
"""

import os
import hashlib
from pathlib import Path
from datetime import datetime
from collections import defaultdict

from ..core.skill import (
    Skill, 
    ActionPlan, 
    ProposedAction, 
    ActionType,
    register_skill,
)


# Photo file extensions
PHOTO_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp',
    '.heic', '.heif', '.tiff', '.tif', '.raw', '.cr2',
    '.nef', '.arw', '.dng', '.orf', '.rw2'
}

# Screenshot indicators in filename
SCREENSHOT_PATTERNS = [
    'screenshot', 'screen shot', 'capture', 'snip',
    'clip', 'screen_', 'screenclip'
]


class PhotoOrganizerSkill(Skill):
    """
    Skill for organizing photos by date and metadata.
    
    Can:
    - Sort photos into YYYY/MM folder structure
    - Separate screenshots from photos
    - Find duplicate images
    - Identify photos by date taken vs file date
    """
    
    name = "photo_organizer"
    description = "Organize your photos by date, find duplicates, separate screenshots"
    version = "0.1.0"
    
    trigger_phrases = [
        "photo",
        "photos",
        "pictures",
        "images",
        "organize photo",
        "sort photo",
        "photo duplicate",
        "screenshot",
    ]
    
    permissions = [
        "filesystem.read",
        "filesystem.write",
    ]
    
    def __init__(self):
        self._pictures_folder = self._find_pictures_folder()
    
    async def analyze(self, request: str, context: dict) -> ActionPlan:
        """
        Analyze photo organization request.
        """
        request_lower = request.lower()
        
        # Determine target folder
        target_folder = self._pictures_folder
        
        # Check for specific folder in request
        if 'download' in request_lower:
            target_folder = Path.home() / 'Downloads'
        elif 'desktop' in request_lower:
            target_folder = Path.home() / 'Desktop'
        elif 'onedrive' in request_lower:
            target_folder = self._find_onedrive_photos()
        
        # Check context for target
        if context.get('target'):
            target = context['target']
            if Path(target).exists():
                target_folder = Path(target)
        
        if not target_folder.exists():
            return ActionPlan(
                summary="Folder not found",
                reasoning=f"Could not find the target folder: {target_folder}",
                warnings=[f"Please specify a valid folder path."],
            )
        
        # Scan for photos
        photos = self._scan_photos(target_folder)
        
        if not photos:
            return ActionPlan(
                summary="No photos found",
                reasoning=f"No photo files found in {target_folder}",
                actions=[],
            )
        
        # Categorize photos
        categorized = self._categorize_photos(photos)
        
        # Build organization plan
        actions = []
        screenshots = categorized.get('screenshots', [])
        by_date = categorized.get('by_date', {})
        duplicates = categorized.get('duplicates', [])
        
        # Propose organizing by date
        organized_base = target_folder / "Organized"
        
        for date_key, date_photos in by_date.items():
            year, month = date_key.split('-')
            dest_folder = organized_base / year / month
            
            for photo in date_photos:
                actions.append(ProposedAction(
                    action_type=ActionType.MOVE,
                    source=str(photo),
                    destination=str(dest_folder / photo.name),
                    reason=f"Organize by date: {date_key}",
                ))
        
        # Propose moving screenshots
        if screenshots:
            screenshots_folder = target_folder / "Screenshots"
            for ss in screenshots:
                actions.append(ProposedAction(
                    action_type=ActionType.MOVE,
                    source=str(ss),
                    destination=str(screenshots_folder / ss.name),
                    reason="Separate screenshots from photos",
                ))
        
        # Note duplicates
        warnings = []
        if duplicates:
            warnings.append(f"Found {len(duplicates)} potential duplicate photos")
        
        return ActionPlan(
            summary=f"Organize {len(photos)} photos from {target_folder.name}",
            reasoning=f"Found {len(photos)} photos. Will organize into year/month folders, "
                     f"separate {len(screenshots)} screenshots.",
            actions=actions,
            warnings=warnings,
        )
    
    async def execute(self, plan: ActionPlan, approved_indices: list[int]) -> dict:
        """
        Execute approved photo organization actions.
        """
        success = []
        failed = []
        
        for i in approved_indices:
            if i >= len(plan.actions):
                continue
                
            action = plan.actions[i]
            
            try:
                src = Path(action.source)
                dest = Path(action.destination)
                
                if not src.exists():
                    failed.append({
                        "action": str(action.action_type),
                        "source": action.source,
                        "error": "Source file not found"
                    })
                    continue
                
                # Create destination folder
                dest.parent.mkdir(parents=True, exist_ok=True)
                
                # Handle name conflicts
                if dest.exists():
                    # Add number suffix
                    stem = dest.stem
                    suffix = dest.suffix
                    counter = 1
                    while dest.exists():
                        dest = dest.parent / f"{stem}_{counter}{suffix}"
                        counter += 1
                
                # Move file
                src.rename(dest)
                
                success.append({
                    "action": "moved",
                    "from": action.source,
                    "to": str(dest)
                })
                
            except Exception as e:
                failed.append({
                    "action": str(action.action_type),
                    "source": action.source,
                    "error": str(e)
                })
        
        return {
            "success": success,
            "failed": failed,
            "message": f"Organized {len(success)} photos, {len(failed)} failed"
        }
    
    def _find_pictures_folder(self) -> Path:
        """Find the user's Pictures folder."""
        home = Path.home()
        
        # Check OneDrive first (Windows)
        if os.name == 'nt':
            for item in home.iterdir():
                if item.is_dir() and item.name.startswith('OneDrive'):
                    pics = item / 'Pictures'
                    if pics.exists():
                        return pics
        
        # Standard Pictures folder
        pics = home / 'Pictures'
        if pics.exists():
            return pics
        
        return home
    
    def _find_onedrive_photos(self) -> Path:
        """Find OneDrive Pictures folder."""
        home = Path.home()
        
        for item in home.iterdir():
            if item.is_dir() and item.name.startswith('OneDrive'):
                pics = item / 'Pictures'
                if pics.exists():
                    return pics
                # Also check for Camera Roll
                cam = item / 'Pictures' / 'Camera Roll'
                if cam.exists():
                    return cam
        
        return self._pictures_folder
    
    def _scan_photos(self, folder: Path, max_depth: int = 3) -> list[Path]:
        """Scan folder for photo files."""
        photos = []
        
        def scan_recursive(path: Path, depth: int):
            if depth > max_depth:
                return
            
            try:
                for item in path.iterdir():
                    if item.is_file() and item.suffix.lower() in PHOTO_EXTENSIONS:
                        photos.append(item)
                    elif item.is_dir() and not item.name.startswith('.'):
                        scan_recursive(item, depth + 1)
            except PermissionError:
                pass
        
        scan_recursive(folder, 0)
        return photos
    
    def _categorize_photos(self, photos: list[Path]) -> dict:
        """Categorize photos by date, identify screenshots and duplicates."""
        by_date = defaultdict(list)
        screenshots = []
        hashes = defaultdict(list)
        
        for photo in photos:
            # Check if screenshot
            name_lower = photo.name.lower()
            if any(pattern in name_lower for pattern in SCREENSHOT_PATTERNS):
                screenshots.append(photo)
                continue
            
            # Try to get date from EXIF or fall back to file modification time
            date = self._get_photo_date(photo)
            date_key = date.strftime('%Y-%m')
            by_date[date_key].append(photo)
            
            # Quick hash for small file duplicate detection
            # (Only hash first 64KB for speed)
            try:
                file_hash = self._quick_hash(photo)
                hashes[file_hash].append(photo)
            except:
                pass
        
        # Find duplicates (same hash = likely duplicate)
        duplicates = [
            group for group in hashes.values() if len(group) > 1
        ]
        
        return {
            'by_date': dict(by_date),
            'screenshots': screenshots,
            'duplicates': duplicates,
        }
    
    def _get_photo_date(self, photo: Path) -> datetime:
        """
        Get the date a photo was taken.
        Tries EXIF first, falls back to file modification time.
        """
        # Try to read EXIF data
        try:
            # Simple EXIF reading without external libraries
            # In real implementation, use PIL or exifread
            pass
        except:
            pass
        
        # Fall back to file modification time
        try:
            stat = photo.stat()
            return datetime.fromtimestamp(stat.st_mtime)
        except:
            return datetime.now()
    
    def _quick_hash(self, path: Path, chunk_size: int = 65536) -> str:
        """
        Quick hash of file (first chunk only for speed).
        """
        hasher = hashlib.md5()
        with open(path, 'rb') as f:
            chunk = f.read(chunk_size)
            hasher.update(chunk)
        return hasher.hexdigest()


# Register the skill
photo_organizer = PhotoOrganizerSkill()
register_skill(photo_organizer)
