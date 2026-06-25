# Operations and Deployment — openbook

**Status:** Living doc | **Last updated:** 2026-06-25

---

Runbook for running openbook in local development, Docker, and production. For codebase layout see [07-Architecture-and-Code-Map.md](07-Architecture-and-Code-Map.md). For import/metadata internals see [10-Import-and-Metadata-Pipeline.md](10-Import-and-Metadata-Pipeline.md).

---

## 1. Prerequisites

| Environment | Requirements |
|-------------|--------------|
| **Local dev** | [uv](https://docs.astral.sh/uv/), Python 3.12+ (see `.python-version`) |
| **Docker** | Docker Engine + Docker Compose v2 |
| **Production** | PostgreSQL 16 recommended; reverse proxy (Traefik or similar) for HTTPS |

---

## 2. First-run setup

### Web setup (recommended)

1. Run migrations and create the cache table:
   ```bash
   uv run python manage.py migrate
   uv run python manage.py createcachetable
   ```
2. Start the server: `uv run python manage.py runserver`
3. Visit `/setup/` and create the sole operator account.

`FirstRunSetupMiddleware` redirects all unauthenticated traffic to `/setup/` until at least one user exists.

### CLI fallback

```bash
uv run python manage.py createsuperuser
```

Uses email (not username) as the login identifier.

---

## 3. Environment variable reference

Copy [.env.example](../.env.example) to `.env` for local development.

### Core

| Variable | Default | When to set | Notes |
|----------|---------|-------------|-------|
| `SECRET_KEY` | Dev placeholder in settings | **Required in production** | Django signing key |
| `DEBUG` | `True` | Set `False` in production | Enables security headers, CSP, SSL redirect when off |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Production hostname(s) | Comma-separated |
| `DATABASE_URL` | *(SQLite fallback)* | Production | `postgres://user:pass@host:5432/openbook` |
| `TIME_ZONE` | `Asia/Tashkent` | Your locale | Used for date display; per-user override via profile |

### Production security (when `DEBUG=False`)

| Variable | Default | Notes |
|----------|---------|-------|
| `SECURE_SSL_REDIRECT` | `True` | Redirect HTTP → HTTPS |
| `SECURE_HSTS_SECONDS` | `31536000` | HSTS header duration |
| `CSRF_TRUSTED_ORIGINS` | *(empty)* | `https://your-domain.com` — required for HTTPS forms |
| `CORS_ALLOWED_ORIGINS` | *(empty)* | Origins allowed to call the API from browsers |

### Metadata providers

| Variable | Default | Notes |
|----------|---------|-------|
| `OPENLIBRARY_BASE_URL` | `https://openlibrary.org` | Override for testing |
| `GOOGLE_BOOKS_BASE_URL` | `https://www.googleapis.com/books/v1` | Fallback provider |
| `OPENLIBRARY_CONTACT_EMAIL` | *(empty)* | **Strongly recommended** — identified User-Agent gets 3 req/s; without email, 1 req/s |
| `METADATA_CONNECT_TIMEOUT` | `5` | HTTP connect timeout (seconds) |
| `METADATA_READ_TIMEOUT` | `10` | HTTP read timeout (seconds) |
| `METADATA_RETRY_COUNT` | `1` | Retries on transient failures |
| `METADATA_RETRY_BACKOFF` | `1` | Backoff between retries (seconds) |
| `METADATA_IMPORT_DELAY_SECONDS` | `0` (auto) | `0` = auto: 0.35s with contact email, 1s without; override for custom pacing |
| `IMPORT_GOODREADS_ENRICH_METADATA` | `false` | `true` = fetch covers/genres from Open Library during Goodreads CSV import |

### Import job processing

| Variable | Default | Notes |
|----------|---------|-------|
| `IMPORT_JOB_AUTO_PROCESS` | `true` | `true` = web process drains queue in background thread; `false` = requires worker |
| `IMPORT_JOB_STALE_MINUTES` | `30` | Reclaim `running` jobs older than this back to `pending` |

### API

| Variable | Default | Notes |
|----------|---------|-------|
| `API_THROTTLE_RATES` | `user=1000/day,auth=5/min` | Comma-separated `scope=rate` pairs |
| `APP_VERSION` | `0.1.0` | Shown in metadata User-Agent string |

### Logging

| Variable | Default | Notes |
|----------|---------|-------|
| `LOG_LEVEL` | `INFO` | Root logger level |

---

## 4. Local development vs Docker

### Local (`runserver`)

```bash
uv sync --dev
cp .env.example .env
uv run python manage.py migrate
uv run python manage.py createcachetable
uv run python manage.py runserver
```

- Uses SQLite if `DATABASE_URL` is unset.
- `IMPORT_JOB_AUTO_PROCESS=true` (default) — import jobs drain automatically in a daemon background thread after each request commits.
- No separate worker process needed.

### Docker Compose (production layout)

The bundled [docker-compose.yml](../docker-compose.yml) runs three services:

| Service | Role |
|---------|------|
| `openbook` | Gunicorn web app on port 8000 |
| `worker` | `python manage.py process_import_jobs --loop` |
| `db` | PostgreSQL 16 |

Key differences from local dev:

- `IMPORT_JOB_AUTO_PROCESS=false` on the web container — the `worker` service drains the queue.
- `DEBUG=False`, production security headers enabled.
- Shared `openbook_media` volume for import CSV uploads and downloaded cover images (`media/covers/`).
- Traefik labels for `books.javohirmx.com` (adjust for your domain).
- Requires external Docker network `web` (for Traefik).

For a **self-contained local Docker stack** without Traefik, see the `docker-compose.local.yml` example in [README.md](../README.md).

### Docker first-run

After `docker compose up`:

```bash
docker compose exec openbook python manage.py migrate
docker compose exec openbook python manage.py createcachetable
```

Then visit `http://localhost:8000/setup/` (or your configured host).

---

## 5. Import worker

### Automatic processing (local dev)

When `IMPORT_JOB_AUTO_PROCESS=true`, `schedule_import_processing()` starts a daemon thread named `openbook-import` after a job is queued. The thread drains all pending jobs then exits.

### Manual / Docker worker

```bash
# Process one pending job and exit
uv run python manage.py process_import_jobs

# Poll continuously (Docker worker default)
uv run python manage.py process_import_jobs --loop

# Custom poll interval (default 2 seconds)
uv run python manage.py process_import_jobs --loop --interval 5
```

### Stale job reclaim

If a worker crashes mid-job, the job stays `running`. On each drain cycle, `reclaim_stale_running_jobs()` resets jobs in `running` state longer than `IMPORT_JOB_STALE_MINUTES` (default 30) back to `pending`.

### Web UI "Process now"

On the import job detail page, operators can trigger `schedule_import_processing(force=True)` to drain immediately regardless of `IMPORT_JOB_AUTO_PROCESS`.

---

## 6. Metadata rate limits

Open Library enforces rate limits based on User-Agent identification:

| Configuration | Pacing | User-Agent example |
|---------------|--------|-------------------|
| `OPENLIBRARY_CONTACT_EMAIL` set | ~3 req/s (0.35s delay) | `openbook/0.1.0 (you@example.com)` |
| No contact email | ~1 req/s (1.0s delay) | `openbook/0.1.0 (+https://your-host)` |
| `METADATA_IMPORT_DELAY_SECONDS` > 0 | Custom delay | Overrides auto pacing |

**Recommendations:**

1. Set `OPENLIBRARY_CONTACT_EMAIL` in production and Docker.
2. Leave `IMPORT_GOODREADS_ENRICH_METADATA=false` for fast CSV imports; use **Library Tools** (`/library-tools/`) to backfill metadata afterward.
3. Large backfill jobs are paced per ISBN — expect minutes for hundreds of books.

Metadata responses are cached in the Django database cache for 30 days (negative results for 1 hour).

---

## 7. Health and monitoring

### `/healthz`

```bash
curl -s http://127.0.0.1:8000/healthz
```

**Healthy (200):**
```json
{"status": "ok", "database": true}
```

**Unhealthy (503):**
```json
{"status": "error", "database": false}
```

Docker Compose uses this endpoint in the `openbook` service healthcheck.

### What to monitor

- `/healthz` returns 200
- Import jobs not stuck in `pending` (worker running)
- Disk usage on `media/` volume (CSV uploads and cover images)
- PostgreSQL connection pool / disk

---

## 8. Production checklist

- [ ] `SECRET_KEY` set to a strong random value
- [ ] `DEBUG=False`
- [ ] `ALLOWED_HOSTS` includes your domain
- [ ] `CSRF_TRUSTED_ORIGINS` and `CORS_ALLOWED_ORIGINS` set for HTTPS origin
- [ ] `DATABASE_URL` points to PostgreSQL
- [ ] `createcachetable` run (required for throttling + metadata cache)
- [ ] `OPENLIBRARY_CONTACT_EMAIL` set
- [ ] Import worker running (`worker` service or manual `process_import_jobs --loop`)
- [ ] `IMPORT_JOB_AUTO_PROCESS=false` on web if using separate worker
- [ ] Reverse proxy terminates TLS (Traefik, Caddy, nginx)
- [ ] Backup strategy for PostgreSQL and `media/` volume
- [ ] Log aggregation configured (`LOG_LEVEL`)

---

## 9. Backup and restore

### Database

```bash
# Backup
pg_dump "$DATABASE_URL" -Fc -f openbook-$(date +%Y%m%d).dump

# Restore
pg_restore -d "$DATABASE_URL" --clean --if-exists openbook-20260625.dump
```

For SQLite (local dev only): copy `db.sqlite3`.

### Media files

Import job CSV files are stored under `media/import_jobs/`. Cover images are stored under `media/covers/`. Back up the `media/` directory (or the `openbook_media` Docker volume) alongside the database.

To backfill covers for existing books: **Library Tools** → metadata backfill, or `uv run python manage.py download_covers`.

### Export alternative

Operators can export the full library as JSON via the web UI (**Import / Export**) or `GET /api/v1/export/?format=json` for a portable snapshot without direct DB access.

---

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Import jobs stay `pending` | No worker draining queue | Set `IMPORT_JOB_AUTO_PROCESS=true` (local) or start `worker` service / run `process_import_jobs --loop` |
| Import jobs stuck `running` | Worker crashed | Wait for stale reclaim (`IMPORT_JOB_STALE_MINUTES`) or restart worker; job returns to `pending` |
| Books imported without covers | `IMPORT_GOODREADS_ENRICH_METADATA=false` | Expected — use **Library Tools** → bulk backfill, `download_covers`, or set enrichment flag for future imports |
| Metadata backfill very slow | Rate limiting | Set `OPENLIBRARY_CONTACT_EMAIL`; check `METADATA_IMPORT_DELAY_SECONDS` |
| Open Library 429 errors | Too many requests | Increase delay; ensure contact email is set |
| `/setup/` redirect loop | No users and middleware active | Complete setup or run `createsuperuser` |
| API returns 401 | Missing or invalid token | Login via `/api/v1/auth/login/` or copy token from Settings |
| API returns 429 | Throttle exceeded | Wait for `Retry-After` seconds; adjust `API_THROTTLE_RATES` if needed |
| CSRF errors on web forms | Origin not trusted | Add origin to `CSRF_TRUSTED_ORIGINS` |
| Static files 404 in production | `collectstatic` not run | `uv run python manage.py collectstatic` (handled in Docker build) |
| Cache/throttle errors | Cache table missing | `uv run python manage.py createcachetable` |

---

## 11. Related docs

- [README.md](../README.md) — quickstart and Docker local-compose example
- [07-Architecture-and-Code-Map.md](07-Architecture-and-Code-Map.md) — codebase layout
- [10-Import-and-Metadata-Pipeline.md](10-Import-and-Metadata-Pipeline.md) — import job details
- [09-API-Consumer-Guide.md](09-API-Consumer-Guide.md) — API usage
