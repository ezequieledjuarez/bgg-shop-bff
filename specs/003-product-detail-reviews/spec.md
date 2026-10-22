# BFF Functional Specification: Product Detail and Reviews (As-Built)

**Input**: CU-C03
**Status**: As-built / retrospective
**Scope**: The BFF REST operations for reading a game detail and submitting a review. The full buyer behavior is in the [canonical CU-C03 specification](../../../specs/003-product-detail-reviews-as-built/spec.md).

## BFF responsibilities

The BFF maps the public slug-based REST detail request to Core's product-detail query and returns its product, approved-review, and summary fields. For review submission it validates the HTTP input, requires an `Authorization` header, forwards that value to Core, maps the response, and translates known Core errors.

| BFF requirement | REST contract | Core operation | BFF behavior and evidence |
| --- | --- | --- | --- |
| **BFF-C03-001 — Read a game detail by slug.** | `GET /api/v1/games/{slug}` (`getGameDetail`) | `Query.productBySlug(slug)` | The BFF maps returned product attributes, quantity, `review_summary`, and `approved_reviews` into the REST response. It maps Core's `PRODUCT_NOT_FOUND` to HTTP 404 and other upstream GraphQL failures to 502. See [OpenAPI](../openapi.yaml), [detail controller](../../src/controllers/product_detail_controller.py), [product DTO](../../src/dtos/products.py), [proxy](../../src/proxy.py), and [product tests](../../tests/test_products.py). |
| **BFF-C03-002 — Accept review input for a slug.** | `POST /api/v1/games/{slug}/reviews` (`createGameReview`) | `Mutation.createReview(input: CreateReviewInput!)` | The BFF validates integer rating 1–5 (excluding booleans) and a nonblank body up to 2,000 characters, trims the body, requires an Authorization header, and forwards the header value to Core with the slug, rating, and body. A successful Core result is serialized with HTTP 201. See [review controller](../../src/controllers/reviews_controller.py), [review DTOs](../../src/dtos/products.py), and [review proxy](../../src/proxy.py). |
| **BFF-C03-003 — Translate review outcomes.** | `POST /api/v1/games/{slug}/reviews` (`createGameReview`) | `Mutation.createReview(...)` | Missing authorization returns 401; known Core codes map to HTTP 401 (`UNAUTHENTICATED`), 404 (`PRODUCT_NOT_FOUND`), 409 (`REVIEW_ALREADY_EXISTS`), or 400 (rating/body validation codes). Unexpected upstream failures return 502 with a generic message. See [review controller](../../src/controllers/reviews_controller.py) and [review tests](../../tests/test_reviews.py). |

## BFF boundary and limitations

- The BFF forwards the buyer's Authorization header value; it does not validate the token or independently decide whether a review is authorized. Core handles authentication and review-domain rules.
- Approved-review filtering and summary calculation are returned by Core through `productBySlug`; the BFF maps these fields and does not calculate moderation state or averages.
- BFF test coverage is limited for review creation: [the existing review test](../../tests/test_reviews.py) verifies generic upstream-error translation, not a successful review response or every enumerated status mapping. The detail response mapping is covered separately in [product tests](../../tests/test_products.py).
- Moderation tools and review display states are not BFF REST responsibilities evidenced by this API.

## Verification evidence

- [Canonical end-to-end behavior](../../../specs/003-product-detail-reviews-as-built/spec.md)
- [BFF OpenAPI contract](../openapi.yaml)
- [Core GraphQL schema](../../../bgg-shop-core/specs/schema.graphql)
- [Detail and review controllers](../../src/controllers/product_detail_controller.py), [review controller](../../src/controllers/reviews_controller.py)
- [Product/review DTOs](../../src/dtos/products.py), [Core proxy](../../src/proxy.py)
- [BFF product tests](../../tests/test_products.py), [BFF review tests](../../tests/test_reviews.py)

## BFF scope exclusions

The BFF does not render the detail screen or review form, manage buyer navigation, approve or moderate submissions, or implement the review domain rules owned by Core.
