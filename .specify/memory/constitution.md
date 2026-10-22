# BGG Shop BFF Constitution

## Scope and precedence

This constitution governs implementation in `bgg-shop-bff`. The root `.specify/memory/constitution.md` governs shared product and cross-service behavior; this file governs the BFF's local implementation and cannot redefine that behavior. Existing BFF behavior remains the compatibility baseline. No constitution automatically authorizes a retroactive behavior or contract change.

## Principles

### 1. Own the REST boundary

`specs/openapi.yaml` is the authoritative BFF REST contract. Keep routes, request and response shapes, and public error behavior aligned with it. An explicitly approved contract change must be traceable to affected specifications, implementation, tests, and downstream consumers, including Frontend-generated types.

### 2. Adapt services without taking over domain ownership

Keep this service focused on the REST boundary: validate and translate HTTP inputs, orchestrate calls to Core, map GraphQL results to REST representations, and translate failures into the documented public responses. Do not silently redefine Core-owned domain rules or make the Frontend depend on Core GraphQL.

### 3. Protect the public boundary

Validate untrusted requests and enforce the authentication requirements of each operation. Public responses must not expose upstream exceptions, traces, internal URLs, credentials, or other implementation details. Keep service credentials in server-side configuration, never in responses.

### 4. Verify BFF changes

For each approved change, trace the requirement through the applicable `specs/*/spec.md`, `specs/openapi.yaml`, implementation, relevant tests under `tests/`, and documentation. Run the applicable checks and record only observed outcomes; a completed task is not evidence that tests passed.
