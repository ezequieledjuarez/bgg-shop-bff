# Implementation Plan: Shopping Cart

**Branch**: `CU-06-wishlist` | **Date**: 2026-10-21 | **Spec**: [`spec.md`](./spec.md)
**Input**: Feature specification from `/specs/004-shopping-cart/spec.md`

## Summary

The BFF adapts cart read/add/update/remove REST operations to Core, selecting account identity from Authorization or guest identity from an HttpOnly cookie. It validates item identifiers and quantities, maps cart totals/warnings, and returns guest cart identity as a cookie.

## Technical Context

**Language/Version**: Python (runtime version not stated in the BFF feature record)
**Primary Dependencies**: Flask, Flask-CORS, Requests; see [`requirements.txt`](../../requirements.txt)
**Storage**: None in the BFF; persistent domain state is owned by Core, while cart identity is carried in a cookie where applicable
**Testing**: pytest
**Target Platform**: Flask REST service; deployment target is not specified in this feature record
**Project Type**: Web-service backend-for-frontend
**Performance Goals**: Not specified in the as-built BFF evidence
**Constraints**: Keep the public REST/OpenAPI contract aligned with the Core GraphQL adapter; validate inputs and avoid leaking upstream details
**Scale/Scope**: The BFF operations and test coverage listed for CU-C04 only

## Constitution Check

- **Pass** — retain the existing Flask/Python BFF and source contract at [`specs/openapi.yaml`](../openapi.yaml).
- **Pass** — keep controllers focused on HTTP behavior, DTOs on request/response shapes, services/proxy on Core orchestration and mapping; this plan adds no abstraction.
- **Pass** — public error responses follow the documented generic upstream behavior rather than exposing internal exception details.

## Project Structure

### Documentation (this feature)

```text
specs/004-shopping-cart/
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
- [`src/controllers/cart_controller.py`](../../src/controllers/cart_controller.py)
- [`src/controllers/auth_controller.py`](../../src/controllers/auth_controller.py)
- [`src/dtos/cart.py`](../../src/dtos/cart.py)
- [`src/dtos/products.py`](../../src/dtos/products.py)
- [`src/services.py`](../../src/services.py)
- [`src/proxy.py`](../../src/proxy.py)
- [`specs/openapi.yaml`](../../specs/openapi.yaml)
- [`tests/test_cart.py`](../../tests/test_cart.py)
- [`tests/test_auth.py`](../../tests/test_auth.py)

**Structure Decision**: Use the existing single Flask BFF repository and resource-oriented `src/controllers` and `src/dtos` modules. The REST contract remains `specs/openapi.yaml`; Core GraphQL remains upstream.

## User Stories in Scope

- **US1** — Manage cart items: Read a cart and add, set quantity, or remove a product with validated REST inputs.
- **US2** — Preserve cart identity: Use bearer authentication in preference to the guest cookie and carry the guest identifier into login.

## Retrospective Record

Historical implementation, commit, and verification claims are sourced from [`odd/tasks/cu-c04-shopping-cart.md`](../../../odd/tasks/cu-c04-shopping-cart.md). Root documentation evidence, where present:

- [`docs/CU-C04-SHOPPING-CART.md`](../../../docs/CU-C04-SHOPPING-CART.md)

ODD-recorded BFF verification:

- Final BFF `python -m pytest -q` — 36 passed.
- BFF `git diff --check` — clean.
- OpenAPI YAML parsing and cart/inventory route/field checks — passed, as reported in the ODD record.

- Pending verification: Database DDL/bootstrap was inspected but not executed against PostgreSQL. Guest-to-account cart merge was not live-verified, per the ODD record.

This plan is retrospective. It does not claim these implementation checks were rerun while generating this document. Behavior not verified by the cited ODD record remains pending.

## Complexity Tracking

No constitution violations or additional architectural components are recorded for this BFF feature.
