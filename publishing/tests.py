import tempfile
import time
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import VideoProject

from .models import PublishingChannel, ScheduledPublication
from .services import (
    OAUTH_SESSION_KEY,
    OAuthStateError,
    PublishingError,
    _validate_oauth_state,
    publish_scheduled_publication,
)


class PublishingOwnershipTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.owner = user_model.objects.create_user(username="owner", password="password")
        cls.other = user_model.objects.create_user(username="other", password="password")
        cls.project = VideoProject.objects.create(user=cls.owner, title="Owned project")
        cls.other_channel = PublishingChannel.objects.create(
            user=cls.other,
            channel_id="other-channel",
            channel_title="Other Channel",
        )

    def test_publication_rejects_a_channel_owned_by_another_user(self):
        publication = ScheduledPublication(
            project=self.project,
            channel=self.other_channel,
            title="Unsafe cross-tenant schedule",
            scheduled_for=timezone.now(),
        )
        with self.assertRaisesMessage(
            ValidationError,
            "project and publishing channel must have the same owner",
        ):
            publication.full_clean()


class OAuthStateTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _request_with_session(self, state):
        request = self.factory.get("/publishing/youtube/callback/", {"state": state})
        SessionMiddleware(lambda value: None).process_request(request)
        request.session.save()
        return request

    def test_state_is_verified_and_cannot_be_replayed(self):
        request = self._request_with_session("trusted-state")
        request.session[OAUTH_SESSION_KEY] = {
            "value": "trusted-state",
            "issued_at": int(time.time()),
        }
        self.assertEqual(_validate_oauth_state(request), "trusted-state")
        with self.assertRaises(OAuthStateError):
            _validate_oauth_state(request)

    def test_mismatched_state_is_rejected(self):
        request = self._request_with_session("attacker-state")
        request.session[OAUTH_SESSION_KEY] = {
            "value": "trusted-state",
            "issued_at": int(time.time()),
        }
        with self.assertRaises(OAuthStateError):
            _validate_oauth_state(request)


@override_settings(PUBLISHING_SIMULATION_MODE=True)
class SimulationPublishingTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="simulator",
            password="password",
        )
        self.client.force_login(self.user)
        self.channel = PublishingChannel.objects.create(
            user=self.user,
            channel_id=f"simulation-{self.user.pk}",
            channel_title="YouTube Sandbox",
        )

    def test_simulation_connect_creates_an_explicit_sandbox_channel(self):
        self.channel.delete()
        response = self.client.get(reverse("publishing:youtube_connect"))
        self.assertRedirects(response, reverse("publishing:channels"))
        channel = PublishingChannel.objects.get(user=self.user)
        self.assertEqual(channel.channel_title, "YouTube Sandbox")
        self.assertEqual(channel.credentials_blob, "")
        self.assertTrue(channel.is_active)

    def test_simulated_publish_marks_publication_and_project_published(self):
        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            project = VideoProject.objects.create(user=self.user, title="Ready Short")
            project.video_file.save("ready-short.mp4", ContentFile(b"valid-test-mp4"))
            publication = ScheduledPublication.objects.create(
                project=project,
                channel=self.channel,
                title="Ready Short",
                scheduled_for=timezone.now(),
            )
            result = publish_scheduled_publication(publication, force=True)

        project.refresh_from_db()
        self.assertEqual(result.status, ScheduledPublication.Status.PUBLISHED)
        self.assertTrue(result.youtube_video_id.startswith("sim-"))
        self.assertIn(result.youtube_video_id, result.publication_url)
        self.assertEqual(project.status, VideoProject.Status.PUBLISHED)

    def test_publish_now_form_does_not_require_a_schedule_value(self):
        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            project = VideoProject.objects.create(user=self.user, title="Publish from form")
            project.video_file.save("publish-form.mp4", ContentFile(b"valid-test-mp4"))
            response = self.client.post(
                reverse("publishing:publish_project", args=(project.pk,)),
                {
                    "mode": "now",
                    "channel": self.channel.pk,
                    "title": "Publish from form",
                    "description": "A complete simulated publish.",
                    "privacy_status": ScheduledPublication.Privacy.PUBLIC,
                    "tags_text": "shorts, testing",
                },
            )
        publication = ScheduledPublication.objects.get(project=project)
        self.assertRedirects(response, publication.get_absolute_url())
        self.assertEqual(publication.status, ScheduledPublication.Status.PUBLISHED)

    def test_scheduling_updates_the_project_calendar_state(self):
        project = VideoProject.objects.create(user=self.user, title="Schedule from form")
        scheduled_for = timezone.localtime(timezone.now() + timedelta(days=1)).replace(
            second=0,
            microsecond=0,
        )
        response = self.client.post(
            reverse("publishing:publish_project", args=(project.pk,)),
            {
                "mode": "schedule",
                "channel": self.channel.pk,
                "title": "Schedule from form",
                "description": "Scheduled publishing test.",
                "privacy_status": ScheduledPublication.Privacy.UNLISTED,
                "tags_text": "schedule",
                "scheduled_for": scheduled_for.strftime("%Y-%m-%dT%H:%M"),
            },
        )
        publication = ScheduledPublication.objects.get(project=project)
        self.assertRedirects(response, publication.get_absolute_url())
        project.refresh_from_db()
        self.assertEqual(project.status, VideoProject.Status.SCHEDULED)
        self.assertEqual(project.scheduled_for, publication.scheduled_for)

    @override_settings(PUBLISHING_MAX_ATTEMPTS=1)
    def test_missing_render_is_a_bounded_failure(self):
        project = VideoProject.objects.create(user=self.user, title="Missing render")
        publication = ScheduledPublication.objects.create(
            project=project,
            channel=self.channel,
            title="Missing render",
            scheduled_for=timezone.now(),
        )
        with self.assertRaisesMessage(PublishingError, "rendered video"):
            publish_scheduled_publication(publication, force=True)
        publication.refresh_from_db()
        self.assertEqual(publication.status, ScheduledPublication.Status.FAILED)
        self.assertEqual(publication.attempt_count, 1)
        self.assertIn("rendered video", publication.error_message)
