# BFF Functional Specification: Customer Authentication (As-Built)

**Input**: CU-C01
**Status**: As-built / retrospective
**Scope**: The BFF REST boundary for registration and login, including its mapping to Core. Buyer-facing browser-session behavior remains described by the [canonical CU-C01 specification](../../../specs/001-authentication-as-built/spec.md).

## BFF responsibilities

The BFF exposes registration and login as JSON REST operations. It validates and reshapes request data, calls the corresponding Core GraphQL mutation, maps the Core user/session result to the REST DTO, and translates known errors to HTTP responses. It does not provide a logout operation or independently implement credential verification.

| BFF requirement | REST contract | Core operation | BFF behavior and evidence |
| --- | --- | --- | --- |
| **BFF-C01-001 — Register a buyer.** Accept email, password, first name, and last name; return the created user without a password. | `POST /api/v1/auth/register` (`registerAccount`) | `Mutation.register(input: RegisterInput!)` | The proxy validates and normalizes the registration fields, maps `first_name` / `last_name` to Core `firstName` / `lastName`, and returns user fields only in the tested registration response. See [OpenAPI](../openapi.yaml), [auth controller](../../src/controllers/auth_controller.py), [auth proxy](../../src/proxy.py), [auth DTOs](../../src/dtos/auth.py), and [auth tests](../../tests/test_auth.py). |
| **BFF-C01-002 — Authenticate a buyer.** Return the account and Core-issued session fields when login succeeds. | `POST /api/v1/auth/login` (`loginAccount`) | `Mutation.login(input: LoginInput!)` | The proxy maps the returned token, refresh token, and CSRF token to the REST `session` object; it rejects a Core login result that has no session. A guest `cart_id` cookie, when present, is sent as `guestCartId` to Core. On a successful login response, the BFF deletes that cookie. See [OpenAPI](../openapi.yaml), [route wiring](../../app.py), [auth proxy](../../src/proxy.py), and [auth/cart tests](../../tests/test_auth.py) and [cart tests](../../tests/test_cart.py). |
| **BFF-C01-003 — Validate and translate authentication errors.** | Both authentication operations | `register` and `login` | Invalid request fields return HTTP 400; duplicate-email errors return 409; invalid credentials return HTTP 401 with the generic message “Invalid email or password.”; other upstream GraphQL failures return HTTP 502 without upstream detail. These mappings are implemented in the [auth controller](../../src/controllers/auth_controller.py) and exercised in [auth tests](../../tests/test_auth.py). |

## Authentication boundary and limitations

- Registration and login are the only BFF authentication routes in this feature. There is no BFF logout endpoint; local logout is outside this project's REST responsibility.
- Login returns the Core session fields to the caller. The BFF does not store or rotate the buyer's access or refresh tokens.
- Guest-cart handoff is limited to passing the cookie identifier in Core's login input and clearing the cookie after a successful response. Cart merging itself is a Core responsibility.
- The BFF's tested registration response contains a user and no session. Registration is not described here as establishing a session.

## Verification evidence

- [Canonical end-to-end behavior](../../../specs/001-authentication-as-built/spec.md)
- [BFF OpenAPI contract](../openapi.yaml)
- [Core GraphQL schema](../../../bgg-shop-core/specs/schema.graphql)
- [Controller and route wiring](../../src/controllers/auth_controller.py), [application routes](../../app.py)
- [Core proxy and REST DTOs](../../src/proxy.py), [auth DTOs](../../src/dtos/auth.py)
- [BFF tests](../../tests/test_auth.py), [cart/login handoff tests](../../tests/test_cart.py)

## BFF scope exclusions

The BFF does not establish the browser's persistent navigation state, implement server-side logout, define credential storage policy, or replace Core authentication and authorization. Those are not BFF operations evidenced by this layer.
