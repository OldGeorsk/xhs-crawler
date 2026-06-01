"""
Crawler module — responsible for collecting note data from Xiaohongshu.

Uses Playwright to navigate creator profile pages, scroll through notes,
and extract structured note information (title, content, images, videos,
publish time, engagement metrics, etc.).

Design principle: behave like a normal user browsing content.
No aggressive crawling, no high concurrency.
"""

from .collector import NoteCollector

__all__ = ["NoteCollector"]
