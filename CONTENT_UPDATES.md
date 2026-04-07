# Content Updates

This site now has a single content sync pipeline so the timeline, stream, personal page, and related generated data stay aligned.

## Source of truth

- Posts: add/edit files in `_posts/`
- Career, education, projects: edit `_data/career.yml`
- Publications: edit `publications/index.markdown`
- Manual social items: edit `_data/stream_manual.yml`
- Manual photos/media: edit `_data/photos_manual.yml`
- YouTube videos: fetched into `_data/videos.yml`

Do not manually edit these generated files unless you have a very specific reason:

- `_data/stream.json`
- `_data/photos.json`
- `_data/timeline.json`
- `_data/videos.yml` for normal YouTube refreshes

## Update locally

Fetch external sources and rebuild everything:

```bash
python3 scripts/sync_site_data.py
```

Rebuild only derived files from the current local data:

```bash
python3 scripts/sync_site_data.py --skip-fetch
```

## What gets rebuilt

- `scripts/fetch_stream.py` builds `_data/stream.json` from Medium, local posts, publications metadata, and manual social entries.
- `scripts/fetch_photos.py` builds `_data/photos.json` from Flickr and manual media entries.
- `scripts/fetch_videos.py` syncs YouTube metadata into `_data/videos.yml`.
- `scripts/build_timeline.py` builds `_data/timeline.json` from career, publications, photos, videos, and stream data.

## GitHub Actions

- `.github/workflows/sync_site_data.yml` runs on a schedule and can be triggered manually. It syncs generated data, validates a Jekyll build, and commits generated files if they changed.
- `.github/workflows/build_site.yml` runs on pushes and pull requests. It rebuilds derived data from local sources and checks that the site still builds.

## Typical update flow

1. Edit the source files you actually own, such as `_posts/`, `_data/career.yml`, `publications/index.markdown`, or the manual data YAML files.
2. Run `python3 scripts/sync_site_data.py --skip-fetch` if you only changed local source files.
3. Run `python3 scripts/sync_site_data.py` if you want fresh external data too.
4. Review the generated diffs, especially `_data/timeline.json`.
5. Commit the source changes and the regenerated data together.
