# Plan: CU-A01 — Contrato e integración de catálogo e inventario en BFF

Owner: `bgg-shop-bff`
Spec de producto: [`specs/006-manage-catalog-inventory/spec.md`](../../specs/006-manage-catalog-inventory/spec.md)
Contexto BFF: [`007-manage-catalog-inventory-bff.md`](./007-manage-catalog-inventory-bff.md)
Contexto de consumo: [`bgg-shop-frontend/specs/007-manage-catalog-inventory-frontend.md`](../../bgg-shop-frontend/specs/007-manage-catalog-inventory-frontend.md)

## Estado y objetivo

Planificación pendiente de decisiones de contrato. OpenAPI contiene desde
2026-10-31 un borrador parcial de nueve operaciones administrativas existentes,
marcadas como propuestas; no declara que la implementación cumpla el contrato.
El objetivo es acordar primero el contrato REST público del BFF y su integración
con Core; luego ajustar o completar la implementación existente para que cumpla
ese contrato.

El frontend permanece pausado hasta que el contrato BFF esté definido y
validado. El alcance de este plan termina en BFF, OpenAPI, integración con Core,
pruebas BFF y documentación relacionada; no incluye implementar ni actualizar
el frontend.

## Estado observado y línea base

- Al crear el plan, `bgg-shop-bff/specs/openapi.yaml` no definía operaciones
  administrativas de productos, promociones, cupones, inventario o auditoría.
  El borrador parcial posterior cubre nueve operaciones de rutas existentes;
  las decisiones restantes se registran en las tareas.
- El código BFF contiene rutas y controladores administrativos parciales
  (por ejemplo, list/create/update de productos y promociones, ajuste de stock y
  preview de aplicación de cupón). Esa presencia no equivale a un contrato
  OpenAPI validado ni demuestra cobertura de todas las necesidades del caso.
  Las tareas deben contrastar y reconciliar esas superficies con el contrato
  aprobado; no duplicarlas a ciegas ni tratarlas como contrato ya terminado.
- El alcance administrativo solicitado requiere resolver también operaciones
  cuya forma HTTP no está fijada en los artefactos consultados: detalle y
  baja de producto, manejo de imágenes, gestión de cupones,
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
   manteniendo Core como autoridad para stock, precios, promociones,
   cupones y persistencia.
5. Traducir errores de Core a respuestas públicas estables y no filtrar cuerpos,
   trazas, mensajes internos ni datos sensibles del upstream.
6. Añadir pruebas unitarias y contractuales con Core simulado y actualizar la
   documentación BFF afectada.

## Capacidades que el contrato debe resolver

La lista es una entrada para definir el contrato, no una afirmación de métodos,
rutas o esquemas ya acordados:

Si una operación `IN`/`OUT` no impacta la base, se cancela o rechaza; una
transacción efectivamente rechazada o revertida no deja el cambio aplicado. Si se
confirma el rechazo o rollback sin cambios en la base, se permite procesar nuevamente
un reintento con el mismo ID y datos. Un error de comunicación o HTTP no demuestra
rollback: el servidor puede confirmar
y perderse la respuesta, y un reintento aditivo podría duplicar la operación actual.
Informar al usuario y registrar el error de forma segura sin detalles sensibles,
sin suponer seguro reintentar con el contrato actual. Cada movimiento tendrá un ID
único; repetir el mismo ID y datos no debe duplicar el cambio, y reutilizarlo con
datos diferentes debe rechazar la operación sin aplicar un nuevo cambio de stock.
Registrar el ID y modificar el stock deben confirmarse atómicamente. Los ID de movimientos exitosos
se conservarán indefinidamente, sin vencimiento, también ante reintentos tardíos.
Fuera de la posibilidad de reintento indicada, el plazo y tratamiento de ID de
fallos o rechazos no están aprobados. Quedan abiertos
formato y alcance del ID, campos que determinan la identidad de los datos, detalles
de la respuesta de rechazo, respuesta a reintentos de una operación aún en curso y
recuperación del resultado incierto. Definir y validar primero el contrato; no se acredita implementación.

Trazabilidad de stock: requisito `specs/006-manage-catalog-inventory/spec.md`;
contratos actuales `bgg-shop-core/specs/schema.graphql` y `bgg-shop-bff/specs/openapi.yaml`;
implementación `bgg-shop-bff/src/controllers/admin_products_controller.py` y
`bgg-shop-bff/src/services.py`; pruebas relacionadas `bgg-shop-bff/tests/test_admin_validation.py`
y `bgg-shop-bff/tests/test_admin_error_mapping.py`. La inspección local con `rg`
no encontró ID de movimiento en las firmas actuales; no se ejecutaron pruebas de
runtime para esta actualización documental.

- Productos: búsqueda/listado paginado para administración, lectura individual,
  alta, edición y baja de stock. No existe despublicación ni se infiere eliminación física.
- Imagen: por ahora una `.webp` por producto, indicada por URL o nombre de
  archivo, sin asumir subida de binarios; definir respuesta y relación con alta/edición.
- Inventario: `IN` aumenta el stock y `OUT` lo reduce, incluso parcialmente.
  A cero el producto permanece visible con «Sin stock»; no se hacen reservas.
  Cada edición o variante es otro producto. Si `OUT` supera el stock disponible,
  se informa que quedará en cero. No se establece confirmación ni código HTTP.
  Quedan abiertos los detalles contractuales del ID y la recuperación del resultado incierto. El ingreso
  aditivo existente (`10 + 20 = 30`) no acredita el contrato de reducción.
- Promociones: listado, alta/edición, estado y vigencia; cada producto del carrito
  puede tener su propia promoción, sin combinar descuentos sobre un mismo producto.
  Al comparar descuentos aplicables al mismo producto, prevalece el que descuente
  más pesos, también al comparar un porcentaje con un monto fijo. Los cupones de
  descuento aplican a toda la compra al momento del pago; los cupones por producto no se implementan
  en este MVP. Las promociones y descuentos sí pueden ser por producto.
  Se compara la suma de ahorros de las promociones aplicables a todo el carrito
  con el ahorro del cupón calculado sobre la compra sin descuentos y se aplica
  exclusivamente la alternativa que ahorre más pesos. Si se eligen promociones,
  cada producto puede recibir la suya; si se elige el cupón, no se aplican promociones.
  Ante dos promociones iguales para un producto aplica la ofrecida por la tienda.
  Cuando el usuario usa un cupón que empata con una promoción, se le avisa que
  se aplicará la promoción de tienda y no el cupón, sin definir la interfaz.
  No hay impuestos y el envío es gratis, sin modificar otras specs cerradas de
  checkout. Las fracciones hasta 0,50 inclusive se mantienen; desde 0,51 se redondean hacia arriba. El límite de descuento es 50%.
  El cupón no se da de baja antes de que se realice el pago; no se presupone que
  todos sean de un solo uso. El resultado de intentos fallidos y concurrentes sigue abierto.
  Quedan pendientes elegibilidad o exclusiones; identidad de promociones iguales
  y precedencia si ambas proceden de la tienda; otras igualdades; unidad y etapa
  del redondeo; si el 50% aplica por producto, cupón o compra y si se rechazan o
  limitan configuraciones; consumo del contador ante un intento de pago fallido;
  y la forma de preview. Resolver estos puntos y definir y validar los contratos
  antes de implementar. Las gift
  cards y el crédito son medios de pago, no cupones de descuento.
  El checkout actual usa precios base y la integración de descuentos no está validada.
- Cupones: clientes, administradores e invitados pueden consultar los cupones
  activos sin carrito; GraphQL debe devolver los habilitados y disponibles.
  Aplicar uno requiere usuario autenticado y carrito. La consulta previa solo
  muestra cupones, sin consumir ni reservar usos. Se identifica la estimación en
  la vista que ofrece pagar. Se rechazan con motivo los cupones inactivos,
  vencidos, agotados o cuyo descuento supere el 50% de la compra sin descuentos;
  esta decisión reemplaza el límite automático anterior para cupones fijos.
  Se indicó `404` si no se encuentra el cupón y `401` para uso no autorizado.
  Siguen pendientes las formas de las operaciones, los campos de respuesta, la
  interacción del límite con el redondeo y el estado de usos bloqueados por un
  pago incierto. Son requisitos, no evidencia de implementación.
- Auditoría: registrar usuario, fecha, acción y valores anteriores y nuevos para
  cambios de productos, movimientos de stock, promociones y cupones. Coordinar
  con Core las entidades consultables y campos de respuesta. El acceso a la
  auditoría, filtros, paginación y captura de secretos siguen pendientes. La
  auditoría básica permanece en alcance. Como requisitos futuros y fuera del alcance
  actual se prevén siete días en la base y un ZIP local semanal; no se eliminarán
  filas sin verificar antes la creación correcta del archivo y no se acuerda purga
  automática. Queda pendiente compatibilizar la ejecución
  semanal con la retirada exactamente a los siete días, pues ambas podrían retrasarse.
  Los ZIP no vencen ni se eliminan automáticamente; su eliminación manual queda a
  cargo del usuario y está acordada solo para `is_superuser=true`, no para `is_staff`
  por sí solo. La generación semanal del ZIP y el mecanismo que hace cumplir el
  permiso de borrado quedan pendientes y fuera del alcance actual de la 007. No se
  afirma que se aplique en el filesystem. La retención es indefinida hasta la
  eliminación manual de cada archivo. La
  decisión anterior de conservar los ZIP un mes queda reemplazada. Esta política no
  se considera implementada ni validada. Siguen pendientes el inicio de los siete días,
  el horario del proceso,
  el mecanismo de archivo atómico ante fallas, el acceso y consulta de archivos y
  el cifrado.
  Los ejemplos de filtros no son decisiones confirmadas. La existencia
  de AuditLog no acredita cobertura de todos los flujos ni conformidad.

Las rutas `/admin/products` y `/admin/promotions`, errores por campo,
preview, referencia de imagen, auditoría y confirmaciones destructivas aparecen como expectativas de
consumo, no como contrato aprobado. Deben validarse en la matriz de operaciones
y el OpenAPI. La confirmación destructiva puede pertenecer a la experiencia de
usuario; el contrato BFF debe definir por separado la operación y sus
precondiciones sin codificar decisiones de interfaz.

## Decisiones pendientes antes de congelar OpenAPI

La primera fase debe registrar una decisión o un responsable y criterio de
validación para cada punto; no completar los espacios con supuestos:

- Rutas, verbos, versionado, identificadores y operaciones de ciclo de vida de
  producto, imagen, promoción, cupón y auditoría, salvo el ingreso de stock previsto.
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
- Detalles pendientes de aplicación de descuentos, ID de movimiento y recuperación
  del resultado incierto, y datos que Core
  garantizará devolver. El ingreso aditivo por producto está implementado en
  BFF y probado con Core simulado; no se verificó concurrencia PostgreSQL.
- No se hacen reservas. Core conserva `stackable` y modelo/consulta de reservas;
  el formulario frontend acepta URL y nombre de imagen, y una tarjeta muestra
  «Sin stock» con cantidad cero. Esto no prueba la conformidad integral con las
  decisiones vigentes; reconciliar runtime y contrato sin inventar operaciones.
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
  producto, Frontend y Core. Resolver compatibilidad con RF-1..RF-8 y las
  políticas de inventario pendientes en `specs/006-manage-catalog-inventory/spec.md`.
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
  actores y decisiones de inventario pendientes).
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
