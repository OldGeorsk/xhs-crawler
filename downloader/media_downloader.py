"""
Phase 2: Media downloader.

Downloads images and videos from Xiaohongshu CDN URLs and saves
them with deterministic filenames inside a note's archive folder.

Uses Python stdlib (urllib) — no extra dependencies.
"""

import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional


class MediaDownloader:
    """
    Downloads media files (images, videos, covers) from URLs.

    Features:
        - Deterministic file naming (01.jpg, 02.jpg, video.mp4, cover.jpg)
        - Automatic retry with backoff
        - Respects configurable request interval
    """

    def __init__(self, interval_ms: int = 2000, max_retries: int = 3):
        self.interval = interval_ms / 1000.0
        self.max_retries = max_retries
        self._last_request = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def download(self, url: str, dest: Path) -> bool:
        """
        Download a single file from *url* to *dest*.

        Returns True on success, False on failure (after all retries).
        Creates parent directories as needed.
        """
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Skip if already downloaded and non-empty
        if dest.exists() and dest.stat().st_size > 0:
            return True

        for attempt in range(1, self.max_retries + 1):
            try:
                self._throttle()
                self._fetch(url, dest)
                return True
            except urllib.error.HTTPError as e:
                print(f"  [download] HTTP {e.code} for {url[-60:]} (attempt {attempt}/{self.max_retries})")
                if e.code in (403, 404):
                    return False  # don't retry on auth errors or not-found
            except Exception as e:
                print(f"  [download] {e} (attempt {attempt}/{self.max_retries})")
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)

        return False

    def download_batch(
        self, images: list[str], video_url: Optional[str], cover_url: str, dest_dir: Path
    ) -> dict:
        """
        Download all media for one note.

        Parameters
        ----------
        images : list[str]
            Ordered list of image URLs (→ 01.jpg, 02.jpg, ...).
        video_url : str or None
            URL of the video file, if any.
        cover_url : str
            URL of the cover image.
        dest_dir : Path
            The note's archive folder.

        Returns
        -------
        dict
            Mapping of media type → relative file paths (e.g.
            ``{"images": ["01.jpg", "02.jpg"], "cover": "cover.jpg"}``).
        """
        result: dict[str, list[str]] = {"images": [], "cover": [], "video": []}
        dest_dir.mkdir(parents=True, exist_ok=True)

        # -- cover --------------------------------------------------------
        if cover_url:
            cover_path = dest_dir / "cover.jpg"
            if self.download(cover_url, cover_path):
                result["cover"] = ["cover.jpg"]

        # -- images -------------------------------------------------------
        for i, url in enumerate(images, 1):
            ext = _guess_ext(url, ".jpg")
            fname = f"{i:02d}{ext}"
            if self.download(url, dest_dir / fname):
                result["images"].append(fname)

        # -- video --------------------------------------------------------
        if video_url:
            ext = _guess_ext(video_url, ".mp4")
            vname = f"video{ext}"
            if self.download(video_url, dest_dir / vname):
                result["video"] = [vname]

        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        """Ensure a minimum interval between requests."""
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)
        self._last_request = time.monotonic()

    @staticmethod
    def _fetch(url: str, dest: Path) -> None:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Referer": "https://www.xiaohongshu.com/",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            dest.write_bytes(resp.read())


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _guess_ext(url: str, fallback: str) -> str:
    """Extract file extension from URL, falling back to *fallback*."""
    # Strip query params
    path = url.split("?")[0]
    ext = Path(path).suffix.lower()
    if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov"):
        return ext
    return fallback
