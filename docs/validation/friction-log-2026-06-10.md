# Friction Log

## Runtime Naming

Hermes uses both "hooks" and "middleware", but the extension artifact is a
plugin. The repo/package uses `vinctor-hermes-plugin`; docs say
`pre_tool_call` authorization boundary.

## Local Test Environment

The default macOS system Python in this sandbox did not have `pytest` or `ruff`.
The test suite was written with standard-library `unittest` so it can run
without installing test dependencies.

## Local HTTP Smoke

The sandbox blocks binding to `127.0.0.1` without elevated permission. Unit tests
avoid local sockets by injecting the HTTP opener. The service-backed smoke script
still uses a real local HTTP server and was run with approved escalation.

## Python Bytecode Cache

`compileall` tried to write bytecode under the user Library cache and was blocked
by sandbox permissions. Setting `PYTHONPYCACHEPREFIX=/private/tmp/...` made the
compile check pass.

## Future Product Decision

Deployment remains `execute:deploy/...` for v0.2.0. Moving to `deploy:...`
should be a cross-repo Vinctor taxonomy decision.

## Dynamic Hermes Tools

Hermes can register static core tools, plugin tools, and dynamic MCP tools. The
v0.2.1 classifier now mirrors the Claude hook's filesystem, GitHub, and Slack
MCP tool tables for known tools. v0.3.0 adds offline registry-based config
drafting for unknown MCP tools, but live MCP server polling is still deferred.
