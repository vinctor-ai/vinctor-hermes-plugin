# Operator Preflight

Use this checklist before dogfooding the Vinctor Hermes Plugin against real
Hermes workflows.

## 1. Confirm Plugin Loading

- Install the package in the same Python environment used by Hermes.
- Configure Hermes to load this plugin directory or package entry point.
- Confirm the runtime registers `pre_tool_call` from
  `vinctor_hermes_plugin.plugin:register`.
- Run the local registration smoke:

```bash
PYTHONPATH=src python scripts/plugin_load_smoke.py
```

Expected output:

```text
registered pre_tool_call
```

- Confirm no model-facing output includes `grant_ref`, raw tool arguments,
  `audit_event_id`, or matched scope.

## 2. Configure Vinctor Access

Required environment:

```bash
VINCTOR_ENDPOINT=http://127.0.0.1:8080
VINCTOR_AGENT_KEY=agent-key
VINCTOR_GRANT_REF=grant-ref
```

Optional service context:

```bash
VINCTOR_BOUNDARY_ID=boundary-id
```

Optional dogfood hardening:

```bash
VINCTOR_HERMES_UNMAPPED_POLICY=block
VINCTOR_HERMES_DECISION_LOG=/tmp/vinctor-hermes-decisions.jsonl
VINCTOR_HERMES_COVERAGE_LOG=/tmp/vinctor-hermes-coverage.jsonl
# Use only with non-sensitive fixture arguments:
# VINCTOR_HERMES_COVERAGE_LOG_INCLUDE_ARGS=1
```

Keep `VINCTOR_HERMES_ALLOW_MCP_REGISTRY_RUNTIME_RULES` unset unless you are
intentionally testing runtime-generated MCP mappings. The safer workflow is:

1. Export the Hermes MCP tool registry.
2. Run `vinctor-hermes-plugin draft-mcp-config <registry> --json`.
3. Review and materialize the generated rules in operator config.
4. Point `VINCTOR_HERMES_PLUGIN_CONFIG` at that reviewed config.

## 3. Validate Local Mapping

Validate config:

```bash
vinctor-hermes-plugin validate .vinctor/hermes-plugin.json --json
```

Explain one known mapped event:

```bash
printf '%s' '{"tool_name":"terminal","args":{"command":"npm test"}}' > /tmp/hermes-event.json
vinctor-hermes-plugin explain /tmp/hermes-event.json --json
```

Expected result:

- `status` is `mapped`
- `action` is one of the six v1 actions
- `resource` is explicit and contains no wildcard

## 4. Verify Service Behavior

Run one mapped Hermes workflow for each outcome:

| Outcome | Expected behavior |
| --- | --- |
| permit | Hermes continues execution. |
| deny | Hermes receives a block directive before execution. |
| service unavailable, timeout, malformed 200, or missing auth | Hermes receives a fail-closed block directive. |
| unmapped with default policy | Plugin returns no directive and Hermes handles its own guard path. |
| unmapped with `VINCTOR_HERMES_UNMAPPED_POLICY=block` | Hermes receives a block directive before execution. |

For mapped calls, confirm the service received the strict v1 body:

```json
{
  "grant_ref": "...",
  "action": "...",
  "resource": "..."
}
```

If `VINCTOR_BOUNDARY_ID` is set, also confirm the service received
`X-Vinctor-Boundary-Id` so audit rows can identify the configured Hermes runtime
boundary.

The request must include `X-Agent-Key`. The plugin must not include workspace
tokens, raw tool input, or extra service contract fields.

## 5. Measure Runtime Boundary Coverage

Runtime coverage is measured separately from local mapping coverage. During a
controlled Hermes run, keep `VINCTOR_HERMES_COVERAGE_LOG` enabled and exercise
the tool families listed in
`docs/validation/coverage-matrix-hermes-unmeasured-2026-06-11.md`.

For every tool call you intentionally trigger:

- if a coverage row appears before execution, record `observed`
- if the tool executes and no coverage row appears, record `bypassed`
- if the probe was not run, leave it `unmeasured`

Do not claim boundary coverage for a tool family until the measured matrix for a
pinned Hermes runtime version shows `observed`.

## 6. Confirm Audit Correlation

After each mapped call:

- Confirm the Vinctor service produced an audit event.
- If `VINCTOR_HERMES_DECISION_LOG` is set, confirm the JSONL log includes
  `decision`, `action`, `resource`, and `audit_event_id`.
- If `VINCTOR_HERMES_COVERAGE_LOG` is set, confirm the JSONL log includes the
  observed `tool_name`, top-level `arg_keys`, mapping status, and block result
  without raw argument values by default. If exact fixture args are needed for a
  controlled coverage run, set `VINCTOR_HERMES_COVERAGE_LOG_INCLUDE_ARGS=1` and
  use only non-sensitive fixture inputs.
- Confirm the Hermes/model-facing block message stays generic and does not
  disclose the local decision metadata.
