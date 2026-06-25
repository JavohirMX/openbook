# Implementation Plan — openbook

**Status:** Draft | **Owner:** John | **Last updated:** 2026-06-22

---

## 1. Build Philosophy

**Single-focus loop:** Plan → Build → Verify → Repeat

Each phase is completed and verified before moving to the next. No parallel feature building. This prevents the "spaghetti death spiral" — 5 half-working systems that break each other.

**Review cadence:** After each phase, we review and revise the remaining documents before proceeding.

---

## 2. Phases Overview

| Phase | Name | Dependencies | Est. Sessions |
|-------|------|-------------|:---:|
| **0** | Project Scaffolding | None | 1 |
| **1** | Core Models + Database | Phase 0 | 1-2 |
| **2** | Authentication | Phase 1 | 1 |
| **3** | API — Books CRUD | Phase 2 | 2 |
| **4** | API — Shelves + Reviews + Reading | Phase 3 | 2 |
| **5** | Frontend — Core UI + Books | Phase 3 (API exists) | 2-3 |
| **6** | Frontend — Shelves + Reviews + Reading | Phase 4 + 5 | 2 |
| **7** | Import + Stats + Polish | Phase 6 | 2 |
| **8** | Deployment + Docker | Phase 7 | 1 |

**Total estimate:** ~12-14 AI build sessions

---

## 3. Phase Details

### Phase 0 — Project Scaffolding

**Goal:** Get the project skeleton running locally

- [ ] Create Django project: `django-admin startproject openbook`
- [ ] Set up `settings.py` for PostgreSQL + local dev SQLite fallback
- [ ] Create `accounts` app (custom user) and `books` app
- [ ] Set up environment variables (`.env` file template)
- [ ] Configure `requirements.txt` with **pinned versions** (verify latest patch at build time): `Django==5.2.*` (LTS), `djangorestframework==3.17.*`, `psycopg[binary]==3.2.*`, `drf-spectacular==0.28.*`, `django-cors-headers==4.*`, `whitenoise==6.*`, `gunicorn`, `requests` (metadata clients)
- [ ] Configure Django **DB cache** (`DatabaseCache`) and run `createcachetable` (used by throttling + metadata lookup cache)
- [ ] Configure test tooling: `pytest`, `pytest-django`, `factory_boy` (dev requirements)
- [ ] Add **GitHub Actions** CI: run `pytest` (against a disposable Postgres) on every push/PR
- [ ] Verify: `python manage.py runserver` starts without errors; `pytest` runs (zero tests OK)
- [ ] Initialise Git repo
- [ ] Create `.gitignore`
- [ ] Add **MIT** `LICENSE`, `README.md` (overview + quickstart), and `CONTRIBUTING.md`
- [ ] Start a `CHANGELOG.md` (Keep a Changelog format); adopt SemVer (`0.1.0`)

**Gate:** Server starts, first migration runs, database connects, cache table created, `pytest` runs clean (locally + CI), license/README present

---

### Phase 1 — Core Models + Database

**Goal:** All database tables exist and migrations are clean

- [ ] Create custom User model in `accounts` (email-based auth, **no username**, `USERNAME_FIELD = "email"`)
- [ ] Create Author model
- [ ] Create Book model (ISBN uniqueness, `search_vector`, `deleted_at` soft-delete + default manager excluding trashed)
- [ ] Create BookAuthor junction model
- [ ] Create Genre model (+ `source`) + BookGenre junction model
- [ ] Create Shelf model (no `owner_id` — single user)
- [ ] Create BookshelfItem junction model
- [ ] Create Review model (one per book)
- [ ] Create ReadingLog model (one per book, current status)
- [ ] Create ReadingProgress model (per-day history for streak/charts)
- [ ] Add full-text search trigger/signal on Book
- [ ] Apply all migrations to PostgreSQL
- [ ] Create Django Admin registration for all models
- [ ] Write model/factory tests (constraints, uniqueness, cascades)
- [ ] **Verify:** `python manage.py check` passes, admin shows all models, `pytest` model tests pass, test data can be created via shell

**Gate:** All tables exist, admin panel functional, model tests pass, manual data entry works

---

### Phase 2 — Authentication

**Goal:** The single operator can log in / log out (web + API). No self-service registration.

- [ ] Configure DRF with TokenAuth
- [ ] Create login endpoint (POST `/api/v1/auth/login/`)
- [ ] Create logout endpoint (POST `/api/v1/auth/logout/`)
- [ ] Create session-based login for web (Django built-in); account created via `createsuperuser`
- [ ] Add token management to user profile (view/regenerate)
- [ ] Implement the custom DRF **renderer + pagination class + exception handler** for the `{data, meta}` / `{error}` envelope (TRD §4)
- [ ] Configure DRF **throttling** (per-token rate limit; `429` + `Retry-After`)
- [ ] Configure drf-spectacular (OpenAPI schema + Swagger UI)
- [ ] Write auth + envelope + throttling tests
- [ ] **Verify:** curl login → token works; invalid credentials return `401`; responses use the envelope; throttle returns `429`; `pytest` passes

**Gate:** Auth flow complete — web login + API token both work; envelope + throttling enforced; tests pass

---

### Phase 3 — API — Books CRUD

**Goal:** Full book CRUD via API

- [ ] Create BookSerializer (validate ISBN format, author + genre handling)
- [ ] Create BookViewSet (list, detail, create, update, partial_update, destroy)
- [ ] Implement search: full-text search on title/author, ISBN exact match
- [ ] Add filtering: by author, ISBN, shelf, **genre**, status (from reading log)
- [ ] Add pagination (20 per page) via the envelope pagination class from Phase 2
- [ ] Build metadata service + `GET /api/v1/books/lookup/?isbn=` endpoint — **Open Library primary, Google Books fallback** (descriptive User-Agent, ~5s timeout, 1 retry, ISBN-keyed cache, graceful fallback to manual; base URLs via `OPENLIBRARY_BASE_URL` / `GOOGLE_BOOKS_BASE_URL`)
- [ ] Hotlink cover image URL (Open Library size L→M, else Google Books thumbnail) on add/lookup
- [ ] Seed genres from Open Library subjects / Google Books categories (deduped, user-editable)
- [ ] ISBN checksum validation: accept-and-warn (non-blocking)
- [ ] Soft delete: `DELETE` sets `deleted_at`; add `restore` + `trash` endpoints; default queryset excludes trashed
- [ ] Confirm OpenAPI schema covers all book endpoints (drf-spectacular)
- [ ] Write CRUD + search + lookup tests (mock Open Library + Google Books HTTP), incl. soft delete → restore and ISBN accept-and-warn
- [ ] **Verify:** Full CRUD via curl — create, list, search, filter, ISBN lookup (OL + Google fallback), update, soft delete + restore; `pytest` passes

**Gate:** All book endpoints functional, search/filter return results, ISBN lookup works, pagination works, tests pass

---

### Phase 4 — API — Shelves, Reviews, Reading

**Goal:** Full CRUD for remaining features

**Shelves:**
- [ ] ShelfSerializer + ViewSet (CRUD)
- [ ] Add/remove book from shelf endpoints
- [ ] Shelves are custom tags only — **no auto-created default/system shelves** (status is owned by ReadingLog)

**Reviews:**
- [ ] ReviewSerializer + ViewSet (create/update/retrieve/destroy)
- [ ] One review per book (upsert)

**Reading:**
- [ ] ReadingLogSerializer + ViewSet (create/update/retrieve)
- [ ] Auto-create ReadingLog (status `not_started`) when a book is added
- [ ] Status lifecycle (not_started → reading → finished/paused/abandoned; finished → reading re-read) with `started_at`/`finished_at`/`read_count` side effects
- [ ] Progress tracking (percent complete; page optional) — each update writes a ReadingProgress entry

**Stats:**
- [ ] Stats endpoint: total books, completion rate, books by shelf, books by genre, books by status, monthly reads, pages read (period sums)
- [ ] Reading streak (consecutive local-tz days from ReadingProgress; uses `TIME_ZONE`)

- [ ] Write tests for shelves, reviews, reading, progress history, stats, and streak

**Gate:** All endpoints functional, stats return correct numbers (incl. streak), shelving a book works, tests pass

---

### Phase 5 — Frontend — Core UI

**Goal:** Base templates, navigation, book browsing — looking good

- [ ] Add Tailwind CSS via **CDN** (MVP); light theme, indigo accent, system font (see UI/UX §8)
- [ ] Set up base template (header, sidebar, content area)
- [ ] Create sidebar navigation component
- [ ] Dashboard page — currently reading cards, quick stats, recent additions
- [ ] Books list page — searchable, filterable (shelf/genre/status), paginated
- [ ] Book detail page — full metadata, cover, rating, shelves, genres, review, status
- [ ] Add/edit book page — form with validation, ISBN lookup (Open Library + Google Books fallback, pre-fill + manual fallback)
- [ ] Mobile slide-in drawer navigation
- [ ] **Verify:** Browse, search, add (via ISBN lookup + manual), edit books via web UI; drawer works on mobile

**Gate:** All book-related UI pages work end-to-end

---

### Phase 6 — Frontend — Shelves, Reviews, Reading

**Goal:** Complete the remaining UI

- [ ] Shelves list page
- [ ] Shelf detail page (books on shelf, remove from shelf)
- [ ] Create shelf inline form
- [ ] Add book to shelf modal
- [ ] Genre multi-select on add/edit book; genre tags on detail; genre filter on list
- [ ] Star rating component (clickable, interactive)
- [ ] Review form on book detail page
- [ ] Reading status controls (not started / reading / finished / paused / DNF)
- [ ] Progress input (inline edit — percent complete, page optional) — records a ReadingProgress entry
- [ ] Trash view — list soft-deleted books with Restore / Delete permanently
- [ ] Settings page (profile, timezone, API token, data export)
- [ ] **Verify:** Full workflow — add book → shelve → rate → review → track reading → delete → restore

**Gate:** Complete user journey works in browser

---

### Phase 7 — Import + Export + Stats + Polish

**Goal:** Import/export functionality and visual polish

- [ ] Import page — paste ISBNs textarea (enriched via Open Library where available)
- [ ] Import — CSV upload (Goodreads export format: parse, validate, preview, confirm; idempotent dedup on ISBN-13/10 then normalized title+author)
- [ ] Export — `GET /api/v1/export/?format=json` (full fidelity) + `?format=csv` (Goodreads-compatible)
- [ ] Export UI — buttons on Import/Export + Settings (file download)
- [ ] Stats page — total counts, charts (shelf + genre breakdown, monthly reads, streak) via Chart.js (CDN)
- [ ] Empty states for all pages (incl. first-run/empty-library onboarding)
- [ ] Error handling (user-friendly messages)
- [ ] Loading states (skeleton/spinner)
- [ ] Responsive layout pass (mobile-friendly)
- [ ] Write import/export tests, incl. **round-trip** (import → export → re-import is idempotent)
- [ ] **Verify:** Import 10+ books via CSV, export JSON + CSV, re-import the CSV with no duplicates, see stats update, test on mobile viewport

**Gate:** Import + export work (round-trip clean), stats show correct data, UI is polished, tests pass

---

### Phase 8 — Deployment + Docker

**Goal:** Running on books.javohirmx.com

- [ ] Create `Dockerfile` (multi-stage — collect static, run **Gunicorn** sync workers ~2×CPU+1)
- [ ] Create `docker-compose.yml` for production (Django app + depends on shared-db); add container `healthcheck` hitting `/healthz`
- [ ] Add `GET /healthz` view (app + DB connectivity, no auth)
- [ ] Configure environment variables per TRD §8 (`SECRET_KEY`, `DATABASE_URL`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `CORS_ALLOWED_ORIGINS`, `TIME_ZONE`, `OPENLIBRARY_BASE_URL`, throttle rates, `LOG_LEVEL`)
- [ ] Apply security settings (HSTS, SSL redirect, secure cookies, security headers) with `DEBUG=False`
- [ ] Add Traefik labels (matching existing homelab pattern)
- [ ] Configure CORS via `CORS_ALLOWED_ORIGINS` (restricted, not wildcard)
- [ ] Set up CSRF trusted origins
- [ ] Set up static file serving (Whitenoise)
- [ ] Configure structured logging to stdout (`LOG_LEVEL`)
- [ ] Deploy to homelab
- [ ] Smoke test: `/healthz` 200, visit `https://books.javohirmx.com`, add a book, API responds, `/api/v1/docs/` loads
- [ ] **Verify:** Full production deployment, external API access works, healthcheck green

- [ ] Tag the release (`v0.1.0`, SemVer) and update `CHANGELOG.md`; surface the version in the footer

**Deployment checklist (pre-go-live):** `DEBUG=False` · `SECRET_KEY` set · `ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS` pinned · HTTPS+HSTS on · secure cookies · CORS restricted · DB migrated · `createsuperuser` run · `pg_dump` backup verified · `/healthz` monitored externally.

**Gate:** Site live at books.javohirmx.com, API accessible from outside, healthcheck + monitoring in place

---

## 4. Testing Gates

```
Phase 0 ──→ Phase 1 ──→ Phase 2 ──→ Phase 3 ──→ Phase 4
                                              │
                                              ▼
                              Phase 5 ←── Phase 6 ←── Phase 7
                                              │
                                              ▼
                                          Phase 8
                                              │
                                              ▼
                                          🚀 LIVE
```

**Every phase must pass these checks before moving on:**

| Gate | Check |
|------|-------|
| ✅ No errors | `python manage.py check` passes zero errors |
| ✅ Migrations | All new migrations applied without conflict |
| ✅ Tests pass | `pytest` green; new code has unit/API tests (not just curl) |
| ✅ API works | curl-test each new endpoint (smoke) |
| ✅ No regressions | Previous phase's endpoints + tests still pass |
| ✅ Data integrity | No orphaned records, FK constraints hold |
| ✅ Git commit | Everything committed with clear message |

### Testing Strategy

- **Framework:** `pytest` + `pytest-django`; fixtures/factories via `factory_boy`.
- **Coverage focus:** model constraints (uniqueness, cascades), serializers/validation, API CRUD + auth + throttling + envelope shape, Open Library lookup (HTTP mocked), stats/streak math, CSV import idempotency.
- **External calls:** Open Library is always mocked in tests — no live network in the suite.
- **CI-ready:** the suite must run with a single `pytest` command against a disposable test DB.

---

## 5. Rollback Strategy

- **Per-phase Git tags:** After each phase passes, tag it: `git tag phase-0`, `phase-1`, etc.
- **Rollback:** `git checkout <tag>` + revert migrations = back to clean state
- **Migration revert:** `python manage.py migrate <app> <previous_migration>`
- **Database backup:** `pg_dump openbook > backup_phase_N.sql` before each phase with schema changes

---

## 6. Session Workflow

For each build session:

1. **Load context:** Read `AGENTS.md` + relevant phase doc
2. **Propose plan:** AI says "Here's my plan for Phase X"
3. **Get approval:** John says "Go" or adjusts
4. **Build one feature at a time:** Implement → test → commit → next
5. **Verify gate:** Run checklist
6. **Commit + tag**
7. **Report:** AI summarises what was built, what's next, any decisions made
