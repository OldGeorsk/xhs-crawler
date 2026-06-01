# CLAUDE.md

## Quick Reference — Daily Operations

All commands are run from the project root.  CDP mode (real Chrome) is the default.

### Sync (download new notes from a creator)

```bash
python main.py                          # Sync the first enabled creator
python main.py --creator <id>           # Sync a specific creator
python main.py --dry-run                # Preview only — no download, no DB writes
python main.py --dry-run --creator <id>
```

Before syncing, Chrome must be running with the debug port open:

```bash
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir=./chrome_profile
```

The crawler will open xiaohongshu.com in that Chrome window; log in once, then leave it open.  Subsequent syncs reuse the same session.

If CDP is not available the script falls back to `storage_state` + QR-code login automatically.

### Creator management

```bash
python main.py --add                    # Interactive — prompts for name + profile URL
python main.py --remove <id>            # Removes from config only; archive + DB are kept
python main.py --list                   # List all tracked creators
python main.py --status                 # DB overview: note counts, last sync, date range
```

### Search & analysis (read-only — no network, no writes)

```bash
python main.py --search "制服"          # Full-text search across all archived notes
python main.py --search "jk" --creator 4  # Filter by creator
python main.py --report 1               # Statistical report: tags, trends, top posts
```

### Emergency / fallback

```bash
python login_helper.py                  # Manual QR-code login (saves storage_state.json)
python login_helper.py --check          # Test whether current session is still valid
python main.py --no-cdp                 # Force storage_state mode (skip CDP)
```

---

## Project Overview

This project is a personal-use Xiaohongshu (RED/XHS) content synchronization tool.

The purpose of this project is NOT large-scale scraping or commercial data collection.

The goal is to build a long-term personal archive system for tracking selected Xiaohongshu creators and automatically synchronizing newly published content, including:

* Images
* Videos
* Post captions
* Metadata
* Publish dates
* Tags

The archive should remain searchable even if original posts are deleted in the future.

---

# Core Design Principles

Priority order:

1. Account Safety
2. Long-term Maintainability
3. Data Integrity
4. Download Efficiency

Never sacrifice account safety for speed.

Avoid aggressive crawling strategies.

Avoid high concurrency.

Avoid proxy rotation.

Avoid multi-account automation.

The crawler should behave similarly to a normal user browsing content.

---

# Technical Stack

Language:

* Python 3.11+

Browser Automation:

* Playwright

Database:

* SQLite

Storage:

* Local filesystem

Configuration:

* JSON

---

# Authentication Strategy

Do NOT automate login.

Do NOT automate username/password entry.

The user should manually export browser cookies.

The application loads an existing cookies.json file.

Authentication flow:

User Browser
→ Login Manually
→ Export Cookies
→ cookies.json
→ Playwright Session

This minimizes login-related risks.

---

# Intended Workflow

1. Load creators from config
2. Open creator profile
3. Collect note information
4. Compare with local database
5. Download only new notes
6. Archive content
7. Update database

The project should support incremental synchronization.

Already downloaded notes should never be downloaded again.

---

# Creator Tracking

The system is designed around long-term creator tracking.

Expected use case:

* Follow multiple creators
* Run sync periodically
* Download only newly published content

Not designed for one-time bulk scraping.

---

# Database Requirements

SQLite is the source of truth.

Filesystem is storage only.

Suggested tables:

## creators

creator_id
creator_name
profile_url
last_sync_time

## notes

note_id
creator_id

title
content

publish_time

like_count
collect_count
comment_count

has_video

local_path

created_at
updated_at

## media

media_id
note_id

media_type

file_path

source_url

---

# Archive Structure

Each note must have its own folder.

Do NOT separate image posts and video posts into different archive structures.

Recommended format:

downloads/

└── creator_name/

```
└── YYYY-MM-DD_noteid_title/

    metadata.json

    note.txt

    cover.jpg

    01.jpg
    02.jpg
    03.jpg

    video.mp4
```

A note folder should represent a complete archive unit.

---

# Metadata Preservation

Always preserve:

* Note ID
* Title
* Caption
* Author
* Publish date
* Tags
* Media URLs

Store machine-readable information in metadata.json.

Store human-readable content in note.txt.

Example:

metadata.json
note.txt

This ensures future searchability.

---

# Download Strategy

Support configurable limits.

Example:

max_notes = 50

If fewer notes exist, download all available notes.

For synchronization runs:

Do not rely on max_notes.

Instead:

1. Scan newest notes first.
2. Stop scanning once an existing note_id is found.
3. Download only unseen notes.

This significantly reduces workload.

---

# Media Naming Rules

Images:

01.jpg
02.jpg
03.jpg

Videos:

video.mp4

Cover:

cover.jpg

Avoid random filenames.

Use deterministic naming.

---

# Development Philosophy

Build in phases.

Phase 1:

* Open creator page
* Collect first 10 notes
* Extract note information
* Print results

No downloading.

No database.

No synchronization.

Goal:
Validate collection strategy.

Phase 2:

* SQLite integration
* Incremental sync
* Media downloading
* Archive creation

Phase 3:

* Multi-creator management
* Search tools
* Archive maintenance utilities

---

# Architecture Guidelines

Separate responsibilities.

Crawler:
Collect note data

Downloader:
Download media

Database:
Store state

Archive:
Manage filesystem

Sync:
Coordinate workflow

Avoid placing all logic into a single script.

---

# Future Expansion

Potential future features:

* Full-text search
* Tag search
* Local archive browser
* Duplicate detection
* Metadata analytics

However:

Do not implement future features until core synchronization is stable.

Stability is more important than feature count.

---

# Important Reminder

This is a personal archive project.

The primary objective is:

Reliable synchronization of selected creators while minimizing account risk.

Whenever a design decision must be made:

Choose the safer and simpler option.
