# PRD — openbook MVP

**Status:** Draft | **Owner:** John | **Last updated:** 2026-06-22

---

## 1. Problem Statement

Existing book tracking tools have fundamental flaws:

- **Goodreads** — owned by Amazon, no public API, dated UI, zero privacy, no AI/automation access
- **Jelu & other open source alternatives** — buggy codebases, poor APIs (or none), outdated UIs, no consideration for AI agents or automation
- **No existing tool** treats both *human readers* and *AI agents* as first-class users

People who care about their data, want a modern experience, and want to integrate their book data into automated workflows (AI agents, home automation, stats pipelines) have no good option.

## 2. Vision

**openbook** is an open source, privacy-first book tracking platform built for both **people** and **AI agents**. It offers a modern UI, a powerful API, and automation capabilities — giving everyone control over their reading data.

**Deployment model (MVP):** openbook is **single-user and self-hosted** — one account per instance. There is no open registration; the account is provisioned by the operator (via `createsuperuser` / Django admin). Multi-tenant / multi-user is explicitly post-MVP (see §4 Future).

## 3. Target Users

| User | Needs |
|------|-------|
| **John (operator + sole user)** | Full control, API access, automation, modern UI, privacy |
| **AI agents (e.g. Nexus)** | Read/write access via API — query shelves, log books, generate stats |
| **Privacy-conscious readers** | Self-host their *own* single-user instance, no Big Tech, own their data |
| **Open source community** | Extensible, well-documented, API-first; each person runs their own instance |

> **Note on "users":** Each openbook deployment serves one person. "Privacy-conscious readers" and the "open source community" are served by *self-hosting their own instance*, not by a shared multi-tenant service.

## 4. Core Features (MVP)

### Must-Have

- [x] **Book search & add** — search by title/author/ISBN, add books to personal collection. ISBN add is backed by **Open Library** metadata lookup (auto-fills title, authors, cover, pages, etc.); manual entry is always available as a fallback.
- [x] **Custom shelves** — create, name, and organise shelves as free-form tags (e.g. "Favourites", "2026 Reads", "Sci-Fi TBR"). Shelves are *not* reading status — want-to-read / reading / read / paused / DNF are tracked separately as **reading status** (see Reading tracking)
- [x] **Genres** — categorise books by genre (multiple genres per book); filter/browse by genre
- [x] **Reading tracking** — mark books as currently reading, log progress by **percent complete** (page number optional, where known). Progress is recorded over time so streaks and progress charts can be computed
- [x] **Ratings & reviews** — rate books (1-5 stars), write personal notes/reviews
- [x] **Full REST API** — all operations accessible via API for AI agents and automation
- [x] **Reading stats** — books per month, pages read, completion rate, shelf breakdown, reading streak
- [x] **Search & browse** — search your collection, filter by shelf/genre/author/rating/status
- [x] **Import** — import books via ISBN list or CSV (Goodreads export format), enriched via Open Library where possible
- [x] **Export** — export your entire collection at any time: complete **JSON** (full fidelity) and **CSV** (Goodreads-compatible for round-trip). Core to the "own your data" promise; available via UI and API

### Future (post-MVP)

- [ ] Multi-user / multi-tenant support (open registration, per-user data isolation)
- [x] Series / volume tracking (e.g. "Mistborn #1")
- [ ] Internationalisation (i18n) of the UI (MVP is English-only; per-book `language` is still supported)
- [x] Public profile with embeddable shelf widget
- [ ] OAuth (Google, GitHub login)
- [x] Reading goals & challenges
- [x] OPDS sync
- [x] Webhooks for automation (e.g. "notify when book status changes")
- [ ] Collaborative shelves / shared lists
- [ ] AI-powered recommendations

## 5. Explicitly Out of Scope (MVP)

- Social features (friends, feeds, comments, following)
- EPUB/PDF book reader
- Books discovery / recommendations engine
- Native mobile apps
- E-commerce / book buying
- User-generated content beyond reviews
- Moderation systems

## 6. Success Metrics

| Metric | Target | How measured |
|--------|--------|--------------|
| Books in John's collection | 100+ within first month | DB count |
| API response time | <200ms P95 for standard queries | External monitoring / request-timing logs |
| CSV import success rate | 100% of valid rows imported or clearly reported | Import result `{added, skipped, failed}` |
| Agent API uptime | 99.9% | External monitor polling `/healthz` |
| Zero data loss | Imports idempotent, no duplicates; export round-trips cleanly | Round-trip test (import → export → re-import) |

**Metric definitions** (used by the Stats screen and tests):

- **Completion rate** = books with `status = finished` ÷ total books.
- **Books read this year** = books whose `ReadingLog.finished_at` falls in the current calendar year (local timezone).
- **Reading streak** = number of consecutive local-timezone days, ending today, that have at least one `ReadingProgress` entry.
- **Pages read (period)** = sum of `ReadingProgress.pages_read` in the period.
- Day boundaries and "this year" use the configured `TIME_ZONE` (see TRD §8), not UTC.

## 7. Guiding Principles

1. **API-first** — every UI feature is backed by an API endpoint; agents have full parity
2. **Privacy by default** — no telemetry, no third-party data sharing, self-hosted
3. **Own your data** — full export (JSON + CSV) is always available; no lock-in
4. **Modern UX** — clean, fast, responsive (desktop + mobile browser)
5. **Simple to deploy** — single Docker container, minimal dependencies
6. **Open source** — MIT licensed
