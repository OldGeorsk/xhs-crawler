"""
Xiaohongshu note collector.

Uses Playwright to:
  1. Open a creator profile page with authenticated cookies.
  2. Extract note cards (title, cover, likes, note_id, xsec_token).
  3. Click into each note's detail page to extract full content:
     - All images (up to 18 per note)
     - Video URL (if present)
     - Full description / tags
     - Publish timestamp
     - Engagement counts (likes, collects, comments, shares)

Human-like delays and scrolling are applied throughout to
minimise bot-detection risk.
"""

import json
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.sync_api import Page, sync_playwright


# ----------------------------------------------------------------------
# Cookie normalisation (Cookie-Editor export -> Playwright format)
# ----------------------------------------------------------------------

def _normalise_cookies(raw: list[dict]) -> list[dict]:
    """Convert Cookie-Editor JSON into the subset Playwright accepts."""
    clean: list[dict] = []
    for c in raw:
        out: dict = {}
        out["name"] = c.get("name", "")
        out["value"] = c.get("value", "")
        out["domain"] = c.get("domain", "")
        out["path"] = c.get("path", "/")
        out["httpOnly"] = bool(c.get("httpOnly", False))
        out["secure"] = bool(c.get("secure", False))

        if "expires" in c:
            out["expires"] = int(c["expires"])
        elif "expirationDate" in c and c["expirationDate"] is not None:
            out["expires"] = int(c["expirationDate"])

        same_site = c.get("sameSite")
        out["sameSite"] = same_site if same_site in ("Strict", "Lax", "None") else "Lax"

        clean.append(out)
    return clean


# ----------------------------------------------------------------------
# Human-like delay helpers
# ----------------------------------------------------------------------

def _human_delay(base_ms: int, jitter_ms: int = 800) -> None:
    """Sleep for *base_ms* +/- random *jitter_ms* milliseconds."""
    delay = max(200, base_ms + random.randint(-jitter_ms, jitter_ms))
    time.sleep(delay / 1000.0)


def _human_scroll(page: Page) -> None:
    """Scroll a slightly random amount downward."""
    amount = random.randint(400, 900)
    page.evaluate(f"window.scrollBy(0, {amount})")


# ----------------------------------------------------------------------
# NoteCollector
# ----------------------------------------------------------------------

class NoteCollector:
    """
    Collects note metadata from a Xiaohongshu creator profile and
    enriches with detail-page data.

    Supports two modes:
      - ``collect()`` — standalone, opens & closes its own browser (Phase 1).
      - ``collect_from_profile(page, ...)`` + ``collect_note_detail(page, ...)``
        — share a browser page managed by the Synchronizer (Phase 2).
    """

    def __init__(self, config: dict, cookies: Optional[list] = None):
        self.config = config
        self.cookies = _normalise_cookies(cookies) if cookies else []
        self.browser_cfg = config.get("browser", {})
        self.sync_cfg = config.get("sync", {})
        self._profile_url: str = ""

    # ------------------------------------------------------------------
    # Phase 1: standalone collect (opens & closes own browser)
    # ------------------------------------------------------------------

    def collect(self, creator: dict, max_notes: int = 10,
                storage_state_path: str = "") -> list[dict]:
        """Standalone Phase 1 collection — returns basic card-level data."""
        profile_url = creator["profile_url"]
        timeout = self.sync_cfg.get("page_load_timeout_ms", 30000)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=self.browser_cfg.get("headless", False)
            )
            context_kwargs: dict = {
                "viewport": self.browser_cfg.get("viewport", {"width": 1280, "height": 800}),
                "user_agent": self.browser_cfg.get("user_agent"),
            }
            if storage_state_path:
                context_kwargs["storage_state"] = storage_state_path
            context = browser.new_context(**context_kwargs)
            if self.cookies and not storage_state_path:
                context.add_cookies(self.cookies)
            page = context.new_page()

            try:
                print(f"\n[collector] Opening {profile_url}")
                page.goto(profile_url, timeout=timeout, wait_until="domcontentloaded")
                _human_delay(2500, 800)

                print(f"[collector] Page title: {page.title()}")

                notes = self._scroll_and_collect(page, max_notes)

                return notes
            finally:
                browser.close()

    # ------------------------------------------------------------------
    # Phase 2: profile-level extraction (shared page)
    # ------------------------------------------------------------------

    def open_profile(self, page: Page, creator: dict, max_notes: int = 50) -> list[dict]:
        """Navigate to *creator*'s profile and extract note cards.
        Returns basic card data PLUS the ``detail_url`` with xsec_token
        for each note.  The *page* remains open on the profile."""
        profile_url = creator["profile_url"]
        self._profile_url = profile_url
        timeout = self.sync_cfg.get("page_load_timeout_ms", 30000)

        print(f"\n[collector] Opening {profile_url}")
        page.goto(profile_url, timeout=timeout, wait_until="domcontentloaded")
        _human_delay(2500, 1000)

        print(f"[collector] Page title: {page.title()}")

        notes = self._scroll_and_collect(page, max_notes)
        return notes

    # ------------------------------------------------------------------
    # Phase 2: detail-level extraction (shared page)
    # ------------------------------------------------------------------

    def collect_note_detail(self, page: Page, note: dict,
                            should_like: bool = False) -> Optional[dict]:
        """
        Navigate from the current page to *note*'s detail page using the
        ``detail_url`` (with xsec_token) extracted from the profile card.

        Extracts full note data from ``window.__INITIAL_STATE__``, then
        navigates back to the profile page.

        Returns the enriched note dict, or None on failure.
        """
        detail_url = note.get("detail_url", "")
        if not detail_url:
            print(f"  [detail] No detail_url for {note['note_id']}, skipping.")
            return None

        full_url = f"https://www.xiaohongshu.com{detail_url}"
        note_id = note["note_id"]

        # -- human-like pre-click delay ---------------------------------
        _human_delay(1500, 500)

        # -- navigate to detail page ------------------------------------
        print(f"  [detail] Opening {full_url[:100]}...")
        page.goto(full_url, timeout=30000, wait_until="domcontentloaded")

        # -- dismiss any login popup that might block extraction --------
        from login_helper import dismiss_login_popup
        dismiss_login_popup(page)

        # -- simulate reading time --------------------------------------
        _human_delay(3500, 1500)

        # -- extract data from React SSR state --------------------------
        detail = page.evaluate(_DETAIL_JS)

        if detail:
            # Merge detail data into the note dict
            note["title"] = detail.get("title") or note.get("title", "")
            note["content"] = detail.get("desc", "")
            note["publish_time"] = _render_timestamp(detail.get("time"))
            note["tags"] = [t["name"] for t in detail.get("tagList", [])]
            note["like_count"] = str(detail.get("interactInfo", {}).get("likedCount", note.get("like_count", "?")))
            note["collect_count"] = str(detail.get("interactInfo", {}).get("collectedCount", ""))
            note["comment_count"] = str(detail.get("interactInfo", {}).get("commentCount", ""))
            note["has_video"] = 1 if detail.get("type") == "video" else 0
            note["image_urls"] = [img["url"] for img in detail.get("imageList", [])]
            note["video_url"] = (detail.get("video") or {}).get("masterUrl", "")

            img_count = len(note["image_urls"])
            print(f"  [detail] {note_id}: {img_count} images, "
                  f"type={detail.get('type', '?')}, "
                  f"time={note['publish_time']}")
        else:
            print(f"  [detail] {note_id}: failed to extract data from __INITIAL_STATE__")

        # -- random like (1 in 3~5 notes, human-like engagement) -------
        if should_like:
            _human_delay(600, 300)
            self._click_like(page)
            note.setdefault("liked", True)

        # -- navigate back to profile for the next note -----------------
        _human_delay(800, 400)
        page.goto(self._profile_url, timeout=30000, wait_until="domcontentloaded")
        _human_delay(2000, 800)

        return note

    # ------------------------------------------------------------------
    # Internal: like button
    # ------------------------------------------------------------------

    @staticmethod
    def _click_like(page: Page) -> None:
        """
        Click the like button on a note detail page, if it is not already
        liked (no ``like-active`` class).
        """
        try:
            like_btn = page.query_selector("span.like-wrapper")
            if like_btn:
                classes = like_btn.get_attribute("class") or ""
                if "like-active" not in classes:
                    like_btn.click()
                    print("  [like] Liked this note.")
                else:
                    print("  [like] Already liked — skipped.")
        except Exception as e:
            # Never fail a sync because of a like
            print(f"  [like] Could not click like: {e}")

    # ------------------------------------------------------------------
    # Internal: scroll & extract (profile page)
    # ------------------------------------------------------------------

    def _scroll_and_collect(self, page: Page, max_notes: int) -> list[dict]:
        """
        Scroll through the profile page AND extract notes at each scroll
        position.  This is critical for XHS profiles that use virtual
        scrolling — cards are recycled out of the DOM as you scroll,
        so capturing only at the end misses the newest notes.

        Returns deduplicated note list (up to *max_notes*).
        """
        seen_ids: set[str] = set()
        notes: list[dict] = []

        prev_count = 0
        stall_attempts = 0

        for _ in range(30):  # safety cap
            # -- extract from current scroll position -------------------
            cards = page.query_selector_all("section.note-item")

            for card in cards:
                if len(notes) >= max_notes:
                    break

                explore_link = card.query_selector('a[href*="/explore/"]')
                if not explore_link:
                    continue
                href = (explore_link.get_attribute("href") or "").strip()
                note_id = _extract_note_id(href)
                if not note_id or note_id in seen_ids:
                    continue
                seen_ids.add(note_id)

                cover_link = card.query_selector("a.cover")
                detail_url = cover_link.get_attribute("href") or "" if cover_link else ""

                title_el = card.query_selector("a.title span, a.title")
                title = title_el.inner_text().strip() if title_el else ""

                cover_el = card.query_selector("img")
                cover_url = cover_el.get_attribute("src") or "" if cover_el else ""

                like_el = card.query_selector("span.count")
                like_count = like_el.inner_text().strip() if like_el else "?"

                notes.append({
                    "note_id": note_id,
                    "title": title or "(no title)",
                    "cover_url": cover_url,
                    "like_count": like_count,
                    "note_url": f"https://www.xiaohongshu.com/explore/{note_id}",
                    "detail_url": detail_url,
                })

            if len(notes) >= max_notes:
                break

            # -- scroll & check for stall -------------------------------
            current = len(cards)
            if current == prev_count:
                stall_attempts += 1
                if stall_attempts >= 8:
                    break
            else:
                stall_attempts = 0
            prev_count = current

            _human_scroll(page)
            _human_delay(1800, 600)

        print(f"[collector] Found {len(notes)} unique notes "
              f"(max={max_notes})")
        return notes


# ----------------------------------------------------------------------
# JS snippet injected into the note detail page
# ----------------------------------------------------------------------

_DETAIL_JS = """() => {
    const state = window.__INITIAL_STATE__;
    if (!state || !state.note) return null;
    const map = state.note.noteDetailMap || {};
    for (const [key, val] of Object.entries(map)) {
        if (!val.note || !val.note.noteId) continue;
        const n = val.note;
        return {
            noteId: n.noteId,
            title: n.title || "",
            desc: n.desc || "",
            time: n.time || null,
            type: n.type || "normal",
            tagList: (n.tagList || []).map(t => ({ name: t.name, id: t.id })),
            imageList: (n.imageList || []).map(img => ({
                url: img.urlDefault || img.url || "",
                width: img.width || 0,
                height: img.height || 0
            })),
            video: n.video ? {
                duration: n.video.duration,
                masterUrl: (n.video.media?.stream?.h264 || [{}])[0]?.masterUrl || ""
            } : null,
            interactInfo: {
                likedCount: n.interactInfo?.likedCount || 0,
                collectedCount: n.interactInfo?.collectedCount || 0,
                commentCount: n.interactInfo?.commentCount || 0,
                shareCount: n.interactInfo?.shareCount || 0
            }
        };
    }
    return null;
}"""


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _extract_note_id(href: str) -> Optional[str]:
    m = re.search(r"/(?:explore|search_result|note)/([a-f0-9]{24})", href)
    return m.group(1) if m else None


def _render_timestamp(ms: Optional[int]) -> Optional[str]:
    """Unix ms -> ISO-8601 string."""
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000).isoformat()
    except (ValueError, OSError):
        return str(ms)


def _log_console(msg, errors: list[str]) -> None:
    """Capture severe console messages for diagnostics."""
    if msg.type in ("error", "warning"):
        errors.append(f"[{msg.type}] {msg.text}")


# ----------------------------------------------------------------------
# Standalone helpers (Phase 1 CLI)
# ----------------------------------------------------------------------

def load_json(path: str) -> dict | list:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def print_notes(creator_name: str, notes: list[dict]) -> None:
    """Pretty-print extracted notes to the console."""
    print(f"\n{'=' * 60}")
    print(f"  Creator: {creator_name}")
    print(f"  Notes found: {len(notes)}")
    print(f"{'=' * 60}")

    for i, n in enumerate(notes, 1):
        print(f"\n-- [{i}] {n['note_id']} --")
        print(f"  Title     : {n['title']}")
        print(f"  Likes     : {n['like_count']}")
        print(f"  Cover     : {n['cover_url'][:80]}...")
        print(f"  URL       : {n['note_url']}")


def main():
    """Standalone Phase 1 runner."""
    project_root = Path(__file__).resolve().parent.parent
    config_path = project_root / "config" / "config.json"
    cookies_path = project_root / "config" / "cookies.json"

    if not config_path.exists():
        print(f"[ERROR] Config not found: {config_path}")
        sys.exit(1)
    if not cookies_path.exists():
        print(f"[ERROR] Cookies not found: {cookies_path}")
        sys.exit(1)

    config = load_json(str(config_path))
    cookies = load_json(str(cookies_path))

    creators = config.get("creators", [])
    enabled = [c for c in creators if c.get("enabled", True)]
    if not enabled:
        print("[ERROR] No enabled creators.")
        sys.exit(1)

    max_notes = config.get("sync", {}).get("max_notes_per_run", 10)
    collector = NoteCollector(config, cookies)

    for creator in enabled:
        print(f"\n>> Processing: {creator['name']}")
        notes = collector.collect(creator, max_notes=max_notes)
        print_notes(creator["name"], notes)

    print("\n[DONE] Phase 1 collection complete.")


if __name__ == "__main__":
    main()
