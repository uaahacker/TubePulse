import signal
import threading

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from publishing.models import ScheduledPublication
from publishing.services import (
    PublishingError,
    due_publication_ids,
    publish_scheduled_publication,
    recover_stale_publications,
)


class Command(BaseCommand):
    help = "Publish due TubePulse videos and safely retry transient failures."

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stop_event = threading.Event()

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=25,
            help="Maximum number of due publications to process (default: 25).",
        )
        parser.add_argument(
            "--loop",
            action="store_true",
            help="Keep polling for due publications until SIGTERM or SIGINT.",
        )
        parser.add_argument(
            "--interval",
            type=float,
            default=30.0,
            help="Seconds between loop cycles, from 5 to 3600 (default: 30).",
        )

    def _request_stop(self, signum, frame):
        del frame
        self.stdout.write(f"Received signal {signum}; stopping after the current operation.")
        self.stop_event.set()

    def _run_cycle(self, limit, *, report_empty=True):
        close_old_connections()
        try:
            recovered = recover_stale_publications()
            if recovered:
                self.stdout.write(f"Recovered {recovered} stalled publication(s).")

            publication_ids = due_publication_ids(limit=limit)
            if not publication_ids:
                if report_empty:
                    self.stdout.write("No publications are due.")
                return 0, 0, 0

            succeeded = 0
            failed = 0
            for publication_id in publication_ids:
                if self.stop_event.is_set():
                    break
                try:
                    publication = ScheduledPublication.objects.get(pk=publication_id)
                    result = publish_scheduled_publication(publication)
                except PublishingError as exc:
                    failed += 1
                    self.stderr.write(f"Publication {publication_id}: {exc}")
                except Exception as exc:  # isolate one record from the remaining queue
                    failed += 1
                    self.stderr.write(
                        self.style.ERROR(
                            f"Publication {publication_id}: unexpected {type(exc).__name__}."
                        )
                    )
                else:
                    succeeded += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Published {result.title} ({result.youtube_video_id})."
                        )
                    )

            processed = succeeded + failed
            self.stdout.write(
                f"Processed {processed} publication(s): "
                f"{succeeded} published, {failed} deferred or failed."
            )
            return processed, succeeded, failed
        finally:
            close_old_connections()

    def handle(self, *args, **options):
        limit = options["limit"]
        if not 1 <= limit <= 500:
            raise CommandError("--limit must be between 1 and 500.")
        interval = options["interval"]
        if not 5 <= interval <= 3600:
            raise CommandError("--interval must be between 5 and 3600 seconds.")

        if not options["loop"]:
            self._run_cycle(limit)
            return

        previous_handlers = {}
        for signal_number in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signal_number] = signal.getsignal(signal_number)
            signal.signal(signal_number, self._request_stop)
        self.stdout.write(
            f"Publishing scheduler started (interval={interval:g}s, limit={limit})."
        )
        try:
            while not self.stop_event.is_set():
                try:
                    self._run_cycle(limit, report_empty=False)
                except Exception as exc:
                    self.stderr.write(
                        self.style.ERROR(
                            f"Scheduler cycle failed with {type(exc).__name__}; retrying next cycle."
                        )
                    )
                    close_old_connections()
                self.stop_event.wait(interval)
        finally:
            close_old_connections()
            for signal_number, handler in previous_handlers.items():
                signal.signal(signal_number, handler)
            self.stdout.write("Publishing scheduler stopped cleanly.")
