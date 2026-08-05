"""PKA-157 / PKA-159 / PKA-190 — what `.` and `..` path SEGMENTS mean.

The canon decision and its 20 vectors live in vinctor-conformance
`fixtures/path-normalization.json`. They are MIRRORED here rather than vendored:
vendoring records a provenance sha that must name a commit reachable from
vinctor-conformance `main`, and the canon PR is still open, so the only sha
available today is a PR-branch sha. Pinning one of those is what PKA-132 cost us
— the branch is deleted on merge and nobody can re-derive what the vendored
bytes were meant to be. Swapping this table for the vendored fixture is the
follow-up.

This adapter was already the closest of the three to canon: it folds through
`posixpath.normpath` and refuses `../`-escapes, and — unlike the two hooks — it
already routes a path refusal through `kind="error"` / `parse_unsafe`, which
blocks unconditionally rather than falling to the `VINCTOR_HERMES_UNMAPPED_POLICY`
escape hatch. That is canon clause 3 (a refusal is a parse failure, not a
coverage gap), and it is asserted below so it stays true.

The one gap was a bare `..`: `normpath` returns `".."` with no trailing slash, so
a check for `startswith("../")` missed it and `repo/..` was emitted raw.

Adapters binding a different prefix for in-tree paths apply the same folding and
the same refusals; only the prefix differs. This adapter uses `repo/` for
relative paths and `fs/` for absolute ones, so the table below carries the
prefix-free `normalized` form and the resource is derived per that rule.

Every credential-shaped path here is a DECOY STRING: classified, never opened.
"""

from __future__ import annotations

import pytest

from vinctor_hermes_plugin.config import Config
from vinctor_hermes_plugin.mapping import resolve_tool_call
from vinctor_hermes_plugin.resources import normalize_path, repo_or_secret_resource

EMPTY_CONFIG = Config(version=1, rules=())

# (path, normalized) — normalized is None when the adapter must REFUSE.
VECTORS: list[tuple[str, str | None]] = [
    ("/a/b", "a/b"),
    ("a/b", "a/b"),
    ("./a/b", "a/b"),
    ("/a/./b", "a/b"),
    ("/a/././b", "a/b"),
    ("/a/b/../c", "a/c"),
    ("/a/b/c/../../d", "a/d"),
    ("/a/b/../b", "a/b"),
    ("/home/u/x/../.env", "home/u/.env"),
    ("/home/u/./.ssh/id_rsa", "home/u/.ssh/id_rsa"),
    ("/a/../../etc/passwd", None),
    ("../etc/passwd", None),
    ("..", None),
    ("/..", None),
    ("/a/../..", None),
    (".", None),
    ("/", None),
    ("//", None),
    ("/a//b", "a/b"),
    ("/a/b/", "a/b"),
]

# The vectors whose folded form is a credential, and what it classifies as.
SECRETS = {
    "/home/u/x/../.env": "secret/env",
    "/home/u/./.ssh/id_rsa": "secret/ssh",
}


def test_table_exercises_both_halves_of_the_rule() -> None:
    """A fold-only or refuse-only table lets a one-sided fix look complete.

    Refusing everything is the specific failure mode this guards against: it
    passes every escape vector while breaking `./a/b`, and a boundary that
    refuses ordinary work is what drove operators onto the unmapped escape hatch
    in the first place (PKA-159).
    """
    folds = [v for v in VECTORS if v[1] is not None]
    refusals = [v for v in VECTORS if v[1] is None]
    assert len(folds) >= 8
    assert len(refusals) >= 6


@pytest.mark.parametrize(("path", "expected"), VECTORS)
def test_normalize_path(path: str, expected: str | None) -> None:
    assert normalize_path(path) == expected


@pytest.mark.parametrize(("path", "expected"), VECTORS)
def test_resource_binding(path: str, expected: str | None) -> None:
    """`repo/` for in-tree relative paths, `fs/` for absolute ones (D-4).

    The prefix differs from the canon's `fs/`-space table; the FOLD and the
    REFUSALS do not, which is what the prefix-free `normalized` column is for.
    """
    got = repo_or_secret_resource(path)
    if expected is None:
        assert got is None
        return
    if path in SECRETS:
        assert got == SECRETS[path]
        return
    prefix = "fs" if path.strip().replace("\\", "/").startswith("/") else "repo"
    assert got == f"{prefix}/{expected}"


def test_folding_runs_before_the_sensitive_path_overlay() -> None:
    """Canon clause: if the fold ran AFTER classification, `/home/u/x/../.env`
    would bind an `fs/` resource and a broad `fs/**` grant would read a
    credential."""
    assert repo_or_secret_resource("/home/u/x/../.env") == "secret/env"
    assert repo_or_secret_resource("/home/u/./.ssh/id_rsa") == "secret/ssh"


@pytest.mark.parametrize("path", [p for p, n in VECTORS if n is None])
def test_refusal_is_a_hard_block_not_the_unmapped_escape_hatch(path: str) -> None:
    """Canon clause 3, and the reason this adapter was already ahead of the hooks.

    `kind="unmapped"` is subject to `VINCTOR_HERMES_UNMAPPED_POLICY`, which
    defaults to `defer` — i.e. ALLOW. Routing an escaping path through it would
    hand the call the exact silent pass the refusal exists to prevent. The tool
    IS recognised here; only its argument is inexpressible, so it must be
    `kind="error"` with `parse_unsafe`, which blocks regardless of that policy.
    """
    result = resolve_tool_call("read_file", {"path": path}, EMPTY_CONFIG)
    assert result.kind == "error", f"{path}: {result.kind} is subject to the unmapped policy"
    assert result.reason == "parse_unsafe"


def test_positive_control_an_ordinary_path_still_maps() -> None:
    """Without this, a change that refused every path would pass the test above."""
    result = resolve_tool_call("read_file", {"path": "src/app.py"}, EMPTY_CONFIG)
    assert result.kind == "mapped"
    assert (result.action, result.resource) == ("read", "repo/src/app.py")


def test_positive_control_in_bounds_traversal_folds_to_the_same_resource() -> None:
    """One file, one resource — whichever spelling the caller used. Otherwise an
    operator rule or an audit query written against one spelling misses the
    other."""
    config = EMPTY_CONFIG
    spellings = ("src/app.py", "src/./app.py", "src/x/../app.py", "./src/app.py", "src//app.py")
    for spelling in spellings:
        result = resolve_tool_call("read_file", {"path": spelling}, config)
        assert result.kind == "mapped", spelling
        assert result.resource == "repo/src/app.py", spelling
