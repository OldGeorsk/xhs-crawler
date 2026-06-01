"""
Single-creator statistical report generator.

Reads from the SQLite database.  No network, no writes.
"""

import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional


def generate_report(db_path: str, creator_id: str) -> str:
    """
    Generate a Markdown-formatted statistical report for one creator.

    Parameters
    ----------
    db_path : str
        Path to the SQLite archive database.
    creator_id : str
        The creator's id in the config / creators table.

    Returns
    -------
    str
        A Markdown report string ready to print or save.
    """
    if not Path(db_path).exists():
        return f"[ERROR] Database not found: {db_path}"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # -- fetch creator info -----------------------------------------------
    creator = conn.execute(
        "SELECT * FROM creators WHERE creator_id = ?", (creator_id,)
    ).fetchone()
    if not creator:
        conn.close()
        return f"[ERROR] Creator '{creator_id}' not found in database."

    # -- fetch all notes for this creator ---------------------------------
    notes = conn.execute(
        """
        SELECT n.*, COUNT(m.media_id) as media_count
        FROM notes n
        LEFT JOIN media m ON m.note_id = n.note_id
        WHERE n.creator_id = ?
        GROUP BY n.note_id
        ORDER BY n.publish_time DESC
        """,
        (creator_id,),
    ).fetchall()
    conn.close()

    if not notes:
        return f"[INFO] No notes archived yet for '{creator['creator_name']}'."

    return _build_report(creator, notes)


# ----------------------------------------------------------------------
# Report builder
# ----------------------------------------------------------------------

def _build_report(creator, notes: list) -> str:
    name = creator["creator_name"]
    total = len(notes)

    # -- basic stats ------------------------------------------------------
    likes_all = [_parse_likes(n["like_count"]) for n in notes]
    likes_all = [x for x in likes_all if x > 0]
    dates = [n["publish_time"] for n in notes if n["publish_time"]]
    earliest = min(dates)[:10] if dates else "?"
    latest = max(dates)[:10] if dates else "?"
    has_video = sum(1 for n in notes if n["has_video"])
    has_image = total - has_video

    # -- monthly activity -------------------------------------------------
    month_counts: Counter = Counter()
    month_likes: Counter = Counter()
    for n in notes:
        if n["publish_time"]:
            month = n["publish_time"][:7]
            month_counts[month] += 1
            month_likes[month] += _parse_likes(n["like_count"])

    # -- tag extraction ---------------------------------------------------
    all_tags: Counter = Counter()
    for n in notes:
        content = n["content"] or ""
        tags = _extract_tags(content)
        for t in tags:
            all_tags[t] += 1

    # -- top notes --------------------------------------------------------
    ranked = sorted(notes, key=lambda n: _parse_likes(n["like_count"]), reverse=True)

    # ---- render ---------------------------------------------------------
    lines = []
    lines.append(f"# 博主分析报告: {name}")
    lines.append(f"*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    lines.append("")

    # Overview
    lines.append("## 概览")
    lines.append("")
    lines.append(f"| 指标 | 数值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 归档笔记数 | {total} |")
    lines.append(f"| 时间范围 | {earliest} ~ {latest} |")
    lines.append(f"| 总获赞 | {sum(likes_all):,} |")
    lines.append(f"| 平均点赞 | {sum(likes_all)//len(likes_all):,}" if likes_all else "| 平均点赞 | — |")
    lines.append(f"| 最高单篇点赞 | {max(likes_all):,}" if likes_all else "| 最高单篇点赞 | — |")
    lines.append(f"| 图片笔记 | {has_image} ({_pct(has_image, total)}) |")
    lines.append(f"| 视频笔记 | {has_video} ({_pct(has_video, total)}) |")
    lines.append("")

    # Monthly activity
    if month_counts:
        lines.append("## 每月发布活动")
        lines.append("")
        lines.append("| 月份 | 笔记数 | 总获赞 | 热度 |")
        lines.append("|------|--------|--------|------|")
        for month in sorted(month_counts.keys()):
            count = month_counts[month]
            avg_likes = month_likes[month] // count if count else 0
            bar = "█" * min(count, 20)
            lines.append(f"| {month} | {count} | {month_likes[month]:,} | {bar} |")
        lines.append("")

    # Top tags
    if all_tags:
        lines.append("## 高频标签 (Top 15)")
        lines.append("")
        lines.append("| 标签 | 出现次数 |")
        lines.append("|------|----------|")
        for tag, count in all_tags.most_common(15):
            lines.append(f"| #{tag} | {count} |")
        lines.append("")

    # Top notes
    lines.append("## 高赞笔记 (Top 10)")
    lines.append("")
    for i, n in enumerate(ranked[:10], 1):
        date = (n["publish_time"] or "")[:10]
        title = n["title"] or "(无标题)"
        likes = n["like_count"] or "?"
        lines.append(f"{i}. **{title}** — 点赞 {likes} ({date})")
        content = (n["content"] or "")[:120].replace("\n", " ")
        if content:
            lines.append(f"   > {content}...")
        lines.append("")

    return "\n".join(lines)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _parse_likes(val: str) -> int:
    """Convert XHS like strings ('1.2万', '6979') to int."""
    if not val or val == "?":
        return 0
    try:
        if "万" in val:
            return int(float(val.replace("万", "")) * 10000)
        return int(val.replace(",", ""))
    except (ValueError, TypeError):
        return 0


def _extract_tags(content: str) -> list[str]:
    """Extract hashtags from XHS content like '#jk制服[话题]# #ootd[话题]#'."""
    # Remove the [话题] suffix commonly seen in XHS
    cleaned = re.sub(r"\[话题\]", "", content)
    # Find all #hashtag patterns
    tags = re.findall(r"#([^\s#]+)", cleaned)
    # Filter out obvious non-tags (long text, URLs, numbers only)
    return [t for t in tags if 2 <= len(t) <= 20 and not t.startswith("http")]


def _pct(part: int, whole: int) -> str:
    if whole == 0:
        return "0%"
    return f"{part * 100 // whole}%"
