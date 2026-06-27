# Agent-driven reading suggestions

openbook does not run a built-in recommendation engine. Instead, agents and automation can query your library via the API and propose reads using rule-based logic.

## API endpoints for suggestions

| Goal | Approach |
|------|----------|
| TBR by genre | `GET /api/v1/books/?status=not_started&genre=<id>` |
| Short reads | Filter books with `pages__lte=250` via API or export JSON |
| Unread by author | List books by author, exclude `status=finished` |
| Reading goal gap | `GET /api/v1/reading-goals/` + stats API for progress |

## Webhooks

Subscribe to `reading.status_changed` and `import.completed` to trigger external workflows when the library changes.

## Example agent flow

1. `GET /api/v1/books/?status=not_started` — fetch TBR
2. Filter client-side by genre, page count, or tags
3. Return top N titles to the user

## OPDS

Use `/opds/` for e-reader clients; reading status remains in openbook as source of truth.

## Privacy

All suggestion logic runs on your instance. No data is sent to third-party recommendation services unless you explicitly call metadata providers during import.
