"""Authenticated web endpoints for running the ingestion service."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .forms import TrendIngestionForm
from .services.ingestion import TrendIngestionService
from .services.sources import build_sources


@login_required
def index(request: HttpRequest) -> HttpResponse:
    """Use the dashboard's canonical Active Trends screen."""

    return redirect("dashboard:trends")


@require_http_methods(["GET", "POST"])
@login_required
def ingest(request: HttpRequest) -> HttpResponse:
    """Run ingestion on POST and render a validated configuration form on GET."""

    form = TrendIngestionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        service = TrendIngestionService(
            sources=build_sources(form.cleaned_data["sources"]),
        )
        report = service.run(
            form.cleaned_data["niches"],
            geo=form.cleaned_data["geo"],
            limit_per_source=form.cleaned_data["limit_per_source"],
            user=request.user,
            dispatch_ai=form.cleaned_data["dispatch_ai"],
        )
        messages.success(
            request,
            (
                f"Trend scan complete: {report.created} new, {report.updated} refreshed, "
                f"{report.dispatched} sent to AI generation."
            ),
        )
        for error in report.errors[:5]:
            messages.warning(request, f"{error.stage.title()}: {error.detail}")
        if len(report.errors) > 5:
            messages.warning(
                request,
                f"{len(report.errors) - 5} additional source errors were suppressed.",
            )
        return redirect("dashboard:trends")

    return render(request, "trends/ingest.html", {"form": form})
