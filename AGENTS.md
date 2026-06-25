# AGENTS.md — AI build guide for openbook

## Context

openbook is a single-user, self-hosted book tracker. Read the docs in `docs/` before building:

- **Doc index:** [docs/README.md](docs/README.md)
- **Phase scope:** [docs/06-Implementation-Plan.md](docs/06-Implementation-Plan.md)
- **Architecture / code map:** [docs/07-Architecture-and-Code-Map.md](docs/07-Architecture-and-Code-Map.md)
- **Import pipeline:** [docs/10-Import-and-Metadata-Pipeline.md](docs/10-Import-and-Metadata-Pipeline.md)
- **API spec:** [docs/02-TRD-Technical-Requirements-Document.md](docs/02-TRD-Technical-Requirements-Document.md) §4
- **Schema:** [docs/05-Backend-Schema.md](docs/05-Backend-Schema.md)
- **UI:** [docs/03-UI-UX-Design.md](docs/03-UI-UX-Design.md)

## uv commands

| Task | Command |
|------|---------|
| Install deps | `uv sync --dev` |
| Add runtime dep | `uv add <package>` |
| Add dev dep | `uv add --dev <package>` |
| Django | `uv run python manage.py <cmd>` |
| Tests | `uv run pytest` |
| Import worker | `uv run python manage.py process_import_jobs --loop` (optional in Docker; local dev auto-processes by default) |

Imports run in the background via a database job queue. Local `runserver` auto-starts processing when jobs are queued (`IMPORT_JOB_AUTO_PROCESS=true` by default). Docker Compose disables auto-process on the web container and uses the `worker` service instead. Use **Process now** on a pending job or `process_import_jobs` to drain manually.

**Metadata during import:** Goodreads CSV imports use CSV data only by default (`IMPORT_GOODREADS_ENRICH_METADATA=false`). Set `IMPORT_GOODREADS_ENRICH_METADATA=true` to backfill covers/genres via Open Library. Set `OPENLIBRARY_CONTACT_EMAIL` so requests use an identified User-Agent (`openbook/0.1.0 (you@example.com)`) for Open Library’s 3 req/s limit; without it, pacing defaults to 1 req/s. Override with `METADATA_IMPORT_DELAY_SECONDS` if needed.

Dependencies live in `pyproject.toml` + `uv.lock`. Do not add `requirements.txt`.

## Build philosophy

**Plan → Build → Verify → Repeat.** Complete one phase before starting the next. Within a phase, parallel agents may work on independent subtasks, then integrate before the gate.

## Phase gate checklist

Before marking a phase complete:

```bash
uv sync --dev
uv run python manage.py check    # zero errors
uv run python manage.py migrate
uv run python manage.py createcachetable
uv run pytest                    # all green
# curl smoke tests for new API endpoints
```

Then commit with a clear message and tag: `git tag phase-N`.

## Architecture notes

- **Two surfaces:** Web (Django templates + HTMX, session auth) and API (`/api/v1/*`, token auth, JSON envelope).
- **Single user:** No registration after setup. First visit to `/setup/` creates the sole superuser; `createsuperuser` remains a CLI fallback.
- **Soft delete:** Books use `deleted_at`; default queryset excludes trashed.
- **Reading status:** Owned by `ReadingLog`, not custom shelves. Default Goodreads-style shelves (Want to Read / Currently Reading / Read) are virtual views over status on the Shelves page; custom `Shelf` rows remain optional tags.

## Testing

- Framework: pytest + pytest-django + factory_boy
- Mock Open Library / Google Books HTTP in tests — no live network
- CI: GitHub Actions with `astral-sh/setup-uv` + PostgreSQL

## Commit conventions

- One logical change per commit
- Tag after each phase passes: `phase-0`, `phase-1`, etc.
- Update CHANGELOG.md under `[Unreleased]`
