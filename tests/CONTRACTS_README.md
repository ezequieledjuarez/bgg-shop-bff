Contract Tests (mocked GraphQL)

Purpose
- Provide lightweight contract/integration tests that assert the GraphQL request shapes produced by the BFF service layer and the BFF mapping of GraphQL responses.

Location
- Tests live under `bgg-shop-bff/tests/` and use the `test_services_*` filename prefix.

How they work
- Tests patch `src.proxy.requests.post` to intercept GraphQL requests and return deterministic GraphQL-shaped JSON objects.
- They validate: GraphQL `query` text (or mutation name), `variables` content, and BFF mapping behavior (including `userErrors` handling).

Run all contract tests

```bash
# From workspace root
cd bgg-shop-bff
PYTHONPATH=. pytest tests/test_services_* -q
```

Run a single contract test file

```bash
cd bgg-shop-bff
PYTHONPATH=. pytest tests/test_services_cart_product_contract.py -q
```

Adding new contract tests
- Create tests named `tests/test_services_*.py`.
- Patch `src.proxy.requests.post` and return a simple object implementing `json()` and `raise_for_status()`.
- Keep responses small but include all fields the mapping helpers expect (e.g. product fields used by `_map_wishlist_product`).

Design notes
- These tests intentionally avoid a live GraphQL server and focus on request/response translation.
- For full end-to-end verification, consider adding an optional integration suite that runs against a test GraphQL endpoint.
