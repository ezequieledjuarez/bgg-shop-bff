# Tasks (BFF): CU-A02 — Sales Metrics & Reports

Plan and rules: `../../specs/010-sales-metrics-reports/plan.md`. Global ledger: `../../specs/010-sales-metrics-reports/tasks.md`.
Branch: `010-sales-metrics-reports`. Local validation only.

## Contract (blocking)

- [ ] X-2 Add `GET /api/v1/admin/sales-metrics` to `specs/openapi.yaml`: params `from`, `to`, repeated `category`, repeated `product_id`; responses 200/400/401/403; `Cache-Control: no-store`; `x-implementation-status: planned`. Document date semantics (revenue/`ordersCount` by `paid_at`, status counts by `created_at`), gross revenue from line subtotals, dispatch rules, 366-day maximum and 30-day default.
- [ ] X-3 Add `GET /api/v1/admin/sales-metrics/categories` to the OpenAPI.
- [ ] X-4 Run `scripts/run_contracts.sh` and confirm OpenAPI and Core SDL are consistent. (after X-1..X-3, Core side included)

## Implementation

- [ ] B-1 Write failing tests in `tests/test_admin_sales_metrics.py`: 401, 403, param validation (missing timezone, `from >= to`, >366 days, non-integer `product_id`), forwarding of repeated filters, `Cache-Control: no-store`, and negative tests proving no leakage of upstream exceptions, traces, internal URLs or credentials. (after X-4)
- [ ] B-2 Add the proxy call in `src/proxy.py` and service in `src/services.py`, following `list_admin_audit`.
- [ ] B-3 Add `src/controllers/admin_sales_controller.py` with validation and error mapping; register it with the other admin controllers. Make B-1 pass.
- [ ] B-4 Add the categories endpoint with tests. (after X-3)
- [ ] B-5 Update `README.md` with endpoints, filters and date semantics.
- [ ] B-6 Run BFF and contract tests; record results in the global ledger.
