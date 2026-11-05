# Tasks (BFF): CU-A02 — Sales Metrics & Reports

Plan and rules: `../../specs/010-sales-metrics-reports/plan.md`. Global ledger: `../../specs/010-sales-metrics-reports/tasks.md`.
Branch: `010-sales-metrics-reports`. Local validation only.

## Contract (blocking)

- [x] X-2 Add `GET /api/v1/admin/sales-metrics` to `specs/openapi.yaml` with optional `from`/`to`, repeated `category`/`product_id`, responses 200/400/401/403, `Cache-Control: no-store`, planned status, and the business rules from X-1.
- [x] X-3 Add `GET /api/v1/admin/sales-metrics/categories` to the OpenAPI with distinct stored categories, 200/401/403/502 responses, `Cache-Control: no-store`, and planned status.
- [x] X-4 Validate OpenAPI and Core SDL structure and run `scripts/run_contracts.sh`; structural assertions passed, while unrelated BFF service tests failed (see global Evidence Ledger).
- [x] X-5 Document paired `from`/`to` semantics in OpenAPI and the plan: callers provide both bounds or omit both; a one-sided range returns `INVALID` identifying the missing bound in `field`; omitting both defaults to the last 30 days. OpenAPI parse and paired-bound assertions passed; see the global Evidence Ledger.

## Implementation

- [x] B-1 Write failing tests in `tests/test_admin_sales_metrics.py`: auth for both endpoints, staff/superuser access, date and filter validation, repeated-filter forwarding, `Cache-Control: no-store`, and negative tests for upstream-detail redaction. Expected RED observed after successful collection. (after X-5)
- [ ] B-2 Add the proxy call in `src/proxy.py` and service in `src/services.py`, following `list_admin_audit`.
- [ ] B-3 Add `src/controllers/admin_sales_controller.py` with validation and error mapping; register it with the other admin controllers. Make B-1 pass.
- [ ] B-4 Add the categories endpoint with tests. (after X-3)
- [ ] B-5 Update `README.md` with endpoints, filters and date semantics.
- [ ] B-6 Run BFF and contract tests; record results in the global ledger.

## Evidence Ledger

| Task | Check run | Result | Date |
|------|-----------|--------|------|
| B-1 | `pytest -q tests/test_admin_sales_metrics.py` from BFF | COLLECTION ERROR: `ModuleNotFoundError: No module named 'app'`; the console entrypoint did not add the BFF root to the import path. | 2026-11-05 |
| B-1 | `PYTHONPATH=. .venv/bin/pytest -q tests/test_admin_sales_metrics.py` | COLLECTION ERROR: the BFF virtual environment lacks `redis`, imported by `app.py`. No packages were installed. | 2026-11-05 |
| B-1 | `PYTHONPATH=. pytest -q tests/test_admin_sales_metrics.py` | EXPECTED RED: collection succeeded; 20 failed, 20 warnings. All responses were 405 from the generic OPTIONS-only catch-all because the metrics/category GET routes are not registered. All GraphQL requests were mocked; no database or network access. | 2026-11-05 |
