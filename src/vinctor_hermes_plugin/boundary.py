from __future__ import annotations

import hashlib
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import Config, ConfigError, load_runtime_config
from .enforce import ActionDeniedError, EnforceClient, EnforceOutcome, ServiceUnavailableError
from .mapping import resolve_tool_call

DEFAULT_TIMEOUT_MS = 500
PUBLIC_BLOCK_REASONS = {
    "action_denied",
    "missing_auth_env",
    "service_unavailable",
    "invalid_config",
    "parse_unsafe",
    "malformed_payload",
    "unmapped_tool",
}

EnforceFunc = Callable[[str, str, str], EnforceOutcome]
DecisionRecorder = Callable[[dict[str, Any]], None]
CoverageRecorder = Callable[[dict[str, Any]], None]


class VinctorHermesBoundary:
    def __init__(
        self,
        *,
        env: dict[str, str | None],
        config: Config | None = None,
        enforce_func: EnforceFunc | None = None,
        decision_recorder: DecisionRecorder | None = None,
        coverage_recorder: CoverageRecorder | None = None,
    ):
        self.env = env
        self.config = config
        self.enforce_func = enforce_func
        self.decision_recorder = decision_recorder
        self.coverage_recorder = coverage_recorder
        self._config_stamp = _config_source_stamp(env) if config is not None else None

    @classmethod
    def from_env(
        cls,
        *,
        env: dict[str, str | None],
        enforce_func: EnforceFunc | None = None,
    ) -> VinctorHermesBoundary:
        # PKA-160: say so ONCE, at construction, if the operator asked for a
        # policy this plugin does not recognize. Emitted here rather than per
        # call so a busy boundary cannot bury it, and to stderr because stdout
        # is the plugin's data channel.
        warning = unmapped_policy_warning(env)
        if warning is not None:
            print(warning, file=sys.stderr)
        recorder = _recorder_from_env(env)
        coverage_recorder = _coverage_recorder_from_env(env)
        boundary = cls(
            env=env,
            config=None,
            enforce_func=enforce_func,
            decision_recorder=recorder,
            coverage_recorder=coverage_recorder,
        )
        # PKA-119 review: do NOT latch the startup failure. A boundary built
        # while the config was missing or broken must recover once operators
        # repair the file — an init-container or mount rollout race must not
        # leave a running plugin permanently blocked. _load_config leaves
        # config unset on failure, so every call re-loads and still blocks
        # fail-closed for as long as it stays broken.
        boundary._load_config()
        return boundary

    def _load_config(self) -> Config | None:
        """Load the configured sources, remembering the stamp they were read at.

        The stamp is taken BEFORE the read: if a source changes while it is
        being read, the recorded stamp describes the older state, so the next
        call reloads rather than caching content the stamp does not describe.
        """
        stamp = _config_source_stamp(self.env)
        try:
            config = load_runtime_config(
                self.env.get("VINCTOR_HERMES_PLUGIN_CONFIG"),
                self.env.get("VINCTOR_HERMES_MCP_REGISTRY"),
                allow_mcp_registry_runtime_rules=_enabled(
                    self.env.get("VINCTOR_HERMES_ALLOW_MCP_REGISTRY_RUNTIME_RULES")
                ),
            )
        except ConfigError:
            self.config = None
            self._config_stamp = None
            return None
        self.config = config
        self._config_stamp = stamp
        return config

    def pre_tool_call(
        self,
        *,
        tool_name: str,
        args: dict[str, Any] | None = None,
        **_context: Any,
    ) -> dict[str, str] | None:
        config = self.config
        if config is None or _config_source_stamp(self.env) != self._config_stamp:
            config = self._load_config()
            if config is None:
                self._record_coverage(
                    tool_name=tool_name,
                    args=args,
                    mapping_status="error",
                    block_reason="invalid_config",
                    blocked=True,
                )
                return _block("invalid_config")

        mapping = resolve_tool_call(tool_name, args if isinstance(args, dict) else {}, config)
        if mapping.kind == "unmapped":
            if (
                mapping.reason == "unsafe_shell"
                or _unmapped_policy(self.env) == "block"
            ):
                self._record_coverage(
                    tool_name=tool_name,
                    args=args,
                    mapping_status="unmapped",
                    block_reason="unmapped_tool",
                    blocked=True,
                )
                return _block("unmapped_tool")
            self._record_coverage(
                tool_name=tool_name,
                args=args,
                mapping_status="unmapped",
                blocked=False,
            )
            return None
        if mapping.kind == "error":
            self._record_coverage(
                tool_name=tool_name,
                args=args,
                mapping_status="error",
                block_reason=mapping.reason or "malformed_payload",
                blocked=True,
            )
            return _block(mapping.reason or "malformed_payload")

        endpoint = self.env.get("VINCTOR_ENDPOINT")
        agent_key = self.env.get("VINCTOR_AGENT_KEY")
        grant_ref = self.env.get("VINCTOR_GRANT_REF")
        if not endpoint or not agent_key or not grant_ref:
            self._record_coverage(
                tool_name=tool_name,
                args=args,
                mapping_status="mapped",
                action=mapping.action,
                resource=mapping.resource,
                block_reason="missing_auth_env",
                blocked=True,
            )
            return _block("missing_auth_env")

        try:
            enforce = self.enforce_func or _client_from_env(self.env).enforce
            # PKA-145: a compound operation causes more than one effect, and each
            # is a separate authorization question. Ask for the primary AND every
            # other effect; the first denial denies the whole call, so a grant
            # covering one effect can never authorize another. Mapping the extra
            # effects without asking for them here would leave the original hole
            # exactly as open.
            outcome = enforce(grant_ref, mapping.action or "", mapping.resource or "")
            for requirement in mapping.also_requires:
                outcome = enforce(grant_ref, requirement.action, requirement.resource)
            self._record(
                decision="permit",
                action=mapping.action,
                resource=mapping.resource,
                audit_event_id=outcome.audit_event_id,
            )
            self._record_coverage(
                tool_name=tool_name,
                args=args,
                mapping_status="mapped",
                action=mapping.action,
                resource=mapping.resource,
                enforce_decision="permit",
                blocked=False,
            )
            return None
        except ActionDeniedError as exc:
            self._record(
                decision="deny",
                action=mapping.action,
                resource=mapping.resource,
                audit_event_id=exc.audit_event_id,
            )
            self._record_coverage(
                tool_name=tool_name,
                args=args,
                mapping_status="mapped",
                action=mapping.action,
                resource=mapping.resource,
                enforce_decision="deny",
                block_reason="action_denied",
                blocked=True,
            )
            return _block("action_denied")
        except ServiceUnavailableError:
            self._record(
                decision="error",
                action=mapping.action,
                resource=mapping.resource,
                audit_event_id=None,
            )
            self._record_coverage(
                tool_name=tool_name,
                args=args,
                mapping_status="mapped",
                action=mapping.action,
                resource=mapping.resource,
                enforce_decision="error",
                block_reason="service_unavailable",
                blocked=True,
            )
            return _block("service_unavailable")
        except Exception:
            self._record(
                decision="error",
                action=mapping.action,
                resource=mapping.resource,
                audit_event_id=None,
            )
            self._record_coverage(
                tool_name=tool_name,
                args=args,
                mapping_status="mapped",
                action=mapping.action,
                resource=mapping.resource,
                enforce_decision="error",
                block_reason="service_unavailable",
                blocked=True,
            )
            return _block("service_unavailable")

    def _record(
        self,
        *,
        decision: str,
        action: str | None,
        resource: str | None,
        audit_event_id: str | None,
    ) -> None:
        if self.decision_recorder is None:
            return
        self.decision_recorder(
            {
                "decision": decision,
                "action": action,
                "resource": resource,
                "audit_event_id": audit_event_id,
            }
        )

    def _record_coverage(
        self,
        *,
        tool_name: str,
        args: dict[str, Any] | None,
        mapping_status: str,
        blocked: bool,
        action: str | None = None,
        resource: str | None = None,
        enforce_decision: str | None = None,
        block_reason: str | None = None,
    ) -> None:
        if self.coverage_recorder is None:
            return
        safe_args = args if isinstance(args, dict) else {}
        event = {
            "event": "pre_tool_call",
            "tool_name": tool_name,
            "arg_keys": sorted(str(key) for key in safe_args),
            "args_sha256": _args_sha256(safe_args),
            "mapping_status": mapping_status,
            "strict_unmapped_policy": _unmapped_policy(self.env),
            "action": action,
            "resource": resource,
            "enforce_decision": enforce_decision,
            "blocked": blocked,
            "block_reason": block_reason,
        }
        if _enabled(self.env.get("VINCTOR_HERMES_COVERAGE_LOG_INCLUDE_ARGS")):
            event["args"] = _jsonable_args(safe_args)
        try:
            self.coverage_recorder(event)
        except Exception:
            return


def _client_from_env(env: dict[str, str | None]) -> EnforceClient:
    timeout_ms = DEFAULT_TIMEOUT_MS
    raw_timeout = env.get("VINCTOR_HERMES_TIMEOUT_MS")
    if raw_timeout:
        try:
            timeout_ms = max(1, int(raw_timeout))
        except ValueError:
            timeout_ms = DEFAULT_TIMEOUT_MS
    return EnforceClient(
        endpoint=env["VINCTOR_ENDPOINT"] or "",
        agent_key=env["VINCTOR_AGENT_KEY"] or "",
        boundary_id=env.get("VINCTOR_BOUNDARY_ID") or None,
        timeout_ms=timeout_ms,
    )


def _enabled(value: str | None) -> bool:
    return value in {"1", "true", "TRUE", "yes", "on"}


def _unmapped_policy(env: dict[str, str | None]) -> str:
    """The policy actually in force for an unmapped tool.

    Only the exact value `block` blocks. That exactness is PKA-128's rule and
    stays: a typo must never silently turn enforcement on OR off. Everything
    else — including every near-miss spelling — is the permissive default.
    """
    return "block" if env.get("VINCTOR_HERMES_UNMAPPED_POLICY") == "block" else "defer"


def unmapped_policy_warning(env: dict[str, str | None]) -> str | None:
    """A message when VINCTOR_HERMES_UNMAPPED_POLICY is set to something unrecognized.

    PKA-160. Exact matching is right; being SILENT about a near miss was not. An
    operator who wrote `Block`, `BLOCK`, `true`, `1` or `yes` got the permissive
    default with no signal anywhere, believed unmapped tools were being blocked,
    and could not discover otherwise short of reading this file. `true`/`1`/`yes`
    are especially easy to land on — they are exactly what `_enabled()` accepts
    for the other env vars in this same plugin, so generalising from those is a
    reasonable thing to do and silently wrong.

    Warning does NOT widen what counts as blocking; `_unmapped_policy` is
    unchanged. The two must stay separate, or the warning becomes a back door
    that makes `Block` behave as `block` — the other half of PKA-128's rule.

    An unset or empty value is silent. Empty is how most shell templating and
    container tooling renders an unset variable (`FOO=${BAR}` with BAR unset), so
    warning on it would fire on ordinary deployments that never configured this
    at all, and a warning that cries wolf is one operators learn to ignore.
    """
    raw = env.get("VINCTOR_HERMES_UNMAPPED_POLICY")
    if raw is None or not raw.strip():
        return None
    if raw in _RECOGNIZED_UNMAPPED_POLICIES:
        return None
    return (
        f"vinctor-hermes-plugin: VINCTOR_HERMES_UNMAPPED_POLICY={raw!r} is not recognized; "
        f"expected one of {sorted(_RECOGNIZED_UNMAPPED_POLICIES)}. "
        "Falling back to 'defer', which ALLOWS calls to tools this plugin cannot map."
    )


_RECOGNIZED_UNMAPPED_POLICIES = frozenset({"block", "defer"})


def _config_source_stamp(env: dict[str, str | None]) -> tuple[Any, ...]:
    """Cheap identity of the configured config sources.

    PKA-119's property is that an explicitly configured path which is missing
    fails closed. Caching the first valid snapshot for the process lifetime
    traded that away: once the file was read the boundary kept permitting from
    it even after operators deleted it, tightened it, or revoked its rules.
    Re-parsing on every call is not affordable, so every call stats the
    configured sources instead and reloads only when this stamp changes. A path
    that disappears (or otherwise stops being stattable) yields a value no
    successful stat can equal, so it forces the reload that fails closed.
    """
    stamps: list[Any] = []
    registry = (
        env.get("VINCTOR_HERMES_MCP_REGISTRY")
        if _enabled(env.get("VINCTOR_HERMES_ALLOW_MCP_REGISTRY_RUNTIME_RULES"))
        else None
    )
    for path in (env.get("VINCTOR_HERMES_PLUGIN_CONFIG"), registry):
        if not path:
            stamps.append(None)
            continue
        try:
            info = os.stat(path)
        except (OSError, ValueError) as exc:
            stamps.append(("unstattable", repr(exc)))
            continue
        stamps.append((info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size))
    return tuple(stamps)


def _recorder_from_env(env: dict[str, str | None]) -> DecisionRecorder | None:
    path = env.get("VINCTOR_HERMES_DECISION_LOG")
    if not path:
        return None

    def record(event: dict[str, str | None]) -> None:
        log_path = Path(path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")

    return record


def _coverage_recorder_from_env(env: dict[str, str | None]) -> CoverageRecorder | None:
    path = env.get("VINCTOR_HERMES_COVERAGE_LOG")
    if not path:
        return None

    def record(event: dict[str, Any]) -> None:
        log_path = Path(path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")

    return record


def _args_sha256(args: dict[str, Any]) -> str:
    payload = json.dumps(args, default=str, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _jsonable_args(args: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(args, default=str, sort_keys=True))


def _block(reason: str) -> dict[str, str]:
    public_reason = reason if reason in PUBLIC_BLOCK_REASONS else "service_unavailable"
    return {
        "action": "block",
        "message": f"Denied by Vinctor authorization: {public_reason}.",
    }
