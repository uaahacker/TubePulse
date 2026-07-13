"""Validated inputs for manual trend-ingestion runs."""

from __future__ import annotations

from django import forms
from django.core.validators import RegexValidator

from .services.normalization import unique_strings
from .services.sources import SOURCE_TYPES


class TrendIngestionForm(forms.Form):
    """Configuration for an authenticated, user-owned ingestion run."""

    niches = forms.CharField(
        label="Niches",
        max_length=500,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": "AI tools, personal finance, fitness",
                "class": "form-control",
            }
        ),
        help_text="Separate niches with commas or new lines.",
    )
    geo = forms.CharField(
        label="Country code",
        initial="US",
        max_length=2,
        min_length=2,
        validators=[
            RegexValidator(
                regex=r"^[A-Za-z]{2}$",
                message="Enter a two-letter country code, such as US or PK.",
            )
        ],
        widget=forms.TextInput(attrs={"class": "form-control text-uppercase"}),
    )
    sources = forms.MultipleChoiceField(
        choices=tuple((name, name.replace("_", " ").title()) for name in SOURCE_TYPES),
        initial=tuple(SOURCE_TYPES),
        widget=forms.CheckboxSelectMultiple,
    )
    limit_per_source = forms.IntegerField(
        label="Items per source",
        initial=20,
        min_value=1,
        max_value=100,
        widget=forms.NumberInput(attrs={"class": "form-control"}),
    )
    dispatch_ai = forms.BooleanField(
        label="Start AI script generation for new trends",
        required=False,
        help_text="Requires an active provider API key in Settings.",
    )

    def clean_niches(self) -> list[str]:
        raw = self.cleaned_data["niches"].replace("\r", "\n")
        parts: list[str] = []
        for line in raw.split("\n"):
            parts.extend(line.split(","))
        niches = unique_strings(parts, limit=50)
        if not niches:
            raise forms.ValidationError("Enter at least one niche.")
        if any(len(niche) > 100 for niche in niches):
            raise forms.ValidationError("Each niche must be 100 characters or fewer.")
        return niches

    def clean_geo(self) -> str:
        return self.cleaned_data["geo"].upper()
