from __future__ import annotations

import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import APIKeyStore, Trend, User, VideoProject

from ai_studio.credentials import DjangoAPIKeyRepository
from ai_studio.generation import GeneratedContentPackage
from ai_studio.services import render_video_project
from ai_studio.video.pipeline import RenderResult


class FakeRenderPipeline:
    def render(self, **kwargs):
        output_path = Path(kwargs["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"functional-mp4-result")
        return RenderResult(
            output_path=output_path,
            duration=4.0,
            width=1080,
            height=1920,
            fps=30,
            caption_count=2,
            attributions=(),
        )


class CredentialsAndViewsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="creator", password="safe-pass-123")

    def test_encrypted_django_key_repository(self):
        record = APIKeyStore(user=self.user, provider=APIKeyStore.Provider.OPENAI)
        record.set_secret("sk-private-value")
        record.save()

        value = DjangoAPIKeyRepository().get(self.user, "openai")

        self.assertEqual(value, "sk-private-value")
        self.assertNotIn("sk-private-value", record.encrypted_key)

    def test_create_project_requires_login(self):
        response = self.client.get(reverse("ai_studio:create_project"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    @patch("ai_studio.views.TrendGenerationPipeline.generate_from_trend")
    def test_create_project_generates_and_queues(self, generate_from_trend):
        generate_from_trend.return_value = GeneratedContentPackage(
            script="A generated script.",
            voiceover_prompt="Bright and quick.",
            provider="openai",
            model="gpt-5.6-sol",
        )
        trend = Trend.objects.create(
            user=self.user,
            niche="technology",
            title="A trend worth explaining",
            keywords=["tech"],
            source="test",
            fingerprint="a" * 64,
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("ai_studio:create_project"),
            {"trend_id": trend.pk, "provider": "openai"},
        )

        self.assertRedirects(response, reverse("dashboard:queue"))
        project = VideoProject.objects.get(user=self.user, trend=trend)
        self.assertEqual(project.status, VideoProject.Status.READY)
        self.assertEqual(project.script, "A generated script.")
        trend.refresh_from_db()
        self.assertEqual(trend.status, Trend.Status.QUEUED)

    def test_create_project_cannot_use_another_users_private_trend(self):
        other = User.objects.create_user(username="other", password="safe-pass-456")
        trend = Trend.objects.create(
            user=other,
            niche="private",
            title="Private trend",
            source="test",
            fingerprint="b" * 64,
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("ai_studio:create_project"), {"trend_id": trend.pk}
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(VideoProject.objects.filter(user=self.user).exists())

    def test_render_service_claims_and_persists_video(self):
        project = VideoProject.objects.create(
            user=self.user,
            title="Ready project",
            script="A complete narration ready to render.",
            status=VideoProject.Status.READY,
            progress=35,
        )
        with tempfile.TemporaryDirectory() as media_root, override_settings(
            MEDIA_ROOT=media_root
        ):
            result = render_video_project(
                project,
                pipeline=FakeRenderPipeline(),
                asset_sources=["https://images.example.test/portrait.jpg"],
            )
            project.refresh_from_db()
            self.assertEqual(project.status, VideoProject.Status.RENDERED)
            self.assertEqual(project.progress, 100)
            self.assertTrue(project.video_file.name.endswith(".mp4"))
            self.assertTrue(Path(project.video_file.path).is_file())
            self.assertEqual(Path(project.video_file.path).read_bytes(), b"functional-mp4-result")
            self.assertEqual(result.output_path, Path(project.video_file.path))

    def test_render_queue_endpoint_is_non_blocking(self):
        project = VideoProject.objects.create(
            user=self.user,
            title="Queue me",
            script="Narration",
            status=VideoProject.Status.FAILED,
            progress=0,
            error_message="old failure",
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("ai_studio:render_project", args=[project.public_id]),
            {"asset_url": "https://cdn.example.test/clip.mp4"},
        )

        self.assertRedirects(response, reverse("dashboard:queue"))
        project.refresh_from_db()
        self.assertEqual(project.status, VideoProject.Status.QUEUED)
        self.assertEqual(project.progress, 40)
        self.assertEqual(project.source_assets, ["https://cdn.example.test/clip.mp4"])

    def test_render_queue_endpoint_persists_validated_audio(self):
        project = VideoProject.objects.create(
            user=self.user,
            title="Narrated project",
            script="Narration",
            status=VideoProject.Status.READY,
        )
        self.client.force_login(self.user)
        upload = SimpleUploadedFile(
            "voiceover.mp3", b"small-audio-payload", content_type="audio/mpeg"
        )
        with tempfile.TemporaryDirectory() as media_root, override_settings(
            MEDIA_ROOT=media_root
        ):
            response = self.client.post(
                reverse("ai_studio:render_project", args=[project.public_id]),
                {"audio": upload},
            )
            self.assertRedirects(response, reverse("dashboard:queue"))
            project.refresh_from_db()
            self.assertEqual(project.status, VideoProject.Status.QUEUED)
            self.assertTrue(project.audio_file.name.endswith(".mp3"))
            self.assertEqual(
                Path(project.audio_file.path).read_bytes(), b"small-audio-payload"
            )

    def test_render_queue_rejects_aggregate_upload_over_budget(self):
        project = VideoProject.objects.create(
            user=self.user,
            title="Bounded uploads",
            script="Narration",
            status=VideoProject.Status.READY,
        )
        self.client.force_login(self.user)
        uploads = [
            SimpleUploadedFile(
                f"asset-{index}.jpg",
                b"x" * (600 * 1024),
                content_type="image/jpeg",
            )
            for index in range(2)
        ]
        with tempfile.TemporaryDirectory() as media_root, override_settings(
            MEDIA_ROOT=media_root, TUBEPULSE_MAX_DOWNLOAD_MB=1
        ):
            response = self.client.post(
                reverse("ai_studio:render_project", args=[project.public_id]),
                {"assets": uploads},
            )
            self.assertRedirects(response, reverse("dashboard:queue"))
            project.refresh_from_db()
            self.assertEqual(project.status, VideoProject.Status.READY)
            self.assertEqual(project.source_assets, [])
            self.assertFalse(any(Path(media_root).rglob("*.*")))

    @patch("ai_studio.management.commands.process_video_queue.render_video_project")
    def test_worker_command_consumes_queued_not_merely_ready(self, render_project):
        ready = VideoProject.objects.create(
            user=self.user,
            title="Needs user confirmation",
            script="Ready script",
            status=VideoProject.Status.READY,
        )
        queued = VideoProject.objects.create(
            user=self.user,
            title="Explicitly queued",
            script="Queued script",
            status=VideoProject.Status.QUEUED,
        )
        render_project.return_value = RenderResult(
            output_path=Path("rendered.mp4"),
            duration=4,
            width=1080,
            height=1920,
            fps=30,
            caption_count=1,
            attributions=(),
        )

        call_command(
            "process_video_queue",
            batch_size=5,
            interval=1,
            stale_minutes=90,
            stdout=StringIO(),
            stderr=StringIO(),
        )

        render_project.assert_called_once()
        rendered_argument = render_project.call_args.args[0]
        self.assertEqual(rendered_argument.pk, queued.pk)
        self.assertNotEqual(rendered_argument.pk, ready.pk)

    @patch("ai_studio.management.commands.process_video_queue.render_video_project")
    def test_worker_recovers_stale_rendering_lease(self, render_project):
        stale = VideoProject.objects.create(
            user=self.user,
            title="Interrupted render",
            script="Recoverable script",
            status=VideoProject.Status.RENDERING,
            progress=45,
        )
        VideoProject.objects.filter(pk=stale.pk).update(
            updated_at=timezone.now() - timedelta(minutes=120)
        )
        render_project.return_value = RenderResult(
            output_path=Path("rendered.mp4"),
            duration=4,
            width=1080,
            height=1920,
            fps=30,
            caption_count=1,
            attributions=(),
        )

        call_command(
            "process_video_queue",
            batch_size=5,
            interval=1,
            stale_minutes=90,
            stdout=StringIO(),
            stderr=StringIO(),
        )

        stale.refresh_from_db()
        self.assertEqual(stale.status, VideoProject.Status.QUEUED)
        self.assertIn("Recovered after an interrupted render", stale.error_message)
        render_project.assert_called_once()
