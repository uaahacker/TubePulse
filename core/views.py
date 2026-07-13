from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import HttpRequest, JsonResponse
from django.shortcuts import redirect


@login_required
def root_redirect(request: HttpRequest):
    return redirect("dashboard:overview")


def health_check(request: HttpRequest) -> JsonResponse:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return JsonResponse({"status": "unhealthy", "database": "unavailable"}, status=503)
    return JsonResponse({"status": "ok", "database": "connected"})
