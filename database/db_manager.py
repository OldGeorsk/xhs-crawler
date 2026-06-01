"""
Phase 2: SQLite database manager.

The database is the single source of truth for sync state.
All filesystem operations are driven by what's recorded here.

Tables
------
creators
    Tracks which creators are being followed and when they were last synced.

notes
    Every collected note, linked to a creator. Stores metadata and the
    local archive path so we never re-download.

media
    Individual media files (images, videos, covers) belonging to a note.
"""

import sqlite3
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS creators (
    creator_id   TEXT PRIMARY KEY,
    creator_name TEXT NOT NULL,
    profile_url  TEXT NOT NULL,
    last_sync_time TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notes (
    note_id       TEXT PRIMARY KEY,
    creator_id    TEXT NOT NULL,
    title         TEXT,
    content       TEXT,
    publish_time  TEXT,
    like_count    TEXT,
    collect_count TEXT,
    comment_count TEXT,
    has_video     INTEGER DEFAULT 0,
    local_path    TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (creator_id) REFERENCES creators(creator_id)
);

CREATE TABLE IF NOT EXISTS media (
    media_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id    TEXT NOT NULL,
    media_type TEXT NOT NULL,   -- 'image', 'video', 'cover'
    file_path  TEXT NOT NULL,
    source_url TEXT,
    FOREIGN KEY (note_id) REFERENCES notes(note_id)
);

CREATE INDEX IF NOT EXISTS idx_notes_creator ON notes(creator_id);
CREATE INDEX IF NOT EXISTS idx_media_note    ON media(note_id);

-- Full-text search (SQLite FTS5, built into Python stdlib)
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    title,
    content,
    content='notes',
    content_rowid='rowid'
);
"""

# Trigger to keep the FTS index in sync with the notes table.
_FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
    INSERT INTO notes_fts(rowid, title, content)
    VALUES (new.rowid, new.title, new.content);
END;

CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, title, content)
    VALUES ('delete', old.rowid, old.title, old.content);
END;

CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, title, content)
    VALUES ('delete', old.rowid, old.title, old.content);
    INSERT INTO notes_fts(rowid, title, content)
    VALUES (new.rowid, new.title, new.content);
END;
"""


class DatabaseManager:
    """Thin wrapper around an SQLite connection for the XHS archive."""

    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        # FTS5 triggers — safe to run every connect (IF NOT EXISTS)
        self._conn.executescript(_FTS_TRIGGERS)
        # Populate FTS index from existing notes (idempotent)
        self._conn.execute(
            "INSERT OR IGNORE INTO notes_fts(rowid, title, content) "
            "SELECT rowid, title, content FROM notes"
        )
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.close()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() or use as context manager.")
        return self._conn

    # ------------------------------------------------------------------
    # Creators
    # ------------------------------------------------------------------

    def upsert_creator(self, creator_id: str, name: str, profile_url: str) -> None:
        self.conn.execute(
            """
            INSERT INTO creators (creator_id, creator_name, profile_url)
            VALUES (?, ?, ?)
            ON CONFLICT(creator_id) DO UPDATE SET
                creator_name = excluded.creator_name,
                profile_url  = excluded.profile_url,
                updated_at   = datetime('now')
            """,
            (creator_id, name, profile_url),
        )
        self.conn.commit()

    def get_creator(self, creator_id: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM creators WHERE creator_id = ?", (creator_id,)
        ).fetchone()
        return dict(row) if row else None

    def update_last_sync(self, creator_id: str) -> None:
        now = datetime.now().isoformat()
        self.conn.execute(
            "UPDATE creators SET last_sync_time = ?, updated_at = datetime('now') WHERE creator_id = ?",
            (now, creator_id),
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Notes
    # ------------------------------------------------------------------

    def note_exists(self, note_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM notes WHERE note_id = ?", (note_id,)
        ).fetchone()
        return row is not None

    def insert_note(self, note: dict) -> None:
        """Insert a new note record. ``note`` is a dict with keys matching the
        ``notes`` table columns (note_id, creator_id, title, etc.)."""
        self.conn.execute(
            """
            INSERT OR IGNORE INTO notes
                (note_id, creator_id, title, content, publish_time,
                 like_count, collect_count, comment_count, has_video, local_path)
            VALUES
                (:note_id, :creator_id, :title, :content, :publish_time,
                 :like_count, :collect_count, :comment_count, :has_video, :local_path)
            """,
            note,
        )
        self.conn.commit()

    def get_notes_for_creator(self, creator_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM notes WHERE creator_id = ? ORDER BY publish_time DESC",
            (creator_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_note(self, note_id: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM notes WHERE note_id = ?", (note_id,)
        ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Full-text search
    # ------------------------------------------------------------------

    def search(self, query: str, creator_id: str = "", limit: int = 50) -> list[dict]:
        """
        Full-text search across note titles and content.

        Parameters
        ----------
        query : str
            The search terms (space-separated, FTS5 syntax).
        creator_id : str
            Optional creator filter.
        limit : int
            Max results.

        Returns
        -------
        list[dict]
            Matching notes with ``creator_name`` joined in.
        """
        # FTS5 prefix search: add * to each term so "春" matches "春天"
        # Multi-char CJK terms need * for substring matching since
        # SQLite FTS5 uses whitespace-based tokenization.
        terms = [f'"{t}"*' if " " in t else f'{t}*' for t in query.strip().split() if t]
        fts_query = " OR ".join(terms) if terms else query.strip()

        where = ""
        params: list = [fts_query, limit]
        if creator_id:
            where = "AND n.creator_id = ? "
            params.insert(1, creator_id)

        rows = self.conn.execute(
            f"""
            SELECT n.note_id, n.title, n.content, n.publish_time,
                   n.like_count, n.local_path,
                   c.creator_name
            FROM notes_fts f
            JOIN notes n ON n.rowid = f.rowid
            JOIN creators c ON c.creator_id = n.creator_id
            WHERE notes_fts MATCH ? {where}
            ORDER BY rank
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Media
    # ------------------------------------------------------------------

    def insert_media(self, note_id: str, media_type: str, file_path: str, source_url: str = "") -> None:
        self.conn.execute(
            """
            INSERT INTO media (note_id, media_type, file_path, source_url)
            VALUES (?, ?, ?, ?)
            """,
            (note_id, media_type, file_path, source_url),
        )
        self.conn.commit()

    def get_media_for_note(self, note_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM media WHERE note_id = ? ORDER BY media_id", (note_id,)
        ).fetchall()
        return [dict(r) for r in rows]
