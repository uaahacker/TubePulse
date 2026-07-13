from django import forms

from core.models import APIKeyStore


class TrendFilterForm(forms.Form):
    q = forms.CharField(required=False, label="Search")
    niche = forms.CharField(required=False)
    source = forms.CharField(required=False)


class VideoQueueFilterForm(forms.Form):
    q = forms.CharField(required=False, label="Search")
    status = forms.CharField(required=False)


class APIKeyForm(forms.Form):
    provider = forms.ChoiceField(label="Provider")
    api_key = forms.CharField(
        label="API key",
        strip=True,
        min_length=8,
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "new-password",
                "placeholder": "Paste your private API key",
            }
        ),
        help_text="Your key is encrypted before it is stored and is never shown again.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["provider"].choices = APIKeyStore.Provider.choices

    def clean_api_key(self):
        value = self.cleaned_data["api_key"].strip()
        if any(character.isspace() for character in value):
            raise forms.ValidationError("API keys cannot contain spaces.")
        return value
