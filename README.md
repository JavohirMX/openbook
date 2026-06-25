# openbook

Self-hosted, privacy-first book tracker with a full REST API for humans and AI agents.

Single-user deployment — one account per instance, created via `createsuperuser`. No open registration.

## Features (MVP)

- Book search, add, and metadata lookup (Open Library + Google Books fallback)
- Custom shelves, genres, reading status and progress
- Ratings, reviews, stats, import/export (CSV + JSON)
- REST API with OpenAPI docs at `/api/v1/docs/`

## Quickstart

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+.

```bash
# Install dependencies
uv sync --dev

# Copy environment template
cp .env.example .env

# Run migrations and create cache table
uv run python manage.py migrate
uv run python manage.py createcachetable

# Create the operator account
uv run python manage.py createsuperuser

# Start the dev server
uv run python manage.py runserver
```

Visit http://127.0.0.1:8000/admin/ to sign in.

## Development

```bash
uv run pytest                  # Run tests
uv run python manage.py check  # Django system check
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines and [AGENTS.md](AGENTS.md) for AI build workflow.

## Documentation

| Doc | Description |
|-----|-------------|
| [docs/01-PRD-Product-Requirements-Document.md](docs/01-PRD-Product-Requirements-Document.md) | Product requirements |
| [docs/02-TRD-Technical-Requirements-Document.md](docs/02-TRD-Technical-Requirements-Document.md) | Technical requirements |
| [docs/05-Backend-Schema.md](docs/05-Backend-Schema.md) | Database schema |
| [docs/06-Implementation-Plan.md](docs/06-Implementation-Plan.md) | Build phases |

## License

MIT — see [LICENSE](LICENSE).
