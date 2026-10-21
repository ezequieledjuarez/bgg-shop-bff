---
description: "Retrospective task list for CU-C05 in the BFF"
---

# Tasks: Checkout, Orders, and Invoice

**Input**: [`spec.md`](./spec.md) and [`plan.md`](./plan.md)
**Prerequisites**: plan.md and spec.md
**Retrospective status**: All listed implementation tasks are checked complete based on the ODD record; this file does not independently verify past implementation.

## Format: `[ID] [P?] [Story] Description`

- **[P]** marks independent work; no parallel execution is inferred by this retrospective record.
- **[Story]** maps each task to a user story in plan.md.
- Descriptions use repository-relative paths such as `app.py`, `src/controllers/orders_controller.py`, `src/dtos/orders.py`, `src/services.py`, `src/proxy.py`, `specs/openapi.yaml`, `tests/test_orders.py`.

## Path Conventions

All task paths are relative to the `bgg-shop-bff` repository root.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish the retrospective feature boundary from the existing contract, source, and ODD record.

- [x] T001 [US1] Map the BFF purchase endpoints and authenticated Core GraphQL/invoice adapter responsibilities.

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Record the existing REST-to-Core adapter surfaces required by the feature.

- [x] T002 [US1] Validate checkout address/shipping mode, UUID order IDs, payment IDs, and supported payload fields.

## Phase 3: User Story 1 - Start and confirm checkout (Priority: P1)

**Goal**: Submit validated delivery details, confirm payment with Core, and retry payment when supported.

### Implementation for User Story 1

- [x] T003 [US1] Expose authenticated checkout, confirmation, and retry endpoints with Core response and error mapping.

## Phase 4: User Story 2 - View orders and invoice (Priority: P2)

**Goal**: List or inspect authenticated orders and stream the corresponding invoice response.

### Implementation for User Story 2

- [x] T004 [US2] Expose authenticated order list/detail and stream invoice PDF bytes after the proxy authorization check.

## Phase N: Polish & Cross-Cutting Concerns

**Purpose**: Capture final contract, test, error-handling, and documentation work evidenced for this BFF feature.

- [x] T005 [US2] Document endpoint schemas and cover authentication, validation, proxy mapping, invoice streaming, and sanitized errors in order tests.

## Dependencies & Execution Order

### Phase Dependencies

- Setup precedes the adapter foundation and user-story operations.
- DTO/service/proxy surfaces support the feature routes.
- User-story work uses the existing Flask application and OpenAPI contract; no new BFF storage layer is introduced.

### User Story Dependencies

- User Story 1 is the primary REST capability for CU-C05.
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

- Historical completion evidence: [`odd/tasks/cu-c05-purchase.md`](../../../odd/tasks/cu-c05-purchase.md).
- Feature source/test paths: `app.py`, `src/controllers/orders_controller.py`, `src/dtos/orders.py`, `src/services.py`, `src/proxy.py`, `specs/openapi.yaml`, `tests/test_orders.py`.
- All task checkboxes are complete per the retrospective requirement; unverified behavior is listed separately.

## Retrospective Evidence

- BFF `.venv/bin/python -m pytest -q` — 66 passed.
- The ODD record reports structural review of OpenAPI paths/refs; YAML parser validation was unavailable because PyYAML and Ruby were not installed.
- No live payment or Core request was made by the BFF verification described in the ODD record.

## Pending Verification

- Payment with the sandbox buyer, paid transition, stock decrement, invoice persistence/PDF download, cart quantity clearing, and full guest-cart merge remain unverified. Full import_catalog.sql validation on a clean PostgreSQL is also unverified in the ODD record.
