#!/usr/bin/env python3
"""Reproducible runtime coverage-measurement harness for the Vinctor Hermes plugin.

This harness drives the main Hermes tool families through the plugin boundary and
records, per family, what the plugin can observe about a tool call:

- did the call reach ``pre_tool_call``?
- was it ``mapped``, ``unmapped``, or ``error``?
- what ``action:resource`` does the plugin enforce?
- was the call blocked, and with which public reason?

CLAIM DISCIPLINE: this harness measures two different things and never conflates
them. Read ``--help`` and the per-row ``runtime_traversal`` column carefully.

- MAPPING coverage (what this harness measures by default): given a tool event
  that ALREADY reached the plugin, can the plugin classify and enforce it? The
  default ``synthetic`` mode synthesizes the ``pre_tool_call`` event itself, so
  it proves mapping/enforce behavior but says NOTHING about whether a real Hermes
  runtime emits ``pre_tool_call`` for that family.

- RUNTIME coverage (only measurable on a real runtime): does a versioned Hermes
  runtime actually route the family through ``pre_tool_call`` before execution?
  This is left ``unmeasured`` in synthetic mode. To measure it, run the family
  probes from inside a real Hermes process with ``VINCTOR_HERMES_COVERAGE_LOG``
  set, then compare the intended invocation list against the coverage log:
  a family with a coverage row is ``observed``; a family that executed with no
  coverage row is ``bypassed`` and is OUTSIDE the Vinctor boundary.

The harness does not change mapping/enforce/block behavior. It uses a stub
enforce function so it can run offline without a Vinctor service, and so the
``action:resource`` and block decision it reports come straight from the
plugin's real ``resolve_tool_call`` + ``pre_tool_call`` code paths.

Usage:

    PYTHONPATH=src python scripts/coverage_harness.py
    PYTHONPATH=src python scripts/coverage_harness.py --json
    PYTHONPATH=src python scripts/coverage_harness.py --enforce permit
    PYTHONPATH=src python scripts/coverage_harness.py --unmapped-policy block

See ``scripts/README.md`` for the full fill-in runbook.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from vinctor_hermes_plugin.boundary import VinctorHermesBoundary  # noqa: E402
from vinctor_hermes_plugin.enforce import (  # noqa: E402
    ActionDeniedError,
    EnforceOutcome,
    ServiceUnavailableError,
)


@dataclass(frozen=True)
class Probe:
    """A single representative tool invocation for one tool family."""

    family: str
    tool_name: str
    args: dict[str, Any]
    note: str = ""


@dataclass
class ProbeResult:
    family: str
    tool_name: str
    arg_keys: list[str]
    mapping_status: str
    action: str | None
    resource: str | None
    enforce_decision: str | None
    blocked: bool
    block_reason: str | None
    runtime_traversal: str
    note: str = ""


# The probe set walks the tool families named in the coverage matrix. Each probe
# uses non-sensitive fixture arguments only. The harness drives these through the
# real plugin boundary; it does NOT assume any of them reaches a real runtime
# hook. Family ordering mirrors the coverage matrix doc for easy cross-reference.
PROBES: tuple[Probe, ...] = (
    Probe("file read", "read_file", {"path": "README.md"}),
    Probe("file write", "write_file", {"path": "build/out.txt"}),
    Probe("file edit", "edit_file", {"path": "src/app.py"}),
    Probe("file delete", "delete_file", {"path": "build/out.txt"}),
    Probe(
        "patch",
        "patch",
        {"patch": "*** Begin Patch\n*** Update File: src/app.py\n@@\n-x\n+y\n*** End Patch"},
    ),
    Probe("terminal/CI test", "terminal", {"command": "npm test"}),
    Probe("terminal/build", "terminal", {"command": "npm run build"}),
    Probe(
        "terminal/deploy",
        "terminal",
        {"command": "vercel deploy --prod"},
        note="non-production fixture only",
    ),
    Probe(
        "terminal/release",
        "terminal",
        {"command": "gh release create v0.0.0-fixture --repo acme/fixture"},
        note="do not target a real repo; --repo is required for the canon github grammar",
    ),
    Probe(
        "terminal/destructive",
        "terminal",
        {"command": "git reset --hard"},
    ),
    Probe("process control", "process", {"action": "kill", "session_id": "fixture"}),
    Probe("execute_code", "execute_code", {"code": "print('fixture')"}),
    Probe("memory", "memory", {"action": "add", "target": "fixture"}),
    Probe("session search", "session_search", {"query": "fixture"}),
    Probe("cron", "cronjob", {"action": "create", "job_id": "fixture"}),
    Probe("delegation", "delegate_task", {"task": "fixture"}),
    Probe("web search", "web_search", {"query": "fixture"}),
    Probe("web extract", "web_extract", {"url": "https://example.com/fixture"}),
    Probe("browser read", "browser_snapshot", {}),
    Probe("browser action", "browser_click", {"selector": "#fixture"}),
    Probe("browser CDP", "browser_cdp", {"method": "Page.navigate"}),
    Probe("outbound message", "send_message", {"action": "send", "target": "fixture"}),
    Probe(
        "MCP filesystem (mcp_)",
        "mcp_filesystem_read_file",
        {"path": "README.md"},
        note="mcp_<server>_<tool> shape",
    ),
    Probe(
        "MCP filesystem (mcp__)",
        "mcp__filesystem__read_file",
        {"path": "README.md"},
        note="mcp__server__tool shape",
    ),
    Probe(
        "MCP GitHub",
        "mcp_github_create_pull_request",
        {"owner": "fixture", "repo": "fixture", "title": "fixture"},
        note="fixture args, no real mutation",
    ),
    Probe(
        "MCP Slack",
        "mcp_slack_post_message",
        {"channel_id": "fixture", "text": "fixture"},
        note="test channel only; send needs channel_id to avoid ambiguous-send deferral",
    ),
    Probe(
        "MCP unmapped (dynamic)",
        "mcp_unknown_custom_tool",
        {"value": "fixture"},
        note="unknown server/tool; strict policy should block if reached",
    ),
)


EnforceMode = Literal["permit", "deny", "unavailable"]


@dataclass
class _StubEnforcer:
    """Deterministic offline enforce function.

    The harness never reaches a real Vinctor service. This stub lets the harness
    exercise the full ``pre_tool_call`` enforce branch (permit / deny / error)
    so the reported block decision is real plugin behavior, not a mock of it.
    """

    mode: EnforceMode
    seen: list[tuple[str, str]] = field(default_factory=list)

    def __call__(self, grant_ref: str, action: str, resource: str) -> EnforceOutcome:
        self.seen.append((action, resource))
        if self.mode == "permit":
            return EnforceOutcome(decision="permit", audit_event_id="evt_fixture")
        if self.mode == "deny":
            raise ActionDeniedError("action_denied", "evt_fixture")
        raise ServiceUnavailableError("offline harness")


def run_probes(
    *,
    enforce_mode: EnforceMode,
    unmapped_policy: str | None,
    runtime_traversal: str,
    probes: tuple[Probe, ...] = PROBES,
) -> list[ProbeResult]:
    """Drive every probe through the real plugin boundary and collect results.

    ``runtime_traversal`` is recorded verbatim per row. In synthetic mode it is
    ``unmeasured (synthetic)`` because the harness synthesizes the event rather
    than observing a real runtime emit it.
    """

    results: list[ProbeResult] = []
    for probe in probes:
        coverage_rows: list[dict[str, Any]] = []
        enforcer = _StubEnforcer(mode=enforce_mode)
        env: dict[str, str | None] = {
            "VINCTOR_ENDPOINT": "http://127.0.0.1:0",
            "VINCTOR_AGENT_KEY": "aak_harness",
            "VINCTOR_GRANT_REF": "grt_harness",
        }
        if unmapped_policy:
            env["VINCTOR_HERMES_UNMAPPED_POLICY"] = unmapped_policy
        boundary = VinctorHermesBoundary(
            env=env,
            config=_empty_config(),
            enforce_func=enforcer,
            coverage_recorder=coverage_rows.append,
        )
        block = boundary.pre_tool_call(tool_name=probe.tool_name, args=probe.args)
        row = coverage_rows[-1] if coverage_rows else {}
        results.append(
            ProbeResult(
                family=probe.family,
                tool_name=probe.tool_name,
                arg_keys=row.get("arg_keys", sorted(probe.args)),
                mapping_status=row.get("mapping_status", "unknown"),
                action=row.get("action"),
                resource=row.get("resource"),
                enforce_decision=row.get("enforce_decision"),
                blocked=bool(block) if block is not None else row.get("blocked", False),
                block_reason=row.get("block_reason"),
                runtime_traversal=runtime_traversal,
                note=probe.note,
            )
        )
    return results


def _empty_config():
    from vinctor_hermes_plugin.config import empty_config

    return empty_config()


def _enforce_action_resource(result: ProbeResult) -> str:
    if result.mapping_status != "mapped":
        return "-"
    if result.action is None or result.resource is None:
        return "-"
    return f"{result.action}:{result.resource}"


def render_table(results: list[ProbeResult]) -> str:
    headers = [
        "Tool family",
        "Probe tool",
        "Mapping status",
        "Enforce action:resource",
        "Blocked",
        "Block reason",
        "Runtime traversal",
    ]
    rows = [
        [
            r.family,
            r.tool_name,
            r.mapping_status,
            _enforce_action_resource(r),
            "yes" if r.blocked else "no",
            r.block_reason or "-",
            r.runtime_traversal,
        ]
        for r in results
    ]
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt(cells: list[str]) -> str:
        return " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells))

    lines = [fmt(headers), "-+-".join("-" * w for w in widths)]
    lines.extend(fmt(row) for row in rows)
    return "\n".join(lines)


def render_markdown(results: list[ProbeResult]) -> str:
    header = (
        "| Tool family | Probe tool | Mapping status | Enforce action:resource "
        "| Blocked | Block reason | Runtime traversal | Notes |"
    )
    sep = "| --- | --- | --- | --- | --- | --- | --- | --- |"
    lines = [header, sep]
    for r in results:
        lines.append(
            "| {family} | `{tool}` | {status} | {ar} | {blocked} | {reason} "
            "| {traversal} | {note} |".format(
                family=r.family,
                tool=r.tool_name,
                status=r.mapping_status,
                ar=_enforce_action_resource(r),
                blocked="yes" if r.blocked else "no",
                reason=r.block_reason or "-",
                traversal=r.runtime_traversal,
                note=r.note or "-",
            )
        )
    return "\n".join(lines)


def render_json(results: list[ProbeResult], meta: dict[str, Any]) -> str:
    return json.dumps(
        {
            "meta": meta,
            "results": [
                {
                    "family": r.family,
                    "tool_name": r.tool_name,
                    "arg_keys": r.arg_keys,
                    "mapping_status": r.mapping_status,
                    "action": r.action,
                    "resource": r.resource,
                    "enforce_decision": r.enforce_decision,
                    "blocked": r.blocked,
                    "block_reason": r.block_reason,
                    "runtime_traversal": r.runtime_traversal,
                    "note": r.note,
                }
                for r in results
            ],
        },
        indent=2,
        sort_keys=True,
    )


def summarize(results: list[ProbeResult]) -> dict[str, int]:
    summary = {"mapped": 0, "unmapped": 0, "error": 0, "blocked": 0}
    for r in results:
        if r.mapping_status in summary:
            summary[r.mapping_status] += 1
        if r.blocked:
            summary["blocked"] += 1
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Drive Hermes tool families through the Vinctor plugin boundary and "
            "report per-family mapping + enforce coverage. Synthetic mode proves "
            "MAPPING coverage only; runtime traversal stays unmeasured until run "
            "inside a real Hermes runtime."
        )
    )
    parser.add_argument(
        "--enforce",
        choices=("permit", "deny", "unavailable"),
        default="permit",
        help="stub enforce decision for mapped calls (default: permit)",
    )
    parser.add_argument(
        "--unmapped-policy",
        choices=("defer", "block"),
        default="defer",
        help="strict unmapped policy (default: defer)",
    )
    parser.add_argument(
        "--runtime-traversal",
        default="unmeasured (synthetic)",
        help=(
            "verbatim label for the runtime-traversal column. Override only when "
            "running inside a real Hermes runtime that confirmed traversal, e.g. "
            "--runtime-traversal observed."
        ),
    )
    parser.add_argument(
        "--format",
        choices=("table", "markdown", "json"),
        default="table",
        help="output format (default: table)",
    )
    parser.add_argument(
        "--json",
        action="store_const",
        const="json",
        dest="format",
        help="shorthand for --format json",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    unmapped_policy = None if args.unmapped_policy == "defer" else args.unmapped_policy
    results = run_probes(
        enforce_mode=args.enforce,
        unmapped_policy=unmapped_policy,
        runtime_traversal=args.runtime_traversal,
    )
    meta = {
        "enforce_mode": args.enforce,
        "unmapped_policy": args.unmapped_policy,
        "runtime_traversal": args.runtime_traversal,
        "summary": summarize(results),
        "claim_discipline": (
            "Synthetic mode measures MAPPING coverage only. Runtime traversal is "
            "unmeasured until the probes run inside a versioned Hermes runtime "
            "with VINCTOR_HERMES_COVERAGE_LOG set."
        ),
    }

    if args.format == "json":
        print(render_json(results, meta))
    else:
        if args.format == "markdown":
            print(render_markdown(results))
        else:
            print(render_table(results))
        summary = meta["summary"]
        print()
        print(
            "Summary: {mapped} mapped, {unmapped} unmapped, {error} error, "
            "{blocked} blocked.".format(**summary)
        )
        print(
            f"Runtime traversal: {args.runtime_traversal} (synthetic mode does not "
            "observe a real Hermes runtime)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
