"""
Phase 2: Archive manager.

Creates and manages the local filesystem archive for downloaded notes.

Archive structure (per CLAUDE.md):
    downloads/creator_name/YYYY-MM-DD_noteid_title/
        metadata.json   — machine-readable metadata
        note.txt        — human-readable content
        cover.jpg       — cover image
        01.jpg, 02.jpg  — images (deterministic naming)
        video.mp4       — video (if present)
"""

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional


class Archiver:
    """
    Manages the local archive filesystem.

    Creates per-note folders with standardised naming and writes
    metadata.json + note.txt for future searchability.
    """

    def __init__(self, base_dir: str = "downloads"):
        self.base_dir = Path(base_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_note_folder(
        self,
        creator_name: str,
        note_id: str,
        title: str,
        publish_time: Optional[str] = None,
    ) -> Path:
        """
        Create the archive folder for a single note.

        Folder name: ``YYYY-MM-DD_noteid_sanitised_title``

        Returns the created Path.
        """
        date_str = self._format_date(publish_time)
        safe_title = _sanitise_folder_name(title, max_len=40)

        folder_name = f"{date_str}_{note_id}_{safe_title}"
        note_dir = self.base_dir / _sanitise_folder_name(creator_name) / folder_name
        note_dir.mkdir(parents=True, exist_ok=True)

        return note_dir

    def write_metadata(
        self,
        note_dir: Path,
        note: dict,
        media_files: dict,
        creator_name: str,
    ) -> None:
        """
        Write metadata.json and note.txt into *note_dir*.

        Parameters
        ----------
        note_dir : Path
            The note's archive folder.
        note : dict
            Note data (note_id, title, content, like_count, etc.).
        media_files : dict
            Downloaded media paths keyed by type (``images``, ``cover``, ``video``).
        creator_name : str
            The creator display name.
        """
        metadata = {
            "note_id": note.get("note_id"),
            "title": note.get("title"),
            "content": note.get("content", ""),
            "author": creator_name,
            "publish_time": note.get("publish_time"),
            "like_count": note.get("like_count"),
            "collect_count": note.get("collect_count", ""),
            "comment_count": note.get("comment_count", ""),
            "tags": note.get("tags", []),
            "has_video": bool(media_files.get("video")),
            "media": {
                "cover": media_files.get("cover", []),
                "images": media_files.get("images", []),
                "video": media_files.get("video", []),
            },
            "archived_at": datetime.now().isoformat(),
        }

        (note_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # -- human-readable note.txt ------------------------------------
        lines = [
            f"Title: {note.get('title', '')}",
            f"Author: {creator_name}",
            f"Published: {note.get('publish_time', 'unknown')}",
            f"Likes: {note.get('like_count', '?')}",
            f"URL: https://www.xiaohongshu.com/explore/{note.get('note_id', '')}",
            "",
            "--- Content ---",
            "",
            note.get("content", "(no content)"),
        ]
        (note_dir / "note.txt").write_text("\n".join(lines), encoding="utf-8")

    @staticmethod
    def _format_date(publish_time: Optional[str]) -> str:
        """Return YYYY-MM-DD from an ISO-ish string, or today's date."""
        if publish_time:
            # Try ISO format first
            m = re.match(r"(\d{4})-(\d{2})-(\d{2})", publish_time)
            if m:
                return f"{m[1]}-{m[2]}-{m[3]}"
            # Try "2024年5月20日" or similar
            m = re.match(r"(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})", publish_time)
            if m:
                return f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}"
        return datetime.now().strftime("%Y-%m-%d")


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _sanitise_folder_name(name: str, max_len: int = 60) -> str:
    """
    Remove characters that are unsafe in folder names and trim length.

    Keeps: Chinese chars, letters, digits, spaces, and a few safe symbols.
    """
    # Strip emoji and other non-BMP characters (U+10000+) that break GBK on Windows
    safe = re.sub(r'[\U00010000-\U0010FFFF]', '', name)
    # Replace path-unsafe characters with underscore
    safe = re.sub(r'[<>:"/\\|?*]', "_", safe)
    # Collapse whitespace
    safe = re.sub(r"\s+", " ", safe).strip()
    # Trim to max_len, trying not to cut mid-character
    if len(safe) > max_len:
        safe = safe[:max_len].rstrip()
    # Remove trailing dots/spaces (Windows issue)
    safe = safe.rstrip(". ")
    return safe or "note"
