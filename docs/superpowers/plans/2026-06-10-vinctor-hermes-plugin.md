# Vinctor Hermes Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Boundary Preview Hermes plugin that authorizes configured tool calls through Vinctor before execution.

**Architecture:** The package is a Python plugin with one primary `pre_tool_call` boundary. The boundary maps Hermes-style tool calls to Vinctor v1 `(action, resource)`, calls `/v1/enforce`, and returns a safe Hermes block directive only when execution must not proceed.

**Tech Stack:** Python 3.11, standard library HTTP client, unittest, ruff.

---

## File Structure

- `src/vinctor_hermes_plugin/types.py` defines shared dataclasses and action literals.
- `src/vinctor_hermes_plugin/config.py` loads and validates optional mapping config.
- `src/vinctor_hermes_plugin/mapping.py` resolves tool calls to action/resource.
- `src/vinctor_hermes_plugin/enforce.py` calls strict Vinctor `/v1/enforce`.
- `src/vinctor_hermes_plugin/boundary.py` implements fail-closed `pre_tool_call`.
- `src/vinctor_hermes_plugin/plugin.py` registers with Hermes.
- `src/vinctor_hermes_plugin/cli.py` implements `validate` and `explain`.
- `tests/` verifies behavior with fake Hermes context and local HTTP services.
- `scripts/service_backed_e2e.py` runs the end-to-end contract proof.

### Task 1: Mapping Contract

**Files:**
- Test: `tests/test_mapping.py`
- Create: `src/vinctor_hermes_plugin/types.py`
- Create: `src/vinctor_hermes_plugin/config.py`
- Create: `src/vinctor_hermes_plugin/mapping.py`

- [ ] Write failing tests for `write_file`, branch creation, test/build/deploy/release commands, memory, session search, operator config, and unmapped calls.
- [ ] Run `python -m unittest tests.test_mapping -q` and confirm failures are missing imports.
- [ ] Implement minimal mapping/config/types code.
- [ ] Run `python -m unittest tests.test_mapping -q` and confirm pass.

### Task 2: Enforce Client

**Files:**
- Test: `tests/test_enforce.py`
- Create: `src/vinctor_hermes_plugin/enforce.py`

- [ ] Write failing HTTP contract tests for permit, deny, strict body, timeout/unavailable.
- [ ] Run `python -m unittest tests.test_enforce -q` and confirm failures are missing implementation.
- [ ] Implement the standard-library enforce client.
- [ ] Run `python -m unittest tests.test_enforce -q` and confirm pass.

### Task 3: Boundary Behavior

**Files:**
- Test: `tests/test_boundary.py`
- Create: `src/vinctor_hermes_plugin/boundary.py`

- [ ] Write failing tests for permit returns `None`, deny blocks, missing auth blocks, service failure blocks, invalid config blocks, and unmapped returns `None`.
- [ ] Run `python -m unittest tests.test_boundary -q` and confirm failures are missing implementation.
- [ ] Implement `VinctorHermesBoundary.pre_tool_call`.
- [ ] Run `python -m unittest tests.test_boundary -q` and confirm pass.

### Task 4: Plugin Registration and CLI

**Files:**
- Test: `tests/test_plugin.py`
- Test: `tests/test_cli.py`
- Create: `src/vinctor_hermes_plugin/plugin.py`
- Create: `src/vinctor_hermes_plugin/cli.py`
- Create: `src/vinctor_hermes_plugin/__init__.py`

- [ ] Write failing tests for `register(ctx)`, `validate`, and `explain`.
- [ ] Run `python -m unittest tests.test_plugin tests.test_cli -q` and confirm failures are missing implementation.
- [ ] Implement plugin registration and CLI.
- [ ] Run `python -m unittest tests.test_plugin tests.test_cli -q` and confirm pass.

### Task 5: Non-Disclosure and E2E

**Files:**
- Test: `tests/test_non_disclosure.py`
- Test: `tests/test_service_e2e.py`
- Create: `scripts/service_backed_e2e.py`
- Create: `docs/validation/service-backed-e2e-2026-06-10.md`

- [ ] Write failing tests proving block output does not disclose `grant_ref`, raw args, audit event id, or mapped scope.
- [ ] Write failing service-backed tests proving permit, deny, fail-closed, and audit records.
- [ ] Run `python -m unittest tests.test_non_disclosure tests.test_service_e2e -q` and confirm failures.
- [ ] Implement the service-backed harness and validation note.
- [ ] Run `python -m unittest tests.test_non_disclosure tests.test_service_e2e -q` and confirm pass.

### Task 6: Whole-Repo Verification

**Files:**
- Modify: `README.md`
- Modify: `ROADMAP.md`

- [ ] Run `PYTHONPATH=src python -m unittest discover -s tests`.
- [ ] Run `python -m ruff check .`.
- [ ] Run `python scripts/service_backed_e2e.py`.
- [ ] Run a claim-safety scan for prohibited wording.
- [ ] Run `git diff --check`.
- [ ] Update docs if verification changes the operator path.
