"""
Skills package - All Apex capabilities live here

Each skill is a self-contained capability that:
1. Understands a domain (files, calendar, browser, etc.)
2. Generates plans for user approval
3. Executes approved actions safely
"""

from .file_organizer import FileOrganizerSkill

__all__ = ["FileOrganizerSkill"]
