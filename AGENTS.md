# AGENTS.md — AI build guide for openbook

## Context

openbook is a single-user, self-hosted book tracker. Read the docs in `docs/` before building:

- **Phase scope:** [docs/06-Implementation-Plan.md](docs/06-Implementation-Plan.md)
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

Dependencies live in `pyproject.toml` + `uv.lock`. Do not add `requirements.txt`.

## Build philosophy

**Plan → Build → Verify → Repeat.** Complete one phase before starting the next. Within a phase, parallel agents may work on independent subtasks, then integrate before the gate.

## Phase gate checklist

Before marking a phase complete:

```bash
uv sync --dev
uv run python manage.py check    # zero errors
uv run python manage.py migrate
uv run pytest                    # all green
# curl smoke tests for new API endpoints
```

Then commit with a clear message and tag: `git tag phase-N`.

## Architecture notes

- **Two surfaces:** Web (Django templates + HTMX, session auth) and API (`/api/v1/*`, token auth, JSON envelope).
- **Single user:** No registration endpoint. Account via `createsuperuser`.
- **Soft delete:** Books use `deleted_at`; default queryset excludes trashed.
- **Reading status:** Owned by `ReadingLog`, not shelves.

## Testing

- Framework: pytest + pytest-django + factory_boy
- Mock Open Library / Google Books HTTP in tests — no live network
- CI: GitHub Actions with `astral-sh/setup-uv` + PostgreSQL

## Commit conventions

- One logical change per commit
- Tag after each phase passes: `phase-0`, `phase-1`, etc.
- Update CHANGELOG.md under `[Unreleased]`
