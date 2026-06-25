# openbook — Product context

## Register

`product` — app UI serves reading workflows; design is familiar and task-focused, not marketing-led.

## Users

- **Operator:** single self-hosted account (provisioned via `createsuperuser`)
- **API agents:** automation via token auth (shelves, books, stats)

## Primary tasks

1. Browse and search the library
2. Log reading status and progress
3. Organize books on shelves
4. Import/export data (ISBN list, Goodreads CSV)
5. Review reading stats

## Personality

Calm, content-first, trustworthy, Goodreads-familiar with modern polish.

## Anti-references

- SaaS marketing chrome (hero metrics, gradient blobs, eyebrow kickers)
- Decorative motion and glassmorphism
- Card soup (nested cards, one card per list row)
- AI-purple gradients and numbered section markers

## Accessibility

WCAG 2.1 AA target. Keyboard navigation, visible focus, semantic HTML, `prefers-reduced-motion` respected.
