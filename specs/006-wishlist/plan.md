# Implementation Plan: Wishlist

**Branch**: `CU-06-wishlist` | **Date**: 2026-10-21 | **Spec**: [`spec.md`](./spec.md)
**Input**: Feature specification from `/specs/006-wishlist/spec.md`

## Summary

The BFF adapts authenticated Wishlist list/add/remove operations to Core, forwards the exact Authorization header, validates public BGG IDs, and sanitizes upstream errors. Product detail also exposes bgg_id so clients can save a game from direct slug navigation.

## Technical Context

**Language/Version**: Python (runtime version not stated in the BFF feature record)
**Primary Dependencies**: Flask, Flask-CORS, Requests; see [`requirements.txt`](../../requirements.txt)
**Storage**: None in the BFF; persistent domain state is owned by Core, while cart identity is carried in a cookie where applicable
**Testing**: pytest
**Target Platform**: Flask REST service; deployment target is not specified in this feature record
**Project Type**: Web-service backend-for-frontend
**Performance Goals**: Not specified in the as-built BFF evidence
**Constraints**: Keep the public REST/OpenAPI contract aligned with the Core GraphQL adapter; validate inputs and avoid leaking upstream details
**Scale/Scope**: The BFF operations and test coverage listed for CU-C06 only

## Constitution Check

- **Pass** — retain the existing Flask/Python BFF and source contract at [`specs/openapi.yaml`](../openapi.yaml).
- **Pass** — keep controllers focused on HTTP behavior, DTOs on request/response shapes, services/proxy on Core orchestration and mapping; this plan adds no abstraction.
- **Pass** — public error responses follow the documented generic upstream behavior rather than exposing internal exception details.

## Project Structure

### Documentation (this feature)

```text
specs/006-wishlist/
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
- [`src/controllers/wishlist_controller.py`](../../src/controllers/wishlist_controller.py)
- [`src/controllers/product_detail_controller.py`](../../src/controllers/product_detail_controller.py)
- [`src/dtos/wishlist.py`](../../src/dtos/wishlist.py)
- [`src/dtos/products.py`](../../src/dtos/products.py)
- [`src/services.py`](../../src/services.py)
- [`src/proxy.py`](../../src/proxy.py)
- [`specs/openapi.yaml`](../../specs/openapi.yaml)
- [`tests/test_wishlist.py`](../../tests/test_wishlist.py)
- [`tests/test_products.py`](../../tests/test_products.py)

**Structure Decision**: Use the existing single Flask BFF repository and resource-oriented `src/controllers` and `src/dtos` modules. The REST contract remains `specs/openapi.yaml`; Core GraphQL remains upstream.

## User Stories in Scope

- **US1** — Manage a Wishlist: List, add, and remove products through authenticated REST operations without accepting client user IDs.
- **US2** — Identify products from detail: Expose public bgg_id in game detail so callers need not depend on catalog-navigation state.

## Retrospective Record

Historical implementation, commit, and verification claims are sourced from [`odd/tasks/cu-c06-wishlist.md`](../../../odd/tasks/cu-c06-wishlist.md). Root documentation evidence, where present:

- No CU-C06 root documentation file is listed in this source set.

ODD-recorded BFF verification:

- Focused BFF Wishlist tests — 14 passed.
- Full BFF suite — 80 passed.
- Independent verification and parent spot-check passed; `git diff --check` passed.
- OpenAPI parser/validator was unavailable, as recorded in the ODD document.

- Pending verification: The additive Wishlist DDL and live authenticated Wishlist/purchase-confirmation flow were not run against PostgreSQL. OpenAPI parser validation was unavailable.

This plan is retrospective. It does not claim these implementation checks were rerun while generating this document. Behavior not verified by the cited ODD record remains pending.

## Complexity Tracking

No constitution violations or additional architectural components are recorded for this BFF feature.

## Delegación a agentes

Objetivo: delegar la implementación de endpoints, orquestación GraphQL y pruebas de contrato a un agente automatizado que devuelva parches y pruebas locales sin hacer commits ni pushes.

- Allowed edit surfaces (ejemplos):
	- bgg-shop-bff/src/controllers/wishlist_controller.py
	- bgg-shop-bff/src/services.py
	- bgg-shop-bff/src/dtos/wishlist.py
	- specs/006-wishlist/*

- Qué entregar (por agente):
	- Parche/diff aplicable con los controladores y servicios implementados.
	- Tests de contrato y unitarios y su salida (logs) tras ejecutarlos.
	- Mensaje de commit propuesto (Conventional Commits).
	- Bloque "## Key Learnings:" con 1–5 puntos.

- Comandos de verificación recomendados:
	- `pip install -r requirements.txt`
	- `pytest tests/test_wishlist.py -q`

- Restricción importante: NO hacer commit ni push automático. Entregar `git diff` o parches en formato aplicable.

Colocar estas instrucciones en `plan.md` sitúa la delegación junto a la planificación técnica y las rutas de código objetivo, facilitando al agente las superficies de edición autorizadas.
