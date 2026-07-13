from django.contrib import admin

from .models import PublishingChannel, ScheduledPublication


@admin.register(PublishingChannel)
class PublishingChannelAdmin(admin.ModelAdmin):
    list_display = (
        "channel_title",
        "provider",
        "user",
        "is_active",
        "last_connected_at",
    )
    list_filter = ("provider", "is_active")
    search_fields = ("channel_title", "channel_id", "user__email")
    readonly_fields = (
        "channel_id",
        "channel_title",
        "channel_thumbnail_url",
        "scopes",
        "token_expiry",
        "last_connected_at",
        "created_at",
        "updated_at",
    )
    exclude = ("credentials_blob",)


@admin.register(ScheduledPublication)
class ScheduledPublicationAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "channel",
        "scheduled_for",
        "status",
        "attempt_count",
        "published_at",
    )
    list_filter = ("status", "privacy_status", "channel__provider")
    search_fields = ("title", "channel__channel_title", "youtube_video_id")
    readonly_fields = (
        "youtube_video_id",
        "publication_url",
        "attempt_count",
        "published_at",
        "created_at",
        "updated_at",
    )
    autocomplete_fields = ("project", "channel")
