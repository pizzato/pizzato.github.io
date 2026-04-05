#!/usr/bin/env python3
"""
fetch_videos.py — Sync YouTube public videos into _data/videos.yml

Uses the free YouTube Atom RSS feed (no API key required).
Channel ID is discovered once from the @handle page and cached.

Usage:
  python scripts/fetch_videos.py

Dependencies (stdlib only — no pip install needed):
  urllib, xml.etree.ElementTree, re, os, sys, datetime
  + PyYAML  (already used by other scripts: pip3 install PyYAML)
"""

import os
import re
import sys
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError
import xml.etree.ElementTree as ET

try:
    import yaml
except ImportError:
    print("Missing dependency: PyYAML")
    print("Run: pip3 install PyYAML")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

YT_HANDLE        = "luizpizzato"
YT_HANDLE_URL    = f"https://www.youtube.com/@{YT_HANDLE}"
YT_RSS_BASE      = "https://www.youtube.com/feeds/videos.xml"

REPO_ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHANNEL_ID_CACHE = os.path.join(REPO_ROOT, "_data", "youtube_channel_id.txt")
VIDEOS_YML       = os.path.join(REPO_ROOT, "_data", "videos.yml")

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; portfolio-builder/1.0)"}

# ---------------------------------------------------------------------------
# Channel ID discovery
# ---------------------------------------------------------------------------

def get_channel_id():
    """Return the UC... channel ID, using a cached value when available."""
    if os.path.exists(CHANNEL_ID_CACHE):
        with open(CHANNEL_ID_CACHE) as f:
            cid = f.read().strip()
        if cid:
            print(f"[YouTube] Channel ID (cached): {cid}")
            return cid

    print(f"[YouTube] Discovering channel ID for @{YT_HANDLE} ...")
    req = Request(YT_HANDLE_URL, headers=HEADERS)
    try:
        with urlopen(req, timeout=15) as r:
            html = r.read().decode("utf-8", errors="replace")
    except URLError as e:
        raise RuntimeError(f"Could not fetch {YT_HANDLE_URL}: {e}") from e

    m = re.search(r'"externalId":"(UC[A-Za-z0-9_-]+)"', html)
    if not m:
        raise RuntimeError(
            f"Could not find channel ID in page for @{YT_HANDLE}. "
            "Set it manually in _data/youtube_channel_id.txt."
        )

    cid = m.group(1)
    os.makedirs(os.path.dirname(CHANNEL_ID_CACHE), exist_ok=True)
    with open(CHANNEL_ID_CACHE, "w") as f:
        f.write(cid)
    print(f"[YouTube] Channel ID: {cid} (cached)")
    return cid


# ---------------------------------------------------------------------------
# RSS feed parser
# ---------------------------------------------------------------------------

# XML namespaces used in YouTube's Atom feed
NS = {
    "atom":  "http://www.w3.org/2005/Atom",
    "yt":    "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}


def fetch_videos(channel_id):
    """Fetch all public videos from the channel RSS feed."""
    url = f"{YT_RSS_BASE}?channel_id={channel_id}"
    print(f"[YouTube] Fetching RSS feed: {url}")
    req = Request(url, headers=HEADERS)
    try:
        with urlopen(req, timeout=15) as r:
            raw = r.read()
    except URLError as e:
        raise RuntimeError(f"Could not fetch RSS feed: {e}") from e

    root = ET.fromstring(raw)
    items = []

    for entry in root.findall("atom:entry", NS):
        video_id = (entry.findtext("yt:videoId", namespaces=NS) or "").strip()
        if not video_id:
            continue

        title = (entry.findtext("atom:title", namespaces=NS) or "").strip()

        pub = (entry.findtext("atom:published", namespaces=NS) or "").strip()
        date_str = pub[:10] if pub else None   # "YYYY-MM-DD"
        if not date_str:
            continue

        # Description lives inside media:group/media:description
        mg = entry.find("media:group", NS)
        description = ""
        if mg is not None:
            description = (mg.findtext("media:description", namespaces=NS) or "").strip()
            # Truncate to first sentence or 160 chars
            if description:
                first = re.split(r'(?<=[.!?])\s', description, maxsplit=1)[0]
                description = first[:160].rstrip()

        items.append({
            "title":      title,
            "youtube_id": video_id,
            "date":       date_str,
            "description": description,
        })

    print(f"[YouTube] {len(items)} video(s) found in feed")
    return items


# ---------------------------------------------------------------------------
# YAML helpers
# ---------------------------------------------------------------------------

VIDEOS_HEADER = """\
# YouTube videos for the personal page.
# Auto-populated by: python scripts/fetch_videos.py
#
# You can edit descriptions manually — the script only adds new entries
# and updates the date field; it never overwrites your edits.
#
# Fields:
#   title:       Video title
#   youtube_id:  The part after ?v= in the YouTube URL
#   date:        "YYYY-MM-DD"  (publish date)
#   description: One-sentence summary (optional, editable)

"""


def load_videos_yml():
    if not os.path.exists(VIDEOS_YML):
        return {"videos": []}
    with open(VIDEOS_YML) as f:
        data = yaml.safe_load(f) or {}
    if "videos" not in data or data["videos"] is None:
        data["videos"] = []
    return data


def save_videos_yml(data):
    os.makedirs(os.path.dirname(VIDEOS_YML), exist_ok=True)
    with open(VIDEOS_YML, "w") as f:
        f.write(VIDEOS_HEADER)
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False,
                  sort_keys=False, indent=2)


# ---------------------------------------------------------------------------
# Merge logic
# ---------------------------------------------------------------------------

def merge(existing, fetched):
    """
    Merge fetched videos into existing list.
    - New videos are added.
    - Date is updated if it changed.
    - Title and youtube_id are updated if they changed.
    - Description is only set for new entries (preserve manual edits).
    Returns (merged_list, added_count, updated_count).
    """
    by_id = {v["youtube_id"]: v for v in existing}
    added = updated = 0

    for item in fetched:
        vid = item["youtube_id"]
        if vid not in by_id:
            by_id[vid] = item
            added += 1
        else:
            changed = False
            for field in ("title", "date"):
                if by_id[vid].get(field) != item[field]:
                    by_id[vid][field] = item[field]
                    changed = True
            if changed:
                updated += 1

    merged = sorted(by_id.values(), key=lambda x: x.get("date", ""), reverse=True)
    return merged, added, updated


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    channel_id = get_channel_id()
    fetched    = fetch_videos(channel_id)

    data     = load_videos_yml()
    merged, added, updated = merge(data["videos"], fetched)
    data["videos"] = merged

    save_videos_yml(data)

    print(f"\n✓ {VIDEOS_YML}")
    print(f"  {added} new  |  {updated} updated  |  {len(merged)} total")


if __name__ == "__main__":
    main()
