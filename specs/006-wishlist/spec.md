# BFF Functional Specification: Wishlist

**Input**: CU-C06
**Status**: As-built
**Scope**: Authenticated REST operations that adapt Core's Wishlist GraphQL query and mutations.

## REST contract

| Method and path | Request | Core operation | Success response |
| --- | --- | --- | --- |
| `GET /api/v1/wishlist` | No body | `Query.myWishlist` | `200` with `{"items": [Product]}` |
| `POST /api/v1/wishlist` | `{"bgg_id": positive integer}` | `Mutation.addToWishlist(bggId)` | `200` with the returned `Product` |
| `DELETE /api/v1/wishlist/{bgg_id}` | Positive path integer | `Mutation.removeFromWishlist(bggId)` | `200` with the returned `Product` |

All three operations require an `Authorization` header. The BFF forwards its
exact value to Core and never accepts a user identifier; Core determines
ownership from the authenticated token. `bgg_id` must be a positive integer
within GraphQL's signed 32-bit `Int` range. The POST request rejects unknown
fields, including user identifiers.

The BFF maps Core product fields into the existing REST `Product` schema using
snake_case. Input validation returns `400`; missing or Core-rejected
authentication returns `401`; a recognized missing-product error returns
`404`; unrecognized GraphQL errors, transport failures, and invalid upstream
payloads return a generic `502` response. Upstream exception text, URLs,
credentials, and stack traces are not returned publicly.

Wishlist membership is independent of the cart. Adding a Wishlist product to
the cart does not remove it. Core owns Wishlist cleanup after a purchase is
confirmed as paid.

## Product detail identity

`GET /api/v1/games/{slug}` includes the public BoardGameGeek identifier as the
required `bgg_id` field. The Frontend uses this value to save a game to Wishlist
regardless of whether the detail page was opened from catalog navigation or a
direct URL. Core's GraphQL `ProductDetail.bggId` is adapted to this REST field;
no internal identifiers are exposed.

## Evidence

- Contract: [OpenAPI](../openapi.yaml)
- Route registration: [app.py](../../app.py)
- Controller and request DTO: [wishlist_controller.py](../../src/controllers/wishlist_controller.py), [wishlist.py](../../src/dtos/wishlist.py)
- Core adapter: [proxy.py](../../src/proxy.py), [services.py](../../src/services.py)
- Focused behavior and proxy tests: [test_wishlist.py](../../tests/test_wishlist.py)
