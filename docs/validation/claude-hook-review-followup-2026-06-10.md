# Claude Hook Review Follow-Up

Date: 2026-06-10
Scope: Vinctor Hermes Plugin v0.3.2
Reviewer baseline: `vinctor-claude-code-hook`

## Accepted And Implemented

- Split invariant ratchets:
  - `tests/test_enforce_body_strict.py`
  - `tests/test_reason_templates.py`
  - existing non-disclosure tests remain in place
- Collapsed service deny details to the fixed model-facing
  `action_denied` template.
- Added CLI `--help` and unknown-subcommand tests.
- Added `VINCTOR_HERMES_DEBUG=1` local config-path diagnostics for `explain`.
- Added `scripts/claim_safety_scan.py` and tests.
- Added `CONTRIBUTING.md` with quality gates and test-design-review process.
- Added GitHub Actions CI for unit tests, compile, ruff, claim-safety scan, and
  service-backed E2E.
- Kept `plugin.yaml`, package version, and CLI version aligned at v0.3.2.
- Ran an adversarial cold-start review and addressed its local/documentation
  findings:
  - added `scripts/plugin_load_smoke.py`
  - expanded claim-safety scanning for sandboxing, hosted-service, and raw
    interception claims
  - corrected preflight `explain --json` expected field from `kind` to `status`
  - replaced README absolute local links with repository-relative links

## Already Addressed Before This Follow-Up

- Service-backed E2E existed and passed.
- GitHub remote push had already completed.
- MCP filesystem, GitHub, and Slack coverage matched the practical Claude-hook
  coverage target.
- `plugin.yaml` version drift had already been covered by a regression test in
  v0.3.1.

## Deferred

- Real Hermes install/load/block smoke still requires a target Hermes runtime.
- Real Vinctor service grant lifecycle tests still require the service/core
  engine.
- A fresh adversarial cold-start dogfood pass should run once those two
  dependencies exist.
