# Tareas BFF — CU-A01: Catálogo e inventario

**Alcance**: solo `bgg-shop-bff`. La implementación del frontend está pausada
hasta disponer del contrato BFF aprobado.  
**Plan**: [`007-manage-catalog-inventory-plan.md`](./007-manage-catalog-inventory-plan.md)  
**Spec de producto**: [`../../specs/006-manage-catalog-inventory/spec.md`](../../specs/006-manage-catalog-inventory/spec.md)  
**Contrato actual**: [`openapi.yaml`](./openapi.yaml)

## Convenciones

- Las diez tareas siguen abiertas respecto de sus criterios completos; esto no
  significa que no exista implementación o evidencia parcial.
- Paths de código y pruebas son relativos a la raíz `bgg-shop-bff`.
- No se asume que las formas HTTP descritas en la expectativa frontend estén
  aprobadas. Rutas, verbos, modelos y comportamientos abiertos se deciden en
  T002 y se documentan en T003 antes de usarlos como base de implementación.
- Los contratos GraphQL y las reglas de negocio autoritativas deben validarse
  con Core; no inventar campos/operaciones ni replicar decisiones de stock en
  el BFF.
- Los comandos de implementación de la última sección siguen pendientes; la
  evidencia de validación documental ejecutada se registra por separado.

## Estado consolidado — 2026-11-01

Este archivo desglosa trabajo BFF y no debe sumarse como diez tareas adicionales
al [recuento general](../../specs/007-manage-catalog-inventory/tasks.md). Las
casillas permanecen abiertas porque sus criterios abarcan más que stock.

Actualización del 2026-11-02: la lista de promociones y la consulta pública de
cupones validan sus documentos GraphQL frente al SDL y al esquema ejecutable.
El detalle administrativo usa `productByBggId` de Core, sin escanear páginas
ni devolver datos incompletos de caché como producto. Los puntos y resultados
de la sección fechada 2026-11-01 son históricos; la aplicación del cupón y los
demás contratos administrativos siguen pendientes.

| Tarea | Avance y trabajo pendiente | Referencia general |
| --- | --- | --- |
| T001 | Hay inventario parcial; falta la matriz completa por operación. | X-1, B-1 |
| T002 | Se registraron decisiones de stock y roles; quedan decisiones de otras operaciones. | X-1 |
| T003 | Stock, lista de promociones, consulta de cupones y detalle por BGG ID tienen validación parcial; falta reconciliar la aplicación de cupones y otras operaciones. | X-1 |
| T004 | Hay pruebas de autorización de stock; falta cubrir todas las operaciones administrativas. | B-1 |
| T005 | La validación de stock y de tipos de promociones se probó; faltan los demás DTOs aprobados. | B-1 |
| T006 | El ajuste de stock está implementado y probado; falta reconciliar productos e imágenes. | B-1, C-2 |
| T007 | Quedan reglas y contratos de promociones, cupones y consulta de auditoría. | B-1, C-3, C-5 |
| T008 | El mapeo y la sanitización de errores de stock y de alta/edición de productos se probaron; faltan los demás flujos. | B-2 |
| T009 | Pasaron 218 pruebas administrativas y contractuales seleccionadas sin exclusiones; falta cobertura y verificación integral. | B-4 |
| T010 | Hay trazabilidad y resultados de stock; falta documentación integral del contrato administrativo. | B-4 |

La verificación de recuperación registró inicialmente 152 pruebas BFF
aprobadas con dos pruebas antiguas de creación excluidas. Después de corregir
esas rutas y tres pruebas administrativas adicionales, pasaron 185 pruebas
seleccionadas sin exclusiones, incluidas pruebas negativas de sanitización. Se
verificó la recuperación por HTTP real entre BFF y Core con datos sintéticos;
el frontend sigue sin verificarse. El detalle y las limitaciones figuran en el
recuento general.

### Contratos y persistencia — 2026-11-01

- La validación de promociones rechaza tipos incorrectos, valores nulos y
  propiedades desconocidas antes de llamar al servicio. La edición traduce
  `discount_percent` a `discountPercent`; el documento y las variables se
  validaron contra el SDL, sin probar persistencia real de promociones.
- La consulta de lista solicita `discountPercent` y `active`, ausentes del
  tipo `Promotion` de Core, que expone `discountPct`. Las mutaciones aceptan
  `active` pero Core no lo guarda. Se acordó que `active` sea un interruptor
  manual independiente de la vigencia: una promoción desactivada no aplica
  aunque la fecha esté dentro del rango. El estado inicial de las promociones
  existentes al incorporar el campo sigue pendiente de decisión; la regla no
  está implementada ni verificada.
- El preview de cupón solicita `ApplyCouponInput` y `applyCouponPreview`,
  ausentes del SDL de Core; la compatibilidad permanece abierta.
- `manage.py showmigrations promotions`, usando SQLite en memoria, mostró que
  Django no descubre migraciones de promociones. La carpeta contiene
  `0001_initial.py` pero no un inicializador de paquete; queda pendiente una
  estrategia para reconciliar su adopción con tablas comerciales existentes.
  No se modificó ni consultó la base activa.
- La suite BFF seleccionada pasó 218 pruebas; la comprobación de documentos
  GraphQL no demuestra que los flujos completos estén implementados.

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
  - **Decisión confirmada (2026-10-31)**: las operaciones administrativas
    requieren un usuario activo con `is_staff` o `is_superuser`. Un Vendedor
    sin esos permisos no está autorizado. Esta decisión no acredita que la
    implementación actual la cumpla en todas las operaciones.
  - **Auditoría confirmada (2026-10-31)**: registrar usuario, fecha, acción y
    valores anteriores y nuevos para cambios de productos, movimientos de stock,
    promociones y cupones. La auditoría básica permanece en alcance. Como requisitos
    futuros y fuera del alcance actual se prevén siete días en la base y un ZIP local
    semanal; no se eliminarán filas sin verificar antes la creación correcta del archivo
    y no se acuerda purga automática. Compatibilizar la
    frecuencia semanal con la retirada exactamente a los siete días queda pendiente:
    el archivado y la retirada podrían retrasarse. Los ZIP no vencen ni se eliminan
    automáticamente; su eliminación manual queda a cargo del usuario y está acordada
    solo para `is_superuser=true`, no para `is_staff` por sí solo. La generación
    semanal del ZIP y el mecanismo que hace cumplir el permiso de borrado quedan
    pendientes y fuera del alcance actual de la 007. No se afirma que se aplique en
    el filesystem. La retención es indefinida hasta la eliminación manual. La decisión anterior de conservar
    los ZIP un mes queda reemplazada. Esta política no se considera implementada ni
    validada. Siguen pendientes el inicio de los siete días, el horario del proceso, el mecanismo de archivo
    atómico ante fallas, el acceso y consulta de archivos y el cifrado. También siguen pendientes el acceso a
    la auditoría, filtros, paginación y captura de secretos; los ejemplos de filtros
    no están confirmados. La existencia de AuditLog no acredita cobertura de
    todos los flujos ni conformidad.
  - **Movimiento de stock implementado**: el BFF genera un UUID y recibe
    `movement_id`, `direction` (`IN`/`OUT`) y `quantity` positiva en
    `POST /api/v1/admin/products/{product_id}/stock`. Core usa
    `adjustProductStock`; la mutación anterior `addProductStock` rechaza
    escrituras sin UUID. Un registro provisional `IN_PROGRESS` precede la
    transacción que confirma stock, auditoría y resultado. El mismo UUID y
    datos devuelve el resultado original; datos distintos producen conflicto.
    `OUT` se limita al stock disponible y devuelve un aviso. Un rollback
    confirmado permite reintentar con el mismo UUID; un resultado incierto no
    se presupone revertido. El reintento con los mismos datos puede recuperar
    un registro provisional y se probó por HTTP local con datos sintéticos.
    Las migraciones 0012 y 0013 se probaron en PostgreSQL descartable, pero no
    se aplicaron a la base activa. Las pruebas cubren concurrencia, auditoría,
    respuesta perdida y reintentos; la cadena aplicada incluyó solo migraciones
    descubiertas por Django y no acredita el estado de la base activa.
  - **Errores**: informar al usuario y registrar el error de forma segura sin detalles
    sensibles, sin suponer seguro reintentar. Un error de comunicación o HTTP no
    demuestra rollback: el servidor puede confirmar y perderse la respuesta; un
    reintento aditivo podría duplicar la operación. Esto no acredita implementación.
  - **Trazabilidad de stock**: requisito `specs/006-manage-catalog-inventory/spec.md`;
    contratos actuales `bgg-shop-core/specs/schema.graphql` y
    `bgg-shop-bff/specs/openapi.yaml`; implementación
    `bgg-shop-bff/src/controllers/admin_products_controller.py` y
    `bgg-shop-bff/src/services.py`; pruebas relacionadas
    `bgg-shop-bff/tests/test_admin_validation.py` y
    `bgg-shop-bff/tests/test_admin_error_mapping.py` y
    `bgg-shop-core/tests/test_graphql_credit_postgres.py`. Las firmas actuales
    incluyen UUID; las pruebas PostgreSQL descartables cubren reintentos y
    concurrencia, sin acreditar despliegue en la base activa.
  - **Comprobación posterior (2026-10-31)**: se actualizaron las descripciones de
    `bgg-shop-core/specs/schema.graphql` y `bgg-shop-bff/specs/openapi.yaml` sin
    cambiar sus firmas. `python3 -m openapi_spec_validator specs/openapi.yaml`
    pasó desde BFF; desde Core, `PYTHONPATH=. python3 -m pytest
    tests/test_graphql_products.py::test_generated_schema_matches_reference_sdl -q`
    pasó con una advertencia de Django. Estas comprobaciones no prueban
    idempotencia ni modifican la implementación de `saleor/graphql/api.py`.
  - **Decisión confirmada (2026-10-31)**: `quantity` se define al crear el
    producto y luego solo se modifica mediante operaciones de inventario; la
    edición de producto no debe aceptarlo. Core y BFF rechazan el campo en
    edición, incluso con valor nulo; las pruebas focalizadas usan mocks. Core
    pasó 47 pruebas de productos con una excluida por paridad global pendiente;
    BFF pasó 66 pruebas de validación con una excluida por una ruta antigua.
    El input GraphQL de edición coincide con el SDL y OpenAPI validó. Esto no
    acredita integración completa. No existe despublicación y no se infiere
    eliminación física.
  - **Paridad y consulta de estado**: Core expone `adminStockMovementStatus`
    y BFF expone `GET /api/v1/admin/stock-movements/{movement_id}`. Las suites
    de Core y BFF pasaron 174 y 147 pruebas respectivamente; dos casos BFF
    de creación con ruta antigua se excluyeron. Pasaron 17 pruebas de
    movimientos en PostgreSQL descartable, incluida integración en proceso
    con credenciales o validación OpKey simuladas. Django aplicó 0012 y 0013
    en un esquema descartable; no se probó la cadena completa de migraciones.
  - **Decisiones vigentes (2026-10-31)**: una imagen `.webp` por producto,
    por URL o nombre de archivo, sin asumir subida de binarios; cada producto del
    carrito puede tener su propia promoción, sin combinar descuentos sobre un mismo
    producto; al comparar descuentos aplicables al mismo producto prevalece el que descuente más
    pesos, también al comparar un porcentaje con un monto fijo.
    Ante dos promociones iguales para un producto aplica la ofrecida por la tienda.
    Los cupones de descuento aplican a toda la compra al momento del pago; los cupones por producto
    no se implementan en este MVP. Las promociones y descuentos sí pueden ser por
    producto. Se compara la suma de ahorros de las promociones aplicables a todo
    el carrito con el ahorro del cupón calculado sobre la compra sin descuentos;
    se aplica exclusivamente la alternativa que ahorre más pesos. Si se eligen
    promociones, cada producto puede recibir la suya; si se elige el cupón, no se
    aplican promociones. Cuando el usuario usa un cupón que empata con una
    promoción, se le avisa que se aplicará la promoción de tienda y no el cupón,
    sin definir la interfaz. No hay impuestos y el envío es gratis, sin modificar
    otras specs cerradas de checkout. Las fracciones hasta 0,50 inclusive se
    mantienen; desde 0,51 se redondean hacia arriba. El límite de descuento es
    50%. El cupón no se da de baja antes de que se realice el pago;
    no se presupone que todos sean de un solo uso y el resultado de intentos
    fallidos o concurrentes sigue abierto. Quedan pendientes elegibilidad o exclusiones; identidad de
    promociones iguales y precedencia si ambas proceden de la tienda; otras
    igualdades; unidad y etapa del redondeo; si el 50% aplica por producto, cupón
    o compra y si se rechazan o limitan configuraciones; y consumo del contador
    ante un intento de pago fallido. También quedan pendientes el significado de
    los filtros y los detalles de auditoría aún no definidos.
    Resolver estos puntos y definir y validar los contratos antes de implementar.
    Las gift cards y el crédito son medios de pago, no cupones de descuento. El
    checkout actual usa precios base y la integración no está validada.
  - **Discrepancias con runtime**: Core conserva `stackable` y modelo/consulta
    de reservas. El formulario frontend acepta URL y nombre de imagen y una
    tarjeta muestra «Sin stock» a cantidad cero; eso no acredita el flujo
    completo de baja ni el formato/cantidad de imagen o la selección de promoción.
  - **Antecedente histórico de stock (2026-10-31)**: en esa fecha BFF exponía la ruta por producto
    y delega a `addProductStock`, sin mantener la ruta anterior por variante.
    Las pruebas usan Core simulado y cubren validación, autorización, errores y
    propagación de credenciales. No prueban concurrencia ni persistencia real.
    La autorización JWT compartida consulta `me` en Core en cada solicitud:
    `me: null` responde 401, un usuario autenticado sin rol responde 403 y
    respuestas incompletas o fallos de Core responden 502 sin detalles.
    No se cachea la decisión; esto observa el vencimiento y cualquier
    revocación que Core reconozca, pero Core aún no revoca JWT al hacer logout.
    No se ha verificado cada operación administrativa 007.
  - **Verificación local (2026-10-31)**: las pruebas de identidad y stock
    usan mocks. El conjunto solicitado `tests/test_admin_validation.py
    tests/test_opkey_middleware.py` dio 70 aprobadas y una falla ajena en
    `test_create_product_requires_name_and_valid_fields`: espera 400 en la
    ruta antigua `/admin/products`, que devuelve 404. `tests/test_admin.py`
    dio 12 aprobadas y tres fallas por la misma ruta antigua. Al excluir esos
    casos, dieron 70 aprobadas y una excluida, y 12 aprobadas y tres excluidas,
    respectivamente. No se modificaron las pruebas ajenas.
    La ejecución usó los argumentos pytest solicitados mediante `pytest.main`,
    con `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=.` y la conexión de socket
    bloqueada; `bwrap --unshare-net` no estuvo disponible.
    Comando ejecutado desde BFF:

    ```sh
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -c 'import socket, pytest; socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("network disabled")); raise SystemExit(pytest.main(["-p", "no:cacheprovider", "tests/test_admin_validation.py", "tests/test_opkey_middleware.py", "-q", "--tb=short"]))'
    ```
    Para la suite adicional se sustituyeron los dos archivos por
    `tests/test_admin.py` con los mismos argumentos y bloqueo de red. El RED
    inicial de identidad tuvo 8 fallas y 5 aprobadas; la prueba focalizada
    final de identidad y compatibilidad tuvo 19 aprobadas y 51 excluidas.
  - **Evidencia de OpKey (2026-10-31)**: `src/opkey_middleware.py` consulta
    a Core con la ruta y el método; `../bgg-shop-core/opkeys/views.py` exige
    usuario activo y `is_staff` o `is_superuser` para rutas administrativas,
    además de validar la operación permitida. La compatibilidad con JWT figura
    en `../bgg-shop-core/specs/008-operations-keys-auth.md`. Las pruebas
    relacionadas son `tests/test_opkey_middleware.py` y
    `../bgg-shop-core/tests/test_opkeys_internal.py`; no se ejecutaron en esta
    revisión. Falta verificar la autorización y propagación en cada
    operación 007 y su correspondencia con el contrato aprobado.
  - **Revisión de seguridad posterior (2026-10-31)**: Core vincula cada
    delegación administrativa conocida a una única selección GraphQL y a sus
    IDs o acciones antes de ejecutar resolvers. Con solo OpKey, BFF distingue
    clave inválida (401) de falla de validación Core (502); JWT mantiene su
    prioridad. La suite local solicitada dio 155 aprobadas en Core y 119 en
    BFF, con una falla preexistente por la ruta antigua `/admin/products`.
    Se usaron SQLite en memoria, mocks y sockets bloqueados, sin probar
    concurrencia PostgreSQL. `productByBggId` y `applyCouponPreview` no están
    en el esquema Core actual; su integración no se considera verificada.
    La consulta real de promociones del BFF pide `discountPercent` y `active`,
    campos también ausentes del tipo Core `Promotion`; la prueba positiva de
    delegación usa una selección distinta válida para el esquema.
  - **Acción**: acordar una matriz con método/ruta, propósito, request/response,
    autorización, errores públicos y operación Core para listado/detalle/alta/
    edición/baja de stock de productos, imágenes, ajuste de inventario,
    promociones (incluido preview), cupones y auditoría. Resolver o asignar
    responsable y criterio para paginación, campos/fechas, unidades, contrato del
    aviso de `OUT` superior al stock, detalles pendientes de promociones y cupones, errores por campo,
    referencia de imagen, filtros/auditoría, roles,
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
    inventario, promociones, cupones y auditoría; no dar por
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
    confirmado con Core; el ingreso de inventario suma unidades por producto;
    las políticas pendientes no se presuponen ni se duplica la autoridad de stock.

- [ ] **T007 — Alinear endpoints BFF de promociones, cupones y auditoría**
  - **Depende de**: T003, T004 y T005.
  - **Referencias**: `app.py`, `src/controllers/admin_promotions_controller.py`,
    `src/controllers/admin_coupons_controller.py`, `src/services.py`,
    `src/proxy.py`, `src/dtos/`, `specs/openapi.yaml`.
  - **Acción**: reconciliar las operaciones existentes de promociones y preview
      de cupón con OpenAPI; implementar o ajustar gestión de cupones, preview de
      promoción y consultas de auditoría en la medida acordada y soportada por
    Core. Considerar la auditoría básica confirmada y resolver sus decisiones
    pendientes antes de definir el contrato. Definir claramente si un preview no
    muta estado ni consume cupos.
  - **Aceptación**: cada operación aprobada tiene permisos, validación,
    comportamiento Core y respuesta/error coherentes con OpenAPI; la selección
    de promoción, vigencia, preview y auditoría solo tienen semántica confirmada;
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

## Avance parcial histórico del contrato — 2026-10-31

- `specs/openapi.yaml` contiene un borrador de nueve operaciones sobre rutas
  existentes: listado y alta de productos; detalle y edición; ajuste de stock;
  listado, alta y edición de promociones; y preview de cupón. Están marcadas
  `x-implementation-status: planned`; su presencia no acredita implementación
  compatible ni aprobación de T002/T003.
- Se comprobó que `openapi-typescript ../bgg-shop-bff/specs/openapi.yaml --output /dev/null`
  puede generar tipos desde `bgg-shop-frontend`. Una revisión estructural con
  `js-yaml` comprobó nueve operaciones, parámetros de ruta, seguridad, IDs
  únicos y referencias locales. No se ejecutó un validador formal OpenAPI 3.2:
  `openapi_spec_validator` no estaba instalado en el entorno BFF.
- Diferencias que deben resolverse antes de aprobar el contrato: el listado
  administrativo puede devolver 200 vacío ante fallos upstream; el detalle
  puede devolver una respuesta parcial desde caché; el formulario frontend
  envía campos camelCase y valores nulos, mientras el borrador propone
  snake_case y validación estricta. La propagación y autorización de OpKey
  debe verificarse por operación, no inferirse de su declaración en OpenAPI.
- El adaptador de promociones usa `active` y `discountPercent`, mientras el
  tipo `Promotion` del SDL expone `discountPct`, `stackable` y vigencia. El
  SDL consultado no contiene `applyCouponPreview`. Compatibilidad, preview sin
  mutación, roles y errores seguían pendientes de decisión y pruebas en esa revisión;
  la decisión vigente es no hacer reservas.
- Publicación/baja, referencia de imagen, administración de cupones, preview de
  promoción y auditoría requieren acordar rutas, semántica y soporte Core; no
  se inventaron operaciones ni se considera finalizada la spec 007.
  Referencia histórica: la decisión vigente excluye la despublicación; la baja
  se refiere al stock y no implica eliminación física.

## Evidencia de la actualización contractual — 2026-10-31

- Desde `bgg-shop-bff`, `PYTHONDONTWRITEBYTECODE=1 python3 -m openapi_spec_validator specs/openapi.yaml`: pasó (`specs/openapi.yaml: OK`).
- Desde `bgg-shop-core`, `PYTHONDONTWRITEBYTECODE=1 python3 -c 'from pathlib import Path; from graphql import build_schema; build_schema(Path("specs/schema.graphql").read_text()); print("SDL valid")'`: pasó (`SDL valid`).
- Desde `bgg-shop-core`, `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python3 -m pytest -p no:cacheprovider tests/test_graphql_products.py::test_generated_schema_matches_reference_sdl -q`: falló una prueba de paridad con una advertencia de Django. El SDL previsto usa `addProductStock`, mientras el runtime conserva `adjustVariantStock`: drift esperado, no conformidad implementada. La aserción compara el esquema completo.
- `git diff --check` pasó para los archivos modificados de cada repositorio;
  el archivo no rastreado `odd/tasks/admin-contract-first.md` también pasó
  `git diff --no-index --check /dev/null odd/tasks/admin-contract-first.md`.
- La primera validación SDL se ejecutó por error desde la raíz y falló con
  `FileNotFoundError`; el resultado válido es el ejecutado desde Core arriba.
- No se ejecutaron pruebas funcionales de ingreso ni se modificó el runtime.
  Esa evidencia es anterior a la implementación parcial posterior. T002, T003
  y las tareas generales de implementación permanecen abiertas.

## Evidencia parcial de stock BFF — 2026-10-31

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -p no:cacheprovider tests/test_admin_validation.py -q -k product_stock`: RED inicial con 20 fallos y GREEN con 36 pruebas aprobadas, una excluida y 37 advertencias de `datetime.utcnow()`.
- Tras validar el ID de producto y la ruta delegada, el mismo comando pasó con 39 pruebas, una excluida y 40 advertencias. En Core, `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python3 -m pytest -p no:cacheprovider tests/test_graphql_products.py tests/test_opkeys_internal.py::test_graphql_delegation_requires_trusted_secret_and_allowed_operation -q` pasó con 41 pruebas y una advertencia de Django; incluye paridad entre SDL y runtime.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m openapi_spec_validator specs/openapi.yaml`: pasó (`specs/openapi.yaml: OK`).
- La suite solicitada detectó cinco pruebas heredadas que usan rutas `/admin/...` ya no disponibles y cuatro mocks de carrito/cupón incompatibles con `allow_redirects`; no se modificaron por estar fuera de este comportamiento.
- La autorización JWT compartida responde 403 para un token inválido en un caso que requiere 401. Con acceso al secreto interno, la delegación OpKey compartida también permite ejecutar otra mutación GraphQL usando una clave limitada a la ruta de stock. Estas brechas de autorización generales permanecen abiertas; la mutación de ingreso valida su propia ruta delegada y el ID del producto.
- No se accedió a Core real ni a una base de datos, ni se verificó concurrencia PostgreSQL. Las tareas de 007 siguen abiertas.

## Comandos de verificación existentes (desde `bgg-shop-bff`)

### Verificación parcial histórica anterior al cambio de firma — 2026-10-31

- Desde `../bgg-shop-core`, `PYTHONPATH=. python3 -m pytest
  tests/test_graphql_products.py::test_generated_schema_matches_reference_sdl -q`
  pasó: una prueba y una advertencia de Django. Comprueba la firma SDL frente
  al schema de ejecución, no la suma de stock ni su atomicidad.
- Tras cambiar la semántica de `new_stock`, `python3 -m openapi_spec_validator
  specs/openapi.yaml` pasó con el Python del sistema. No se ejecutaron pruebas
  funcionales de stock para ese cambio contractual.
- `python3 -m openapi_spec_validator specs/openapi.yaml` pasó usando el Python
  del sistema y `openapi-spec-validator 0.9.0`; se confirmó que seleccionó
  `OpenAPIV32SpecValidator` para OpenAPI `3.2.0`. El módulo no estaba instalado
  en `.venv`. Esta validación no prueba conformidad de la implementación.
- `PYTHONPATH=. .venv/bin/python -m pytest tests/test_opkey_middleware.py -q`
  pasó: 16 pruebas, una advertencia de deprecación. Desde `../bgg-shop-core`,
  `PYTHONPATH=. python3 -m pytest tests/test_opkeys_internal.py::test_admin_operation_requires_active_administrator -q`
  pasó: tres pruebas, una advertencia de Django. Son pruebas aisladas; no
  acreditan autorización ni propagación para cada operación administrativa.

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
documentado. Esta indicación es histórica; la validación formal observada se
registra arriba y en la evidencia de la actualización contractual.

## Resultado de la planificación original

- Plan y tareas delimitan el trabajo al BFF y mantienen pausada la integración
  frontend.
- En esa actualización no se cambió el contrato ni el código. El avance
  posterior del borrador OpenAPI se registra en la sección anterior.
- Verificación realizada: lectura estructural de estos dos artefactos,
  confirmación de rutas OpenAPI actuales, archivos/documentación BFF y
  existencia de los comandos arriba citados. No se ejecutaron suites ni los
  comandos de implementación.
