# Tareas BFF — CU-A01: Catálogo e inventario

**Alcance**: solo `bgg-shop-bff`. La implementación del frontend está pausada
hasta disponer del contrato BFF aprobado.  
**Plan**: [`007-manage-catalog-inventory-plan.md`](./007-manage-catalog-inventory-plan.md)  
**Spec de producto**: [`../../specs/006-manage-catalog-inventory/spec.md`](../../specs/006-manage-catalog-inventory/spec.md)  
**Contrato actual**: [`openapi.yaml`](./openapi.yaml)

## Convenciones

- Todas las tareas están pendientes; no reflejan verificación o implementación
  ya completada.
- Paths de código y pruebas son relativos a la raíz `bgg-shop-bff`.
- No se asume que las formas HTTP descritas en la expectativa frontend estén
  aprobadas. Rutas, verbos, modelos y comportamientos abiertos se deciden en
  T002 y se documentan en T003 antes de usarlos como base de implementación.
- Los contratos GraphQL y las reglas de negocio autoritativas deben validarse
  con Core; no inventar campos/operaciones ni replicar decisiones de stock en
  el BFF.
- Los comandos de verificación de la última sección existen en el repositorio.
  Son checks futuros para la implementación; no se ejecutaron en esta
  actualización documental.

## Fase 1 — Inventario y decisiones previas

**Propósito**: identificar la diferencia entre OpenAPI, código existente y
necesidades funcionales antes de congelar la API.

- [ ] **T001 — Inventariar el contrato y la implementación administrativa**
  - **Depende de**: ninguna.
  - **Referencias**: `specs/openapi.yaml`, `app.py`,
    `src/controllers/admin_products_controller.py`,
    `src/controllers/admin_promotions_controller.py`,
    `src/controllers/admin_coupons_controller.py`, `src/dtos/`,
    `src/services.py`, `src/proxy.py`, `tests/test_admin*.py`.
  - **Acción**: registrar por operación qué aparece en OpenAPI, qué ruta y
    handler existe, qué DTO/Core mapping usa y qué pruebas lo cubren. Incluir
    operaciones faltantes de producto, imagen, promoción, cupón, inventario y
    auditoría. No interpretar la presencia de código como contrato aprobado.
  - **Aceptación**: una matriz de cobertura identifica explícitamente
    coincidencias, brechas y discrepancias con el plan y
    `../../bgg-shop-frontend/specs/007-manage-catalog-inventory-frontend.md`; no
    quedan rutas o comportamientos atribuidos a evidencia inexistente.

- [ ] **T002 — Resolver y registrar decisiones de contrato con producto, Core y consumidor**
  - **Depende de**: T001.
  - **Referencias**: `../../specs/006-manage-catalog-inventory/spec.md`,
    `specs/007-manage-catalog-inventory-bff.md`,
    `../../bgg-shop-frontend/specs/007-manage-catalog-inventory-frontend.md`,
    `specs/openapi.yaml`.
  - **Acción**: acordar una matriz con método/ruta, propósito, request/response,
    autorización, errores públicos y operación Core para listado/detalle/alta/
    edición/publicación/baja de productos, imágenes, ajuste de inventario,
    promociones (incluido preview), cupones y auditoría. Resolver o asignar
    responsable y criterio para paginación, campos/fechas, unidades y reservas,
    `min_allowed_stock`, errores por campo, upload, filtros/auditoría, roles,
    fallos Core y disponibilidad de operaciones GraphQL. Definir si caché y
    eventos se excluyen o cuentan con contrato/justificación verificados.
  - **Aceptación**: cada punto tiene decisión aprobada o queda bloqueado con
    responsable explícito; no se introducen esquemas o decisiones de producto
    por inferencia. El frontend continúa pausado mientras existan bloqueos que
    afecten el contrato.

## Fase 2 — Contrato HTTP y criterios de integración

**Propósito**: establecer OpenAPI como referencia para la superficie consumida
por la UI, antes de aceptar la implementación de endpoints.

- [ ] **T003 — Definir operaciones y esquemas administrativos en OpenAPI**
  - **Depende de**: T002.
  - **Archivo**: `specs/openapi.yaml`.
  - **Acción**: añadir las operaciones aprobadas, tags, operation IDs, path/
    query parameters, request/response schemas, ejemplos no sensibles,
    respuestas de éxito y errores, y referencias de seguridad. Cubrir los
    recursos/acciones administrativos acordados para productos, imágenes,
    variantes/inventario, promociones, cupones y auditoría; no dar por
    obligatorias rutas concretas no acordadas.
  - **Aceptación**: las operaciones y campos coinciden con la matriz T002; la
    autorización está definida por operación; los errores por campo y los
    errores generales son consistentes; no hay referencias OpenAPI rotas ni
    contradicciones con la spec de producto/Core confirmada. OpenAPI no expone
    detalles internos de Core.

- [ ] **T004 — Acordar e implementar autenticación y autorización administrativa**
  - **Depende de**: T003.
  - **Referencias**: `specs/openapi.yaml`, `src/auth.py`, `src/proxy.py`,
    `tests/test_admin.py`.
  - **Acción**: expresar en OpenAPI y aplicar a cada operación la política de
    token y roles aprobada para Administrador/Vendedor. Reconciliar la
    verificación de rol existente con la política, sin ampliar permisos por
    defecto.
  - **Aceptación**: ausencia/validez de credenciales y rol insuficiente producen
    respuestas HTTP acordadas (incluyendo distinción autenticación/permisos);
    cada endpoint administrativo queda cubierto por pruebas positivas y
    negativas; el BFF no confía en un rol enviado en el body.

- [ ] **T005 — Implementar DTOs y validación alineados con el contrato**
  - **Depende de**: T003.
  - **Referencias**: `src/dtos/`, `src/controllers/`,
    `tests/test_admin_validation.py`.
  - **Acción**: revisar y ajustar DTOs para requests aprobados de producto,
    imagen, inventario, promociones y cupones. Validar campos requeridos,
    tipos, rangos, formatos, valores permitidos y campos desconocidos según
    contrato. Usar una única forma pública de errores por campo acordada en
    OpenAPI.
  - **Aceptación**: payloads inválidos se rechazan antes de llamar a Core y
    reportan ruta/campo y mensaje conforme al esquema acordado; payloads
    válidos se normalizan sin alterar semántica; la validación de stock usa
    solo reglas y valores confirmados con Core.

## Fase 3 — Endpoints BFF e integración con Core

**Propósito**: adaptar o completar las rutas existentes para satisfacer el
contrato aprobado, usando el Core como autoridad.

- [ ] **T006 — Alinear endpoints BFF de productos, imágenes e inventario**
  - **Depende de**: T003, T004 y T005.
  - **Referencias**: `app.py`, `src/controllers/admin_products_controller.py`,
    `src/services.py`, `src/proxy.py`, `src/dtos/`, `specs/openapi.yaml`.
  - **Acción**: reconciliar el listado/alta/edición/ajuste de stock presentes
    con OpenAPI y completar las operaciones acordadas de detalle, publicación/
    baja e imágenes. Implementar o ajustar las rutas y adaptadores Core para
    los contratos aprobados; no agregar rutas únicamente porque se mencionen
    como ejemplo en el documento frontend.
  - **Aceptación**: cada operación acordada tiene ruta protegida, validación,
    mapeo REST/Core y status/body documentados; las imágenes usan un flujo
    confirmado con Core; ajustes de inventario respetan las reservas según
    respuesta/regla confirmada por Core; no se duplica la autoridad de stock.

- [ ] **T007 — Alinear endpoints BFF de promociones, cupones y auditoría**
  - **Depende de**: T003, T004 y T005.
  - **Referencias**: `app.py`, `src/controllers/admin_promotions_controller.py`,
    `src/controllers/admin_coupons_controller.py`, `src/services.py`,
    `src/proxy.py`, `src/dtos/`, `specs/openapi.yaml`.
  - **Acción**: reconciliar las operaciones existentes de promociones y preview
      de cupón con OpenAPI; implementar o ajustar gestión de cupones, preview de
      promoción y consultas de auditoría en la medida acordada y soportada por
    Core. Definir claramente si un preview no muta estado ni consume cupos.
  - **Aceptación**: cada operación aprobada tiene permisos, validación,
    comportamiento Core y respuesta/error coherentes con OpenAPI; `stackable`,
    vigencia, preview y datos de auditoría solo tienen semántica confirmada;
    funcionalidades no soportadas por Core quedan explícitas y no se simulan.

- [ ] **T008 — Normalizar errores de negocio y fallos de Core**
  - **Depende de**: T003, T006 y T007.
  - **Referencias**: `src/proxy.py`, controladores admin, `specs/openapi.yaml`,
    `tests/test_admin_error_mapping.py`.
  - **Acción**: mapear errores de validación/upstream confirmados a respuestas
    públicas y códigos HTTP acordados; separar errores de usuario de fallos
    técnicos. Eliminar de respuestas públicas mensajes, cuerpos, trazas,
    consultas y detalles internos del upstream, incluidos los retornos
    genéricos actuales que pudieran incluir `detail`.
  - **Aceptación**: cada error documentado tiene una respuesta pública estable;
    los tests demuestran que fallos Core/upstream no filtran el contenido
    interno; los errores de campo conservan únicamente los datos seguros
    definidos por contrato.

## Fase 4 — Pruebas y documentación

**Propósito**: probar las fronteras REST/Core con fixtures/mocks y registrar
cómo verificar el trabajo sin realizar llamadas a servicios reales.

- [ ] **T009 — Añadir pruebas unitarias y contractuales administrativas**
  - **Depende de**: T004, T005, T006, T007 y T008.
  - **Referencias**: `tests/test_admin.py`,
    `tests/test_admin_validation.py`, `tests/test_admin_error_mapping.py`,
    `tests/test_admin_promotions.py`, `tests/test_admin_coupons.py`,
    `tests/test_services_*.py`, `tests/CONTRACTS_README.md`.
  - **Acción**: cubrir autorización por rol, validación/DTOs, respuestas de
    cada endpoint aprobado, operaciones Core solicitadas, mapeo de respuestas,
    errores de negocio y fallos sanitizados. Usar mocks; no depender de Core
    real. Incorporar pruebas GraphQL al patrón documentado de
    `tests/test_services_*`.
  - **Aceptación**: los tests ejercitan las decisiones de contrato acordadas y
    se ejecutan con los comandos de verificación de abajo; registrar el
    resultado observado. No declarar probado ningún flujo que no esté cubierto
    o cuyo comando no se haya ejecutado.

- [ ] **T010 — Actualizar documentación BFF del contrato y verificación**
  - **Depende de**: T003, T004, T005, T006, T007, T008 y T009.
  - **Referencias**: `README.md`, `specs/openapi.yaml`,
    `tests/CONTRACTS_README.md`, `specs/007-manage-catalog-inventory-plan.md`.
  - **Acción**: documentar capacidades administrativas, autenticación,
    requests/responses y errores desde el OpenAPI aprobado; explicar pruebas y
    comandos existentes. Corregir solo documentación BFF afectada y enlazar la
    fuente de contrato, evitando copiar esquemas que puedan derivar.
  - **Aceptación**: enlaces/rutas correctos, ejemplos sin datos sensibles y
    coherentes con OpenAPI; los comandos publicados existen; resultados
    aparecen como verificados solo si se ejecutaron. La documentación no
    reanuda ni describe trabajo frontend como completado.

## Dependencias y orden

- T001 → T002 → T003 es la cadena de descubrimiento y aprobación: no implementar
  una forma HTTP como si fuera definitiva antes de cerrar decisiones.
- T004 y T005 dependen del contrato; T006 y T007 dependen además de la política
  de autorización y validación. Se pueden realizar en paralelo tras esos gates
  si comparten los mismos contratos aprobados.
- T008 consolida los resultados de las integraciones y precede a pruebas
  finales T009; T010 publica el estado probado.
- Tareas sin check no significan que el código existente no contenga nada:
  T006/T007 requieren reconciliar primero la implementación parcial con
  OpenAPI y no duplicar handlers.

## Comandos de verificación existentes (desde `bgg-shop-bff`)

Ejecutar en la implementación de las tareas correspondientes y reportar el
resultado real. No se ejecutaron al crear esta planificación.

```bash
PYTHONPATH=. pytest tests/test_admin.py tests/test_admin_validation.py tests/test_admin_error_mapping.py tests/test_admin_promotions.py tests/test_admin_coupons.py -q
bash scripts/run_contracts.sh
```

`scripts/run_contracts.sh` ya existe y ejecuta `PYTHONPATH=. pytest
tests/test_services_* -q`; `tests/CONTRACTS_README.md` documenta ambos patrones
de ejecución de pruebas contractuales. No se documenta un lint/validador
OpenAPI porque no se identificó un comando de ese tipo en el BFF; revisar
estructuralmente rutas, referencias, esquemas y seguridad en
`specs/openapi.yaml` hasta que se incorpore una herramienta con comando
documentado.

## Resultado de esta actualización de planificación

- Plan y tareas delimitan el trabajo al BFF y mantienen pausada la integración
  frontend.
- OpenAPI y endpoints administrativos siguen siendo trabajo pendiente; no se
  cambió el contrato ni el código.
- Verificación realizada: lectura estructural de estos dos artefactos,
  confirmación de rutas OpenAPI actuales, archivos/documentación BFF y
  existencia de los comandos arriba citados. No se ejecutaron suites ni los
  comandos de implementación.
