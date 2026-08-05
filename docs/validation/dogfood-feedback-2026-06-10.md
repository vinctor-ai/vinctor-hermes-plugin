# Dogfood Feedback

Date: 2026-06-10
Scope: Vinctor Hermes Plugin v0.3.0
Method: subagent dogfooding review with the real Vinctor core/service assumed
but not available locally.
Follow-up: v0.3.1 implemented the adapter-side hardening items called out
below. Real Hermes runtime and real Vinctor service validation remain pending.
The v0.3.2 follow-up added Claude-hook review parity gates for invariant
ratchets, CLI help/error handling, claim-safety scanning, and CI.

## Summary

The plugin now has a credible Boundary Preview shape, broad Hermes action
coverage, Claude-hook-level MCP table coverage, and a service-contract smoke
test. The largest remaining risks are no longer basic classifier coverage; they
are runtime adoption, strictness policy, and service-backed operational proof.

The main next iteration should focus on:

1. real Hermes install/load/block smoke
2. real Vinctor service grant lifecycle validation
3. live MCP schema observation for least-privilege resource extraction

## Follow-Up Status

Implemented in v0.3.1:

- `VINCTOR_HERMES_UNMAPPED_POLICY=block` for strict unmapped blocking.
- `VINCTOR_HERMES_ALLOW_MCP_REGISTRY_RUNTIME_RULES=1` gate for runtime
  registry-derived rules.
- Explicit operator config priority over registry-derived runtime rules.
- HTTP 200 responses fail closed unless `decision == "permit"` and a non-empty
  `audit_event_id` is present.
- Non-model-facing decision recorder plus `VINCTOR_HERMES_DECISION_LOG`.
- Ambiguous or negated multi-verb MCP registry tools are skipped.
- `plugin.yaml` version aligned with the package version and covered by a
  regression test.
- `docs/preflight.md` first-run checklist.

Implemented in v0.3.2:

- independent `enforce-body-strict` and `reason-templates` tests
- service deny details collapsed to the fixed `action_denied` block template
- CLI `--help`, unknown-command exit behavior, and debug config-path diagnostics
- reusable claim-safety scan
- `CONTRIBUTING.md` quality gates and CI workflow

Still pending outside the local adapter:

- real Hermes plugin loading and `pre_tool_call` block smoke
- real Vinctor service audit semantics
- expired, revoked, unknown, and wrong-scope grant cases
- live MCP schema polling and argument-specific resource extraction

## P0 / Product Decision Needed

### Unmapped Calls Currently Bypass Vinctor

`pre_tool_call` returns `None` for unmapped calls. That lets Hermes continue its
own path, but it also means no Vinctor decision and no Vinctor audit event for
unknown dynamic tools.

Evidence:

- `src/vinctor_hermes_plugin/boundary.py`
- `README.md` runtime flow and coverage sections

Recommended follow-up:

- Added `VINCTOR_HERMES_UNMAPPED_POLICY=block` in v0.3.1.
- Keep defer as the Boundary Preview default, but dogfood with `block` in
  controlled Hermes workflows.
- Document that production-like dogfood should not rely on unmapped deferral for
  high-impact tool families.

### MCP Registry Runtime Merge May Be Too Automatic

In v0.3.0, `VINCTOR_HERMES_MCP_REGISTRY` appended inferred registry rules into
the runtime boundary path. This was convenient, but it weakened the claim that
unknown MCP tools are not automatically approved. The rules still went through
Vinctor, but the mapping itself was inferred at runtime instead of materialized
and reviewed in explicit config.

Evidence:

- `src/vinctor_hermes_plugin/boundary.py`
- `src/vinctor_hermes_plugin/config.py`
- `src/vinctor_hermes_plugin/mcp_discovery.py`

Recommended follow-up:

- Split discovery from runtime use.
- Prefer `draft-mcp-config` as the operator workflow.
- Runtime registry-derived rules are now gated behind
  `VINCTOR_HERMES_ALLOW_MCP_REGISTRY_RUNTIME_RULES=1`.

## P1 / Service Contract Feedback

### Permit Handling Trusts Any HTTP 200

The client treats every HTTP 200 as permit and does not verify
`decision == "permit"`. If a malformed service response returns 200 with a deny
payload or missing fields, the adapter permits.

Evidence:

- `src/vinctor_hermes_plugin/enforce.py`

Recommended follow-up:

- Require `decision == "permit"` on 200. Done in v0.3.1.
- Require non-empty `audit_event_id` on permit responses. Done in v0.3.1.
- Add E2E fixtures for malformed 200, missing decision, 401, 429, and 5xx.

### Audit IDs Are Not Preserved Locally

The enforce client extracts `audit_event_id`, but the boundary discards the
outcome. This protects model-facing output, but gives operators no local
correlation handle.

Evidence:

- `src/vinctor_hermes_plugin/enforce.py`
- `src/vinctor_hermes_plugin/boundary.py`

Recommended follow-up:

- Add non-model-facing telemetry hook or log sink. Done in v0.3.1.
- Include decision, action, resource, and audit event id in local operator logs.
- Keep the model-facing block message unchanged.

### Grant Lifecycle Is Static Environment State

Every mapped call uses `VINCTOR_GRANT_REF`. There is no plugin-side model for
grant expiry, revocation, per-task binding, or session/run correlation.

Evidence:

- `src/vinctor_hermes_plugin/boundary.py`
- `README.md`

Recommended follow-up:

- Document the expected grant lifecycle.
- Add real-service E2E cases for expired, revoked, unknown, and wrong-scope
  grants once the Vinctor service is ready.

## P1 / Operator Adoption Feedback

### Hermes Install And Enablement Path Is Missing

Docs show editable install, but not the real Hermes enablement path. Operators
need to know whether to use the Python entry point, directory plugin,
`plugin.yaml`, or another Hermes plugin installation location.

Evidence:

- `README.md`
- `pyproject.toml`
- `plugin.yaml`

Recommended follow-up:

- Add a "Hermes install" section with package and directory-plugin paths.
- Include a verification step proving `pre_tool_call` was registered.
- Add a known-good mapped event and expected block/permit behavior.
  A local preflight checklist was added in v0.3.1; real Hermes load smoke is
  still pending.

### First-Run Preflight Is Missing

Operators need a small checklist before running real workflows.

Recommended follow-up:

- Added `docs/preflight.md` in v0.3.1 covering:
  - required env vars
  - `validate`
  - `explain` on a known event
  - expected `/v1/enforce` audit
  - expected Hermes block directive

### Plugin Version Is Inconsistent

Package and CLI report v0.3.0, but `plugin.yaml` still reported an older
version during review.

Recommended follow-up:

- Align `plugin.yaml` with package version. Done in v0.3.1.
- Add a small test or checklist to catch future drift. Done in v0.3.1.

## P1 / MCP Feedback

### Action Inference Is Fragile

Registry action inference uses verb heuristics. Multi-verb names/descriptions
can be ambiguous:

- `get_or_create_*`
- descriptions containing "cannot delete"
- tools that "post approval comment then merge"

Recommended follow-up:

- Ambiguous and negated multi-verb tools are skipped in v0.3.1.
- Add confidence metadata only if operators need richer review output.

### Generated MCP Resources Are Coarse

Unknown MCP tools map to `mcp/<server>/<tool>`, ignoring args/schema. This is
safe as an explicit draft, but coarse for least-privilege grants.

Recommended follow-up:

- Add suggested `inputField` placeholders when schema fields look like target
  identifiers.
- Add server-specific resource extractors only after observing real schemas.

### Multi-File Non-Secret Reads Still Defer

Filesystem MCP `read_multiple_files` maps only if at least one path is
sensitive. Multiple normal repo reads remain unmapped because one precise
resource is not obvious.

Recommended follow-up:

- Either map to `repo/multiple` / common-prefix resources, or document this as a
  known false-negative.

## P2 / Polish

- Add richer argparse descriptions and examples.
- Ship sample config and sample MCP registry fixtures.
- Make `validate` examples avoid falsely reassuring operators when config files
  are missing.
- Install/run `ruff` in CI or local dev dependencies.

## Verification Notes

Subagent reviews were read-only.

Observed checks:

- unit tests passed in dogfood review
- local service-backed E2E passed in dogfood review
- GitHub push completed to `pkachuc/vinctor-hermes-plugin`

Remaining unproven:

- real Hermes plugin loading
- real Hermes `pre_tool_call` blocking
- real Vinctor service decisions and audit semantics
- real grant lifecycle
