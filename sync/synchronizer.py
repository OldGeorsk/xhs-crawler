"""
Phase 2: Synchronisation orchestrator.

Coordinates the full workflow with human-like delays:

    1. Open creator profile               -> NoteCollector.open_profile()
    2. For each NEW note:
       a. Click into detail page          -> NoteCollector.collect_note_detail()
       b. Download all images + cover     -> MediaDownloader
       c. Create archive folder           -> Archiver
       d. Write metadata.json + note.txt  -> Archiver
       e. Insert into SQLite database     -> DatabaseManager
    3. Update last_sync_time              -> DatabaseManager

The browser stays open for the entire per-creator sync run.
Each detail page visit is followed by a navigation back to profile
with human-like randomised delays.
"""

import random
import sys
import time
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright

# -- project modules ---------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from crawler.collector import NoteCollector
from database.db_manager import DatabaseManager
from downloader.media_downloader import MediaDownloader
from archive.archiver import Archiver
from login_helper import dismiss_login_popup


class Synchronizer:
    """
    Orchestrates a single sync run for all enabled creators.

    Usage::

        synchronizer = Synchronizer(config, cookies)
        synchronizer.run()
    """

    def __init__(self, config: dict, storage_state_path: Optional[str] = None,
                 use_cdp: bool = False):
        self.config = config
        self.storage_state_path = storage_state_path
        self.use_cdp = use_cdp

        paths = config.get("paths", {})
        self.db_path = paths.get("database", "data/xhs_archive.db")
        self.downloads_dir = paths.get("downloads", "downloads")

        sync_cfg = config.get("sync", {})
        self.max_notes = sync_cfg.get("max_notes_per_run", 50)
        self.interval_ms = sync_cfg.get("request_interval_ms", 3000)

        self.browser_cfg = config.get("browser", {})

        # Sub-components
        self._db: Optional[DatabaseManager] = None
        self._downloader: Optional[MediaDownloader] = None
        self._archiver: Optional[Archiver] = None
        self._collector: Optional[NoteCollector] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, creator_filter: Optional[str] = None) -> dict:
        """Run a full sync pass over all enabled creators."""
        creators = self.config.get("creators", [])
        enabled = [c for c in creators if c.get("enabled", True)]

        if creator_filter:
            enabled = [c for c in enabled if c["id"] == creator_filter]

        if not enabled:
            print("[sync] No enabled creators to sync.")
            return {"total_notes": 0, "new_notes": 0, "errors": 0, "creators_ok": 0, "creators_total": 0}

        summary = {"total_notes": 0, "new_notes": 0, "errors": 0, "creators_ok": 0, "creators_total": len(enabled)}

        for i, creator in enumerate(enabled):
            # -- inter-creator gap (skip first) -------------------------------
            if i > 0:
                gap_ms = random.randint(5000, 15000)
                print(f"\n[sync] Inter-creator pause {gap_ms/1000:.0f}s ...")
                time.sleep(gap_ms / 1000.0)

            # -- sync with resilience -----------------------------------------
            try:
                stats = self._sync_creator(creator)
                summary["total_notes"] += stats["total_notes"]
                summary["new_notes"] += stats["new_notes"]
                summary["errors"] += stats["errors"]
                summary["creators_ok"] += 1
            except Exception as e:
                print(f"\n[sync] [ERROR] Failed to sync '{creator['name']}': {e}")
                print(f"[sync] Continuing with next creator ...")
                summary["errors"] += 1

        print(f"\n[sync] All done. "
              f"{summary['creators_ok']}/{summary['creators_total']} creators OK, "
              f"{summary['new_notes']} new notes archived.")
        return summary

    # ------------------------------------------------------------------
    # Per-creator sync (single browser session)
    # ------------------------------------------------------------------

    def _sync_creator(self, creator: dict) -> dict:
        name = creator["name"]
        cid = creator["id"]

        print(f"\n{'=' * 55}")
        print(f"  Syncing: {name}")
        print(f"{'=' * 55}")

        stats = {"total_notes": 0, "new_notes": 0, "errors": 0}

        # 1. Open browser (once per creator) -----------------------------------
        with sync_playwright() as pw:

            if self.use_cdp:
                browser = pw.chromium.connect_over_cdp("http://localhost:9222")
                # Use existing default context (carries the real session)
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                if context.pages:
                    page = context.pages[0]
                else:
                    page = context.new_page()
            else:
                browser = pw.chromium.launch(
                    headless=self.browser_cfg.get("headless", False)
                )
                context_kwargs: dict = {
                    "viewport": self.browser_cfg.get("viewport", {"width": 1280, "height": 800}),
                    "user_agent": self.browser_cfg.get("user_agent"),
                }
                if self.storage_state_path:
                    context_kwargs["storage_state"] = self.storage_state_path
                context = browser.new_context(**context_kwargs)
                page = context.new_page()

            try:
                # 2. Collect notes from profile ---------------------------------
                collector = self._get_collector()

                # Dismiss any login popup that might block interaction
                if not dismiss_login_popup(page):
                    print(f"  [WARN] Login popup could not be dismissed for {name}.")
                    # Don't fail — some pages work even with the popup

                notes = collector.open_profile(page, creator, max_notes=self.max_notes)
                stats["total_notes"] = len(notes)

                if not notes:
                    print(f"  No notes found for {name}.")
                    return stats

                # 3. Database comparison + per-note processing ------------------
                db = self._get_db()
                db.connect()

                # Read sync mode from config: "fast" or "safe" (default)
                mode = self.config.get("sync", {}).get("mode", "safe")
                print(f"  Mode: {mode}")

                try:
                    db.upsert_creator(cid, name, creator["profile_url"])

                    notes_to_process = 0
                    next_like_at = random.randint(2, 5)
                    next_collect_at = random.randint(5, 8)
                    print(f"  [init] Like at #{next_like_at}, Collect at #{next_collect_at}")

                    for i, note in enumerate(notes):
                        note_id = note["note_id"]

                        # -- incremental sync: skip if already archived ------------
                        if db.note_exists(note_id):
                            print(f"  [skip] {note_id} ({note['title']}) - already in database.")
                            continue

                        # -- fast mode: random skip (30% chance) -----------------
                        if mode == "fast" and random.random() < 0.3:
                            print(f"  [browse] Skipped: {note.get('title', '?')} ({note_id})")
                            notes_to_process += 1
                            # Still increment like/collect counters
                            if notes_to_process >= next_like_at:
                                print(f"  [like] Would like #{notes_to_process} but detail skipped.")
                            continue

                        # -- inter-note delay (mode-dependent) ----------------
                        if notes_to_process > 0:
                            if mode == "fast":
                                # Fast mode: 1-3s between notes
                                idle_sec = random.randint(1, 3)
                                print(f"  [..] {idle_sec}s pause")
                                time.sleep(idle_sec)
                                # Every ~10 notes, take a longer break
                                if notes_to_process % 10 == 0:
                                    long_idle = random.randint(15, 25)
                                    print(f"  [zzz] {long_idle}s long idle ...")
                                    time.sleep(long_idle)
                            else:
                                # Safe mode: 15-25s between every note
                                idle_sec = random.randint(15, 25)
                                print(f"  [zzz] {idle_sec}s idle ...")
                                time.sleep(idle_sec)

                        # -- random engagement triggers -------------------------
                        should_like = notes_to_process >= next_like_at
                        should_collect = notes_to_process >= next_collect_at

                        # -- detail page enrichment -----------------------------
                        print(f"\n  [{i+1}/{len(notes)}] {note['title']} ({note_id})")
                        notes_to_process += 1

                        enriched = collector.collect_note_detail(
                            page, note,
                            should_like=should_like,
                            should_collect=should_collect,
                        )

                        if should_like:
                            next_like_at = notes_to_process + random.randint(2, 5)
                            print(f"  [info] Next like at note #{next_like_at}")
                        if should_collect:
                            next_collect_at = notes_to_process + random.randint(5, 8)
                            print(f"  [info] Next collect at note #{next_collect_at}")
                        if enriched is None:
                            stats["errors"] += 1
                            continue

                        # -- download & archive ---------------------------------
                        try:
                            self._process_enriched_note(enriched, creator, db)
                            stats["new_notes"] += 1
                        except Exception as e:
                            print(f"  [ERROR] {note_id}: {e}")
                            stats["errors"] += 1

                    # 4. Update sync timestamp ----------------------------------
                    db.update_last_sync(cid)

                finally:
                    db.close()

            finally:
                if not self.use_cdp:
                    browser.close()

        print(f"  -> {stats['new_notes']} new, {stats['errors']} errors")
        return stats

    # ------------------------------------------------------------------
    # Per-note processing (download + archive + db)
    # ------------------------------------------------------------------

    def _process_enriched_note(self, note: dict, creator: dict, db: DatabaseManager) -> None:
        note_id = note["note_id"]

        # -- create archive folder -----------------------------------------
        archiver = self._get_archiver()
        note_dir = archiver.create_note_folder(
            creator_name=creator["name"],
            note_id=note_id,
            title=note.get("title", ""),
            publish_time=note.get("publish_time"),
        )

        # -- download ALL images + cover + video ---------------------------
        downloader = self._get_downloader()
        image_urls = note.pop("image_urls", [])
        video_url = note.pop("video_url", "") or None
        cover_url = note.get("cover_url", "")

        # If cover_url is already the first image, use it; otherwise download separately
        media_files = downloader.download_batch(
            images=image_urls,
            video_url=video_url,
            cover_url="" if image_urls else cover_url,  # only separate cover if no detail images
            dest_dir=note_dir,
        )

        # If we have detail images, first detail image *is* the cover
        if image_urls and not media_files.get("cover"):
            # The first downloaded image serves as cover
            imgs = media_files.get("images", [])
            if imgs:
                media_files.setdefault("cover", [imgs[0]])

        # -- write metadata ------------------------------------------------
        note["creator_id"] = creator["id"]
        note["local_path"] = str(note_dir)
        note.setdefault("has_video", 0)
        note.setdefault("content", "")
        note.setdefault("publish_time", None)
        note.setdefault("collect_count", "")
        note.setdefault("comment_count", "")
        note.setdefault("tags", [])

        archiver.write_metadata(note_dir, note, media_files, creator["name"])

        # -- record in database --------------------------------------------
        db.insert_note(note)
        for mtype, paths in media_files.items():
            for fname in paths:
                source = cover_url if mtype == "cover" else (image_urls[0] if image_urls else "")
                db.insert_media(note_id, mtype.rstrip("s"), str(note_dir / fname), source)

        img_count = len(media_files.get("images", []))
        has_vid = " +video" if media_files.get("video") else ""
        print(f"    archived -> {note_dir}")
        print(f"    {img_count} images, 1 cover{has_vid}")

    # ------------------------------------------------------------------
    # Lazy component getters
    # ------------------------------------------------------------------

    def _get_collector(self) -> NoteCollector:
        if self._collector is None:
            self._collector = NoteCollector(self.config)
        return self._collector

    def _get_db(self) -> DatabaseManager:
        if self._db is None:
            self._db = DatabaseManager(self.db_path)
        return self._db

    def _get_downloader(self) -> MediaDownloader:
        if self._downloader is None:
            self._downloader = MediaDownloader(interval_ms=self.interval_ms)
        return self._downloader

    def _get_archiver(self) -> Archiver:
        if self._archiver is None:
            self._archiver = Archiver(base_dir=self.downloads_dir)
        return self._archiver
