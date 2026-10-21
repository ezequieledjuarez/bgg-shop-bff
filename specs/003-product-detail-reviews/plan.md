# Implementation Plan: Product Detail and Reviews

**Branch**: `CU-06-wishlist` | **Date**: 2026-10-21 | **Spec**: [`spec.md`](./spec.md)
**Input**: Feature specification from `/specs/003-product-detail-reviews/spec.md`

## Summary

The BFF provides slug-based game detail and authenticated review creation. It maps Core detail/review results to REST DTOs, validates review input, forwards the caller's Authorization value, and translates known errors without exposing unexpected upstream details.

## Technical Context

**Language/Version**: Python (runtime version not stated in the BFF feature record)
**Primary Dependencies**: Flask, Flask-CORS, Requests; see [`requirements.txt`](../../requirements.txt)
**Storage**: None in the BFF; persistent domain state is owned by Core, while cart identity is carried in a cookie where applicable
**Testing**: pytest
**Target Platform**: Flask REST service; deployment target is not specified in this feature record
**Project Type**: Web-service backend-for-frontend
**Performance Goals**: Not specified in the as-built BFF evidence
**Constraints**: Keep the public REST/OpenAPI contract aligned with the Core GraphQL adapter; validate inputs and avoid leaking upstream details
**Scale/Scope**: The BFF operations and test coverage listed for CU-C03 only

## Constitution Check

- **Pass** — retain the existing Flask/Python BFF and source contract at [`specs/openapi.yaml`](../openapi.yaml).
- **Pass** — keep controllers focused on HTTP behavior, DTOs on request/response shapes, services/proxy on Core orchestration and mapping; this plan adds no abstraction.
- **Pass** — public error responses follow the documented generic upstream behavior rather than exposing internal exception details.

## Project Structure

### Documentation (this feature)

```text
specs/003-product-detail-reviews/
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
- [`src/controllers/product_detail_controller.py`](../../src/controllers/product_detail_controller.py)
- [`src/controllers/reviews_controller.py`](../../src/controllers/reviews_controller.py)
- [`src/dtos/products.py`](../../src/dtos/products.py)
- [`src/services.py`](../../src/services.py)
- [`src/proxy.py`](../../src/proxy.py)
- [`specs/openapi.yaml`](../../specs/openapi.yaml)
- [`tests/test_products.py`](../../tests/test_products.py)
- [`tests/test_reviews.py`](../../tests/test_reviews.py)

**Structure Decision**: Use the existing single Flask BFF repository and resource-oriented `src/controllers` and `src/dtos` modules. The REST contract remains `specs/openapi.yaml`; Core GraphQL remains upstream.

## User Stories in Scope

- **US1** — Read product detail: Return product attributes, review summary, and approved reviews for a public slug.
- **US2** — Submit a review: Validate rating/body, require authorization, forward the request, and map the pending-review response.

## Retrospective Record

Historical implementation, commit, and verification claims are sourced from [`odd/tasks/cu-c03-product-reviews.md`](../../../odd/tasks/cu-c03-product-reviews.md). Root documentation evidence, where present:

- [`docs/CU-C03-REVIEWS.md`](../../../docs/CU-C03-REVIEWS.md)
- [`docs/CU-C01-C03-E2E-VALIDATION.md`](../../../docs/CU-C01-C03-E2E-VALIDATION.md)

ODD-recorded BFF verification:

- BFF `python -m pytest` — 19 passed, as recorded in the CU-C03 ODD verification.

- Pending verification: PostgreSQL parser validation for review persistence remains pending because `psql` is unavailable, as recorded in the CU-C03 ODD document.

This plan is retrospective. It does not claim these implementation checks were rerun while generating this document. Behavior not verified by the cited ODD record remains pending.

## Complexity Tracking

No constitution violations or additional architectural components are recorded for this BFF feature.
