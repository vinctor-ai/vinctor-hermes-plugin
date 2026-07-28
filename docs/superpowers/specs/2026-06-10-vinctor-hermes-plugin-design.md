# Vinctor Hermes Plugin Design

## Status

Approved direction. Boundary Preview.

## Product Contract

Build `vinctor-hermes-plugin`, a Hermes plugin that registers a `pre_tool_call`
authorization boundary for configured tool calls.

This repository is independent of Hermes and Nous Research. It must not imply
vendor endorsement or special runtime status. It is a Hermes plugin that applies
Vinctor runtime authorization to mediated tool calls routed through the plugin
boundary.

## Runtime Boundary

Hermes exposes plugins through `plugin.yaml` / `register(ctx)` directory plugins
and through the `hermes_agent.plugins` entry point group. Hermes also exposes
lifecycle hooks including `pre_tool_call` and middleware including
`tool_execution`.

The v0.1.0 primary boundary is `pre_tool_call`, because it has a direct blocking
contract before execution. `tool_execution` middleware is deferred as a secondary
path.

Flow:

1. Hermes proposes a tool call.
2. The plugin receives `pre_tool_call`.
3. The plugin maps `(tool_name, args, context)` to `(action, resource)`.
4. The plugin calls `POST /v1/enforce` with header `X-Agent-Key`.
5. The request body is exactly `{grant_ref, action, resource}`.
6. Permit returns no block directive.
7. Deny or unresolved authorization returns a block directive.
8. Unmapped calls return no directive and defer to Hermes.

## Security Invariants

Model-facing output must not include:

- `grant_ref`
- raw tool arguments
- raw tool input
- `audit_event_id`
- matched scope

All classified calls fail closed when authorization cannot be resolved.

## Initial Taxonomy

- `write:repo/<path-or-branch>`
- `write:repo/branch/<branch>`
- `execute:ci/test`
- `execute:shell/<command-family>`
- `execute:deploy/<env>`
- `execute:release/<target>`
- `read:memory/<scope>`
- `read:session/search`
- `send:<resource>` for later outbound/tool gateway actions

Deployment and release use the existing Vinctor convention:
`execute:deploy/<env>` and `execute:release/<target>`.

## Components

- `plugin.py` registers the Hermes hook.
- `boundary.py` owns the `pre_tool_call` callback and fail-closed behavior.
- `mapping.py` maps Hermes-style tool calls to Vinctor action/resource pairs.
- `config.py` validates optional operator config.
- `enforce.py` calls the Vinctor v1 service.
- `cli.py` provides offline `validate` and `explain`.
- `scripts/service_backed_e2e.py` proves permit, deny, fail-closed, and audit
  behavior against a local contract service.

## Test Strategy

Use Python `unittest` with no runtime dependency on a full Hermes install:

- fake Hermes plugin context verifies `register(ctx)` behavior
- mapping tests verify high-impact action/resource taxonomy
- boundary tests verify permit, deny, missing auth, invalid config, and unmapped
  behavior
- non-disclosure tests ratchet model-facing output
- service-backed E2E verifies HTTP contract behavior and audit records

## Non-Goals

- no sandboxing
- no raw interception
- no approval workflow
- no provider integration
- no prompt/content safety
- no hosted service
- no dashboard/UI
- no grant issuance
- no public SDK middleware API
