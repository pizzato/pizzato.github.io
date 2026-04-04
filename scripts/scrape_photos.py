#!/usr/bin/env python3
"""
scrape_photos.py — Bulk-import photos from Flickr, 500px, and Instagram
                   into _data/photos_manual.yml (consumed by fetch_photos.py)

Usage:
  # Scrape ALL public Flickr photos (no login, no API key):
  python scripts/scrape_photos.py --flickr

  # Process 500px data export ZIP (download from 500px Settings → Privacy → Request your data):
  python scripts/scrape_photos.py --500px /path/to/500px-data-export.zip

  # Process Instagram data export directory (download from Instagram Settings
  # → Your activity → Download your information → select JSON format):
  python scripts/scrape_photos.py --instagram /path/to/instagram-archive/

  # All at once:
  python scripts/scrape_photos.py --flickr \\
      --500px /path/to/500px.zip \\
      --instagram /path/to/instagram-archive/

After running, rebuild photos.json:
  python scripts/fetch_photos.py

Notes:
  - Existing entries in photos_manual.yml are preserved; duplicates (same URL) skipped.
  - Flickr: scrapes all paginated pages of the public photostream. No account needed.
  - 500px: reads the ZIP export. Image quality depends on what 500px includes in the export.
  - Instagram: reads posts_N.json from the archive. ⚠ CDN image URLs are NOT included
    in Instagram's export — only local file paths. The script writes entries with
    image: "" so you can fill them in, or use the post permalink-only entries.
"""

import argparse
import json
import os
import re
import sys
import time
import zipfile
from datetime import datetime, timezone

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
INSTAGRAM_USERNAME   = "kinhopizzato"
FIVEPX_USERNAME      = "kinho"

REPO_ROOT            = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANUAL_YML           = os.path.join(REPO_ROOT, "_data", "photos_manual.yml")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/123.0.0.0 Safari/537.36"
}

# ---------------------------------------------------------------------------
# YAML helpers
# ---------------------------------------------------------------------------

def load_manual():
    if not os.path.exists(MANUAL_YML):
        return {"entries": []}
    with open(MANUAL_YML) as f:
        data = yaml.safe_load(f) or {}
    if "entries" not in data or data["entries"] is None:
        data["entries"] = []
    return data


def save_manual(data):
    header = """\
# Manual photo entries for Instagram, 500px, and any other source.
#
# After adding entries here, run the fetch script to rebuild photos.json:
#   python scripts/fetch_photos.py
#
# NOTE ON PLATFORMS:
#   - Flickr: auto-fetched via public feed (20 most recent); ALL photos via scrape_photos.py
#   - 500px:  RSS feed is dead as of 2026 — add photos here manually (source: "500px")
#   - Instagram: requires OAuth setup — add photos here manually (source: "instagram")
#
# Entry format:
#   - source: flickr              (or: instagram, 500px, other)
#     title:  "Caption or description"
#     url:    "https://www.flickr.com/photos/kinho/12345/"
#     image:  "https://live.staticflickr.com/..."   # direct image URL
#     date:   "YYYY-MM-DD"
#
# Auto-populated by: python scripts/scrape_photos.py

"""
    with open(MANUAL_YML, "w") as f:
        f.write(header)
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False,
                  sort_keys=False, indent=2)


def existing_urls(entries):
    return {e.get("url") for e in entries if e.get("url")}


# ---------------------------------------------------------------------------
# Flickr scraper
# ---------------------------------------------------------------------------

def _parse_flickr_page(html):
    """
    Extract photo objects from Flickr's embedded page JSON.
    Returns list of dicts: {title, url, image, date, source}.
    """
    photos = []

    # Find every photo-model block in the embedded JS
    # Each looks like: {"_flickrModelRegistry":"photo-models","title":"...","sizes":{...},"dateTaken":"...","id":"..."}
    # The z-size URL: "z":{"data":{"url":"\/\/live.staticflickr.com\/..."}}
    # URLs use escaped slashes (\/)

    # Split on photo-model registry markers to process each photo block
    blocks = re.split(r'"_flickrModelRegistry":"photo-models"', html)
    if len(blocks) < 2:
        return photos

    for block in blocks[1:]:  # skip first split (before first photo)
        # Extract title
        title_m = re.search(r'"title":"((?:[^"\\]|\\.)*)"', block)
        title = title_m.group(1).replace('\\"', '"') if title_m else ""

        # Extract z-size URL (640px wide) — unescape forward slashes
        z_url_m = re.search(r'"z":\{"data":\{"displayUrl":"((?:[^"\\]|\\.)*?)"', block)
        if not z_url_m:
            # Try n-size (320px) as fallback
            z_url_m = re.search(r'"n":\{"data":\{"displayUrl":"((?:[^"\\]|\\.)*?)"', block)
        if not z_url_m:
            continue
        image = z_url_m.group(1).replace('\/', '/')
        if image.startswith('//'):
            image = 'https:' + image

        # Extract date taken
        date_m = re.search(r'"dateTaken":"(\d{4}-\d{2}-\d{2})', block)
        if not date_m:
            continue
        date_str = date_m.group(1)

        # Extract photo ID (used to build the page URL)
        id_m = re.search(r'"id":"(\d{8,12})"[,}]', block)
        if not id_m:
            continue
        photo_id = id_m.group(1)
        photo_url = f"https://www.flickr.com/photos/{FLICKR_USERNAME}/{photo_id}/"

        photos.append({
            "source": "flickr",
            "title":  title,
            "url":    photo_url,
            "image":  image,
            "date":   date_str,
        })

    return photos


def scrape_flickr():
    items = []
    seen_ids = set()
    page = 1

    print(f"[Flickr] Scraping all public photos for '{FLICKR_USERNAME}'")

    while True:
        url = FLICKR_PROFILE_URL if page == 1 else f"{FLICKR_PROFILE_URL}page{page}/"
        print(f"[Flickr] Page {page}: {url}")
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 404:
                print(f"[Flickr] No more pages (404 on page {page})")
                break
            r.raise_for_status()
        except Exception as e:
            print(f"[Flickr] Request failed on page {page}: {e}")
            break

        page_photos = _parse_flickr_page(r.text)

        if not page_photos:
            print(f"[Flickr] No photos found on page {page} — stopping")
            break

        new_this_page = 0
        for p in page_photos:
            pid = p["url"]
            if pid not in seen_ids:
                seen_ids.add(pid)
                items.append(p)
                new_this_page += 1

        print(f"[Flickr] Page {page}: {new_this_page} new photos (total so far: {len(items)})")

        if new_this_page == 0:
            print("[Flickr] No new photos — stopping pagination")
            break

        page += 1
        time.sleep(0.8)   # polite delay between pages

    print(f"[Flickr] Done — {len(items)} total photos")
    return items


# ---------------------------------------------------------------------------
# 500px export parser
# ---------------------------------------------------------------------------

def parse_500px(zip_path):
    """
    Parse a 500px data export ZIP file.

    500px exports their data as a ZIP containing one or more JSON files.
    Typical structure:
      photos.json  — array of photo objects with 'name', 'taken_at'/'created_at',
                     'image_url'/'url'/'images', 'url'/'permalink'
    """
    items = []
    print(f"[500px] Reading export: {zip_path}")

    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            names = zf.namelist()
            print(f"[500px] Files in archive: {names}")

            # Find JSON files that look like photo data
            json_files = [n for n in names if n.lower().endswith('.json')]
            if not json_files:
                print("[500px] No JSON files found in archive")
                return items

            for jf in json_files:
                with zf.open(jf) as f:
                    try:
                        data = json.load(f)
                    except json.JSONDecodeError:
                        print(f"[500px] Could not parse {jf}")
                        continue

                # Handle both list and dict root formats
                records = data if isinstance(data, list) else data.get('photos', data.get('items', []))
                if not isinstance(records, list):
                    continue

                print(f"[500px] {jf}: {len(records)} records")

                for rec in records:
                    # Title — try multiple field names
                    title = (rec.get('name') or rec.get('title') or rec.get('caption') or "").strip()

                    # Date — try multiple field names
                    raw_date = (rec.get('taken_at') or rec.get('created_at') or
                                rec.get('date') or rec.get('uploaded_at') or "")
                    if isinstance(raw_date, (int, float)):
                        raw_date = datetime.fromtimestamp(raw_date, tz=timezone.utc).strftime("%Y-%m-%d")
                    elif isinstance(raw_date, str):
                        raw_date = raw_date[:10]  # keep YYYY-MM-DD portion
                    if not raw_date or len(raw_date) < 10:
                        continue

                    # Photo page URL — try multiple field names
                    page_url = (rec.get('url') or rec.get('permalink') or rec.get('link') or "")
                    if page_url and not page_url.startswith('http'):
                        page_url = "https://500px.com" + page_url
                    if not page_url and rec.get('id'):
                        page_url = f"https://500px.com/photo/{rec['id']}"
                    if not page_url:
                        continue

                    # Image URL — try multiple field names
                    image_url = ""
                    for key in ('image_url', 'cover_url', 'image', 'photo_url'):
                        if rec.get(key):
                            image_url = rec[key]
                            break
                    # Some exports nest images as a list
                    if not image_url and isinstance(rec.get('images'), list):
                        imgs = sorted(rec['images'],
                                      key=lambda x: x.get('size', 0) if isinstance(x, dict) else 0)
                        for img in reversed(imgs):
                            if isinstance(img, dict) and img.get('url'):
                                image_url = img['url']
                                break

                    if not image_url:
                        print(f"[500px] No image URL for '{title}' ({page_url}) — skipping")
                        continue

                    items.append({
                        "source": "500px",
                        "title":  title,
                        "url":    page_url,
                        "image":  image_url,
                        "date":   raw_date,
                    })

    except zipfile.BadZipFile:
        print(f"[500px] Not a valid ZIP file: {zip_path}")
    except Exception as e:
        print(f"[500px] Error: {e}")

    print(f"[500px] {len(items)} photos parsed")
    return items


# ---------------------------------------------------------------------------
# Instagram archive parser
# ---------------------------------------------------------------------------

def parse_instagram(archive_dir):
    """
    Parse an Instagram data export directory (JSON format).

    Download from: Instagram → Settings → Your activity →
                   Download your information → Format: JSON → Request download

    The archive contains content/posts_1.json, posts_2.json, etc.
    Each file is a list of post objects, each with a 'media' list.

    ⚠ Instagram exports do NOT include CDN image URLs — only local file paths
      (e.g. media/posts/202201/photo.jpg) that only exist inside the ZIP.
      This parser writes the post permalink as 'url' and leaves 'image' empty.
      To fill in image URLs, host the photos from your archive and update manually,
      or use the entries as link-only stream items (without photo thumbnail).
    """
    items = []
    print(f"[Instagram] Reading archive: {archive_dir}")

    if not os.path.isdir(archive_dir):
        print(f"[Instagram] Not a directory: {archive_dir}")
        return items

    # Find all posts_N.json files
    import glob
    post_files = sorted(
        glob.glob(os.path.join(archive_dir, "content", "posts_*.json")) +
        glob.glob(os.path.join(archive_dir, "posts_*.json"))
    )

    if not post_files:
        print(f"[Instagram] No posts_*.json found in {archive_dir}/content/")
        print("  Expected path: <archive_dir>/content/posts_1.json")
        return items

    for pf in post_files:
        print(f"[Instagram] Reading {os.path.basename(pf)}")
        try:
            with open(pf, encoding="utf-8") as f:
                posts = json.load(f)
        except Exception as e:
            print(f"[Instagram] Could not parse {pf}: {e}")
            continue

        for post in posts:
            media_list = post.get("media") or []
            for media in media_list:
                # Timestamp
                ts = media.get("creation_timestamp") or post.get("creation_timestamp")
                if not ts:
                    continue
                date_str = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")

                # Caption / title (from post-level title or media-level)
                title = (media.get("title") or post.get("title") or "").strip()

                # Instagram post URL — not directly in the export, so we build it
                # from cross_post_source if available, otherwise leave empty
                post_url = ""
                for key in ("cross_post_source", "media_metadata"):
                    src = media.get(key) or {}
                    if isinstance(src, dict):
                        for u in ("fb_url", "ig_url", "url"):
                            if src.get(u):
                                post_url = src[u]
                                break
                if not post_url:
                    post_url = f"https://www.instagram.com/{INSTAGRAM_USERNAME}/"

                # Image URL — not available in standard export
                # The 'uri' field is a local path (media/posts/.../file.jpg)
                image_url = ""   # intentionally empty — see docstring

                items.append({
                    "source": "instagram",
                    "title":  title,
                    "url":    post_url,
                    "image":  image_url,   # empty — fill in manually or host locally
                    "date":   date_str,
                })

    print(f"[Instagram] {len(items)} posts parsed")
    if items:
        print("  ⚠  image URLs are empty — Instagram exports don't include CDN URLs.")
        print("     Options:")
        print("     1. Open each post on instagram.com, right-click photo → Copy image address")
        print("     2. Host the photos from your archive and update 'image' fields")
        print("     3. Leave image empty — entries still appear in the Stream but not the photo grid")

    return items


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Bulk-import photos into _data/photos_manual.yml",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/scrape_photos.py --flickr
  python scripts/scrape_photos.py --500px ~/Downloads/500px-export.zip
  python scripts/scrape_photos.py --instagram ~/Downloads/instagram-archive/
  python scripts/scrape_photos.py --flickr --instagram ~/Downloads/instagram-archive/
        """
    )
    parser.add_argument("--flickr", action="store_true",
                        help="Scrape all public Flickr photos (no API key needed)")
    parser.add_argument("--500px", metavar="export.zip",
                        dest="fivepx",
                        help="Path to 500px data export ZIP file")
    parser.add_argument("--instagram", metavar="archive-dir/",
                        help="Path to extracted Instagram data archive directory")
    args = parser.parse_args()

    if not args.flickr and not args.fivepx and not args.instagram:
        parser.print_help()
        sys.exit(1)

    data = load_manual()
    seen = existing_urls(data["entries"])
    new_items = []

    if args.flickr:
        for item in scrape_flickr():
            if item["url"] not in seen:
                new_items.append(item)
                seen.add(item["url"])

    if args.fivepx:
        if not os.path.exists(args.fivepx):
            print(f"[500px] File not found: {args.fivepx}")
            sys.exit(1)
        for item in parse_500px(args.fivepx):
            if item["url"] not in seen:
                new_items.append(item)
                seen.add(item["url"])

    if args.instagram:
        for item in parse_instagram(args.instagram):
            if item["url"] not in seen:
                new_items.append(item)
                seen.add(item["url"])

    if not new_items:
        print("\nNo new entries to add.")
        return

    # Sort new items by date desc before appending
    new_items.sort(key=lambda x: x.get("date", ""), reverse=True)
    data["entries"].extend(new_items)
    # Re-sort all entries by date desc
    data["entries"].sort(key=lambda x: x.get("date", ""), reverse=True)

    save_manual(data)
    print(f"\n✓ Added {len(new_items)} new entries to {MANUAL_YML}")
    print("  Run 'python scripts/fetch_photos.py' to rebuild photos.json")


if __name__ == "__main__":
    main()
