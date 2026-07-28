# Hermes Runtime Boundary Coverage Matrix

Date: 2026-06-11
Hermes runtime version: unmeasured
Plugin version: 0.3.3
Status: template only; no runtime coverage claims

## Summary

This matrix is intentionally unmeasured. The local workspace used for this
iteration does not contain an installed or runnable Hermes runtime. Local checks
found this plugin repository and Hermes-style prior-art examples, but no versioned
Hermes runtime capable of executing tool calls through `pre_tool_call`.

Because no versioned Hermes runtime was available, this document does not claim
that any Hermes tool family is covered by the runtime boundary. It records the
measurement plan, the matrix shape, and the exact rule for filling measured
cells later.

## Coverage Meanings

This repository now distinguishes two different kinds of coverage:

- Mapping coverage: `resolve_tool_call` can translate a tool event that already
  reached the plugin into `(action, resource)`.
- Runtime boundary coverage: a real Hermes runtime actually routes a tool call
  through this plugin's `pre_tool_call` hook before execution.

Mapping coverage is not evidence of runtime boundary coverage. Runtime coverage
requires direct observation from a pinned Hermes runtime.

## Reproducible Probe Harness

`scripts/coverage_harness.py` drives the tool families below through the plugin's
real `pre_tool_call` boundary and reports, per family, the mapping status, the
enforced `action:resource`, and the block decision. It uses an offline stub
enforce function, so it runs without a Vinctor service.

```bash
PYTHONPATH=src python scripts/coverage_harness.py --format markdown
PYTHONPATH=src python scripts/coverage_harness.py --enforce deny
PYTHONPATH=src python scripts/coverage_harness.py --unmapped-policy block
```

The harness measures MAPPING coverage only. Its default `synthetic` mode
synthesizes the `pre_tool_call` event, so every row reports
`runtime_traversal = unmeasured (synthetic)`. It does not and cannot prove that a
real Hermes runtime routes any family through `pre_tool_call`. Use it to populate
the mapping/enforce/block columns of a measured matrix and to cross-check the
runtime coverage-log rows; fill the `pre_tool_call traversal` column only from a
real runtime coverage log (see Runbook below).

See `scripts/README.md` for the full harness reference.

## Probe Harness

Set these variables in the Hermes process while running a controlled coverage
probe:

```bash
VINCTOR_HERMES_COVERAGE_LOG=/tmp/vinctor-hermes-coverage.jsonl
VINCTOR_HERMES_DECISION_LOG=/tmp/vinctor-hermes-decisions.jsonl
VINCTOR_HERMES_UNMAPPED_POLICY=block
```

`VINCTOR_HERMES_COVERAGE_LOG` records one JSON object for each observed
`pre_tool_call` entry. By default it records:

- `tool_name`
- top-level `arg_keys`
- `args_sha256` fingerprint
- mapping status: `mapped`, `unmapped`, or `error`
- `action` and `resource` when mapped
- strict unmapped policy mode
- whether the plugin blocked the call
- public block reason when applicable

The coverage log intentionally does not include raw argument values, grant refs,
agent keys, audit event ids, or model-facing data. If a tool executes in the
Hermes runtime but no `pre_tool_call` coverage row appears for it, record it as
`bypassed` and treat it as outside the Vinctor boundary.

When the measurement requires exact fixture arguments, set:

```bash
VINCTOR_HERMES_COVERAGE_LOG_INCLUDE_ARGS=1
```

Use that flag only with controlled non-sensitive fixtures. It writes raw args to
the local coverage log so the matrix can document the exact runtime event shape.
It does not change model-facing output or the strict `/v1/enforce` body.

## Runbook: How to Fill on a Real Hermes Runtime

The steps below turn this template into a measured matrix. They combine the
runtime coverage log (`VINCTOR_HERMES_COVERAGE_LOG`, the only source of truth for
`pre_tool_call traversal`) with the harness (`scripts/coverage_harness.py`, which
fills the mapping/enforce/block columns and cross-checks the log). A condensed
copy of this runbook lives in `scripts/README.md`.

Distinction to preserve while filling:

- `pre_tool_call traversal` comes ONLY from a runtime coverage-log row. Row
  present before execution → `observed`; tool executed with no row → `bypassed`
  (outside the Vinctor boundary); probe not run → `unmeasured`.
- `resolve_tool_call result`, `Enforce action:resource`, and
  `Strict unmapped block observed` may be cross-checked with the harness, but
  only record them for a family whose traversal you actually `observed`.

## Measurement Procedure

1. Record the exact Hermes runtime package/version and commit if available.
2. Install and load this plugin through the runtime-supported plugin path.
3. Confirm `plugin.yaml` advertises `pre_tool_call` and the runtime registers
   `vinctor_hermes_plugin.plugin:register`.
4. Enable `VINCTOR_HERMES_COVERAGE_LOG`.
5. Run each controlled tool probe below with non-sensitive fixture arguments.
   Use the same fixtures the harness uses (`PROBES` in
   `scripts/coverage_harness.py`) so the runtime log and harness output line up.
6. For each attempted tool call, compare the intended invocation list against
   the coverage log:
   - row present before execution: `observed`
   - tool executed but no row present: `bypassed`
   - probe not run: `unmeasured`
7. For unmapped tools, run once with `VINCTOR_HERMES_UNMAPPED_POLICY=block` and
   record whether the runtime received a block directive before execution.
   `coverage_harness.py --unmapped-policy block` shows the expected strict block
   behavior for the unmapped families.
8. Save the measured result as
   `docs/validation/coverage-matrix-hermes-<version>-<date>.md`.

## Matrix

All rows are `unmeasured` until a versioned Hermes runtime is available.

| Tool family | Probe target | pre_tool_call traversal | resolve_tool_call result | Strict unmapped block observed | Enforce action:resource | Boundary status | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| file read | `read_file` | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | Run with a repo fixture path. |
| file write | `write_file` | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | Run with a temp repo fixture path. |
| file edit | `edit_file` | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | Use a non-sensitive fixture. |
| file delete | `delete_file` | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | Confirm block occurs before delete. |
| patch | `patch` | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | Include add/update/delete patch fixtures. |
| terminal/Bash | `terminal` or Bash-equivalent | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | Include benign `npm test` fixture. |
| process control | `process` | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | Probe list, write, wait, kill if supported. |
| CI/test command | `terminal: npm test` | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | Expected mapping only if observed. |
| build command | `terminal: npm run build` | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | Expected mapping only if observed. |
| deploy command | `terminal: vercel deploy --prod` | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | Use non-production fixture credentials. |
| release command | `terminal: gh release create ...` | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | Do not hit a real repo. |
| code execution | `execute_code` | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | Use harmless code fixture. |
| memory | `memory` | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | Probe read/write/delete if runtime exposes them. |
| session search | `session_search` | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | Probe fixture query only. |
| cron | `cronjob` | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | Avoid persistent schedules. |
| delegation | `delegate_task` | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | Use no-op child task fixture. |
| web search | `web_search` | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | Use deterministic test query. |
| web extract | `web_extract` | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | Use local or fixture URL. |
| browser read | `browser_snapshot` or equivalent | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | Runtime-specific tool name required. |
| browser action | `browser_click` or equivalent | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | Use fixture page. |
| browser CDP | `browser_cdp` | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | Confirm runtime exposes this tool. |
| outbound message | `send_message` | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | Use test target only. |
| MCP filesystem | `mcp_filesystem_read_file` | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | Include `mcp_<server>_<tool>` shape. |
| MCP filesystem alternate | `mcp__filesystem__read_file` | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | Include `mcp__server__tool` shape. |
| MCP GitHub | `mcp_github_create_pull_request` | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | Use fixture args, not a real repo mutation. |
| MCP Slack | `mcp_slack_post_message` | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | Use test channel only. |
| Dynamic MCP mapped by config | `mcp_internal_release_promote` | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | Requires reviewed operator config. |
| Dynamic MCP unmapped | `mcp_unknown_custom_tool` | unmeasured | unmeasured | unmeasured | unmeasured | unmeasured | With strict unmapped policy, should block if observed. |

## Bypassed Findings

None measured. Do not infer that no bypasses exist. A bypass finding requires a
real Hermes tool invocation that executes without a corresponding coverage log
entry.
