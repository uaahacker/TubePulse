from datetime import timedelta

from django import forms
from django.db import models
from django.utils import timezone

from .models import PublishingChannel, ScheduledPublication


class PublicationForm(forms.ModelForm):
    class Mode(models.TextChoices):
        NOW = "now", "Publish now"
        SCHEDULE = "schedule", "Schedule for later"

    mode = forms.ChoiceField(
        choices=Mode.choices,
        initial=Mode.NOW,
        widget=forms.RadioSelect,
    )
    tags_text = forms.CharField(
        required=False,
        label="Tags",
        help_text="Comma-separated keywords; YouTube accepts up to 500 characters total.",
    )

    class Meta:
        model = ScheduledPublication
        fields = (
            "channel",
            "title",
            "description",
            "privacy_status",
            "scheduled_for",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
            "scheduled_for": forms.DateTimeInput(
                attrs={"type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
        }

    def __init__(self, *args, user, project, **kwargs):
        self.user = user
        self.project = project
        super().__init__(*args, **kwargs)
        self.fields["channel"].queryset = PublishingChannel.objects.filter(
            user=user,
            is_active=True,
        )
        self.fields["scheduled_for"].required = False
        self.fields["scheduled_for"].input_formats = ("%Y-%m-%dT%H:%M",)
        if not self.is_bound:
            self.initial.setdefault("title", project.title[:100])
            self.initial.setdefault(
                "scheduled_for",
                timezone.localtime(timezone.now() + timedelta(hours=1)).strftime(
                    "%Y-%m-%dT%H:%M"
                ),
            )
            trend = getattr(project, "trend", None)
            keywords = getattr(trend, "keywords", []) if trend else []
            if isinstance(keywords, list):
                self.initial.setdefault("tags_text", ", ".join(map(str, keywords)))

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get("mode")
        scheduled_for = cleaned.get("scheduled_for")
        if mode == self.Mode.NOW:
            cleaned["scheduled_for"] = timezone.now()
        elif mode == self.Mode.SCHEDULE:
            if not scheduled_for:
                self.add_error("scheduled_for", "Choose a date and time.")
            elif scheduled_for <= timezone.now():
                self.add_error("scheduled_for", "Choose a time in the future.")
        return cleaned

    def clean_tags_text(self):
        tags = [item.strip() for item in self.cleaned_data.get("tags_text", "").split(",")]
        tags = list(dict.fromkeys(item for item in tags if item))
        if sum(len(item) for item in tags) + max(len(tags) - 1, 0) > 500:
            raise forms.ValidationError("Tags must use 500 characters or fewer in total.")
        return tags

    def save(self, commit=True):
        publication = super().save(commit=False)
        publication.project = self.project
        publication.tags = self.cleaned_data["tags_text"]
        publication.status = ScheduledPublication.Status.PENDING
        publication.full_clean()
        if commit:
            publication.save()
        return publication
