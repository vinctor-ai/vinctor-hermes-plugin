# Vinctor Hermes Plugin MCP Registry Plan

Date: 2026-06-10
Status: Implemented

## Task 1: Red Tests

Add failing tests for:

- MCP registry discovery from `{ "tools": [...] }` and top-level arrays.
- Built-in MCP tools reported separately.
- Unknown MCP tools with inferred action verbs producing exact config rules.
- Uninferable tools skipped.
- Runtime config appending generated MCP rules after explicit rules.
- `draft-mcp-config` CLI output.
- `explain` using `VINCTOR_HERMES_MCP_REGISTRY`.

## Task 2: Discovery Module

Add `mcp_discovery.py` with:

- registry parser
- MCP name parser reuse
- conservative action inference
- `DiscoveryResult` payload renderer

## Task 3: Runtime Config Merge

Add `load_runtime_config(config_path, mcp_registry_path)`.

Boundary and CLI `explain` use this runtime config loader.

## Task 4: CLI

Add:

```bash
vinctor-hermes-plugin draft-mcp-config <registry> --json
vinctor-hermes-plugin explain <event> --mcp-registry <registry> --json
```

## Task 5: Docs and Verification

Update README, configuration, roadmap, adoption readiness, friction log, and E2E
validation notes.

Run the full test suite, compile check, CLI smoke, claim-safety scan,
service-backed E2E, and `git diff --check`.
