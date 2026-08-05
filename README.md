# Vinctor Hermes Plugin

> **Status:** Boundary Preview

A Hermes plugin that registers a `pre_tool_call` authorization boundary for
selected high-impact Hermes tool calls.

Vinctor authorizes configured, mediated tool calls routed through an adapter
boundary. Unwrapped tool paths remain outside Vinctor's boundary. Vinctor does
not provide OS/process/account isolation, sandboxing, raw tool interception,
provider credential control, or rollback of already-started work.

This repository is independent of Hermes and Nous Research. It does not issue
grants and does not run the Vinctor authorization service.

## Runtime Flow

1. Hermes proposes a tool call.
2. This plugin receives the `pre_tool_call` hook.
3. The plugin maps the tool call to `(action, resource)`.
4. The plugin calls `POST /v1/enforce` with `X-Agent-Key` and the strict v1 body:
   `{ "grant_ref": "...", "action": "...", "resource": "..." }`.
5. Permit returns no block directive, so Hermes continues execution.
6. Deny, timeout, unavailable service, missing auth, invalid config, or malformed
   mapped calls return a block directive before execution.
7. Unmapped calls return no directive and defer to Hermes' own approval or guard
   path by default. Operators can opt into strict unmapped blocking with
   `VINCTOR_HERMES_UNMAPPED_POLICY=block`.

The model-facing block message is a fixed template. It never includes
`grant_ref`, raw tool arguments, `audit_event_id`, or matched scope.

**Enforce response contract (shared by every Vinctor adapter).** An HTTP `200`
is treated as a permit **only** when the body carries both `decision: "permit"`
and a string `audit_event_id` containing at least one ASCII alphanumeric
character. A missing, null, empty, visually blank, or non-string `audit_event_id` is **not** a permit: it fails
closed as `service_unavailable` and the call is blocked. Every allowed action
therefore has durable, correlatable decision evidence, and a malformed or
compromised response cannot authorize an unauditable action. The Claude Code
hook, the Codex hook, and the MCP PEP enforce the identical rule.

## Before You Start

Have these in place before installing:

- A Hermes runtime that loads local plugins.
- A Python environment for installing this package.
- Access to a running Vinctor authorization service: its endpoint, an agent
  key, and a grant reference.

## Install

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install vinctor-hermes-plugin
.venv/bin/vinctor-hermes-plugin --version
```

From a source checkout, contributors can instead run
`pip install -e ".[dev]"`.

Set these environment variables in the Hermes runtime:

- `VINCTOR_ENDPOINT` - Vinctor authorization service base URL.
- `VINCTOR_AGENT_KEY` - agent API key, sent as `X-Agent-Key`.
- `VINCTOR_GRANT_REF` - opaque grant reference for `/v1/enforce`.

Optional:

- `VINCTOR_BOUNDARY_ID` - boundary id from the local Vinctor service. It is
  required by fresh `vinctor-core` 0.6.0 databases; upgraded databases retain
  their previous mandate default. The plugin sends it as
  `X-Vinctor-Boundary-Id`.
- `VINCTOR_HERMES_PLUGIN_CONFIG` - path to a JSON mapping config.
- `VINCTOR_HERMES_MCP_REGISTRY` - path to an exported Hermes MCP tool registry.
  Runtime registry-derived rules are ignored unless explicitly enabled.
- `VINCTOR_HERMES_ALLOW_MCP_REGISTRY_RUNTIME_RULES` - set to `1` to append
  inferred exact-match registry rules to runtime config. Prefer
  `draft-mcp-config` plus reviewed config for normal operator workflows.
- `VINCTOR_HERMES_UNMAPPED_POLICY` - set to `block` to block unmapped tool calls
  before execution. Any other value keeps the default Hermes-defer behavior.
- `VINCTOR_HERMES_DECISION_LOG` - path to a local JSONL operator log for
  non-model-facing decision metadata.
- `VINCTOR_HERMES_COVERAGE_LOG` - path to a local JSONL probe log for measuring
  which real Hermes tool calls reach `pre_tool_call`.
- `VINCTOR_HERMES_COVERAGE_LOG_INCLUDE_ARGS` - set to `1` only during controlled
  non-sensitive coverage probes to include raw fixture args in the local coverage
  log.
- `VINCTOR_HERMES_TIMEOUT_MS` - enforce request timeout in milliseconds.

## Hermes Enablement

Hermes plugin loading can vary by deployment. The repository ships both a Python
package entry point and a directory-style `plugin.yaml`; use the path your Hermes
runtime already supports for local plugins.

Directory plugin shape:

```text
vinctor-hermes-plugin/
  plugin.yaml
  src/vinctor_hermes_plugin/plugin.py
```

Python entry point:

```toml
[project.entry-points."hermes_agent.plugins"]
vinctor = "vinctor_hermes_plugin.plugin:register"
```

Local registration smoke:

```bash
PYTHONPATH=src python scripts/plugin_load_smoke.py
```

Expected output:

```text
registered pre_tool_call
```

Operator checklist:

1. Install the package in the Hermes runtime environment.
2. Point Hermes at this plugin directory or package entry point.
3. Confirm Hermes registers the `pre_tool_call` hook from
   `vinctor_hermes_plugin.plugin:register`.
4. Run `vinctor-hermes-plugin explain` on a known mapped event.
5. Run a mapped Hermes workflow and confirm permit, deny, fail-closed, and audit
   behavior against the Vinctor service.

See [docs/preflight.md](docs/preflight.md) for the first-run checklist.

## Offline Tools

Show the config a newly constructed boundary would load — resolved from the
same environment the plugin reads, so a wrong or missing
`VINCTOR_HERMES_PLUGIN_CONFIG` is visible instead of silent:

```bash
vinctor-hermes-plugin doctor          # config: /path/to/config.json (3 rules)
vinctor-hermes-plugin doctor --json
```

With no path configured it reports `built-in empty config` — a legitimate
state, not an error. A configured path that is missing, a directory, not a
regular file (e.g. a FIFO), too large, or malformed is reported as
`invalid_config` with exit 1; the boundary blocks every call for as long as
that is true, and recovers on its own once the file is repaired. A running
boundary re-validates the configured sources on every call with a `stat` and
re-reads them only when one changes (inode, mtime, or size) or stops being
readable. Later file edits therefore take effect without a restart, including
tightening and revocation, and deleting the file blocks again on the next call
rather than leaving the last snapshot in force. `doctor` reports what the
boundary would load from the same environment.

Validate a specific config file:

```bash
vinctor-hermes-plugin validate .vinctor/hermes-plugin.json --json
```

Explain how one tool call maps, without calling the service:

```bash
printf '%s' '{"tool_name":"terminal","args":{"command":"npm test"}}' > /tmp/hermes-event.json
vinctor-hermes-plugin explain /tmp/hermes-event.json --json
```

Show the installed version:

```bash
vinctor-hermes-plugin --version
```

Show CLI help:

```bash
vinctor-hermes-plugin --help
```

Draft config rules from a Hermes MCP tool registry:

```bash
vinctor-hermes-plugin draft-mcp-config /tmp/hermes-mcp-tools.json --json
```

`explain` uses `VINCTOR_HERMES_PLUGIN_CONFIG` when `--config` is omitted.
It uses `VINCTOR_HERMES_MCP_REGISTRY` only when `--mcp-registry` is omitted and
`VINCTOR_HERMES_ALLOW_MCP_REGISTRY_RUNTIME_RULES=1`.

## Getting a Grant

This plugin does not issue grants. A real run needs an existing Vinctor grant
reference and agent key from the Vinctor authorization service.

For offline evaluation:

1. Capture or write a Hermes-style event with `tool_name` and `args`.
2. Run `vinctor-hermes-plugin explain <event> --json`.
3. Create or select a Vinctor grant that covers the returned `(action, resource)`.
4. Set `VINCTOR_ENDPOINT`, `VINCTOR_AGENT_KEY`, `VINCTOR_GRANT_REF`, and
   optional `VINCTOR_BOUNDARY_ID`.
5. Run the Hermes workflow and check the service audit for the permit or deny
   decision.

If `explain` returns `unmapped`, the plugin will defer to Hermes unless an
operator config rule maps that tool call or `VINCTOR_HERMES_UNMAPPED_POLICY` is
set to `block`.

## Runtime Boundary Coverage

Runtime boundary coverage means a versioned Hermes runtime actually routed a
tool call through this plugin's `pre_tool_call` hook before execution. It is
separate from mapping coverage below.

Current status: no versioned Hermes runtime has been measured in this
repository. The current matrix is a template with all cells marked
`unmeasured`: [coverage matrix](docs/validation/coverage-matrix-hermes-unmeasured-2026-06-11.md).

Do not treat the mapping table below as evidence that Hermes routes those tools
through the boundary. A tool is inside the Vinctor boundary only after a measured
coverage row shows `pre_tool_call` traversal for that runtime version. A tool
that executes without a coverage log entry is outside the boundary.

## Built-In Mapping Coverage

Built-in mappings cover selected Hermes core and plugin-style tool calls after
they reach `pre_tool_call`:

| Surface | Mapping |
| --- | --- |
| file reads and search | `read:repo/<path>` (in-tree) or `read:fs/<path>` (external/absolute) or `read:secret/<kind>` |
| file writes and patches | `write:repo/<path>` / `write:fs/<path>` or `write:secret/<kind>` |
| patch delete headers, direct delete tools, single-target `rm`/`rmdir` | `delete:repo/<path>` / `delete:fs/<path>` or `delete:secret/<kind>` |
| branch creation commands | `write:repo/branch/<branch>` |
| local git (`status`/`log`/`diff`/`show`; `add`/`commit`/`stash`/`clone`; explicit-URL `fetch`/`pull`) | `read:shell/git` / `write:shell/git`; default or named remotes fail closed because config can bind an executable helper |
| `git push <github-url>` (force spellings destroy remote history) | `write:github/<owner>/<repo>/contents`, force `delete:...`; a forced bare remote maps conservatively to `delete:shell/git`, while a non-force bare remote fails closed |
| `git reset --hard`, `git branch -D`, `git clean -f` | `delete:shell/git` |
| pipe to shell (`curl ... \| sh`) | `execute:shell/<first-token>` |
| npm-family scripts and installs (`npm/pnpm/yarn test\|run\|install\|ci`, `npx`) | `execute:shell/<tool>` |
| `npm publish` (`--workspace <name>` carries the name; bare publish binds the unknown segment) | `deploy:pkg/npm/<name>` or `deploy:pkg/npm/_` |
| non-npm test/build runners (`pytest`, `go test`, `cargo build`, ...) | `execute:ci/test` / `execute:ci/build` |
| terminal secrets read (`cat .env`, `printenv`) | `read:secret/env` |
| infra apply (`kubectl apply`, `terraform apply`, `helm install`/`upgrade`) | `execute:infra/{k8s,terraform,helm}/apply` |
| platform deploy (`vercel`, `fly deploy`, `railway up`) | `deploy:<platform>/app` |
| other deployment commands | `execute:deploy/<env>` |
| `docker build`/`run` / `push` / `rmi` | `execute`/`deploy`/`delete` over `container/<registry>/<image>`; unresolvable image references fail closed |
| `gh pr merge`/`pr create`/`release create`/`secret set`/`workflow run\|rerun\|cancel` with `--repo` | `deploy`/`write`/`execute` over `github/<owner>/<repo>/<kind>`; without `--repo` fails closed |
| process control | `read/write/delete/execute:process/<id>` |
| `execute_code` | `execute:code/python` |
| memory writes/removes/search | `write/delete/read:memory/<scope>` |
| session search tools | `read:session/search` |
| cron jobs | `read/write/delete/execute:cron/...` |
| delegation | `execute:agent/delegate` |
| web and browser network calls | `send:web/search`, `send:net/<scope>/<host>` |
| browser page reads/actions/CDP | `read:browser/page`, `execute:browser/action`, `execute:browser/cdp` |
| outbound messaging | `send:message/<target>` |
| MCP filesystem, GitHub, Slack known tables | `repo/` / `fs/` / `secret/` paths, `github/<owner>/<repo>/<kind>` (canon kinds incl. `contents` and `secret`), `chat/slack[/<channel>]` |

Everything else is unmapped unless an operator config rule maps it. Unmapped
calls that reach `pre_tool_call` can be blocked with
`VINCTOR_HERMES_UNMAPPED_POLICY=block`; unobserved runtime paths remain outside
this plugin's measured boundary.

Terminal Git classification is anchored to `git`, the explicit
`!`/`env`/`command` wrappers, or trusted executable paths. Assignment
prefixes, arbitrary executable paths, repository/config overrides, external
helpers, and unresolved Git subcommands are unmapped before operator config.
Nested shell reinterpreters and other shell-safety rejections always block,
independent of the optional policy for otherwise unknown tools. Ref deletion,
mirror, and prune pushes retain `delete`.

The MCP filesystem, GitHub, and Slack classifiers mirror the practical table
coverage from the Claude hook, adapted to Hermes' `mcp_<server>_<tool>` names.
The classifier also accepts `mcp__<server>__<tool>` for operator fixture parity.

The mapping coverage is intentionally non-exhaustive. Hermes tool names can be
static, dynamic, plugin-provided, or MCP-derived. Unknown MCP servers and
unknown tools on known servers should be mapped with operator config only when
the local operator understands their effect.

For custom MCP servers, export the Hermes MCP tool registry and run
`draft-mcp-config`. The generated rules are exact-match config drafts; operators
should review them before using them as runtime policy translation. Runtime
registry-derived rules require
`VINCTOR_HERMES_ALLOW_MCP_REGISTRY_RUNTIME_RULES=1` and remain coarser than
reviewed operator config.

## Development

```bash
python -m pytest            # uses [tool.pytest.ini_options] (pytest is in the dev extra)
PYTHONPATH=src python -m unittest discover -s tests   # equivalent, no extra deps
python -m ruff check .
PYTHONPATH=src python scripts/plugin_load_smoke.py
VINCTOR_CORE_PATH=../vinctor-core PYTHONPATH=src python -m unittest tests.test_mock_vinctor_service_smoke -q
python scripts/claim_safety_scan.py
python scripts/service_backed_e2e.py
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full quality gate checklist.
