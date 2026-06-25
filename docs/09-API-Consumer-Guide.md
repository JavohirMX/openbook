# API Consumer Guide — openbook

**Status:** Living doc | **Last updated:** 2026-06-25

---

Practical guide for scripts, home automation, and AI agents integrating with openbook. For the **canonical endpoint reference**, see [TRD §4](02-TRD-Technical-Requirements-Document.md). For interactive exploration, use `/api/v1/docs/` on a running instance.

Base URL examples below use `http://127.0.0.1:8000` — replace with your instance hostname.

---

## 1. Getting started

### Obtain an API token

**Option A — Login endpoint:**

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "your-password"}'
```

Response:
```json
{
  "data": {
    "token": "9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b"
  }
}
```

**Option B — Settings UI:** Log in to the web UI → **Settings** (`/settings/`) → copy the API token.

### Single-user model

There is **no registration endpoint**. The sole account is created at `/setup/` or via `createsuperuser`. All API data belongs to that one operator.

---

## 2. Authentication

Include the token on every authenticated request:

```
Authorization: Token 9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b
```

**Logout** (invalidates the current token):

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/logout/ \
  -H "Authorization: Token YOUR_TOKEN"
```

Response: `{"data": null}`

---

## 3. Response envelope

All `/api/v1/*` responses use a consistent envelope (not plain DRF defaults).

### Success — single object

```json
{
  "data": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "title": "Dune",
    "isbn_13": "9780441172719"
  }
}
```

### Success — paginated list

```json
{
  "data": [
    {"id": "...", "title": "Book One"},
    {"id": "...", "title": "Book Two"}
  ],
  "meta": {
    "page": 1,
    "total": 42,
    "per_page": 20
  }
}
```

### Error

```json
{
  "error": {
    "code": "unauthorized",
    "message": "Invalid email or password.",
    "details": null
  }
}
```

Validation errors include field details:

```json
{
  "error": {
    "code": "validation_error",
    "message": "isbn: Invalid ISBN format.",
    "details": {
      "isbn": ["Invalid ISBN format."]
    }
  }
}
```

Full error catalog: [TRD §4 Error Catalog](02-TRD-Technical-Requirements-Document.md).

---

## 4. Pagination and filtering

### Pagination

| Param | Default | Max | Description |
|-------|---------|-----|-------------|
| `page` | 1 | — | 1-based page number |
| `per_page` | 20 | 100 | Items per page |

```bash
curl -s "http://127.0.0.1:8000/api/v1/books/?page=2&per_page=10" \
  -H "Authorization: Token YOUR_TOKEN"
```

### Books list filters

| Param | Example | Description |
|-------|---------|-------------|
| `search` | `?search=dune` | Full-text title/author search |
| `author` | `?author=Herbert` | Filter by author name |
| `genre` | `?genre=fantasy` | Filter by genre slug |
| `shelf` | `?shelf=favorites` | Filter by custom shelf slug |
| `status` | `?status=reading` | `not_started`, `reading`, `finished`, `paused`, `abandoned` |
| `rating` | `?rating=5` | Filter by your rating (1–5) |
| `ordering` | `?ordering=-created_at` | Sort field; prefix `-` for descending |

```bash
curl -s "http://127.0.0.1:8000/api/v1/books/?status=reading&ordering=title" \
  -H "Authorization: Token YOUR_TOKEN"
```

---

## 5. Common workflows

Set `TOKEN` once for the examples below:

```bash
TOKEN="your-token-here"
BASE="http://127.0.0.1:8000/api/v1"
```

### 5.1 List your library

```bash
curl -s "$BASE/books/" -H "Authorization: Token $TOKEN"
```

### 5.2 Look up metadata by ISBN (does not create a book)

```bash
curl -s "$BASE/books/lookup/?isbn=9780441172719" \
  -H "Authorization: Token $TOKEN"
```

Returns bibliographic metadata to pre-fill an add-book form. No database record is created.

### 5.3 Search metadata by title or author

```bash
curl -s "$BASE/books/search-metadata/?q=dune&limit=5" \
  -H "Authorization: Token $TOKEN"
```

### 5.4 Add a book

```bash
curl -s -X POST "$BASE/books/" \
  -H "Authorization: Token $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Dune",
    "isbn_13": "9780441172719",
    "author_names": ["Frank Herbert"],
    "pages": 688
  }'
```

Save the returned `data.id` for subsequent steps.

### 5.5 Update reading status

```bash
BOOK_ID="550e8400-e29b-41d4-a716-446655440000"

curl -s -X PUT "$BASE/books/$BOOK_ID/reading/" \
  -H "Authorization: Token $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "status": "reading",
    "progress_percent": 25,
    "current_page": 150
  }'
```

Mark finished:

```bash
curl -s -X PUT "$BASE/books/$BOOK_ID/reading/" \
  -H "Authorization: Token $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status": "finished"}'
```

### 5.6 Reading history

```bash
curl -s "$BASE/books/$BOOK_ID/reading/history/" \
  -H "Authorization: Token $TOKEN"
```

Returns status changes and progress snapshots.

### 5.7 Add to a custom shelf

List shelves to get an ID:

```bash
curl -s "$BASE/shelves/" -H "Authorization: Token $TOKEN"
```

Shelve a book:

```bash
curl -s -X POST "$BASE/books/$BOOK_ID/shelve/" \
  -H "Authorization: Token $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"shelf_id": 1}'
```

### 5.8 Write a review

```bash
curl -s -X PUT "$BASE/books/$BOOK_ID/review/" \
  -H "Authorization: Token $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "rating": 5,
    "body": "A masterpiece of science fiction."
  }'
```

### 5.9 Soft delete and restore

Soft delete (move to trash):

```bash
curl -s -X DELETE "$BASE/books/$BOOK_ID/" \
  -H "Authorization: Token $TOKEN"
```

List trashed books:

```bash
curl -s "$BASE/books/trash/" -H "Authorization: Token $TOKEN"
```

Restore:

```bash
curl -s -X POST "$BASE/books/$BOOK_ID/restore/" \
  -H "Authorization: Token $TOKEN"
```

Permanent delete:

```bash
curl -s -X DELETE "$BASE/books/$BOOK_ID/?permanent=true" \
  -H "Authorization: Token $TOKEN"
```

### 5.10 Get reading stats

```bash
curl -s "$BASE/stats/" -H "Authorization: Token $TOKEN"
```

---

## 6. Import and export via API

Import jobs run asynchronously. Poll job status until `completed` or `failed`. See [10-Import-and-Metadata-Pipeline.md](10-Import-and-Metadata-Pipeline.md) for details.

### Import ISBN list

```bash
curl -s -X POST "$BASE/import/" \
  -H "Authorization: Token $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"isbns": ["9780141439518", "9780143127550"]}'
```

Response (202 Accepted):
```json
{
  "data": {
    "id": "job-uuid-here",
    "kind": "isbns",
    "status": "pending",
    "progress_done": 0,
    "progress_total": 2,
    "status_url": "http://127.0.0.1:8000/api/v1/import/jobs/job-uuid-here/"
  }
}
```

### Poll job status

```bash
JOB_ID="job-uuid-here"

curl -s "$BASE/import/jobs/$JOB_ID/" \
  -H "Authorization: Token $TOKEN"
```

Completed job example:
```json
{
  "data": {
    "status": "completed",
    "progress_done": 2,
    "progress_total": 2,
    "result": {
      "added": 1,
      "skipped": 1,
      "failed": 0,
      "errors": []
    }
  }
}
```

### Import Goodreads CSV

**Step 1 — Upload for preview:**

```bash
curl -s -X POST "$BASE/import/" \
  -H "Authorization: Token $TOKEN" \
  -F "file=@goodreads_export.csv"
```

Status will be `awaiting_confirmation` with a `preview` array.

**Step 2 — Confirm and queue:**

```bash
curl -s -X POST "$BASE/import/jobs/$JOB_ID/" \
  -H "Authorization: Token $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"confirm": true}'
```

Alternatively, upload with immediate confirm:

```bash
curl -s -X POST "$BASE/import/" \
  -H "Authorization: Token $TOKEN" \
  -F "file=@goodreads_export.csv" \
  -F "confirm=true"
```

### Export library

**JSON (full fidelity):**

```bash
curl -s "$BASE/export/?format=json" \
  -H "Authorization: Token $TOKEN" \
  -o openbook-export.json
```

**CSV (Goodreads-compatible):**

```bash
curl -s "$BASE/export/?format=csv" \
  -H "Authorization: Token $TOKEN" \
  -o openbook-export.csv
```

Export responses are raw file downloads (not wrapped in the JSON envelope).

---

## 7. Public embed widget

The embed API is **unauthenticated** but requires a secret key configured in Settings.

### Enable embed

1. Log in → **Settings** → enable embed widget.
2. Copy the embed key.

### Fetch embed JSON

```bash
curl -s "http://127.0.0.1:8000/api/v1/embed/?key=YOUR_EMBED_KEY&kind=currently_reading"
```

`kind` options: `currently_reading` (default), `recently_finished`.

Response:
```json
{
  "data": {
    "title": "Currently reading",
    "books": [
      {
        "id": "...",
        "title": "Dune",
        "authors": ["Frank Herbert"],
        "cover_url": "https://...",
        "url": "/books/.../",
        "status": "reading",
        "progress_percent": 25
      }
    ]
  }
}
```

### Embed script

Include on an external site:

```html
<script src="https://your-instance.com/embed/widget.js?key=YOUR_EMBED_KEY"></script>
```

Rotate the key from Settings if compromised.

---

## 8. Rate limits and errors

### Throttling

Default limits (configurable via `API_THROTTLE_RATES`):

| Scope | Rate |
|-------|------|
| `user` | 1000 requests/day per token |
| `auth` | 5 login attempts/minute |

When throttled (HTTP 429):

```json
{
  "error": {
    "code": "throttled",
    "message": "Request was throttled.",
    "details": null
  }
}
```

The response includes a `Retry-After` header (seconds to wait).

### Common error codes

| HTTP | Code | Typical cause |
|------|------|---------------|
| 400 | `validation_error` | Invalid request body or query params |
| 401 | `unauthorized` | Missing/invalid token |
| 404 | `not_found` | Book or resource does not exist |
| 409 | `duplicate_isbn` | ISBN already in library |
| 422 | `unprocessable` | Invalid status transition |
| 429 | `throttled` | Rate limit exceeded |
| 500 | `server_error` | Unexpected server error |

---

## 9. OpenAPI discovery

For machine-readable schema generation:

| URL | Format |
|-----|--------|
| `/api/v1/schema/` | OpenAPI 3 JSON/YAML |
| `/api/v1/docs/` | Swagger UI (interactive) |

Use these to generate client SDKs or feed agent tool definitions. The schema is auto-generated from DRF viewsets via drf-spectacular.

---

## 10. Related docs

- [02-TRD §4](02-TRD-Technical-Requirements-Document.md) — full endpoint reference and error catalog
- [08-Operations-and-Deployment.md](08-Operations-and-Deployment.md) — deployment and env vars
- [10-Import-and-Metadata-Pipeline.md](10-Import-and-Metadata-Pipeline.md) — import job internals
- [07-Architecture-and-Code-Map.md](07-Architecture-and-Code-Map.md) — codebase layout
