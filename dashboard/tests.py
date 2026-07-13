from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import APIKeyStore, Trend, VideoProject


class DashboardTenantScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.owner = user_model.objects.create_user(username="owner", password="test-password")
        cls.other = user_model.objects.create_user(username="other", password="test-password")
        cls.public_trend = Trend.objects.create(
            title="Public signal",
            niche="Science",
            source="rss",
            score=80,
            fingerprint="public-signal",
            user=None,
        )
        cls.owner_trend = Trend.objects.create(
            title="Owner private signal",
            niche="Technology",
            source="manual",
            score=90,
            fingerprint="owner-signal",
            user=cls.owner,
        )
        cls.other_trend = Trend.objects.create(
            title="Other private signal",
            niche="Finance",
            source="manual",
            score=100,
            fingerprint="other-signal",
            user=cls.other,
        )
        cls.owner_project = VideoProject.objects.create(
            user=cls.owner,
            trend=cls.owner_trend,
            title="Owner video project",
        )
        cls.other_project = VideoProject.objects.create(
            user=cls.other,
            trend=cls.other_trend,
            title="Other video project",
        )

    def setUp(self):
        self.client.force_login(self.owner)

    def test_overview_only_exposes_public_and_owned_trends(self):
        response = self.client.get(reverse("dashboard:overview"))
        self.assertContains(response, self.public_trend.title)
        self.assertContains(response, self.owner_trend.title)
        self.assertNotContains(response, self.other_trend.title)

    def test_active_trends_only_exposes_public_and_owned_trends(self):
        response = self.client.get(reverse("dashboard:trends"))
        self.assertContains(response, self.public_trend.title)
        self.assertContains(response, self.owner_trend.title)
        self.assertNotContains(response, self.other_trend.title)

    def test_video_queue_only_exposes_owned_projects(self):
        response = self.client.get(reverse("dashboard:queue"))
        self.assertContains(response, self.owner_project.title)
        self.assertNotContains(response, self.other_project.title)


class APIKeySettingsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="creator",
            password="test-password",
        )
        self.client.force_login(self.user)

    def test_provider_key_is_encrypted_and_can_be_replaced(self):
        secret = "sk-live-not-a-real-key-123456"
        response = self.client.post(
            reverse("dashboard:api_keys"),
            {"provider": APIKeyStore.Provider.OPENAI, "api_key": secret},
        )
        self.assertRedirects(response, reverse("dashboard:api_keys"))
        key_store = APIKeyStore.objects.get(
            user=self.user,
            provider=APIKeyStore.Provider.OPENAI,
        )
        self.assertNotEqual(key_store.encrypted_key, secret)
        self.assertNotIn(secret, key_store.encrypted_key)
        self.assertEqual(key_store.get_secret(), secret)

        replacement = "sk-live-replacement-key-654321"
        self.client.post(
            reverse("dashboard:api_keys"),
            {"provider": APIKeyStore.Provider.OPENAI, "api_key": replacement},
        )
        self.assertEqual(
            APIKeyStore.objects.filter(
                user=self.user,
                provider=APIKeyStore.Provider.OPENAI,
            ).count(),
            1,
        )
        key_store.refresh_from_db()
        self.assertEqual(key_store.get_secret(), replacement)
