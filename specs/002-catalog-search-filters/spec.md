# BFF Functional Specification: Catalog Search and Filters (As-Built)

**Input**: CU-C02
**Status**: As-built / retrospective
**Scope**: The BFF REST interface and its forwarding/mapping of catalog requests. The complete buyer behavior, including local presentation and sorting, is in the [canonical CU-C02 specification](../../../specs/002-catalog-search-filters-as-built/spec.md).

## BFF responsibilities

The BFF offers a public, unauthenticated catalog-list operation. It accepts page and filter query parameters, validates them in the proxy boundary, maps supported criteria to Core GraphQL variables, and returns product and pagination fields in the REST shape.

| BFF requirement | REST contract | Core operation | BFF behavior and evidence |
| --- | --- | --- | --- |
| **BFF-C02-001 — List catalog products.** Return products with catalog attributes and page metadata without requiring an authorization header. | `GET /api/v1/products` (`listProducts`) | `Query.products(page, pageSize, search, yearPublished, minPlayers, maxPlayers, categoryId, priceMin, priceMax)` | REST names use `page_size`, `year_published`, `min_players`, `max_players`, `category_id`, `price_min`, and `price_max`; the proxy maps these to Core's camel-case GraphQL arguments. The DTO returns `items`, `page`, `page_size`, `total`, and `total_pages`. See [OpenAPI](../openapi.yaml), [product controller](../../src/controllers/products_controller.py), [query and response DTOs](../../src/dtos/products.py), [proxy](../../src/proxy.py), and [product tests](../../tests/test_products.py). |
| **BFF-C02-002 — Forward search and supported filters.** | `GET /api/v1/products` (`listProducts`) query parameters `search`, `year_published`, `min_players`, `max_players`, `category_id`, `price_min`, and `price_max` | `Query.products(...)` | The BFF forwards the query values to Core and returns Core's result page. It rejects invalid input and inverted player-count or price ranges with HTTP 400. Search matching and category semantics are supplied by Core, not reimplemented by the BFF. See [product proxy](../../src/proxy.py) and [query-forwarding and validation tests](../../tests/test_products.py). |
| **BFF-C02-003 — Preserve paging and distinguish upstream failure.** | `GET /api/v1/products` (`listProducts`) | `Query.products(...)` | The BFF accepts `page` and `page_size` and returns Core page metadata. Invalid request input returns 400; an upstream GraphQL failure returns 502 rather than a successful empty page. See [OpenAPI](../openapi.yaml), [product controller](../../src/controllers/products_controller.py), and [product tests](../../tests/test_products.py). |

## BFF boundary and limitations

- This BFF operation has no sort or “recommended” parameter. The locally displayed ordering described in the canonical specification is not a BFF behavior.
- The BFF exposes pagination but does not control which page the client requests or provide UI page navigation.
- A successful empty result is passed through as Core's result page; visual empty, loading, retry, and error states belong to the consuming client.
- The BFF transports the criteria but does not independently implement name/publisher matching or the category map. The Core query contract and implementation determine those semantics.

## Verification evidence

- [Canonical end-to-end behavior](../../../specs/002-catalog-search-filters-as-built/spec.md)
- [BFF OpenAPI contract](../openapi.yaml)
- [Core GraphQL schema](../../../bgg-shop-core/specs/schema.graphql)
- [Product controller](../../src/controllers/products_controller.py), [product proxy](../../src/proxy.py), [product DTOs](../../src/dtos/products.py)
- [BFF catalog and detail tests](../../tests/test_products.py)

## BFF scope exclusions

The BFF does not implement catalog rendering, filter controls, local result ordering, empty-state copy, or a relevance-ranking service.
