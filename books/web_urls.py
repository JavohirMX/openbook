from django.urls import path

from books import web_views as views

app_name = "web"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("books/", views.BookListView.as_view(), name="book-list"),
    path("books/add/", views.BookCreateView.as_view(), name="book-add"),
    path("books/lookup/", views.isbn_lookup, name="book-lookup"),
    path("books/search-metadata/", views.metadata_search, name="book-search-metadata"),
    path("books/<uuid:pk>/", views.BookDetailView.as_view(), name="book-detail"),
    path("books/<uuid:pk>/edit/", views.BookUpdateView.as_view(), name="book-edit"),
    path("books/<uuid:pk>/delete/", views.book_soft_delete, name="book-delete"),
    path("books/<uuid:pk>/shelve/", views.book_shelve, name="book-shelve"),
    path("books/<uuid:pk>/unshelve/", views.book_unshelve, name="book-unshelve"),
    path("books/<uuid:pk>/review/", views.book_review, name="book-review"),
    path("books/<uuid:pk>/reading/", views.book_reading, name="book-reading"),
    path("books/<uuid:pk>/quotes/", views.book_quote, name="book-quote"),
    path("books/<uuid:pk>/quotes/<int:quote_id>/delete/", views.book_quote_delete, name="book-quote-delete"),
    path("books/<uuid:pk>/refresh-metadata/", views.book_refresh_metadata, name="book-refresh-metadata"),
    path("authors/", views.AuthorListView.as_view(), name="author-list"),
    path("authors/<int:pk>/", views.AuthorDetailView.as_view(), name="author-detail"),
    path("genres/<slug:slug>/", views.GenreDetailView.as_view(), name="genre-detail"),
    path("embed/widget.js", views.embed_widget, name="embed-widget"),
    path("shelves/", views.ShelfListView.as_view(), name="shelf-list"),
    path("shelves/status/<slug:slug>/", views.StatusShelfDetailView.as_view(), name="status-shelf-detail"),
    path("shelves/<int:pk>/", views.ShelfDetailView.as_view(), name="shelf-detail"),
    path("shelves/<int:pk>/edit/", views.shelf_update, name="shelf-edit"),
    path("shelves/<int:pk>/delete/", views.shelf_delete, name="shelf-delete"),
    path("trash/", views.TrashListView.as_view(), name="trash-list"),
    path("trash/<uuid:pk>/restore/", views.trash_restore, name="trash-restore"),
    path("trash/<uuid:pk>/delete/", views.trash_delete_permanent, name="trash-delete"),
    path("settings/", views.SettingsView.as_view(), name="settings"),
    path("library-tools/", views.LibraryToolsView.as_view(), name="library-tools"),
    path("stats/", views.StatsPageView.as_view(), name="stats"),
    path("import-export/", views.ImportExportView.as_view(), name="import-export"),
    path("import-export/jobs/<uuid:pk>/", views.ImportJobDetailView.as_view(), name="import-job-detail"),
    path(
        "import-export/jobs/<uuid:pk>/status/",
        views.ImportJobStatusPartialView.as_view(),
        name="import-job-status",
    ),
    path(
        "import-export/jobs/<uuid:pk>/process/",
        views.ImportJobProcessView.as_view(),
        name="import-job-process",
    ),
]
