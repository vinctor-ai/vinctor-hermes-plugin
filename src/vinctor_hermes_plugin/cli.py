from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, TextIO

from . import __version__
from .config import ConfigError, load_config, load_runtime_config
from .mapping import resolve_tool_call
from .mcp_discovery import discover_mcp_registry


class _ParserExit(Exception):
    def __init__(self, code: int):
        super().__init__(code)
        self.code = code


class _CliParser(argparse.ArgumentParser):
    def __init__(
        self,
        *args: Any,
        stdout: TextIO,
        stderr: TextIO,
        **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)
        self.stdout = stdout
        self.stderr = stderr

    def print_help(self, file: TextIO | None = None) -> None:
        super().print_help(file or self.stdout)

    def print_usage(self, file: TextIO | None = None) -> None:
        super().print_usage(file or self.stderr)

    def exit(self, status: int = 0, message: str | None = None) -> None:
        if message:
            target = self.stderr if status else self.stdout
            target.write(message)
        raise _ParserExit(status)

    def error(self, message: str) -> None:
        self.print_usage(self.stderr)
        self.exit(2, f"{self.prog}: error: {message}\n")


def main() -> int:
    return run(sys.argv[1:], stdout=sys.stdout, stderr=sys.stderr)


def run(
    argv: list[str],
    *,
    stdout: TextIO,
    stderr: TextIO,
    env: dict[str, str | None] | None = None,
) -> int:
    runtime_env = env if env is not None else os.environ
    if argv == ["--version"]:
        stdout.write(f"vinctor-hermes-plugin {__version__}\n")
        return 0

    parser = _CliParser(prog="vinctor-hermes-plugin", stdout=stdout, stderr=stderr)
    subcommands = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=lambda *args, **kwargs: _CliParser(
            *args,
            stdout=stdout,
            stderr=stderr,
            **kwargs,
        ),
    )

    validate = subcommands.add_parser("validate")
    validate.add_argument("path")
    validate.add_argument("--json", action="store_true")

    explain = subcommands.add_parser("explain")
    explain.add_argument("event")
    explain.add_argument("--config")
    explain.add_argument("--mcp-registry")
    explain.add_argument("--json", action="store_true")

    doctor = subcommands.add_parser("doctor")
    doctor.add_argument("--json", action="store_true")

    draft_mcp_config = subcommands.add_parser("draft-mcp-config")
    draft_mcp_config.add_argument("registry")
    draft_mcp_config.add_argument("--json", action="store_true")

    try:
        args = parser.parse_args(argv)
    except _ParserExit as exc:
        return exc.code
    if args.command == "validate":
        return _validate(args.path, json_output=args.json, stdout=stdout)
    if args.command == "explain":
        config_path = args.config or runtime_env.get("VINCTOR_HERMES_PLUGIN_CONFIG")
        mcp_registry_path = args.mcp_registry or runtime_env.get("VINCTOR_HERMES_MCP_REGISTRY")
        allow_mcp_registry_runtime_rules = _enabled(
            runtime_env.get("VINCTOR_HERMES_ALLOW_MCP_REGISTRY_RUNTIME_RULES")
        )
        return _explain(
            args.event,
            config_path=config_path,
            mcp_registry_path=mcp_registry_path,
            allow_mcp_registry_runtime_rules=allow_mcp_registry_runtime_rules,
            debug=_enabled(runtime_env.get("VINCTOR_HERMES_DEBUG")),
            json_output=args.json,
            stdout=stdout,
            stderr=stderr,
        )
    if args.command == "doctor":
        return _doctor(runtime_env, json_output=args.json, stdout=stdout)
    if args.command == "draft-mcp-config":
        return _draft_mcp_config(args.registry, json_output=args.json, stdout=stdout, stderr=stderr)
    return 2


def _doctor(
    runtime_env: Any,
    *,
    json_output: bool,
    stdout: TextIO,
) -> int:
    """Report the config a newly constructed boundary would load.

    PKA-119 review: `validate <path>` only inspects a path the operator types,
    so a wrong or missing VINCTOR_HERMES_PLUGIN_CONFIG stayed invisible. doctor
    resolves the source from the same environment a new boundary reads and
    names it — including when the answer is "no path configured, built-in
    empty config", which is a legitimate state and must not look broken.
    """
    config_path = runtime_env.get("VINCTOR_HERMES_PLUGIN_CONFIG")
    mcp_registry_path = runtime_env.get("VINCTOR_HERMES_MCP_REGISTRY")
    allow_mcp_registry_runtime_rules = _enabled(
        runtime_env.get("VINCTOR_HERMES_ALLOW_MCP_REGISTRY_RUNTIME_RULES")
    )
    payload: dict[str, Any] = {
        "config_path": config_path or None,
        "config_source": (
            "VINCTOR_HERMES_PLUGIN_CONFIG" if config_path else "built-in empty config"
        ),
        "mcp_registry_path": mcp_registry_path or None,
        "mcp_registry_runtime_rules": allow_mcp_registry_runtime_rules,
    }
    try:
        config = load_runtime_config(
            config_path,
            mcp_registry_path,
            allow_mcp_registry_runtime_rules=allow_mcp_registry_runtime_rules,
        )
    except ConfigError as exc:
        payload.update({"valid": False, "errors": exc.errors, "rule_count": 0})
        _write(payload, json_output=json_output, stdout=stdout)
        return 1
    payload.update({"valid": True, "errors": [], "rule_count": len(config.rules)})
    _write(payload, json_output=json_output, stdout=stdout)
    return 0


def _validate(path: str, *, json_output: bool, stdout: TextIO) -> int:
    # PKA-119: an explicitly given path that is missing/unreadable/malformed is
    # invalid_config, not a silent empty config. `path` names the active config
    # source so the operator can see exactly what is (or is not) in effect.
    try:
        config = load_config(path)
    except ConfigError as exc:
        payload = {
            "valid": False,
            "errors": exc.errors,
            "path": path,
            "rule_count": 0,
            "note": None,
        }
        _write(payload, json_output=json_output, stdout=stdout)
        return 1
    payload = {
        "valid": True,
        "errors": [],
        "path": path,
        "rule_count": len(config.rules),
        "note": None,
    }
    _write(payload, json_output=json_output, stdout=stdout)
    return 0


def _explain(
    event_path: str,
    *,
    config_path: str | None,
    mcp_registry_path: str | None,
    allow_mcp_registry_runtime_rules: bool,
    debug: bool,
    json_output: bool,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    try:
        config = load_runtime_config(
            config_path,
            mcp_registry_path,
            allow_mcp_registry_runtime_rules=allow_mcp_registry_runtime_rules,
        )
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ConfigError) as exc:
        print(str(exc), file=stderr)
        if debug:
            print(
                "debug: "
                f"config={config_path or '<none>'} "
                f"mcp_registry={mcp_registry_path or '<none>'} "
                f"allow_mcp_registry_runtime_rules={allow_mcp_registry_runtime_rules}",
                file=stderr,
            )
        return 1
    if not isinstance(event, dict):
        print("event must be an object", file=stderr)
        return 1

    tool_name = event.get("tool_name")
    tool_args = event.get("args", {})
    if not isinstance(tool_name, str) or not isinstance(tool_args, dict):
        print("event must include tool_name and object args", file=stderr)
        return 1

    result = resolve_tool_call(tool_name, tool_args, config)
    if result.kind == "mapped":
        payload: dict[str, Any] = {
            "status": "mapped",
            "action": result.action,
            "resource": result.resource,
            "source": result.source,
        }
    elif result.kind == "error":
        payload = {"status": "error", "reason": result.reason}
    else:
        payload = {"status": "unmapped"}
    _write(payload, json_output=json_output, stdout=stdout)
    return 0


def _draft_mcp_config(
    registry_path: str,
    *,
    json_output: bool,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    try:
        data = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=stderr)
        return 1
    payload = discover_mcp_registry(data).as_payload()
    _write(payload, json_output=json_output, stdout=stdout)
    return 0


def _write(payload: dict[str, Any], *, json_output: bool, stdout: TextIO) -> None:
    if json_output:
        stdout.write(json.dumps(payload, sort_keys=True) + "\n")
    else:
        stdout.write(_text(payload) + "\n")


def _text(payload: dict[str, Any]) -> str:
    if "config_source" in payload:
        # doctor: always name the active source, valid or not (PKA-119 review).
        source = payload["config_path"] or payload["config_source"]
        if payload.get("valid") is True:
            return f"config: {source} ({payload['rule_count']} rules)"
        errors = "; ".join(str(error) for error in payload.get("errors", []))
        return f"config: {source} invalid: {errors}"
    if payload.get("valid") is True:
        return "valid"
    if payload.get("valid") is False:
        return "invalid: " + "; ".join(str(error) for error in payload.get("errors", []))
    if payload.get("status") == "mapped":
        return f"{payload['action']}:{payload['resource']} ({payload['source']})"
    return str(payload.get("status", "unknown"))


def _enabled(value: str | None) -> bool:
    return value in {"1", "true", "TRUE", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
