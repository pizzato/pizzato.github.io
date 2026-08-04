#!/usr/bin/env python3
"""Tests for Semantic Scholar rate-limit handling in scripts/fetch_stream.py.

The free Semantic Scholar API 429s routinely; these tests simulate that and
check that (a) requests retry with backoff and (b) a run that stays
rate-limited preserves the scholar data already in _data/stream.json instead
of committing degraded output.

Run: python3 tests/test_fetch_stream.py -v
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

import requests

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"),
)

import fetch_stream


def _resp(status=200, payload=None, headers=None):
    r = mock.Mock(name=f"response-{status}")
    r.status_code = status
    r.headers = headers or {}
    r.json.return_value = {} if payload is None else payload
    if status >= 400:
        r.raise_for_status.side_effect = requests.exceptions.HTTPError(f"{status} error")
    else:
        r.raise_for_status.return_value = None
    return r


def _pub(title, date="2025-01-01", url="https://doi.org/10.1000/example"):
    """A publications-page item as fetch_publications() produces it."""
    return {
        "type": "scholar",
        "title": title,
        "url": url,
        "date": date,
        "source": "Scholar",
        "venue": "Some Venue",
    }


class ScholarGetRetryTest(unittest.TestCase):
    """_scholar_get: retry-with-backoff on 429."""

    def test_retries_on_429_then_succeeds(self):
        ok = _resp(200, payload={"data": []})
        get = mock.Mock(side_effect=[_resp(429), _resp(429), ok])
        with mock.patch.object(fetch_stream.requests, "get", get), \
                mock.patch.object(fetch_stream.time, "sleep") as sleep:
            result = fetch_stream._scholar_get("https://x", {}, timeout=5)
        self.assertIs(result, ok)
        self.assertEqual(get.call_count, 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [5, 10])

    def test_gives_up_after_max_attempts(self):
        get = mock.Mock(side_effect=lambda *a, **k: _resp(429))
        with mock.patch.object(fetch_stream.requests, "get", get), \
                mock.patch.object(fetch_stream.time, "sleep") as sleep:
            with self.assertRaises(requests.exceptions.HTTPError):
                fetch_stream._scholar_get("https://x", {}, timeout=5)
        self.assertEqual(get.call_count, fetch_stream.SCHOLAR_MAX_ATTEMPTS)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [5, 10, 20, 40])

    def test_respects_retry_after_header(self):
        get = mock.Mock(side_effect=[
            _resp(429, headers={"Retry-After": "7"}),
            _resp(200, payload={"data": []}),
        ])
        with mock.patch.object(fetch_stream.requests, "get", get), \
                mock.patch.object(fetch_stream.time, "sleep") as sleep:
            fetch_stream._scholar_get("https://x", {}, timeout=5)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [7])

    def test_non_429_errors_are_not_retried(self):
        get = mock.Mock(return_value=_resp(500))
        with mock.patch.object(fetch_stream.requests, "get", get), \
                mock.patch.object(fetch_stream.time, "sleep") as sleep:
            with self.assertRaises(requests.exceptions.HTTPError):
                fetch_stream._scholar_get("https://x", {}, timeout=5)
        self.assertEqual(get.call_count, 1)
        sleep.assert_not_called()


class RateLimitedFallbackTest(unittest.TestCase):
    """fetch_scholar: a fully rate-limited run must not degrade stream data."""

    def _run_rate_limited(self, previous_stream, pub_items):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "stream.json")
            if previous_stream is not None:
                with open(out, "w") as f:
                    json.dump(previous_stream, f)
            get = mock.Mock(side_effect=lambda *a, **k: _resp(429))
            with mock.patch.object(fetch_stream.requests, "get", get), \
                    mock.patch.object(fetch_stream.time, "sleep"), \
                    mock.patch.object(fetch_stream, "OUTPUT_JSON", out):
                result = fetch_stream.fetch_scholar(pub_items)
        return result, get

    def test_preserves_enriched_dates_and_scholar_only_papers(self):
        previous = [
            {"type": "medium", "title": "A Medium post",
             "url": "https://medium.com/p/1", "date": "2026-01-01",
             "source": "Medium", "image": ""},
            # Publications-page paper whose date a past run enriched
            {"type": "scholar", "title": "ConCISE: A Reference-Free Metric",
             "url": "https://arxiv.org/pdf/2511.16846", "date": "2025-11-20",
             "source": "Scholar", "venue": "arXiv"},
            # Scholar-only paper, absent from the publications page
            {"type": "scholar",
             "title": "Prompt Segmentation and Annotation Optimisation",
             "url": "https://doi.org/10.48550/arXiv.2605.14561",
             "date": "2026-05-14", "source": "Scholar", "venue": ""},
        ]
        pub_items = [_pub("ConCISE: A Reference-Free Metric",
                          url="https://arxiv.org/pdf/2511.16846")]

        result, get = self._run_rate_limited(previous, pub_items)

        # Author search retried to exhaustion, then no further API calls
        self.assertEqual(get.call_count, fetch_stream.SCHOLAR_MAX_ATTEMPTS)

        self.assertEqual(len(result), 2)
        concise = next(i for i in result if i["title"].startswith("ConCISE"))
        self.assertEqual(concise["date"], "2025-11-20")  # not reset to -01-01
        prompt_seg = next(i for i in result if i["title"].startswith("Prompt"))
        self.assertEqual(prompt_seg["date"], "2026-05-14")  # not dropped
        self.assertFalse(any(i["type"] == "medium" for i in result))

    def test_without_previous_stream_returns_pub_items_unchanged(self):
        pub_items = [_pub("Some Paper")]
        result, _ = self._run_rate_limited(None, pub_items)
        self.assertEqual(result, [_pub("Some Paper")])


class ScholarSuccessPathTest(unittest.TestCase):
    """fetch_scholar: normal behaviour is unchanged when the API responds."""

    def test_enriches_dates_and_adds_new_papers(self):
        search_payload = {"data": [{
            "authorId": "123", "name": "Luiz Pizzato",
            "affiliations": [{"name": "Commonwealth Bank"}], "paperCount": 30,
        }]}
        papers_payload = {"data": [
            {"title": "Known Paper", "year": 2025,
             "publicationDate": "2025-08-01",
             "externalIds": {"DOI": "10.1109/known"}, "venue": "BigData"},
            {"title": "Brand New Paper", "year": 2026,
             "publicationDate": "2026-05-14",
             "externalIds": {"DOI": "10.48550/arXiv.2605.14561"}, "venue": ""},
        ]}

        def fake_get(url, params=None, timeout=None):
            payload = search_payload if "author/search" in url else papers_payload
            return _resp(200, payload=payload)

        pub_items = [_pub("Known Paper")]
        with mock.patch.object(fetch_stream.requests, "get", side_effect=fake_get) as get, \
                mock.patch.object(fetch_stream.time, "sleep") as sleep:
            result = fetch_stream.fetch_scholar(pub_items)

        self.assertEqual(get.call_count, 2)
        sleep.assert_not_called()
        self.assertEqual(len(result), 2)
        known = next(i for i in result if i["title"] == "Known Paper")
        self.assertEqual(known["date"], "2025-08-01")
        self.assertEqual(known["url"], "https://doi.org/10.1000/example")
        new = next(i for i in result if i["title"] == "Brand New Paper")
        self.assertEqual(new["date"], "2026-05-14")
        self.assertEqual(new["url"], "https://doi.org/10.48550/arXiv.2605.14561")


if __name__ == "__main__":
    unittest.main()
