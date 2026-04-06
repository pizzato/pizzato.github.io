#!/usr/bin/env python3
"""
fetch_photos.py — Aggregate public photos for pizzato.github.io /personal/

Sources:
  - Flickr public feed (no API key — uses the free public JSON feed endpoint)
  - 500px: RSS feed is dead as of 2026; add photos manually to photos_manual.yml
  - Instagram/manual entries (_data/photos_manual.yml — populated by hand)

Output: _data/photos.json (sorted by date desc, capped at 100 items)

Usage:
  pip install requests PyYAML
  python scripts/fetch_photos.py

No API keys or secrets needed for Flickr. The script discovers the user's
NSID from their public profile page (one-time, cached in _data/flickr_nsid.txt)
then fetches their 20 most recent public photos via the free public feed API.
"""

import json
import os
import re
import sys
from datetime import datetime

try:
    import requests
    import yaml
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Run: pip3 install requests PyYAML")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FLICKR_USERNAME      = "kinho"
FLICKR_PROFILE_URL   = f"https://www.flickr.com/photos/{FLICKR_USERNAME}/"
FLICKR_FEED_BASE     = "https://www.flickr.com/services/feeds/photos_public.gne"

REPO_ROOT            = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANUAL_YML           = os.path.join(REPO_ROOT, "_data", "photos_manual.yml")
NSID_CACHE           = os.path.join(REPO_ROOT, "_data", "flickr_nsid.txt")
OUTPUT_JSON          = os.path.join(REPO_ROOT, "_data", "photos.json")

MAX_ITEMS            = 500

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def iso_date(value):
    """Normalise various date formats to 'YYYY-MM-DD'."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ",
                    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z"):
            try:
                s = value.strip()
                # datetime.strptime can't handle ±HH:MM timezone in older Python;
                # normalise to remove it for a best-effort parse
                s_clean = re.sub(r'[+-]\d{2}:\d{2}$', '', s).strip()
                return datetime.strptime(s_clean, fmt.replace('%z', '')).strftime("%Y-%m-%d")
            except ValueError:
                pass
    if hasattr(value, "tm_year"):
        return f"{value.tm_year:04d}-{value.tm_mon:02d}-{value.tm_mday:02d}"
    return None


# ---------------------------------------------------------------------------
# Source: Flickr (public feed, no API key required)
# ---------------------------------------------------------------------------

def flickr_get_nsid():
    """
    Discover the Flickr NSID for FLICKR_USERNAME by scraping the profile page.
    Result is cached in _data/flickr_nsid.txt so we only do this once.
    """
    if os.path.exists(NSID_CACHE):
        with open(NSID_CACHE) as f:
            nsid = f.read().strip()
        if nsid:
            return nsid

    print(f"[Flickr] Discovering NSID for '{FLICKR_USERNAME}' ...")
    r = requests.get(
        FLICKR_PROFILE_URL,
        headers={"User-Agent": "Mozilla/5.0 (compatible; portfolio-builder/1.0)"},
        timeout=15,
    )
    r.raise_for_status()

    m = re.search(r'"nsid":"(\d+@N\d+)"', r.text)
    if not m:
        # Fallback pattern
        m = re.search(r'flickr\.com/people/(\d+@N\d+)', r.text)
    if not m:
        raise RuntimeError(
            f"Could not find NSID in Flickr profile page for '{FLICKR_USERNAME}'. "
            "The page structure may have changed. Set NSID manually in _data/flickr_nsid.txt."
        )

    nsid = m.group(1)
    os.makedirs(os.path.dirname(NSID_CACHE), exist_ok=True)
    with open(NSID_CACHE, "w") as f:
        f.write(nsid)
    print(f"[Flickr] NSID: {nsid} (cached)")
    return nsid


def fetch_flickr():
    """
    Fetch recent public photos using Flickr's free public feed endpoint.
    No API key required. Returns up to 20 most recent public photos.
    """
    items = []
    try:
        nsid = flickr_get_nsid()

        print(f"[Flickr] Fetching public feed for NSID {nsid}")
        r = requests.get(
            FLICKR_FEED_BASE,
            params={"id": nsid, "format": "json", "nojsoncallback": "1"},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()

        for entry in data.get("items", []):
            # Upgrade thumbnail URL from _m (240px) to _z (640px) for better quality
            image = entry.get("media", {}).get("m", "")
            image = re.sub(r'_m\.jpg$', '_z.jpg', image)

            date_str = iso_date(entry.get("date_taken") or entry.get("published") or "")
            if not date_str or not image:
                continue

            items.append({
                "source": "flickr",
                "title":  entry.get("title") or "",
                "url":    entry.get("link") or "",
                "image":  image,
                "date":   date_str,
            })

        print(f"[Flickr] {len(items)} photos")
    except Exception as e:
        print(f"[Flickr] Error: {e}")

    return items


# ---------------------------------------------------------------------------
# Source: 500px
# ---------------------------------------------------------------------------

def fetch_500px():
    """
    500px shut down their developer API in 2018 and their RSS feed now returns
    HTML instead of XML (as of 2026). This function is a no-op.
    Add 500px photos manually via _data/photos_manual.yml using source: '500px'.
    """
    print("[500px] RSS feed is no longer functional (returns HTML as of 2026). "
          "Add 500px photos manually to _data/photos_manual.yml.")
    return []


# ---------------------------------------------------------------------------
# Source: Manual (Instagram, 500px, etc.)
# ---------------------------------------------------------------------------

def fetch_manual():
    """
    Read _data/photos_manual.yml — used for:
      - Instagram entries (source: instagram)
      - 500px entries (source: 500px) — RSS feed is dead as of 2026
      - Flickr bulk entries scraped via scrape_photos.py (source: flickr)
    Entries without an image URL are skipped (can't show in grid).
    """
    items = []
    if not os.path.exists(MANUAL_YML):
        print("[Manual] No photos_manual.yml found — skipping")
        return items
    try:
        with open(MANUAL_YML) as f:
            data = yaml.safe_load(f) or {}
        entries = data.get("entries") or []
        skipped = 0
        for e in entries:
            d = iso_date(e.get("date") or "")
            if not d or not e.get("image") or not e.get("url"):
                skipped += 1
                continue
            item = {
                "source":     e.get("source", "instagram"),
                "title":      e.get("title") or "",
                "url":        e["url"],
                "image":      e["image"],
                "date":       d,
            }
            if e.get("media_type"):
                item["media_type"] = e["media_type"]
            items.append(item)
        print(f"[Manual] {len(items)} entries ({skipped} skipped — no image URL)")
    except Exception as e:
        print(f"[Manual] Error: {e}")
    return items


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    all_items = []
    all_items.extend(fetch_flickr())
    all_items.extend(fetch_500px())
    all_items.extend(fetch_manual())

    # Filter items without required fields
    all_items = [i for i in all_items if i.get("image") and i.get("url") and i.get("date")]

    # Deduplicate: prefer image path as key (handles Instagram where all entries
    # share the same profile fallback URL); fall back to URL for other sources.
    seen_keys = set()
    deduped = []
    for item in all_items:
        key = item.get("image") or item["url"]
        if key not in seen_keys:
            seen_keys.add(key)
            deduped.append(item)
    all_items = deduped

    # Sort by date descending
    all_items.sort(key=lambda x: x.get("date", ""), reverse=True)

    # Cap total
    all_items = all_items[:MAX_ITEMS]

    os.makedirs(os.path.dirname(OUTPUT_JSON), exist_ok=True)
    with open(OUTPUT_JSON, "w") as f:
        json.dump(all_items, f, indent=2, ensure_ascii=False)

    print(f"\n✓ Wrote {len(all_items)} photos to {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
