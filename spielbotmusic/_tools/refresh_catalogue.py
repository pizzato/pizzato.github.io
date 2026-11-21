#!/usr/bin/env python3
"""Refresh the public Stephen Spielbot Music catalogue (Python 3.9+, stdlib only).

From the repository root:
    python spielbotmusic/_tools/refresh_catalogue.py --refresh
    python spielbotmusic/_tools/refresh_catalogue.py --refresh --download-thumbnails

Optional output and reusable source cache:
    python spielbotmusic/_tools/refresh_catalogue.py --refresh \
        --output /tmp/catalogue.json --cache-dir /tmp/spielbot-source-cache

The default output is ../assets/catalogue.json, relative to this script.
Without --cache-dir, source HTML lives in a temporary directory that is removed
after the run. With --cache-dir, cached pages are reused unless --refresh is set.
Raw source pages must stay outside the served spielbotmusic directory.

This reads public YouTube playlist HTML without credentials, private endpoints,
or an API key. It refreshes the explicit artist roster below; it does not discover
new artist playlists. Order, collaborations, repeated entries, Shorts, original
titles, and item-level channel evidence are preserved. Missing item metadata may
be supplemented from the same video in the collection only when that item's
channel ID matches Spielbot Music.

Missing or invalid required thumbnails are downloaded before every catalogue
write. --download-thumbnails additionally refreshes existing video thumbnails
without downgrading their resolution or replacing curated artist portraits.
The previous catalogue is left intact if retrieval, parsing, count validation,
or any required image download fails. Pagination is detected but not followed; a
larger playlist or a changed YouTube page format requires a parser update.
Video thumbnails prefer YouTube's maximum-resolution image, falling back to
standard/high-quality images and then the playlist source when unavailable.
Thumbnails are downloaded unmodified, validated as JPEG with usable dimensions,
and atomically saved beside the output in videos/<id>.jpg and artists/<slug>.jpg.
No schedule, commits, or deployment are created by this script.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlsplit
from urllib.request import urlopen


SITE_ROOT = Path(__file__).resolve().parent.parent
CHANNEL_ID = "UCm0coTP4Ztr91F5ZyYZwXTQ"
CHANNEL_URL = "https://www.youtube.com/@SpielbotMusic"
ARTISTS = [
    ("dayo-ember", "Dayo Ember", "PLHeaGxWVyVp8"),
    ("rua-vex", "Rua Vex", "PLB4KOL0CL23U"),
    ("damian-henao", "Damián Henao", "PLNqOshiTywVg"),
    ("kinho", "KINHØᴬᴵ", "PLN8w79OveH3I"),
    ("nilo-fohn", "Nilo Föhn", "PLKN9iKS-_8T4"),
    ("mick-dargo", "Mick Dargo", "PLT9A8FuBHlM8"),
    ("vaezuri", "VÆZURI", "PLRLwOWi6KH2M"),
    ("koko-yard", "Koko Yard", "PLfvMSgpo9BEY"),
    ("orla-static", "Orla Static", "PLLtWWI7ELcIs"),
    ("ixovel", "IXØVEL", "PLW48zww8S06s"),
]
COLLECTION = ("ai-music-video-network", "AI Music Video Network", "PLS5WTo4e7mhQ")
MAX_PAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


class RefreshError(Exception):
    """A source could not be verified without losing catalogue fidelity."""


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix="." + path.name,
                                         suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def text(value):
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    return (value.get("simpleText") or value.get("content")
            or "".join(run.get("text", "") for run in value.get("runs", [])))


def nodes(value, key):
    if isinstance(value, dict):
        if key in value:
            yield value[key]
        for child in value.values():
            yield from nodes(child, key)
    elif isinstance(value, list):
        for child in value:
            yield from nodes(child, key)


def display_entries(value):
    kinds = {"lockupViewModel", "shortsLockupViewModel", "playlistVideoRenderer"}
    if isinstance(value, dict):
        for key, child in value.items():
            if key in kinds:
                yield key, child
            else:
                yield from display_entries(child)
    elif isinstance(value, list):
        for child in value:
            yield from display_entries(child)


def read_page(url, cache_path, refresh):
    if refresh or not cache_path.exists():
        try:
            with urlopen(url, timeout=30) as response:
                content = response.read(MAX_PAGE_BYTES + 1)
            if len(content) > MAX_PAGE_BYTES:
                raise RefreshError("Source page exceeds the download limit: " + url)
            content.decode("utf-8")
        except (OSError, UnicodeError) as error:
            raise RefreshError("Cannot retrieve public playlist " + url) from error
        atomic_write(cache_path, content)
    html = cache_path.read_text(encoding="utf-8")
    assignment = re.search(r"(?:var\s+)?ytInitialData\s*=\s*", html)
    try:
        if assignment:
            data = json.JSONDecoder().raw_decode(html[assignment.end():])[0]
        else:
            element = re.search(
                r'<script[^>]+id=[\"\']yt-initial-data[\"\'][^>]*>(.*?)</script>',
                html, re.S,
            )
            if not element:
                raise RefreshError("Public playlist data is unavailable: " + url)
            data = json.loads(element.group(1))
    except (ValueError, TypeError) as error:
        raise RefreshError("Public playlist data could not be parsed: " + url) from error
    fetched_at = datetime.fromtimestamp(cache_path.stat().st_mtime, timezone.utc).isoformat()
    return data, fetched_at


def best_thumbnail(sources):
    valid = [source for source in sources if isinstance(source.get("url"), str)]
    return max(valid, key=lambda source: (source.get("width", 0), source.get("height", 0)))["url"] if valid else ""


def channel_fields(metadata, name=""):
    result = {"channel": name} if name else {}
    channels = [item for item in nodes(metadata, "browseEndpoint")
                if item.get("browseId", "").startswith("UC")]
    if channels:
        result["channelId"] = channels[0]["browseId"]
        canonical = channels[0].get("canonicalBaseUrl", "")
        if canonical.startswith("/") and not canonical.startswith("//"):
            result["channelUrl"] = "https://www.youtube.com" + canonical
    return result


def parse_entry(kind, row, playlist_id, fallback_index):
    if kind == "lockupViewModel":
        if row.get("contentType") != "LOCKUP_CONTENT_TYPE_VIDEO":
            return None
        command = row.get("rendererContext", {}).get("commandContext", {}).get("onTap", {}).get("innertubeCommand", {})
        watch = command.get("watchEndpoint", {})
        if watch.get("playlistId") != playlist_id:
            return None
        video_id = row.get("contentId", "")
        metadata = row.get("metadata", {}).get("lockupMetadataViewModel", {})
        thumbnail = row.get("contentImage", {}).get("thumbnailViewModel", {})
        sources = thumbnail.get("image", {}).get("sources", [])
        durations = [badge.get("text", "") for badge in nodes(thumbnail.get("overlays", []), "thumbnailBadgeViewModel")
                     if re.fullmatch(r"\d+(?::\d{2})+", badge.get("text", ""))]
        result = {"id": video_id, "title": text(metadata.get("title")),
                  "duration": durations[0] if durations else ""}
        rows = metadata.get("metadata", {}).get("contentMetadataViewModel", {}).get("metadataRows", [])
        parts = rows[0].get("metadataParts", []) if rows else []
        author = text(parts[0].get("text")) if parts else ""
        result.update(channel_fields(metadata, author))
        index = watch.get("index", fallback_index - 1) + 1
    elif kind == "shortsLockupViewModel":
        watch = row.get("onTap", {}).get("innertubeCommand", {}).get("reelWatchEndpoint", {})
        if watch.get("playlistId") != playlist_id:
            return None
        video_id = watch.get("videoId", "")
        sources = row.get("thumbnailViewModel", {}).get("thumbnailViewModel", {}).get("image", {}).get("sources", [])
        result = {"id": video_id, "title": text(row.get("overlayMetadata", {}).get("primaryText")),
                  "duration": "", "format": "short"}
        index = row.get("indexInCollection", fallback_index - 1) + 1
    else:
        video_id = row.get("videoId", "")
        watch = row.get("navigationEndpoint", {}).get("watchEndpoint", {})
        if watch.get("playlistId") not in (None, playlist_id):
            return None
        sources = row.get("thumbnail", {}).get("thumbnails", [])
        byline = row.get("shortBylineText", {})
        result = {"id": video_id, "title": text(row.get("title")),
                  "duration": text(row.get("lengthText"))}
        result.update(channel_fields(byline, text(byline)))
        index = int(text(row.get("index")) or fallback_index)
    if not VIDEO_ID.fullmatch(video_id) or not result["title"]:
        raise RefreshError("An unavailable or unrecognised playlist entry was found.")
    result.update({"playlistIndex": index,
                   "url": "https://www.youtube.com/watch?v=" + video_id + "&list=" + playlist_id + "&index=" + str(index),
                   "thumbnail": best_thumbnail(sources)})
    return result


def extract_playlist(spec, cache_dir, refresh):
    slug, name, playlist_id = spec
    url = "https://www.youtube.com/playlist?list=" + playlist_id
    data, source_fetched_at = read_page(url, cache_dir / (slug + ".html"), refresh)
    metadata = next(nodes(data, "playlistMetadataRenderer"), {})
    sidebar = next(nodes(data, "playlistSidebarPrimaryInfoRenderer"), {})
    stats = [text(item) for item in sidebar.get("stats", [])]
    reported_count = None
    for stat in stats:
        match = re.fullmatch(r"([\d,]+) videos?", stat)
        if match:
            reported_count = int(match.group(1).replace(",", ""))
            break
    if reported_count is None:
        header = next(nodes(data, "playlistHeaderRenderer"), {})
        count_text = text(header.get("numVideosText"))
        match = re.fullmatch(r"([\d,]+)(?: videos?)?", count_text)
        if match:
            reported_count = int(match.group(1).replace(",", ""))
    if reported_count is None:
        raise RefreshError("Cannot verify the public playlist count: " + name)
    videos = []
    for kind, row in display_entries(data.get("contents", {})):
        entry = parse_entry(kind, row, playlist_id, len(videos) + 1)
        if entry is not None:
            videos.append(entry)
    has_continuation = bool(list(nodes(data.get("contents", {}), "continuationItemRenderer")))
    if has_continuation or len(videos) != reported_count:
        raise RefreshError("Incomplete playlist " + name + ": read " + str(len(videos))
                           + " of " + str(reported_count) + " entries; previous catalogue retained.")
    result = {"id": slug, "name": name, "playlistId": playlist_id, "playlistUrl": url,
              "imageVideoId": videos[0]["id"] if videos else "", "reportedVideoCount": reported_count,
              "description": text(metadata.get("description")) or text(sidebar.get("description")),
              "videos": videos, "sourceUrl": url, "sourceStats": stats,
              "sourceFetchedAt": source_fetched_at, "verifiedCount": len(videos),
              "uniqueVideoCount": len({video["id"] for video in videos}),
              "complete": True, "hasContinuation": False}
    if metadata.get("title") and metadata["title"] != name:
        result["metadataTitle"] = metadata["title"]
    print(name + ": " + str(len(videos)) + " verified playlist entries", flush=True)
    return result


def thumbnail_content(url):
    def allowed(candidate):
        parsed = urlsplit(candidate)
        host = parsed.hostname or ""
        return parsed.scheme == "https" and (host == "ytimg.com" or host.endswith(".ytimg.com"))
    if not allowed(url):
        raise RefreshError("Thumbnail is missing or is not a YouTube image")
    try:
        with urlopen(url, timeout=30) as response:
            if not allowed(response.url) or response.headers.get_content_type() != "image/jpeg":
                raise RefreshError("Thumbnail response is not a verified JPEG")
            content = response.read(MAX_IMAGE_BYTES + 1)
    except OSError as error:
        raise RefreshError("Could not download thumbnail") from error
    if not valid_jpeg(content):
        raise RefreshError("Invalid or oversized JPEG thumbnail")
    return content


def retrieve_thumbnail(url, destination):
    content = thumbnail_content(url)
    atomic_write(destination, content)


def valid_jpeg(content):
    return (len(content) <= MAX_IMAGE_BYTES and content.startswith(b"\xff\xd8\xff")
            and content.rstrip().endswith(b"\xff\xd9"))


def jpeg_dimensions(content):
    """Read a JPEG frame header without adding an imaging dependency."""
    if not valid_jpeg(content):
        return None
    offset = 2
    while offset + 3 < len(content):
        if content[offset] != 0xff:
            return None
        while offset < len(content) and content[offset] == 0xff:
            offset += 1
        if offset >= len(content):
            return None
        marker = content[offset]
        offset += 1
        if marker in (0xd9, 0xda):
            return None
        if marker == 0x01 or 0xd0 <= marker <= 0xd8:
            continue
        length = int.from_bytes(content[offset:offset + 2], "big")
        if length < 2 or offset + length > len(content):
            return None
        if marker in (0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7,
                      0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf):
            if length < 8:
                return None
            height = int.from_bytes(content[offset + 3:offset + 5], "big")
            width = int.from_bytes(content[offset + 5:offset + 7], "big")
            return (width, height) if width and height else None
        offset += length
    return None


def retrieve_video_thumbnail(video, destination):
    video_id = video.get("id", "")
    if not VIDEO_ID.fullmatch(video_id):
        raise RefreshError("Invalid video ID for thumbnail")
    existing = destination.read_bytes() if destination.is_file() else b""
    existing_size = jpeg_dimensions(existing)
    candidates = [(f"https://i.ytimg.com/vi/{video_id}/{name}.jpg", minimum)
                  for name, minimum in (("maxresdefault", (1280, 720)),
                                        ("sddefault", (640, 480)),
                                        ("hqdefault", (480, 360)))]
    candidates.append((video.get("thumbnail", ""), (1, 1)))
    for url, minimum in candidates:
        try:
            content = thumbnail_content(url)
        except RefreshError:
            continue
        size = jpeg_dimensions(content)
        # YouTube can return a tiny placeholder with HTTP 200 for missing sizes.
        if not size or max(size) < minimum[0] or min(size) < minimum[1]:
            continue
        if not existing_size or size[0] * size[1] > existing_size[0] * existing_size[1]:
            atomic_write(destination, content)
        elif size == existing_size:
            atomic_write(destination, content)
        return
    if not existing_size:
        raise RefreshError("No usable thumbnail available: " + destination.name)


def existing_thumbnail_valid(path):
    try:
        return path.is_file() and path.stat().st_size <= MAX_IMAGE_BYTES and bool(jpeg_dimensions(path.read_bytes()))
    except OSError:
        return False


def download_thumbnails(catalogue, asset_dir, refresh_all=False):
    videos = {video["id"]: video for artist in catalogue["artists"] for video in artist["videos"]}
    videos.update({video["id"]: video for video in catalogue["collection"]["videos"]})
    tasks = [(video, asset_dir / "videos" / (video_id + ".jpg")) for video_id, video in videos.items()]
    artist_fallbacks = [(artist["videos"][0]["thumbnail"], asset_dir / "artists" / (artist["id"] + ".jpg"))
                       for artist in catalogue["artists"] if artist["videos"]]
    required = tasks + artist_fallbacks
    tasks = [(video, destination) for video, destination in tasks
             if refresh_all or not existing_thumbnail_valid(destination)]
    # Artist portraits are curated separately; refreshing video thumbnails must
    # never replace them with a low-resolution frame from a music video.
    fallback_tasks = [(url, destination) for url, destination in artist_fallbacks
                      if not existing_thumbnail_valid(destination)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for _ in pool.map(lambda task: retrieve_video_thumbnail(*task), tasks):
            pass
        for _ in pool.map(lambda task: retrieve_thumbnail(*task), fallback_tasks):
            pass
    missing = [destination.name for _, destination in required if not existing_thumbnail_valid(destination)]
    if missing:
        raise RefreshError("Required thumbnails are unavailable; previous catalogue retained: " + ", ".join(missing))
    print("Refreshed " + str(len(tasks) + len(fallback_tasks)) + " JPEG thumbnails; all " + str(len(required)) + " required images verified.")


def run(options, cache_dir):
    with ThreadPoolExecutor(max_workers=4) as pool:
        artists = list(pool.map(lambda spec: extract_playlist(spec, cache_dir, options.refresh), ARTISTS))
    collection = extract_playlist(COLLECTION, cache_dir, options.refresh)
    lookup = {video["id"]: video for video in collection["videos"]}
    for artist in artists:
        for video in artist["videos"]:
            match = lookup.get(video["id"], {})
            if match.get("channelId") == CHANNEL_ID:
                inherited = False
                for field in ("duration", "channel", "channelId", "channelUrl"):
                    if not video.get(field) and match.get(field):
                        video[field] = match[field]
                        inherited = True
                if inherited:
                    video["metadataSourceUrl"] = collection["sourceUrl"]
    result = {"schemaVersion": 1, "channel": "Stephen Spielbot Music", "channelUrl": CHANNEL_URL,
              "channelId": CHANNEL_ID,
              "fetchedAt": min(item["sourceFetchedAt"] for item in artists + [collection]),
              "generatedAt": datetime.now(timezone.utc).isoformat(),
              "sourceMethod": "Public YouTube playlist HTML, ytInitialData playlist entries. Source order preserved.",
              "artists": artists, "collection": collection}
    download_thumbnails(result, options.output.parent, refresh_all=options.download_thumbnails)
    atomic_write(options.output, (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print("Catalogue saved to " + str(options.output))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--refresh", action="store_true", help="Ignore cached pages and retrieve current public playlists.")
    parser.add_argument("--output", type=Path, default=SITE_ROOT / "assets" / "catalogue.json")
    parser.add_argument("--cache-dir", type=Path, help="Optional reusable HTML cache outside the served music section.")
    parser.add_argument("--download-thumbnails", action="store_true", help="Refresh all thumbnails; missing or invalid required images are always downloaded.")
    options = parser.parse_args()
    options.output = options.output.expanduser().resolve()
    try:
        if options.cache_dir:
            cache_dir = options.cache_dir.expanduser().resolve()
            if cache_dir == SITE_ROOT or SITE_ROOT in cache_dir.parents:
                raise RefreshError("The raw HTML cache must be outside the served spielbotmusic directory.")
            cache_dir.mkdir(parents=True, exist_ok=True)
            run(options, cache_dir)
        else:
            with tempfile.TemporaryDirectory(prefix="spielbot-catalogue-") as temporary:
                run(options, Path(temporary))
    except (RefreshError, OSError, ValueError, TypeError, KeyError) as error:
        print("Refresh failed: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
