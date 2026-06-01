"""
Sync module — coordinates the full synchronization workflow.

Orchestrates the interaction between Crawler, Downloader, Database,
and Archive modules:

    1. Load creators from config
    2. Open creator profile
    3. Collect note information
    4. Compare with local database
    5. Download only new notes
    6. Archive content
    7. Update database

Supports incremental synchronization: already-downloaded notes
are never downloaded again.
"""

from .synchronizer import Synchronizer

__all__ = ["Synchronizer"]
