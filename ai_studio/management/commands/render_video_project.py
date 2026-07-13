from __future__ import annotations

import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from core.models import VideoProject

from ai_studio.exceptions import AIStudioError
from ai_studio.services import render_video_project


class Command(BaseCommand):
    help = "Render one VideoProject and persist its generated MP4."

    def add_arguments(self, parser):
        parser.add_argument("project_id", help="Database ID or public UUID")
        parser.add_argument(
            "--asset",
            action="append",
            default=[],
            help="Local path or public media URL; repeat for multiple assets",
        )
        parser.add_argument("--stock-query", help="Override the Pexels search query")
        parser.add_argument("--audio", help="Override narration audio with a local file")
        parser.add_argument("--output", help="Also retain a rendered MP4 at this path")
        parser.add_argument("--duration", type=float, help="Explicit duration in seconds")
        parser.add_argument(
            "--retry",
            action="store_true",
            help="Allow a failed project to be claimed again",
        )

    def handle(self, *args, **options):
        project = self._get_project(options["project_id"])
        sources = options["asset"] or None
        try:
            result = render_video_project(
                project,
                asset_sources=sources,
                stock_query=options.get("stock_query"),
                audio_path=options.get("audio"),
                output_path=options.get("output"),
                duration=options.get("duration"),
                allow_retry=options["retry"],
                progress_logger="bar" if self.verbosity > 1 else None,
            )
        except (AIStudioError, OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"Rendered project {project.public_id} to {result.output_path}"
            )
        )

    @staticmethod
    def _get_project(identifier: str) -> VideoProject:
        query = Q()
        try:
            query |= Q(pk=int(identifier))
        except ValueError:
            try:
                query |= Q(public_id=uuid.UUID(identifier))
            except ValueError as exc:
                raise CommandError("project_id must be an integer or UUID") from exc
        try:
            return VideoProject.objects.select_related("user", "trend").get(query)
        except VideoProject.DoesNotExist as exc:
            raise CommandError(f"VideoProject {identifier} does not exist") from exc

