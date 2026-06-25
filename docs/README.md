# openbook documentation

**Status:** Living docs | **Last updated:** 2026-06-25

---

## Start here by role

| Role | Read first | Then |
|------|------------|------|
| **Product / stakeholder** | [01-PRD](01-PRD-Product-Requirements-Document.md) | [04-AppFlow](04-AppFlow-Application-Flow.md) |
| **Designer** | [03-UI-UX-Design](03-UI-UX-Design.md) | [DESIGN.md](../DESIGN.md) (design tokens) |
| **Contributor / developer** | [07-Architecture-and-Code-Map](07-Architecture-and-Code-Map.md) | [05-Backend-Schema](05-Backend-Schema.md), [02-TRD](02-TRD-Technical-Requirements-Document.md) §4 |
| **Operator / deployer** | [08-Operations-and-Deployment](08-Operations-and-Deployment.md) | [README.md](../README.md) (quickstart) |
| **API consumer / agent** | [09-API-Consumer-Guide](09-API-Consumer-Guide.md) | [02-TRD](02-TRD-Technical-Requirements-Document.md) §4, live [OpenAPI docs](/api/v1/docs/) |
| **AI build agent** | [AGENTS.md](../AGENTS.md) | [06-Implementation-Plan](06-Implementation-Plan.md), [07-Architecture](07-Architecture-and-Code-Map.md) |

---

## Product and design (planning specs)

| Doc | Description |
|-----|-------------|
| [01-PRD-Product-Requirements-Document.md](01-PRD-Product-Requirements-Document.md) | MVP product requirements, feature checklist |
| [02-TRD-Technical-Requirements-Document.md](02-TRD-Technical-Requirements-Document.md) | Stack, architecture, **canonical API reference** (§4), error catalog |
| [03-UI-UX-Design.md](03-UI-UX-Design.md) | Screen map, layout, components, editorial design direction |
| [04-AppFlow-Application-Flow.md](04-AppFlow-Application-Flow.md) | Navigation map and user flows (mermaid) |
| [05-Backend-Schema.md](05-Backend-Schema.md) | ER diagram and table definitions |
| [06-Implementation-Plan.md](06-Implementation-Plan.md) | Phased build plan and gate checklist |

---

## Implementation guides (code ↔ spec)

| Doc | Audience | Description |
|-----|----------|-------------|
| [07-Architecture-and-Code-Map.md](07-Architecture-and-Code-Map.md) | Contributors | Django project layout, URL maps, module responsibilities, services, testing |
| [08-Operations-and-Deployment.md](08-Operations-and-Deployment.md) | Operators | Environment variables, Docker, import worker, backup, troubleshooting |
| [09-API-Consumer-Guide.md](09-API-Consumer-Guide.md) | API consumers | Auth, envelope, workflows, import/export, embed — practical curl walkthroughs |
| [10-Import-and-Metadata-Pipeline.md](10-Import-and-Metadata-Pipeline.md) | All | Import job state machine, Goodreads CSV, metadata providers, worker concurrency |

---

## Live API reference

The **authoritative endpoint list** is [TRD §4](02-TRD-Technical-Requirements-Document.md). For interactive exploration on a running instance:

- **Swagger UI:** `/api/v1/docs/`
- **OpenAPI schema:** `/api/v1/schema/`

The consumer guide ([09](09-API-Consumer-Guide.md)) adds context and step-by-step examples; it does not duplicate the full endpoint tables.

---

## Root-level docs

| File | Description |
|------|-------------|
| [README.md](../README.md) | Project overview, quickstart, Docker, API at a glance |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | Dev setup, tests, PR expectations |
| [AGENTS.md](../AGENTS.md) | AI build workflow and phase gates |
| [DESIGN.md](../DESIGN.md) | Design system tokens |
| [PRODUCT.md](../PRODUCT.md) | Product context and anti-patterns |
| [CHANGELOG.md](../CHANGELOG.md) | Release notes |
