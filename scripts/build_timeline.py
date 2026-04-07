#!/usr/bin/env python3
"""
build_timeline.py — Build _data/timeline.json from all available sources.

Sources:
  - _data/career.yml        → career and education events
  - publications/index.md   → research papers
  - _data/photos.json       → photo events (capped at 1 per week)
  - _data/videos.yml        → YouTube media events
  - _data/stream.json       → writing (medium, post) and social (linkedin, twitter)

Run:
  python3 scripts/build_timeline.py
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta

try:
    import yaml
except ImportError:
    print("Missing dependency: PyYAML — run: pip3 install PyYAML")
    sys.exit(1)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CAREER_YML    = os.path.join(REPO_ROOT, "_data", "career.yml")
STREAM_JSON   = os.path.join(REPO_ROOT, "_data", "stream.json")
PHOTOS_JSON   = os.path.join(REPO_ROOT, "_data", "photos.json")
VIDEOS_YML    = os.path.join(REPO_ROOT, "_data", "videos.yml")
PUBS_MD       = os.path.join(REPO_ROOT, "publications", "index.markdown")
OUTPUT_JSON   = os.path.join(REPO_ROOT, "_data", "timeline.json")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_date(date_str):
    """Return datetime from YYYY-MM-DD string, or None."""
    if not date_str:
        return None
    try:
        return datetime.strptime(str(date_str)[:10], "%Y-%m-%d")
    except ValueError:
        return None


def fmt(date_str):
    """Normalise any date-like string to YYYY-MM-DD."""
    dt = parse_date(date_str)
    return dt.strftime("%Y-%m-%d") if dt else str(date_str)


# ---------------------------------------------------------------------------
# Career source
# ---------------------------------------------------------------------------

def load_career():
    if not os.path.exists(CAREER_YML):
        print("[Career] career.yml not found — skipping")
        return []

    with open(CAREER_YML) as f:
        data = yaml.safe_load(f) or {}

    items = []

    # Positions
    for pos in data.get("positions", []):
        items.append({
            "type":     "career",
            "title":    pos["title"],
            "subtitle": pos["company"],
            "location": pos.get("location", ""),
            "date":     fmt(pos["start"]),
            "date_end": fmt(pos["end"]) if pos.get("end") else None,
            "url":      None,
            "description": pos.get("description", ""),
        })

    # Advisory (grouped with career, distinct visual optional)
    for pos in data.get("advisory", []):
        items.append({
            "type":     "career",
            "subtype":  "advisory",
            "title":    pos["title"],
            "subtitle": pos["company"],
            "location": pos.get("location", ""),
            "date":     fmt(pos["start"]),
            "date_end": fmt(pos["end"]) if pos.get("end") else None,
            "url":      None,
            "description": "",
        })

    # Education
    for edu in data.get("education", []):
        items.append({
            "type":     "education",
            "title":    edu["degree"],
            "subtitle": edu["institution"],
            "location": edu.get("location", ""),
            "date":     fmt(edu["start"]),
            "date_end": fmt(edu["end"]) if edu.get("end") else None,
            "url":      None,
            "description": edu.get("thesis", "") or edu.get("description", ""),
        })

    # Projects
    for proj in data.get("projects", []):
        items.append({
            "type":     "career",
            "subtype":  "project",
            "title":    proj["title"],
            "subtitle": "Project",
            "date":     fmt(proj["start"]),
            "date_end": fmt(proj["end"]) if proj.get("end") else None,
            "url":      proj.get("url"),
            "description": proj.get("description", ""),
        })

    print(f"[Career] {len(items)} items")
    return items


# ---------------------------------------------------------------------------
# Publications source
# ---------------------------------------------------------------------------

def load_publications():
    if not os.path.exists(PUBS_MD):
        print("[Publications] index.markdown not found — skipping")
        return []

    with open(PUBS_MD, encoding="utf-8") as f:
        text = f.read()

    items = []

    # Match bold title blocks followed by venue line with a year
    # Pattern: **Title**\n_authors_\nVenue..., YYYY
    blocks = re.split(r'\n{2,}', text)

    for block in blocks:
        lines = [l.strip() for l in block.strip().splitlines() if l.strip()]
        if not lines:
            continue

        # Title line: **...**
        title_match = re.match(r'^\*\*(.+?)\*\*$', lines[0])
        if not title_match:
            continue
        title = title_match.group(1)

        # Find a year (4-digit) in any subsequent line
        year = None
        venue = ""
        url = None
        for line in lines[1:]:
            y = re.search(r'\b(19|20)\d{2}\b', line)
            if y and not year:
                year = y.group(0)
                # Venue: the line containing the year, stripped of markdown links
                venue = re.sub(r'\[.*?\]\(.*?\)', '', line).strip().rstrip('.,')
            # First URL in the block
            if url is None:
                u = re.search(r'\]\((https?://[^)]+)\)', line)
                if u:
                    url = u.group(1)

        if not year:
            continue

        items.append({
            "type":     "research",
            "title":    title,
            "subtitle": venue[:120] if venue else "",
            "date":     f"{year}-01-01",
            "url":      url,
            "description": "",
        })

    print(f"[Publications] {len(items)} items")
    return items


# ---------------------------------------------------------------------------
# Photos source (capped at 1 per week to avoid flooding the timeline)
# ---------------------------------------------------------------------------

def load_photos():
    if not os.path.exists(PHOTOS_JSON):
        print("[Photos] photos.json not found — skipping")
        return []

    with open(PHOTOS_JSON, encoding="utf-8") as f:
        photos = json.load(f)

    # Sort by date desc, keep best 1 per ISO week
    photos_dated = [(p, parse_date(p.get("date", ""))) for p in photos if p.get("date")]
    photos_dated = [(p, dt) for p, dt in photos_dated if dt]
    photos_dated.sort(key=lambda x: x[1], reverse=True)

    seen_weeks = set()
    items = []
    for photo, dt in photos_dated:
        week_key = dt.strftime("%Y-W%U")
        if week_key in seen_weeks:
            continue
        seen_weeks.add(week_key)
        items.append({
            "type":     "photo",
            "title":    photo.get("title") or "Photo",
            "subtitle": photo.get("source", ""),
            "date":     dt.strftime("%Y-%m-%d"),
            "url":      photo.get("url", ""),
            "image":    photo.get("image", ""),
            "media_type": photo.get("media_type", "photo"),
            "description": "",
        })

    print(f"[Photos] {len(items)} items (from {len(photos_dated)} total, capped 1/week)")
    return items


# ---------------------------------------------------------------------------
# Videos source
# ---------------------------------------------------------------------------

def load_videos():
    if not os.path.exists(VIDEOS_YML):
        print("[Videos] videos.yml not found — skipping")
        return []

    with open(VIDEOS_YML, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    videos = data.get("videos") or []
    items = []
    for video in videos:
        youtube_id = (video.get("youtube_id") or "").strip()
        date = video.get("date")
        if not youtube_id or not date:
            continue

        items.append({
            "type": "photo",
            "title": video.get("title") or "Video",
            "subtitle": "YouTube",
            "date": fmt(date),
            "url": f"https://www.youtube.com/watch?v={youtube_id}",
            "image": video.get("image") or f"https://img.youtube.com/vi/{youtube_id}/hqdefault.jpg",
            "media_type": "photo",
            "description": video.get("description", ""),
        })

    print(f"[Videos] {len(items)} items")
    return items


# ---------------------------------------------------------------------------
# Stream source (writing + social)
# ---------------------------------------------------------------------------

def load_stream():
    if not os.path.exists(STREAM_JSON):
        print("[Stream] stream.json not found — skipping")
        return [], []

    with open(STREAM_JSON, encoding="utf-8") as f:
        entries = json.load(f)

    writing = []
    social = []

    for e in entries:
        t = e.get("type", "")
        date = e.get("date", "")
        if not date:
            continue

        base = {
            "title":       e.get("title", ""),
            "subtitle":    e.get("source", ""),
            "date":        fmt(date),
            "url":         e.get("url", ""),
            "description": "",
        }

        if t in ("medium", "post"):
            writing.append({**base, "type": "writing"})
        elif t in ("linkedin", "twitter"):
            social.append({**base, "type": "social"})

    print(f"[Stream] {len(writing)} writing, {len(social)} social items")
    return writing, social


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    all_items = []

    all_items.extend(load_career())
    all_items.extend(load_publications())
    all_items.extend(load_photos())
    all_items.extend(load_videos())

    writing, social = load_stream()
    all_items.extend(writing)
    all_items.extend(social)

    # Sort by date descending
    def sort_key(item):
        dt = parse_date(item.get("date", ""))
        return dt if dt else datetime.min

    all_items.sort(key=sort_key, reverse=True)

    # Remove items without a date
    all_items = [i for i in all_items if i.get("date")]

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(all_items, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Wrote {len(all_items)} items to {OUTPUT_JSON}")

    # Summary by type
    from collections import Counter
    counts = Counter(i["type"] for i in all_items)
    for t, n in sorted(counts.items()):
        print(f"  {t}: {n}")


if __name__ == "__main__":
    main()
