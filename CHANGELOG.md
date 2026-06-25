# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Contributor, operations, API consumer, and import pipeline documentation (`docs/07`–`10`, `docs/README.md`)
- Author list/detail pages (web + API) with clickable authors on book detail
- Genre detail pages with clickable genre badges
- Reading history timeline on book detail (`GET /api/v1/books/{id}/reading/history/`)
- Rating filter on books list and API (`?rating=`)
- Title/author metadata search on add-book (Open Library + Google Books)
- External provider links on book detail (Open Library, Google Books, Amazon, Goodreads)
- Book quotes/highlights (web + API)
- Public embed widget for currently reading / recently finished lists (Settings → Embed)
- User profile settings: name and timezone (`UserProfile` model, timezone middleware)
- Books list sort (title, recently added, author, recently finished)
- Accessible star rating component (SVG, keyboard labels)
- Mobile search panel, skip-to-main link, drawer close on Escape/nav
- `books/static/books/star-rating.js` and `forms.js` for rating and form UX

### Changed
- Full UI/UX pass: touch targets (44px), consistent empty states, destructive `.btn-destructive`
- Dashboard and stats use metrics strip instead of stat card grid
- Book detail: single-surface editorial layout with section dividers
- Books list: labeled filters, mobile cover thumbnails, pagination a11y
- Login/setup unified via `auth_layout.html`; password show/hide toggle
- Shelves, trash, import/export polish; chart screen-reader summaries
- Sidebar refactored to `nav_item` component; import job detail highlights Import nav
- UI polish: Inter font, design-system Tailwind primitives, header search, sidebar icons and API token footer, skeleton loading, progress bars
- PRODUCT.md and DESIGN.md design context for impeccable workflow
- Auto-process import jobs from the web app (background thread on enqueue; **Process now** HTMX fallback)
- First-run web setup at `/setup/` — creates the sole superuser when no users exist
- Dark mode: Light / Dark / System theme picker (localStorage), with `dark:` Tailwind variants across the web UI
- Background import jobs: PostgreSQL queue, import worker container, job status UI with HTMX polling
- Phase 0: Django project scaffolding with uv, PostgreSQL/SQLite support, DatabaseCache
- Phase 1: Core models (User, Book, Author, Genre, Shelf, Review, ReadingLog, ReadingProgress)
- Phase 2: Token authentication, API envelope, throttling, OpenAPI docs
- Phase 3: Books CRUD API with ISBN lookup (Open Library + Google Books), search/filter, soft delete/restore/trash
- Phase 4: Shelves, reviews, reading status/progress, stats endpoint with reading streak
- Phase 5–6: Web UI with Tailwind CDN + HTMX — dashboard, books, shelves, reviews, reading, trash, settings
- Phase 7: Import/export (ISBN list + Goodreads CSV), stats charts (Chart.js), API import/export endpoints
- Phase 8: Dockerfile (uv), docker-compose, `/healthz`, production security settings

### Changed
- Reading status labels: Not Started → Want to Read, Finished → Read (Goodreads-style naming)
- Docker Compose sets `IMPORT_JOB_AUTO_PROCESS=false` on the web service (dedicated `worker` container drains the queue)
- API `POST /api/v1/import/` now returns `202 Accepted` with a job id and status URL (poll `GET /api/v1/import/jobs/<id>/`)
- Goodreads CSV import skips external metadata lookups by default (`IMPORT_GOODREADS_ENRICH_METADATA=false`); ISBN imports are paced per Open Library rate limits
- Metadata `User-Agent` includes `OPENLIBRARY_CONTACT_EMAIL` when set (identified requests: 3 req/s)
- Metadata service: retry backoff, `Retry-After` on 429, split connect/read timeouts; transient failures are no longer cached for 30 days

## [0.1.0] - 2026-06-25

Initial MVP release — self-hosted book tracker with REST API and web UI.
