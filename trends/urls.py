from django.urls import path

from . import views

app_name = "trends"

urlpatterns = [
    path("", views.index, name="index"),
    path("ingest/", views.ingest, name="ingest"),
]
