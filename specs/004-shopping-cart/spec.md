# BFF Functional Specification: Shopping Cart (As-Built)

**Input**: CU-C04
**Status**: As-built / retrospective
**Scope**: BFF cart REST behavior, identity transport, and mapping to Core cart operations. The end-to-end buyer behavior is in the [canonical CU-C04 specification](../../../specs/004-shopping-cart-as-built/spec.md).

## BFF responsibilities

The BFF exposes cart read/add/update/remove operations. It chooses the identity input from the Authorization header or guest cart cookie, validates cart-item requests, sends the corresponding GraphQL operation to Core, maps Core cart fields to the REST DTO, and returns a guest cart cookie when Core supplies a cart identifier.

| BFF requirement | REST contract | Core operation | BFF behavior and evidence |
| --- | --- | --- | --- |
| **BFF-C04-001 — Read the current cart.** | `GET /api/v1/cart` (`getCart`) | `Query.cart(cartId)` | Without Authorization, the BFF reads its configured cart cookie and passes the identifier to Core; with Authorization, it ignores the guest cookie and passes the header value. Core's cart subtotal becomes the REST `total`; line fields and warnings are mapped. See [OpenAPI](../openapi.yaml), [cart controller](../../src/controllers/cart_controller.py), [cart proxy](../../src/proxy.py), [cart DTO](../../src/dtos/cart.py), and [cart tests](../../tests/test_cart.py). |
| **BFF-C04-002 — Add, set quantity, or remove a line.** | `POST /api/v1/cart/items` (`addCartItem`); `PATCH /api/v1/cart/items/{bgg_id}` (`updateCartItemQuantity`); `DELETE /api/v1/cart/items/{bgg_id}` (`removeCartItem`) | `Mutation.addToCart`, `Mutation.updateCartQuantity`, `Mutation.removeFromCart` | The BFF requires positive integer identifiers and quantities within GraphQL `Int` bounds, rejects unsupported payload fields, and maps the updated cart and Core user errors. See [OpenAPI](../openapi.yaml), [cart controller](../../src/controllers/cart_controller.py), [cart DTO](../../src/dtos/cart.py), [proxy](../../src/proxy.py), and [cart tests](../../tests/test_cart.py). |
| **BFF-C04-003 — Keep guest cart identity opaque to request JSON.** | All four cart operations; successful login at `POST /api/v1/auth/login` (`loginAccount`) | `Query.cart`, cart mutations, and `Mutation.login(input: LoginInput!)` | The guest identifier is carried in an HttpOnly cookie configured by the BFF, not a client-supplied user ID. Authenticated requests pass Authorization and do not use the guest cookie. On login, the BFF forwards the guest identifier as `guestCartId` and clears the cookie after a successful response; Core performs the merge. See [cart controller](../../src/controllers/cart_controller.py), [login route](../../app.py), [proxy](../../src/proxy.py), and [cart tests](../../tests/test_cart.py). |
| **BFF-C04-004 — Surface cart warnings and upstream failures.** | The four cart operations | `Query.cart` and the three cart mutations | Core user errors are returned as cart warnings. A warning with `INSUFFICIENT_STOCK` maps to HTTP 409, `PRODUCT_NOT_FOUND` to 404, and other warnings to 400; input validation returns 400 and an upstream GraphQL exception returns 502. See [cart controller](../../src/controllers/cart_controller.py) and [cart tests](../../tests/test_cart.py). |

## Authentication and identity boundary

The BFF does not authenticate a token itself. When Authorization is present, its value is forwarded to Core and takes precedence over any guest cookie. For a guest, the BFF reads the cookie and sets it from the returned opaque cart identifier using `HttpOnly`, `SameSite=Lax`, path `/`, and the configured `Secure` setting. It does not accept a user identity in cart mutation JSON.

## BFF boundary and limitations

- Cart ownership and authenticated-account selection are Core responsibilities. The BFF only chooses which identity input to forward.
- The login adapter passes the guest cart identifier and clears the cookie after login succeeds; it does not itself merge lines.
- Stock acceptance and cart totals are returned by Core. The BFF exposes Core warnings and totals; it does not reserve inventory or calculate cart pricing.
- The current BFF tests exercise REST validation, cookie/header selection, Core operation forwarding, warning status mapping, and upstream failure. They do not independently prove Core's underlying merge or stock lifecycle.

## Verification evidence

- [Canonical end-to-end behavior](../../../specs/004-shopping-cart-as-built/spec.md)
- [BFF OpenAPI contract](../openapi.yaml)
- [Core GraphQL schema](../../../bgg-shop-core/specs/schema.graphql)
- [Cart controller and DTO](../../src/controllers/cart_controller.py), [cart DTO](../../src/dtos/cart.py)
- [Route and login cookie handling](../../app.py), [Core proxy](../../src/proxy.py)
- [BFF cart/login tests](../../tests/test_cart.py)

## BFF scope exclusions

The BFF does not render the cart, reserve or decrement stock, establish a price snapshot, or implement Core's cart ownership and guest-to-account merge rules.
