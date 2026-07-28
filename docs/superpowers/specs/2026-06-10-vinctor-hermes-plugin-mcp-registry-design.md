# Vinctor Hermes Plugin MCP Registry Design

Date: 2026-06-10
Status: Implemented

## Goal

Reduce friction for Hermes deployments with custom MCP servers without turning
the plugin into a generic MCP security framework.

The plugin can now read an exported Hermes/MCP tool registry and infer explicit
operator config rules for MCP tools that are not covered by the built-in tables.
The result is still ordinary Vinctor mapping config: `(tool, matchType, pattern,
action, resource)`.

## Runtime Contract

Optional environment variable:

- `VINCTOR_HERMES_MCP_REGISTRY` - path to a JSON file containing MCP tool
  entries discovered from the Hermes runtime.

When set, the boundary loads normal operator config first, then appends inferred
MCP rules from the registry. Explicit operator rules win because they are loaded
first.

Invalid or unreadable registry JSON is treated like invalid config and fails
closed.

## Registry Input

The parser accepts either:

```json
{
  "tools": [
    { "name": "mcp_notion_create_page", "description": "Create a page" }
  ]
}
```

or a top-level array of tool entries.

Tool names may be in either form:

- Hermes-style: `mcp_<server>_<tool>`
- fixture-compatible: `mcp__<server>__<tool>`

## Inference

The inference layer is intentionally conservative:

- known built-in filesystem/GitHub/Slack tools are reported as built-in and do
  not generate duplicate rules
- unknown MCP tools generate exact-match rules only when their tool name or
  description contains a recognizable action verb
- tools that cannot be inferred are skipped and reported

Generated resources use:

```text
mcp/<server>/<tool>
```

## CLI

New offline command:

```bash
vinctor-hermes-plugin draft-mcp-config hermes-mcp-tools.json --json
```

This prints:

- a config object containing generated exact-match rules
- generated rule count
- known built-in tool names
- skipped tool names with reasons

`explain` also accepts `--mcp-registry`, and otherwise reads
`VINCTOR_HERMES_MCP_REGISTRY`.

## Non-Goals

- connecting to MCP servers
- inspecting live OAuth/session state
- approving unknown MCP tools automatically
- generating grants
- extending `/v1/enforce`
- replacing operator review
