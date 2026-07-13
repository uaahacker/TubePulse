from django.apps import AppConfig


class AiStudioConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ai_studio"
    verbose_name = "AI Studio"


# Readable alias for code that imports the config class directly.
AIStudioConfig = AiStudioConfig

