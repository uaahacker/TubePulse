from django.test import SimpleTestCase

from trends.services.normalization import (
    build_fingerprint,
    canonical_title,
    extract_keywords,
    parse_traffic,
    plain_text,
)


class NormalizationTests(SimpleTestCase):
    def test_text_and_keywords_are_stable(self) -> None:
        self.assertEqual(plain_text("<b>  AI&nbsp;agents </b>"), "AI agents")
        self.assertEqual(canonical_title("AI—Agents!!!"), "ai agents")
        self.assertEqual(extract_keywords("Viral AI agents with Python"), ("ai", "agents", "python"))

    def test_traffic_parser_supports_feed_suffixes(self) -> None:
        self.assertEqual(parse_traffic("200K+"), 200_000)
        self.assertEqual(parse_traffic("1.5M+"), 1_500_000)
        self.assertEqual(parse_traffic("unknown"), 0)

    def test_fingerprint_deduplicates_sources_but_is_tenant_aware(self) -> None:
        first = build_fingerprint(niche="AI Tools", title="Agent Workflows!", user_id=4)
        second = build_fingerprint(niche="ai tools", title="Agent   workflows", user_id=4)
        other_user = build_fingerprint(niche="AI Tools", title="Agent workflows", user_id=5)
        self.assertEqual(first, second)
        self.assertNotEqual(first, other_user)
