"""
XHS Crawler — Xiaohongshu Content Synchronization Tool

Personal-use archive system for tracking selected creators
and synchronizing newly published content.

Commands:
    python main.py                  Full sync (Phase 2)
    python main.py --dry-run        Collect and print only (Phase 1)
    python main.py --add            Interactive creator addition
    python main.py --remove <id>    Remove a creator (archive & DB kept)
    python main.py --list           List all tracked creators
    python main.py --status         Database overview
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Force UTF-8 on Windows to avoid GBK encoding errors with emoji in file paths
if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    # Reconfigure stdout/stderr to UTF-8 (env vars only work at startup)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from crawler.collector import NoteCollector, load_json, print_notes
from login_helper import ensure_fresh_session

CONFIG_PATH = PROJECT_ROOT / "config" / "config.json"


# ======================================================================
# Config helpers
# ======================================================================

def _read_config() -> dict:
    if not CONFIG_PATH.exists():
        print(f"[ERROR] Config not found: {CONFIG_PATH}")
        print("  Copy config/config.example.json -> config/config.json and edit it.")
        sys.exit(1)
    return load_json(str(CONFIG_PATH))


def _write_config(config: dict) -> None:
    CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _next_creator_id(creators: list[dict]) -> str:
    """Generate the next numeric creator ID."""
    existing = []
    for c in creators:
        try:
            existing.append(int(c["id"]))
        except (ValueError, KeyError):
            pass
    return str(max(existing) + 1) if existing else "1"


# ======================================================================
# Management commands
# ======================================================================

def cmd_add() -> None:
    """Interactive creator addition."""
    config = _read_config()
    creators = config.setdefault("creators", [])

    print("\n" + "=" * 45)
    print("  Add New Creator")
    print("=" * 45)
    print()

    name = input("  Creator name     : ").strip()
    if not name:
        print("[ERROR] Name cannot be empty.")
        sys.exit(1)

    profile_url = input("  Profile URL      : ").strip()
    if not profile_url or "xiaohongshu.com" not in profile_url:
        print("[ERROR] Invalid URL — must be a xiaohongshu.com profile link.")
        sys.exit(1)

    # -- duplicate check ----------------------------------------------------
    for c in creators:
        if c.get("name") == name:
            print(f"[WARN] Creator '{name}' already exists (id={c['id']}).")
            sys.exit(0)
        if c.get("profile_url", "").rstrip("/") == profile_url.rstrip("/"):
            print(f"[WARN] URL already tracked by '{c['name']}' (id={c['id']}).")
            sys.exit(0)

    # -- confirm ------------------------------------------------------------
    print()
    print(f"  Name : {name}")
    print(f"  URL  : {profile_url}")
    confirm = input("\n  Confirm add? [Y/n]: ").strip().lower()
    if confirm and confirm != "y":
        print("  Cancelled.")
        return

    cid = _next_creator_id(creators)
    creators.append({
        "id": cid,
        "name": name,
        "profile_url": profile_url,
        "enabled": True,
    })
    _write_config(config)
    print(f"  [OK] Added '{name}' (id={cid})")


def cmd_remove(creator_id: str) -> None:
    """Remove a creator from config only — archive and DB are untouched."""
    config = _read_config()
    creators = config.get("creators", [])

    target = None
    for c in creators:
        if c["id"] == creator_id or c["name"] == creator_id:
            target = c
            break

    if target is None:
        print(f"[ERROR] Creator '{creator_id}' not found.")
        sys.exit(1)

    print(f"\n  Remove: {target['name']} (id={target['id']})")
    print(f"  URL  : {target['profile_url']}")
    print()
    print("  Archived notes and database records will be kept.")
    confirm = input("  Confirm? [y/N]: ").strip().lower()
    if confirm != "y":
        print("  Cancelled.")
        return

    creators.remove(target)
    _write_config(config)
    print(f"  [OK] Removed '{target['name']}' from tracking list.")
    print(f"  Archives and DB records are preserved.")


def cmd_list() -> None:
    """List all tracked creators with sync status."""
    config = _read_config()
    creators = config.get("creators", [])

    print(f"\n{'=' * 60}")
    print(f"  Tracked Creators ({len(creators)})")
    print(f"{'=' * 60}")

    for c in creators:
        status = "enabled" if c.get("enabled", True) else "disabled"
        print(f"\n  [{c['id']}] {c['name']}")
        print(f"       Status : {status}")
        print(f"       URL    : {c['profile_url']}")

    print()


def cmd_status() -> None:
    """Database overview — requires sqlite3."""
    import sqlite3

    config = _read_config()
    db_path = config.get("paths", {}).get("database", "data/xhs_archive.db")

    print(f"\n{'=' * 50}")
    print(f"  Archive Status")
    print(f"{'=' * 50}")

    if not Path(db_path).exists():
        print(f"\n  Database not found: {db_path}")
        print("  Run a sync first to create it.")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        creator_count = conn.execute("SELECT COUNT(*) as n FROM creators").fetchone()["n"]
        note_count = conn.execute("SELECT COUNT(*) as n FROM notes").fetchone()["n"]
        media_count = conn.execute("SELECT COUNT(*) as n FROM media").fetchone()["n"]

        print(f"  Database    : {db_path}")
        print(f"  Creators   : {creator_count}")
        print(f"  Notes      : {note_count}")
        print(f"  Media files: {media_count}")
        print()

        # -- per-creator breakdown ------------------------------------------
        rows = conn.execute("""
            SELECT c.creator_name, c.last_sync_time, COUNT(n.note_id) as total
            FROM creators c
            LEFT JOIN notes n ON n.creator_id = c.creator_id
            GROUP BY c.creator_id
            ORDER BY c.creator_name
        """).fetchall()

        for r in rows:
            last = r["last_sync_time"][:19] if r["last_sync_time"] else "never"
            print(f"  {r['creator_name']:<20s}  {r['total']:>4d} notes  last sync: {last}")

        # -- date range -----------------------------------------------------
        date_range = conn.execute("""
            SELECT MIN(publish_time) as oldest, MAX(publish_time) as newest
            FROM notes WHERE publish_time IS NOT NULL
        """).fetchone()

        if date_range and date_range["oldest"]:
            print(f"\n  Date range : {date_range['oldest'][:10]} ~ {date_range['newest'][:10]}")

    finally:
        conn.close()

    print()


def cmd_report(creator_id: str) -> None:
    """Generate a statistical report for a single creator."""
    config = _read_config()
    db_path = config.get("paths", {}).get("database", "data/xhs_archive.db")

    from analyzer.reporter import generate_report

    report = generate_report(db_path, creator_id)
    print(report)


def cmd_search(query: str, creator_filter: str = "") -> None:
    """Full-text search across archived notes."""
    import sqlite3

    config = _read_config()
    db_path = config.get("paths", {}).get("database", "data/xhs_archive.db")

    if not Path(db_path).exists():
        print("[ERROR] No database yet. Run a sync first.")
        sys.exit(1)

    from database.db_manager import DatabaseManager

    with DatabaseManager(db_path) as db:
        results = db.search(query, creator_id=creator_filter)

    print(f"\n  Search: \"{query}\" — {len(results)} results\n")

    for i, r in enumerate(results, 1):
        date = (r.get("publish_time") or "")[:10]
        creator = r.get("creator_name", "?")
        title = r.get("title", "(no title)")
        content = (r.get("content") or "")[:100]
        tags = r.get("tags", "")
        likes = r.get("like_count", "?")

        print(f"  [{i}] {title}")
        print(f"      Creator : {creator}")
        print(f"      Date    : {date}  |  Likes: {likes}")
        if content:
            print(f"      Content : {content}...")
        if tags:
            print(f"      Tags    : {tags}")
        print()

    if not results:
        print("  (no matches)\n")


# ======================================================================
# Auth — fresh session every run
# ======================================================================


# ======================================================================
# Main entry point
# ======================================================================

def main():
    parser = argparse.ArgumentParser(
        description="XHS Crawler — Xiaohongshu Content Sync Tool"
    )
    # -- management commands ------------------------------------------------
    parser.add_argument("--add", action="store_true", help="Add a new creator interactively")
    parser.add_argument("--remove", type=str, metavar="ID", help="Remove a creator by ID or name")
    parser.add_argument("--list", action="store_true", help="List all tracked creators")
    parser.add_argument("--status", action="store_true", help="Show database overview")
    # -- sync commands ------------------------------------------------------
    parser.add_argument("--cdp", action="store_true", default=True, help="Connect to real Chrome via CDP (default)")
    parser.add_argument("--no-cdp", action="store_true", help="Use storage_state instead of CDP")
    parser.add_argument("--dry-run", action="store_true", help="Collect & print only (no download)")
    parser.add_argument("--creator", type=str, metavar="ID", help="Sync only a specific creator")
    parser.add_argument("--search", type=str, metavar="QUERY", help="Full-text search archived notes")
    parser.add_argument("--report", type=str, metavar="ID", help="Generate statistical report for a creator")
    args = parser.parse_args()

    # ---- report command (no auth, read-only) -------------------------------
    if args.report:
        cmd_report(args.report)
        return

    # ---- search command (no auth, read-only) ----------------------------------
    if args.search:
        cmd_search(args.search, args.creator)
        return

    # ---- management commands (no auth needed) ------------------------------
    if args.add:
        cmd_add()
        return

    if args.remove:
        cmd_remove(args.remove)
        return

    if args.list:
        cmd_list()
        return

    if args.status:
        cmd_status()
        return

    # ---- sync commands (need config) --------------------------------------
    config = _read_config()

    creators = config.get("creators", [])
    enabled = [c for c in creators if c.get("enabled", True)]

    if not enabled:
        print("[ERROR] No enabled creators. Use --add to add one.")
        sys.exit(1)

    # -- pick the ONE creator to sync ---------------------------------------
    if args.creator:
        matched = [c for c in enabled if c["id"] == args.creator]
        if not matched:
            print(f"[ERROR] Creator '{args.creator}' not found.")
            sys.exit(1)
        target = matched[0]
    else:
        target = enabled[0]  # default: first enabled creator
        if len(enabled) > 1:
            print(f"[info] {len(enabled)} creators enabled. Syncing '{target['name']}'.")
            print(f"[info] Use --creator <id> to pick another.\n")

    max_notes = config.get("sync", {}).get("max_notes_per_run", 10)

    # -- Phase 1: dry-run --------------------------------------------------
    if args.dry_run:
        print("=" * 50)
        print("  XHS Crawler - Phase 1 (dry-run)")
        print("=" * 50)

        state_path = str(PROJECT_ROOT / "config" / "storage_state.json")
        collector = NoteCollector(config)

        print(f"\n>> Processing: {target['name']}")
        notes = collector.collect(target, max_notes=max_notes,
                                  storage_state_path=state_path)
        print_notes(target["name"], notes)

        print("\n[DONE] Phase 1 collection complete.")
        return

    # -- Phase 2: full sync ------------------------------------------------
    print("=" * 50)
    print("  XHS Crawler - Phase 2 (full sync)")
    print("=" * 50)

    from cdp_helper import is_cdp_available

    if args.no_cdp:
        use_cdp = False
        state_path = ensure_fresh_session()
    elif is_cdp_available():
        use_cdp = True
        state_path = None
        print("  Mode            : CDP (real Chrome)")
    else:
        print("  [!] CDP not available — falling back to session-based auth.")
        print("  [!] Tip: keep Chrome open with --remote-debugging-port=9222")
        use_cdp = False
        state_path = ensure_fresh_session()

    print(f"  Creator         : {target['name']}")
    print(f"  Max notes / run : {max_notes}")
    print(f"  Database        : {config.get('paths', {}).get('database', 'data/xhs_archive.db')}")
    print(f"  Archive         : {config.get('paths', {}).get('downloads', 'downloads')}")
    print("=" * 50)

    from sync.synchronizer import Synchronizer

    sync = Synchronizer(config, storage_state_path=state_path, use_cdp=use_cdp)
    result = sync.run(creator_filter=target["id"])

    print(f"\n[DONE] Phase 2 sync complete.")
    print(f"  Total notes scanned : {result['total_notes']}")
    print(f"  New notes archived  : {result['new_notes']}")
    print(f"  Errors              : {result['errors']}")


if __name__ == "__main__":
    main()
