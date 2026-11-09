# ⚡ BGG Shop - Backend-For-Frontend (`bgg-shop-bff`)

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Flask 3.0](https://img.shields.io/badge/Flask-3.0-black.svg)](https://flask.palletsprojects.com/)
[![Pandas 2.2](https://img.shields.io/badge/Pandas-2.2-150458.svg)](https://pandas.pydata.org/)
[![Architecture](https://img.shields.io/badge/Pattern-BFF%20Gateway-orange.svg)](https://microservices.io/patterns/apigateway.html)

## 📌 Descripción General

**`bgg-shop-bff`** es la capa de **orquestación, transformación de datos y API Gateway** de la plataforma e-commerce de juegos de mesa.

Desarrollado con **Flask**, actúa como la API REST del cliente web
(`bgg-shop-frontend`) para catálogo y operaciones de cuenta/compra. El
navegador consume REST; el BFF coordina esas solicitudes con GraphQL en el
Core (`bgg-shop-core`) y adapta las respuestas al contrato REST.

El contrato REST canónico es [`specs/openapi.yaml`](specs/openapi.yaml). El
esquema GraphQL del Core está en
[`../bgg-shop-core/specs/schema.graphql`](../bgg-shop-core/specs/schema.graphql).
Algunas operaciones documentadas, en particular las del chatbot, siguen
marcadas como planificadas; el contrato no acredita por sí solo que estén
implementadas.

---

## 🏗️ Arquitectura y Flujo de Datos

El BFF es el límite REST entre el cliente y el Core:

Frontend React/Vite ── REST/JSON ──> BFF Flask ── GraphQL ──> Core Django/Graphene
                                      │                       ├── PostgreSQL
                                      │                       └── Redis/Celery
                                      └── Redis (rate limit del chatbot)

* **Contrato REST:** El inventario canónico está en `specs/openapi.yaml`; este README resume operaciones seleccionadas.
* **Adaptación:** Traduce los nombres camelCase de GraphQL a snake_case en la
  respuesta REST de productos.
* **Aislamiento:** El navegador no necesita conocer la URL ni el esquema
  GraphQL del Core.

## Servicios expuestos

### `POST /api/v1/auth/register` y `POST /api/v1/auth/login`

El BFF expone registro y login con credenciales locales y adapta las
mutaciones GraphQL del Core a REST. El registro responde `201` sin sesión; el
login responde `200` con usuario y tokens. Los errores públicos son `400`,
`401`, `409` y `502`.

La especificación completa del caso de uso, incluyendo ejemplos, mapeos y
decisiones de seguridad, está en
[`docs/CU-C01-AUTHENTICATION-CHANGES.md`](../docs/CU-C01-AUTHENTICATION-CHANGES.md).

### `GET /api/v1/auth/me`

Devuelve únicamente `is_staff` e `is_superuser`, consultados desde el estado
actual de la cuenta en Core. Requiere un token `Bearer` de una cuenta activa;
un comprador también recibe `200` con ambos indicadores en `false`. Las
respuestas de autenticación son `401` y los fallos al verificar la identidad
en Core son `502`, siempre con errores sanitizados y `Cache-Control: no-store`.
Una clave de operación por sí sola no autentica esta solicitud.

### `GET /health`

No requiere parámetros y responde `200` con:

```json
{"status": "healthy"}
```

### `GET /api/v1/products`

Lista y filtra el catálogo paginado. Parámetros opcionales:

| Parámetro | Tipo | Predeterminado | Restricciones |
| --- | --- | ---: | --- |
| `page` | entero | `1` | positivo |
| `page_size` | entero | `20` | positivo y como máximo `100` |
| `search` | texto | — | entre 1 y 200 caracteres |
| `year_published` | entero | — | entre `0` y `9999` |
| `min_players`, `max_players` | entero | — | entre `1` y `999` |
| `category_id` | entero | — | mayor o igual que `1` |
| `price_min`, `price_max` | número | — | no negativos |

Ejemplo:

```bash
curl "http://localhost:5000/api/v1/products?page=1&page_size=20"
```

Respuesta `200`:

```json
{
  "items": [{
    "bgg_id": 274364,
    "name": "Watergate",
    "release_year": 2019,
    "min_players": 2,
    "max_players": 2,
    "playing_time_minutes": 60,
    "min_age": 12,
    "weight": 2.25,
    "category": ["Juegos de Estrategia"],
    "price": 90000.0,
    "quantity": 10,
    "publisher": "Salt & Pepper Games",
    "image_url": "/media/portadas/2743640.webp"
  }],
  "page": 1,
  "page_size": 20,
  "total": 1,
  "total_pages": 1
}
```

Los valores reales dependen de `product_boardgame`. Una paginación inválida
responde `400` con `{"error": "..."}`. Si el Core falla o entrega un payload
inválido, responde `502`; no dependas de detalles internos del upstream.

### Esquema de producto y paginación

La respuesta REST usa `snake_case`: `bgg_id`, `release_year`,
`playing_time_minutes`, `image_url`, `page_size` y `total_pages`. Cada
producto contiene además `name`, `min_players`, `max_players`, `min_age`,
`weight`, `category` (lista de textos), `price`, `quantity` (stock actual), y
`publisher`.

El BFF traduce estos parámetros a argumentos GraphQL `camelCase`, convierte la
respuesta a `snake_case` y responde `400` para validación inválida o `502` si
falla el Core. Permite CORS desde `http://localhost:3000` y
`http://127.0.0.1:3000`. Además expone las operaciones de autenticación
documentadas al comienzo de esta sección. El carrito se expone mediante las
rutas descritas a continuación; las operaciones de compra se documentan en la
sección siguiente.

La implementación completa del alcance y sus limitaciones está en
[`docs/CU-C02-FILTERING-CHANGES.md`](../docs/CU-C02-FILTERING-CHANGES.md).

### `GET /api/v1/cart` y operaciones de artículos

| Método | Ruta | Entrada | Resultado |
| --- | --- | --- | --- |
| `GET` | `/api/v1/cart` | Cookie de carrito opcional | Carrito actual |
| `POST` | `/api/v1/cart/items` | `bgg_id`, `quantity` | Agrega esa cantidad |
| `PATCH` | `/api/v1/cart/items/{bgg_id}` | `quantity` | Establece la cantidad solicitada |
| `DELETE` | `/api/v1/cart/items/{bgg_id}` | — | Elimina el artículo |

Las cantidades de alta y actualización deben ser enteros positivos; el Core
valida el stock vigente. Todas las respuestas de carrito contienen `lines`,
`total` y `warnings`; cada línea incluye `bgg_id`, `name`, `quantity`,
`available_stock`, `unit_price` y `subtotal`. Un exceso de stock responde `409`
con el carrito sin cambios y el error de Core dentro de `warnings`. Las
solicitudes inválidas responden `400` y un fallo del Core responde `502`.

Para compradores anónimos, el BFF emite el identificador opaco del Core en una
cookie `cart_id` HttpOnly, `SameSite=Lax`; no acepta identificadores de usuario
del cliente. La cookie es `Secure` fuera de debug/desarrollo y se puede ajustar
con `CART_COOKIE_SECURE`; `CART_COOKIE_NAME` permite cambiar su nombre. Las
solicitudes autenticadas reenvían el encabezado `Authorization: Bearer ...` al
Core, que determina el carrito de cuenta. En login, el BFF envía la cookie como
`guestCartId` para combinar el carrito anónimo y la elimina solo si el login es
exitoso.

Ejemplo de respuesta:

```json
{
  "lines": [{
    "bgg_id": 274364,
    "name": "Watergate",
    "quantity": 2,
    "available_stock": 10,
    "unit_price": 90000.0,
    "subtotal": 180000.0
  }],
  "total": 180000.0,
  "warnings": []
}
```

### Wishlist

The authenticated Wishlist is available through `GET /api/v1/wishlist`,
`POST /api/v1/wishlist` with `{"bgg_id": 274364}`, and
`DELETE /api/v1/wishlist/{bgg_id}`. The BFF forwards the caller's
`Authorization` header unchanged; Core derives account ownership from that
token. Add and remove return the existing product shape, while list returns
`{"items": [...]}`. Invalid identifiers return `400`, missing or invalid
authentication returns `401`, and sanitized Core/upstream failures return
`502`. Adding an item to the cart does not remove it from the Wishlist.
See the [Wishlist specification](specs/006-wishlist/spec.md).

### Purchase and order endpoints

All purchase and order routes require `Authorization: Bearer <access-token>`. The BFF forwards that token to Core; it never accepts a user ID and never uses Mercado Pago credentials.

| Method | Route | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/checkout` | Create an order from the authenticated cart and return `order` plus `init_point`. |
| `POST` | `/api/v1/checkout/confirm` | Ask Core to verify a payment ID and return the updated `order`. |
| `GET` | `/api/v1/orders` | List the authenticated customer's orders. |
| `GET` | `/api/v1/orders/{order_id}` | Read an owned order, including lines, totals, shipping, invoice metadata, and `payment_status_detail`. |
| `POST` | `/api/v1/orders/{order_id}/retry-payment` | Initialize a new payment attempt for an eligible order. |
| `GET` | `/api/v1/orders/{order_id}/invoice` | Stream the owned invoice PDF from Core. |

Checkout accepts `shipping_mode` (`standard` or `pickup`) and an optional `address` with `recipient`, `street`, `city`, `postal_code`, and `phone`. Core validates required delivery fields, calculates prices, and owns order state. Payment confirmation accepts an order UUID and a non-empty, length-limited payment identifier containing only safe characters; the browser never supplies a Mercado Pago access token.

Order responses use `snake_case` and include snapshot line prices, currency, shipping fields, payment state and its provider detail, and invoice number/date/total when issued. Missing or invalid credentials return `401`; invalid request data returns `400`; an unowned or missing order returns `404`; payment configuration and Core failures are reported as `503` and `502` respectively. The invoice route validates UUIDs before constructing the Core URL, forwards the same bearer token, streams `application/pdf` with the upstream attachment header, and preserves Core `404` responses.

### Métricas de ventas (Admin)

Las rutas `GET /api/v1/admin/sales-metrics` y
`GET /api/v1/admin/sales-metrics/categories` requieren un usuario activo con
rol staff o superuser. Ambas respuestas son `no-store`.

La ruta de métricas acepta `from` y `to` como instantes ISO-8601 con zona
horaria, y acepta parámetros repetidos `category` y `product_id`. Se deben
enviar ambos límites de fecha o ninguno; un límite faltante responde `400`
con `code: INVALID` y `field` indicando el parámetro faltante. Si se omiten
ambos, se usa el rango de los últimos 30 días. El rango máximo es de 366 días
y es semiabierto `[from, to)` en UTC.

La respuesta usa `snake_case` e incluye `revenue_total`, `orders_count`,
`top_products`, `orders_by_dispatch_status`, `orders_by_payment_status` y
`revenue_by_day`. El ingreso suma los subtotales históricos de líneas de
órdenes pagadas por `paid_at`; los conteos de estado usan `created_at`. Los
filtros de categoría son coincidencias exactas con el valor almacenado y los
productos se identifican por BGG ID. La ruta de categorías devuelve los
valores distintos almacenados en `product_boardgame.category`.

Las respuestas de validación usan `400`, la falta de autenticación `401`, un
rol no autorizado `403` y los errores no reconocidos del Core se exponen como
`502` genérico sin detalles internos.

### Chatbot CU-C07 (en progreso)

El BFF implementa actualmente dos rutas:

| Método | Ruta | Estado observado en el código |
| --- | --- | --- |
| `POST` | `/api/v1/chat/conversations` | Crea una conversación asociada a un token de usuario o a una sesión anónima. |
| `POST` | `/api/v1/chat/conversations/{conversation_id}/messages` | Valida mensajes de hasta 2.000 caracteres, aplica guardrails y registra en Core los mensajes aceptados. |

Estado y límites comprobados de Feature 013:

- La generación de respuestas usa OpenRouter (`OPENROUTER_API_KEY` y
  `OPENROUTER_MODEL`) cuando está configurado; ante falta de configuración,
  error de transporte/HTTP o respuesta inválida, recurre a Ollama local
  (`deepseek-r1:8b`). Los embeddings permanecen en Ollama. Las pruebas no leen
  `.env` ni llaman al servicio externo: simulan la respuesta HTTP con valores
  sintéticos. La selección enfocada de proveedor, RAG e integración pasó **51
  pruebas, 12 warnings**, también confirmadas por revisión independiente y
  spot-check local. No se validaron credenciales reales contra OpenRouter.
- La selección BFF de guardrails, privacidad, RAG, catálogo y conversaciones pasó **69 pruebas, 0 fallos, 99 warnings**. La selección de integración/guardrails/privacidad pasó **64 pruebas, 0 fallos, 87 warnings**. Los tests RAG usan fakes deterministas; no son aceptación de Chroma local.
- LangChain y ChromaDB siguen siendo requisitos aprobados. En el entorno Python local comprobado, el import probe no pudo importar `langchain`; no instales dependencias ni contactes registries como parte de esta guía.
- La suite de contratos BFF reportó **7 aprobadas y 9 fallidas**, en pruebas existentes de producto/carrito/cupón/checkout/wishlist/pedidos. No se conoce causa o baseline; no se atribuyen esos fallos al chatbot ni se consideran corregidos.
- La prueba de navegador determinista pasó **7 casos**, pero intercepta `/api/v1/**` con mocks. No demuestra integración BFF/Core, enforcement de ownership ni expiración de la base de datos.
- El cierre de aceptación completa sigue pendiente. Los comandos exactos, evidencia de Core, fallos y limitaciones están en [`../specs/013-add-chatbot/quickstart.md`](../specs/013-add-chatbot/quickstart.md).

### Comandos locales enfocados

Ejecuta estos comandos desde la raíz del repositorio y solo en el entorno local de pruebas:

```bash
cd bgg-shop-bff && PYTHONPATH=. pytest -q tests/test_chatbot_service_integration.py tests/test_chatbot_rag.py tests/test_chatbot_guardrails.py tests/test_chatbot_privacy.py
cd bgg-shop-bff && PYTHONPATH=. pytest -q tests/test_chatbot_guardrails.py tests/test_chatbot_privacy.py tests/test_chatbot_rag.py tests/test_chatbot_catalog.py tests/test_chatbot_conversations.py
```

Resultados observados: **64 passed, 0 failed, 87 warnings** en el primer comando y **69 passed, 0 failed, 99 warnings** en el segundo. No son pruebas de integración de servicios reales. No uses una base de datos no desechable, datos personales/de pedidos reales, CI, staging, producción o servicios remotos; no imprimas secretos ni ejecutes comandos de despliegue. Esta documentación no instruye cómo iniciar un proveedor o retención de datos.

Trazabilidad: contrato/requisitos en [`../specs/013-add-chatbot/spec.md`](../specs/013-add-chatbot/spec.md); decisiones y límites en [`../specs/013-add-chatbot/plan.md`](../specs/013-add-chatbot/plan.md); tareas y evidencia en [`../specs/013-add-chatbot/tasks.md`](../specs/013-add-chatbot/tasks.md); implementación en [`src/controllers/chatbot_controller.py`](src/controllers/chatbot_controller.py), [`src/chatbot/guardrails.py`](src/chatbot/guardrails.py), [`src/chatbot/rag.py`](src/chatbot/rag.py) y [`src/chatbot/catalog.py`](src/chatbot/catalog.py); pruebas en `tests/test_chatbot_service_integration.py`, `tests/test_chatbot_guardrails.py`, `tests/test_chatbot_privacy.py`, `tests/test_chatbot_rag.py`, `tests/test_chatbot_catalog.py` y `tests/test_chatbot_conversations.py`.

---

## 🛠️ Tech Stack

* **Lenguaje:** Python 3.12+
* **Framework Web:** Flask 3.0+
* **Cliente HTTP:** `requests` / `httpx`
* **Contenerización:** Podman / Podman Compose (Rootless)

---

## 🚀 Inicio Rápido (Entorno Local con Podman)

Para iniciar el BFF junto con sus dependencias, usa Podman y un proveedor
Compose desde la raíz de este repositorio:

```bash
podman compose -f podman-compose.yaml up -d --build
```

El servicio queda publicado en `http://localhost:5000`; dentro de Compose,
`SALEOR_GRAPHQL_URL` apunta a `http://api:8000/graphql/`. La interfaz Core
GraphQL está en `http://localhost:8000/graphql/`. Para detener los servicios
sin borrar sus volúmenes, ejecuta desde la raíz:

```bash
podman compose -f podman-compose.yaml down
```

El Compose usa valores predeterminados de desarrollo. No se requiere una
credencial de Mercado Pago para iniciar el BFF; las operaciones de compra sí
requieren la configuración de sandbox descrita en la sección de checkout.
