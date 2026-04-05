#!/usr/bin/env python3
"""
scrape_photos.py — Bulk-import photos from Flickr, 500px, and Instagram
                   into _data/photos_manual.yml (consumed by fetch_photos.py)

Usage:
  # Scrape ALL public Flickr photos (no login, no API key):
  python scripts/scrape_photos.py --flickr

  # Scrape ALL public 500px photos via their GraphQL API (no login, no API key):
  python scripts/scrape_photos.py --500px

  # Process Instagram data export directory (download from Instagram Settings
  # → Your activity → Download your information → select JSON format):
  python scripts/scrape_photos.py --instagram /path/to/instagram-archive/

  # All automated sources at once:
  python scripts/scrape_photos.py --flickr --500px

Then rebuild photos.json:
  python scripts/fetch_photos.py

Notes:
  - Existing entries in photos_manual.yml are preserved; duplicates (same URL) skipped.
  - Flickr: scrapes all paginated pages of the public photostream. No account needed.
  - 500px: uses their public GraphQL API (same one the website uses). No account or
    API key needed. Retrieves all public photos with pagination.
  - Instagram: reads posts_N.json from the data archive download. ⚠ CDN image URLs
    are NOT included in Instagram exports — only local file paths. Entries are written
    with image: "" so you can fill them in, or leave them as link-only stream entries.

pip dependencies: requests PyYAML
"""

import argparse
import json
import os
import re
import sys
import time
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

FIVEPX_USERNAME      = "kinho"
FIVEPX_GRAPHQL_URL   = "https://api.500px.com/graphql"

INSTAGRAM_USERNAME   = "kinhopizzato"

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
#   - 500px:  scraped via public GraphQL API; run: python scripts/scrape_photos.py --500px
#   - Instagram: export archive required; run: python scripts/scrape_photos.py --instagram <dir>
#
# Entry format:
#   - source: flickr              (or: 500px, instagram, other)
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


def iso_date(value):
    if isinstance(value, str) and value:
        return value[:10]   # ISO strings already start with YYYY-MM-DD
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%d")
    return None


# ---------------------------------------------------------------------------
# Flickr scraper
# ---------------------------------------------------------------------------

def _parse_flickr_page(html):
    photos = []
    blocks = re.split(r'"_flickrModelRegistry":"photo-models"', html)
    for block in blocks[1:]:
        title_m = re.search(r'"title":"((?:[^"\\]|\\.)*)"', block)
        title = title_m.group(1).replace('\\"', '"') if title_m else ""

        z_url_m = re.search(r'"z":\{"data":\{"displayUrl":"((?:[^"\\]|\\.)*?)"', block)
        if not z_url_m:
            z_url_m = re.search(r'"n":\{"data":\{"displayUrl":"((?:[^"\\]|\\.)*?)"', block)
        if not z_url_m:
            continue
        image = z_url_m.group(1).replace('\/', '/')
        if image.startswith('//'):
            image = 'https:' + image

        date_m = re.search(r'"dateTaken":"(\d{4}-\d{2}-\d{2})', block)
        if not date_m:
            continue

        id_m = re.search(r'"id":"(\d{8,12})"[,}]', block)
        if not id_m:
            continue

        photo_id = id_m.group(1)
        photos.append({
            "source": "flickr",
            "title":  title,
            "url":    f"https://www.flickr.com/photos/{FLICKR_USERNAME}/{photo_id}/",
            "image":  image,
            "date":   date_m.group(1),
        })
    return photos


def scrape_flickr():
    items = []
    seen_urls = set()
    page = 1
    print(f"[Flickr] Scraping all public photos for '{FLICKR_USERNAME}'")

    while True:
        url = FLICKR_PROFILE_URL if page == 1 else f"{FLICKR_PROFILE_URL}page{page}/"
        print(f"[Flickr] Page {page}: {url}")
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 404:
                break
            r.raise_for_status()
        except Exception as e:
            print(f"[Flickr] Request failed on page {page}: {e}")
            break

        page_photos = _parse_flickr_page(r.text)
        if not page_photos:
            print(f"[Flickr] No photos on page {page} — stopping")
            break

        added = 0
        for p in page_photos:
            if p["url"] not in seen_urls:
                seen_urls.add(p["url"])
                items.append(p)
                added += 1

        print(f"[Flickr] Page {page}: {added} new photos (total: {len(items)})")
        if added == 0:
            break

        page += 1
        time.sleep(0.8)

    print(f"[Flickr] Done — {len(items)} total photos")
    return items


# ---------------------------------------------------------------------------
# 500px scraper (public GraphQL API — no auth required)
# ---------------------------------------------------------------------------

FIVEPX_QUERY = """
query OtherPhotosQuery($username: String!, $pageSize: Int, $after: String) {
  user: userByUsername(username: $username) {
    photos(first: $pageSize, after: $after, privacy: PROFILE, sort: ID_DESC, excludeNude: false) {
      edges {
        node {
          legacyId
          canonicalPath
          name
          takenAt
          uploadedAt
          images(sizes: [33]) {
            size
            jpegUrl
          }
        }
        cursor
      }
      totalCount
      pageInfo {
        endCursor
        hasNextPage
      }
    }
    id
  }
}
"""


def scrape_500px():
    items = []
    cursor = None
    page = 1
    total = None

    print(f"[500px] Scraping all public photos for '{FIVEPX_USERNAME}' via GraphQL API")

    while True:
        variables = {
            "username": FIVEPX_USERNAME,
            "pageSize": 50,
        }
        if cursor:
            variables["after"] = cursor

        try:
            r = requests.post(
                FIVEPX_GRAPHQL_URL,
                json={
                    "operationName": "OtherPhotosQuery",
                    "variables": variables,
                    "query": FIVEPX_QUERY,
                },
                headers={
                    **HEADERS,
                    "Content-Type":  "application/json",
                    "Origin":        "https://500px.com",
                    "Referer":       "https://500px.com/",
                },
                timeout=20,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"[500px] Request failed on page {page}: {e}")
            break

        if data.get("errors"):
            print(f"[500px] GraphQL errors: {data['errors']}")
            break

        photos_conn = data.get("data", {}).get("user", {}).get("photos", {})
        if total is None:
            total = photos_conn.get("totalCount", "?")
            print(f"[500px] Total photos: {total}")

        edges = photos_conn.get("edges", [])
        if not edges:
            break

        for edge in edges:
            node = edge.get("node", {})
            legacy_id = node.get("legacyId", "")
            name = (node.get("name") or "").strip().title()
            taken = node.get("takenAt") or node.get("uploadedAt") or ""
            date_str = iso_date(taken)
            if not date_str:
                continue

            # Use 600px JPEG (size 33); size 35 is 2048px
            imgs = node.get("images") or []
            image_url = next((img["jpegUrl"] for img in imgs if img.get("jpegUrl")), "")
            if not image_url:
                continue

            canonical = node.get("canonicalPath") or f"/photo/{legacy_id}"
            photo_url = f"https://500px.com{canonical}"

            items.append({
                "source": "500px",
                "title":  name,
                "url":    photo_url,
                "image":  image_url,
                "date":   date_str,
            })

        page_info = photos_conn.get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            break

        cursor = page_info.get("endCursor")
        print(f"[500px] Page {page}: {len(edges)} photos fetched (total so far: {len(items)})")
        page += 1
        time.sleep(0.5)

    print(f"[500px] Done — {len(items)} total photos")
    return items


# ---------------------------------------------------------------------------
# Instagram archive parser
# ---------------------------------------------------------------------------

def parse_instagram(archive_dir):
    """
    Parse an Instagram data export directory (JSON format).

    Download from: Instagram → Settings → Your activity →
                   Download your information → Format: JSON → Request download

    ⚠ Instagram exports do NOT include CDN image URLs.
      Entries are written with image: "" — fill these in manually,
      or leave them as link-only stream items (no thumbnail in gallery).
    """
    import glob

    items = []
    print(f"[Instagram] Reading archive: {archive_dir}")

    if not os.path.isdir(archive_dir):
        print(f"[Instagram] Not a directory: {archive_dir}")
        return items

    post_files = sorted(
        glob.glob(os.path.join(archive_dir, "content", "posts_*.json")) +
        glob.glob(os.path.join(archive_dir, "posts_*.json"))
    )

    if not post_files:
        print(f"[Instagram] No posts_*.json found under {archive_dir}/content/")
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
            for media in (post.get("media") or []):
                ts = media.get("creation_timestamp") or post.get("creation_timestamp")
                if not ts:
                    continue
                date_str = iso_date(int(ts))
                title = (media.get("title") or post.get("title") or "").strip()

                # Try to find an external post URL
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

                items.append({
                    "source": "instagram",
                    "title":  title,
                    "url":    post_url,
                    "image":  "",   # not available in export
                    "date":   date_str,
                })

    print(f"[Instagram] {len(items)} posts parsed")
    if items:
        print("  ⚠  image: fields are empty — Instagram exports don't include CDN URLs.")
        print("     Fill them in manually, or these entries will be skipped by the photo grid.")

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
  python scripts/scrape_photos.py --500px
  python scripts/scrape_photos.py --flickr --500px
  python scripts/scrape_photos.py --instagram ~/Downloads/instagram-archive/
        """
    )
    parser.add_argument("--flickr", action="store_true",
                        help="Scrape all public Flickr photos (no API key needed)")
    parser.add_argument("--500px", action="store_true", dest="fivepx",
                        help="Scrape all public 500px photos via GraphQL API (no auth needed)")
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
        for item in scrape_500px():
            if item["url"] not in seen:
                new_items.append(item)
                seen.add(item["url"])

    if args.instagram:
        if not os.path.exists(args.instagram):
            print(f"[Instagram] Path not found: {args.instagram}")
            sys.exit(1)
        for item in parse_instagram(args.instagram):
            if item["url"] not in seen:
                new_items.append(item)
                seen.add(item["url"])

    if not new_items:
        print("\nNo new entries to add.")
        return

    new_items.sort(key=lambda x: x.get("date", ""), reverse=True)
    data["entries"].extend(new_items)
    data["entries"].sort(key=lambda x: x.get("date", ""), reverse=True)

    save_manual(data)
    print(f"\n✓ Added {len(new_items)} new entries to {MANUAL_YML}")
    print("  Run 'python scripts/fetch_photos.py' to rebuild photos.json")


if __name__ == "__main__":
    main()
