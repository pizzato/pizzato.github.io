#!/usr/bin/env python3
"""
fetch_photos.py — Aggregate public photos for pizzato.github.io /personal/

Sources:
  - Flickr REST API (requires FLICKR_API_KEY env var — free non-commercial key)
  - 500px RSS feed (public, no auth)
  - Instagram manual entries (_data/photos_manual.yml — populated by hand)

Output: _data/photos.json (sorted by date desc, capped at 100 items)

Usage:
  pip install requests feedparser PyYAML
  FLICKR_API_KEY=your_key_here python scripts/fetch_photos.py

Setup:
  1. Get a free Flickr API key: https://www.flickr.com/services/api/keys
  2. Add it to GitHub repo Settings → Secrets → Actions → New secret: FLICKR_API_KEY
  3. Trigger the workflow manually via GitHub Actions UI (or push a commit)
  4. For Instagram: add entries to _data/photos_manual.yml
"""

import json
import os
import re
import sys
from datetime import datetime

try:
    import feedparser
    import requests
    import yaml
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Run: pip3 install requests feedparser PyYAML")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FLICKR_USERNAME   = "kinho"
FLICKR_API_BASE   = "https://www.flickr.com/services/rest/"
FLICKR_API_KEY    = os.environ.get("FLICKR_API_KEY", "")

FIVEPX_RSS_URL    = "https://500px.com/kinho/rss"
# NOTE: As of 2026, 500px no longer returns a valid RSS feed (returns HTML).
# 500px photos should be added manually to _data/photos_manual.yml instead.

REPO_ROOT         = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANUAL_YML        = os.path.join(REPO_ROOT, "_data", "photos_manual.yml")
NSID_CACHE        = os.path.join(REPO_ROOT, "_data", "flickr_nsid.txt")
OUTPUT_JSON       = os.path.join(REPO_ROOT, "_data", "photos.json")

MAX_ITEMS         = 100

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def iso_date(value):
    """Normalise various date formats to 'YYYY-MM-DD'."""
    if isinstance(value, (datetime,)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ",
                    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d",
                    "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
            try:
                return datetime.strptime(value[:25].strip(), fmt).strftime("%Y-%m-%d")
            except ValueError:
                pass
    if hasattr(value, "tm_year"):
        return f"{value.tm_year:04d}-{value.tm_mon:02d}-{value.tm_mday:02d}"
    return None


# ---------------------------------------------------------------------------
# Source: Flickr
# ---------------------------------------------------------------------------

def flickr_get_nsid():
    """Look up Flickr NSID for FLICKR_USERNAME; cache in _data/flickr_nsid.txt."""
    # Return cached value if available
    if os.path.exists(NSID_CACHE):
        with open(NSID_CACHE) as f:
            nsid = f.read().strip()
        if nsid:
            return nsid

    print(f"[Flickr] Looking up NSID for '{FLICKR_USERNAME}'")
    r = requests.get(FLICKR_API_BASE, params={
        "method":   "flickr.people.findByUsername",
        "api_key":  FLICKR_API_KEY,
        "username": FLICKR_USERNAME,
        "format":   "json",
        "nojsoncallback": 1,
    }, timeout=15)
    r.raise_for_status()
    data = r.json()
    if data.get("stat") != "ok":
        raise RuntimeError(f"Flickr API error: {data.get('message')}")

    nsid = data["user"]["id"]
    os.makedirs(os.path.dirname(NSID_CACHE), exist_ok=True)
    with open(NSID_CACHE, "w") as f:
        f.write(nsid)
    print(f"[Flickr] NSID: {nsid}")
    return nsid


def fetch_flickr():
    items = []
    if not FLICKR_API_KEY:
        print("[Flickr] FLICKR_API_KEY not set — skipping. "
              "Get a free key at https://www.flickr.com/services/api/keys "
              "and set it as a GitHub Secret named FLICKR_API_KEY.")
        return items

    try:
        nsid   = flickr_get_nsid()
        page   = 1
        target = 100   # fetch up to this many photos

        while len(items) < target:
            print(f"[Flickr] Fetching page {page}")
            r = requests.get(FLICKR_API_BASE, params={
                "method":        "flickr.people.getPublicPhotos",
                "api_key":       FLICKR_API_KEY,
                "user_id":       nsid,
                "extras":        "url_z,url_m,date_taken,title",
                "per_page":      100,
                "page":          page,
                "format":        "json",
                "nojsoncallback": 1,
            }, timeout=15)
            r.raise_for_status()
            data = r.json()

            if data.get("stat") != "ok":
                print(f"[Flickr] API error: {data.get('message')}")
                break

            photos = data.get("photos", {}).get("photo", [])
            if not photos:
                break

            for p in photos:
                # Prefer 640px (url_z), fall back to 240px (url_m)
                image = p.get("url_z") or p.get("url_m")
                if not image:
                    continue

                date_str = iso_date(p.get("datetaken") or "")
                if not date_str:
                    continue

                items.append({
                    "source": "flickr",
                    "title":  p.get("title") or "",
                    "url":    f"https://www.flickr.com/photos/{FLICKR_USERNAME}/{p['id']}/",
                    "image":  image,
                    "date":   date_str,
                })

            total_pages = int(data.get("photos", {}).get("pages", 1))
            if page >= total_pages:
                break
            page += 1

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
    HTML instead of XML (as of 2026). This function is kept as a no-op placeholder.
    Add 500px photos manually via _data/photos_manual.yml using source: "500px".
    """
    print("[500px] RSS feed is no longer functional (returns HTML). "
          "Add 500px photos manually to _data/photos_manual.yml.")
    return []


# ---------------------------------------------------------------------------
# Source: Instagram (manual)
# ---------------------------------------------------------------------------

def fetch_manual():
    items = []
    if not os.path.exists(MANUAL_YML):
        print("[Instagram/manual] No photos_manual.yml found — skipping")
        return items
    try:
        with open(MANUAL_YML) as f:
            data = yaml.safe_load(f) or {}
        entries = data.get("entries") or []
        for e in entries:
            d = iso_date(e.get("date") or "")
            if not d or not e.get("image") or not e.get("url"):
                continue
            items.append({
                "source": e.get("source", "instagram"),
                "title":  e.get("title") or "",
                "url":    e["url"],
                "image":  e["image"],
                "date":   d,
            })
        print(f"[Instagram/manual] {len(items)} entries")
    except Exception as e:
        print(f"[Instagram/manual] Error: {e}")
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

    # Sort by date descending
    all_items.sort(key=lambda x: x.get("date", ""), reverse=True)

    # Cap total
    all_items = all_items[:MAX_ITEMS]

    os.makedirs(os.path.dirname(OUTPUT_JSON), exist_ok=True)
    with open(OUTPUT_JSON, "w") as f:
        json.dump(all_items, f, indent=2, ensure_ascii=False)

    print(f"\n✓ Wrote {len(all_items)} photos to {OUTPUT_JSON}")
    if not FLICKR_API_KEY:
        print("  ⚠  Flickr photos not included — set FLICKR_API_KEY env var or GitHub Secret")


if __name__ == "__main__":
    main()
