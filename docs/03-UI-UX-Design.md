# UI/UX Design — openbook

**Status:** Draft | **Owner:** John | **Last updated:** 2026-06-22

> **Design direction (decided):** simple, clean, content-first — Goodreads-like familiarity with modern, polished UI/UX. Tailwind (CDN for MVP), light theme, indigo accent, Chart.js for stats, slide-in drawer on mobile. See §8 for tokens.

---

## 1. Screen Map

| Screen | Purpose |
|--------|---------|
| **Dashboard** | Overview — recently added, currently reading, quick stats |
| **Books (list)** | Browse/search/filter all books in collection |
| **Book Detail** | Full book metadata, shelves, review, reading status |
| **Add Book** | Form to add a new book (manual or ISBN search) |
| **Shelves** | List of user's custom shelves |
| **Shelf Detail** | Books in a specific shelf |
| **Reading Log** | Currently reading + reading history |
| **Stats** | Reading statistics & visualisations |
| **Import / Export** | Bulk import (CSV / ISBNs) and export (JSON / CSV) |
| **Settings** | Profile, timezone, API token, data export |
| **Login** | Single sign-in screen (no registration — single-user instance) |

> **Single-user:** there is no Register/Sign-up screen. The one account is provisioned by the operator (see AppFlow §1). The only unauthenticated screen is Login.

---

## 2. Layout Structure (Desktop)

```
┌─────────────────────────────────────────────────────────┐
│  Header: Logo | Search bar | Profile | [menu toggle]     │
├──────────────────┬──────────────────────────────────────┤
│                  │                                       │
│  Sidebar         │  Main Content Area                     │
│                  │                                       │
│  • Dashboard     │  (varies by screen)                   │
│  • Books         │                                       │
│  • Shelves       │                                       │
│  • Stats         │                                       │
│  • Import/Export │                                       │
│  • Settings      │                                       │
│                  │                                       │
│  ─────────────   │                                       │
│  ⚡ API Token    │                                       │
│                  │                                       │
├──────────────────┴──────────────────────────────────────┤
│  Footer: openbook v0.1 | open source                     │
└─────────────────────────────────────────────────────────┘
```

### Responsive Behavior

- **Desktop (>1024px):** Sidebar visible, content fills remaining width
- **Tablet (768-1024px):** Collapsible sidebar (hamburger toggle)
- **Mobile (<768px):** Full-width content, sidebar becomes a **slide-in drawer** (hamburger toggle)

---

## 3. Screen Wireframes

### Dashboard

```
┌─────────────────────────────────────────────────────────┐
│  📚  Currently Reading              [see all →]          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                 │
│  │ Book     │ │ Book     │ │ Book     │                 │
│  │ Cover    │ │ Cover    │ │ Cover    │                 │
│  │ Title    │ │ Title    │ │ Title    │                 │
│  │ 45% done │ │ 72% done │ │ 22% done │                 │
│  └──────────┘ └──────────┘ └──────────┘                 │
│                                                          │
│  📊  Quick Stats                                          │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐                    │
│  │ 47   │ │ 12   │ │ 8    │ │ 3    │                    │
│  │Books │ │Read  │ │Reading│ │Shelves                    │
│  └──────┘ └──────┘ └──────┘ └──────┘                    │
│                                                          │
│  📖  Recent Additions                                     │
│  • Book Title — Author — 2 days ago                       │
│  • Book Title — Author — 5 days ago                       │
│  • Book Title — Author — 1 week ago                      │
└─────────────────────────────────────────────────────────┘
```

### Books List

```
┌─────────────────────────────────────────────────────────┐
│  🔍 [_________________________]  [Search]  [+ Add Book] │
│                                                          │
│  Filters: [All Shelves ▼] [All Status ▼] [Sort: ▼]      │
│                                                          │
│  ┌─────────────────────────────────────────────────┐     │
│  │ 📖 Book Title                    ⭐⭐⭐⭐☆        │     │
│  │ Author Name                Status: Reading      │     │
│  │ 400 pages     Shelves: Fiction, Favourites     │     │
│  ├─────────────────────────────────────────────────┤     │
│  │ 📖 Another Book                   ⭐⭐⭐☆☆        │     │
│  │ Author Name                Status: Finished     │     │
│  │ 250 pages     Shelves: Non-Fiction             │     │
│  └─────────────────────────────────────────────────┘     │
│                                                          │
│  [< Prev]  Page 1 of 5  [Next >]                        │
└─────────────────────────────────────────────────────────┘
```

### Book Detail

```
┌─────────────────────────────────────────────────────────┐
│  ┌──────────┐  Title                                        │
│  │          │  Author                                       │
│  │  Book    │  ⭐⭐⭐⭐☆  My rating: 4 / 5                  │
│  │  Cover   │                                              │
│  │          │  ISBN: 978-0-00-000000-0                     │
│  │          │  Pages: 350                                  │
│  └──────────┘  Published: 2021                             │
│                 Genres: Fiction, Drama                     │
│                                                          │
│  ─── Status ───                                            │
│  [■ Currently Reading]  45%  (p.158 / 350)  [Update]      │
│                                                          │
│  ─── Shelves ───                                           │
│  [Fiction] [Favourites] [2026 Reads]  [+ Add to Shelf]   │
│                                                          │
│  ─── My Review ───                                         │
│  ⭐⭐⭐⭐☆                                                  │
│  [Edit review / notes...]                                 │
│                                                          │
│  ─── Details ───                                           │
│  Description / synopsis...                                │
│                                                          │
│  [Edit] [Delete]                                          │
└─────────────────────────────────────────────────────────┘
```

> **Notes:**
> - **Rating** is the single operator's rating (1-5), not a community average — display "My rating: N / 5" (see Backend Schema `books_review`, one review per book).
> - **Genres** ("Fiction, Drama" above) are backed by the `books_genre` / `books_bookgenre` tables and are editable on Add/Edit Book and filterable on the Books list.

---

## 4. Interaction Patterns

| Element | Behaviour |
|---------|-----------|
| **Book search** | Live results as you type (HTMX, debounced 300ms) |
| **ISBN lookup** | On Add Book, entering an ISBN fetches metadata via Open Library and pre-fills the form (falls back to manual on miss/error) |
| **Add to shelf** | Modal/dropdown with shelf list, checkboxes |
| **Genres** | Multi-select on Add/Edit Book; shown as tags on detail; filterable on list |
| **Reading status** | Status control (Not started / Reading / Finished / Paused / DNF) — the single source of truth for reading state (shelves are separate tags) |
| **Reading progress** | Inline editable — set percent complete (page optional); saves a progress entry |
| **Star rating** | Whole stars only (1-5, no half-stars); hover highlights, click to set, shows numeric value |
| **Shelf management** | Drag-and-drop reorder (nice-to-have, not MVP) |
| **Export** | "Export JSON" / "Export CSV" buttons trigger a file download |
| **Empty states** | "No books yet. Add your first book!" with CTA button |
| **Error states** | Inline toast notifications for API errors |
| **Loading states** | Skeleton placeholders for lists, spinner for actions |

---

## 5. First-Run / Onboarding

A fresh instance has one account and no data. The empty experience should guide, not dead-end:

- **Empty dashboard:** brief welcome + primary CTAs: "Add your first book" and "Import from Goodreads".
- **Empty books/shelves/stats:** contextual empty states with the relevant CTA (add, create shelf, import).
- **API token surfaced early:** Settings highlights the token so agents can be wired up immediately.
- No multi-step setup wizard for MVP — keep it to inline empty states.

---

## 6. Settings Screen

| Section | Contents |
|---------|----------|
| **Profile** | Name, email (display) |
| **Security** | Change password (note: CLI/admin reset if locked out) |
| **Preferences** | Timezone (drives reading-day boundaries / streaks), theme (future) |
| **API** | Token display + Regenerate (rotates, invalidates old token) |
| **Data** | Export JSON, Export CSV, link to Import / Export |

---

## 7. Accessibility (WCAG 2.1 AA target)

- **Keyboard:** every interactive element reachable/operable by keyboard; logical focus order; visible focus styles.
- **Semantics/ARIA:** semantic HTML; ARIA labels for icon-only buttons (star rating, status toggle, menu); `aria-live` region for toasts and HTMX updates.
- **Contrast:** text and UI meet AA contrast (esp. in dark mode); never rely on colour alone (shelf/status also use text/icons).
- **Images:** book covers have meaningful `alt` (title + author); decorative icons are `aria-hidden`.
- **Forms:** labels associated with inputs; inline error text linked via `aria-describedby`.
- **Motion:** respect `prefers-reduced-motion` for skeletons/animations.

---

## 8. Design System

**Direction:** simple, clean, content-first — Goodreads-like familiarity but with modern, polished UI/UX (generous whitespace, clear hierarchy, fast interactions). No visual clutter.

| Token | Value | Notes |
|-------|-------|-------|
| **Delivery** | **Tailwind via CDN** (MVP) | Fast to start; migrate to a purged npm build post-MVP if page weight matters |
| **Theme** | Light by default | Dark mode is post-MVP (don't block on it) |
| **Primary/accent colour** | Indigo (`indigo-600`) | Single calm accent for CTAs/links; everything else neutral |
| **Neutrals** | Tailwind `slate`/`gray` | Backgrounds, borders, text |
| **Font** | System font stack | Fast, no web-font load; revisit Inter later |
| **Border radius** | `rounded-md` | Soft, not pill |
| **Spacing scale** | Tailwind defaults | |
| **Charts** | **Chart.js** (via CDN) | Stats visualisations |
| **Icons** | Inline SVG (e.g. Heroicons) | No icon-font dependency |

> **Note:** Using the Tailwind CDN means no build-time purge; acceptable for MVP. If first-paint regresses past the <1.5s target, switch to a compiled/purged Tailwind build.
