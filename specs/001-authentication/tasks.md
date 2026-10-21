---
description: "Retrospective task list for CU-C01 in the BFF"
---

# Tasks: Customer Authentication

**Input**: [`spec.md`](./spec.md) and [`plan.md`](./plan.md)
**Prerequisites**: plan.md and spec.md
**Retrospective status**: All listed implementation tasks are checked complete based on the ODD record; this file does not independently verify past implementation.

## Format: `[ID] [P?] [Story] Description`

- **[P]** marks independent work; no parallel execution is inferred by this retrospective record.
- **[Story]** maps each task to a user story in plan.md.
- Descriptions use repository-relative paths such as `app.py`, `src/controllers/auth_controller.py`, `src/dtos/auth.py`, `src/services.py`, `src/proxy.py`, `specs/openapi.yaml`, `tests/test_auth.py`, `tests/test_cart.py`.

## Path Conventions

All task paths are relative to the `bgg-shop-bff` repository root.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish the retrospective feature boundary from the existing contract, source, and ODD record.

- [x] T001 [US1] Map authentication routes, Core proxy responsibilities, and the OpenAPI contract.

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Record the existing REST-to-Core adapter surfaces required by the feature.

- [x] T002 [US1] Provide authentication request/response DTOs and service/controller adapters in the existing Flask layering.

## Phase 3: User Story 1 - Register a buyer (Priority: P1)

**Goal**: Validate registration input and return the created user without a session.

### Implementation for User Story 1

- [x] T003 [US1] Expose registration with request validation, Core field mapping, and a user-only success response.

## Phase 4: User Story 2 - Authenticate a buyer (Priority: P2)

**Goal**: Return the Core-issued session and pass guest-cart identity to Core when available.

### Implementation for User Story 2

- [x] T004 [US2] Expose login with Core session mapping and guest-cart cookie forwarding/clearing on success.

## Phase N: Polish & Cross-Cutting Concerns

**Purpose**: Capture final contract, test, error-handling, and documentation work evidenced for this BFF feature.

- [x] T005 [US2] Translate validation, duplicate-email, invalid-credential, and unexpected upstream outcomes; cover auth and login/cart handoff tests and update CU-C01 documentation.

## Dependencies & Execution Order

### Phase Dependencies

- Setup precedes the adapter foundation and user-story operations.
- DTO/service/proxy surfaces support the feature routes.
- User-story work uses the existing Flask application and OpenAPI contract; no new BFF storage layer is introduced.

### User Story Dependencies

- User Story 1 is the primary REST capability for CU-C01.
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

- Historical completion evidence: [`odd/tasks/cu-c01-layered-bff.md`](../../../odd/tasks/cu-c01-layered-bff.md).
- Feature source/test paths: `app.py`, `src/controllers/auth_controller.py`, `src/dtos/auth.py`, `src/services.py`, `src/proxy.py`, `specs/openapi.yaml`, `tests/test_auth.py`, `tests/test_cart.py`.
- All task checkboxes are complete per the retrospective requirement; unverified behavior is listed separately.

## Retrospective Evidence

- `python -m pytest` — 19 passed.
- `python -m compileall -q app.py src tests` — passed.
- `git diff --check` — passed.

## Pending Verification

- The ODD records do not report an unresolved BFF authentication verification item. Browser session behavior and Core persistence are outside this BFF-only plan.
