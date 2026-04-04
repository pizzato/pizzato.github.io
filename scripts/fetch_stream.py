#!/usr/bin/env python3
"""
fetch_stream.py — Aggregate activity stream for pizzato.github.io

Sources:
  - Medium RSS feed (public, no auth)
  - Semantic Scholar papers (REST API, no auth)
  - Jekyll blog posts (local _posts/ directory)
  - Manual X / LinkedIn entries (_data/stream_manual.yml)

Output: _data/stream.json (sorted by date desc, capped at 50 items)

Usage:
  pip install requests feedparser PyYAML python-frontmatter
  python scripts/fetch_stream.py
"""

import glob
import json
import os
import re
import sys
from datetime import datetime, date

try:
    import feedparser
    import frontmatter
    import requests
    import yaml
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Run: pip install requests feedparser PyYAML python-frontmatter")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MEDIUM_USER = "@pizzato"
SCHOLAR_AUTHOR_NAME = "Luiz Pizzato"
SCHOLAR_AFFILIATION_HINT = "Commonwealth Bank"  # helps disambiguate

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSTS_DIR = os.path.join(REPO_ROOT, "_posts")
MANUAL_YML = os.path.join(REPO_ROOT, "_data", "stream_manual.yml")
OUTPUT_JSON = os.path.join(REPO_ROOT, "_data", "stream.json")

MAX_ITEMS = 50

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def iso_date(value):
    """Normalise various date representations to 'YYYY-MM-DD' string."""
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ",
                    "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
            try:
                return datetime.strptime(value[:len(fmt) + 5].strip(), fmt).strftime("%Y-%m-%d")
            except ValueError:
                pass
        # feedparser struct_time
    if hasattr(value, "tm_year"):
        return f"{value.tm_year:04d}-{value.tm_mon:02d}-{value.tm_mday:02d}"
    return None


def sort_key(item):
    d = item.get("date") or "0000-00-00"
    return d


# ---------------------------------------------------------------------------
# Source: Medium RSS
# ---------------------------------------------------------------------------

def fetch_medium():
    items = []
    url = f"https://medium.com/feed/{MEDIUM_USER}"
    print(f"[Medium] Fetching {url}")
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            pub = entry.get("published_parsed") or entry.get("updated_parsed")
            d = iso_date(pub) if pub else None
            if not d:
                continue

            # Try to extract first image from content
            thumb = ""
            content = ""
            if entry.get("content"):
                content = entry.content[0].value
            elif entry.get("summary"):
                content = entry.summary
            m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', content)
            if m:
                thumb = m.group(1)

            items.append({
                "type": "medium",
                "title": entry.title,
                "url": entry.link,
                "date": d,
                "source": "Medium",
                "image": thumb,
            })
        print(f"[Medium] {len(items)} items")
    except Exception as e:
        print(f"[Medium] Error: {e}")
    return items


# ---------------------------------------------------------------------------
# Source: Semantic Scholar
# ---------------------------------------------------------------------------

def find_scholar_author_id():
    """Search Semantic Scholar for the author and return the best-match ID."""
    url = "https://api.semanticscholar.org/graph/v1/author/search"
    params = {
        "query": SCHOLAR_AUTHOR_NAME,
        "fields": "name,affiliations,paperCount",
        "limit": 10,
    }
    print(f"[Scholar] Searching for author: {SCHOLAR_AUTHOR_NAME}")
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        candidates = data.get("data", [])
        if not candidates:
            print("[Scholar] No candidates found")
            return None

        # Score candidates: prefer those with matching affiliation hint or higher paper count
        def score(c):
            affil_str = " ".join(
                a.get("name", "") for a in (c.get("affiliations") or [])
            ).lower()
            s = c.get("paperCount", 0)
            if SCHOLAR_AFFILIATION_HINT.lower() in affil_str:
                s += 1000
            if SCHOLAR_AUTHOR_NAME.lower() in c.get("name", "").lower():
                s += 500
            return s

        best = max(candidates, key=score)
        print(f"[Scholar] Best match: {best.get('name')} (id={best['authorId']}, papers={best.get('paperCount')})")
        return best["authorId"]
    except Exception as e:
        print(f"[Scholar] Author search error: {e}")
        return None


def fetch_scholar():
    items = []
    author_id = find_scholar_author_id()
    if not author_id:
        return items

    url = f"https://api.semanticscholar.org/graph/v1/author/{author_id}/papers"
    params = {
        "fields": "title,year,publicationDate,externalIds,venue",
        "limit": 20,
        "sort": "publicationDate:desc",
    }
    print(f"[Scholar] Fetching papers for author {author_id}")
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        for paper in data.get("data", []):
            pub_date = paper.get("publicationDate")
            if not pub_date and paper.get("year"):
                pub_date = f"{paper['year']}-01-01"
            if not pub_date:
                continue

            # Build URL: prefer DOI, fallback to Semantic Scholar paper page
            ext = paper.get("externalIds") or {}
            if ext.get("DOI"):
                paper_url = f"https://doi.org/{ext['DOI']}"
            elif paper.get("paperId"):
                paper_url = f"https://www.semanticscholar.org/paper/{paper['paperId']}"
            else:
                continue

            items.append({
                "type": "scholar",
                "title": paper.get("title", "Untitled"),
                "url": paper_url,
                "date": pub_date,
                "source": "Scholar",
                "venue": paper.get("venue") or "",
            })
        print(f"[Scholar] {len(items)} items")
    except Exception as e:
        print(f"[Scholar] Papers fetch error: {e}")
    return items


# ---------------------------------------------------------------------------
# Source: Jekyll blog posts
# ---------------------------------------------------------------------------

def fetch_posts():
    items = []
    pattern = os.path.join(POSTS_DIR, "*.md")
    files = glob.glob(pattern) + glob.glob(os.path.join(POSTS_DIR, "*.markdown"))
    print(f"[Posts] Found {len(files)} post files")
    for path in files:
        try:
            post = frontmatter.load(path)
            title = post.get("title", "")
            if not title:
                continue

            post_date = post.get("date")
            d = iso_date(post_date)
            if not d:
                # Try to extract date from filename: YYYY-MM-DD-slug.md
                fname = os.path.basename(path)
                m = re.match(r"(\d{4}-\d{2}-\d{2})", fname)
                if m:
                    d = m.group(1)
            if not d:
                continue

            # Build URL from filename slug
            fname = os.path.basename(path)
            slug = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", fname)
            slug = re.sub(r"\.(md|markdown)$", "", slug)
            post_url = f"/{slug}/"

            items.append({
                "type": "post",
                "title": title,
                "url": post_url,
                "date": d,
                "source": "Blog",
            })
        except Exception as e:
            print(f"[Posts] Error reading {path}: {e}")
    print(f"[Posts] {len(items)} items")
    return items


# ---------------------------------------------------------------------------
# Source: Manual YAML (X / LinkedIn)
# ---------------------------------------------------------------------------

def fetch_manual():
    items = []
    if not os.path.exists(MANUAL_YML):
        print("[Manual] No stream_manual.yml found, skipping")
        return items
    try:
        with open(MANUAL_YML) as f:
            data = yaml.safe_load(f)
        entries = (data or {}).get("entries") or []
        for entry in entries:
            d = iso_date(entry.get("date"))
            if not d or not entry.get("title") or not entry.get("url"):
                continue
            t = entry.get("type", "twitter")
            source_map = {"twitter": "X", "linkedin": "LinkedIn"}
            items.append({
                "type": t,
                "title": entry["title"],
                "url": entry["url"],
                "date": d,
                "source": source_map.get(t, t.capitalize()),
            })
        print(f"[Manual] {len(items)} items")
    except Exception as e:
        print(f"[Manual] Error: {e}")
    return items


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    all_items = []
    all_items.extend(fetch_medium())
    all_items.extend(fetch_scholar())
    all_items.extend(fetch_posts())
    all_items.extend(fetch_manual())

    # Remove items without a date or URL
    all_items = [i for i in all_items if i.get("date") and i.get("url")]

    # Sort descending by date
    all_items.sort(key=sort_key, reverse=True)

    # Cap at MAX_ITEMS
    all_items = all_items[:MAX_ITEMS]

    os.makedirs(os.path.dirname(OUTPUT_JSON), exist_ok=True)
    with open(OUTPUT_JSON, "w") as f:
        json.dump(all_items, f, indent=2, ensure_ascii=False)

    print(f"\n✓ Wrote {len(all_items)} items to {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
