# CU-A01 — BFF Responsibilities (Flask)

Reference: ../007-manage-catalog-inventory/spec.md

## Purpose
Actuar como capa de orquestación y adaptación entre el Core (fuente de verdad) y el Frontend, implementando validaciones de entrada, control de permisos administrativos y transformación de contratos.

## Responsibilities
- Exponer endpoints públicos/administrativos consumidos por la UI de administración.
- Validar autorizaciones (rol Admin) y sanitizar payloads antes de enviarlos al Core.
- Implementar endpoints que traduzcan/adjunten datos entre Frontend y Core internal API.
- Gestionar lógica de presentación de promociones (resolución de aplicar/mostrar precios) y cachear respuestas de catálogo para rendimiento (invalidadas por eventos del Core).
- Prever consultas de auditoría para el Admin UI; las búsquedas simplificadas son una propuesta sujeta a las decisiones pendientes.
- Encolar o propagar eventos a otros servicios (ej. notificaciones) cuando sea necesario.

La auditoría básica requerida cubre cambios de productos, movimientos de stock,
promociones y cupones, con usuario, fecha, acción y valores anteriores y nuevos.
La auditoría básica permanece en el alcance actual. Para la solución futura se
prevén siete días en la base y un ZIP local semanal; no se eliminarán filas sin
verificar antes la creación correcta del archivo y no se acuerda purga automática.
Queda pendiente compatibilizar la frecuencia
semanal con la retirada exactamente a los siete días: ambas podrían retrasarse.
Los ZIP no vencen ni se eliminan automáticamente; su eliminación manual queda a
cargo del usuario y solo está autorizada para `is_superuser=true`. `is_staff=true`
por sí solo no basta. La generación semanal del ZIP y el mecanismo que hace cumplir
el permiso de borrado quedan pendientes y fuera del alcance actual de la 007. No se
afirma que se aplique en el filesystem. La retención es indefinida hasta la eliminación manual. La
decisión anterior de conservar los ZIP un mes queda reemplazada. Esta política
no se considera implementada ni validada. Siguen pendientes el inicio de los
siete días, el horario, el mecanismo de archivo atómico ante fallas, el acceso y
consulta de archivos y el cifrado.
También siguen pendientes el acceso a la auditoría, filtros, paginación
y captura de secretos; los ejemplos de filtros no están confirmados. Las
consultas y rutas sugeridas no constituyen un contrato aprobado. La existencia
de AuditLog no acredita su uso en todos los flujos ni conformidad.

## Suggested Endpoints (Admin-facing)
- Si una operación `IN`/`OUT` no impacta la base, se cancela o rechaza; una transacción efectivamente rechazada o revertida no deja el cambio aplicado. Si se confirma el rechazo o rollback sin cambios en la base, se permite procesar nuevamente un reintento con el mismo ID y datos. Un error de comunicación o HTTP no demuestra rollback: el servidor puede confirmar y perderse la respuesta, y un reintento aditivo podría duplicar la operación actual. Se informa al usuario y se registra el error de forma segura sin detalles sensibles, sin suponer seguro reintentar con el contrato actual. Cada movimiento tendrá un ID único; el mismo ID y datos no deben duplicar el cambio, y reutilizarlo con datos diferentes debe rechazar la operación sin aplicar un nuevo cambio de stock. El ID puede registrarse provisionalmente como IN_PROGRESS; el cambio de stock, la auditoría y el resultado definitivo deben confirmarse atómicamente. Los ID de movimientos exitosos se conservarán indefinidamente, sin vencimiento, también ante reintentos tardíos; fuera de la posibilidad de reintento indicada, el plazo y tratamiento de ID de fallos o rechazos no están aprobados. Quedan abiertos formato y alcance del ID, campos que determinan la identidad de los datos, detalles de la respuesta de rechazo, respuesta a reintentos de una operación aún en curso y recuperación del resultado incierto. Definir y validar primero el contrato; la implementación no está acreditada.
- GET /admin/products?page=&limit=&q= → list for admin UI (with metadata)
- POST /admin/products → create product (validates payload, forwards to core)
- PUT /admin/products/{id} → update product
- POST /api/v1/admin/products/{product_id}/stock → {movement_id: UUID, direction: IN|OUT, quantity: positive 32-bit integer}; returns the movement status and applied result.
- POST /admin/promotions → create/update promotion
- POST `/api/v1/cart/coupons/preview` previews a coupon against the authenticated user's current cart without reserving or consuming a use. Checkout receives the selected code and reserves it atomically; confirmed failure/cancellation releases it, while uncertain outcomes remain reserved for provider reconciliation and manual review if unresolved. A timeout alone never releases it.
- GET /admin/audit?entity=product&id=...

Notes: Each game edition or variant is a separate product. The BFF delegates UUID-bound `IN` and `OUT` movements to Core `adjustProductStock`; the legacy UUID-less mutation rejects writes. `OUT` is limited to available stock and returns a warning when it is reduced. A provisional `IN_PROGRESS` record may remain after a crash; recovery is not yet implemented. Migrations 0012 and 0013 were tested on disposable PostgreSQL but not applied to the active database. BFF defers authoritative business logic to Core. An invalid JWT returns 401 and a non-admin JWT returns 403; a validated OpKey may authorize the requested admin route. An invalid OpKey returns 401, while an unavailable or malformed Core validation response returns 502 when no JWT is supplied. JWT remains authoritative when both credentials are present.

Stock trace: requirement `specs/006-manage-catalog-inventory/spec.md`; contracts `bgg-shop-core/specs/schema.graphql` and `bgg-shop-bff/specs/openapi.yaml`; implementation `bgg-shop-core/saleor/graphql/api.py`, `bgg-shop-bff/src/controllers/admin_products_controller.py` and `bgg-shop-bff/src/proxy.py`; related tests `bgg-shop-core/tests/test_graphql_credit_postgres.py` and `bgg-shop-bff/tests/test_admin_validation.py`.

The product image is one `.webp` reference by URL or filename; binary upload is not assumed. Approved store-promotion selection is product-specific first, otherwise the highest eligible global offer; offers do not stack and coupon-linked rows are excluded. Coupon/store comparison and rounding follow the overall plan and contracts. Local checkout-path evidence is `bgg-shop-core/tests/test_graphql_credit_postgres.py::test_checkout_total_uses_specific_and_highest_global_store_promotions`; the selector test in that file also passed. The entire PostgreSQL test file was not run.

Core restricts delegated GraphQL operations to the administrative route and
its relevant ID or action before executing resolvers. The former concern that
`productByBggId` or the promotion list fields were absent is resolved: the
staff-protected product detail flow uses the exact
`GET /api/v1/admin/products/{bggId}` → `productByBggId(bggId)` binding, and
`bgg-shop-bff/src/proxy.py` aliases Core `discountPct` to BFF
`discountPercent` while selecting the active/product-link fields. The restored
product binding is checked in `bgg-shop-core/tests/test_opkeys_internal.py`;
the current final BFF focused admin suite passed 108 tests.

The local security run below is a historical 2026-10-31 snapshot; its
mock/socket-blocked result and legacy-route failure do not describe the final
integration status. Final local verification, including PostgreSQL checkout
and browser results, is recorded in
`odd/tasks/007-closeout.md` and the overall task ledger.

The initial BFF RED run reported 6 failed and 2 passed; its GREEN rerun
reported 8 passed. The final full run reported 119 passed and the legacy route
failure described above. Exact commands:

```sh
cd /home/eze/develop/boardgame-app/bgg-shop-bff && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -c 'import socket, pytest; socket.socket.connect = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("network disabled")); socket.socket.connect_ex = socket.socket.connect; socket.create_connection = socket.socket.connect; raise SystemExit(pytest.main(["-p", "no:cacheprovider", "tests/test_opkey_middleware.py", "-q", "-k", "malformed_core_response or validation_failure", "--tb=short"]))'
cd /home/eze/develop/boardgame-app/bgg-shop-bff && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -c 'import socket, pytest; socket.socket.connect = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("network disabled")); socket.socket.connect_ex = socket.socket.connect; socket.create_connection = socket.socket.connect; raise SystemExit(pytest.main(["-p", "no:cacheprovider", "tests/test_admin_validation.py", "tests/test_opkey_middleware.py", "tests/test_opkey_admin.py", "tests/test_admin_gift_cards.py", "-q", "--tb=short"]))'
```

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

## Status
Spec 007 BFF contracts, admin flows, focused integration checks and local
browser evidence are recorded in
`specs/007-manage-catalog-inventory/tasks.md` and
`odd/tasks/007-closeout.md`. No CI, deployment or remote validation is claimed.

## Approved contract and data decisions (2026-11-02)

For Spec 007 tasks X-1, X-2 and C-1 only, the approved admin principal is an
active user with `is_staff` or `is_superuser`, enforced by both BFF and Core.
The product contract requires a positive base price; create requires name,
price and quantity; updates are partial and cannot modify BGG ID or quantity.
Create supplies exactly one `.webp` image URL or path/filename, with no binary
upload.

Coupon codes are unique by exact, case-sensitive equality without
normalization. Remaining uses are nonnegative. UTC validity is
`[starts_at, ends_at)` and, when both boundaries exist, start must precede end.
Promotion discounts range from 0% through 50%; each product can have at most
one active promotion, and the promotion's product link is part of the data/API
contract.

Stock never goes below zero. An overstock `OUT` applies only available units
and returns both requested and applied quantities. Successful movement UUIDs
persist indefinitely; failed, rejected or no-change operations may retry the
same exact payload indefinitely, while reusing an ID with a different product,
direction or quantity rejects.

Coupon preview is `POST /api/v1/cart/coupons/preview`, authenticated and
read-only against the caller's current cart; it does not reserve or consume a
use. A selected coupon is submitted to checkout, which reserves atomically.
Only confirmed failure/cancellation releases a reservation; an uncertain
provider outcome remains reserved for reconciliation and unresolved outcomes
require manual review. Timeout alone is not release evidence. A discount above
50% of undiscounted cart subtotal is rejected, not capped. Intermediate
discount amounts are truncated to two decimals, then rounded to whole pesos:
fractions through 0.50 round down and 0.51 or more round up. These are contract
requirements, not implemented behavior in this task.

The matching OpenAPI 3.2 and GraphQL SDL changes are planned contract only.
Events/cache, UI, and audit authorization/query details are not part of this
bounded task. No runtime conformance is claimed.

The existing OpKey note above is superseded for admin access by this decision:
an operation key alone is not authorization for these admin operations.

Local request examples (documentation only):

```sh
curl -X POST http://localhost:5000/api/v1/admin/products \
  -H 'Authorization: Bearer <local-token>' \
  -H 'Content-Type: application/json' \
  -d '{"name":"Local game","price":25.00,"quantity":3,"image_url":"/media/local-game.webp"}'

curl -X POST http://localhost:5000/api/v1/cart/coupons/preview \
  -H 'Authorization: Bearer <local-token>' \
  -H 'Content-Type: application/json' \
  -d '{"coupon_code":"SAVE10"}'

curl -X POST http://localhost:5000/api/v1/checkout \
  -H 'Authorization: Bearer <local-token>' \
  -H 'Content-Type: application/json' \
  -d '{"shipping_mode":"pickup","coupon_code":"SAVE10"}'
```
