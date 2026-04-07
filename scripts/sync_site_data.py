#!/usr/bin/env python3
"""
sync_site_data.py — Run the generated-data pipeline in one place.

Full sync:
  python3 scripts/sync_site_data.py

Rebuild only derived outputs from local cached/generated data:
  python3 scripts/sync_site_data.py --skip-fetch
"""

import argparse
import os
import subprocess
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FETCH_TASKS = [
    ("stream", "scripts/fetch_stream.py"),
    ("photos", "scripts/fetch_photos.py"),
    ("videos", "scripts/fetch_videos.py"),
]

DERIVED_TASKS = [
    ("timeline", "scripts/build_timeline.py"),
]


def run_task(name, rel_path):
    path = os.path.join(REPO_ROOT, rel_path)
    print(f"\n==> {name}: {rel_path}")
    completed = subprocess.run([sys.executable, path], cwd=REPO_ROOT)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Sync generated site data and rebuild derived content."
    )
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="Skip remote fetches and rebuild only derived files from local cached data.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    tasks = []

    if not args.skip_fetch:
        tasks.extend(FETCH_TASKS)
    tasks.extend(DERIVED_TASKS)

    for name, rel_path in tasks:
        run_task(name, rel_path)

    print("\n✓ Site data sync complete")


if __name__ == "__main__":
    main()
