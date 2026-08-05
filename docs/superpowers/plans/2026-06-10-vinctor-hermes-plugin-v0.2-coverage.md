# Vinctor Hermes Plugin v0.2 Coverage Plan

Date: 2026-06-10

## Goal

Bring the Hermes plugin closer to the Claude hook's breadth by expanding
built-in classification, operator tooling, documentation, and non-disclosure
ratchets while preserving the strict v1 Vinctor boundary.

## Task 1: Classifier Test Expansion

Add failing tests for:

- File read/write/delete/search mappings and sensitive path redaction.
- Terminal git, release, deploy, package publish, Docker, Kubernetes,
  Terraform, and direct delete patterns.
- Process actions.
- `execute_code`, `memory`, `session_search`, `cronjob`, `delegate_task`.
- `web_search`, `web_extract`, browser action families, and `send_message`.
- MCP filesystem and GitHub tool names using Hermes' `mcp_<server>_<tool>`
  convention.

Verification:

```bash
PYTHONPATH=src python3 -m unittest tests.test_mapping -q
```

Expected before implementation: new tests fail.

## Task 2: Mapping Implementation

Implement the smallest classifier structure that keeps the code readable:

- Add a sensitive path helper.
- Add URL/network resource classification.
- Add MCP tool parsing/classification.
- Extend terminal, file, process, browser, web, memory, cron, delegate, and
  message dispatch.

Constraints:

- Use only Python standard library.
- Keep output resources explicit and non-secret.
- Return `unmapped` for unknown MCP servers/tools unless safely classified.
- Return mapping errors for unsafe null bytes and path traversal.

Verification:

```bash
PYTHONPATH=src python3 -m unittest tests.test_mapping -q
```

## Task 3: CLI Parity

Add failing then passing tests for:

- `--version`.
- `validate --json` fields: `valid`, `errors`, `path`, `rule_count`, `note`.
- Missing config path as valid empty config with a readable note.
- `explain` loading `VINCTOR_HERMES_PLUGIN_CONFIG` by default.

Verification:

```bash
PYTHONPATH=src python3 -m unittest tests.test_cli -q
```

## Task 4: Non-Disclosure Ratchets

Add tests that block messages never disclose:

- grant refs
- agent keys
- audit event ids
- raw command/tool args
- mapped resources
- config match patterns
- service exception bodies

Cover block reasons:

- `action_denied`
- `missing_auth_env`
- `service_unavailable`
- `invalid_config`
- `parse_unsafe`
- `malformed_payload`

Verification:

```bash
PYTHONPATH=src python3 -m unittest tests.test_non_disclosure -q
```

## Task 5: Documentation

Update:

- `README.md`: broader coverage table, grant/offline evaluation flow, boundary
  caveats.
- `docs/configuration.md`: config schema, match inputs, specificity, absent vs
  invalid behavior, examples.
- `docs/troubleshooting.md`: deny-code table and operational checks.
- `docs/action-resource-taxonomy.md`: v0.2 taxonomy.
- `docs/runtime-boundary-discovery.md`: upstream Hermes surfaces.
- `ROADMAP.md`: mark v0.2 done/deferred clearly.

Add:

- `docs/validation/adoption-readiness-2026-06-10.md`.

Verification:

Run a claim-safety scan for prohibited vendor-support phrasing. The repository
should use independence/disclaimer wording without implying endorsement or
special runtime status.

## Task 6: Full Verification

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -q
PYTHONPYCACHEPREFIX=/private/tmp/vinctor-hermes-plugin-pycache python3 -m compileall -q src scripts tests
python3 scripts/service_backed_e2e.py
git diff --check
```

If `ruff` is available, run:

```bash
python3 -m ruff check .
```

Commit as one logical v0.2 coverage iteration after all checks pass.
