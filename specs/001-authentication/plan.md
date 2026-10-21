# Implementation Plan: Customer Authentication

**Branch**: `CU-06-wishlist` | **Date**: 2026-10-21 | **Spec**: [`spec.md`](./spec.md)
**Input**: Feature specification from `/specs/001-authentication/spec.md`

## Summary

The BFF exposes registration and login over REST, validates and reshapes payloads, forwards GraphQL operations to Core, maps user/session fields, and returns generic upstream errors. Login also forwards a guest-cart identifier when present and clears its cookie after success.

## Technical Context

**Language/Version**: Python (runtime version not stated in the BFF feature record)
**Primary Dependencies**: Flask, Flask-CORS, Requests; see [`requirements.txt`](../../requirements.txt)
**Storage**: None in the BFF; persistent domain state is owned by Core, while cart identity is carried in a cookie where applicable
**Testing**: pytest
**Target Platform**: Flask REST service; deployment target is not specified in this feature record
**Project Type**: Web-service backend-for-frontend
**Performance Goals**: Not specified in the as-built BFF evidence
**Constraints**: Keep the public REST/OpenAPI contract aligned with the Core GraphQL adapter; validate inputs and avoid leaking upstream details
**Scale/Scope**: The BFF operations and test coverage listed for CU-C01 only

## Constitution Check

- **Pass** — retain the existing Flask/Python BFF and source contract at [`specs/openapi.yaml`](../openapi.yaml).
- **Pass** — keep controllers focused on HTTP behavior, DTOs on request/response shapes, services/proxy on Core orchestration and mapping; this plan adds no abstraction.
- **Pass** — public error responses follow the documented generic upstream behavior rather than exposing internal exception details.

## Project Structure

### Documentation (this feature)

```text
specs/001-authentication/
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
- [`src/controllers/auth_controller.py`](../../src/controllers/auth_controller.py)
- [`src/dtos/auth.py`](../../src/dtos/auth.py)
- [`src/services.py`](../../src/services.py)
- [`src/proxy.py`](../../src/proxy.py)
- [`specs/openapi.yaml`](../../specs/openapi.yaml)
- [`tests/test_auth.py`](../../tests/test_auth.py)
- [`tests/test_cart.py`](../../tests/test_cart.py)

**Structure Decision**: Use the existing single Flask BFF repository and resource-oriented `src/controllers` and `src/dtos` modules. The REST contract remains `specs/openapi.yaml`; Core GraphQL remains upstream.

## User Stories in Scope

- **US1** — Register a buyer: Validate registration input and return the created user without a session.
- **US2** — Authenticate a buyer: Return the Core-issued session and pass guest-cart identity to Core when available.

## Retrospective Record

Historical implementation, commit, and verification claims are sourced from [`odd/tasks/cu-c01-layered-bff.md`](../../../odd/tasks/cu-c01-layered-bff.md). Root documentation evidence, where present:

- [`docs/CU-C01-AUTHENTICATION-CHANGES.md`](../../../docs/CU-C01-AUTHENTICATION-CHANGES.md)
- [`docs/CU-C01-C03-E2E-VALIDATION.md`](../../../docs/CU-C01-C03-E2E-VALIDATION.md)

ODD-recorded BFF verification:

- `python -m pytest` — 19 passed.
- `python -m compileall -q app.py src tests` — passed.
- `git diff --check` — passed.

- No BFF-specific pending verification is recorded in the ODD task file; browser session behavior and Core persistence are outside this BFF-only plan.

This plan is retrospective. It does not claim these implementation checks were rerun while generating this document. Behavior not verified by the cited ODD record remains pending.

## Complexity Tracking

No constitution violations or additional architectural components are recorded for this BFF feature.
