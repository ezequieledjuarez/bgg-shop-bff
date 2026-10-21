# Implementation Plan: Catalog Search and Filters

**Branch**: `CU-06-wishlist` | **Date**: 2026-10-21 | **Spec**: [`spec.md`](./spec.md)
**Input**: Feature specification from `/specs/002-catalog-search-filters/spec.md`

## Summary

The BFF exposes a public paginated product-list operation with optional search, year, player-count, category, and price filters. It validates REST query parameters, maps snake_case to Core GraphQL camelCase, and adapts the paginated response back to REST.

## Technical Context

**Language/Version**: Python (runtime version not stated in the BFF feature record)
**Primary Dependencies**: Flask, Flask-CORS, Requests; see [`requirements.txt`](../../requirements.txt)
**Storage**: None in the BFF; persistent domain state is owned by Core, while cart identity is carried in a cookie where applicable
**Testing**: pytest
**Target Platform**: Flask REST service; deployment target is not specified in this feature record
**Project Type**: Web-service backend-for-frontend
**Performance Goals**: Not specified in the as-built BFF evidence
**Constraints**: Keep the public REST/OpenAPI contract aligned with the Core GraphQL adapter; validate inputs and avoid leaking upstream details
**Scale/Scope**: The BFF operations and test coverage listed for CU-C02 only

## Constitution Check

- **Pass** — retain the existing Flask/Python BFF and source contract at [`specs/openapi.yaml`](../openapi.yaml).
- **Pass** — keep controllers focused on HTTP behavior, DTOs on request/response shapes, services/proxy on Core orchestration and mapping; this plan adds no abstraction.
- **Pass** — public error responses follow the documented generic upstream behavior rather than exposing internal exception details.

## Project Structure

### Documentation (this feature)

```text
specs/002-catalog-search-filters/
├── spec.md
├── plan.md
└── tasks.md
```

### Source Code (repository root)

```text
bgg-shop-bff/
├── app.py
├── src/
│   ├── controllers/
│   ├── dtos/
│   ├── services.py
│   └── proxy.py
├── tests/
└── specs/openapi.yaml
```

**Feature-specific source and test paths**:

- [`app.py`](../../app.py)
- [`src/controllers/products_controller.py`](../../src/controllers/products_controller.py)
- [`src/dtos/products.py`](../../src/dtos/products.py)
- [`src/services.py`](../../src/services.py)
- [`src/proxy.py`](../../src/proxy.py)
- [`specs/openapi.yaml`](../../specs/openapi.yaml)
- [`tests/test_products.py`](../../tests/test_products.py)

**Structure Decision**: Use the existing single Flask BFF repository and resource-oriented `src/controllers` and `src/dtos` modules. The REST contract remains `specs/openapi.yaml`; Core GraphQL remains upstream.

## User Stories in Scope

- **US1** — List and filter products: Forward validated catalog criteria and preserve pagination metadata and upstream failure behavior.

## Retrospective Record

Historical implementation, commit, and verification claims are sourced from [`odd/tasks/cu-c02-catalog-filtering.md`](../../../odd/tasks/cu-c02-catalog-filtering.md). Root documentation evidence, where present:

- [`docs/CU-C02-FILTERING-CHANGES.md`](../../../docs/CU-C02-FILTERING-CHANGES.md)

ODD-recorded BFF verification:

- BFF `python -m pytest` — 10 passed.
- OpenAPI/Core GraphQL mapping and request validation are documented in the ODD implementation record.

- Pending verification: No browser-based visual validation or live end-to-end validation with running services and a database was performed, per the ODD record.

This plan is retrospective. It does not claim these implementation checks were rerun while generating this document. Behavior not verified by the cited ODD record remains pending.

## Complexity Tracking

No constitution violations or additional architectural components are recorded for this BFF feature.
