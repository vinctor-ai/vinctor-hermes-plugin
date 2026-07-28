# Vinctor Hermes Plugin MCP Parity Design

Date: 2026-06-10
Status: Implemented

## Goal

Raise the Hermes plugin's MCP coverage to the same practical breadth as the
Claude hook for the MCP servers that both projects recognize:

- filesystem
- GitHub
- Slack

This is still not runtime MCP schema discovery. It is a table-driven classifier
for known MCP server/tool names observed in the Claude hook and adapted to
Hermes' tool naming.

## Naming Contract

Hermes registers MCP tools as `mcp_<server>_<tool>`. The classifier supports
that shape for the known servers above.

For operator fixture parity, the classifier also accepts Claude-style
`mcp__<server>__<tool>` names.

Unknown MCP servers and unknown tools on known MCP servers remain unmapped and
defer to Hermes or operator config.

## Filesystem

The filesystem classifier follows the Claude hook table:

- read tools: `read_text_file`, `read_file`, `read_media_file`,
  `read_multiple_files`, `list_directory`, `list_directory_with_sizes`,
  `directory_tree`, `search_files`, `get_file_info`,
  `list_allowed_directories`
- write tools: `write_file`, `edit_file`, `create_directory`, `move_file`
- delete tools: `delete_file`, `delete_directory`

Hermes keeps the existing file resource convention:

- normal file paths: `repo/<path>`
- sensitive paths: `secret/<kind>`
- allowed directory listing: `fs/_allowed-dirs`

`read_multiple_files` maps only when at least one path is sensitive. Multiple
non-sensitive paths remain unmapped because they cannot be represented as one
specific `(action, resource)` without broadening the resource.

## GitHub

The GitHub classifier mirrors the Claude hook's table categories:

- context and user reads
- repository, file, commit, branch, tag, release, collaborator reads
- issue reads/writes
- pull request reads/writes
- workflow reads and method-specific actions
- code security and Dependabot reads
- secret scanning reads as `secret/gh`

Scope behavior mirrors the Claude hook:

- global reads: `github/_/<kind>`
- owner-scoped reads: `github/<owner>/_/<kind>`
- repo-scoped reads/writes: `github/<owner>/<repo>/<kind>`
- flexible search: repo, owner, or global scope depending on arguments

Repo-scoped mutations with missing owner or repo remain unmapped.

One intentional Vinctor/Hermes difference remains: GitHub PR merge maps to
`execute:github/<owner>/<repo>/pr`, not the `deploy` verb. This preserves the
Hermes plugin's current taxonomy decision that deployment/release verbs stay in
the `execute:...` convention until Vinctor changes that cross-repo.

## Slack

The Slack classifier mirrors the Claude hook's reference Slack and korotovsky
tool tables:

- workspace reads map to `read:message/slack`
- channel reads map to `read:message/slack/<channel>` when a channel is present,
  otherwise `read:message/slack`
- message sends and reactions map to `send:message/slack/<channel>`
- search maps to the target channel when supplied, otherwise the workspace

Send tools without a channel remain unmapped. The boundary must not authorize an
ambiguous outbound message target.

## Tests

The MCP parity test suite covers:

- filesystem table rows and edge behavior
- GitHub read, mutation, workflow, secret, and method-specific mappings
- Slack workspace, channel, search, send, and ambiguous-send behavior
- `mcp__server__tool` separator compatibility

Existing v0.2 broad tests continue to assert the narrower examples.

## Non-Goals

- Runtime MCP schema discovery.
- Generic classification of all possible MCP servers.
- MCP server connection management.
- Tool argument inspection beyond the known server tables.
