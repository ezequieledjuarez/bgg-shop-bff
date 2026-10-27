# Plan: CU-A01 — Contrato e integración de catálogo e inventario en BFF

Owner: `bgg-shop-bff`
Spec de producto: [`specs/006-manage-catalog-inventory/spec.md`](../../specs/006-manage-catalog-inventory/spec.md)
Contexto BFF: [`007-manage-catalog-inventory-bff.md`](./007-manage-catalog-inventory-bff.md)
Contexto de consumo: [`bgg-shop-frontend/specs/007-manage-catalog-inventory-frontend.md`](../../bgg-shop-frontend/specs/007-manage-catalog-inventory-frontend.md)

## Estado y objetivo

Planificación pendiente de decisiones de contrato. Este documento no modifica ni
declara implementado el contrato OpenAPI ni los endpoints administrativos.
El objetivo es acordar primero el contrato REST público del BFF y su integración
con Core; luego ajustar o completar la implementación existente para que cumpla
ese contrato.

El frontend permanece pausado hasta que el contrato BFF esté definido y
validado. El alcance de este plan termina en BFF, OpenAPI, integración con Core,
pruebas BFF y documentación relacionada; no incluye implementar ni actualizar
el frontend.

## Estado observado y línea base

- `bgg-shop-bff/specs/openapi.yaml` define autenticación, catálogo de lectura,
  carrito, wishlist y compras, pero no define operaciones administrativas de
  productos, promociones, cupones, inventario o auditoría.
- El código BFF contiene rutas y controladores administrativos parciales
  (por ejemplo, list/create/update de productos y promociones, ajuste de stock y
  preview de aplicación de cupón). Esa presencia no equivale a un contrato
  OpenAPI validado ni demuestra cobertura de todas las necesidades del caso.
  Las tareas deben contrastar y reconciliar esas superficies con el contrato
  aprobado; no duplicarlas a ciegas ni tratarlas como contrato ya terminado.
- El alcance administrativo solicitado requiere resolver también operaciones
  cuya forma HTTP no está fijada en los artefactos consultados: detalle y
  publicación/baja de producto, manejo de imágenes, gestión de cupones,
  preview de promoción y consulta de auditoría.
- El plan BFF previo proponía esquemas Core, mapeo de errores, caché e
  invalidación por eventos sin un contrato Core/eventos verificable adjunto.
  Esas propuestas no se consideran decisiones aprobadas. No se agrega una
  caché ni un listener salvo que una necesidad y un contrato de eventos se
  validen expresamente.

## Alcance BFF

1. Acordar con Frontend y Core el inventario de operaciones administrativas y
   los modelos REST que la UI necesita, documentando OpenAPI antes de cerrar el
   contrato para consumo.
2. Definir autenticación y autorización por rol, identificadores, parámetros,
   formatos de entrada/salida, validación, límites y códigos HTTP.
3. Definir DTOs y validación del lado servidor, incluida la forma estable de
   errores por campo que utilizará la UI.
4. Integrar cada operación aprobada con las operaciones disponibles en Core,
   manteniendo Core como autoridad para stock, reservas, precios, promociones,
   cupones y persistencia.
5. Traducir errores de Core a respuestas públicas estables y no filtrar cuerpos,
   trazas, mensajes internos ni datos sensibles del upstream.
6. Añadir pruebas unitarias y contractuales con Core simulado y actualizar la
   documentación BFF afectada.

## Capacidades que el contrato debe resolver

La lista es una entrada para definir el contrato, no una afirmación de métodos,
rutas o esquemas ya acordados:

- Productos: búsqueda/listado paginado para administración, lectura individual,
  alta, edición, publicación/despublicación y semántica de baja/eliminación.
- Imágenes: flujo de carga o referencia de imágenes, tipos/tamaño admitidos,
  respuesta y relación con el alta/edición del producto.
- Inventario: ajuste por variante, significado de la cantidad enviada y
  respuesta con stock disponible/reservado. Validar con Core la regla de no
  permitir quedar por debajo de reservas y si se expondrá `min_allowed_stock`.
- Promociones: listado, alta/edición, estado y vigencia, `stackable` cuando
  aplique según la spec, y forma de previsualizar el precio efectivo.
- Cupones: operaciones administrativas de consulta/alta/edición y preview de
  aplicación; definir si se requiere una operación de prueba separada y qué
  datos necesita sin consumir contadores o alterar estado.
- Auditoría: entidades consultables, filtros, paginación, campos de respuesta y
  permisos, coordinados con las capacidades reales de Core.

Las rutas `/admin/products` y `/admin/promotions`, errores por campo,
`new_stock`, unidades reservadas, `min_allowed_stock`, preview, carga de
imágenes, auditoría y confirmaciones destructivas aparecen como expectativas de
consumo, no como contrato aprobado. Deben validarse en la matriz de operaciones
y el OpenAPI. La confirmación destructiva puede pertenecer a la experiencia de
usuario; el contrato BFF debe definir por separado la operación y sus
precondiciones sin codificar decisiones de interfaz.

## Decisiones pendientes antes de congelar OpenAPI

La primera fase debe registrar una decisión o un responsable y criterio de
validación para cada punto; no completar los espacios con supuestos:

- Rutas, verbos, versionado, identificadores y operaciones de ciclo de vida de
  producto, variante, imagen, promoción, cupón y auditoría.
- Campos obligatorios/opcionales, tipos, unidades, límites, formatos de fecha,
  paginación, filtros, ordenamiento y semántica de `null`/campos omitidos.
- Esquema uniforme de errores de validación por campo y de errores de negocio;
  correspondencia de códigos HTTP para autenticación, permisos, conflictos,
  recursos inexistentes y fallos de Core.
- Roles admitidos (Administrador/Vendedor según la spec de producto), fuente de
  identidad, política de autorización por operación y comportamiento ante
  token ausente, inválido o rol insuficiente.
- Contrato Core disponible para cada operación, campos y errores GraphQL,
  permisos requeridos y cualquier limitación que requiera adaptar el contrato
  BFF. Core conserva las reglas de negocio autoritativas.
- Ajuste de stock absoluto frente a delta, unidad de inventario, cálculo de
  stock mínimo reservado y datos que Core garantiza devolver.
- Soporte real de Core para imágenes, promociones/cupones, preview y auditoría;
  comportamiento observable cuando una capacidad no exista.
- Necesidad de eventos/caché e invalidación: origen, evento, SLA y consistencia,
  solo si Core acredita un contrato aplicable. No forma parte del mínimo por
  defecto.

## Secuencia y entregables

### Fase 1 — Descubrimiento y contrato

1. Inventariar OpenAPI, rutas/controladores/DTOs/servicios BFF y pruebas
   administrativas actuales; anotar cobertura y discrepancias sin inferir que
   cumplen el contrato por existir.
2. Validar la matriz de operaciones y decisiones pendientes con responsables de
   producto, Frontend y Core. Resolver compatibilidad con RF-1..RF-8 y la regla
   de stock reservado de `specs/006-manage-catalog-inventory/spec.md`.
3. Actualizar `bgg-shop-bff/specs/openapi.yaml` con las operaciones, esquemas,
   seguridad y respuestas acordadas. Este es un gate previo a implementar o
   aceptar el contrato; no se congela mientras queden decisiones funcionales
   sin dueño.

### Fase 2 — Implementación y adaptación BFF

1. Reconciliar rutas existentes con OpenAPI y completar solo las operaciones
   aprobadas.
2. Implementar/ajustar DTOs y validación en el borde BFF; autorizar cada
   operación con el rol acordado.
3. Integrar las operaciones REST con Core mediante las superficies existentes
   de servicios/proxy, sin duplicar reglas autoritativas ni inventar
   operaciones GraphQL.
4. Normalizar errores públicos. Los detalles técnicos del upstream se
   mantienen fuera de las respuestas de cliente.

### Fase 3 — Evidencia y documentación

1. Añadir pruebas unitarias de autorización, validación/DTOs, controladores y
   mapeo de errores; añadir pruebas contractuales que verifiquen solicitudes y
   respuestas GraphQL simuladas para cada integración acordada.
2. Actualizar la documentación BFF pertinente y referenciar OpenAPI como fuente
   del contrato HTTP.
3. Ejecutar los comandos existentes documentados en
   [`tests/CONTRACTS_README.md`](../tests/CONTRACTS_README.md) y los tests
   administrativos pertinentes. Registrar resultados reales; no atribuir
   verificación a checks no ejecutados.

## Criterios de aceptación del plan

- OpenAPI define la superficie REST administrativa acordada y no quedan
  discrepancias no resueltas con las necesidades de consumo aprobadas.
- Cada operación está asociada a una regla de autorización, DTO/validación,
  operación Core (o limitación explícita), respuestas públicas y pruebas.
- La validación de inventario y límites de stock se basa en datos/reglas
  confirmados por Core; no se duplica la autoridad de inventario.
- Fallos del upstream no exponen datos técnicos en las respuestas públicas.
- Pruebas contractuales y unitarias cubren los flujos acordados, y la
  documentación indica comandos y resultados observados.
- El trabajo permanece en BFF; la implementación del frontend continúa pausada
  hasta la aprobación del contrato.

## Dependencias y límites

- Spec de producto: `specs/006-manage-catalog-inventory/spec.md` (RF, flujos,
  actores y regla de inventario reservado).
- Contrato BFF actual: `bgg-shop-bff/specs/openapi.yaml`.
- Implementación y evidencia existentes a reconciliar: `bgg-shop-bff/app.py`,
  `bgg-shop-bff/src/controllers/`, `bgg-shop-bff/src/dtos/`,
  `bgg-shop-bff/src/services.py`, `bgg-shop-bff/src/proxy.py` y
  `bgg-shop-bff/tests/test_admin*.py`.
- Expectativas de consumidor, todavía no contrato:
  `bgg-shop-frontend/specs/007-manage-catalog-inventory-frontend.md`.
- No se incluyen cambios Core ni frontend, un nuevo almacenamiento BFF, caché o
  eventos sin una necesidad/contrato aprobado, ni cambios al OpenAPI en esta
  tarea de planificación.
