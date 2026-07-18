# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Metadata lookups use a conditional provider chain by default (`METADATA_LOOKUP_STRATEGY=chain`): Open Library first; Google Books and Wikidata only when needed. Import uses a strict chain; interactive lookups may still call Google Books for missing description, year, or publisher. Set `METADATA_LOOKUP_STRATEGY=parallel` for legacy merge-all behavior.

### Added

- Book detail **Find online** section with always-visible provider buttons (catalog/store links plus Project Gutenberg and Internet Archive search); links built in `books/provider_links.py` and exposed via `GET /api/v1/books/{id}/provider-links/`.
- Manual book cover upload on Add/Edit Book forms (with preview), clickable empty-cover affordance on book detail, cover removal, auto-lock of `cover_url` after upload, and REST API multipart upload via `cover_image` / `clear_cover`.

#### Batch 9 — UX roadmap (audit implementation)
- Reading goals UI in Settings; dashboard goal CTA and streak display
- Reading Log journal with date picker and month navigation for finishes
- Stats reading activity heatmap; custom time period filter (YTD, 90d, custom range)
- Rating distribution, format breakdown, DNF analytics, and reading speed on Stats
- Richer year-in-review page with print summary and cover collage
- Library Tools health metric deep links; author merge; scoped cover backfill
- EPUB/OPF metadata import on add book; barcode ISBN scan (where supported)
- Author Wikipedia enrichment; metadata field locks on book detail
- Series index page; saved filter presets; table book layout; custom book tags
- Rule-based “More by author / same genre” suggestions on book detail; agent rec docs
- Mobile header live search parity; authors pagination; clear review button

- Multi-source metadata pipeline: per-field merge across Open Library, Google Books, and Wikidata
- Title/author search fallback for books missing ISBN; semi-automatic match review queue on **Library Tools**
- Book detail **Refresh metadata** overwrites cover, pages, publisher, year, authors, genres, description, ISBN, and provider IDs
- `MetadataMatchProposal` model and Library Tools apply/reject/alternate actions
- Goodreads CSV import: `Date Read`, `Date Added`, and `Additional Authors` columns with round-trip export support
- Metadata backfill jobs (web + API) for books missing cover, pages, or other fields
- `export_library` management command for JSON/CSV snapshots

#### Batch 4 — Series, genres & contributor roles
- `Series` model with slug, sort order, and book `series_position`
- Series API (`/api/v1/series/`) and web detail pages; series filter on books list
- Goodreads CSV `Series` / `#` column import
- Genre management API: rename, merge, delete with reassignment
- Genre name normalization (`Science Fiction` canonical casing)
- Author contributor roles on add/edit book: translator, editor, illustrator

#### Batch 5 — Webhooks, bulk actions & maintenance
- Webhook endpoints API with HMAC-SHA256 signatures and retry delivery
- Events: `reading.status_changed`, `import.completed`
- Duplicate book detection and merge on **Library Tools**
- Books list bulk actions: soft delete, set reading status, add to shelf
- Import metadata backfill API (`POST /api/v1/import/backfill/`)

#### Batch 6 — Search, format, notes & shortcuts
- Full-text search across review text, quotes, and private notes (web + API)
- Book `format` (print, ebook, audiobook), `owned`, and `narrator` fields
- Private per-book notes (web form + API upsert/delete)
- Keyboard shortcuts (`g b` books, `g s` stats, `/` focus search) with Settings documentation

#### Batch 7 — Tokens, public profile, OPDS & StoryGraph
- Named API tokens: create, revoke, and `last_used_at` tracking in Settings
- Public reading profile page (`/profile/`, `/p/`) with embed key
- OPDS catalog feed (`/opds/`) authenticated via API token or embed key
- StoryGraph CSV import with auto-detection, preview, and job queue support

#### Batch 8 — Polish
- Drag-and-drop custom shelf reorder on Shelves page (SortableJS + HTMX POST)
- Toast-style flash notifications with `aria-live` region (replaces inline banners)
- PRD, UI/UX, and implementation-plan doc reconciliation

#### Earlier MVP (Phases 0–8)
- Reading form: `pages_read` and `note` on web UI; `read_count`, `started_at`, `finished_at` on book detail
- Settings: change password, direct JSON/CSV export links, `published_date` on book form
- Web export routes: `/export/json/` and `/export/csv/`
- Dedicated Reading Log page at `/reading/`
- Genre hub at `/genres/` with sidebar navigation
- Paused and DNF virtual status shelves
- Shelf edit UI with color and sort order fields
- Live debounced header search (HTMX)
- Authors link in sidebar navigation
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
- Reading goals and year-in-review stats page
- First-run web setup at `/setup/` — creates the sole superuser when no users exist
- Background import jobs: PostgreSQL queue, import worker container, job status UI with HTMX polling
- Dockerfile (uv), docker-compose, `/healthz`, production security settings

### Changed

#### Batch 3
- Goodreads CSV imports enrich metadata by default (`IMPORT_GOODREADS_ENRICH_METADATA=true`); rows without ISBN use title+author lookup
- Metadata backfill includes books without ISBN when title and author are present; uncertain matches queue for review
- Metadata `User-Agent` includes `OPENLIBRARY_CONTACT_EMAIL` when set (identified requests: 3 req/s)
- Metadata service: retry backoff, `Retry-After` on 429, split connect/read timeouts; transient failures are no longer cached for 30 days

#### Batches 4–8 & MVP polish
- Stats charts use a 12-color categorical palette (theme-aware light/dark variants); UI chrome remains monochrome editorial
- Contributor, operations, API consumer, and import pipeline documentation (`docs/07`–`10`, `docs/README.md`)
- Full UI/UX pass: touch targets (44px), consistent empty states, destructive `.btn-destructive`
- Dashboard and stats use metrics strip instead of stat card grid
- Book detail: single-surface editorial layout with section dividers
- Books list: labeled filters, mobile cover thumbnails, pagination a11y, bulk action bar
- Login/setup unified via `auth_layout.html`; password show/hide toggle
- Shelves, trash, import/export polish; chart screen-reader summaries
- Sidebar refactored to `nav_item` component; import job detail highlights Import nav
- UI polish: IBM Plex Sans + Newsreader typography, design-system Tailwind primitives, header search, sidebar icons and API token footer, skeleton loading, progress bars
- PRODUCT.md and DESIGN.md design context
- Auto-process import jobs from the web app (background thread on enqueue; **Process now** HTMX fallback)
- Dark mode: Light / Dark / System theme picker (localStorage), with `dark:` Tailwind variants across the web UI
- Reading status labels: Not Started → Want to Read, Finished → Read (Goodreads-style naming)
- Docker Compose sets `IMPORT_JOB_AUTO_PROCESS=false` on the web service (dedicated `worker` container drains the queue)
- API `POST /api/v1/import/` now returns `202 Accepted` with a job id and status URL (poll `GET /api/v1/import/jobs/<id>/`)

## [0.1.0] - 2026-06-25

Initial MVP release — self-hosted book tracker with REST API and web UI.
