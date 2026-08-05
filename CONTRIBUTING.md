# Contributing

This repository is a Boundary Preview adapter. Keep changes scoped to the
Hermes `pre_tool_call` authorization boundary and its operator tooling.

## Quality Gates

Before committing:

```bash
PYTHONPATH=src python -m unittest discover -s tests -q
PYTHONPYCACHEPREFIX=/tmp/vinctor-hermes-plugin-pycache python -m compileall -q src scripts tests
python -m ruff check .
PYTHONPATH=src python scripts/plugin_load_smoke.py
VINCTOR_CORE_PATH=../vinctor-core PYTHONPATH=src python -m unittest tests.test_mock_vinctor_service_smoke -q
python scripts/claim_safety_scan.py
PYTHONPATH=src python scripts/service_backed_e2e.py
git diff --check
```

If `ruff` is missing locally, install development dependencies first:

```bash
python -m pip install -e ".[dev]"
```

## Test Design Review

For non-trivial feature or behavior changes, add or update a written plan before
implementation. Before committing that plan, request a test-design review that
checks only:

- missing regression coverage
- weak assertions
- redundant test cases
- stale file references
- claim-safety and non-disclosure invariants

Fold the review into the plan before implementing.

## Invariant Ratchets

Keep these tests independent so failures identify the broken guarantee:

- `tests/test_enforce_body_strict.py` - strict `/v1/enforce` body and
  `X-Agent-Key`
- `tests/test_reason_templates.py` - fixed model-facing block messages
- `tests/test_non_disclosure.py` and `tests/test_non_disclosure_matrix.py` -
  no grant ref, raw tool input, audit id, or mapped scope in model-facing output
- `tests/test_claim_safety_scan.py` - prohibited public claims stay out of docs

Do not weaken these tests to make implementation easier.

## Claim Safety

Run `python scripts/claim_safety_scan.py` before publishing changes. The docs
may say what this repository is not, but they must not claim vendor endorsement,
native runtime status, or operational readiness beyond Boundary Preview.
