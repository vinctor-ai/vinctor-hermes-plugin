"""One filesystem resolution path for both Hermes tool surfaces.

PKA-156: this adapter exposes the same filesystem operations twice - under their
bare Hermes names (``move_file``) and under the MCP spelling
(``mcp__filesystem__move_file``) - and they were two independent implementations
of one contract. Every multi-effect fix landed on one of them:

- PKA-145 gave the NATIVE ``move_file`` its three effects; the MCP resolver kept
  charging a single pair, so a ``secret/env`` grant still carried the
  destination write, the source read and the source delete.
- PKA-148 gave ``mcp__filesystem__read_multiple_files`` one requirement per
  path; the bare ``read_multiple_files`` name was in no native tool table at
  all, so it resolved `unmapped` and the default policy deferred it OPEN.
- The MCP resolvers answered `unmapped` for a path they could not express,
  which also defers OPEN, while the native ones failed closed.

Fixing those call sites one at a time leaves the cause - two tables, two
resolvers - exactly where it was. This module is the single table and the single
resolver; ``mapping.py`` drives it for the native spellings and ``mcp.py`` for
the ``mcp__filesystem__*`` ones.

The surfaces take ONE parameter, ``secret_source_is_primary``, because the canon
pins a difference: the multi-effect catalogue keeps each surface's historical
primary pair so existing grants keep working, and the primary is a member of the
required set. On the MCP surface a credential-shaped move SOURCE stays the
primary (canon ``move-file-secret-source``); on the native surface the primary is
the destination (canon ``hermes-move-file-secret-source``).

Because the primary is a MEMBER of the set, that is not only a reporting
difference - the two required sets differ by that member, and only by it:

    move_file {"source": "<decoy>/.env", "destination": "/tmp/x"}
      native: {write fs/tmp/x, read secret/env, delete secret/env}                    (3)
      mcp   : {write secret/env, read secret/env, delete secret/env, write fs/tmp/x}  (4)

The MCP set is a strict SUPERSET of the native one, so the MCP surface is never
the weaker of the two, and a move with a credential-shaped source is the only
case where they differ at all. ``tests/test_surface_parity.py`` asserts
``required_set(mcp) == required_set(native) | {extra}`` with ``extra``
enumerated per case, so the carve-out is countable data and the exact equality
still catches a requirement going missing on either side.
"""

from __future__ import annotations

from typing import Any

from .resources import repo_or_secret_resource
from .types import Action, MappingResult, Requirement

FILESYSTEM_ACTIONS: dict[str, Action] = {
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
    "remove_directory": "delete",  # canon/spec name; delete_directory is the fork alias
}

# Argument spellings each surface has been observed to use for one path. The
# union is accepted on both: a name only one surface sends is inert on the
# other, and resolving it is strictly more conservative than deferring.
_PATH_FIELDS: dict[Action, tuple[str, ...]] = {
    "read": ("path", "file_path"),
    "write": ("path", "file_path", "destination", "dest"),
    "delete": ("path", "file_path", "target"),
}
_SOURCE_FIELDS = ("source", "src")
_DESTINATION_FIELDS = ("destination", "dest", "path")


def is_filesystem_tool(tool: str) -> bool:
    return tool in FILESYSTEM_ACTIONS


def resolve_filesystem_tool(
    tool: str, args: dict[str, Any], *, secret_source_is_primary: bool
) -> MappingResult | None:
    """Resolve one filesystem tool, or None when the name is not one of ours.

    None means "not a filesystem tool" so each caller keeps its own behaviour for
    an unrecognized name: the native surface falls through to its remaining
    classifiers, the MCP surface returns its documented `unmapped` escape hatch
    for an unknown tool on a known server.
    """
    action = FILESYSTEM_ACTIONS.get(tool)
    if action is None:
        return None
    if tool == "list_allowed_directories":
        return MappingResult(
            kind="mapped", action="read", resource="fs/_allowed-dirs", source="builtin"
        )
    if tool == "move_file":
        return _resolve_move(args, secret_source_is_primary=secret_source_is_primary)
    if tool == "read_multiple_files":
        return _resolve_multi_read(args)
    raw_path = _first_string(args, _PATH_FIELDS[action])
    if raw_path is None:
        return MappingResult(kind="error", reason="malformed_payload")
    resource = repo_or_secret_resource(raw_path)
    if resource is None:
        # Fail CLOSED. `unmapped` here would defer the call open under the
        # default VINCTOR_HERMES_UNMAPPED_POLICY, which is how the MCP surface
        # let `../../etc/passwd` through with zero enforce calls (PKA-156).
        return MappingResult(kind="error", reason="parse_unsafe")
    return MappingResult(kind="mapped", action=action, resource=resource, source="builtin")


def _resolve_move(args: dict[str, Any], *, secret_source_is_primary: bool) -> MappingResult:
    """PKA-145/PKA-156: a move causes THREE effects, not one.

    New state appears at the destination (write), and the source is both
    disclosed at a new location (read) and removed (delete). Authorizing one of
    them let a grant on that one pair move a credential out of the tree.

    Both endpoints must resolve: a member the resource mapper cannot express
    must not silently drop out of the required set, or the rest of the call
    would be authorized while that end still executes.
    """
    raw_source = _first_string(args, _SOURCE_FIELDS)
    raw_destination = _first_string(args, _DESTINATION_FIELDS)
    if raw_source is None or raw_destination is None:
        return MappingResult(kind="error", reason="malformed_payload")
    source = repo_or_secret_resource(raw_source)
    destination = repo_or_secret_resource(raw_destination)
    if source is None or destination is None:
        return MappingResult(kind="error", reason="parse_unsafe")

    primary = (
        source
        if secret_source_is_primary and source.startswith("secret/")
        else destination
    )
    also: list[Requirement] = []

    def require(action: Action, resource: str) -> None:
        if action == "write" and resource == primary:
            return  # already asserted by the primary pair
        requirement = Requirement(action=action, resource=resource)
        if requirement not in also:
            also.append(requirement)

    require("read", source)
    require("delete", source)
    require("write", destination)
    return MappingResult(
        kind="mapped",
        action="write",
        resource=primary,
        source="builtin",
        also_requires=tuple(also),
    )


def _resolve_multi_read(args: dict[str, Any]) -> MappingResult:
    """PKA-148: N paths are N read effects.

    The old shape returned the FIRST credential-shaped path as the whole
    required set, so a grant covering any one member of the list read every
    other member unenforced; all-ordinary lists fell to `unmapped`, which the
    default VINCTOR_HERMES_UNMAPPED_POLICY defers OPEN. Now every member is its
    own requirement (deduplicated by resource), the primary stays the pair the
    old behavior charged (first sensitive path, else the first path), and the
    boundary already enforces every `also_requires` member.

    A member the resource mapper cannot express refuses the WHOLE call as
    `error` - NOT `unmapped`: charging the expressible subset would authorize a
    call that still reads the inexpressible path, and `unmapped` here would
    defer the entire read open.
    """
    paths = args.get("paths")
    if not isinstance(paths, list) or not paths:
        return MappingResult(kind="error", reason="malformed_payload")
    resources: list[str] = []
    for path in paths:
        if not isinstance(path, str) or not path:
            return MappingResult(kind="error", reason="malformed_payload")
        resource = repo_or_secret_resource(path)
        if resource is None:
            return MappingResult(kind="error", reason="parse_unsafe")
        if resource not in resources:
            resources.append(resource)
    primary = next((r for r in resources if r.startswith("secret/")), resources[0])
    rest = tuple(
        Requirement(action="read", resource=resource)
        for resource in resources
        if resource != primary
    )
    return MappingResult(
        kind="mapped",
        action="read",
        resource=primary,
        source="builtin",
        also_requires=rest,
    )


def _first_string(args: dict[str, Any], fields: tuple[str, ...]) -> str | None:
    for field in fields:
        value = args.get(field)
        if isinstance(value, str) and value:
            return value
    return None
