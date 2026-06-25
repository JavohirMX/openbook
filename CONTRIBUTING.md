# Contributing to openbook

## Setup

1. Install [uv](https://docs.astral.sh/uv/) and Python 3.12 (see `.python-version`).
2. Clone the repo and run `uv sync --dev`.
3. Copy `.env.example` to `.env` and adjust as needed.
4. Run migrations: `uv run python manage.py migrate && uv run python manage.py createcachetable`.
5. Create a superuser: `uv run python manage.py createsuperuser`.

## Running tests

```bash
uv run pytest
```

CI runs the same command against PostgreSQL on every push and pull request.

## Code style

- Match existing patterns in the codebase (double-quoted strings, minimal comments).
- Keep changes focused — one feature or fix per commit.
- Add tests for new behavior (models, serializers, API endpoints).

## Phase workflow

See [AGENTS.md](AGENTS.md) for the phased build process and gate checklist.

## Pull requests

- Ensure `uv run python manage.py check` and `uv run pytest` pass.
- Update [CHANGELOG.md](CHANGELOG.md) under `[Unreleased]` for user-visible changes.
