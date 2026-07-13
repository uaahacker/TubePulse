from django.urls import path

from . import views

app_name = "ai_studio"

urlpatterns = [
    path("projects/create/", views.create_project, name="create_project"),
    path(
        "projects/<uuid:public_id>/render/",
        views.queue_project_render,
        name="render_project",
    ),
]
