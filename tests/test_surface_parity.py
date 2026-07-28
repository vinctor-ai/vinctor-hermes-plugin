"""PKA-156: the two Hermes tool surfaces must resolve one contract, not two.

This adapter exposes the same filesystem operations twice - under their bare
Hermes names (``move_file``) and under the MCP spelling
(``mcp__filesystem__move_file``). They were two independent implementations of
one contract, so every multi-effect fix landed on one of them and the other kept
the hole: PKA-145 fixed native ``move_file`` while the MCP resolver kept charging
a single pair, and PKA-148 fixed ``mcp__filesystem__read_multiple_files`` while
the native spelling was not in the tool table at all and deferred OPEN.

Fixing those call sites one at a time leaves the cause intact, so this sweep is
the ratchet: for EVERY operation both surfaces expose, and for every argument
shape that matters (ordinary path, credential-shaped decoy, unmappable path,
missing path), the two spellings must produce the same required set.

The one place they legitimately differ is pinned by the canon itself and is
enumerated below as data, so widening it is a visible edit rather than a silent
drift.

Every credential-shaped path here is a DECOY STRING classified in-process.
Nothing below is ever opened.
"""

import unittest

from vinctor_hermes_plugin.config import empty_config
from vinctor_hermes_plugin.filesystem import FILESYSTEM_ACTIONS
from vinctor_hermes_plugin.mapping import resolve_tool_call

# Decoy path strings. Never opened - only classified.
ORDINARY = "/project/notes.txt"
IN_TREE = "src/app.py"
SECRET_ENV = "/home/u/.env"
SECRET_AWS = "/home/u/.aws/credentials"
UNMAPPABLE = "../../etc/passwd"

SINGLE_PATH_VALUES = (ORDINARY, IN_TREE, SECRET_ENV, UNMAPPABLE)

# The shared table, enumerated independently of the table itself.
#
# The sweep below is GENERATED from FILESYSTEM_ACTIONS, so the table is also its
# own oracle: an entry deleted from it is deleted from every case this file
# builds, and `swept == set(FILESYSTEM_ACTIONS)` still holds because both sides
# shrank together. A count floor did not close that - with 17 entries and a
# floor of "more than 15", exactly one could be dropped in silence, and
# `delete_directory` was that one: removing it left the whole suite green at 202
# passed, after which both spellings resolved `unmapped` and
# `delete_directory {"path": "<decoy>/.ssh"}` reached `pre_tool_call` with
# result None and zero enforce calls.
#
# So the expected table is written out here as literal data. Adding, removing or
# reclassifying an operation is now an edit to two places that must agree.
EXPECTED_FILESYSTEM_ACTIONS = {
    "read_text_file": "read",
    "read_file": "read",
    "read_media_file": "read",
    "read_multiple_files": "read",
    "list_directory": "read",
    "list_directory_with_sizes": "read",
    "directory_tree": "read",
    "search_files": "read",
    "get_file_info": "read",
    "list_allowed_directories": "read",
    "write_file": "write",
    "edit_file": "write",
    "create_directory": "write",
    "move_file": "write",
    "delete_file": "delete",
    "delete_directory": "delete",
    "remove_directory": "delete",
}

# Operations the generated single-path sweep cannot cover with `{"path": ...}`:
# a move needs two endpoints, a multi-read needs a list, and
# list_allowed_directories takes no path at all. Each has its own test below.
SPECIAL_CASE_TOOLS = frozenset(
    {"move_file", "read_multiple_files", "list_allowed_directories"}
)

MOVE_CASES = (
    # (source, destination, extra pair the MCP surface charges on top of the
    #  native surface's set, MCP primary resource or None to mean "same as
    #  native").
    #
    # The divergence is canon, not a bug we are papering over: the multi-effect
    # catalogue keeps EACH surface's historical primary pair so existing grants
    # keep working, and the primary is a member of the required set. On the MCP
    # surface a credential-shaped SOURCE stays the primary
    # (move-file-secret-source), so `write secret/<kind>` is in the set; on the
    # native Hermes surface the primary is the destination
    # (hermes-move-file-secret-source), so it is not. Everything else - the
    # source read, the source delete, the destination write - is identical.
    (ORDINARY, "/tmp/x", None, None),
    (IN_TREE, "docs/readme.md", None, None),
    (SECRET_ENV, "/tmp/x", ("write", "secret/env"), "secret/env"),
    (SECRET_ENV, SECRET_AWS, ("write", "secret/env"), "secret/env"),
    ("/tmp/x", SECRET_AWS, None, None),
    (SECRET_ENV, SECRET_ENV, None, None),  # both endpoints fold to one resource
    (UNMAPPABLE, "/tmp/x", None, None),
    ("/tmp/x", UNMAPPABLE, None, None),
)

MULTI_READ_CASES = (
    ["/repo/notes.txt", SECRET_ENV, "/home/u/.ssh/id_rsa"],
    ["/repo/a.txt", "/docs/readme.md"],
    [SECRET_ENV, "/home/u2/.env"],
    ["/repo/a.txt", UNMAPPABLE, SECRET_ENV],
)


def _required_set(result):
    return {(result.action, result.resource)} | {
        (r.action, r.resource) for r in result.also_requires
    }


def _outcome(result):
    """Everything the boundary acts on: the verdict, the primary, and the set."""
    if result.kind != "mapped":
        return (result.kind, result.reason, None, frozenset())
    return (result.kind, None, (result.action, result.resource), frozenset(_required_set(result)))


def _resolve(tool, args):
    return resolve_tool_call(tool, dict(args), empty_config())


def _both(tool, args):
    return _resolve(tool, args), _resolve(f"mcp__filesystem__{tool}", args)


def _single_path_cases():
    for tool, action in sorted(FILESYSTEM_ACTIONS.items()):
        if tool in SPECIAL_CASE_TOOLS:
            continue
        for path in SINGLE_PATH_VALUES:
            yield tool, {"path": path}, action
        yield tool, {}, action


class FilesystemSurfaceParityTests(unittest.TestCase):
    def test_single_path_tools_resolve_identically_on_both_surfaces(self):
        for tool, args, _action in _single_path_cases():
            with self.subTest(tool=tool, args=args):
                native, mcp = _both(tool, args)
                self.assertEqual(_outcome(native), _outcome(mcp))

    def test_read_multiple_files_resolves_identically_on_both_surfaces(self):
        for paths in MULTI_READ_CASES:
            with self.subTest(paths=paths):
                native, mcp = _both("read_multiple_files", {"paths": paths})
                self.assertEqual(_outcome(native), _outcome(mcp))

    def test_list_allowed_directories_resolves_identically_on_both_surfaces(self):
        native, mcp = _both("list_allowed_directories", {})
        self.assertEqual(_outcome(native), _outcome(mcp))

    def test_move_file_differs_only_by_the_canon_pinned_primary_escalation(self):
        for source, destination, extra, mcp_primary in MOVE_CASES:
            with self.subTest(source=source, destination=destination):
                native, mcp = _both(
                    "move_file", {"source": source, "destination": destination}
                )
                if native.kind != "mapped":
                    self.assertEqual(_outcome(native), _outcome(mcp))
                    continue
                self.assertEqual(mcp.kind, "mapped")
                expected = _required_set(native) | ({extra} if extra else set())
                self.assertEqual(_required_set(mcp), expected)
                self.assertEqual(
                    (mcp.action, mcp.resource),
                    ("write", mcp_primary) if mcp_primary else (native.action, native.resource),
                )

    def test_the_shared_table_is_exactly_the_enumerated_expected_table(self):
        """The premise under the premise: the table is not its own oracle.

        Everything else in this file is generated from FILESYSTEM_ACTIONS, so a
        dropped entry drops its own coverage and the sweep stays green. This is
        the one assertion that does not read the table to decide what the table
        should contain - see EXPECTED_FILESYSTEM_ACTIONS.
        """
        self.assertEqual(FILESYSTEM_ACTIONS, EXPECTED_FILESYSTEM_ACTIONS)

    def test_every_shared_filesystem_operation_is_swept(self):
        """The premise: this sweep covers the whole table, not a stale subset.

        PKA-156's third gap was a tool missing from ONE surface's table, which a
        hand-listed sweep would reproduce. The case list is generated from the
        shared table, and this asserts the generation actually reached every
        entry - a sweep that silently covered nothing would still pass the
        equality assertions above.
        """
        swept = {tool for tool, _args, _action in _single_path_cases()}
        swept |= SPECIAL_CASE_TOOLS
        self.assertEqual(swept, set(EXPECTED_FILESYSTEM_ACTIONS))

    def test_the_sweep_reaches_every_outcome_it_claims_to_compare(self):
        """The premise: each compared shape actually fires.

        A parity sweep whose every case returned `unmapped` on both surfaces
        would pass vacuously. Assert each verdict this file exists to compare is
        actually produced at least once, on BOTH surfaces.
        """
        kinds = {"native": set(), "mcp": set()}
        reasons = {"native": set(), "mcp": set()}
        multi_effect = {"native": 0, "mcp": 0}

        def observe(args_by_tool):
            for tool, args in args_by_tool:
                native, mcp = _both(tool, args)
                for label, result in (("native", native), ("mcp", mcp)):
                    kinds[label].add(result.kind)
                    if result.reason:
                        reasons[label].add(result.reason)
                    if result.also_requires:
                        multi_effect[label] += 1

        observe((tool, args) for tool, args, _action in _single_path_cases())
        observe(
            ("move_file", {"source": source, "destination": destination})
            for source, destination, _extra, _primary in MOVE_CASES
        )
        observe(("read_multiple_files", {"paths": paths}) for paths in MULTI_READ_CASES)

        for label in ("native", "mcp"):
            self.assertEqual(kinds[label], {"mapped", "error"}, label)
            self.assertEqual(reasons[label], {"parse_unsafe", "malformed_payload"}, label)
            self.assertGreaterEqual(multi_effect[label], 5, label)

    def test_an_unmappable_path_blocks_on_both_surfaces_instead_of_deferring(self):
        """PKA-156 gap 2: the MCP resolvers returned `unmapped` for a path they
        could not express, and the default unmapped policy defers OPEN - so
        `mcp__filesystem__write_file` on `../../etc/passwd` ran with zero
        enforcement while the native spelling blocked."""
        for tool in ("write_file", "read_text_file", "delete_file", "search_files"):
            with self.subTest(tool=tool):
                for result in _both(tool, {"path": UNMAPPABLE}):
                    self.assertEqual(result.kind, "error")
                    self.assertEqual(result.reason, "parse_unsafe")


class NativeReadMultipleFilesTests(unittest.TestCase):
    """PKA-156 gap 3: PKA-148 fixed only the ``mcp__*`` spelling.

    The bare ``read_multiple_files`` name was in neither native tool set, so it
    resolved `unmapped` and the default policy deferred it OPEN - a list of
    credential-shaped decoys read with zero enforce calls.
    """

    def test_the_native_spelling_charges_every_distinct_path(self):
        result = _resolve("read_multiple_files", {"paths": [SECRET_ENV, "/home/u/.ssh/id_rsa"]})

        self.assertEqual(result.kind, "mapped")
        self.assertEqual(
            _required_set(result), {("read", "secret/env"), ("read", "secret/ssh")}
        )


if __name__ == "__main__":
    unittest.main()
