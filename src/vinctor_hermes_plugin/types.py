from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Action = Literal["read", "write", "execute", "deploy", "delete", "send"]
MatchType = Literal["exact", "prefix", "glob"]


@dataclass(frozen=True)
class Requirement:
    """One (action, resource) pair the PDP must permit before the call runs."""

    action: Action
    resource: str


@dataclass(frozen=True)
class MappingResult:
    kind: Literal["mapped", "unmapped", "error"]
    action: Action | None = None
    resource: str | None = None
    source: Literal["config", "builtin"] | None = None
    reason: str | None = None
    # PKA-145: a compound operation causes more than one effect, and each is a
    # separate authorization question. `action`/`resource` stay the single
    # canon-comparable pair; every OTHER effect the same call causes is listed
    # here. The boundary must obtain a permit for the primary AND every member —
    # one denial denies the whole call. Empty for single-effect operations.
    also_requires: tuple[Requirement, ...] = ()
