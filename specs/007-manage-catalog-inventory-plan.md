# Plan: CU-A01 — BFF Implementation

Owner: bgg-shop-bff
Reference spec: ../../specs/007-manage-catalog-inventory/spec.md

## Objective
Actuar como capa de orquestación entre Frontend y Core, validando, mapeando errores y proporcionando endpoints amigables para la UI administrativa.

## Steps
1. Finalize JSON schemas with Core (X-1)
2. Implement admin endpoints with payload validation
3. Map Core error codes to friendly messages
4. Add caching + invalidation via Core events
5. Implement contract tests with Core

## Acceptance Criteria
- AC-BFF-1..AC-BFF-4 from BFF spec are met.
