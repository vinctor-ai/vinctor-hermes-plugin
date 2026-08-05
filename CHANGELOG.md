# Changelog

Notable changes to `vinctor-hermes-plugin`. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file was adopted at `0.6.0`. Earlier releases are listed by version and
date only and are not reconstructed change-by-change; their notes live in the
release PRs.

## [0.6.0] - 2026-08-06

**Upgrade if you set `VINCTOR_HERMES_UNMAPPED_POLICY`.** On `0.5.0` a near miss
on that variable — `Block`, `BLOCK`, `true`, `1`, `yes`, `on` — silently left
the boundary on its permissive default, with no diagnostic anywhere. `doctor`,
the command whose whole job is reporting what is in effect, did not mention the
policy at all, so an operator who set `Block` and then checked their work got a
clean report.

The second fix closes one missed spelling in path refusal: a bare `..` escaped
the escape check and was emitted as the resource `repo/..`, a string naming the
parent of the tree while textually sitting inside it — so a scope granted on the
tree matched it, and an audit query for the real target found nothing.

This release requires no config change. Read "What breaks" — one change turns
previously-allowed calls into unconditional blocks.

### ⚠️ What breaks

- **A bare `..` is now refused, and that refusal blocks unconditionally.** Three
  spellings slipped through: `..`, `/..`, and `/a/../..`. `normalize_path` folds
  through `posixpath.normpath` and then refused anything starting with `../` —
  which misses the case where the escape *is* the whole result, because
  `normpath` returns a bare `".."` with no trailing slash.

  | path | before | after |
  |---|---|---|
  | `..` | `repo/..` | refused |
  | `/..` | `fs/..` | refused |
  | `/a/../..` | `fs/..` | refused |

  The third is why the check must run *after* the fold: `/a/../..` carries no
  leading `..` at all and only escapes once folded.

  A path refusal routes through `kind="error"` / `parse_unsafe`, which blocks
  **unconditionally** — it is not `kind="unmapped"` and is therefore not subject
  to `VINCTOR_HERMES_UNMAPPED_POLICY`. So a call that previously mapped to
  `repo/..` and was permitted by a tree-scoped grant now fails, and setting the
  unmapped policy to `defer` will not restore it.

### Added

- **A startup warning when `VINCTOR_HERMES_UNMAPPED_POLICY` holds a value the
  plugin does not recognize.** Written to stderr once at construction — once
  rather than per call so a busy boundary cannot bury it, and stderr because
  stdout is the plugin's data channel. `true`/`1`/`yes`/`on` are not arbitrary
  typos: they are exactly what every *other* environment variable in this plugin
  accepts, so an operator generalising from those lands here and gets the
  permissive default while believing they hardened the boundary.

  An unset or **empty** value stays silent, because empty is how most shell
  templating and container tooling renders an unset variable (`FOO=${BAR}`), and
  a warning that fires on ordinary deployments is one operators learn to skip.
- **`doctor` reports the effective unmapped policy**, in two new fields:
  `unmapped_policy` (the policy actually in force — `"block"` or `"defer"`, not
  the raw string you set) and `unmapped_policy_warning` (the diagnostic, or
  `null`). Both are reported on the invalid-config path too: the policy is a
  property of the environment, and a broken config is exactly when you most want
  to know what the boundary will do.

  A misspelling does **not** make `doctor` exit non-zero. This is an optional
  policy, and failing the command would break CI pipelines gating on it for a
  setting that was never required.

### Unchanged, deliberately

- **Matching is still exact: only the literal `block` blocks.** The warning does
  not widen what counts as blocking — `Block` still does not block. A typo must
  never silently turn enforcement on *or* off, and warning is how you find out
  which one you have. If you set `Block`, the fix is to set `block`; the warning
  tells you so and `doctor` shows you the result.

### Known limits

- Canon path vectors are **mirrored** from `vinctor-conformance` #17, not
  vendored: provenance must name a commit reachable from that repository's
  `main`, and #17 is still open. Vendoring is a follow-up.
