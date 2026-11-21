"""Regression checks for the public music site's thumbnail refresh."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "music_catalogue", Path(__file__).parents[1] / "spielbotmusic/_tools/refresh_catalogue.py")
catalogue = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(catalogue)


def jpeg(width, height):
    # A minimal frame header is sufficient for the dimension reader.
    return (b"\xff\xd8\xff\xc0\x00\x0b\x08" + height.to_bytes(2, "big")
            + width.to_bytes(2, "big") + b"\x01\x01\x11\x00\xff\xd9")


class MusicThumbnailTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.destination = self.root / "video.jpg"
        self.video = {"id": "BGMTWGPzt7M", "thumbnail": "https://i.ytimg.com/vi/BGMTWGPzt7M/source.jpg"}

    def test_upgrades_playlist_image_to_full_resolution(self):
        self.destination.write_bytes(jpeg(336, 188))
        with patch.object(catalogue, "thumbnail_content", return_value=jpeg(1280, 720)) as fetch:
            catalogue.retrieve_video_thumbnail(self.video, self.destination)
        self.assertEqual(catalogue.jpeg_dimensions(self.destination.read_bytes()), (1280, 720))
        self.assertIn("maxresdefault.jpg", fetch.call_args.args[0])
        self.assertEqual(fetch.call_count, 1)

    def test_missing_maximum_resolution_uses_standard_image(self):
        with patch.object(catalogue, "thumbnail_content", side_effect=[
                catalogue.RefreshError("404"), jpeg(640, 480)]):
            catalogue.retrieve_video_thumbnail(self.video, self.destination)
        self.assertEqual(catalogue.jpeg_dimensions(self.destination.read_bytes()), (640, 480))

    def test_placeholder_is_rejected_even_when_request_succeeds(self):
        with patch.object(catalogue, "thumbnail_content", side_effect=[jpeg(120, 90), jpeg(640, 480)]):
            catalogue.retrieve_video_thumbnail(self.video, self.destination)
        self.assertEqual(catalogue.jpeg_dimensions(self.destination.read_bytes()), (640, 480))

    def test_refresh_never_downgrades_existing_image(self):
        original = jpeg(1920, 1080)
        self.destination.write_bytes(original)
        with patch.object(catalogue, "thumbnail_content", return_value=jpeg(1280, 720)):
            catalogue.retrieve_video_thumbnail(self.video, self.destination)
        self.assertEqual(self.destination.read_bytes(), original)

    def test_failed_sources_preserve_existing_image_but_fail_if_absent(self):
        original = jpeg(1280, 720)
        self.destination.write_bytes(original)
        with patch.object(catalogue, "thumbnail_content", side_effect=catalogue.RefreshError("offline")):
            catalogue.retrieve_video_thumbnail(self.video, self.destination)
            self.assertEqual(self.destination.read_bytes(), original)
            self.destination.unlink()
            with self.assertRaises(catalogue.RefreshError):
                catalogue.retrieve_video_thumbnail(self.video, self.destination)

    def test_full_refresh_preserves_curated_artist_portrait(self):
        portrait = self.root / "artists/dayo.jpg"
        portrait.parent.mkdir()
        original = jpeg(1024, 1536)
        portrait.write_bytes(original)
        data = {"artists": [{"id": "dayo", "videos": [self.video]}], "collection": {"videos": []}}
        with patch.object(catalogue, "thumbnail_content", return_value=jpeg(1280, 720)):
            catalogue.download_thumbnails(data, self.root, refresh_all=True)
        self.assertEqual(portrait.read_bytes(), original)

    def test_malformed_images_are_rejected(self):
        for content in (b"not a jpeg", b"\xff\xd8\xff\xc0\xff\xff\xff\xd9", b"\xff\xd8\xff\xd9"):
            with self.subTest(content=content):
                self.assertIsNone(catalogue.jpeg_dimensions(content))


if __name__ == "__main__":
    unittest.main()
