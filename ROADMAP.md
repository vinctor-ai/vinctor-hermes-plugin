# Roadmap

This document is not a release commitment. It records the work currently
recognized as valuable after v0.3.3.

## v0.1.0

Goal: prove Vinctor inside the real Hermes extension shape by using a Hermes
plugin and the `pre_tool_call` lifecycle hook as the runtime authorization
boundary.

Done:

- strict `/v1/enforce` client
- `pre_tool_call` block directive integration
- initial high-impact built-in mappings
- operator config mappings
- offline `validate` and `explain`
- non-disclosure invariant tests
- service-backed local E2E

## v0.2.0

Goal: broaden the dogfood surface to cover the Hermes core tool families most
likely to contain consequential actions.

Done:

- file read/write/delete/search mappings with sensitive-path resources
- terminal git push/reset/clean/delete, package publish, Docker, deploy, and
  release mappings
- process, `execute_code`, memory, session, cron, delegate, web, browser, and
  outbound message mappings
- MCP filesystem, GitHub, and Slack subset mappings using Hermes' dynamic
  `mcp_<server>_<tool>` names
- richer CLI parity: `--version`, validate metadata, and env-config explain
- broader non-disclosure matrix
- v0.2 design and implementation plan artifacts

## v0.2.1

Goal: bring MCP classification up to the Claude hook's practical coverage for
the shared filesystem, GitHub, and Slack MCP servers.

Done:

- table-driven MCP filesystem classifier, including multiple-file sensitive
  reads and allowed-directory listing
- table-driven MCP GitHub classifier, including global/owner/repo/flex scopes,
  workflow method actions, and secret scanning
- table-driven MCP Slack classifier, including workspace reads, channel reads,
  search, sends, and ambiguous-send deferral
- compatibility for both Hermes `mcp_<server>_<tool>` and Claude-style
  `mcp__<server>__<tool>` fixture names
- MCP parity design, plan, and tests

## v0.3.0

Goal: reduce custom MCP server friction without automatically authorizing
unknown tools.

Done:

- runtime MCP registry parser for exported Hermes tool lists
- conservative action inference for unknown MCP tools
- `draft-mcp-config` CLI command
- `VINCTOR_HERMES_MCP_REGISTRY` support for reviewed runtime discovery
- `explain --mcp-registry` support
- registry-derived rules append after explicit config when explicitly enabled
- MCP registry design, plan, and tests

## v0.3.1

Goal: harden the dogfood path before real-service/core integration is available.

Done:

- opt-in strict unmapped blocking with `VINCTOR_HERMES_UNMAPPED_POLICY=block`
- MCP registry runtime rules gated behind
  `VINCTOR_HERMES_ALLOW_MCP_REGISTRY_RUNTIME_RULES=1`
- explicit operator config priority over registry-derived runtime rules
- malformed HTTP 200 responses fail closed unless they explicitly permit and
  include an audit event id
- local non-model-facing decision recorder and
  `VINCTOR_HERMES_DECISION_LOG`
- ambiguous or negated multi-verb MCP registry tools skipped during discovery
- `plugin.yaml` version aligned with the Python package and covered by a
  regression test
- operator preflight documentation

## v0.3.2

Goal: close Claude-hook review gaps around quality gates and operator CLI
behavior.

Done:

- independent invariant ratchets for strict `/v1/enforce` body and
  model-facing reason templates
- service deny details collapsed to the fixed `action_denied` block template
- `--help` and unknown-subcommand behavior covered by CLI tests
- `VINCTOR_HERMES_DEBUG=1` config-path diagnostics for local `explain` failures
- reusable `scripts/claim_safety_scan.py` gate
- `CONTRIBUTING.md` quality gates and test-design-review expectations
- GitHub Actions CI for tests, compile, ruff, claim-safety scan, and
  service-backed E2E

## v0.3.3

Goal: separate runtime boundary traversal coverage from local mapping coverage.

Done:

- optional `VINCTOR_HERMES_COVERAGE_LOG` probe for observed `pre_tool_call`
  entries
- sanitized coverage rows with tool name, argument keys, argument fingerprint,
  mapping status, block result, and mapped action/resource
- unmeasured Hermes runtime coverage matrix template
- README and docs wording that binds runtime boundary claims to measured matrix
  cells rather than mapping-table entries

## v0.3.4

Goal: make runtime coverage measurement reproducible and keep mapping coverage
strictly distinct from runtime coverage.

CONTEXT (why this work exists): no versioned Hermes runtime has been measured in
this repository, so runtime boundary coverage (does the runtime actually route a
family through `pre_tool_call`?) is unknown. The `VINCTOR_HERMES_COVERAGE_LOG`
probe and the unmeasured matrix template existed, but there was no reusable way
to drive the tool families or a step-by-step runbook to fill the matrix on a real
runtime.

WHAT THIS CHANGE DOES (current state after this PR):

- adds `scripts/coverage_harness.py`, a reproducible harness that drives the main
  tool families (file read/write/edit/delete/patch, terminal CI/build/deploy/
  release/destructive, process, `execute_code`, memory, session, cron, delegate,
  web/browser, `send_message`, MCP `mcp_`/`mcp__` including unmapped dynamic)
  through the real `pre_tool_call` boundary with an offline stub enforcer, and
  reports per family: mapping status, enforced `action:resource`, block decision,
  and runtime-traversal status
- the harness measures MAPPING coverage only; its synthetic mode reports every
  row's runtime traversal as `unmeasured (synthetic)` and never claims runtime
  coverage
- adds `scripts/README.md` documenting the harness and a fill-in runbook
- extends the unmeasured coverage matrix doc with the harness and a "How to fill
  on a real Hermes runtime" runbook; all matrix cells remain `unmeasured`
- adds harness tests and a CI smoke step; mapping/enforce/block behavior is
  unchanged

NEXT STEPS (top open item): run the harness probe set inside a real versioned
Hermes runtime with `VINCTOR_HERMES_COVERAGE_LOG` set, reconcile attempted calls
against the coverage log (`observed` / `bypassed` / `unmeasured`), and save the
measured result as `docs/validation/coverage-matrix-hermes-<version>-<date>.md`.
Mapping coverage (which tools the harness can classify) is not runtime coverage
(which tools the runtime actually emits `pre_tool_call` for); only fill measured
cells from a real runtime coverage log.

## Deferred

- `tool_execution` middleware adapter path
- live MCP server connection/schema polling
- browser CDP argument-specific classification
- platform plugin families beyond the initial Slack/message mapping
- real Hermes install/load/block smoke once a target runtime is available
  (harness ready in `scripts/coverage_harness.py`; runtime traversal measurement
  is the top open item above)
- real Vinctor service grant lifecycle cases for expired, revoked, unknown, and
  wrong-scope grants
- public SDK middleware API
- hosted-service work
- approval workflow
- sandboxing or raw interception
- canonical switch from `execute:deploy/...` to `deploy:...`
