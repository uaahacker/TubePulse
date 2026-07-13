from django.test import TestCase, override_settings

from core.models import APIKeyStore, User
from core.services import MissingAPIKeyError, get_api_key


@override_settings(TUBEPULSE_ENCRYPTION_KEY="")
class APIKeyStoreTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="creator", password="strong-test-pass")

    def test_secret_round_trip_is_encrypted_at_rest(self):
        record = APIKeyStore(user=self.user, provider=APIKeyStore.Provider.OPENAI)
        record.set_secret("sk-live-secret-value")
        record.save()
        record.refresh_from_db()

        self.assertNotIn("sk-live", record.encrypted_key)
        self.assertEqual(record.get_secret(), "sk-live-secret-value")
        self.assertEqual(record.masked_key[-4:], "alue")

    def test_missing_key_has_actionable_message(self):
        with self.assertRaisesRegex(MissingAPIKeyError, "Configure an active Openai API key"):
            get_api_key(self.user, "openai")
