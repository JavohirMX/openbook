from django import forms

from books.covers import CoverUploadError, validate_cover_upload
from books.isbn import normalize_and_validate
from books.models import AuthorRole, Book, Genre, BookNote, Quote, ReadingGoal, ReadingStatus, Review, Series, Shelf

INPUT_CLASS = (
    "input mt-1 block w-full"
)


class BookForm(forms.ModelForm):
    author_names = forms.CharField(
        label="Authors",
        required=False,
        widget=forms.TextInput(
            attrs={"class": INPUT_CLASS, "placeholder": "Author names, comma-separated"}
        ),
        help_text="Separate multiple authors with commas.",
    )
    genres = forms.ModelMultipleChoiceField(
        queryset=Genre.objects.all().order_by("name"),
        required=False,
        widget=forms.SelectMultiple(attrs={"class": INPUT_CLASS}),
    )
    series = forms.ModelChoiceField(
        queryset=Series.objects.all().order_by("sort_order", "name"),
        required=False,
        empty_label="No series",
        widget=forms.Select(attrs={"class": INPUT_CLASS}),
    )
    series_position = forms.DecimalField(
        required=False,
        max_digits=6,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"class": INPUT_CLASS, "placeholder": "e.g. 1 or 1.5", "step": "0.01"}),
    )
    editor_names = forms.CharField(
        label="Editors",
        required=False,
        widget=forms.TextInput(
            attrs={"class": INPUT_CLASS, "placeholder": "Editor names, comma-separated"}
        ),
    )
    translator_names = forms.CharField(
        label="Translators",
        required=False,
        widget=forms.TextInput(
            attrs={"class": INPUT_CLASS, "placeholder": "Translator names, comma-separated"}
        ),
    )
    illustrator_names = forms.CharField(
        label="Illustrators",
        required=False,
        widget=forms.TextInput(
            attrs={"class": INPUT_CLASS, "placeholder": "Illustrator names, comma-separated"}
        ),
    )
    isbn = forms.CharField(
        label="ISBN",
        required=False,
        widget=forms.TextInput(attrs={"class": INPUT_CLASS, "placeholder": "ISBN-10 or ISBN-13"}),
    )
    cover_image = forms.FileField(
        label="Cover image",
        required=False,
        widget=forms.ClearableFileInput(
            attrs={
                "class": "file-input text-sm",
                "accept": "image/jpeg,image/png,image/webp,image/gif",
            }
        ),
        help_text="JPEG, PNG, WebP, or GIF. Max 2 MB.",
    )
    remove_cover = forms.BooleanField(
        label="Remove uploaded cover",
        required=False,
        widget=forms.CheckboxInput(
            attrs={"class": "h-4 w-4 border-neutral-300 dark:border-neutral-700"}
        ),
    )

    class Meta:
        model = Book
        fields = [
            "title",
            "subtitle",
            "pages",
            "published_year",
            "published_date",
            "publisher",
            "description",
            "cover_url",
            "language",
            "format",
            "owned",
            "narrator",
            "series",
            "series_position",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": INPUT_CLASS}),
            "subtitle": forms.TextInput(attrs={"class": INPUT_CLASS}),
            "pages": forms.NumberInput(attrs={"class": INPUT_CLASS}),
            "published_year": forms.NumberInput(attrs={"class": INPUT_CLASS}),
            "published_date": forms.DateInput(attrs={"class": INPUT_CLASS, "type": "date"}),
            "publisher": forms.TextInput(attrs={"class": INPUT_CLASS}),
            "description": forms.Textarea(attrs={"rows": 4, "class": INPUT_CLASS}),
            "cover_url": forms.URLInput(attrs={"class": INPUT_CLASS}),
            "language": forms.TextInput(attrs={"class": INPUT_CLASS}),
            "format": forms.Select(attrs={"class": INPUT_CLASS}),
            "owned": forms.CheckboxInput(attrs={"class": "h-4 w-4 border-neutral-300 dark:border-neutral-700"}),
            "narrator": forms.TextInput(attrs={"class": INPUT_CLASS, "placeholder": "Narrator (audiobooks)"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["author_names"].initial = ", ".join(
                link.author.name
                for link in self.instance.book_authors.filter(role=AuthorRole.AUTHOR).select_related("author").order_by("position")
            )
            self.fields["genres"].initial = self.instance.genres.all()
            self.fields["series"].initial = self.instance.series
            self.fields["series_position"].initial = self.instance.series_position
            isbn = self.instance.isbn_13 or self.instance.isbn_10 or ""
            self.fields["isbn"].initial = isbn
            role_names = {
                AuthorRole.EDITOR: [],
                AuthorRole.TRANSLATOR: [],
                AuthorRole.ILLUSTRATOR: [],
            }
            for link in self.instance.book_authors.select_related("author").order_by("position"):
                if link.role in role_names:
                    role_names[link.role].append(link.author.name)
            self.fields["editor_names"].initial = ", ".join(role_names[AuthorRole.EDITOR])
            self.fields["translator_names"].initial = ", ".join(role_names[AuthorRole.TRANSLATOR])
            self.fields["illustrator_names"].initial = ", ".join(role_names[AuthorRole.ILLUSTRATOR])
        from books.covers import stored_cover_is_valid

        self.show_remove_cover = bool(
            self.instance and self.instance.pk and stored_cover_is_valid(self.instance)
        )
        if not self.show_remove_cover:
            self.fields.pop("remove_cover", None)

    def clean_cover_image(self):
        uploaded = self.cleaned_data.get("cover_image")
        if not uploaded:
            return uploaded
        try:
            validate_cover_upload(uploaded)
        except CoverUploadError as exc:
            raise forms.ValidationError(str(exc)) from exc
        uploaded.seek(0)
        return uploaded

    def clean(self):
        cleaned = super().clean()
        isbn_raw = cleaned.get("isbn", "")
        if isbn_raw:
            normalized_13, normalized_10, warnings = normalize_and_validate(raw=isbn_raw)
            cleaned["isbn_13"] = normalized_13
            cleaned["isbn_10"] = normalized_10
            self.isbn_warnings = warnings
        else:
            cleaned["isbn_13"] = None
            cleaned["isbn_10"] = None
            self.isbn_warnings = []
        return cleaned

    def get_author_list(self):
        raw = self.cleaned_data.get("author_names", "")
        return [n.strip() for n in raw.split(",") if n.strip()]

    def get_role_list(self, field_name: str) -> list[str]:
        raw = self.cleaned_data.get(field_name, "")
        return [n.strip() for n in raw.split(",") if n.strip()]


class GenreManageForm(forms.Form):
    name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": INPUT_CLASS, "placeholder": "New genre name"}),
    )
    merge_into = forms.ModelChoiceField(
        queryset=Genre.objects.all().order_by("name"),
        required=False,
        empty_label="Select genre to merge into",
        widget=forms.Select(attrs={"class": INPUT_CLASS}),
    )
    reassign_to = forms.ModelChoiceField(
        queryset=Genre.objects.all().order_by("name"),
        required=False,
        empty_label="Reassign books to (optional)",
        widget=forms.Select(attrs={"class": INPUT_CLASS}),
    )


from books.book_sort import SORT_CHOICES  # noqa: F401 — re-exported for backwards compatibility


class BookFilterForm(forms.Form):
    search = forms.CharField(required=False)
    shelf = forms.ModelChoiceField(queryset=Shelf.objects.all(), required=False, empty_label="All Shelves")
    genre = forms.ModelChoiceField(queryset=Genre.objects.all(), required=False, empty_label="All Genres")
    series = forms.ModelChoiceField(queryset=Series.objects.all(), required=False, empty_label="All Series")
    status = forms.ChoiceField(
        required=False,
        choices=[("", "All Status")] + list(ReadingStatus.choices),
    )
    rating = forms.ChoiceField(
        required=False,
        choices=[("", "All Ratings")] + [(str(i), f"{i} star{'s' if i != 1 else ''}") for i in range(5, 0, -1)],
    )
    sort = forms.ChoiceField(required=False, choices=SORT_CHOICES, initial="-created_at")


class ShelfForm(forms.ModelForm):
    class Meta:
        model = Shelf
        fields = ["name", "description", "color", "sort_order"]
        widgets = {
            "name": forms.TextInput(attrs={"class": INPUT_CLASS}),
            "description": forms.Textarea(attrs={"rows": 2, "class": INPUT_CLASS}),
            "color": forms.TextInput(attrs={"class": "h-11 w-16 border border-neutral-300 dark:border-neutral-700", "type": "color"}),
            "sort_order": forms.NumberInput(attrs={"class": INPUT_CLASS}),
        }


class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ["rating", "review_text"]
        widgets = {
            "rating": forms.HiddenInput(),
            "review_text": forms.Textarea(
                attrs={"rows": 4, "class": INPUT_CLASS, "placeholder": "Your review or notes..."}
            ),
        }


class ReadingUpdateForm(forms.Form):
    status = forms.ChoiceField(
        choices=ReadingStatus.choices,
        widget=forms.RadioSelect,
    )
    progress_percent = forms.IntegerField(min_value=0, max_value=100, required=False)
    current_page = forms.IntegerField(min_value=0, required=False)
    pages_read = forms.IntegerField(min_value=0, required=False, label="Pages read today")
    note = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": INPUT_CLASS, "placeholder": "Optional note"}),
    )


class ShelveForm(forms.Form):
    shelf = forms.ModelChoiceField(queryset=Shelf.objects.all())


class QuoteForm(forms.ModelForm):
    class Meta:
        model = Quote
        fields = ["text", "position"]
        widgets = {
            "text": forms.Textarea(attrs={"rows": 3, "class": INPUT_CLASS, "placeholder": "Quote text..."}),
            "position": forms.TextInput(
                attrs={"class": INPUT_CLASS, "placeholder": "Page or percent (e.g. p. 42 or 35%)"}
            ),
        }


class BookNoteForm(forms.ModelForm):
    class Meta:
        model = BookNote
        fields = ["text"]
        widgets = {
            "text": forms.Textarea(
                attrs={
                    "rows": 6,
                    "class": INPUT_CLASS,
                    "placeholder": "Private notes (Markdown supported)…",
                }
            ),
        }


class ISBNImportForm(forms.Form):
    isbns = forms.CharField(
        widget=forms.Textarea(
            attrs={"rows": 6, "class": INPUT_CLASS, "placeholder": "One ISBN per line"}
        ),
        label="ISBNs",
    )


class CSVImportForm(forms.Form):
    csv_file = forms.FileField(
        label="Goodreads CSV export",
        widget=forms.ClearableFileInput(attrs={"class": "file-input", "accept": ".csv,text/csv"}),
    )


class ReadingGoalForm(forms.ModelForm):
    class Meta:
        model = ReadingGoal
        fields = ["year", "target_books", "target_pages"]
        widgets = {
            "year": forms.NumberInput(attrs={"class": INPUT_CLASS, "min": 2000, "max": 2100}),
            "target_books": forms.NumberInput(attrs={"class": INPUT_CLASS, "min": 1}),
            "target_pages": forms.NumberInput(
                attrs={"class": INPUT_CLASS, "min": 1, "placeholder": "Optional"},
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["target_pages"].required = False
