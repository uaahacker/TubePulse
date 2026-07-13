from django.apps import AppConfig


class TrendsConfig(AppConfig):
    """Django application configuration for trend ingestion."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "trends"
    verbose_name = "Trend ingestion"
