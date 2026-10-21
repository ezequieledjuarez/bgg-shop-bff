---
description: "Retrospective task list for CU-C03 in the BFF"
---

# Tasks: Product Detail and Reviews

**Input**: [`spec.md`](./spec.md) and [`plan.md`](./plan.md)
**Prerequisites**: plan.md and spec.md
**Retrospective status**: All listed implementation tasks are checked complete based on the ODD record; this file does not independently verify past implementation.

## Format: `[ID] [P?] [Story] Description`

- **[P]** marks independent work; no parallel execution is inferred by this retrospective record.
- **[Story]** maps each task to a user story in plan.md.
- Descriptions use repository-relative paths such as `app.py`, `src/controllers/product_detail_controller.py`, `src/controllers/reviews_controller.py`, `src/dtos/products.py`, `src/services.py`, `src/proxy.py`, `specs/openapi.yaml`, `tests/test_products.py`, `tests/test_reviews.py`.

## Path Conventions

All task paths are relative to the `bgg-shop-bff` repository root.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish the retrospective feature boundary from the existing contract, source, and ODD record.

- [x] T001 [US1] Map the slug-based detail and review REST operations to their Core GraphQL operations.

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Record the existing REST-to-Core adapter surfaces required by the feature.

- [x] T002 [US1] Define detail and review DTO mappings through the existing product DTO and service/proxy modules.

## Phase 3: User Story 1 - Read product detail (Priority: P1)

**Goal**: Return product attributes, review summary, and approved reviews for a public slug.

### Implementation for User Story 1

- [x] T003 [US1] Expose public game detail by slug with product fields, review summary, approved reviews, and not-found mapping.

## Phase 4: User Story 2 - Submit a review (Priority: P2)

**Goal**: Validate rating/body, require authorization, forward the request, and map the pending-review response.

### Implementation for User Story 2

- [x] T004 [US2] Validate integer rating 1–5 and nonblank body up to 2,000 characters; require and forward Authorization for review creation.

## Phase N: Polish & Cross-Cutting Concerns

**Purpose**: Capture final contract, test, error-handling, and documentation work evidenced for this BFF feature.

- [x] T005 [US2] Map known review outcomes and sanitize unexpected upstream errors; maintain product/review contract and focused tests.

## Dependencies & Execution Order

### Phase Dependencies

- Setup precedes the adapter foundation and user-story operations.
- DTO/service/proxy surfaces support the feature routes.
- User-story work uses the existing Flask application and OpenAPI contract; no new BFF storage layer is introduced.

### User Story Dependencies

- User Story 1 is the primary REST capability for CU-C03.
- Additional user stories use the shared Core adapter and REST contract.

### Within Each User Story

- Validation and Core mapping underpin controller outcomes.
- Tests and contract documentation cover behavior reported in the ODD record.

### Parallel Opportunities

- The ODD record does not establish parallel BFF execution; no parallelism is claimed here.

## Parallel Example: User Story 1

No parallel execution is asserted by this retrospective task list.

## Implementation Strategy

### MVP First (User Story 1 Only)

The primary BFF REST operation set is identified as User Story 1; completion is retrospective, not a newly proposed MVP.

### Incremental Delivery

The ODD task record is the source for historical sequence and evidence; this document does not claim a new delivery sequence.

### Parallel Team Strategy

No parallel task execution is inferred. Keep the existing OpenAPI contract and Core GraphQL service boundary.

## Notes

- Historical completion evidence: [`odd/tasks/cu-c03-product-reviews.md`](../../../odd/tasks/cu-c03-product-reviews.md).
- Feature source/test paths: `app.py`, `src/controllers/product_detail_controller.py`, `src/controllers/reviews_controller.py`, `src/dtos/products.py`, `src/services.py`, `src/proxy.py`, `specs/openapi.yaml`, `tests/test_products.py`, `tests/test_reviews.py`.
- All task checkboxes are complete per the retrospective requirement; unverified behavior is listed separately.

## Retrospective Evidence

- BFF `python -m pytest` — 19 passed, as recorded in the CU-C03 ODD verification.

## Pending Verification

- PostgreSQL parser validation for review persistence remains pending because `psql` is unavailable, as recorded in the CU-C03 ODD document.
