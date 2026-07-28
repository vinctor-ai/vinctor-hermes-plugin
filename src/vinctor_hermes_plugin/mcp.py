from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .filesystem import is_filesystem_tool, resolve_filesystem_tool
from .resources import safe_identifier
from .types import Action, MappingResult, Requirement

_UNMAPPED = MappingResult(kind="unmapped")

_GITHUB_METHOD_ACTIONS: dict[str, Action] = {
    "run_workflow": "execute",
    "rerun_workflow_run": "execute",
    "rerun_failed_jobs": "execute",
    "cancel_workflow_run": "write",
    "delete_workflow_run_logs": "delete",
}

_GITHUB_TABLE: dict[str, dict[str, object]] = {
    # Canon kinds (vinctor-conformance): pr, issue, workflow, release,
    # contents, secret - the canon collapses file/code/branch kinds into
    # `contents`. Kinds beyond the canon (collaborator, repo, fork, security,
    # context) cover operations the v1 canon deliberately omits; they remain
    # adapter policy.
    # context / users / search
    "get_me": {"action": "read", "kind": "context", "scope": "global"},
    "get_teams": {"action": "read", "kind": "context", "scope": "global"},
    "get_team_members": {"action": "read", "kind": "context", "scope": "owner"},
    "search_users": {"action": "read", "kind": "context", "scope": "global"},
    "search_repositories": {"action": "read", "kind": "repo", "scope": "global"},
    "search_code": {"action": "read", "kind": "contents", "scope": "global"},
    "search_commits": {"action": "read", "kind": "contents", "scope": "global"},
    # repos / git
    "get_file_contents": {"action": "read", "kind": "contents", "scope": "repo"},
    "get_repository_tree": {"action": "read", "kind": "contents", "scope": "repo"},
    "list_commits": {"action": "read", "kind": "contents", "scope": "repo"},
    "get_commit": {"action": "read", "kind": "contents", "scope": "repo"},
    "list_branches": {"action": "read", "kind": "contents", "scope": "repo"},
    "list_tags": {"action": "read", "kind": "contents", "scope": "repo"},
    "get_tag": {"action": "read", "kind": "contents", "scope": "repo"},
    "list_releases": {"action": "read", "kind": "release", "scope": "repo"},
    "get_latest_release": {"action": "read", "kind": "release", "scope": "repo"},
    "get_release_by_tag": {"action": "read", "kind": "release", "scope": "repo"},
    "get_release": {"action": "read", "kind": "release", "scope": "repo"},
    "list_repository_collaborators": {"action": "read", "kind": "collaborator", "scope": "repo"},
    "create_or_update_file": {"action": "write", "kind": "contents", "scope": "repo"},
    "push_files": {"action": "write", "kind": "contents", "scope": "repo"},
    "create_branch": {"action": "write", "kind": "contents", "scope": "repo"},
    "delete_file": {"action": "delete", "kind": "contents", "scope": "repo"},
    # PKA-150: creating a repository is a write into a NAMESPACE, not the old
    # namespace-less global github/_/repo. Owner comes from `organization`.
    "create_repository": {"action": "write", "kind": "repo", "scope": "namespace"},
    # PKA-149: fork_repository is multi-effect - special-cased in _resolve_github.
    "fork_repository": {"action": "write", "kind": "fork", "scope": "repo"},
    # releases - publishing is externally effective -> deploy (canon)
    "create_release": {"action": "deploy", "kind": "release", "scope": "repo"},
    "publish_release": {"action": "deploy", "kind": "release", "scope": "repo"},
    # issues
    "issue_read": {"action": "read", "kind": "issue", "scope": "repo"},
    "get_issue": {"action": "read", "kind": "issue", "scope": "repo"},
    "list_issues": {"action": "read", "kind": "issue", "scope": "repo"},
    "search_issues": {"action": "read", "kind": "issue", "scope": "flex"},
    "list_issue_types": {"action": "read", "kind": "issue", "scope": "owner"},
    "issue_write": {"action": "write", "kind": "issue", "scope": "repo"},
    "update_issue": {"action": "write", "kind": "issue", "scope": "repo"},
    "add_issue_comment": {"action": "write", "kind": "issue", "scope": "repo"},
    "sub_issue_write": {"action": "write", "kind": "issue", "scope": "repo"},
    "create_issue": {"action": "write", "kind": "issue", "scope": "repo"},
    "update_issue_title": {"action": "write", "kind": "issue", "scope": "repo"},
    "update_issue_body": {"action": "write", "kind": "issue", "scope": "repo"},
    "update_issue_assignees": {"action": "write", "kind": "issue", "scope": "repo"},
    "update_issue_labels": {"action": "write", "kind": "issue", "scope": "repo"},
    "update_issue_milestone": {"action": "write", "kind": "issue", "scope": "repo"},
    "update_issue_type": {"action": "write", "kind": "issue", "scope": "repo"},
    "update_issue_state": {"action": "write", "kind": "issue", "scope": "repo"},
    "add_sub_issue": {"action": "write", "kind": "issue", "scope": "repo"},
    "remove_sub_issue": {"action": "write", "kind": "issue", "scope": "repo"},
    "reprioritize_sub_issue": {"action": "write", "kind": "issue", "scope": "repo"},
    "set_issue_fields": {"action": "write", "kind": "issue", "scope": "repo"},
    # pull requests
    "pull_request_read": {"action": "read", "kind": "pr", "scope": "repo"},
    "get_pull_request": {"action": "read", "kind": "pr", "scope": "repo"},
    "list_pull_requests": {"action": "read", "kind": "pr", "scope": "repo"},
    "search_pull_requests": {"action": "read", "kind": "pr", "scope": "flex"},
    "create_pull_request": {"action": "write", "kind": "pr", "scope": "repo"},
    "update_pull_request": {"action": "write", "kind": "pr", "scope": "repo"},
    "update_pull_request_branch": {"action": "write", "kind": "pr", "scope": "repo"},
    "pull_request_review_write": {"action": "write", "kind": "pr", "scope": "repo"},
    "add_comment_to_pending_review": {"action": "write", "kind": "pr", "scope": "repo"},
    "add_reply_to_pull_request_comment": {"action": "write", "kind": "pr", "scope": "repo"},
    # Canon: write + becomes shipping baseline -> deploy by precedence (the
    # deploy moment is the merge).
    "merge_pull_request": {"action": "deploy", "kind": "pr", "scope": "repo"},
    "update_pull_request_title": {"action": "write", "kind": "pr", "scope": "repo"},
    "update_pull_request_body": {"action": "write", "kind": "pr", "scope": "repo"},
    "update_pull_request_state": {"action": "write", "kind": "pr", "scope": "repo"},
    "update_pull_request_draft_state": {"action": "write", "kind": "pr", "scope": "repo"},
    "request_pull_request_reviewers": {"action": "write", "kind": "pr", "scope": "repo"},
    "create_pull_request_review": {"action": "write", "kind": "pr", "scope": "repo"},
    "submit_pending_pull_request_review": {"action": "write", "kind": "pr", "scope": "repo"},
    "delete_pending_pull_request_review": {"action": "write", "kind": "pr", "scope": "repo"},
    "add_pull_request_review_comment": {"action": "write", "kind": "pr", "scope": "repo"},
    # actions
    "actions_list": {"action": "read", "kind": "workflow", "scope": "repo"},
    "actions_get": {"action": "read", "kind": "workflow", "scope": "repo"},
    "get_job_logs": {"action": "read", "kind": "workflow", "scope": "repo"},
    "actions_run_trigger": {"action": "method", "kind": "workflow", "scope": "repo"},
    "list_workflows": {"action": "read", "kind": "workflow", "scope": "repo"},
    "list_workflow_runs": {"action": "read", "kind": "workflow", "scope": "repo"},
    "list_workflow_jobs": {"action": "read", "kind": "workflow", "scope": "repo"},
    "list_workflow_run_artifacts": {"action": "read", "kind": "workflow", "scope": "repo"},
    "get_workflow": {"action": "read", "kind": "workflow", "scope": "repo"},
    "get_workflow_run": {"action": "read", "kind": "workflow", "scope": "repo"},
    "get_workflow_job": {"action": "read", "kind": "workflow", "scope": "repo"},
    "get_workflow_run_usage": {"action": "read", "kind": "workflow", "scope": "repo"},
    "get_workflow_run_logs": {"action": "read", "kind": "workflow", "scope": "repo"},
    "get_workflow_job_logs": {"action": "read", "kind": "workflow", "scope": "repo"},
    "download_workflow_run_artifact": {"action": "read", "kind": "workflow", "scope": "repo"},
    "run_workflow": {"action": "execute", "kind": "workflow", "scope": "repo"},
    "rerun_workflow_run": {"action": "execute", "kind": "workflow", "scope": "repo"},
    "rerun_failed_jobs": {"action": "execute", "kind": "workflow", "scope": "repo"},
    "cancel_workflow_run": {"action": "write", "kind": "workflow", "scope": "repo"},
    "delete_workflow_run_logs": {"action": "delete", "kind": "workflow", "scope": "repo"},
    # security
    "get_code_scanning_alert": {"action": "read", "kind": "security", "scope": "repo"},
    "list_code_scanning_alerts": {"action": "read", "kind": "security", "scope": "repo"},
    "get_dependabot_alert": {"action": "read", "kind": "security", "scope": "repo"},
    "list_dependabot_alerts": {"action": "read", "kind": "security", "scope": "repo"},
    # secret_protection - canon kind `secret` under the repo scope
    "get_secret_scanning_alert": {"action": "read", "kind": "secret", "scope": "repo"},
    "list_secret_scanning_alerts": {"action": "read", "kind": "secret", "scope": "repo"},
}

_SLACK_TABLE: dict[str, tuple[Action, str]] = {
    "slack_list_channels": ("read", "workspace"),
    "slack_get_users": ("read", "workspace"),
    "slack_get_user_profile": ("read", "workspace"),
    "slack_get_channel_history": ("read", "channel"),
    "slack_get_thread_replies": ("read", "channel"),
    "slack_post_message": ("send", "channel"),
    "slack_reply_to_thread": ("send", "channel"),
    "slack_add_reaction": ("send", "channel"),
    "channels_list": ("read", "workspace"),
    "channels_me": ("read", "workspace"),
    "conversations_unreads": ("read", "workspace"),
    "users_search": ("read", "workspace"),
    "conversations_history": ("read", "channel"),
    "conversations_replies": ("read", "channel"),
    "conversations_search_messages": ("read", "search"),
    "conversations_add_message": ("send", "channel"),
    "conversations_join": ("send", "channel"),
    "conversations_leave": ("send", "channel"),
    "conversations_mark": ("send", "channel"),
    "reactions_add": ("send", "channel"),
    "reactions_remove": ("send", "channel"),
    # Compatibility with shorter Hermes names from early local fixtures.
    # search_messages is workspace-scoped: the canon chat grammar has no
    # pseudo-channel segment for searches.
    "post_message": ("send", "channel"),
    "search_messages": ("read", "workspace"),
}


def split_mcp_tool_name(tool_name: str) -> tuple[str, str] | None:
    return _split_mcp_tool_name(tool_name)


def is_known_mcp_tool(tool_name: str) -> bool:
    parsed = _split_mcp_tool_name(tool_name)
    if parsed is None:
        return False
    server, tool = parsed
    if server == "filesystem":
        return is_filesystem_tool(tool)
    if server == "github":
        return tool in _GITHUB_TABLE
    if server == "slack":
        return tool in _SLACK_TABLE
    return False


def resolve_mcp_tool(tool_name: str, args: dict[str, Any]) -> MappingResult | None:
    parsed = _split_mcp_tool_name(tool_name)
    if parsed is None:
        return None
    server, tool = parsed
    resolvers: dict[str, Callable[[str, dict[str, Any]], MappingResult]] = {
        "filesystem": _resolve_filesystem,
        "github": _resolve_github,
        "slack": _resolve_slack,
    }
    resolver = resolvers.get(server)
    if resolver is None:
        return _UNMAPPED
    return resolver(tool, args)


def _split_mcp_tool_name(tool_name: str) -> tuple[str, str] | None:
    if tool_name.startswith("mcp__"):
        remainder = tool_name.removeprefix("mcp__")
        if "__" not in remainder:
            return None
        server, tool = remainder.split("__", 1)
        return (server, tool) if server and tool else None
    if not tool_name.startswith("mcp_"):
        return None
    remainder = tool_name.removeprefix("mcp_")
    for server in ("filesystem", "github", "slack"):
        prefix = f"{server}_"
        if remainder.startswith(prefix):
            tool = remainder.removeprefix(prefix)
            return (server, tool) if tool else None
    if "_" not in remainder:
        return None
    server, tool = remainder.split("_", 1)
    return (server, tool) if server and tool else None


def _resolve_filesystem(tool: str, args: dict[str, Any]) -> MappingResult:
    # PKA-156: one resolver for both surfaces. The MCP surface keeps a
    # credential-shaped move SOURCE as its primary pair, which is what the
    # canon's move-file-secret-source vector pins for this spelling.
    result = resolve_filesystem_tool(tool, args, secret_source_is_primary=True)
    # An unknown tool on a known server stays the documented `unmapped` escape
    # hatch; a tool we DO recognize and cannot express fails closed inside the
    # shared resolver.
    return _UNMAPPED if result is None else result


def _resolve_github(tool: str, args: dict[str, Any]) -> MappingResult:
    desc = _GITHUB_TABLE.get(tool)
    if desc is None:
        return _UNMAPPED
    action = desc["action"]
    if action == "method":
        method = _string_field(args, "method")
        if method is None:
            return _UNMAPPED
        method_action = _GITHUB_METHOD_ACTIONS.get(method)
        if method_action is None:
            return _UNMAPPED
        action = method_action
    if tool == "fork_repository":
        return _resolve_github_fork(args)
    return _github_resource(action, desc, args)


def _resolve_github_fork(args: dict[str, Any]) -> MappingResult:
    """PKA-149: fork_repository is three effects, not one.

    The primary is the source fork (both owner AND repo must be present - never
    fork an ambiguous source), unchanged so existing fork grants keep working.
    A fork ALSO reads the source repo's contents (it copies them) and writes a
    NEW repository into the destination namespace named by `organization` (the
    PKA-150 github/<owner>/_/repo form). Charging only the source fork let a fork
    grant on acme/api create a repository - and a copy of its contents - inside
    an org the operator never authorized; the boundary denies unless every
    member permits.
    """
    owner = _safe(args, "owner")
    repo = _safe(args, "repo")
    if not owner or not repo:
        return _UNMAPPED  # ambiguous source, like every other repo-scoped write
    dest = _destination_namespace(args)
    return MappingResult(
        kind="mapped",
        action="write",
        resource=f"github/{owner}/{repo}/fork",
        source="builtin",
        also_requires=(
            Requirement(action="read", resource=f"github/{owner}/{repo}/contents"),
            Requirement(action="write", resource=f"github/{dest}/_/repo"),
        ),
    )


def _destination_namespace(args: dict[str, Any]) -> str:
    """The owner segment of a namespace-write resource (github/<owner>/_/repo):
    the `organization` arg. Absent means the caller's own account, which the
    plugin cannot name, so it degrades to the deliberately-coarse `_` - an
    operator who wants to allow that grants github/_/_/repo explicitly. Never
    guessed from the source owner: a fork into acme's own org is a different
    grant from a fork into the agent's account."""
    org = _string_field(args, "organization")
    return org if org else "_"


def _github_resource(
    action: Action, desc: dict[str, object], args: dict[str, Any]
) -> MappingResult:
    owner = _safe(args, "owner")
    repo = _safe(args, "repo")
    kind = str(desc["kind"])
    scope = str(desc.get("scope", "repo"))
    is_read = action == "read"

    if scope == "global":
        resource = f"github/_/{kind}"
    elif scope == "namespace":
        # PKA-150: a write INTO a namespace. Degrades to the coarse
        # github/_/_/repo when the namespace is unknown, never to nothing - a
        # create still makes a repo SOMEWHERE.
        resource = f"github/{_destination_namespace(args)}/_/{kind}"
    elif scope == "owner":
        if owner:
            resource = f"github/{owner}/_/{kind}"
        elif is_read:
            resource = f"github/_/{kind}"
        else:
            return _UNMAPPED
    elif scope == "flex":
        if owner and repo:
            resource = f"github/{owner}/{repo}/{kind}"
        elif owner:
            resource = f"github/{owner}/_/{kind}"
        else:
            resource = f"github/_/{kind}"
    else:
        if owner and repo:
            resource = f"github/{owner}/{repo}/{kind}"
        elif is_read:
            resource = f"github/{owner}/_/{kind}" if owner else f"github/_/{kind}"
        else:
            return _UNMAPPED
    return MappingResult(kind="mapped", action=action, resource=resource, source="builtin")


def _resolve_slack(tool: str, args: dict[str, Any]) -> MappingResult:
    # Canon resource grammar: chat/slack/<channel>; workspace-scoped
    # operations bind the platform prefix chat/slack.
    desc = _SLACK_TABLE.get(tool)
    if desc is None:
        return _UNMAPPED
    action, scope = desc
    if scope == "workspace":
        return MappingResult(kind="mapped", action=action, resource="chat/slack", source="builtin")
    if scope == "channel":
        channel = _string_field(args, "channel_id")
        if channel:
            return MappingResult(
                kind="mapped",
                action=action,
                resource=f"chat/slack/{channel}",
                source="builtin",
            )
        if action == "send":
            return _UNMAPPED
        return MappingResult(kind="mapped", action="read", resource="chat/slack", source="builtin")
    if scope == "search":
        channel = _string_field(args, "filter_in_channel")
        resource = f"chat/slack/{channel}" if channel else "chat/slack"
        return MappingResult(kind="mapped", action="read", resource=resource, source="builtin")
    return _UNMAPPED


def _string_field(args: dict[str, Any], field: str) -> str | None:
    value = args.get(field)
    if not isinstance(value, str) or not value or "\0" in value:
        return None
    return value


def _safe(args: dict[str, Any], field: str) -> str | None:
    value = _string_field(args, field)
    return safe_identifier(value, default=None) if value else None
