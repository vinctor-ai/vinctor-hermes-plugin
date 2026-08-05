# Configuration Reference

Operator policy for the Vinctor Hermes Plugin lives in an optional JSON file.
It maps Hermes tool calls to Vinctor `(action, resource)` pairs. The Vinctor
authorization service still makes the permit or deny decision.

## File Location

- Default: no config file. Built-in mappings only.
- Override: `VINCTOR_HERMES_PLUGIN_CONFIG=/absolute/path/to/hermes-plugin.json`.
- Optional MCP registry:
  `VINCTOR_HERMES_MCP_REGISTRY=/absolute/path/to/hermes-mcp-tools.json`.
- Optional MCP runtime rule opt-in:
  `VINCTOR_HERMES_ALLOW_MCP_REGISTRY_RUNTIME_RULES=1`.
- Optional strict unmapped policy:
  `VINCTOR_HERMES_UNMAPPED_POLICY=block`.
- Optional local decision log:
  `VINCTOR_HERMES_DECISION_LOG=/absolute/path/to/decisions.jsonl`.
- Optional runtime coverage probe log:
  `VINCTOR_HERMES_COVERAGE_LOG=/absolute/path/to/coverage.jsonl`.
- Optional raw fixture args in the coverage probe log:
  `VINCTOR_HERMES_COVERAGE_LOG_INCLUDE_ARGS=1`.
- Missing file: valid empty config. The CLI reports
  `config path not found; using empty config`.
- Present but invalid file: fail closed with `invalid_config`.

Invalid config blocks every tool call until fixed. Missing config does not.

`VINCTOR_HERMES_COVERAGE_LOG` is for measuring which tool calls actually enter
the `pre_tool_call` boundary in a real Hermes runtime. It records `tool_name`,
top-level argument keys, an argument fingerprint, mapping status, public block
reason, and mapped action/resource when available. It does not record raw
argument values by default and is not a substitute for the Vinctor audit log.
Set `VINCTOR_HERMES_COVERAGE_LOG_INCLUDE_ARGS=1` only for controlled,
non-sensitive fixture probes when the coverage matrix needs exact argument
values.

## Shape

```json
{
  "version": 1,
  "rules": [
    {
      "tool": "terminal",
      "matchType": "exact",
      "pattern": "npm test",
      "action": "execute",
      "resource": "ci/test"
    }
  ]
}
```

Rule fields:

| Field | Required | Notes |
| --- | --- | --- |
| `tool` | yes | Hermes tool name such as `terminal`, `write_file`, `patch`, `cronjob`, `mcp_github_create_pull_request`, or a project tool name. |
| `matchType` | yes | `exact`, `prefix`, or `glob`. |
| `pattern` | yes | String matched against the tool's input value. |
| `action` | yes | One of `read`, `write`, `execute`, `deploy`, `delete`, `send`. |
| `resource` | yes | Explicit Vinctor resource. Wildcards are not allowed. |
| `inputField` | no | Top-level argument field to match instead of the default value. |

## Matching

For `terminal`, `pattern` matches the normalized command. For file tools, it
matches the file path. For other tools, it matches the tool name unless
`inputField` is set.

| Tool family | Default match input |
| --- | --- |
| `terminal` | normalized `command` |
| `write_file`, `read_file`, `patch`, file MCP tools | `path` or `file_path` |
| `web_extract`, `browser_navigate` | tool name unless `inputField` is set |
| `cronjob`, `delegate_task`, `send_message`, MCP tools | tool name unless `inputField` is set |

Built-in MCP classification recognizes known filesystem, GitHub, and Slack tool
tables. Operator config still names the pair those calls are charged over.

### An operator rule may add a charge; it may never subtract an effect

A rule renames what a call is charged as. It does not change what the call
*does*. So when a built-in classifier finds that a call causes SEVERAL effects
(a move reads, deletes and writes; `read_multiple_files` reads every member; a
fork also copies contents and creates a repository in another namespace), those
effects are unioned into the rule's requirement set - the classifier's primary
pair included - minus the rule's own pair. Every member must be permitted or the
call is denied.

Two consequences worth stating plainly:

- A rule matching on one argument cannot license the others. "A move whose
  `source` is under `/tmp` is a scratch write" still charges wherever the move
  LANDS, so a `/tmp`-scoped grant cannot write into `~/.ssh`.
- A classifier refusal is not overridable. If a recognized tool carries a target
  the resource mapper cannot express, the call fails closed even when a rule
  matches it - authorizing the rule's single pair would run the whole call.

A single-effect call is unaffected: the rule is a plain rename, exactly as
before. That is the boundary of the guarantee, and it is worth stating plainly
too: "a rule may never subtract an effect" holds for the SET, not for the
RESOURCE. On a single-effect operation the rule's resource fully replaces the
classifier's, including a `secret/*` one - a `write_file` rule resolving to
`fs/allowed` charges a write to `~/.ssh/authorized_keys` as `write fs/allowed`
and nothing else, where the built-in classifier would have charged
`write secret/ssh`. On a multi-effect operation the classifier's resources
survive, because its members are unioned back in: the analogous `move_file` rule
still charges `read secret/ssh` and `delete secret/ssh` alongside the rule's own
pair. Built-in mappings are a floor, not a default.

If `VINCTOR_HERMES_MCP_REGISTRY` is set by itself, the runtime ignores inferred
rules. This keeps discovery separate from authorization-boundary behavior.
Runtime registry-derived rules are appended only when
`VINCTOR_HERMES_ALLOW_MCP_REGISTRY_RUNTIME_RULES=1`.

Generated registry rules are exact-match rules for the tool name and usually
produce coarse resources such as `mcp/server/tool`. Prefer `draft-mcp-config`,
review the output, and materialize intentional rules in explicit operator
config. If runtime-generated rules are enabled, explicit config rules still win
over generated rules, even when the explicit rule is broader.

Use `inputField` to match a specific top-level argument:

```json
{
  "version": 1,
  "rules": [
    {
      "tool": "send_message",
      "inputField": "target",
      "matchType": "prefix",
      "pattern": "slack:C",
      "action": "send",
      "resource": "message/slack/company"
    }
  ]
}
```

Mandatory terminal safety classification runs first: unsupported shell control
flow and nested reinterpreters block, pipe-to-shell maps to `execute`, and
destructive force, delete, mirror, or prune push argv maps to `delete`. These
results cannot be downgraded by config. For all
other calls, the highest-priority operator match wins, then the most specific.
Git resolution is anchored to the command start and permits only the explicit
`!`/`env`/`command` wrappers or trusted executable paths; assignments,
repository/config overrides, external helpers, and unresolved subcommands fail
closed before config:
`exact` before `prefix` before `glob`, more literal tokens, fewer wildcards, and
longer pattern. Registry-derived runtime rules have lower priority than explicit
operator config.

## Path and URL Handling

Built-in file classifiers normalize simple relative paths, remove leading `./`,
and reject null bytes, empty paths, root-only paths, or paths that escape with
`..`.

Sensitive paths map to a secret resource instead of a raw file path:

| Path pattern | Resource |
| --- | --- |
| `.env`, `.env.*` | `secret/env` |
| `.ssh/*`, `id_rsa`, `id_ed25519` | `secret/ssh` |
| `.aws/*` | `secret/aws` |
| `.config/gcloud/*`, `application_default_credentials.json` | `secret/gcp` |
| `.azure/*` | `secret/azure` |
| `.npmrc`, `.pypirc` | `secret/package-registry` |
| `.kube/config` | `secret/kube` |
| `.netrc` | `secret/netrc` |
| names containing `secret` or `credential` | `secret/app` |

Built-in network classifiers reduce URLs to host resources:

- `https://example.com/docs` -> `net/external/example.com`
- `http://localhost:3000` -> `net/internal/localhost`
- multiple hosts -> `net/<scope>/multiple`

## Examples

Map a project-specific deployment command:

```json
{
  "version": 1,
  "rules": [
    {
      "tool": "terminal",
      "matchType": "prefix",
      "pattern": "make deploy-staging",
      "action": "execute",
      "resource": "deploy/staging"
    }
  ]
}
```

Map a custom MCP server tool:

```json
{
  "version": 1,
  "rules": [
    {
      "tool": "mcp_internal_release_promote",
      "matchType": "exact",
      "pattern": "mcp_internal_release_promote",
      "action": "execute",
      "resource": "release/internal"
    }
  ]
}
```

Validate and inspect:

```bash
vinctor-hermes-plugin validate .vinctor/hermes-plugin.json --json
vinctor-hermes-plugin explain /tmp/hermes-event.json --json
```

Draft rules from a runtime MCP registry:

```bash
vinctor-hermes-plugin draft-mcp-config /tmp/hermes-mcp-tools.json --json
```

Accepted registry shapes:

```json
{
  "tools": [
    {
      "name": "mcp_notion_create_page",
      "description": "Create a page"
    }
  ]
}
```

The command emits a normal config object plus metadata about built-in and
skipped tools. It does not call MCP servers, issue grants, or update files.
Ambiguous multi-verb or negated tools are skipped instead of translated into
runtime rules.

Map a custom memory retrieval tool:

```json
{
  "version": 1,
  "rules": [
    {
      "tool": "retrieve_context",
      "matchType": "exact",
      "pattern": "retrieve_context",
      "action": "read",
      "resource": "memory/project"
    }
  ]
}
```
