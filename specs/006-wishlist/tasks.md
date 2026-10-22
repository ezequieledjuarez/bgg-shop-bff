---
description: "Retrospective task list for CU-C06 in the BFF"
---

# Tasks: Wishlist

**Input**: [`spec.md`](./spec.md) and [`plan.md`](./plan.md)
**Prerequisites**: plan.md and spec.md
**Retrospective status**: All listed implementation tasks are checked complete based on the ODD record; this file does not independently verify past implementation.

## Format: `[ID] [P?] [Story] Description`

- **[P]** marks independent work; no parallel execution is inferred by this retrospective record.
- **[Story]** maps each task to a user story in plan.md.
- Descriptions use repository-relative paths such as `app.py`, `src/controllers/wishlist_controller.py`, `src/controllers/product_detail_controller.py`, `src/dtos/wishlist.py`, `src/dtos/products.py`, `src/services.py`, `src/proxy.py`, `specs/openapi.yaml`, `tests/test_wishlist.py`, `tests/test_products.py`.

## Path Conventions

All task paths are relative to the `bgg-shop-bff` repository root.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish the retrospective feature boundary from the existing contract, source, and ODD record.

- [x] T001 [US1] Map authenticated Wishlist REST routes and Core GraphQL operations.

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Record the existing REST-to-Core adapter surfaces required by the feature.

- [x] T002 [US1] Validate positive public BGG identifiers and preserve the caller's bearer header through the service/proxy adapter.

## Phase 3: User Story 1 - Manage a Wishlist (Priority: P1)

**Goal**: List, add, and remove products through authenticated REST operations without accepting client user IDs.

### Implementation for User Story 1

- [x] T003 [US1] Expose Wishlist list/add/remove routes with product mapping and authentication, missing-product, and generic-upstream error behavior.

## Phase 4: User Story 2 - Identify products from detail (Priority: P2)

**Goal**: Expose public bgg_id in game detail so callers need not depend on catalog-navigation state.

### Implementation for User Story 2

- [x] T004 [US2] Expose public bgg_id in the slug-based product detail DTO and contract for direct-route Wishlist actions.

## Phase N: Polish & Cross-Cutting Concerns

**Purpose**: Capture final contract, test, error-handling, and documentation work evidenced for this BFF feature.

- [x] T005 [US1] Align OpenAPI and BFF documentation; test authentication, validation, mapping, and upstream-detail sanitization.

## Dependencies & Execution Order

### Phase Dependencies

- Setup precedes the adapter foundation and user-story operations.
- DTO/service/proxy surfaces support the feature routes.
- User-story work uses the existing Flask application and OpenAPI contract; no new BFF storage layer is introduced.

### User Story Dependencies

- User Story 1 is the primary REST capability for CU-C06.
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

- Historical completion evidence: [`odd/tasks/cu-c06-wishlist.md`](../../../odd/tasks/cu-c06-wishlist.md).
- Feature source/test paths: `app.py`, `src/controllers/wishlist_controller.py`, `src/controllers/product_detail_controller.py`, `src/dtos/wishlist.py`, `src/dtos/products.py`, `src/services.py`, `src/proxy.py`, `specs/openapi.yaml`, `tests/test_wishlist.py`, `tests/test_products.py`.
- All task checkboxes are complete per the retrospective requirement; unverified behavior is listed separately.

## Retrospective Evidence

- Focused BFF Wishlist tests — 14 passed.
- Full BFF suite — 80 passed.
- Independent verification and parent spot-check passed; `git diff --check` passed.
- OpenAPI parser/validator was unavailable, as recorded in the ODD document.

## Pending Verification

- The additive Wishlist DDL and live authenticated Wishlist/purchase-confirmation flow were not run against PostgreSQL. OpenAPI parser validation was unavailable.
