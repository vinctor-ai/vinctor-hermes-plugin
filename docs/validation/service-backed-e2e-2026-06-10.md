# Service-Backed E2E Validation

Command:

```bash
python scripts/service_backed_e2e.py
```

Expected behavior:

- `terminal` command `npm test` maps to `execute:ci/test`.
- Local contract service permits `execute:ci/test`; Hermes receives no block
  directive.
- `terminal` command `vercel deploy --prod` maps to
  `execute:deploy/production`.
- Local contract service denies `execute:deploy/production`; Hermes receives a
  safe block directive.
- Unreachable service fails closed with `service_unavailable`.
- The service records one permit audit event and one deny audit event.

The validation service implements only the strict `/v1/enforce` contract needed
for the adapter proof. It does not issue grants or replace the Vinctor service.

## Latest Result

Run on 2026-06-10:

```text
ALL VINCTOR HERMES PLUGIN SERVICE E2E STEPS PASSED
```

Re-run after the v0.2 coverage iteration on 2026-06-10:

```text
ALL VINCTOR HERMES PLUGIN SERVICE E2E STEPS PASSED
```

Re-run after the v0.2.1 MCP parity iteration on 2026-06-10:

```text
ALL VINCTOR HERMES PLUGIN SERVICE E2E STEPS PASSED
```

Re-run after the v0.3.0 MCP registry iteration on 2026-06-10:

```text
ALL VINCTOR HERMES PLUGIN SERVICE E2E STEPS PASSED
```

Re-run after the v0.3.1 dogfood hardening iteration on 2026-06-10:

```text
ALL VINCTOR HERMES PLUGIN SERVICE E2E STEPS PASSED
```

Re-run after the v0.3.2 Claude-hook review follow-up on 2026-06-10:

```text
ALL VINCTOR HERMES PLUGIN SERVICE E2E STEPS PASSED
```
