from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone


class PublishingChannel(models.Model):
    class Provider(models.TextChoices):
        YOUTUBE = "youtube", "YouTube"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="publishing_channels",
    )
    provider = models.CharField(
        max_length=24,
        choices=Provider.choices,
        default=Provider.YOUTUBE,
    )
    channel_id = models.CharField(max_length=128)
    channel_title = models.CharField(max_length=255)
    channel_thumbnail_url = models.URLField(blank=True)
    credentials_blob = models.TextField(
        blank=True,
        help_text="Encrypted OAuth credentials; never exposed in forms or admin.",
    )
    scopes = models.JSONField(default=list, blank=True)
    token_expiry = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    last_connected_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("channel_title",)
        constraints = [
            models.UniqueConstraint(
                fields=("user", "provider", "channel_id"),
                name="unique_user_publishing_channel",
            )
        ]

    def __str__(self):
        return f"{self.channel_title} ({self.get_provider_display()})"

    def set_credentials(self, payload):
        from .security import encrypt_json

        self.credentials_blob = encrypt_json(payload)
        self.token_expiry = payload.get("expiry") or None
        self.scopes = payload.get("scopes") or []

    def get_credentials(self):
        from .security import decrypt_json

        if not self.credentials_blob:
            return None
        return decrypt_json(self.credentials_blob)

    def clear_credentials(self):
        self.credentials_blob = ""
        self.token_expiry = None
        self.scopes = []


class ScheduledPublication(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Uploading"
        RETRY = "retry", "Retry scheduled"
        PUBLISHED = "published", "Published"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    class Privacy(models.TextChoices):
        PUBLIC = "public", "Public"
        UNLISTED = "unlisted", "Unlisted"
        PRIVATE = "private", "Private"

    project = models.ForeignKey(
        "core.VideoProject",
        on_delete=models.CASCADE,
        related_name="publications",
    )
    channel = models.ForeignKey(
        PublishingChannel,
        on_delete=models.CASCADE,
        related_name="publications",
    )
    title = models.CharField(max_length=100)
    description = models.TextField(blank=True, max_length=5000)
    tags = models.JSONField(default=list, blank=True)
    privacy_status = models.CharField(
        max_length=12,
        choices=Privacy.choices,
        default=Privacy.PUBLIC,
    )
    scheduled_for = models.DateTimeField(db_index=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    youtube_video_id = models.CharField(max_length=32, blank=True)
    publication_url = models.URLField(blank=True)
    error_message = models.TextField(blank=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("scheduled_for", "pk")
        indexes = [
            models.Index(
                fields=("status", "scheduled_for"),
                name="publication_due_idx",
            )
        ]

    def __str__(self):
        return f"{self.title} → {self.channel.channel_title}"

    def clean(self):
        super().clean()
        if self.project_id and self.channel_id:
            project_user_id = self.project.user_id
            if project_user_id != self.channel.user_id:
                raise ValidationError("The project and publishing channel must have the same owner.")

    def get_absolute_url(self):
        return reverse("publishing:publication_detail", args=(self.pk,))

    @property
    def can_cancel(self):
        return self.status in {self.Status.PENDING, self.Status.RETRY}

    @property
    def can_retry(self):
        return self.status == self.Status.FAILED
