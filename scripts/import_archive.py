#!/usr/bin/env python3
"""
import_archive.py — Import X (Twitter) or LinkedIn archive data into stream_manual.yml

Usage:
  # X/Twitter — point at the tweets.js file inside the archive:
  python scripts/import_archive.py --twitter /path/to/twitter-archive/data/tweets.js

  # LinkedIn — point at the "Share and Comments.csv" file inside the archive:
  python scripts/import_archive.py --linkedin "/path/to/linkedin-archive/Share and Comments.csv"

  # Both at once:
  python scripts/import_archive.py \\
      --twitter /path/to/twitter-archive/data/tweets.js \\
      --linkedin "/path/to/linkedin-archive/Share and Comments.csv"

After running, execute the fetch script to rebuild stream.json:
  python scripts/fetch_stream.py

Notes:
  - Existing entries in stream_manual.yml are preserved; duplicates (same URL) are skipped.
  - Retweets and reply tweets are skipped by default (use --include-retweets / --include-replies).
  - Tweets/posts with no text content are skipped.
  - LinkedIn entries without a post URL are included with a fallback profile URL.
"""

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timezone

try:
    import yaml
except ImportError:
    print("Missing dependency: PyYAML")
    print("Run: pip3 install PyYAML")
    sys.exit(1)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANUAL_YML = os.path.join(REPO_ROOT, "_data", "stream_manual.yml")

TWITTER_USERNAME = "luizpizzato"
LINKEDIN_PROFILE_URL = "https://www.linkedin.com/in/pizzato/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_manual_yml():
    if not os.path.exists(MANUAL_YML):
        return {"entries": []}
    with open(MANUAL_YML) as f:
        data = yaml.safe_load(f) or {}
    if "entries" not in data or data["entries"] is None:
        data["entries"] = []
    return data


def save_manual_yml(data):
    # Preserve the header comment by writing it manually
    header = """\
# Manual stream entries for X (Twitter) and LinkedIn.
#
# After adding entries here, run the fetch script to rebuild stream.json:
#   python scripts/fetch_stream.py
#
# Or just commit this file — the daily GitHub Action will pick it up.
#
# Entry format:
#   - type:  twitter   (or: linkedin)
#     title: "First line / caption of the post"
#     url:   "https://x.com/luizpizzato/status/..."
#     date:  "YYYY-MM-DD"
#
# To populate from a platform data export, run:
#   python scripts/import_archive.py --twitter <path/to/tweets.js>
#   python scripts/import_archive.py --linkedin <path/to/Share and Comments.csv>

"""
    with open(MANUAL_YML, "w") as f:
        f.write(header)
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False,
                  sort_keys=False, indent=2)


def existing_urls(entries):
    return {e.get("url") for e in entries if e.get("url")}


def first_line(text, max_chars=120):
    """Return the first non-empty line of text, truncated to max_chars."""
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:max_chars] + ("…" if len(line) > max_chars else "")
    return text.strip()[:max_chars]


def clean_tweet_text(text):
    """Remove trailing URLs (t.co links at the end of tweet text)."""
    return re.sub(r'\s*https://t\.co/\S+$', '', text).strip()


# ---------------------------------------------------------------------------
# X / Twitter parser
# ---------------------------------------------------------------------------

def parse_twitter(tweets_js_path, include_retweets=False, include_replies=False):
    """
    Parse tweets.js from a Twitter/X data archive.

    The file looks like:
      window.YTD.tweets.part0 = [ { "tweet": { ... } }, ... ]
    """
    print(f"[Twitter] Reading {tweets_js_path}")
    with open(tweets_js_path, encoding="utf-8") as f:
        raw = f.read()

    # Strip the JS assignment prefix to get pure JSON
    raw = re.sub(r"^\s*window\.\S+\s*=\s*", "", raw, count=1).strip()
    # Remove trailing semicolon if present
    raw = raw.rstrip(";").strip()

    try:
        records = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[Twitter] JSON parse error: {e}")
        sys.exit(1)

    items = []
    skipped = 0

    for record in records:
        tweet = record.get("tweet") or record  # handle both wrapped and flat formats

        text = tweet.get("full_text") or tweet.get("text") or ""
        tweet_id = tweet.get("id_str") or tweet.get("id") or ""

        # Skip retweets
        if not include_retweets and text.startswith("RT @"):
            skipped += 1
            continue

        # Skip replies (in_reply_to_status_id is set)
        if not include_replies and tweet.get("in_reply_to_status_id_str"):
            skipped += 1
            continue

        text = clean_tweet_text(text)
        if not text:
            skipped += 1
            continue

        # Parse date: "Fri Apr 05 12:34:56 +0000 2024"
        created_at = tweet.get("created_at", "")
        try:
            dt = datetime.strptime(created_at, "%a %b %d %H:%M:%S %z %Y")
            date_str = dt.strftime("%Y-%m-%d")
        except ValueError:
            # Fallback: try ISO format
            try:
                dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                date_str = dt.strftime("%Y-%m-%d")
            except ValueError:
                skipped += 1
                continue

        url = f"https://x.com/{TWITTER_USERNAME}/status/{tweet_id}"

        items.append({
            "type": "twitter",
            "title": first_line(text),
            "url": url,
            "date": date_str,
        })

    print(f"[Twitter] Parsed {len(items)} tweets, skipped {skipped}")
    return items


# ---------------------------------------------------------------------------
# LinkedIn parser
# ---------------------------------------------------------------------------

def parse_linkedin(csv_path):
    """
    Parse 'Share and Comments.csv' from a LinkedIn data archive.

    Typical columns (may vary by export date):
      Date, ShareCommentary, ShareLink, PostLink, MediaUrl, Visibility, ...
    """
    print(f"[LinkedIn] Reading {csv_path}")

    items = []
    skipped = 0

    with open(csv_path, encoding="utf-8-sig") as f:
        # LinkedIn CSVs sometimes have BOM and inconsistent column names
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        print(f"[LinkedIn] Columns: {headers}")

        # Normalise header lookup (case-insensitive, strip spaces)
        def col(row, *candidates):
            for c in candidates:
                for h in headers:
                    if h.strip().lower() == c.lower():
                        return (row.get(h) or "").strip()
            return ""

        for row in reader:
            text = col(row, "ShareCommentary", "Commentary", "Text", "Content")
            date_raw = col(row, "Date", "Published At", "CreatedAt")
            post_url = col(row, "PostLink", "Post URL", "URL", "Link")
            share_link = col(row, "ShareLink", "Share Link")

            if not text:
                skipped += 1
                continue

            # Parse date — LinkedIn exports as "2024-03-15 10:30:00 UTC" or ISO
            date_str = None
            for fmt in ("%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%d %H:%M:%S",
                        "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S",
                        "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(date_raw.strip(), fmt)
                    date_str = dt.strftime("%Y-%m-%d")
                    break
                except ValueError:
                    continue

            if not date_str:
                skipped += 1
                continue

            # Best URL: PostLink > ShareLink > fallback to profile
            url = post_url or share_link or LINKEDIN_PROFILE_URL

            # Skip posts made to LinkedIn Groups (private/semi-private groups
            # that don't belong on a public stream)
            if "groupPost" in url:
                skipped += 1
                continue

            items.append({
                "type": "linkedin",
                "title": first_line(text),
                "url": url,
                "date": date_str,
            })

    print(f"[LinkedIn] Parsed {len(items)} posts, skipped {skipped}")
    return items


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Import X/Twitter or LinkedIn archive data into stream_manual.yml"
    )
    parser.add_argument("--twitter", metavar="tweets.js",
                        help="Path to tweets.js from a Twitter/X data archive")
    parser.add_argument("--linkedin", metavar="Share and Comments.csv",
                        help="Path to 'Share and Comments.csv' from a LinkedIn archive")
    parser.add_argument("--include-retweets", action="store_true",
                        help="Include retweets (skipped by default)")
    parser.add_argument("--include-replies", action="store_true",
                        help="Include reply tweets (skipped by default)")
    args = parser.parse_args()

    if not args.twitter and not args.linkedin:
        parser.print_help()
        sys.exit(1)

    data = load_manual_yml()
    seen = existing_urls(data["entries"])
    new_items = []

    if args.twitter:
        if not os.path.exists(args.twitter):
            print(f"[Twitter] File not found: {args.twitter}")
            sys.exit(1)
        tw_items = parse_twitter(args.twitter,
                                 include_retweets=args.include_retweets,
                                 include_replies=args.include_replies)
        for item in tw_items:
            if item["url"] not in seen:
                new_items.append(item)
                seen.add(item["url"])

    if args.linkedin:
        if not os.path.exists(args.linkedin):
            print(f"[LinkedIn] File not found: {args.linkedin}")
            sys.exit(1)
        li_items = parse_linkedin(args.linkedin)
        for item in li_items:
            if item["url"] not in seen:
                new_items.append(item)
                seen.add(item["url"])

    if not new_items:
        print("\nNo new entries to add (all already present or nothing parsed).")
        return

    # Sort new items by date desc before appending
    new_items.sort(key=lambda x: x.get("date", ""), reverse=True)
    data["entries"].extend(new_items)
    # Re-sort all entries by date desc
    data["entries"].sort(key=lambda x: x.get("date", ""), reverse=True)

    save_manual_yml(data)
    print(f"\n✓ Added {len(new_items)} new entries to {MANUAL_YML}")
    print("  Run 'python scripts/fetch_stream.py' to rebuild stream.json")


if __name__ == "__main__":
    main()
