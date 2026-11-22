"""Offline checks for complete, bounded public YouTube playlist pagination."""

import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "music_catalogue_pagination", Path(__file__).parents[1] / "spielbotmusic/_tools/refresh_catalogue.py")
catalogue = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(catalogue)
PLAYLIST = ("pagination-test", "Pagination test", "PL_pagination_test")


def video(video_id, index):
    return {"playlistVideoRenderer": {
        "videoId": video_id,
        "title": {"simpleText": "Song " + video_id},
        "index": {"simpleText": str(index)},
        "navigationEndpoint": {"watchEndpoint": {"playlistId": PLAYLIST[2]}},
    }}


def continuation(token, api_url="/youtubei/v1/browse"):
    return {"continuationItemRenderer": {"continuationEndpoint": {
        "commandMetadata": {"webCommandMetadata": {"apiUrl": api_url}},
        "continuationCommand": {"token": token},
    }}}


def modern_continuation(token):
    return {"continuationItemViewModel": {"continuationCommand": {"innertubeCommand": {
        "continuationCommand": {"token": token, "request": "CONTINUATION_REQUEST_TYPE_BROWSE"},
    }}}}


def response(items, action_key="onResponseReceivedActions"):
    return io.BytesIO(json.dumps({action_key: [{
        "appendContinuationItemsAction": {"continuationItems": items},
    }]}).encode("utf-8"))


class MusicPaginationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.cache = Path(directory.name)

    def write_initial(self, count, items, context=True):
        data = {
            "header": {"playlistHeaderRenderer": {"numVideosText": {"simpleText": str(count)}}},
            "contents": {"playlistVideoListRenderer": {"contents": items}},
        }
        config = {"INNERTUBE_API_KEY": "must-not-be-sent", "INNERTUBE_CONTEXT": {"client": {
            "clientName": "WEB", "clientVersion": "2.test", "hl": "en",
            "visitorData": "anonymous-visitor", "remoteHost": "must-not-be-sent",
        }}}
        html = "<script>var ytInitialData = " + json.dumps(data) + ";</script>"
        if context:
            html += "<script>ytcfg.set(" + json.dumps(config) + ");</script>"
        (self.cache / (PLAYLIST[0] + ".html")).write_text(html, encoding="utf-8")

    def extract(self):
        return catalogue.extract_playlist(PLAYLIST, self.cache, False)

    def test_follows_all_pages_and_preserves_order_and_repeated_videos(self):
        self.write_initial(3, [video("aaaaaaaaaaa", 1), modern_continuation("page-2")])
        pages = [
            response([video("bbbbbbbbbbb", 2), modern_continuation("page-3")]),
            response([video("aaaaaaaaaaa", 3)], "onResponseReceivedEndpoints"),
        ]
        with patch.object(catalogue, "urlopen", side_effect=pages) as fetch:
            result = self.extract()
        self.assertEqual([item["id"] for item in result["videos"]], ["aaaaaaaaaaa", "bbbbbbbbbbb", "aaaaaaaaaaa"])
        self.assertEqual([item["playlistIndex"] for item in result["videos"]], [1, 2, 3])
        self.assertEqual(result["verifiedCount"], 3)
        self.assertEqual(result["uniqueVideoCount"], 2)
        self.assertTrue(result["complete"])
        self.assertFalse(result["hasContinuation"])
        payloads = [json.loads(call.args[0].data) for call in fetch.call_args_list]
        self.assertEqual([payload["continuation"] for payload in payloads], ["page-2", "page-3"])
        self.assertEqual(payloads[0]["context"]["client"]["clientVersion"], "2.test")
        for call in fetch.call_args_list:
            request = call.args[0]
            self.assertEqual(request.full_url, "https://www.youtube.com/youtubei/v1/browse")
            self.assertEqual(request.get_method(), "POST")
            self.assertNotIn(b"must-not-be-sent", request.data)
        with patch.object(catalogue, "urlopen") as fetch:
            self.assertEqual(self.extract()["videos"], result["videos"])
        fetch.assert_not_called()

    def test_repeated_continuation_token_is_rejected(self):
        self.write_initial(3, [video("aaaaaaaaaaa", 1), continuation("same-token")])
        with patch.object(catalogue, "urlopen", return_value=response([
                video("bbbbbbbbbbb", 2), continuation("same-token")])):
            with self.assertRaisesRegex(catalogue.RefreshError, "Incomplete playlist.*repeated"):
                self.extract()

    def test_empty_page_with_continuation_is_rejected(self):
        self.write_initial(3, [video("aaaaaaaaaaa", 1), continuation("page-2")])
        with patch.object(catalogue, "urlopen", return_value=response([continuation("page-3")])):
            with self.assertRaisesRegex(catalogue.RefreshError, "Incomplete playlist.*does not advance"):
                self.extract()

    def test_last_page_must_match_reported_total(self):
        self.write_initial(3, [video("aaaaaaaaaaa", 1), continuation("page-2")])
        with patch.object(catalogue, "urlopen", return_value=response([video("bbbbbbbbbbb", 2)])):
            with self.assertRaisesRegex(catalogue.RefreshError, "Incomplete playlist.*read 2 of 3"):
                self.extract()

    def test_overfull_page_is_rejected(self):
        self.write_initial(2, [video("aaaaaaaaaaa", 1), continuation("page-2")])
        with patch.object(catalogue, "urlopen", return_value=response([
                video("bbbbbbbbbbb", 2), video("ccccccccccc", 3)])):
            with self.assertRaisesRegex(catalogue.RefreshError, "Incomplete playlist.*exceed"):
                self.extract()

    def test_page_limit_stops_before_another_network_request(self):
        self.write_initial(3, [video("aaaaaaaaaaa", 1), continuation("page-2")])
        with patch.object(catalogue, "MAX_PLAYLIST_PAGES", 2), \
                patch.object(catalogue, "urlopen", return_value=response([
                    video("bbbbbbbbbbb", 2), continuation("page-3")])) as fetch:
            with self.assertRaisesRegex(catalogue.RefreshError, "Incomplete playlist.*page limit"):
                self.extract()
        self.assertEqual(fetch.call_count, 1)

    def test_reported_entry_limit_rejects_without_network_request(self):
        self.write_initial(3, [video("aaaaaaaaaaa", 1), continuation("page-2")])
        with patch.object(catalogue, "MAX_PLAYLIST_ENTRIES", 2), \
                patch.object(catalogue, "urlopen") as fetch:
            with self.assertRaisesRegex(catalogue.RefreshError, "Incomplete playlist.*entry limit"):
                self.extract()
        fetch.assert_not_called()

    def test_missing_public_context_is_rejected(self):
        self.write_initial(2, [video("aaaaaaaaaaa", 1), continuation("page-2")], context=False)
        with patch.object(catalogue, "urlopen") as fetch:
            with self.assertRaisesRegex(catalogue.RefreshError, "Incomplete playlist.*context is unavailable"):
                self.extract()
        fetch.assert_not_called()

    def test_arbitrary_continuation_endpoint_is_rejected(self):
        self.write_initial(2, [video("aaaaaaaaaaa", 1), continuation("page-2", "https://example.com/")])
        with patch.object(catalogue, "urlopen") as fetch:
            with self.assertRaisesRegex(catalogue.RefreshError, "Incomplete playlist.*Invalid public playlist continuation"):
                self.extract()
        fetch.assert_not_called()

    def test_invalid_and_oversized_responses_are_rejected(self):
        self.write_initial(2, [video("aaaaaaaaaaa", 1), continuation("page-2")])
        for content, maximum in [(b'{"unexpected": true}', 1024), (b'[]', 1024), (b'not json', 1024), (b'x' * 33, 32)]:
            with self.subTest(content=content), \
                    patch.object(catalogue, "MAX_PAGE_BYTES", maximum), \
                    patch.object(catalogue, "urlopen", return_value=io.BytesIO(content)):
                with self.assertRaisesRegex(catalogue.RefreshError, "Incomplete playlist"):
                    self.extract()
            for cached in self.cache.glob("*.json"):
                cached.unlink()


if __name__ == "__main__":
    unittest.main()
