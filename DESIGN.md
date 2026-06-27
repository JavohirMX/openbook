# openbook — Design system

## Color strategy

**Monochrome editorial:** neutral palette only, no accent color. Semantic red/green for errors/success kept muted. Avoid pure `#000` and pure `#fff` in dark mode.

| Role | Light | Dark (pleasant black) |
|------|-------|----------------------|
| Page bg | `neutral-50` | `neutral-950` (`#0a0a0a`) |
| Sidebar / header / surface | `white` | `neutral-900` |
| Borders / dividers | `neutral-200` | `neutral-800` |
| Body text | `neutral-950` | `neutral-100` |
| Muted text | `neutral-500` | `neutral-400` |
| Primary button | `neutral-950` bg, `neutral-50` text | `neutral-100` bg, `neutral-950` text |
| Secondary button | `border-neutral-300`, hover `neutral-100` | `border-neutral-700`, hover `neutral-800` |
| Links | `neutral-950` + underline on hover | `neutral-100` + underline on hover |
| Active nav | `bg-neutral-100` + `font-semibold` | `bg-neutral-800` + `font-semibold` |

## Typography

- **Display / page titles:** Newsreader — `text-3xl font-bold tracking-tight` (`.page-title`)
- **UI / body:** IBM Plex Sans — `text-base` body, `text-sm` meta
- **Data:** IBM Plex Mono for API tokens (`font-mono`)
- **Section title:** `text-lg font-medium`

## Shape

- **No border radius** on surfaces, buttons, inputs, badges (`rounded-none`)
- Book cover images: sharp rectangles (`object-cover`, no radius)

## Motion

- 150ms ease-out on hover/focus/active
- `active:scale-[0.98]` on pressable elements
- Drawer slide respects `prefers-reduced-motion: reduce` (instant toggle)
- No page-load choreography

## Dark mode

Class-based (`dark` on `<html>`). Theme preference: Light / Dark / System via `localStorage` key `openbook-theme`.

## Components (Tailwind `@layer`)

- `.surface` — elevated panel, border only (no box-shadow)
- `.surface-padded` — surface with padding
- `.surface-list` — bordered list with `divide-y`
- `.btn-primary` / `.btn-secondary` / `.btn-destructive` — CTAs with full interactive states (`min-h-11` touch targets)
- `.input` / `.file-input` — form controls (`min-h-11`)
- `.badge` / `.badge-tag` — status and genre pills
- `.link` — text links with underline on hover
- `.skeleton` — HTMX loading placeholders
- `.segmented-control` / `.segmented-option` — reading status radio group
- `.star-rating` — accessible SVG star buttons
- `.metrics-strip` / `.metrics-strip-item` — horizontal stat row (dashboard, stats)
- `.empty-inline` — lightweight empty copy for sub-sections

## Z-index scale

- Backdrop: `z-40`
- Drawer / sidebar mobile: `z-50`

## Delivery

Tailwind via CDN (MVP). Chart.js for stats (12-color categorical palette — blue, green, amber, red, violet, cyan, pink, lime, orange, indigo, teal, fuchsia; lighter hues in dark mode). Color is scoped to chart data slices; all other UI stays monochrome. Inline Heroicons. HTMX for partial updates.
