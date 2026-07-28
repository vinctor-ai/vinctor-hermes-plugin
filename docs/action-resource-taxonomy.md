# Action / Resource Taxonomy

The plugin uses the existing Vinctor v1 verbs:

`read`, `write`, `execute`, `deploy`, `delete`, `send`

Classification follows the cross-runtime Vinctor Action Taxonomy canon
(vinctor-conformance): verbs are assigned by effect, context-free, and when
several verbs plausibly apply the highest-precedence one wins
(`delete > deploy > execute > send > write > read`). Resources are
domain-keyed hierarchical path prefixes; `.`/`..` never become path segments.
The vendored conformance fixtures under `tests/conformance/` pin the plugin
to the canon fixture-for-fixture.

## Built-In Mappings

| Hermes-style surface | Action | Resource |
| --- | --- | --- |
| `read_file`, file search/list tools | `read` | `repo/<path>` (in-tree), `fs/<path>` (absolute), or `secret/<kind>` |
| `write_file`, `edit_file`, `create_directory`, `move_file` | `write` | `repo/<path>` / `fs/<path>` or `secret/<kind>` |
| `patch` update/add path | `write` | `repo/<path>` / `fs/<path>` or `secret/<kind>` |
| `patch` delete header, delete file tools (`remove_directory` alias included), single-target `rm`/`rmdir` | `delete` | `repo/<path>` / `fs/<path>` or `secret/<kind>` |
| multi-target or shell-expandable `rm` targets | fail closed | (`parse_unsafe`; never a guessed resource) |
| `git status` / `log` / `diff` / `show`; `git fetch <explicit-standard-url-or-path>` | `read` | `shell/git` |
| `git add` / `commit` / `stash` / `clone`; `git pull <explicit-standard-url-or-path>` | `write` | `shell/git` |
| default/named-remote `git fetch` / `pull` | fail closed | repository config can bind the remote to an executable helper |
| `git switch -c <branch>` / `git checkout -b <branch>` | `write` | `repo/branch/<branch>` |
| `git push <github-url>` | `write` | `github/<owner>/<repo>/contents` |
| `git push --force <github-url>` (force destroys remote ref history) | `delete` | `github/<owner>/<repo>/contents` |
| forced `git push <bare-remote-name>` | `delete` | `shell/git` (target repo is not resolvable context-free) |
| non-force `git push <bare-remote-name>` | fail closed | (`parse_unsafe`; the target is not resolvable context-free) |
| `git reset --hard` / `git branch -D` / `git clean -f...` | `delete` | `shell/git` |
| pipe to shell (`curl ... \| sh`, also `bash`/`zsh`/`dash`) | `execute` | `shell/<first-token>` |
| `npm`/`pnpm`/`yarn` `test`/`run`/`install`/`ci` | `execute` | `shell/<tool>` |
| `npx <package>` | `execute` | `shell/npx` |
| `npm publish --workspace <name>` | `deploy` | `pkg/npm/<name>` |
| bare `npm`/`pnpm`/`yarn publish` (name lives in package.json; no cwd in the event) | `deploy` | `pkg/npm/_` |
| `pytest`, `go test`, `cargo test`, `python -m pytest` | `execute` | `ci/test` |
| `go build`, `cargo build`, bare `<pm> build` | `execute` | `ci/build` |
| `docker build -t <ref>` / `docker run <ref>` | `execute` | `container/<registry>/<image>` |
| `docker push <ref>` | `deploy` | `container/<registry>/<image>` |
| `docker rmi <ref>` / `docker image rm <ref>` | `delete` | `container/<registry>/<image>` |
| `gh pr merge --repo <o>/<r>` (the deploy moment is the merge) | `deploy` | `github/<o>/<r>/pr` |
| `gh release create --repo <o>/<r>` | `deploy` | `github/<o>/<r>/release` |
| `gh pr create --repo <o>/<r>` | `write` | `github/<o>/<r>/pr` |
| `gh secret set --repo <o>/<r>` | `write` | `github/<o>/<r>/secret` |
| `gh workflow run`/`rerun` `--repo <o>/<r>` | `execute` | `github/<o>/<r>/workflow` |
| `gh workflow cancel --repo <o>/<r>` (mutates run state; dispatches nothing) | `write` | `github/<o>/<r>/workflow` |
| `gh` subcommands above without `--repo` | fail closed | (`parse_unsafe`) |
| `vercel [deploy]` / `fly deploy` / `railway up` | `deploy` | `<platform>/app` |
| `kubectl apply` / `terraform apply` / `helm install`/`upgrade` | `execute` | `infra/{k8s,terraform,helm}/apply` |
| other deployment commands | `execute` | `deploy/{production,staging,unknown}` |
| `cat .env*` / `printenv` | `read` | `secret/env` |
| `process` read actions | `read` | `process/<id>` or `process/list` |
| `process` stdin actions | `write` | `process/<id>` |
| `process` kill/close actions | `delete` | `process/<id>` |
| `execute_code` | `execute` | `code/python` |
| `memory` add/replace/remove | `write` / `delete` | `memory/<scope>` |
| `memory_search`, `recall_memory`, `search_memory` | `read` | `memory/search` |
| `session_search`, `search_sessions` | `read` | `session/search` |
| `cronjob` create/update/pause/resume | `write` | `cron/job/<id-or-new>` |
| `cronjob` remove | `delete` | `cron/job/<id>` |
| `cronjob` run | `execute` | `cron/job/<id>` |
| `delegate_task` | `execute` | `agent/delegate` |
| `web_search` | `send` | `web/search` |
| `web_extract`, browser navigation | `send` | `net/<internal-or-external>/<host>` |
| browser read/action/CDP tools | `read` / `execute` | `browser/page`, `browser/action`, `browser/cdp` |
| `send_message` | `send` | `message/<target>` |
| MCP filesystem known table | `read` / `write` / `delete` | `repo/<path>`, `fs/<path>`, `secret/<kind>`, or `fs/_allowed-dirs` |
| MCP GitHub known table | `read` / `write` / `execute` / `deploy` / `delete` | `github/<owner>/<repo>/<kind>` (canon kinds: `pr`, `issue`, `workflow`, `release`, `contents`, `secret`) or `github/_/<kind>` |
| MCP Slack known table | `read` / `send` | `chat/slack` or `chat/slack/<channel>` |

## Multi-Effect Operations

A compound operation causes more than one effect, and each is a separate
authorization question. The mapping carries the whole required set and the
boundary asks for every member; one denial denies the call.

| Operation | Required set |
| --- | --- |
| `move_file` (both spellings) | destination `write` + source `read` + source `delete` |
| `read_multiple_files` (both spellings) | one `read` per DISTINCT member resource |
| `patch` envelope | one pair per DISTINCT target, `write` or `delete` per header |
| MCP `fork_repository` | source `fork` write + source `contents` read + destination namespace `write` |

The bare Hermes names and the `mcp__filesystem__*` spellings resolve through one
implementation, so a fix cannot land on one surface and miss the other
(PKA-156). One deliberate difference survives, and it is not confined to which
pair is reported: the PRIMARY is a member of the required set, so choosing a
different primary changes the set. For a move with a credential-shaped source
the MCP surface keeps the source as primary and the native surface keeps the
destination, and the two required sets differ by exactly that member:

```
move_file {"source": "<decoy>/.env", "destination": "/tmp/x"}
  native: {write fs/tmp/x, read secret/env, delete secret/env}                    (3)
  mcp   : {write secret/env, read secret/env, delete secret/env, write fs/tmp/x}  (4)
```

Both primaries are pinned by vinctor-conformance (`move-file-secret-source` and
`hermes-move-file-secret-source`), which preserves each surface's historical
primary so existing grants keep working. What holds is narrower than "identical"
and still worth stating:

- The MCP set is a strict SUPERSET of the native set, so the MCP surface is
  never the weaker of the two.
- `move_file` with a credential-shaped source is the only case where they differ
  at all. Every other operation, on every argument shape, resolves to the same
  verdict, the same primary and the same set on both spellings.
- The exception is enumerated per case in `MOVE_CASES`
  (`tests/test_surface_parity.py`) as data, so it is a list a reader can count
  rather than a blanket excuse, and widening it is a visible edit.
- The assertion is `required_set(mcp) == required_set(native) | {extra}` - an
  exact equality, not a subset check. A requirement going MISSING on the MCP
  side fails it exactly as loudly as one appearing, so the carve-out cannot hide
  a narrowing.

An endpoint or member the resource mapper cannot express voids the WHOLE call
with `parse_unsafe` on both surfaces: charging the expressible subset would
authorize a call that still touches the inexpressible one.

## Operator Config

Operator config can add or override mappings. Config does not grant access; it
only controls how a tool call is translated before `/v1/enforce`.

An operator rule may ADD a charge; it may never SUBTRACT an effect. A rule that
matches a multi-effect operation is unioned with the classifier's full required
set (primary included, minus the rule's own pair), and a classifier refusal is
not overridable. See `docs/configuration.md` for the operator-facing statement.

Unmapped calls return no block directive and defer to Hermes.

Unknown dynamic MCP tools are intentionally unmapped until the operator maps
them or the built-in classifier knows their server/tool semantics.

Recognized consequential commands whose concrete target cannot be resolved
from the input alone (a bare `git push` remote, `gh` mutations without
`--repo`, multi-target deletes) fail closed with `parse_unsafe` instead of
enforcing over a guessed resource.

GitHub PR merge maps to `deploy:github/<owner>/<repo>/pr`: per the canon, the
merge is the moment a change becomes the shipping baseline, so it takes the
`deploy` verb by precedence (`create_pull_request_review` and other PR
mutations stay `write`).
