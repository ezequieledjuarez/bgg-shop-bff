# Implementation Plan: Checkout, Orders, and Invoice

**Branch**: `CU-06-wishlist` | **Date**: 2026-10-21 | **Spec**: [`spec.md`](./spec.md)
**Input**: Feature specification from `/specs/005-checkout-orders-invoice/spec.md`

## Summary

The BFF exposes authenticated checkout, payment confirmation/retry, order history/detail, and PDF invoice operations. It validates shipping/address/payment/order identifiers, forwards the buyer's Authorization value to Core, streams invoice bytes, and translates public errors.

## Technical Context

**Language/Version**: Python (runtime version not stated in the BFF feature record)
**Primary Dependencies**: Flask, Flask-CORS, Requests; see [`requirements.txt`](../../requirements.txt)
**Storage**: None in the BFF; persistent domain state is owned by Core, while cart identity is carried in a cookie where applicable
**Testing**: pytest
**Target Platform**: Flask REST service; deployment target is not specified in this feature record
**Project Type**: Web-service backend-for-frontend
**Performance Goals**: Not specified in the as-built BFF evidence
**Constraints**: Keep the public REST/OpenAPI contract aligned with the Core GraphQL adapter; validate inputs and avoid leaking upstream details
**Scale/Scope**: The BFF operations and test coverage listed for CU-C05 only

## Constitution Check

- **Pass** — retain the existing Flask/Python BFF and source contract at [`specs/openapi.yaml`](../openapi.yaml).
- **Pass** — keep controllers focused on HTTP behavior, DTOs on request/response shapes, services/proxy on Core orchestration and mapping; this plan adds no abstraction.
- **Pass** — public error responses follow the documented generic upstream behavior rather than exposing internal exception details.

## Project Structure

### Documentation (this feature)

```text
specs/005-checkout-orders-invoice/
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
- [`src/controllers/orders_controller.py`](../../src/controllers/orders_controller.py)
- [`src/dtos/orders.py`](../../src/dtos/orders.py)
- [`src/services.py`](../../src/services.py)
- [`src/proxy.py`](../../src/proxy.py)
- [`specs/openapi.yaml`](../../specs/openapi.yaml)
- [`tests/test_orders.py`](../../tests/test_orders.py)

**Structure Decision**: Use the existing single Flask BFF repository and resource-oriented `src/controllers` and `src/dtos` modules. The REST contract remains `specs/openapi.yaml`; Core GraphQL remains upstream.

## User Stories in Scope

- **US1** — Start and confirm checkout: Submit validated delivery details, confirm payment with Core, and retry payment when supported.
- **US2** — View orders and invoice: List or inspect authenticated orders and stream the corresponding invoice response.

## Retrospective Record

Historical implementation, commit, and verification claims are sourced from [`odd/tasks/cu-c05-purchase.md`](../../../odd/tasks/cu-c05-purchase.md). Root documentation evidence, where present:

- [`docs/CU-C05-PURCHASE.md`](../../../docs/CU-C05-PURCHASE.md)

ODD-recorded BFF verification:

- BFF `.venv/bin/python -m pytest -q` — 66 passed.
- The ODD record reports structural review of OpenAPI paths/refs; YAML parser validation was unavailable because PyYAML and Ruby were not installed.
- No live payment or Core request was made by the BFF verification described in the ODD record.

- Pending verification: Payment with the sandbox buyer, paid transition, stock decrement, invoice persistence/PDF download, cart quantity clearing, and full guest-cart merge remain unverified. Full import_catalog.sql validation on a clean PostgreSQL is also unverified in the ODD record.

This plan is retrospective. It does not claim these implementation checks were rerun while generating this document. Behavior not verified by the cited ODD record remains pending.

## Complexity Tracking

No constitution violations or additional architectural components are recorded for this BFF feature.
