import calendar
from collections import defaultdict
from datetime import date, datetime, time

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import APIKeyStore, Trend, VideoProject
from publishing.models import PublishingChannel, ScheduledPublication

from .forms import APIKeyForm, TrendFilterForm, VideoQueueFilterForm


def _page(request, queryset, per_page=12):
    return Paginator(queryset, per_page).get_page(request.GET.get("page"))


def _safe_month(year_value, month_value):
    today = timezone.localdate()
    try:
        year = int(year_value or today.year)
        month = int(month_value or today.month)
        if not 1 <= month <= 12 or not 2000 <= year <= 2100:
            raise ValueError
    except (TypeError, ValueError):
        return today.year, today.month
    return year, month


@login_required
def overview(request):
    projects = VideoProject.objects.filter(user=request.user)
    active_trends_qs = Trend.objects.filter(is_active=True).filter(
        Q(user__isnull=True) | Q(user=request.user)
    )
    publications = ScheduledPublication.objects.filter(channel__user=request.user)

    context = {
        "active_trend_count": active_trends_qs.count(),
        "queue_count": projects.exclude(
            status__in=[
                "rendered",
                "completed",
                "scheduled",
                "published",
                "failed",
                "cancelled",
            ]
        ).count(),
        "ready_count": projects.filter(status__in=["rendered", "completed"]).count(),
        "scheduled_count": publications.filter(
            status__in=[
                ScheduledPublication.Status.PENDING,
                ScheduledPublication.Status.RETRY,
            ]
        ).count(),
        "connected_channel_count": PublishingChannel.objects.filter(
            user=request.user, is_active=True
        ).count(),
        "recent_trends": active_trends_qs.order_by("-score", "-discovered_at")[:6],
        "recent_projects": projects.select_related("trend").order_by("-updated_at")[:6],
        "upcoming_publications": publications.filter(
            status__in=[
                ScheduledPublication.Status.PENDING,
                ScheduledPublication.Status.RETRY,
            ],
            scheduled_for__gte=timezone.now(),
        )
        .select_related("project", "channel")
        .order_by("scheduled_for")[:5],
    }
    return render(request, "dashboard/overview.html", context)


@login_required
def active_trends(request):
    form = TrendFilterForm(request.GET or None)
    visible_trends = Trend.objects.filter(is_active=True).filter(
        Q(user__isnull=True) | Q(user=request.user)
    )
    trends = visible_trends.order_by("-score", "-discovered_at")
    if form.is_valid():
        query = form.cleaned_data["q"]
        niche = form.cleaned_data["niche"]
        source = form.cleaned_data["source"]
        if query:
            trends = trends.filter(
                Q(title__icontains=query)
                | Q(niche__icontains=query)
                | Q(source__icontains=query)
                | Q(keywords__icontains=query)
            )
        if niche:
            trends = trends.filter(niche=niche)
        if source:
            trends = trends.filter(source=source)

    niches = (
        visible_trends
        .exclude(niche="")
        .values_list("niche", flat=True)
        .distinct()
        .order_by("niche")
    )
    sources = (
        visible_trends
        .exclude(source="")
        .values_list("source", flat=True)
        .distinct()
        .order_by("source")
    )
    return render(
        request,
        "dashboard/trends.html",
        {
            "form": form,
            "trends": _page(request, trends),
            "niches": niches,
            "sources": sources,
        },
    )


@login_required
def video_queue(request):
    form = VideoQueueFilterForm(request.GET or None)
    projects = VideoProject.objects.filter(user=request.user).select_related("trend")
    if form.is_valid():
        query = form.cleaned_data["q"]
        status = form.cleaned_data["status"]
        if query:
            projects = projects.filter(
                Q(title__icontains=query)
                | Q(trend__title__icontains=query)
                | Q(script__icontains=query)
            )
        if status:
            projects = projects.filter(status=status)

    status_choices = getattr(VideoProject, "Status").choices
    return render(
        request,
        "dashboard/queue.html",
        {
            "form": form,
            "projects": _page(request, projects.order_by("-updated_at"), 15),
            "status_choices": status_choices,
        },
    )


@login_required
def api_key_settings(request):
    if request.method == "POST":
        form = APIKeyForm(request.POST)
        if form.is_valid():
            key_store, _ = APIKeyStore.objects.get_or_create(
                user=request.user,
                provider=form.cleaned_data["provider"],
                defaults={"is_active": True},
            )
            key_store.set_secret(form.cleaned_data["api_key"])
            key_store.is_active = True
            key_store.save()
            messages.success(
                request,
                f"{key_store.get_provider_display()} credentials saved securely.",
            )
            return redirect("dashboard:api_keys")
    else:
        form = APIKeyForm()

    keys = APIKeyStore.objects.filter(user=request.user).order_by("provider")
    return render(
        request,
        "dashboard/api_keys.html",
        {"form": form, "api_keys": keys},
    )


@require_POST
@login_required
def remove_api_key(request, key_id):
    key_store = get_object_or_404(APIKeyStore, pk=key_id, user=request.user)
    provider = key_store.get_provider_display()
    key_store.delete()
    messages.success(request, f"{provider} credentials removed.")
    return redirect("dashboard:api_keys")


@login_required
def content_calendar(request):
    year, month = _safe_month(request.GET.get("year"), request.GET.get("month"))
    month_calendar = calendar.Calendar(firstweekday=0)
    weeks = month_calendar.monthdatescalendar(year, month)
    first_day = weeks[0][0]
    last_day = weeks[-1][-1]

    start = timezone.make_aware(datetime.combine(first_day, time.min))
    end = timezone.make_aware(datetime.combine(last_day, time.max))
    publications = list(
        ScheduledPublication.objects.filter(
            channel__user=request.user,
            scheduled_for__range=(start, end),
        )
        .select_related("project", "channel")
        .order_by("scheduled_for")
    )
    grouped = defaultdict(list)
    for publication in publications:
        grouped[timezone.localtime(publication.scheduled_for).date()].append(publication)

    calendar_weeks = []
    today = timezone.localdate()
    for week in weeks:
        calendar_weeks.append(
            [
                {
                    "date": day,
                    "in_month": day.month == month,
                    "is_today": day == today,
                    "events": grouped[day],
                }
                for day in week
            ]
        )

    previous_date = date(year, month, 1)
    if month == 1:
        previous_year, previous_month = year - 1, 12
    else:
        previous_year, previous_month = year, month - 1
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    return render(
        request,
        "dashboard/calendar.html",
        {
            "calendar_weeks": calendar_weeks,
            "month_label": previous_date.strftime("%B %Y"),
            "month": month,
            "year": year,
            "previous_year": previous_year,
            "previous_month": previous_month,
            "next_year": next_year,
            "next_month": next_month,
        },
    )


@login_required
def calendar_events(request):
    try:
        start = datetime.fromisoformat(request.GET["start"])
        end = datetime.fromisoformat(request.GET["end"])
    except (KeyError, TypeError, ValueError):
        return JsonResponse({"error": "Valid ISO start and end values are required."}, status=400)

    if timezone.is_naive(start):
        start = timezone.make_aware(start)
    if timezone.is_naive(end):
        end = timezone.make_aware(end)
    events = ScheduledPublication.objects.filter(
        channel__user=request.user,
        scheduled_for__gte=start,
        scheduled_for__lt=end,
    ).select_related("project", "channel")
    payload = [
        {
            "id": publication.pk,
            "title": publication.title,
            "start": publication.scheduled_for.isoformat(),
            "status": publication.status,
            "channel": publication.channel.channel_title,
            "url": publication.get_absolute_url(),
        }
        for publication in events
    ]
    return JsonResponse({"events": payload})
