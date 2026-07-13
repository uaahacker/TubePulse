from django.urls import path

from . import views

app_name = "publishing"

urlpatterns = [
    path("channels/", views.channel_list, name="channels"),
    path("youtube/connect/", views.youtube_connect, name="youtube_connect"),
    path("youtube/callback/", views.youtube_callback, name="youtube_callback"),
    path(
        "channels/<int:channel_id>/disconnect/",
        views.disconnect_channel,
        name="disconnect_channel",
    ),
    path(
        "projects/<int:project_id>/publish/",
        views.publish_project,
        name="publish_project",
    ),
    path(
        "publications/<int:publication_id>/",
        views.publication_detail,
        name="publication_detail",
    ),
    path(
        "publications/<int:publication_id>/retry/",
        views.retry_publication,
        name="retry_publication",
    ),
    path(
        "publications/<int:publication_id>/cancel/",
        views.cancel_publication,
        name="cancel_publication",
    ),
]
