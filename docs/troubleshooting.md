# Troubleshooting

The plugin returns either:

- `None`, meaning Hermes continues its normal path.
- `{"action": "block", "message": "Denied by Vinctor authorization: <code>."}`,
  meaning Hermes should not execute the tool.

## Block Codes

| Code | Meaning |
| --- | --- |
| `action_denied` | Vinctor service denied the mapped action. |
| `missing_auth_env` | A mapped call was found, but endpoint, agent key, or grant ref is missing. |
| `service_unavailable` | `/v1/enforce` could not be reached, timed out, or returned an unexpected status. |
| `invalid_config` | The configured mapping file could not be parsed or failed schema validation. |
| `parse_unsafe` | A mapped input contained unsafe data (such as a null byte), or a recognized consequential command could not be resolved to a concrete target from the input alone (for example `git push origin`, `gh pr merge` without `--repo`, a multi-target `rm`). The plugin never enforces over a guessed resource. |
| `malformed_payload` | A known mapped tool did not include the required argument shape. |
| `unmapped_tool` | Strict unmapped blocking is enabled and no mapping matched the tool call. |

Only `action_denied` is a policy decision. The rest are local fail-closed
outcomes.

## Fast Checks

| Symptom | Check |
| --- | --- |
| A mapped call blocks with `missing_auth_env` | Confirm `VINCTOR_ENDPOINT`, `VINCTOR_AGENT_KEY`, and `VINCTOR_GRANT_REF` are set in the Hermes runtime environment. |
| A mapped call blocks with `service_unavailable` | Confirm the endpoint is reachable from the Hermes process and that `/v1/enforce` responds within `VINCTOR_HERMES_TIMEOUT_MS`. |
| Every call blocks with `invalid_config` | Run `vinctor-hermes-plugin validate "$VINCTOR_HERMES_PLUGIN_CONFIG" --json`. |
| A tool unexpectedly defers to Hermes | Run `explain` on a captured event and add an operator rule if the result is `unmapped`. |
| A secret path maps differently than expected | Check the sensitive-path table in `docs/configuration.md`. |
| Service audit lacks boundary context | Confirm optional `VINCTOR_BOUNDARY_ID` is set in the Hermes runtime environment. |
| A real Hermes tool appears to bypass Vinctor | Enable `VINCTOR_HERMES_COVERAGE_LOG` and compare the intended tool invocation list against the coverage log. If the tool executed with no `pre_tool_call` row, it is outside this boundary. |

Set `VINCTOR_HERMES_DEBUG=1` for local CLI diagnostics when `explain` fails to
load config. The debug output is operator-facing stderr only; it is not returned
through the Hermes block directive.

## Why a Tool Was Unmapped

Run:

```bash
vinctor-hermes-plugin explain /tmp/hermes-event.json --json
```

If the result is `{"status": "unmapped"}`, add an operator rule or wait for a
built-in classifier to cover that Hermes tool.

`explain` does not call Vinctor. It only shows the local mapping result.

## Non-Disclosure

The plugin's block message is intentionally terse. It does not include grant
references, raw tool arguments, matched scope, or audit event ids. Use the
Vinctor service audit for operator-side debugging.

The service audit is the right place to inspect the permitted or denied
`(action, resource)` pair. The model-facing block directive intentionally omits
those details.
