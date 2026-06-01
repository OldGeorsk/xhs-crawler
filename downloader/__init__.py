"""
Downloader module — responsible for downloading media files.

Handles image and video downloads with deterministic file naming
(01.jpg, 02.jpg, video.mp4, cover.jpg).

Includes retry logic and integrity checks to ensure downloaded
files are complete and uncorrupted.
"""

from .media_downloader import MediaDownloader

__all__ = ["MediaDownloader"]
