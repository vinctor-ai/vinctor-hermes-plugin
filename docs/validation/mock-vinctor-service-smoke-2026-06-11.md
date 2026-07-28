# Mock Vinctor Service Smoke Validation

Date: 2026-06-11
Issue: https://github.com/pkachuc/vinctor-hermes-plugin/issues/1

## Scope

Hermes plugin smoke tests now exercise the shared mock Vinctor service from
`vinctor-core/tools/mock_vinctor_service.py` when that repository is available
locally.

Covered behavior:

- permit response allows a mapped action
- deny response blocks a mapped action
- invalid `X-Agent-Key` fails closed
- strict `/v1/enforce` body is accepted by the mock
- optional `X-Vinctor-Boundary-Id` is forwarded as a header
- unavailable mock mode fails closed
- unreachable endpoint fails closed

The tests skip socket-bound cases when the local sandbox does not permit binding
to `127.0.0.1`. They run normally when executed with local socket permission.

## Latest Result

Command:

```bash
VINCTOR_CORE_PATH=../vinctor-core PYTHONPATH=src python -m unittest tests.test_mock_vinctor_service_smoke -q
```

Result:

```text
Ran 6 tests in 2.543s

OK
```

## Contract Note

The shared local mock returns `{"decision":"permit"}` without
`audit_event_id`. `EnforceClient` therefore requires an explicit permit decision
but treats `audit_event_id` as optional response metadata. The strict request
body remains exactly `grant_ref`, `action`, and `resource`.
