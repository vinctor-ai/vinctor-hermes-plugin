from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .types import Action, MatchType

# PKA-119 review: a configured config is read with a hard byte ceiling so a huge
# or growing file cannot be pulled into memory unbounded.
MAX_CONFIG_BYTES = 1024 * 1024

VALID_ACTIONS = {"read", "write", "execute", "deploy", "delete", "send"}
VALID_MATCH_TYPES = {"exact", "prefix", "glob"}


class ConfigError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("invalid_config")
        self.errors = errors


@dataclass(frozen=True)
class Rule:
    tool: str
    match_type: MatchType
    pattern: str
    action: Action
    resource: str
    input_field: str | None = None
    priority: int = 0


@dataclass(frozen=True)
class Config:
    version: int
    rules: tuple[Rule, ...]


def empty_config() -> Config:
    return Config(version=1, rules=())


def load_config(path: str | None) -> Config:
    # PKA-119: an *unset* config path means the documented empty/default config.
    # An *explicitly configured* path is a promise — if it is missing, a
    # directory, unreadable, or malformed, that is invalid_config and must fail
    # closed (the boundary turns ConfigError into a block), never a silent empty
    # config. A typo, missing mount, or rollout race must not disable operator
    # mapping rules while still allowing execution.
    if not path:
        return empty_config()
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError([f"configured config path does not exist: {path}"])
    if config_path.is_dir():
        raise ConfigError([f"configured config path is a directory: {path}"])
    try:
        data = json.loads(_read_regular_file(config_path))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError([f"unreadable config: {exc}"]) from exc
    return parse_config(data)


def _read_regular_file(config_path: Path) -> str:
    """Read a configured config file, refusing anything that is not a regular file.

    PKA-119 review: a FIFO (or socket/device) passes exists() and is_dir(), and
    reading it then blocks forever waiting for a writer — an availability
    failure, not the bounded fail-closed the ticket asks for. The check runs on
    an already-open descriptor (O_NONBLOCK so opening a writer-less FIFO returns
    instead of blocking, then fstat) so it cannot be defeated by swapping the
    path between the check and the read. Symlinks to regular files still load.
    """
    fd = os.open(config_path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ConfigError(
                [f"configured config path is not a regular file: {config_path}"]
            )
        if info.st_size > MAX_CONFIG_BYTES:
            raise ConfigError(
                [f"configured config exceeds {MAX_CONFIG_BYTES} bytes: {config_path}"]
            )
        chunks: list[bytes] = []
        total = 0
        while total <= MAX_CONFIG_BYTES:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if total > MAX_CONFIG_BYTES:
            raise ConfigError(
                [f"configured config exceeds {MAX_CONFIG_BYTES} bytes: {config_path}"]
            )
    finally:
        os.close(fd)
    return b"".join(chunks).decode("utf-8")


def load_runtime_config(
    config_path: str | None,
    mcp_registry_path: str | None,
    *,
    allow_mcp_registry_runtime_rules: bool = False,
) -> Config:
    config = load_config(config_path)
    if not mcp_registry_path or not allow_mcp_registry_runtime_rules:
        return config
    registry_path = Path(mcp_registry_path)
    try:
        data = json.loads(_read_regular_file(registry_path))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        # Same tuple as load_config: _read_regular_file decodes as UTF-8, so a
        # registry holding an invalid byte raises UnicodeDecodeError. Omitting
        # it here let that escape the adapter as an uncaught exception instead
        # of the invalid_config block every config failure is contracted to
        # produce — whether that then fails open is the host's behavior, not
        # ours to assume.
        raise ConfigError([f"unreadable mcp registry: {exc}"]) from exc

    from .mcp_discovery import discover_mcp_registry

    discovered = discover_mcp_registry(data)
    generated_rules = tuple(
        Rule(
            tool=rule.tool,
            match_type="exact",
            pattern=rule.tool,
            action=rule.action,
            resource=rule.resource,
            input_field=None,
            priority=1,
        )
        for rule in discovered.rules
    )
    return Config(version=1, rules=config.rules + generated_rules)


def parse_config(data: Any) -> Config:
    errors: list[str] = []
    if not isinstance(data, dict):
        raise ConfigError(["config must be an object"])
    if data.get("version") != 1:
        errors.append("version must be 1")
    raw_rules = data.get("rules")
    if not isinstance(raw_rules, list):
        errors.append("rules must be an array")
        raw_rules = []

    rules: list[Rule] = []
    for index, raw_rule in enumerate(raw_rules):
        prefix = f"rules[{index}]"
        if not isinstance(raw_rule, dict):
            errors.append(f"{prefix} must be an object")
            continue
        rule = _parse_rule(raw_rule, prefix, errors)
        if rule is not None:
            rules.append(rule)

    if errors:
        raise ConfigError(errors)
    return Config(version=1, rules=tuple(rules))


def _parse_rule(raw_rule: dict[str, Any], prefix: str, errors: list[str]) -> Rule | None:
    tool = raw_rule.get("tool")
    match_type = raw_rule.get("matchType", raw_rule.get("match_type"))
    pattern = raw_rule.get("pattern")
    action = raw_rule.get("action")
    resource = raw_rule.get("resource")
    input_field = raw_rule.get("inputField", raw_rule.get("input_field"))

    if not isinstance(tool, str) or not tool:
        errors.append(f"{prefix}.tool must be a non-empty string")
    if match_type not in VALID_MATCH_TYPES:
        errors.append(f"{prefix}.matchType must be exact, prefix, or glob")
    if not isinstance(pattern, str) or not pattern:
        errors.append(f"{prefix}.pattern must be a non-empty string")
    if action not in VALID_ACTIONS:
        errors.append(f"{prefix}.action must be a v1 action")
    if not isinstance(resource, str) or not resource or "*" in resource:
        errors.append(f"{prefix}.resource must be explicit")
    if input_field is not None and (not isinstance(input_field, str) or not input_field):
        errors.append(f"{prefix}.inputField must be a non-empty string")
    if errors:
        return None

    return Rule(
        tool=tool,
        match_type=match_type,
        pattern=pattern,
        action=action,
        resource=resource,
        input_field=input_field,
    )
