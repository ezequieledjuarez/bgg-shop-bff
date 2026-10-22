---
description: "Retrospective task list for CU-C02 in the BFF"
---

# Tasks: Catalog Search and Filters

**Input**: [`spec.md`](./spec.md) and [`plan.md`](./plan.md)
**Prerequisites**: plan.md and spec.md
**Retrospective status**: All listed implementation tasks are checked complete based on the ODD record; this file does not independently verify past implementation.

## Format: `[ID] [P?] [Story] Description`

- **[P]** marks independent work; no parallel execution is inferred by this retrospective record.
- **[Story]** maps each task to a user story in plan.md.
- Descriptions use repository-relative paths such as `app.py`, `src/controllers/products_controller.py`, `src/dtos/products.py`, `src/services.py`, `src/proxy.py`, `specs/openapi.yaml`, `tests/test_products.py`.

## Path Conventions

All task paths are relative to the `bgg-shop-bff` repository root.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish the retrospective feature boundary from the existing contract, source, and ODD record.

- [x] T001 [US1] Map the existing paginated products REST contract and supported query parameters.

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Record the existing REST-to-Core adapter surfaces required by the feature.

- [x] T002 [US1] Model query parameters and validate pagination, search, numeric bounds, and inverted filter ranges.

## Phase 3: User Story 1 - List and filter products (Priority: P1)

**Goal**: Forward validated catalog criteria and preserve pagination metadata and upstream failure behavior.

### Implementation for User Story 1

- [x] T003 [US1] Forward validated filters through the service/proxy to Core GraphQL and map product/page fields to the REST response.

## Phase N: Polish & Cross-Cutting Concerns

**Purpose**: Capture final contract, test, error-handling, and documentation work evidenced for this BFF feature.

- [x] T004 [US1] Cover query forwarding, response mapping, validation, CORS, and upstream failure behavior in product tests; preserve the contract in OpenAPI.

## Dependencies & Execution Order

### Phase Dependencies

- Setup precedes the adapter foundation and user-story operations.
- DTO/service/proxy surfaces support the feature routes.
- User-story work uses the existing Flask application and OpenAPI contract; no new BFF storage layer is introduced.

### User Story Dependencies

- User Story 1 is the primary REST capability for CU-C02.
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

- Historical completion evidence: [`odd/tasks/cu-c02-catalog-filtering.md`](../../../odd/tasks/cu-c02-catalog-filtering.md).
- Feature source/test paths: `app.py`, `src/controllers/products_controller.py`, `src/dtos/products.py`, `src/services.py`, `src/proxy.py`, `specs/openapi.yaml`, `tests/test_products.py`.
- All task checkboxes are complete per the retrospective requirement; unverified behavior is listed separately.

## Retrospective Evidence

- BFF `python -m pytest` — 10 passed.
- OpenAPI/Core GraphQL mapping and request validation are documented in the ODD implementation record.

## Pending Verification

- No browser-based visual validation or live end-to-end validation with running services and a database was performed, per the ODD record.
