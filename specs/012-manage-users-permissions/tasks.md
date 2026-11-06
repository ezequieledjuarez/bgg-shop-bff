# Tasks: Manage Users and Permissions (CU-A04) — BFF

**Master backlog**: [orchestrator tasks](../../../specs/012-manage-users-permissions/tasks.md)
**Branch**: `012-manage-users-permissions`
**Status**: T005, T009, T014–T016 are complete. The independently verified BFF privilege routes use Core authorization directly.
**Scope**: Local environments and disposable test data only.

This document contains only BFF-owned tasks. IDs, statuses, and dependencies are global and match the master backlog. Cross-repository dependencies refer to master task IDs. Local focused and broader BFF authorization checks passed.

## BFF-owned tasks

- [x] **T005 [BFF] [DONE — investigation only]** Inventory BFF authentication/context propagation, operation-key-only paths, existing user/personnel routes, flag representations, error sanitization, and existing session/token behavior. **Evidence**: existing admin operations allow staff or superuser and operation-key access exists for operational workflows; no user-management routes existed. No contract or behavior was changed during investigation. Trace: FR-001–FR-009, FR-011; US1–US3.
- [x] **T009 [BFF] [DONE — approved OpenAPI contract]** Following T007, draft and approve Flask REST contract changes in canonical `specs/openapi.yaml`. **Evidence**: GET `/api/v1/admin/users` and PATCH `/api/v1/admin/users/{user_id}/privileges` are specified with safe user projection, current bearer Superadmin authority, sanitized error/status mapping, pagination/search, and independent flag updates; structural validation and T010 independent cross-contract validation passed. Trace: FR-001–FR-006, FR-008–FR-009, FR-011; US1–US3.
- [x] **T014 [BFF] [DONE — tests authored, expected RED observed]** After T007 and T010, author deterministic BFF tests for user listing and privilege changes, identity propagation, independent flags, inactive and operation-key-only contexts, last-superuser denials, and error sanitization. **Evidence**: `PYTHONPATH=. pytest tests/test_admin_users.py -q` returned 11 failed; requests reached expected status assertions and got 405 because user-admin routes did not exist. The BFF virtualenv could not collect due missing `redis`; system pytest was used. Trace: FR-001–FR-006, FR-008–FR-009, FR-011; US1–US3.
- [x] **T015 [BFF] [DONE — implementation and independent review passed]** Implement the approved OpenAPI-backed BFF operations and Core delegation. The personnel routes send bearer credentials directly to Core; Core's structured `UNAUTHENTICATED` and `FORBIDDEN` errors map to HTTP 401 and 403. Operation-key forwarding remains disabled for these endpoints, independent flag updates and safe projection are preserved, and public errors are sanitized. **Evidence**: independent review found no significant issue; focused and broader BFF suites passed (15 and 83 tests respectively); `py_compile` and `git diff --check` passed. Trace: FR-001–FR-006, FR-008–FR-009, FR-011; US1–US3.
- [x] **T016 [BFF] [DONE — independent regression verification]** Run and record applicable BFF checks for active Superadmin with `is_staff=false`, staff-only and other unauthorized negatives, independent flag updates, last-superuser denial, and error non-disclosure. **Evidence**: independent `PYTHONPATH=. pytest tests/test_admin_users.py tests/test_admin.py tests/test_admin_error_mapping.py tests/test_opkey_admin.py -q` returned 83 passed; `python -m py_compile src/auth.py src/controllers/admin_users_controller.py` and `git diff --check` passed. 71 existing datetime deprecation warnings were emitted. Trace: SC-001–SC-007.

## Execution gates

- T005, T009 and T014–T016 are complete. T015's direct-Core authorization flow handles actual inactive caller errors using Core structured codes; focused and broader BFF checks passed locally.
- T009 updates BFF's canonical OpenAPI contract. T010 (Orchestrator) must validate it together with the Core SDL before any behavior implementation.
- Apply test-first sequencing where a deterministic expected result and runnable BFF test exist. The plan must name exact test files/selectors and commands; use existing BFF pytest tooling.
- BFF and Core must both enforce authenticated, active `is_superuser=true`. Staff-only, inactive, unauthenticated, and operation-key-only callers cannot perform privilege administration; Frontend controls are not a security boundary.
- Public errors must not expose upstream details, exceptions, traces, internal URLs, credentials, or secrets. Use disposable local data only.
