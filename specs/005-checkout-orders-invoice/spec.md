# BFF Functional Specification: Checkout, Orders, and Invoice (As-Built)

**Input**: CU-C05
**Status**: As-built / retrospective
**Scope**: The BFF REST boundary for checkout, payment confirmation/retry, order history/detail, and invoice retrieval. The full buyer behavior and sandbox limits are in the [canonical CU-C05 specification](../../../specs/005-checkout-orders-invoice-as-built/spec.md).

## BFF responsibilities

The BFF requires an Authorization header for purchase operations, validates request and path identifiers, forwards buyer context to Core, and translates Core outcomes into REST responses. It returns Core order/payment results without independently calculating totals, verifying payments, updating stock, or issuing invoices.

| BFF requirement | REST contract | Core operation / upstream endpoint | BFF behavior and evidence |
| --- | --- | --- | --- |
| **BFF-C05-001 — Start checkout.** | `POST /api/v1/checkout` (`checkout`) | `Mutation.checkout(address, shippingMode)` | Authorization is required and forwarded. The DTO permits `standard` or `pickup`, validates address shape and values, and passes shipping mode/address to Core. The Core SDL also allows an optional `cartId`, but this BFF mutation omits it; the REST request does not accept cart identity. Success returns `order` and `init_point`. See [OpenAPI](../openapi.yaml), [order controller](../../src/controllers/orders_controller.py), [order DTOs](../../src/dtos/orders.py), [proxy](../../src/proxy.py), and [order tests](../../tests/test_orders.py). |
| **BFF-C05-002 — Confirm or retry payment.** | `POST /api/v1/checkout/confirm` (`confirmCheckoutPayment`); `POST /api/v1/orders/{order_id}/retry-payment` (`retryOrderPayment`) | `Mutation.confirmPayment(orderId, paymentId)`; `Mutation.retryPayment(orderId)` | Both require and forward Authorization. The BFF validates UUID order IDs and the confirmation payment identifier, then returns Core's order and, for a retry, `init_point`. Payment verification remains a Core/provider responsibility. See [order controller](../../src/controllers/orders_controller.py), [order DTOs](../../src/dtos/orders.py), [proxy](../../src/proxy.py), and [order tests](../../tests/test_orders.py). |
| **BFF-C05-003 — List and inspect orders.** | `GET /api/v1/orders` (`listOrders`); `GET /api/v1/orders/{order_id}` (`getOrder`) | `Query.myOrders`; `Query.myOrder(id)` | The BFF requires Authorization, forwards it unchanged, validates order IDs on detail requests, and wraps Core data as `orders` or `order`. Core enforces account ownership. See [OpenAPI](../openapi.yaml), [order controller](../../src/controllers/orders_controller.py), [proxy](../../src/proxy.py), and [order tests](../../tests/test_orders.py). |
| **BFF-C05-004 — Retrieve an order invoice.** | `GET /api/v1/orders/{order_id}/invoice` (`downloadOrderInvoice`) | `Query.myOrders` authorization check, then Core HTTP `GET /invoices/{order_id}` | The proxy first calls `myOrders` with the buyer token, then requests the invoice endpoint with the same Authorization value. A successful PDF response is streamed with upstream content headers; an upstream 404 is returned as 404 and other non-success invoice responses become 502. The invoice download is an HTTP Core endpoint, not an SDL operation. See [order controller](../../src/controllers/orders_controller.py), [invoice proxy](../../src/proxy.py), [Core invoice route](../../../bgg-shop-core/saleor/urls.py), and [order tests](../../tests/test_orders.py). |
| **BFF-C05-005 — Translate purchase errors.** | Checkout, confirmation, retry, order list/detail, and invoice operations | Corresponding operations above | Missing Authorization returns 401. Known Core codes map to their configured HTTP statuses, including not found, invalid address/shipping, empty cart, stock conflict, payment-disabled, and payment outcome errors; unknown upstream failures are hidden behind HTTP 502. The mapping is in the [order controller](../../src/controllers/orders_controller.py) and exercised in [order tests](../../tests/test_orders.py). |

## Authentication and error boundary

For checkout, payment confirmation/retry, order listing/detail, and invoice requests, the controller requires a nonempty Authorization header and forwards that value through the proxy. The BFF does not validate token authenticity, determine order ownership, or verify provider payment data; it maps Core's `UNAUTHENTICATED` and other returned error codes. Input validation errors generated at the REST boundary return HTTP 400.

## BFF boundary and limitations

- Order totals, ownership, order state transitions, payment-provider verification, inventory changes, and invoice eligibility/content belong to Core and its payment integration.
- The BFF's checkout operation does not accept browser-supplied order lines, user IDs, cart IDs, or totals; it forwards the delivery selection and authenticated context.
- Invoice delivery is implemented as a Core HTTP request after a `myOrders` GraphQL authorization check. Do not infer an invoice GraphQL operation from the SDL.
- The BFF tests use mocked upstream behavior for payment/order paths. They establish request validation, auth forwarding, response mapping, and error translation, not a live payment-provider or full purchase lifecycle.

## Verification evidence

- [Canonical end-to-end behavior](../../../specs/005-checkout-orders-invoice-as-built/spec.md)
- [BFF OpenAPI contract](../openapi.yaml)
- [Core GraphQL schema](../../../bgg-shop-core/specs/schema.graphql)
- [Order controller](../../src/controllers/orders_controller.py), [order DTOs](../../src/dtos/orders.py)
- [Core proxy and invoice adapter](../../src/proxy.py), [Core invoice URL route](../../../bgg-shop-core/saleor/urls.py)
- [BFF order tests](../../tests/test_orders.py)

## BFF scope exclusions

The BFF does not render checkout or order-history screens, integrate directly with the payment provider, mark orders paid, change inventory, create invoices, or provide shipping fulfillment.
