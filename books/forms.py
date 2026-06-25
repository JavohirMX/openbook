from django import forms

from books.isbn import normalize_and_validate
from books.models import Book, Genre, Quote, ReadingStatus, Review, Shelf

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
    isbn = forms.CharField(
        label="ISBN",
        required=False,
        widget=forms.TextInput(attrs={"class": INPUT_CLASS, "placeholder": "ISBN-10 or ISBN-13"}),
    )

    class Meta:
        model = Book
        fields = [
            "title",
            "subtitle",
            "pages",
            "published_year",
            "publisher",
            "description",
            "cover_url",
            "language",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": INPUT_CLASS}),
            "subtitle": forms.TextInput(attrs={"class": INPUT_CLASS}),
            "pages": forms.NumberInput(attrs={"class": INPUT_CLASS}),
            "published_year": forms.NumberInput(attrs={"class": INPUT_CLASS}),
            "publisher": forms.TextInput(attrs={"class": INPUT_CLASS}),
            "description": forms.Textarea(attrs={"rows": 4, "class": INPUT_CLASS}),
            "cover_url": forms.URLInput(attrs={"class": INPUT_CLASS}),
            "language": forms.TextInput(attrs={"class": INPUT_CLASS}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["author_names"].initial = ", ".join(
                a.name for a in self.instance.authors.all()
            )
            self.fields["genres"].initial = self.instance.genres.all()
            isbn = self.instance.isbn_13 or self.instance.isbn_10 or ""
            self.fields["isbn"].initial = isbn

    def clean(self):
        cleaned = super().clean()
        isbn_raw = cleaned.get("isbn", "")
        if isbn_raw:
            normalized_13, normalized_10, warnings = normalize_and_validate(isbn=isbn_raw)
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


SORT_CHOICES = [
    ("-created_at", "Recently added"),
    ("title", "Title A–Z"),
    ("-title", "Title Z–A"),
    ("author", "Author A–Z"),
    ("-finished_at", "Recently finished"),
]


class BookFilterForm(forms.Form):
    search = forms.CharField(required=False)
    shelf = forms.ModelChoiceField(queryset=Shelf.objects.all(), required=False, empty_label="All Shelves")
    genre = forms.ModelChoiceField(queryset=Genre.objects.all(), required=False, empty_label="All Genres")
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
        fields = ["name", "description"]
        widgets = {
            "name": forms.TextInput(attrs={"class": INPUT_CLASS}),
            "description": forms.Textarea(attrs={"rows": 2, "class": INPUT_CLASS}),
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
