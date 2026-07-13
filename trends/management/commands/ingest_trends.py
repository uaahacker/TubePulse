"""Fetch and persist trend candidates from public RSS sources."""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError, CommandParser

from trends.services.ingestion import TrendIngestionService
from trends.services.sources import SOURCE_TYPES, build_sources


class Command(BaseCommand):
    help = "Ingest niche trends from free public RSS sources into SQLite."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--niche",
            action="append",
            dest="niches",
            required=True,
            help="Niche to scan; repeat this option for multiple niches.",
        )
        parser.add_argument("--geo", default="US", help="Two-letter country code.")
        parser.add_argument(
            "--source",
            action="append",
            dest="sources",
            choices=tuple(SOURCE_TYPES),
            help="Source adapter to use; repeat for multiple sources. Defaults to all.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=20,
            choices=range(1, 101),
            metavar="1..100",
            help="Maximum candidates per niche and source.",
        )
        parser.add_argument(
            "--user",
            help="Optional user primary key or configured login-field value.",
        )
        parser.add_argument(
            "--dispatch-ai",
            action="store_true",
            help="Submit newly created trends to the configured AI pipeline.",
        )
        parser.add_argument(
            "--redispatch-existing",
            action="store_true",
            help="Also submit refreshed trends; may create duplicate generation jobs.",
        )

    @staticmethod
    def _resolve_user(value: str | None) -> Any | None:
        if not value:
            return None
        model = get_user_model()
        if value.isdigit():
            user = model.objects.filter(pk=int(value)).first()
            if user is not None:
                return user
        login_field = model.USERNAME_FIELD
        user = model.objects.filter(**{login_field: value}).first()
        if user is None:
            raise ValueError(f"No user matched {value!r}.")
        return user

    def handle(self, *args: object, **options: object) -> None:
        try:
            user = self._resolve_user(options.get("user"))
            sources = build_sources(options.get("sources"))
            report = TrendIngestionService(sources=sources).run(
                options["niches"],
                geo=str(options["geo"]),
                limit_per_source=int(options["limit"]),
                user=user,
                dispatch_ai=bool(options["dispatch_ai"]),
                redispatch_existing=bool(options["redispatch_existing"]),
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Fetched {report.fetched}; normalized {report.normalized}; "
                f"created {report.created}; refreshed {report.updated}; "
                f"AI dispatched {report.dispatched}."
            )
        )
        for error in report.errors:
            context = "/".join(part for part in (error.source, error.niche) if part)
            prefix = f" [{context}]" if context else ""
            self.stderr.write(
                self.style.WARNING(f"{error.stage}{prefix}: {error.detail}")
            )
