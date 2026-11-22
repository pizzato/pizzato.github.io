"""Regression checks for unattended music catalogue refreshes.

Run: python3 tests/test_music_catalogue.py
"""

import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "music_catalogue", Path(__file__).parents[1] / "spielbotmusic/_tools/refresh_catalogue.py")
catalogue = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(catalogue)

ARTIST = ("test-artist", "Test Artist", "PL_test_artist")
COLLECTION = ("test-collection", "Test Collection", "PL_test_collection")
UPLOADS = ("channel-uploads", "Channel uploads", "UU_test_uploads")
FIRST = ("aaaaaaaaaaa", "First song")
SECOND = ("bbbbbbbbbbb", "Second song")
THIRD = ("ccccccccccc", "New song")


def playlist_page(spec, songs, reported_count=None, continuation=False):
    """Small public playlist fixture with order and channel evidence."""
    entries = []
    for index, (video_id, title) in enumerate(songs, 1):
        entries.append({"playlistVideoRenderer": {
            "videoId": video_id,
            "title": {"simpleText": title},
            "index": {"simpleText": str(index)},
            "lengthText": {"simpleText": "2:10"},
            "navigationEndpoint": {"watchEndpoint": {"playlistId": spec[2]}},
            "shortBylineText": {"runs": [{
                "text": "Stephen Spielbot Music",
                "navigationEndpoint": {"browseEndpoint": {
                    "browseId": catalogue.CHANNEL_ID,
                    "canonicalBaseUrl": "/@SpielbotMusic",
                }},
            }]},
            "thumbnail": {"thumbnails": [{
                "url": "https://i.ytimg.com/vi/" + video_id + "/hqdefault.jpg",
                "width": 480, "height": 360,
            }]},
        }})
    if continuation:
        entries.append({"continuationItemRenderer": {"continuationEndpoint": {}}})
    count = len(songs) if reported_count is None else reported_count
    return {
        "metadata": {"playlistMetadataRenderer": {"title": spec[1]}},
        "sidebar": {"playlistSidebarPrimaryInfoRenderer": {
            "stats": [{"simpleText": str(count) + " videos"}],
        }},
        "contents": {"playlistVideoListRenderer": {"contents": entries}},
    }


class MusicCatalogueTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.cache = self.root / "sources"
        self.cache.mkdir()
        self.output = self.root / "assets/catalogue.json"
        self.output.parent.mkdir()
        self.options = SimpleNamespace(
            output=self.output, refresh=False, download_thumbnails=False)
        self.addCleanup(patch.stopall)
        patch.object(catalogue, "ARTISTS", [ARTIST]).start()
        patch.object(catalogue, "COLLECTION", COLLECTION).start()
        patch.object(catalogue, "UPLOADS", UPLOADS).start()

    def write_page(self, spec, songs, **kwargs):
        page = playlist_page(spec, songs, **kwargs)
        (self.cache / (spec[0] + ".html")).write_text(
            "<script>var ytInitialData = " + json.dumps(page) + ";</script>",
            encoding="utf-8")

    def write_sources(self, songs):
        self.write_page(ARTIST, songs)
        self.write_page(COLLECTION, songs)
        self.write_page(UPLOADS, songs)

    def seed_catalogue(self):
        original = b'{"previous": "known-good catalogue"}\n'
        self.output.write_bytes(original)
        return original

    def test_refresh_propagates_additions_titles_removals_and_source_order(self):
        self.write_sources([FIRST, SECOND])
        with patch.object(catalogue, "download_thumbnails"):
            catalogue.run(self.options, self.cache)
            updated_songs = [THIRD, (FIRST[0], "First song, revised title")]
            self.write_sources(updated_songs)
            catalogue.run(self.options, self.cache)

        result = json.loads(self.output.read_text(encoding="utf-8"))
        for source in [result["artists"][0], result["collection"], result["uploads"]]:
            with self.subTest(source=source["id"]):
                self.assertEqual(
                    [(video["id"], video["title"]) for video in source["videos"]],
                    updated_songs)
                self.assertEqual([video["playlistIndex"] for video in source["videos"]], [1, 2])
                self.assertEqual(source["reportedVideoCount"], 2)
                self.assertEqual(source["verifiedCount"], 2)
                self.assertTrue(source["complete"])

    def test_upload_outside_all_curated_playlists_is_included(self):
        self.write_sources([FIRST])
        self.write_page(UPLOADS, [THIRD, FIRST])
        with patch.object(catalogue, "download_thumbnails") as thumbnails:
            catalogue.run(self.options, self.cache)
        result = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual([v["id"] for v in result["uploads"]["videos"]], [THIRD[0], FIRST[0]])
        self.assertEqual([v["id"] for v in result["artists"][0]["videos"]], [FIRST[0]])
        self.assertEqual(thumbnails.call_args.args[0]["uploads"]["videos"], result["uploads"]["videos"])

    def test_incomplete_uploads_preserve_previous_catalogue(self):
        self.write_sources([FIRST])
        self.write_page(UPLOADS, [FIRST], reported_count=2)
        original = self.seed_catalogue()
        with patch.object(catalogue, "download_thumbnails") as thumbnails:
            with self.assertRaisesRegex(catalogue.RefreshError, "Incomplete playlist.*Channel uploads"):
                catalogue.run(self.options, self.cache)
        thumbnails.assert_not_called()
        self.assertEqual(self.output.read_bytes(), original)

    def test_unverified_upload_owner_preserves_previous_catalogue(self):
        self.write_sources([FIRST])
        path = self.cache / (UPLOADS[0] + ".html")
        path.write_text(path.read_text().replace(catalogue.CHANNEL_ID, "UC_wrong_channel"))
        original = self.seed_catalogue()
        with self.assertRaisesRegex(catalogue.RefreshError, "unverified ownership"):
            catalogue.run(self.options, self.cache)
        self.assertEqual(self.output.read_bytes(), original)

    def test_album_named_playlist_is_not_fetched(self):
        self.write_sources([FIRST])
        album = ("album", "Album: VÆZURI - Petals in the Crossfire", "PL_album")
        with patch.object(catalogue, "ARTISTS", [ARTIST, album]), \
                patch.object(catalogue, "download_thumbnails"), \
                patch.object(catalogue, "extract_playlist", wraps=catalogue.extract_playlist) as fetch:
            catalogue.run(self.options, self.cache)
        result = json.loads(self.output.read_text())
        self.assertEqual([artist["id"] for artist in result["artists"]], [ARTIST[0]])
        self.assertNotIn(album, [call.args[0] for call in fetch.call_args_list])
        self.assertNotIn("albums", result)

    def test_playlist_renamed_to_album_is_excluded(self):
        self.write_sources([FIRST])
        # Even a partial album source must be ignored before count validation.
        self.write_page(ARTIST, [FIRST], reported_count=20, continuation=True)
        path = self.cache / (ARTIST[0] + ".html")
        path.write_text(path.read_text().replace(ARTIST[1], "  ALBUM: Test release"))
        with patch.object(catalogue, "download_thumbnails"):
            catalogue.run(self.options, self.cache)
        result = json.loads(self.output.read_text())
        self.assertEqual(result["artists"], [])
        # Public uploads remain independent of how the user groups their albums.
        self.assertEqual(result["uploads"]["videos"][0]["id"], FIRST[0])

    def test_incomplete_playlist_is_rejected_and_previous_catalogue_retained(self):
        self.write_sources([FIRST])
        self.write_page(ARTIST, [FIRST], reported_count=2)
        original = self.seed_catalogue()
        with patch.object(catalogue, "download_thumbnails") as thumbnails:
            with self.assertRaisesRegex(catalogue.RefreshError, "Incomplete playlist.*read 1 of 2"):
                catalogue.run(self.options, self.cache)
        thumbnails.assert_not_called()
        self.assertEqual(self.output.read_bytes(), original)

    def test_pagination_is_rejected_even_if_visible_count_matches(self):
        self.write_sources([FIRST])
        self.write_page(ARTIST, [FIRST], continuation=True)
        original = self.seed_catalogue()
        with self.assertRaisesRegex(catalogue.RefreshError, "Incomplete playlist"):
            catalogue.run(self.options, self.cache)
        self.assertEqual(self.output.read_bytes(), original)

    def test_fetch_failure_preserves_previous_catalogue(self):
        self.options.refresh = True
        original = self.seed_catalogue()
        with patch.object(catalogue, "urlopen", side_effect=OSError("connection failed")):
            with self.assertRaisesRegex(catalogue.RefreshError, "Cannot retrieve public playlist"):
                catalogue.run(self.options, self.cache)
        self.assertEqual(self.output.read_bytes(), original)

    def test_invalid_source_json_preserves_previous_catalogue(self):
        self.write_sources([FIRST])
        (self.cache / (ARTIST[0] + ".html")).write_text(
            "<script>var ytInitialData = {broken;</script>", encoding="utf-8")
        original = self.seed_catalogue()
        with self.assertRaisesRegex(catalogue.RefreshError, "could not be parsed"):
            catalogue.run(self.options, self.cache)
        self.assertEqual(self.output.read_bytes(), original)

    def test_missing_required_thumbnail_preserves_previous_catalogue(self):
        self.write_sources([FIRST])
        original = self.seed_catalogue()
        with patch.object(catalogue, "thumbnail_content", side_effect=catalogue.RefreshError("offline")):
            with self.assertRaisesRegex(catalogue.RefreshError, "No usable thumbnail available"):
                catalogue.run(self.options, self.cache)
        self.assertEqual(self.output.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
