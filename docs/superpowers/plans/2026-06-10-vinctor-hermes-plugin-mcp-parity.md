# Vinctor Hermes Plugin MCP Parity Plan

Date: 2026-06-10
Status: Implemented

## Task 1: Compare MCP Coverage

Use the Claude hook MCP classifiers as the source of parity:

- `src/classifiers/mcp/filesystem.ts`
- `src/classifiers/mcp/github.ts`
- `src/classifiers/mcp/slack.ts`

Identify differences caused by Hermes naming and Hermes resource taxonomy.

## Task 2: Add Red Tests

Add `tests/test_mcp_parity.py` covering:

- filesystem table rows
- multi-path sensitive file handling
- GitHub global, owner, repo, flex, workflow, secret, and mutation mappings
- Slack workspace, channel, search, send, and ambiguous-send mappings
- `mcp__server__tool` compatibility

Verify red:

```bash
PYTHONPATH=src python3 -m unittest tests.test_mcp_parity -q
```

## Task 3: Implement Classifier

Add `src/vinctor_hermes_plugin/mcp.py` with:

- MCP name splitter
- filesystem classifier
- GitHub table classifier
- Slack table classifier

Update `mapping.py` to dispatch to the MCP module.

## Task 4: Update Docs

Update README, taxonomy, roadmap, and friction log to describe the MCP parity
scope and deferred runtime schema discovery.

## Task 5: Verify

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPYCACHEPREFIX=/private/tmp/vinctor-hermes-plugin-pycache python3 -m compileall -q src scripts tests
python3 scripts/service_backed_e2e.py
git diff --check
```

Run a claim-safety scan for prohibited vendor-support phrasing.
