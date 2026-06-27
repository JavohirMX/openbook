# TRD — Technical Requirements Document

**Status:** Draft | **Owner:** John | **Last updated:** 2026-06-22

---

## 1. Tech Stack

Single-user, self-hosted deployment (one account per instance — see PRD §2).

| Layer | Choice | Rationale |
|-------|--------|-----------|
| **Backend + Frontend** | Python Django | John's preference. Django's batteries-included approach gives us ORM, admin panel, forms, auth, and template rendering out of the box |
| **Database** | PostgreSQL | Recommended. Already running in John's homelab (`shared-db`), production-grade, full-text search, JSON fields for flexible metadata, concurrent API access |
| **API** | Django REST Framework (DRF) | Battle-tested REST API framework; auto-generates docs, filters, pagination |
| **API docs** | drf-spectacular | OpenAPI 3 schema + Swagger UI for agent-friendly, machine-readable API docs |
| **Frontend** | Django Templates + HTMX + Tailwind CSS | No SPA complexity. HTMX gives modern interactivity without a JS framework. Tailwind for consistent, rapid UI |
| **Auth** | Custom email-login user model (`AbstractUser`, `USERNAME_FIELD = email`, no username) | Session-based for web, token-based (DRF Tokens) for API. **No open registration** — the single account is created by the operator via `createsuperuser` / admin |
| **Book metadata** | Open Library (primary) + Google Books (fallback), both no API key | ISBN lookup + cover images for Add Book and Import. Google Books is queried when Open Library misses. Manual entry always available |
| **App server** | Gunicorn (sync workers, ~2×CPU+1) | Production WSGI server; static via Whitenoise |
| **Cache** | PostgreSQL database cache (Django `DatabaseCache`) | Shared across Gunicorn workers (needed for correct throttling + metadata lookup cache) without adding Redis. Migrate to Redis only if needed |
| **Containerisation** | Docker | Single container for dev + production. Fits John's existing homelab (Traefik, Cloudflare Tunnel) |
| **Task Queue** | None for MVP | Keep it simple. CSV import can run synchronously (small collections) |
| **Search** | PostgreSQL full-text search (`search_vector`) | Good enough for MVP. No need for Elasticsearch/Meilisearch yet |

### Pinned versions

Pin in `requirements.txt`. Versions reflect current stable as of this revision (2026-06); verify the latest patch release at build time.

| Package | Version | Notes |
|---------|---------|-------|
| Python | 3.11+ | Matches homelab system Python; DRF supports 3.10+ |
| Django | 5.2.x LTS | LTS, extended support to April 2028 (6.0 is current non-LTS) |
| djangorestframework | 3.17.x | Latest stable; supports Django 5.2 / 6.0 |
| psycopg[binary] | 3.2.x | PostgreSQL driver (psycopg 3) |
| drf-spectacular | 0.28.x | OpenAPI schema generation |
| django-cors-headers | 4.x | CORS for API access |
| whitenoise | 6.x | Static file serving in the container |
| gunicorn | latest | Production WSGI server |
| requests / httpx | latest | Open Library / Google Books HTTP client |

## 2. Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| API response time (standard queries) | <200ms P95 |
| API response time (search) | <500ms P95 |
| Page load time (first paint) | <1.5s |
| Concurrent API users | Support 10+ simultaneous agent requests |
| Data durability | All writes are transactional, idempotent where possible |
| API throttling | DRF throttling enabled (e.g. 1000/day per token, configurable). Exceeding limits returns `429` with a `Retry-After` header (see AppFlow §3) |
| Backup | Database can be backed up via standard pg_dump |
| Deployment | Single `docker compose up` with env vars |

## 3. System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Cloudflare Tunnel                      │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                      Traefik                              │
│       books.javohirmx.com → openbook:8000                 │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│               openbook (Django container)                 │
│  ┌───────────────────────────────────────────────────┐   │
│  │  Django App — two HTTP surfaces                     │   │
│  │                                                   │   │
│  │  Web surface              API surface             │   │
│  │  ┌────────────────┐       ┌────────────────┐      │   │
│  │  │ Django views   │       │ /api/v1/* DRF  │      │   │
│  │  │ + HTMX partials│       │ JSON (REST)    │      │   │
│  │  │ session + CSRF │       │ token + envelope│     │   │
│  │  └────────────────┘       └────────────────┘      │   │
│  │            ┌────────────────┐                     │   │
│  │            │ Admin (Django) │                     │   │
│  │            └────────────────┘                     │   │
│  │  ┌───────────────────────────────────────────┐    │   │
│  │  │ Shared service layer + Django ORM         │    │   │
│  │  └───────────────────────────────────────────┘    │   │
│  └───────────────────────────────────────────────────┘   │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│              PostgreSQL (shared-db)                       │
│              Database: openbook                            │
└─────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Human user (web surface)** — browser → Cloudflare → Traefik → Django **server-rendered views + HTMX partials**. Auth is **Django session + CSRF** (HTMX sends the CSRF token via `hx-headers`). The web surface does **not** use the API token or the JSON envelope.
2. **AI agent (API surface)** — API call → Cloudflare → Traefik → Django **DRF JSON** under `/api/v1/*`. Auth is **token-based**; responses use the `{data, meta}` / `{error}` envelope; throttling applies here.
3. **Import/Export** — web upload/download or API; same shared service layer → PostgreSQL.

> **Two surfaces, one core:** Web (HTML) and API (JSON) are distinct entrypoints over a **shared service/ORM layer** so behaviour stays in parity (PRD principle: API-first). Envelope, token auth, and throttling are scoped to `/api/*`; sessions, CSRF, and Django messages are scoped to the web surface.

## 4. API Specifications

Base URL: `https://books.javohirmx.com/api/v1/`

### Authentication

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/auth/login/` | POST | Login (email + password), returns token |
| `/api/v1/auth/logout/` | POST | Invalidate token |

Auth: Token-based (DRF TokenAuth). Token sent as `Authorization: Token <key>` header.

> **Single-user model:** There is **no `register` endpoint**. The sole account is provisioned by the operator via `python manage.py createsuperuser` (or the Django admin). `login` returns the API token; the token can be viewed/regenerated from the Settings screen.

### Core Endpoints

| Endpoint                       | Method | Description                                                      |
| ------------------------------ | ------ | ---------------------------------------------------------------- |
| `/api/v1/books/`               | GET    | List/search/filter books. Supports `?search=` (full-text), `?author=`, `?isbn=`, `?shelf=`, `?genre=`, `?status=` |
| `/api/v1/books/`               | POST   | Add a new book (requires ISBN or title+author)                   |
| `/api/v1/books/{id}/`          | GET    | Book detail with all metadata                                    |
| `/api/v1/books/{id}/`          | PATCH  | Update book metadata                                             |
| `/api/v1/books/{id}/`          | DELETE | **Soft delete** — move book to Trash (recoverable). Pass `?permanent=true` to hard-delete |
| `/api/v1/books/{id}/restore/`  | POST   | Restore a soft-deleted book from Trash                           |
| `/api/v1/books/trash/`         | GET    | List soft-deleted books                                          |
| `/api/v1/books/lookup/`        | GET    | Look up bibliographic metadata by ISBN via Open Library (`?isbn=`). Returns un-saved metadata to pre-fill Add Book; does not create a record |
| `/api/v1/shelves/`             | GET    | List user's custom shelves                                       |
| `/api/v1/shelves/`             | POST   | Create a new shelf                                               |
| `/api/v1/shelves/{id}/`        | GET    | Shelf detail + books on it                                       |
| `/api/v1/shelves/{id}/`        | PATCH  | Rename/update shelf                                              |
| `/api/v1/shelves/{id}/`        | DELETE | Remove shelf (doesn't delete books)                              |
| `/api/v1/books/{id}/shelve/`   | POST   | Add book to a shelf (`{"shelf_id": 1}`)                          |
| `/api/v1/books/{id}/unshelve/` | POST   | Remove book from a shelf                                         |
| `/api/v1/books/{id}/review/`   | GET    | Get review/notes for a book                                      |
| `/api/v1/books/{id}/review/`   | PUT    | Create or update review                                          |
| `/api/v1/books/{id}/review/`   | DELETE | Remove review                                                    |
| `/api/v1/books/{id}/reading/`  | GET    | Get reading status (not_started/reading/finished/paused/abandoned) + progress |
| `/api/v1/books/{id}/reading/`  | PUT    | Update reading status/progress                                   |
| `/api/v1/stats/`               | GET    | Get reading stats (total books, completion rate, pages, shelf/genre breakdown, monthly reads, streak) |
| `/api/v1/import/`              | POST   | Import books via JSON array of ISBNs or CSV upload (idempotent — see Import/Export spec) |
| `/api/v1/export/`             | GET    | Export the entire collection. `?format=json` (full fidelity) or `?format=csv` (Goodreads-compatible). Returns a file download |

### Response Format

The envelope below applies to the **API surface (`/api/v1/*`)** only — the server-rendered web surface returns HTML. DRF's default response/pagination shape differs from this envelope, so openbook ships a **custom DRF renderer + pagination class** (and a custom exception handler) to produce a consistent envelope across every API endpoint. This is an explicit build task (see Implementation Plan Phase 2).

All success responses follow:

```json
{
  "data": { ... },
  "meta": {
    "page": 1,
    "total": 42,
    "per_page": 20
  }
}
```

`meta` is present on paginated/list responses; for single-object responses `meta` may be omitted or minimal.

Errors:

```json
{
  "error": {
    "code": "not_found",
    "message": "Book not found",
    "details": null
  }
}
```

`details` is optional and carries field-level validation info (e.g. `{ "isbn_13": ["Invalid checksum"] }`).

### Error Catalog

| HTTP | `error.code` | When |
|-----:|--------------|------|
| 400 | `validation_error` | Malformed body / failed field validation (`details` populated) |
| 401 | `unauthorized` | Missing/invalid token (API) |
| 403 | `permission_denied` | Authenticated but not permitted |
| 404 | `not_found` | Resource does not exist |
| 409 | `duplicate_isbn` | Creating a book whose ISBN already exists |
| 413 | `payload_too_large` | Upload exceeds the import size limit |
| 422 | `unprocessable` | Semantically invalid (e.g. bad status transition) |
| 429 | `throttled` | Rate limit exceeded (`Retry-After` header set) |
| 500 | `server_error` | Unexpected failure (details suppressed in prod) |

### Query Parameters (list endpoints)

| Param | Applies to | Notes |
|-------|------------|-------|
| `search` | `/books/` | Full-text (title/author) + ISBN exact match |
| `author`, `isbn`, `shelf`, `genre` | `/books/` | Exact filters |
| `status` | `/books/` | Resolved via join to `ReadingLog.status` (e.g. `?status=reading`) |
| `ordering` | list endpoints | e.g. `title`, `-created_at`, `-finished_at`; default `-created_at` |
| `page` | list endpoints | 1-based page number |
| `per_page` | list endpoints | Default 20, **max 100** |

### API Discovery & Token Lifetime

- **OpenAPI schema:** `GET /api/v1/schema/` (drf-spectacular).
- **Swagger UI:** `GET /api/v1/docs/`.
- **Single token:** one API token for the account (DRF `TokenAuthentication`), shared by all agents. Tokens do **not** expire; rotate by regenerating from Settings (old token is invalidated). Multiple named per-agent tokens are post-MVP.

### Validation & Search Behaviour

- **ISBN validation:** validate ISBN-10/13 **checksums on a best-effort basis** — on failure, **accept the value but surface a non-blocking warning** (the data still saves). This keeps messy real-world/Goodreads data importable while flagging likely typos.
- **Search ranking:** full-text search uses a weighted `search_vector` (title weighted above author/publisher) ranked by `ts_rank`; a trigram similarity match on `title` provides fuzzy fallback. Exact ISBN matches short-circuit to the top.

### Throttling

- **Default scope:** ~1000 requests/day per token (configurable via `API_THROTTLE_RATES`).
- **Auth scope:** ~5/min on login (web + API) to deter brute force.
- Exceeding either returns `429 throttled` with a `Retry-After` header.
- Throttle counters use the shared **DB cache** so limits hold across Gunicorn workers.

### Import / Export Specification

**Idempotency / dedup (import):** a book is considered a duplicate if it matches an existing one by, in order: (1) `isbn_13`, (2) `isbn_10`, else (3) a normalized key of `(title, primary_author)` — lowercased, accents stripped, punctuation/whitespace collapsed. Duplicates are **skipped** (never updated/duplicated) and counted in the import result `{added, skipped, failed}`.

**Author dedup:** authors are matched/reused by a normalized name (lowercased, punctuation stripped, whitespace collapsed) so "J.K. Rowling" and "JK Rowling" resolve to one `Author` row.

**Direct create conflict:** `POST /api/v1/books/` with an ISBN that already exists returns **`409 duplicate_isbn`** (with the existing book id in `details`) rather than creating a second record.

**Goodreads CSV column mapping** (import reads these; CSV export writes them back for round-trip):

| Goodreads column | openbook target |
|------------------|-----------------|
| `Title` | `book.title` |
| `Author` / `Additional Authors` | `Author` + `BookAuthor` (position/role) |
| `ISBN13` / `ISBN` | `book.isbn_13` / `book.isbn_10` (de-quoted from `="..."`) |
| `Number of Pages` | `book.pages` |
| `Year Published` / `Original Publication Year` | `book.published_year` |
| `Publisher` | `book.publisher` |
| `My Rating` (0 = unrated) | `review.rating` (0 → null) |
| `My Review` | `review.review_text` |
| `Exclusive Shelf` (`read` / `currently-reading` / `to-read`) | `ReadingLog.status` (`finished` / `reading` / `not_started`) |
| `Bookshelves` | `Shelf` tags (excluding the three exclusive-shelf names) |
| `Date Read` | `ReadingLog.finished_at` |
| `Date Added` | `book.created_at` |

Unmapped Goodreads columns are ignored. Covers/descriptions absent from the CSV are backfilled via Open Library when an ISBN is present.

## 5. Tradeoff Justifications

| Decision | Alternative | Why |
|----------|-------------|-----|
| Django (monolith) | FastAPI + React SPA | Simpler deployment, fewer moving parts, John's preference. HTMX provides modern UX without two codebases |
| PostgreSQL full-text search | Elasticsearch/Meilisearch | For a personal collection (<10k books), PostgreSQL search is sufficient. No extra service to deploy |
| DRF TokenAuth | JWT | Simpler for MVP. Can migrate to JWT or session+token dual auth later |
| No task queue | Celery/Redis | Import volumes are small (hundreds, not millions). Sync import is simpler. Add queue later if needed |

## 6. Dependencies & Constraints

- **Container runtime:** Docker (compatible with existing homelab)
- **Dependency on shared-db:** openbook needs its own database on the shared PostgreSQL instance
- **Deployment domain:** `books.javohirmx.com` (already configured in Traefik + Cloudflare)
- **Network:** Must be on the `web` network in the homelab Docker stack
- **Python:** 3.11+ (matches system Python)
- **Book metadata source:** Open Library API (`https://openlibrary.org`) as **primary** and Google Books (`https://www.googleapis.com/books/v1`) as **fallback** — **no API key required** for either. Used for ISBN lookup and cover images. Manual entry and CSV import remain fully supported and work offline.
- **Outbound network:** the container needs outbound HTTPS to `openlibrary.org`, `covers.openlibrary.org`, and `www.googleapis.com` for metadata/cover lookups (graceful degradation to manual entry if unreachable).

### Book Metadata Integration (Open Library + Google Books)

| Concern | Spec |
|---------|------|
| **Primary endpoint** | `GET https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&format=json&jscmd=data` (returns title, authors, number_of_pages, publishers, publish_date, subjects, cover URLs) |
| **Fallback endpoint** | If Open Library misses, `GET https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}` (no key); map `volumeInfo` (title, authors, pageCount, publishedDate, categories→genres, imageLinks→cover) |
| **Cover images** | Open Library: `https://covers.openlibrary.org/b/isbn/{isbn}-{S|M|L}.jpg` (prefer **L**, fall back **M**); Google Books: `imageLinks.thumbnail`. Store the source URL in `book.cover_url`, **download** the image to `media/covers/{book_id}.{ext}`, and serve same-origin via `GET /media/covers/...`. Fall back to `cover_url` hotlink only if download fails |
| **User-Agent** | Send a descriptive `User-Agent` (e.g. `openbook/<version> (+https://books.javohirmx.com)`) per Open Library etiquette |
| **Timeout** | ~5s connect+read timeout; treat timeouts as a miss |
| **Retry** | At most 1 retry with short backoff; never block the request indefinitely |
| **Caching** | Cache lookups in the shared Django DB cache, keyed by ISBN, TTL ~30 days, to avoid repeat calls during bulk import |
| **Multiple authors/works** | Map all returned authors to `Author` + `BookAuthor` with `position`; first author is primary |
| **Subjects → genres** | Map Open Library `subjects` to `Genre` (deduped by slug, `source = open_library`); cap to a sensible number; remain user-editable |
| **Fallback chain** | Open Library → Google Books (when needed) → Wikidata (when needed) → empty (manual entry). Default `METADATA_LOOKUP_STRATEGY=chain`; set `parallel` for legacy merge-all. On miss/error/network failure at the end of the chain, return empty and let the user enter data manually; import continues using only CSV/ISBN data |
| **Config** | Base URLs overridable via `OPENLIBRARY_BASE_URL` and `GOOGLE_BOOKS_BASE_URL` (eases testing/mocking) |

## 7. Security & Privacy

Single-user and self-hosted, but still hardened by default:

| Area | Requirement |
|------|-------------|
| **Transport** | HTTPS only (terminated at Cloudflare/Traefik). Enable HSTS (`SECURE_HSTS_SECONDS`), `SECURE_SSL_REDIRECT`, and `SECURE_PROXY_SSL_HEADER` for the proxy |
| **Security headers** | `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, referrer policy, and a Content-Security-Policy. Because the MVP uses CDNs, allow: `script-src` + `style-src` `https://cdn.tailwindcss.com` and `https://cdn.jsdelivr.net` (Chart.js); `img-src 'self' data:`; `connect-src 'self'`. Tighten (drop CDNs) when Tailwind moves to a compiled build |
| **Cookies** | `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SESSION_COOKIE_HTTPONLY`, `SameSite=Lax` |
| **CSRF** | Web surface uses Django CSRF; set `CSRF_TRUSTED_ORIGINS` to `https://books.javohirmx.com`. HTMX posts include the CSRF token via `hx-headers` |
| **Login brute-force** | Dedicated throttle scope on `/api/v1/auth/login/` and the web login (e.g. 5/min/IP) → `429` |
| **API auth** | Token in `Authorization: Token` header; tokens are non-expiring and rotatable from Settings (rotation invalidates the old token) |
| **Admin** | Django admin at `/admin/`, superuser-only (the single account); not linked from the public UI |
| **Sessions** | Expire on browser close; no "remember me" in MVP |
| **Secrets** | `SECRET_KEY`, DB credentials, etc. supplied via environment only; never committed. `DEBUG=False` and pinned `ALLOWED_HOSTS` in production |
| **Passwords** | Django's default PBKDF2 hashing. **Password reset** (single-user) is via `python manage.py changepassword` or the admin — there is no email-based reset flow in MVP |
| **CORS** | `django-cors-headers` restricted via `CORS_ALLOWED_ORIGINS` (not wildcard in production) for the API surface |
| **Privacy** | No telemetry, no third-party trackers, no outbound calls except Open Library metadata/cover lookups |

## 8. Observability & Operations

| Area | Requirement |
|------|-------------|
| **Health check** | `GET /healthz` — returns 200 with app + DB connectivity status (no auth); used by uptime monitoring and container healthcheck |
| **Metrics measurement** | The PRD targets (latency P95, 99.9% uptime) are measured by **external monitoring** hitting `/healthz` + request-timing logs — not self-reported by the app |
| **Logging** | Structured logs to stdout (captured by Docker). Request/error logging with level via `LOG_LEVEL`. No PII beyond the single account |
| **Backup/restore** | DB via `pg_dump` / `pg_restore`, run on a **nightly cron** in the homelab (retain ~14 daily snapshots); full logical export also available via `/api/v1/export/?format=json`. Cover images are stored under `media/covers/` on the `openbook_media` volume (~100–200 KB per book) |

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `SECRET_KEY` | Django secret (required) |
| `DATABASE_URL` | PostgreSQL connection string to the `openbook` DB on `shared-db` |
| `DEBUG` | `False` in production |
| `ALLOWED_HOSTS` | e.g. `books.javohirmx.com` |
| `CSRF_TRUSTED_ORIGINS` | e.g. `https://books.javohirmx.com` |
| `CORS_ALLOWED_ORIGINS` | Permitted API origins |
| `TIME_ZONE` | Local timezone for reading-day boundaries / streaks (default `Asia/Tashkent`) |
| `OPENLIBRARY_BASE_URL` | Override Open Library base URL (default `https://openlibrary.org`) |
| `GOOGLE_BOOKS_BASE_URL` | Override Google Books base URL (default `https://www.googleapis.com/books/v1`) |
| `API_THROTTLE_RATES` | Throttle config (default + auth scopes) |
| `LOG_LEVEL` | Logging verbosity (default `INFO`) |
