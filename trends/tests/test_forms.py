from django.test import SimpleTestCase

from trends.forms import TrendIngestionForm


class TrendIngestionFormTests(SimpleTestCase):
    def test_niches_are_split_normalized_and_deduplicated(self) -> None:
        form = TrendIngestionForm(
            {
                "niches": "AI tools, fitness\nAI TOOLS",
                "geo": "pk",
                "sources": ["google_trends"],
                "limit_per_source": 12,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["niches"], ["AI tools", "fitness"])
        self.assertEqual(form.cleaned_data["geo"], "PK")

    def test_invalid_geo_and_empty_sources_are_rejected(self) -> None:
        form = TrendIngestionForm(
            {
                "niches": "technology",
                "geo": "USA",
                "limit_per_source": 20,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("geo", form.errors)
        self.assertIn("sources", form.errors)

    def test_individual_niches_respect_the_database_limit(self) -> None:
        form = TrendIngestionForm(
            {
                "niches": "n" * 101,
                "geo": "US",
                "sources": ["google_trends"],
                "limit_per_source": 20,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("100 characters", str(form.errors["niches"]))
