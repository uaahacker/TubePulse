from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.models import VideoProject

from .forms import PublicationForm
from .models import PublishingChannel, ScheduledPublication
from .services import (
    PublishingError,
    begin_youtube_oauth,
    complete_youtube_oauth,
    connect_simulated_channel,
    publish_scheduled_publication,
    revoke_channel_access,
    simulation_mode_enabled,
)


@login_required
def channel_list(request):
    channels = PublishingChannel.objects.filter(user=request.user).order_by(
        "-is_active", "channel_title"
    )
    return render(
        request,
        "publishing/channels.html",
        {
            "channels": channels,
            "simulation_mode": simulation_mode_enabled(),
            "oauth_configured": bool(
                getattr(settings, "YOUTUBE_CLIENT_SECRETS_FILE", "")
                or (
                    getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "")
                    and getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", "")
                )
            ),
        },
    )


@require_GET
@login_required
def youtube_connect(request):
    if simulation_mode_enabled():
        connect_simulated_channel(request.user)
        messages.warning(
            request,
            "YouTube Sandbox connected. Simulation mode never sends content to YouTube.",
        )
        return redirect("publishing:channels")
    try:
        return redirect(begin_youtube_oauth(request))
    except PublishingError as exc:
        messages.error(request, str(exc))
        return redirect("publishing:channels")


@require_GET
@login_required
def youtube_callback(request):
    try:
        channel = complete_youtube_oauth(request)
    except PublishingError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"{channel.channel_title} is connected and ready.")
    return redirect("publishing:channels")


@require_POST
@login_required
def disconnect_channel(request, channel_id):
    channel = get_object_or_404(
        PublishingChannel,
        pk=channel_id,
        user=request.user,
        is_active=True,
    )
    revoked = revoke_channel_access(channel)
    with transaction.atomic():
        channel.publications.filter(
            status__in=[
                ScheduledPublication.Status.PENDING,
                ScheduledPublication.Status.RETRY,
            ]
        ).update(
            status=ScheduledPublication.Status.CANCELLED,
            error_message="The channel was disconnected before publication.",
            next_attempt_at=None,
            updated_at=timezone.now(),
        )
        channel.is_active = False
        channel.clear_credentials()
        channel.save(
            update_fields=(
                "is_active",
                "credentials_blob",
                "token_expiry",
                "scopes",
                "updated_at",
            )
        )
    if revoked:
        messages.success(request, f"{channel.channel_title} was disconnected.")
    else:
        messages.warning(
            request,
            "The local connection was removed, but Google could not be reached to revoke it.",
        )
    return redirect("publishing:channels")


@require_http_methods(["GET", "POST"])
@login_required
def publish_project(request, project_id):
    project = get_object_or_404(VideoProject, pk=project_id, user=request.user)
    if request.method == "POST":
        form = PublicationForm(request.POST, user=request.user, project=project)
        if form.is_valid():
            publication = form.save()
            if form.cleaned_data["mode"] == PublicationForm.Mode.NOW:
                try:
                    publication = publish_scheduled_publication(publication, force=True)
                except PublishingError as exc:
                    publication.refresh_from_db()
                    messages.error(request, str(exc))
                else:
                    if simulation_mode_enabled():
                        messages.warning(
                            request,
                            "Simulation completed. No video was sent to YouTube.",
                        )
                    else:
                        messages.success(request, "Your Short was published to YouTube.")
            else:
                VideoProject.objects.filter(pk=project.pk).update(
                    status=VideoProject.Status.SCHEDULED,
                    scheduled_for=publication.scheduled_for,
                    updated_at=timezone.now(),
                )
                messages.success(
                    request,
                    f"Publication scheduled for {timezone.localtime(publication.scheduled_for):%b %d, %Y at %H:%M}.",
                )
            return redirect(publication)
    else:
        form = PublicationForm(user=request.user, project=project)

    return render(
        request,
        "publishing/publish_form.html",
        {
            "form": form,
            "project": project,
            "simulation_mode": simulation_mode_enabled(),
            "has_channels": PublishingChannel.objects.filter(
                user=request.user, is_active=True
            ).exists(),
        },
    )


@login_required
def publication_detail(request, publication_id):
    publication = get_object_or_404(
        ScheduledPublication.objects.select_related("project", "channel"),
        pk=publication_id,
        channel__user=request.user,
    )
    return render(
        request,
        "publishing/publication_detail.html",
        {
            "publication": publication,
            "simulation_mode": simulation_mode_enabled(),
        },
    )


@require_POST
@login_required
def retry_publication(request, publication_id):
    publication = get_object_or_404(
        ScheduledPublication,
        pk=publication_id,
        channel__user=request.user,
        status=ScheduledPublication.Status.FAILED,
    )
    publication.status = ScheduledPublication.Status.PENDING
    publication.scheduled_for = timezone.now()
    publication.next_attempt_at = None
    publication.error_message = ""
    publication.attempt_count = 0
    publication.save(
        update_fields=(
            "status",
            "scheduled_for",
            "next_attempt_at",
            "error_message",
            "attempt_count",
            "updated_at",
        )
    )
    try:
        publish_scheduled_publication(publication, force=True)
    except PublishingError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Publication retry completed.")
    return redirect(publication)


@require_POST
@login_required
def cancel_publication(request, publication_id):
    publication = get_object_or_404(
        ScheduledPublication,
        pk=publication_id,
        channel__user=request.user,
        status__in=[ScheduledPublication.Status.PENDING, ScheduledPublication.Status.RETRY],
    )
    publication.status = ScheduledPublication.Status.CANCELLED
    publication.next_attempt_at = None
    publication.error_message = "Cancelled by the user."
    publication.save(
        update_fields=("status", "next_attempt_at", "error_message", "updated_at")
    )
    messages.success(request, "Scheduled publication cancelled.")
    return redirect(publication)
