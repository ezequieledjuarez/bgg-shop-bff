# Tasks: Admin Navigation and Discoverability — BFF

**Master backlog**: [orchestrator tasks](../../../specs/014-admin-navigation/tasks.md)<br>
**Status**: BFF canonical contract, endpoint tests, and implementation complete. The dependent Frontend work and scoped isolated service-path verification are also complete; see the [master evidence ledger](../../../specs/014-admin-navigation/quickstart.md).<br>
**Scope**: Local environments only.

This service document contains only BFF-owned tasks. IDs, statuses, and dependencies match the master backlog. The BFF uses Flask/Python and `specs/openapi.yaml` as its canonical REST contract. All public errors must be sanitized and negatively tested for upstream detail leakage.

## BFF-owned tasks

- [x] **T002 [BFF] [DONE — investigation only]** Confirm the current role projection and existing Core identity-query pattern. **Evidence**: `specs/openapi.yaml:3764-3785` defines `AuthUser` without staff/superuser flags; `src/proxy.py:1175-1218` contains the existing `me` role-check pattern. T005 later approved the separate minimal BFF projection; T006/T008 subsequently promoted and implemented it. **Trace**: FR-001–FR-002, FR-008, FR-011–FR-012; US1, US4.
- [x] **T006 [BFF] [DONE — canonical contract]** Promoted the T005-approved current-user capability design to canonical `specs/openapi.yaml`. **Evidence**: Local PyYAML parse and assertions passed for operation ID, bearer-only security, 200/401/502 responses, `no-store` headers on every response, and the exact two-boolean role schema. Core SDL remains unchanged. **Depends on**: T005. **Trace**: FR-001–FR-002, FR-008, FR-011–FR-012; US1, US4.
- [x] **T007 [BFF] [DONE — tests, RED observed]** Added deterministic route/proxy tests for staff, Superadmin with `is_staff=false`, buyer, bearer validation, inactive/null/unauthenticated Core identities, operation-key-only requests, malformed Core payloads, role revocation, sanitized failures, proxy headers/query, and non-cacheable responses. **Evidence**: RED before implementation: 27 new tests failed while 17 existing auth tests passed; the failures were the unimplemented route. GREEN: all 44 current-user/auth tests passed. **Depends on**: T006, T002. **Trace**: FR-001–FR-002, FR-008, FR-011–FR-012; US1, US4.
- [x] **T008 [BFF] [DONE — implementation]** Implemented the endpoint using Core `Query.me` and current active/staff/superuser state, strict bearer parsing, sanitized 401/502 errors, operation-key middleware bypass, and no-store headers including error responses. Existing admin authorization remains unchanged. **Evidence**: The independent focused auth and operation-key rerun passed 89 tests; the exact command and observed warnings are recorded in the verification ledger. **Depends on**: T007, T006. **Trace**: FR-001–FR-002, FR-008, FR-011–FR-012; US1, US4.

## BFF execution gates and verification

- T005's approval remains historical design evidence. T006 is now promoted and locally validated in canonical `specs/openapi.yaml`; the planning draft at `../../../specs/014-admin-navigation/contracts/admin-session.openapi.yaml` remains non-canonical.
- Tests must include negative assertions that public errors omit upstream body/details, exceptions, traces, internal URLs, and credentials.
- No staging, production, remote validation, or non-local service access is in scope.

| Executed command/check | Observed result |
|---|---|
| `.venv/bin/python -c 'import yaml; ...'` (PyYAML load and focused schema assertions) | PASS: canonical OpenAPI parses and the operation, bearer security, 200/401/502 responses, `no-store` headers, and exact role fields match the approved design. |
| Local RED run of `tests/test_auth_current_user.py` and `tests/test_auth.py` before implementation | 27 new endpoint tests failed; all 17 existing auth tests passed. |
| `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c 'import app, pytest; app._append_incoming_log = lambda entry: None; raise SystemExit(pytest.main(["tests/test_auth_current_user.py", "tests/test_auth.py", "tests/test_opkey_middleware.py", "tests/test_opkey_admin.py", "-q", "--tb=no", "--basetemp=.pytest-local-spec014"]))'` | PASS: 89 tests. The wrapper suppresses the existing `/tmp` request-file logger and confines pytest temporary data to the repository. |

## Key Learnings

1. BFF login users currently include active status but omit staff and Superadmin flags.
2. Existing BFF proxy code already queries Core identity roles for server-side admin checks.
