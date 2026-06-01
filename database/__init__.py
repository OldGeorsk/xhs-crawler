"""
Database module — SQLite-backed state storage.

The database is the source of truth for synchronization state.
Manages creators, notes, and media records.

Tables:
    - creators: tracked creator profiles and sync timestamps
    - notes: collected note metadata and local paths
    - media: individual media file records linked to notes
"""

from .db_manager import DatabaseManager

__all__ = ["DatabaseManager"]
