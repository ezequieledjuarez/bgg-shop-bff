# Tasks (BFF): CU-A02 — Sales Metrics & Reports

Plan and rules: `../../../specs/010-sales-metrics-reports/plan.md`. Global ledger: `../../../specs/010-sales-metrics-reports/tasks.md`.
Branch: `010-sales-metrics-reports`. Local validation only.

## Contract (blocking)

- [x] X-2 Add `GET /api/v1/admin/sales-metrics` to `specs/openapi.yaml` with optional `from`/`to`, repeated `category`/`product_id`, responses 200/400/401/403, `Cache-Control: no-store`, planned status, and the business rules from X-1.
- [x] X-3 Add `GET /api/v1/admin/sales-metrics/categories` to the OpenAPI with distinct stored categories, 200/401/403/502 responses, `Cache-Control: no-store`, and planned status.
- [x] X-4 Validate OpenAPI and Core SDL structure and run `scripts/run_contracts.sh`; structural assertions passed, while unrelated BFF service tests failed (see global Evidence Ledger).
- [x] X-5 Document paired `from`/`to` semantics in OpenAPI and the plan: callers provide both bounds or omit both; a one-sided range returns `INVALID` identifying the missing bound in `field`; omitting both defaults to the last 30 days. OpenAPI parse and paired-bound assertions passed; see the global Evidence Ledger.

## Implementation

- [x] B-1 Write failing tests in `tests/test_admin_sales_metrics.py`: auth for both endpoints, staff/superuser access, date and filter validation, repeated-filter forwarding, `Cache-Control: no-store`, and negative tests for upstream-detail redaction. Expected RED observed after successful collection. (after X-5)
- [x] B-2 Add proxy calls in `src/proxy.py` and services in `src/services.py`, following `list_admin_audit`.
- [x] B-3 Add `src/controllers/admin_sales_controller.py` with validation and error mapping; register both GET routes in `app.py`. B-1 and added validation cases pass.
- [x] B-4 Add the categories endpoint with tests; implemented and covered within B-2/B-3 and B-1. (after X-3)
- [x] B-5 Update `README.md` with endpoint paths, filters, date semantics, access, cache behavior, and error responses.
- [x] B-6 Run BFF and contract tests; record results in the global ledger.

## Evidence Ledger

| Task | Check run | Result | Date |
|------|-----------|--------|------|
| B-1 | `pytest -q tests/test_admin_sales_metrics.py` from BFF | COLLECTION ERROR: `ModuleNotFoundError: No module named 'app'`; the console entrypoint did not add the BFF root to the import path. | 2026-11-05 |
| B-1 | `PYTHONPATH=. .venv/bin/pytest -q tests/test_admin_sales_metrics.py` | COLLECTION ERROR: the BFF virtual environment lacks `redis`, imported by `app.py`. No packages were installed. | 2026-11-05 |
| B-1 | `PYTHONPATH=. pytest -q tests/test_admin_sales_metrics.py` | EXPECTED RED: collection succeeded; 20 failed, 20 warnings. All responses were 405 from the generic OPTIONS-only catch-all because the metrics/category GET routes are not registered. All GraphQL requests were mocked; no database or network access. | 2026-11-05 |
| B-1 | Work-unit commits | BFF `6f40f5ef54b0e480b6520841ad329f214e702e34`; orchestrator `ecedb1752c11c12e7aee331fd0210c721c22e946` | 2026-11-05 |
| B-2/B-3 | Initial `PYTHONPATH=. pytest -q tests/test_admin_sales_metrics.py` | FAIL: 1 failed, 26 passed; a timezone-naive `from` returned the missing `to` field. Validation was reordered to report the malformed bound first. | 2026-11-05 |
| B-2/B-3 | `PYTHONPATH=. pytest -q tests/test_admin_sales_metrics.py` | PASS: 27 passed, 27 existing `datetime.utcnow()` deprecation warnings. GraphQL calls were mocked; no database or network calls. | 2026-11-05 |
| B-2/B-3 | `PYTHONPATH=. pytest -q tests/test_admin.py` | PASS: 25 passed, 17 deprecation warnings. | 2026-11-05 |
| B-2/B-3 | `git diff --check` from BFF | PASS. | 2026-11-05 |
| B-2..B-4 | Parent combined run `PYTHONPATH=. pytest -q --tb=short tests/test_admin_sales_metrics.py tests/test_admin.py` | PASS: 52 passed, 44 existing `datetime.utcnow()` deprecation warnings. Core calls mocked; no database or network calls. | 2026-11-05 |
| B-5 | README structural review | PASS: both endpoints, access, filters, paired date bounds/default/max range, response shape, `no-store`, and error status codes documented. | 2026-11-05 |
| B-6 | `PYTHONPATH=. pytest -q --tb=short` | PARTIAL: 597 passed, 12 failed, 431 warnings in 13.69s. Failures are existing unrelated service tests (`op_key` undefined; mocked `requests.post` rejects `allow_redirects`); metrics tests passed. | 2026-11-05 |
| B-6 | `bash scripts/run_contracts.sh` | PARTIAL: 9 failed, 7 passed; existing service-contract mock/signature failures, unrelated to metrics routes. | 2026-11-05 |
| B-6 | PyYAML/OpenAPI paths and graphql-core/SDL fields | PASS: both admin REST routes and both Core query fields parsed and asserted. | 2026-11-05 |
