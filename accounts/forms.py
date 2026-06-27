from django import forms
from django.contrib.auth.forms import PasswordChangeForm as DjangoPasswordChangeForm

from accounts.models import UserProfile

INPUT_CLASS = "input mt-1 block w-full"

COMMON_TIMEZONES = [
    ("UTC", "UTC"),
    ("America/New_York", "Eastern Time (US)"),
    ("America/Chicago", "Central Time (US)"),
    ("America/Denver", "Mountain Time (US)"),
    ("America/Los_Angeles", "Pacific Time (US)"),
    ("Europe/London", "London"),
    ("Europe/Paris", "Paris / Berlin"),
    ("Asia/Tashkent", "Tashkent"),
    ("Asia/Tokyo", "Tokyo"),
    ("Asia/Singapore", "Singapore"),
    ("Australia/Sydney", "Sydney"),
]


class ProfileForm(forms.ModelForm):
    first_name = forms.CharField(
        label="First name",
        required=False,
        widget=forms.TextInput(attrs={"class": INPUT_CLASS, "id": "id_first_name"}),
    )
    last_name = forms.CharField(
        label="Last name",
        required=False,
        widget=forms.TextInput(attrs={"class": INPUT_CLASS, "id": "id_last_name"}),
    )

    class Meta:
        model = UserProfile
        fields = ["timezone"]
        widgets = {
            "timezone": forms.Select(attrs={"class": INPUT_CLASS, "id": "id_timezone"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user:
            self.fields["first_name"].initial = user.first_name
            self.fields["last_name"].initial = user.last_name
        self.fields["timezone"].widget.choices = COMMON_TIMEZONES

    def save(self, commit=True):
        profile = super().save(commit=commit)
        if self.user:
            self.user.first_name = self.cleaned_data.get("first_name", "")
            self.user.last_name = self.cleaned_data.get("last_name", "")
            self.user.save(update_fields=["first_name", "last_name"])
        return profile


class PasswordChangeForm(DjangoPasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", INPUT_CLASS)
            field.widget.attrs.pop("autofocus", None)


class SetupSuperuserForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"class": INPUT_CLASS}),
    )
    password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": INPUT_CLASS}),
    )
    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": INPUT_CLASS}),
    )

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("Passwords do not match.")
        return cleaned
