from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("trends/", views.active_trends, name="trends"),
    path("queue/", views.video_queue, name="queue"),
    path("settings/api-keys/", views.api_key_settings, name="api_keys"),
    path(
        "settings/api-keys/<int:key_id>/remove/",
        views.remove_api_key,
        name="remove_api_key",
    ),
    path("calendar/", views.content_calendar, name="calendar"),
    path("calendar/events/", views.calendar_events, name="calendar_events"),
]
