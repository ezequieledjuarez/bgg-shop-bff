# ⚡ BGG Shop - Backend-For-Frontend (`bgg-shop-bff`)

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Flask 3.0](https://img.shields.io/badge/Flask-3.0-black.svg)](https://flask.palletsprojects.com/)
[![Pandas 2.2](https://img.shields.io/badge/Pandas-2.2-150458.svg)](https://pandas.pydata.org/)
[![Architecture](https://img.shields.io/badge/Pattern-BFF%20Gateway-orange.svg)](https://microservices.io/patterns/apigateway.html)

## 📌 Descripción General

**`bgg-shop-bff`** es la capa de **orquestación, transformación de datos y API Gateway** de la plataforma e-commerce de juegos de mesa. 

Desarrollado con **Flask**, actúa como la API REST del catálogo para el
cliente web (`bgg-shop-front`). Abstrae la API GraphQL del Core
(`bgg-shop-core`) y adapta su respuesta a un contrato REST. La Home del Frontend consume este servicio para el catálogo y sus filtros.

---

## 🏗️ Arquitectura y Flujo de Datos

El BFF es el límite REST entre el cliente y el Core:

[ bgg-shop-front ]  ──(REST / JSON)──>  [ bgg-shop-bff ]  ──(GraphQL)──>  [ bgg-shop-core ]
(React / Vite)                         (Flask Gateway)                   (Django / Saleor)
│
┌───────────┴───────────┐
▼                       ▼
[ Pandas Analytics ]    [ Health & Proxy ]

* **Contrato REST:** Expone únicamente las rutas descritas abajo.
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
responde `400` con `{"error": "..."}`. Si el Core falla, devuelve errores
GraphQL o entrega un payload inválido, responde `502` con `error` y, cuando
corresponde, `detail`.

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

---

## 🛠️ Tech Stack

* **Lenguaje:** Python 3.12+
* **Framework Web:** Flask 3.0+
* **Cliente HTTP:** `requests` / `httpx`
* **Contenerización:** Podman / Podman Compose (Rootless)

---

## 🚀 Inicio Rápido (Entorno Local con Podman)

### Prerrequisitos
* Podman y Podman Compose activos.
* El servicio `saleor_api` (`bgg-shop-core`) corriendo en `http://api:8000/graphql/`.

### 1. Clonar el Repositorio
```bash
git clone [https://github.com/tu-usuario/bgg-shop-bff.git](https://github.com/tu-usuario/bgg-shop-bff.git)
cd bgg-shop-bff