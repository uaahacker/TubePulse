from __future__ import annotations

from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

import requests
from django.test import SimpleTestCase

from trends.services.sources import (
    GoogleTrendsRSSSource,
    SourceFetchError,
    YouTubePublicRSSSource,
)


def _session_with_xml(xml: str) -> Mock:
    session = Mock(spec=requests.Session)
    session.headers = {}
    response = Mock()
    response.content = xml.encode("utf-8")
    response.raise_for_status.return_value = None
    session.get.return_value = response
    return session


class PublicRSSSourceTests(SimpleTestCase):
    def test_google_trends_parses_and_filters_by_niche(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0" xmlns:ht="https://trends.google.com/trending/rss">
          <channel>
            <title>Daily Search Trends</title>
            <item>
              <title>Artificial intelligence agents</title>
              <link>https://example.test/ai-agents</link>
              <pubDate>Mon, 13 Jul 2026 08:00:00 GMT</pubDate>
              <ht:approx_traffic>200K+</ht:approx_traffic>
              <description><![CDATA[New AI agent demos are drawing attention.]]></description>
            </item>
            <item>
              <title>Premier league final</title>
              <link>https://example.test/sports</link>
              <ht:approx_traffic>1M+</ht:approx_traffic>
            </item>
          </channel>
        </rss>"""
        session = _session_with_xml(xml)

        results = GoogleTrendsRSSSource(session=session).fetch(
            "Artificial intelligence", geo="PK", limit=10
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source, "google_trends")
        self.assertEqual(results[0].raw_payload["approx_traffic"], 200_000)
        self.assertEqual(results[0].raw_payload["geo"], "PK")
        self.assertGreater(results[0].score, 50)

    def test_youtube_public_feed_uses_niche_query_and_normalizes(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><item>
          <title>Five personal finance Shorts creators to watch</title>
          <link>https://news.example.test/story</link>
          <pubDate>Mon, 13 Jul 2026 08:00:00 GMT</pubDate>
          <description><![CDATA[Short-form explainers are trending.]]></description>
          <source url="https://news.example.test">Example News</source>
        </item></channel></rss>"""
        session = _session_with_xml(xml)

        results = YouTubePublicRSSSource(session=session).fetch(
            "personal finance", geo="US", limit=5
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].niche, "personal finance")
        self.assertEqual(results[0].source, "youtube_public_rss")
        requested_url = session.get.call_args.args[0]
        query = parse_qs(urlparse(requested_url).query)
        self.assertIn("personal finance", query["q"][0])
        self.assertEqual(query["gl"], ["US"])

    def test_network_error_is_wrapped_without_leaking_a_traceback(self) -> None:
        session = Mock(spec=requests.Session)
        session.headers = {}
        session.get.side_effect = requests.Timeout("upstream timed out")

        with self.assertRaisesRegex(SourceFetchError, "request failed"):
            GoogleTrendsRSSSource(session=session).fetch("technology", geo="US", limit=5)
