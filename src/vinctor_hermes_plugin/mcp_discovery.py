from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .mcp import is_known_mcp_tool, split_mcp_tool_name
from .types import Action

_READ_VERBS = {
    "describe",
    "download",
    "fetch",
    "find",
    "get",
    "list",
    "lookup",
    "query",
    "read",
    "search",
    "select",
}
_WRITE_VERBS = {
    "add",
    "create",
    "edit",
    "import",
    "insert",
    "move",
    "set",
    "update",
    "upload",
    "upsert",
    "write",
}
_EXECUTE_VERBS = {
    "apply",
    "deploy",
    "execute",
    "invoke",
    "merge",
    "promote",
    "publish",
    "release",
    "run",
    "trigger",
}
_DELETE_VERBS = {"archive", "delete", "destroy", "remove", "revoke"}
_SEND_VERBS = {"comment", "email", "message", "notify", "post", "reply", "send"}


@dataclass(frozen=True)
class DraftRule:
    tool: str
    action: Action
    resource: str

    def as_config_rule(self) -> dict[str, str]:
        return {
            "tool": self.tool,
            "matchType": "exact",
            "pattern": self.tool,
            "action": self.action,
            "resource": self.resource,
        }


@dataclass(frozen=True)
class SkippedTool:
    name: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "reason": self.reason}


@dataclass(frozen=True)
class DiscoveryResult:
    rules: tuple[DraftRule, ...]
    known_builtin: tuple[str, ...]
    skipped: tuple[SkippedTool, ...]

    def as_payload(self) -> dict[str, object]:
        return {
            "config": {
                "version": 1,
                "rules": [rule.as_config_rule() for rule in self.rules],
            },
            "generated_rule_count": len(self.rules),
            "known_builtin": list(self.known_builtin),
            "skipped": [item.as_dict() for item in self.skipped],
        }


def discover_mcp_registry(data: Any) -> DiscoveryResult:
    tools = _tool_entries(data)
    rules: list[DraftRule] = []
    known_builtin: list[str] = []
    skipped: list[SkippedTool] = []

    for entry in tools:
        name = _tool_name(entry)
        if not name:
            continue
        parsed = split_mcp_tool_name(name)
        if parsed is None:
            skipped.append(SkippedTool(name=name, reason="not_mcp_tool"))
            continue
        if is_known_mcp_tool(name):
            known_builtin.append(name)
            continue
        server, tool = parsed
        inference = _infer_action(tool, _description(entry))
        if inference is None:
            skipped.append(SkippedTool(name=name, reason="could_not_infer_action"))
            continue
        if inference == "ambiguous":
            skipped.append(SkippedTool(name=name, reason="ambiguous_action"))
            continue
        action = inference
        rules.append(DraftRule(tool=name, action=action, resource=f"mcp/{server}/{tool}"))

    return DiscoveryResult(
        rules=tuple(rules),
        known_builtin=tuple(known_builtin),
        skipped=tuple(skipped),
    )


def _tool_entries(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        raw_tools = data
    elif isinstance(data, dict):
        raw_tools = data.get("tools")
    else:
        raw_tools = None
    if not isinstance(raw_tools, list):
        return []
    return [item for item in raw_tools if isinstance(item, dict)]


def _tool_name(entry: dict[str, Any]) -> str | None:
    for field in ("name", "tool_name", "toolName"):
        value = entry.get(field)
        if isinstance(value, str) and value and "\0" not in value:
            return value
    return None


def _description(entry: dict[str, Any]) -> str:
    value = entry.get("description")
    return value if isinstance(value, str) else ""


def _infer_action(tool: str, description: str) -> Action | str | None:
    tokens = _tokens(tool)
    text_tokens = _tokens(description)
    all_tokens = tokens + text_tokens
    verb_hits = [
        token
        for token in all_tokens
        if token in _READ_VERBS
        or token in _DELETE_VERBS
        or token in _SEND_VERBS
        or token in _EXECUTE_VERBS
        or token in _WRITE_VERBS
    ]
    verb_families = {_verb_family(token) for token in verb_hits if _verb_family(token) is not None}
    if len(verb_families) > 1:
        return "ambiguous"
    if "cannot" in text_tokens and verb_hits:
        return "ambiguous"

    if tokens and tokens[0] in _READ_VERBS:
        return "read"
    if tokens and tokens[0] in _DELETE_VERBS:
        return "delete"
    if tokens and tokens[0] in _SEND_VERBS:
        return "send"
    if tokens and tokens[0] in _EXECUTE_VERBS:
        return "execute"
    if tokens and tokens[0] in _WRITE_VERBS:
        return "write"
    all_token_set = set(all_tokens)
    if all_token_set & _DELETE_VERBS:
        return "delete"
    if all_token_set & _SEND_VERBS:
        return "send"
    if all_token_set & _EXECUTE_VERBS:
        return "execute"
    if all_token_set & _WRITE_VERBS:
        return "write"
    if all_token_set & _READ_VERBS:
        return "read"
    return None


def _verb_family(token: str) -> str | None:
    if token in _READ_VERBS:
        return "read"
    if token in _DELETE_VERBS:
        return "delete"
    if token in _SEND_VERBS:
        return "send"
    if token in _EXECUTE_VERBS:
        return "execute"
    if token in _WRITE_VERBS:
        return "write"
    return None


def _tokens(value: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", value.lower()) if token]
