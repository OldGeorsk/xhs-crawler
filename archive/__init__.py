"""
Archive module — manages the local filesystem archive.

Organizes downloaded content into the archive structure:

    downloads/creator_name/YYYY-MM-DD_noteid_title/
        metadata.json
        note.txt
        cover.jpg
        01.jpg
        02.jpg
        video.mp4

Each note folder is a complete, self-contained archive unit.
"""

from .archiver import Archiver

__all__ = ["Archiver"]
