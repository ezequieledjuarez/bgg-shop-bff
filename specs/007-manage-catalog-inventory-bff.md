# CU-A01 — BFF Responsibilities (Flask)

Reference: ../007-manage-catalog-inventory/spec.md

## Purpose
Actuar como capa de orquestación y adaptación entre el Core (fuente de verdad) y el Frontend, implementando validaciones de entrada, control de permisos administrativos y transformación de contratos.

## Responsibilities
- Exponer endpoints públicos/administrativos consumidos por la UI de administración.
- Validar autorizaciones (rol Admin) y sanitizar payloads antes de enviarlos al Core.
- Implementar endpoints que traduzcan/adjunten datos entre Frontend y Core internal API.
- Gestionar lógica de presentación de promociones (resolución de aplicar/mostrar precios) y cachear respuestas de catálogo para rendimiento (invalidadas por eventos del Core).
- Implementar endpoints de auditoría y búsquedas simplificadas para el Admin UI.
- Encolar o propagar eventos a otros servicios (ej. notificaciones) cuando sea necesario.

## Suggested Endpoints (Admin-facing)
- GET /admin/products?page=&limit=&q= → list for admin UI (with metadata)
- POST /admin/products → create product (validates payload, forwards to core)
- PUT /admin/products/{id} → update product
- POST /admin/products/{id}/variants/{vid}/adjust-stock → {new_stock:int} → validates against core response
- POST /admin/promotions → create/update promotion
- POST /admin/coupons/{code}/apply → attempts apply (for preview) — note: final decrement should be done by core at checkout
- GET /admin/audit?entity=product&id=...

Notes: BFF should avoid duplicating authoritative logic (stock reservation, coupon counters); defer to Core and present friendly errors.

## Acceptance Criteria (BFF)
- AC-BFF-1: Admin endpoints authenticate and authorize correctly; unauthorized calls return 403.
- AC-BFF-2: Input payloads are validated with clear field-level errors returned to the frontend.
- AC-BFF-3: BFF translates errors from Core into user-friendly messages and consistent HTTP codes.
- AC-BFF-4: Cache invalidation occurs within X seconds (configurable) after receiving product/stock/promotion events from Core.

## Tests (BFF)
- Contract tests ensuring requests/responses match Core API expectations.
- Integration tests simulating Core failures and verifying BFF error mapping.
- Authorization tests for admin roles.

## Integration Points
- Core internal API (endpoints and event bus). Provide exact schemas and error codes.
- Frontend admin UI endpoints and shapes.

## Next steps
- Define exact JSON schemas and error codes with the Core team.
- Implement lightweight caching strategy and event listener for invalidation.
