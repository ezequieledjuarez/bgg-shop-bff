---
description: "Retrospective task list for CU-C04 in the BFF"
---

# Tasks: Shopping Cart

**Input**: [`spec.md`](./spec.md) and [`plan.md`](./plan.md)
**Prerequisites**: plan.md and spec.md
**Retrospective status**: All listed implementation tasks are checked complete based on the ODD record; this file does not independently verify past implementation.

## Format: `[ID] [P?] [Story] Description`

- **[P]** marks independent work; no parallel execution is inferred by this retrospective record.
- **[Story]** maps each task to a user story in plan.md.
- Descriptions use repository-relative paths such as `app.py`, `src/controllers/cart_controller.py`, `src/controllers/auth_controller.py`, `src/dtos/cart.py`, `src/dtos/products.py`, `src/services.py`, `src/proxy.py`, `specs/openapi.yaml`, `tests/test_cart.py`, `tests/test_auth.py`.

## Path Conventions

All task paths are relative to the `bgg-shop-bff` repository root.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish the retrospective feature boundary from the existing contract, source, and ODD record.

- [x] T001 [US1] Map the cart REST contract, Core operations, and guest/account identity selection.

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Record the existing REST-to-Core adapter surfaces required by the feature.

- [x] T002 [US1] Validate cart item DTOs and GraphQL Int bounds; map Core cart lines, totals, and warnings.

## Phase 3: User Story 1 - Manage cart items (Priority: P1)

**Goal**: Read a cart and add, set quantity, or remove a product with validated REST inputs.

### Implementation for User Story 1

- [x] T003 [US1] Expose cart read/add/update/remove routes through controllers, services, and the Core proxy.

## Phase 4: User Story 2 - Preserve cart identity (Priority: P2)

**Goal**: Use bearer authentication in preference to the guest cookie and carry the guest identifier into login.

### Implementation for User Story 2

- [x] T004 [US2] Set the guest cart cookie with the documented attributes, prefer Authorization for account carts, and forward/clear the guest identifier during login.

## Phase N: Polish & Cross-Cutting Concerns

**Purpose**: Capture final contract, test, error-handling, and documentation work evidenced for this BFF feature.

- [x] T005 [US1] Map stock and product warnings to REST statuses; update OpenAPI/product inventory fields and cover cart behavior with tests.

## Dependencies & Execution Order

### Phase Dependencies

- Setup precedes the adapter foundation and user-story operations.
- DTO/service/proxy surfaces support the feature routes.
- User-story work uses the existing Flask application and OpenAPI contract; no new BFF storage layer is introduced.

### User Story Dependencies

- User Story 1 is the primary REST capability for CU-C04.
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

- Historical completion evidence: [`odd/tasks/cu-c04-shopping-cart.md`](../../../odd/tasks/cu-c04-shopping-cart.md).
- Feature source/test paths: `app.py`, `src/controllers/cart_controller.py`, `src/controllers/auth_controller.py`, `src/dtos/cart.py`, `src/dtos/products.py`, `src/services.py`, `src/proxy.py`, `specs/openapi.yaml`, `tests/test_cart.py`, `tests/test_auth.py`.
- All task checkboxes are complete per the retrospective requirement; unverified behavior is listed separately.

## Retrospective Evidence

- Final BFF `python -m pytest -q` — 36 passed.
- BFF `git diff --check` — clean.
- OpenAPI YAML parsing and cart/inventory route/field checks — passed, as reported in the ODD record.

## Pending Verification

- Database DDL/bootstrap was inspected but not executed against PostgreSQL. Guest-to-account cart merge was not live-verified, per the ODD record.
