# Tasks (BFF): CU-A02 — Sales Metrics & Reports

Plan and rules: `../../specs/010-sales-metrics-reports/plan.md`. Global ledger: `../../specs/010-sales-metrics-reports/tasks.md`.
Branch: `010-sales-metrics-reports`. Local validation only.

## Contract (blocking)

- [x] X-2 Add `GET /api/v1/admin/sales-metrics` to `specs/openapi.yaml` with optional `from`/`to`, repeated `category`/`product_id`, responses 200/400/401/403, `Cache-Control: no-store`, planned status, and the business rules from X-1.
- [x] X-3 Add `GET /api/v1/admin/sales-metrics/categories` to the OpenAPI with distinct stored categories, 200/401/403/502 responses, `Cache-Control: no-store`, and planned status.
- [x] X-4 Validate OpenAPI and Core SDL structure and run `scripts/run_contracts.sh`; structural assertions passed, while unrelated BFF service tests failed (see global Evidence Ledger).
- [x] X-5 Document paired `from`/`to` semantics in OpenAPI and the plan: callers provide both bounds or omit both; a one-sided range returns `INVALID` identifying the missing bound in `field`; omitting both defaults to the last 30 days. OpenAPI parse and paired-bound assertions passed; see the global Evidence Ledger.

## Implementation

- [ ] B-1 Write failing tests in `tests/test_admin_sales_metrics.py`: 401, 403, param validation (missing timezone, one-sided `from`/`to`, `from >= to`, >366 days, non-integer `product_id`), forwarding of repeated filters, `Cache-Control: no-store`, and negative tests proving no leakage of upstream exceptions, traces, internal URLs or credentials. (after X-5)
- [ ] B-2 Add the proxy call in `src/proxy.py` and service in `src/services.py`, following `list_admin_audit`.
- [ ] B-3 Add `src/controllers/admin_sales_controller.py` with validation and error mapping; register it with the other admin controllers. Make B-1 pass.
- [ ] B-4 Add the categories endpoint with tests. (after X-3)
- [ ] B-5 Update `README.md` with endpoints, filters and date semantics.
- [ ] B-6 Run BFF and contract tests; record results in the global ledger.
