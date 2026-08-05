# Scripts

Maintenance and validation scripts for the Vinctor Hermes plugin.

| Script | Purpose |
| --- | --- |
| `plugin_load_smoke.py` | Confirms `register` attaches exactly one `pre_tool_call` hook. |
| `service_backed_e2e.py` | Drives a permit, a deny, and a fail-closed call against a local contract service. |
| `claim_safety_scan.py` | Fails if prohibited over-claims appear in docs/source. |
| `coverage_harness.py` | Reproducible coverage-measurement harness (see below). |

## Coverage harness

`coverage_harness.py` drives the main Hermes tool families through the plugin's
real `pre_tool_call` boundary and reports, per family:

- whether the call reached `pre_tool_call`,
- mapping status (`mapped` / `unmapped` / `error`),
- the enforced `action:resource`,
- whether the call was blocked and the public block reason,
- the runtime-traversal status.

The harness uses an offline stub enforce function, so it runs without a Vinctor
service. The mapping, enforce branch, and block decision it reports come from the
plugin's real code paths, not from a mock of them.

### Two kinds of coverage (claim discipline)

The harness deliberately separates two claims that are easy to conflate:

- **Mapping coverage** — given a tool event that already reached the plugin, can
  the plugin classify and enforce it? This is what the harness measures by
  default. The default `synthetic` mode synthesizes the `pre_tool_call` event
  itself, so it proves mapping/enforce behavior and nothing about real runtime
  routing.
- **Runtime boundary coverage** — does a versioned Hermes runtime actually route
  the family through `pre_tool_call` before execution? This is `unmeasured` in
  synthetic mode. It can only be measured on a real runtime (see the runbook).

In synthetic mode every row's `Runtime traversal` column reads
`unmeasured (synthetic)`. Do not read a `mapped` row as runtime coverage.

### Run it

```bash
# Default: permit all mapped calls, defer unmapped, human-readable table.
PYTHONPATH=src python scripts/coverage_harness.py

# Markdown table (paste into the coverage matrix doc) or machine-readable JSON.
PYTHONPATH=src python scripts/coverage_harness.py --format markdown
PYTHONPATH=src python scripts/coverage_harness.py --json

# Exercise the deny / service-unavailable enforce branches.
PYTHONPATH=src python scripts/coverage_harness.py --enforce deny
PYTHONPATH=src python scripts/coverage_harness.py --enforce unavailable

# Strict unmapped policy: unmapped calls that reach the hook are blocked.
PYTHONPATH=src python scripts/coverage_harness.py --unmapped-policy block
```

`--enforce` chooses the stub decision for mapped calls (`permit` default, `deny`,
or `unavailable`). `--unmapped-policy block` mirrors
`VINCTOR_HERMES_UNMAPPED_POLICY=block`. `--runtime-traversal` overrides the
runtime-traversal label and should only be changed when you have actually
observed traversal on a real runtime.

## Runbook: filling the coverage matrix on a real Hermes runtime

The harness alone cannot prove runtime traversal. To measure it and fill the
[coverage matrix](../docs/validation/coverage-matrix-hermes-unmeasured-2026-06-11.md):

1. **Pin the runtime.** Record the exact Hermes runtime package/version and
   commit if available. Every measured matrix file is named for one version:
   `docs/validation/coverage-matrix-hermes-<version>-<date>.md`.
2. **Install and load the plugin** through the runtime-supported plugin path.
   Confirm `plugin.yaml` advertises `pre_tool_call` and the runtime registers
   `vinctor_hermes_plugin.plugin:register` (sanity-check locally with
   `PYTHONPATH=src python scripts/plugin_load_smoke.py`).
3. **Enable the coverage probe log** in the Hermes process:

   ```bash
   export VINCTOR_HERMES_COVERAGE_LOG=/tmp/vinctor-hermes-coverage.jsonl
   export VINCTOR_HERMES_UNMAPPED_POLICY=block   # to test strict-unmapped rows
   # Optional, controlled non-sensitive fixtures only:
   export VINCTOR_HERMES_COVERAGE_LOG_INCLUDE_ARGS=1
   ```

   `VINCTOR_HERMES_COVERAGE_LOG` appends one sanitized JSON row per observed
   `pre_tool_call` entry (tool name, arg keys, args fingerprint, mapping status,
   action/resource, block result). It never records raw arg values (unless the
   `INCLUDE_ARGS` flag is set), grant refs, agent keys, or audit event ids.
4. **Drive each family** from inside the runtime using the same fixtures the
   harness uses (see `PROBES` in `coverage_harness.py`), with non-sensitive
   arguments only. Keep an explicit list of which tool calls you attempted.
5. **Reconcile attempted calls against the coverage log.** For each family:
   - a coverage row present before execution → `observed`;
   - the tool executed but no coverage row appeared → `bypassed` (outside the
     Vinctor boundary — record it as a bypass finding);
   - the probe was not run → `unmeasured`.
6. **Cross-check the mapping/enforce columns** with the harness output for the
   same families: run `coverage_harness.py --format markdown` and confirm the
   `action:resource` and block reasons match the runtime coverage-log rows.
7. **Write the measured matrix** to
   `docs/validation/coverage-matrix-hermes-<version>-<date>.md`, replacing only
   the cells you actually observed. Leave unmeasured cells marked `unmeasured`.
   Never claim a family is covered without an `observed` coverage row.
