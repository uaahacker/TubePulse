from __future__ import annotations

import signal
import threading
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.utils import timezone

from core.models import VideoProject

from ai_studio.exceptions import AIStudioError
from ai_studio.services import render_video_project


class Command(BaseCommand):
    help = "Process QUEUED VideoProjects once or continuously with --loop."

    def add_arguments(self, parser):
        parser.add_argument(
            "--loop", action="store_true", help="Continue polling until a stop signal"
        )
        parser.add_argument(
            "--interval",
            type=float,
            default=5.0,
            help="Seconds between empty queue polls (1-60)",
        )
        parser.add_argument(
            "--batch-size", type=int, default=5, help="Projects claimed per poll (1-50)"
        )
        parser.add_argument(
            "--stale-minutes",
            type=int,
            default=settings.TUBEPULSE_RENDER_STALE_MINUTES,
            help="Recover rendering jobs with no update for this many minutes",
        )

    def handle(self, *args, **options):
        interval = options["interval"]
        batch_size = options["batch_size"]
        stale_minutes = options["stale_minutes"]
        if not 1 <= interval <= 60:
            raise CommandError("--interval must be between 1 and 60 seconds")
        if not 1 <= batch_size <= 50:
            raise CommandError("--batch-size must be between 1 and 50")
        if not 5 <= stale_minutes <= 1_440:
            raise CommandError("--stale-minutes must be between 5 and 1440")

        stop_event = threading.Event()

        def request_stop(signum, frame):
            stop_event.set()

        previous_handlers = {}
        for signal_name in ("SIGINT", "SIGTERM"):
            signum = getattr(signal, signal_name, None)
            if signum is not None:
                previous_handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, request_stop)
        try:
            while not stop_event.is_set():
                self._recover_stale(stale_minutes)
                processed = self._process_batch(batch_size, stop_event)
                if not options["loop"]:
                    break
                if processed == 0:
                    close_old_connections()
                    stop_event.wait(interval)
        finally:
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)

    def _process_batch(self, batch_size: int, stop_event: threading.Event) -> int:
        project_ids = list(
            VideoProject.objects.filter(status=VideoProject.Status.QUEUED)
            .order_by("created_at")
            .values_list("pk", flat=True)[:batch_size]
        )
        processed = 0
        for project_id in project_ids:
            if stop_event.is_set():
                break
            project = VideoProject.objects.select_related("user", "trend").get(
                pk=project_id
            )
            try:
                result = render_video_project(project)
            except (AIStudioError, OSError, ValueError) as exc:
                self.stderr.write(
                    self.style.ERROR(f"Project {project.public_id} failed: {exc}")
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Rendered {project.public_id} to {result.output_path}"
                    )
                )
            processed += 1
            close_old_connections()
        return processed

    def _recover_stale(self, stale_minutes: int) -> int:
        now = timezone.now()
        recovered = VideoProject.objects.filter(
            status=VideoProject.Status.RENDERING,
            updated_at__lt=now - timedelta(minutes=stale_minutes),
        ).update(
            status=VideoProject.Status.QUEUED,
            progress=40,
            error_message="Recovered after an interrupted render; queued to retry.",
            updated_at=now,
        )
        if recovered:
            self.stdout.write(self.style.WARNING(f"Recovered {recovered} stale render(s)."))
        return recovered
