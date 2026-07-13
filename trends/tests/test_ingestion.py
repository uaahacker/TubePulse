from __future__ import annotations

from typing import ClassVar

from django.test import TestCase, override_settings

from core.models import Trend, User
from trends.services.contracts import AbstractTrendSource, TrendCandidate, TrendGenerationRequest
from trends.services.dispatch import AITrendDispatcher
from trends.services.ingestion import TrendIngestionService
from trends.services.sources import SourceFetchError


class StaticSource(AbstractTrendSource):
    def __init__(self, source_name: str, candidates: list[TrendCandidate]) -> None:
        self.source_name = source_name
        self.candidates = candidates

    def fetch(self, niche: str, *, geo: str, limit: int) -> list[TrendCandidate]:
        return self.candidates[:limit]


class OfflineSource(AbstractTrendSource):
    source_name = "offline_source"

    def fetch(self, niche: str, *, geo: str, limit: int) -> list[TrendCandidate]:
        raise SourceFetchError("offline_source request failed: maintenance")


class RecordingPipeline:
    requests: ClassVar[list[TrendGenerationRequest]] = []

    def submit_trend(self, request: TrendGenerationRequest) -> str:
        self.requests.append(request)
        return f"job-{request.trend_id}"


class TrendIngestionTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username="trend-owner", password="safe-password-123")
        RecordingPipeline.requests.clear()

    @staticmethod
    def _candidates() -> tuple[TrendCandidate, TrendCandidate]:
        return (
            TrendCandidate(
                title="AI Agents Take Over",
                niche="AI tools",
                source="feed_one",
                source_url="https://one.example/topic",
                keywords=("agents", "automation"),
                score=62,
                raw_payload={"rank": 3},
            ),
            TrendCandidate(
                title="AI agents take over!",
                niche="AI Tools",
                source="feed_two",
                source_url="https://two.example/topic",
                keywords=("agents", "workflow"),
                score=86,
                raw_payload={"rank": 1},
            ),
        )

    def test_cross_source_candidates_are_merged_and_upserted(self) -> None:
        first, second = self._candidates()
        service = TrendIngestionService(
            sources=[
                StaticSource("feed_one", [first]),
                OfflineSource(),
                StaticSource("feed_two", [second]),
            ]
        )

        report = service.run(["AI tools"], user=self.user)

        self.assertEqual(report.fetched, 2)
        self.assertEqual(report.normalized, 1)
        self.assertEqual(report.created, 1)
        self.assertEqual(len(report.errors), 1)
        trend = Trend.objects.get()
        self.assertEqual(trend.user, self.user)
        self.assertEqual(trend.source, "feed_two")
        self.assertEqual(trend.score, 86)
        self.assertEqual(set(trend.keywords), {"agents", "workflow", "automation"})
        self.assertEqual(len(trend.raw_payload["provenance"]), 2)

        refreshed = service.run(["AI tools"], user=self.user)
        self.assertEqual(refreshed.created, 0)
        self.assertEqual(refreshed.updated, 1)
        self.assertEqual(Trend.objects.count(), 1)

    def test_fingerprint_keeps_user_workspaces_isolated(self) -> None:
        first, _ = self._candidates()
        other_user = User.objects.create_user(username="other-owner")
        service = TrendIngestionService(sources=[StaticSource("feed_one", [first])])

        service.run(["AI tools"], user=self.user)
        service.run(["AI tools"], user=other_user)

        self.assertEqual(Trend.objects.count(), 2)
        self.assertNotEqual(
            Trend.objects.get(user=self.user).fingerprint,
            Trend.objects.get(user=other_user).fingerprint,
        )

    def test_saved_trend_is_dispatched_through_abstract_boundary(self) -> None:
        first, _ = self._candidates()
        dispatcher = AITrendDispatcher(pipeline=RecordingPipeline())
        service = TrendIngestionService(
            sources=[StaticSource("feed_one", [first])],
            dispatcher=dispatcher,
        )

        report = service.run(["AI tools"], user=self.user, dispatch_ai=True)

        self.assertEqual(report.dispatched, 1)
        self.assertEqual(len(RecordingPipeline.requests), 1)
        request = RecordingPipeline.requests[0]
        self.assertEqual(request.user_id, self.user.pk)
        self.assertEqual(request.trend_id, Trend.objects.get().pk)

    def test_external_candidate_fields_are_bounded_and_url_scheme_is_safe(self) -> None:
        candidate = TrendCandidate(
            title="T" * 350,
            niche="N" * 120,
            source="S" * 100,
            source_url="javascript:alert(1)",
            keywords=("K" * 150,),
            score=75,
        )
        report = TrendIngestionService(
            sources=[StaticSource("feed_one", [candidate])]
        ).run(["valid niche"], user=self.user)

        self.assertEqual(report.created, 1)
        trend = Trend.objects.get()
        self.assertEqual(len(trend.title), 300)
        self.assertEqual(len(trend.niche), 100)
        self.assertEqual(len(trend.source), 80)
        self.assertEqual(len(trend.keywords[0]), 100)
        self.assertEqual(trend.source_url, "")

    @override_settings(TUBEPULSE_AI_PIPELINE_CLASS="")
    def test_missing_pipeline_is_reported_without_rolling_back_trend(self) -> None:
        first, _ = self._candidates()
        service = TrendIngestionService(sources=[StaticSource("feed_one", [first])])

        report = service.run(["AI tools"], user=self.user, dispatch_ai=True)

        self.assertEqual(report.created, 1)
        self.assertEqual(report.dispatched, 0)
        self.assertEqual(report.errors[0].stage, "dispatch")
        self.assertIn("TUBEPULSE_AI_PIPELINE_CLASS", report.errors[0].detail)
        self.assertEqual(Trend.objects.count(), 1)
