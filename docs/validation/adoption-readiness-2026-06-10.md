# Adoption Readiness Validation

Date: 2026-06-10
Status: v0.2 local validation artifact

## Goal

Check whether an operator can understand and evaluate the Hermes plugin from the
repository artifacts without reading source first.

## Walkthrough

1. Read `README.md` to identify the runtime flow, required environment
   variables, and non-goals.
2. Use `docs/action-resource-taxonomy.md` to determine whether a Hermes tool
   call is built-in or needs operator config.
3. Use `docs/configuration.md` to add a project-specific mapping.
4. Use `vinctor-hermes-plugin validate <config> --json` to confirm config
   validity and rule count.
5. Use `vinctor-hermes-plugin explain <event> --json` to confirm the local
   `(action, resource)` pair without calling Vinctor.
6. Use `docs/troubleshooting.md` to interpret block codes.
7. Use `docs/validation/service-backed-e2e-2026-06-10.md` to understand the
   permit, deny, fail-closed, and audit proof.

## Outcome

The docs now cover the operator path from offline mapping evaluation to
service-backed validation. Dynamic MCP servers can be handled by exporting a
Hermes MCP tool registry, generating config drafts with `draft-mcp-config`, and
reviewing the exact-match rules before runtime use.

## Friction Items

- Runtime MCP registry drafting is implemented, but live MCP server polling is
  not.
- Browser CDP is classified as broad `execute:browser/cdp`; it does not inspect
  method-level intent yet.
- The service-backed E2E uses a local contract service rather than a deployed
  Vinctor service.
- `ruff` is optional in this repository because the local sandbox did not have
  it installed during the initial iteration.
