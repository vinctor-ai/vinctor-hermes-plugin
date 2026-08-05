# Vinctor Hermes Plugin v0.2 Coverage Design

Date: 2026-06-10
Status: Approved direction, implementation spec

## Context

The first plugin iteration proved the core boundary shape:

Hermes `pre_tool_call` -> map tool call to `(action, resource)` -> call Vinctor
`POST /v1/enforce` -> permit continues -> deny or failure blocks before
execution -> unmapped calls defer to Hermes.

The next iteration raises the plugin from a narrow proof to a broader dogfood
boundary comparable to the Claude hook. It must still stay a Hermes plugin, not
a generic agent framework and not a public SDK.

## Product Decisions

- Package and repository name remain `vinctor-hermes-plugin`.
- The primary artifact is a Hermes plugin with a `pre_tool_call` boundary.
- `tool_execution` middleware remains future work unless `pre_tool_call` cannot
  block reliably in a target Hermes runtime.
- The v1 enforcement contract is unchanged:
  - body: `{ "grant_ref": "...", "action": "...", "resource": "..." }`
  - header: `X-Agent-Key`
- No workspace token belongs in the runtime plugin path.
- Classified calls fail closed on deny, service failure, timeout, missing auth,
  invalid config, or unsafe/malformed input.
- Unclassified calls return no block directive and defer to Hermes' guard or
  approval path.
- Model-facing output must not disclose `grant_ref`, `agent_key`,
  `audit_event_id`, raw tool arguments, raw command text, matched config
  patterns, or mapped resources.
- Status remains Boundary Preview.
- Documentation may say this repository is independent of Hermes and Nous
  Research, but must not imply vendor endorsement or special runtime status.

## Hermes Runtime Surface

Upstream Hermes exposes a broad core tool surface:

- File tools: `read_file`, `write_file`, `patch`, `search_files`.
- Terminal and process tools: `terminal`, `process`.
- Runtime code execution: `execute_code`.
- Memory and context retrieval: `memory`, `session_search`.
- Scheduled autonomy: `cronjob`.
- Delegation: `delegate_task`.
- Web and browser tools: `web_search`, `web_extract`, `browser_*`.
- Outbound messaging: `send_message`.
- MCP bridge: dynamic names shaped like `mcp_<server>_<tool>`.

Hermes does not expose dedicated repository, release, deployment, or CI APIs in
the inspected surface. Those actions appear through terminal commands, MCP
servers, or delegated tools.

## Built-In Mapping Scope

v0.2 broadens built-in classification around high-impact families:

| Hermes surface | Built-in mapping |
| --- | --- |
| File reads/search | `read:repo/<path>` or `read:secret/<kind>` |
| File writes/patches | `write:repo/<path>` or `write:secret/<kind>` |
| Patch delete headers | `delete:repo/<path>` or `delete:secret/<kind>` |
| Terminal tests/builds | `execute:ci/test`, `execute:shell/build` |
| Terminal git branch/push/reset/clean | `write:repo/branch/<branch>`, `execute:git/push`, `execute:git/push-force`, `delete:git/reset-hard`, `delete:git/clean-force` |
| Terminal release/deploy | `execute:release/<target>`, `execute:deploy/<env>` |
| Terminal shell deletes | `delete:repo/<path>` for direct `rm` patterns |
| Process control | `read:process/<id>`, `write:process/<id>`, `execute:process/<id>`, `delete:process/<id>` |
| `execute_code` | `execute:code/python` |
| Memory/session | `read:memory/<scope>`, `write:memory/<scope>`, `delete:memory/<scope>`, `read:session/search` |
| Cron jobs | `read/write/delete/execute:cron/job/<id-or-new>` |
| Delegation | `execute:agent/delegate` |
| Web/browser | `send:web/search`, `send:net/<scope>/<host>`, `read:browser/page`, `execute:browser/action`, `execute:browser/cdp` |
| Messaging | `send:message/<target>` |
| MCP filesystem | File read/write/delete mappings with secret-path detection |
| MCP GitHub | Repo read/write/execute/delete mappings for common PR, issue, release, workflow, branch, and secret tools |

The plugin keeps using the existing Vinctor convention for deployment and
release:

- `execute:deploy/<env>`
- `execute:release/<target>`

The `deploy` verb is not introduced as the default in this repo.

## Secret and Sensitive Resources

Path-based classifiers must detect common sensitive material before producing a
repo resource:

- environment files: `.env`, `.env.*`
- SSH keys/config: `.ssh/*`, `id_rsa`, `id_ed25519`
- cloud credentials: `.aws/*`, `.config/gcloud/*`, `.azure/*`
- package credentials: `.npmrc`, `.pypirc`
- Kubernetes config: `.kube/config`
- machine credentials: `.netrc`
- generic secret files: names containing `secret`, `secrets`, `credential`, or
  `credentials`

Sensitive paths map to `secret/<kind>` so model-facing output and service
resources avoid raw secret-bearing file names.

## Config Model

Operator config remains a narrow override layer:

- It may map exact, prefix, or glob matches to explicit Vinctor resources.
- It does not issue grants.
- It does not change the v1 enforce contract.
- It wins over built-in mappings so local deployments can classify site-specific
  Hermes plugins and MCP tools.
- Invalid config blocks all calls until fixed.
- Missing config is valid and equivalent to no operator rules.

## CLI Scope

The CLI remains offline-only:

- `validate` checks config and reports path, validity, rule count, and errors.
- `explain` maps a captured tool event without calling Vinctor.
- `--version` reports package version.
- `explain` uses `VINCTOR_HERMES_PLUGIN_CONFIG` if `--config` is absent.

The CLI must not print runtime secrets or raw blocked messages.

## Non-Goals

- No sandboxing.
- No raw syscall or process interception.
- No grant issuance, policy store, audit store, dashboard, or hosted service.
- No approval workflow.
- No provider credential control.
- No generic MCP security framework.
- No claim of vendor endorsement or special runtime status.

## Acceptance Criteria

- Unit tests cover every built-in family listed above.
- Non-disclosure tests cover all block reasons and sensitive value classes.
- Service-backed validation still proves permit, deny, fail-closed, and audit
  behavior.
- Documentation has a built-in coverage appendix, deeper configuration
  reference, and docs-only adoption validation.
- Claim-safety scan passes.
