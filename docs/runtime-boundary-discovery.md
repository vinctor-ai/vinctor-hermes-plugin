# Runtime Boundary Discovery

## Finding

Hermes Agent exposes the relevant extension surface through plugins, lifecycle
hooks, and middleware. The Vinctor boundary uses the `pre_tool_call`
lifecycle hook.

## Attachment Point

The plugin registers:

```python
ctx.register_hook("pre_tool_call", boundary.pre_tool_call)
```

Hermes calls this hook before tool execution. A plugin can return:

```python
{"action": "block", "message": "Reason"}
```

to prevent the tool from executing. Returning `None` lets Hermes continue.

This attachment-point discovery is not the same as runtime boundary coverage.
Coverage requires observing a versioned Hermes runtime and recording which tool
families actually reach `pre_tool_call`. The current runtime coverage matrix is
unmeasured:
`docs/validation/coverage-matrix-hermes-unmeasured-2026-06-11.md`.

## Why This Is the Primary Boundary

When routed through `pre_tool_call`, the plugin authorizes before execution.
`pre_tool_call` is the direct semantic fit because it blocks before Hermes
dispatches the tool.

Hermes also exposes `tool_execution` middleware. That path may be useful later
for wrapping execution, but it is secondary for this plugin because the hook contract
is a cleaner pre-execution authorization boundary.

## Tool Dispatch Surface

The inspected Hermes-style surface is broader than a command-line hook model.
The table below identifies mapping and probe targets; it does not claim that
each row has been observed traversing `pre_tool_call` in a real Hermes runtime:

| Surface | Boundary implication |
| --- | --- |
| `terminal` | Repository writes, build/test, release, deployment, and destructive shell actions are command patterns. |
| `process` | Background process reads, stdin writes, waits, kills, and closes are separate actions. |
| file tools | `read_file`, `write_file`, `patch`, and `search_files` need path and secret-resource handling. |
| `execute_code` | Python execution can invoke wrapped tools; when recursion is unavailable, classify as broad code execution. |
| `memory`, `session_search` | Memory writes and context retrieval affect future model behavior and session visibility. |
| `cronjob` | Scheduled jobs create autonomous future execution. |
| `delegate_task` | Child agents may receive their own toolsets and execution authority. |
| web/browser tools | Navigation, extraction, page actions, CDP, and snapshots are separate risk families. |
| `send_message` | Outbound messages are consequential sends. |
| MCP bridge | Hermes registers dynamic names shaped like `mcp_<server>_<tool>`. The plugin table-classifies known filesystem, GitHub, and Slack tools; unknown servers remain operator-defined. |

## Artifact Shape

The artifact is a Hermes plugin, not a CLI stdin/stdout hook. The package name is
`vinctor-hermes-plugin`.

This repository is independent of Hermes and Nous Research.
