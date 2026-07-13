"""Canonical data model for TubePulse CRM."""
from __future__ import annotations

import uuid
from pathlib import Path

from django.contrib.auth.models import AbstractUser
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from .crypto import decrypt_secret, encrypt_secret


def _upload_path(instance: "VideoProject", filename: str, folder: str) -> str:
    extension = Path(filename).suffix.lower()[:10]
    return f"users/{instance.user_id}/projects/{instance.public_id}/{folder}/{uuid.uuid4().hex}{extension}"


def audio_upload_path(instance: "VideoProject", filename: str) -> str:
    return _upload_path(instance, filename, "audio")


def video_upload_path(instance: "VideoProject", filename: str) -> str:
    return _upload_path(instance, filename, "video")


def thumbnail_upload_path(instance: "VideoProject", filename: str) -> str:
    return _upload_path(instance, filename, "thumbnails")


class User(AbstractUser):
    """Application user and owner of all private CRM records."""

    display_name = models.CharField(max_length=120, blank=True)
    timezone = models.CharField(max_length=64, default="UTC")
    avatar_url = models.URLField(blank=True)

    @property
    def friendly_name(self) -> str:
        return self.display_name or self.get_full_name() or self.username


class Trend(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "New"
        REVIEWED = "reviewed", "Reviewed"
        QUEUED = "queued", "Queued"
        ARCHIVED = "archived", "Archived"

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="trends",
        null=True,
        blank=True,
        help_text="Null means the trend is visible to all users.",
    )
    niche = models.CharField(max_length=100, db_index=True)
    title = models.CharField(max_length=300)
    keywords = models.JSONField(default=list, blank=True)
    source = models.CharField(max_length=80, db_index=True)
    source_url = models.URLField(max_length=1000, blank=True)
    score = models.PositiveSmallIntegerField(
        default=50,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        db_index=True,
    )
    discovered_at = models.DateTimeField(default=timezone.now, db_index=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    fingerprint = models.CharField(max_length=64, unique=True, db_index=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NEW, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-score", "-discovered_at"]
        indexes = [models.Index(fields=["niche", "-discovered_at"])]

    def __str__(self) -> str:
        return f"{self.title} ({self.source})"


class APIKeyStore(models.Model):
    class Provider(models.TextChoices):
        OPENAI = "openai", "OpenAI"
        ANTHROPIC = "anthropic", "Anthropic"
        OPENROUTER = "openrouter", "OpenRouter"
        PEXELS = "pexels", "Pexels"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="api_keys")
    provider = models.CharField(max_length=32, choices=Provider.choices)
    encrypted_key = models.TextField()
    key_hint = models.CharField(max_length=12, blank=True, editable=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "provider"], name="unique_provider_key_per_user")
        ]
        ordering = ["provider"]

    def set_secret(self, value: str) -> None:
        clean = value.strip()
        self.encrypted_key = encrypt_secret(clean)
        self.key_hint = clean[-4:] if len(clean) >= 4 else "••••"

    def get_secret(self) -> str:
        if not self.is_active:
            raise ValueError(f"The {self.get_provider_display()} key is disabled")
        return decrypt_secret(self.encrypted_key)

    @property
    def masked_key(self) -> str:
        return f"••••••••{self.key_hint}" if self.key_hint else "Not configured"

    def __str__(self) -> str:
        return f"{self.user.username}: {self.get_provider_display()}"


class VideoProject(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SCRIPTING = "scripting", "Generating script"
        READY = "ready", "Ready to render"
        QUEUED = "queued", "Queued for render"
        RENDERING = "rendering", "Rendering"
        RENDERED = "rendered", "Rendered"
        SCHEDULED = "scheduled", "Scheduled"
        PUBLISHING = "publishing", "Publishing"
        PUBLISHED = "published", "Published"
        FAILED = "failed", "Failed"

    class Provider(models.TextChoices):
        OPENAI = "openai", "OpenAI"
        ANTHROPIC = "anthropic", "Anthropic"
        OPENROUTER = "openrouter", "OpenRouter"

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="video_projects")
    trend = models.ForeignKey(
        Trend,
        on_delete=models.SET_NULL,
        related_name="video_projects",
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    progress = models.PositiveSmallIntegerField(
        default=0, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    provider = models.CharField(max_length=32, choices=Provider.choices, default=Provider.OPENAI)
    script = models.TextField(blank=True)
    voiceover_prompt = models.TextField(blank=True)
    audio_file = models.FileField(upload_to=audio_upload_path, blank=True)
    source_assets = models.JSONField(default=list, blank=True)
    video_file = models.FileField(upload_to=video_upload_path, blank=True)
    thumbnail = models.ImageField(upload_to=thumbnail_upload_path, blank=True)
    scheduled_for = models.DateTimeField(null=True, blank=True, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True)
    publication_url = models.URLField(max_length=1000, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "status", "-created_at"])]

    def __str__(self) -> str:
        return self.title

    def mark_failed(self, message: str) -> None:
        self.status = self.Status.FAILED
        self.error_message = message[:4000]
        self.save(update_fields=["status", "error_message", "updated_at"])
