from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import APIKeyStore, Trend, User, VideoProject


@admin.register(User)
class TubePulseUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("TubePulse profile", {"fields": ("display_name", "timezone", "avatar_url")}),
    )


@admin.register(Trend)
class TrendAdmin(admin.ModelAdmin):
    list_display = ("title", "niche", "source", "score", "status", "discovered_at")
    list_filter = ("source", "status", "niche", "is_active")
    search_fields = ("title", "niche", "source")
    readonly_fields = ("fingerprint", "created_at", "updated_at")


@admin.register(VideoProject)
class VideoProjectAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "status", "progress", "provider", "created_at")
    list_filter = ("status", "provider")
    search_fields = ("title", "user__username")
    readonly_fields = ("public_id", "created_at", "updated_at")


@admin.register(APIKeyStore)
class APIKeyStoreAdmin(admin.ModelAdmin):
    list_display = ("user", "provider", "masked_key_display", "is_active", "updated_at")
    list_filter = ("provider", "is_active")
    search_fields = ("user__username",)
    exclude = ("encrypted_key",)

    @admin.display(description="Stored key")
    def masked_key_display(self, obj: APIKeyStore) -> str:
        return obj.masked_key

    def has_add_permission(self, request) -> bool:
        # Secrets must pass through set_secret(); the CRM settings form owns creation.
        return False
