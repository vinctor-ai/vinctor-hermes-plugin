from __future__ import annotations

import fnmatch
import re
import shlex
from typing import Any

from .config import Config, Rule
from .filesystem import resolve_filesystem_tool
from .mcp import resolve_mcp_tool
from .resources import (
    network_resource_for_url,
    network_resource_for_urls,
    repo_or_secret_resource,
    safe_identifier,
)
from .types import Action, MappingResult, Requirement

# Which ARGUMENT an operator rule matches on for the native file tools. This is
# config input selection only - the resolution table lives in filesystem.py, and
# PKA-156 is what happens when a second copy of that table drifts from it.
_CONFIG_PATH_RULE_TOOLS = {
    "read_file",
    "read_text_file",
    "read_media_file",
    "list_directory",
    "directory_tree",
    "get_file_info",
    "write_file",
    "edit_file",
    "create_directory",
    "move_file",
    "delete_file",
    "delete_directory",
    "remove_directory",
}
_MEMORY_TOOLS = {"memory_search", "recall_memory", "search_memory"}
_SESSION_TOOLS = {"session_search", "search_sessions"}
_TEST_COMMANDS = {"pytest", "tox", "nox"}
_DEPLOY_TOKENS = {"deploy", "kubectl", "helm", "terraform", "vercel", "fly", "railway"}
_BROWSER_READ_TOOLS = {
    "browser_snapshot",
    "browser_get_images",
    "browser_vision",
    "browser_console",
}
_BROWSER_ACTION_TOOLS = {
    "browser_click",
    "browser_type",
    "browser_scroll",
    "browser_back",
    "browser_press",
    "browser_dialog",
}


def resolve_tool_call(tool_name: str, args: dict[str, Any] | None, config: Config) -> MappingResult:
    safe_args = args if isinstance(args, dict) else {}
    static_terminal_result: MappingResult | None = None
    if tool_name == "terminal":
        command = _string_arg(safe_args, "command")
        if command:
            control_result = _shell_control_result(command)
            if control_result is not None:
                return control_result
            static_words, static_words_safe, commented = _scan_static_shell_words(command)
            if not static_words_safe:
                if re.search(r"(?:^|\s)push(?:\s|$)", command):
                    return _unsafe_shell_result()
                terminal_result = _resolve_terminal(safe_args)
                if terminal_result.resource == "shell/git" or (
                    terminal_result.resource or ""
                ).startswith("github/"):
                    return _unsafe_shell_result()
                return (
                    terminal_result
                    if terminal_result.kind != "unmapped"
                    else _unsafe_shell_result()
                )
            if _unsafe_shell_reinterpreter(static_words):
                return _unsafe_shell_result()
            static_terminal_result = _static_git_command(command)
            if commented and static_terminal_result is None:
                return _unsafe_shell_result()
            if static_terminal_result is not None and (
                static_terminal_result.kind == "unmapped"
                or static_terminal_result.action == "delete"
            ):
                return static_terminal_result
    config_result = _resolve_config(tool_name, safe_args, config)
    if config_result.kind != "unmapped":
        if tool_name == "terminal":
            # Shell classification produces no multi-effect results, and its
            # fail-closed refusals (an unclassifiable command) are precisely
            # what operator config is documented to map. Nothing to preserve
            # here, and preserving the refusal would close the escape hatch.
            return config_result
        return _with_builtin_requirements(
            config_result, _resolve_builtin(tool_name, safe_args, static_terminal_result)
        )
    return _resolve_builtin(tool_name, safe_args, static_terminal_result)


def _with_builtin_requirements(
    config_result: MappingResult, builtin: MappingResult
) -> MappingResult:
    """PKA-173: an operator rule may ADD a charge; it may never SUBTRACT an effect.

    Operator config resolves BEFORE the builtin classifiers, so a rule naming a
    tool used to return a mapping with no `also_requires` at all: the classifier
    that builds move_file's three effects was never reached, and one rule undid
    PKA-145, PKA-148 and PKA-149 at once.

    Unioning only the classifier's `also_requires` was the second wrong answer.
    move_file's classifier PRIMARY is the destination write, so dropping it let
    a plausible rule - "a move whose source is under /tmp is a scratch write",
    matching on `source` - pair a /tmp-scoped grant with a write into ~/.ssh. So
    the classifier's FULL required set is unioned in, primary included, minus
    the rule's own pair.

    A refusal is not overridable either: the classifier recognized the call and
    could not express one of its targets, so authorizing the rule's single pair
    would run the whole call. That is the same rule taken to its limit - config
    cannot subtract the refusal.

    A single-effect classifier has nothing to union: its primary IS the whole
    effect, so unioning it back would double-charge every renamed read and break
    the documented remapping escape hatch. Those mappings are unchanged.
    """
    if builtin.kind == "error":
        return builtin
    if builtin.kind != "mapped" or not builtin.also_requires:
        return config_result
    own = (config_result.action, config_result.resource)
    also: list[Requirement] = []
    # A `mapped` result always carries its primary pair; it leads the union so
    # the classifier's own pair can never be the one that goes missing.
    classifier_primary = Requirement(action=builtin.action, resource=builtin.resource)
    for requirement in (classifier_primary, *builtin.also_requires):
        if (requirement.action, requirement.resource) == own or requirement in also:
            continue
        also.append(requirement)
    if not also:
        return config_result
    return MappingResult(
        kind=config_result.kind,
        action=config_result.action,
        resource=config_result.resource,
        source=config_result.source,
        reason=config_result.reason,
        also_requires=tuple(also),
    )


def _resolve_builtin(
    tool_name: str, safe_args: dict[str, Any], static_terminal_result: MappingResult | None
) -> MappingResult:
    mcp_result = resolve_mcp_tool(tool_name, safe_args)
    if mcp_result is not None:
        return mcp_result
    # PKA-156: ONE filesystem resolver, shared with the mcp__filesystem__*
    # spellings. The native surface keeps the destination as a move's primary
    # pair, which is what the canon's hermes-move-file-secret-source vector
    # pins for this spelling.
    filesystem_result = resolve_filesystem_tool(
        tool_name, safe_args, secret_source_is_primary=False
    )
    if filesystem_result is not None:
        return filesystem_result
    if tool_name == "patch":
        return _resolve_patch(safe_args)
    if tool_name == "terminal":
        if static_terminal_result is not None:
            return static_terminal_result
        return _resolve_terminal(safe_args)
    if tool_name == "process":
        return _resolve_process(safe_args)
    if tool_name == "execute_code":
        return MappingResult(
            kind="mapped", action="execute", resource="code/python", source="builtin"
        )
    if tool_name == "memory":
        return _resolve_memory(safe_args)
    if tool_name in _MEMORY_TOOLS:
        return MappingResult(
            kind="mapped", action="read", resource="memory/search", source="builtin"
        )
    if tool_name in _SESSION_TOOLS:
        return MappingResult(
            kind="mapped", action="read", resource="session/search", source="builtin"
        )
    if tool_name == "cronjob":
        return _resolve_cronjob(safe_args)
    if tool_name == "delegate_task":
        return MappingResult(
            kind="mapped", action="execute", resource="agent/delegate", source="builtin"
        )
    if tool_name == "web_search":
        return MappingResult(kind="mapped", action="send", resource="web/search", source="builtin")
    if tool_name == "web_extract":
        return _resolve_web_extract(safe_args)
    if tool_name.startswith("browser_"):
        return _resolve_browser(tool_name, safe_args)
    if tool_name == "send_message":
        return _resolve_send_message(safe_args)
    return MappingResult(kind="unmapped")


def _resolve_config(tool_name: str, args: dict[str, Any], config: Config) -> MappingResult:
    command = _string_arg(args, "command")
    candidates = []
    for rule in config.rules:
        if rule.tool != tool_name:
            continue
        value = _rule_value(rule, tool_name, args, command)
        if value is None:
            continue
        if _matches(rule, value):
            candidates.append(rule)
    if not candidates:
        return MappingResult(kind="unmapped")
    rule = sorted(candidates, key=_specificity_key)[0]
    return MappingResult(
        kind="mapped",
        action=rule.action,
        resource=rule.resource,
        source="config",
    )


def _resolve_file_path(action: str, args: dict[str, Any]) -> MappingResult:
    raw_path = _string_arg(args, "path") or _string_arg(args, "file_path")
    if not raw_path and action == "write":
        raw_path = _string_arg(args, "destination") or _string_arg(args, "dest")
    if not raw_path and action == "delete":
        raw_path = _string_arg(args, "target")
    if not raw_path:
        return MappingResult(kind="error", reason="malformed_payload")
    resource = repo_or_secret_resource(raw_path)
    if resource is None:
        return MappingResult(kind="error", reason="parse_unsafe")
    return MappingResult(kind="mapped", action=action, resource=resource, source="builtin")


def _resolve_patch(args: dict[str, Any]) -> MappingResult:
    """PKA-145: an envelope carries N targets, so it needs N requirements.

    Previously only the FIRST matching operation was authorized, so bundling an
    `Add File` alongside a `Delete File` wrote a path nobody authorized.
    """
    raw_patch = _string_arg(args, "patch")
    if not raw_patch:
        return _resolve_file_path("write", args)

    targets: list[tuple[str, str]] = [
        ("delete", path) for path in _patch_paths(raw_patch, "Delete File")
    ]
    targets += [
        ("write", path)
        for operation in ("Update File", "Add File")
        for path in _patch_paths(raw_patch, operation)
    ]
    if not targets:
        return _resolve_file_path("write", args)

    requirements: list[Requirement] = []
    for action, raw_path in targets:
        resource = repo_or_secret_resource(raw_path)
        if resource is None:
            return MappingResult(kind="error", reason="parse_unsafe")
        requirement = Requirement(action=action, resource=resource)
        if requirement not in requirements:
            requirements.append(requirement)

    # The primary is the pair reported as this call's single canon-comparable
    # mapping; every other target rides in also_requires. Writes lead so an
    # envelope that both writes and deletes still reports the write it performs.
    primary = next((r for r in requirements if r.action == "write"), requirements[0])
    rest = tuple(r for r in requirements if r is not primary)
    return MappingResult(
        kind="mapped",
        action=primary.action,
        resource=primary.resource,
        source="builtin",
        also_requires=rest,
    )


def _mapped_path(action: str, raw_path: str) -> MappingResult:
    resource = repo_or_secret_resource(raw_path)
    if resource is None:
        return MappingResult(kind="error", reason="parse_unsafe")
    return MappingResult(kind="mapped", action=action, resource=resource, source="builtin")


def _patch_paths(raw_patch: str, operation: str) -> list[str]:
    """Every target of one patch operation. Arity is data, so N targets ⇒ N."""
    pattern = re.compile(rf"^\*\*\* {re.escape(operation)}: (.+)$", re.MULTILINE)
    return [match.group(1).strip() for match in pattern.finditer(raw_patch)]


def _resolve_terminal(args: dict[str, Any]) -> MappingResult:
    command = _string_arg(args, "command")
    if not command:
        return MappingResult(kind="error", reason="malformed_payload")
    control_result = _shell_control_result(command)
    if control_result is not None:
        return control_result
    git_result = _static_git_command(command)
    if git_result is not None:
        return git_result
    normalized = _normalize_command(command)
    tokens = _split_command(normalized)
    if not tokens:
        return MappingResult(kind="unmapped")

    if _is_secret_read_command(tokens):
        return MappingResult(
            kind="mapped", action="read", resource="secret/env", source="builtin"
        )

    git_result = _git_command(tokens)
    if git_result is not None:
        return git_result
    shell_delete = _shell_delete(tokens)
    if shell_delete is not None:
        return shell_delete
    docker = _docker_command(tokens)
    if docker is not None:
        return docker
    gh = _github_cli_command(tokens)
    if gh is not None:
        return gh
    npm = _npm_command(tokens)
    if npm is not None:
        return npm
    branch = _branch_creation(tokens)
    if branch:
        return MappingResult(
            kind="mapped",
            action="write",
            resource=f"repo/branch/{branch}",
            source="builtin",
        )
    if _is_test_command(tokens):
        return MappingResult(kind="mapped", action="execute", resource="ci/test", source="builtin")
    if _is_build_command(tokens):
        return MappingResult(
            kind="mapped", action="execute", resource="ci/build", source="builtin"
        )
    infra_or_platform = _infra_or_platform_deploy(tokens)
    if infra_or_platform is not None:
        return infra_or_platform
    if _is_deploy_command(tokens):
        return MappingResult(
            kind="mapped",
            action="execute",
            resource=f"deploy/{_deploy_env(tokens)}",
            source="builtin",
        )
    return MappingResult(kind="unmapped")


def _infra_or_platform_deploy(tokens: list[str]) -> MappingResult | None:
    # D-6: tool-specific infra-apply (parity with the Claude Code / Codex hooks)
    # and platform-deploy CLIs (the `deploy` verb per D-2). Anything not matched
    # here falls through to the generic `deploy/{env}` bucket below (unchanged).
    def _infra(resource: str) -> MappingResult:
        return MappingResult(kind="mapped", action="execute", resource=resource, source="builtin")

    def _deploy(resource: str) -> MappingResult:
        return MappingResult(kind="mapped", action="deploy", resource=resource, source="builtin")

    if tokens[:2] == ["kubectl", "apply"]:
        return _infra("infra/k8s/apply")
    if tokens[:2] == ["terraform", "apply"]:
        return _infra("infra/terraform/apply")
    if tokens[0] == "helm" and len(tokens) >= 2 and tokens[1] in {"install", "upgrade"}:
        return _infra("infra/helm/apply")
    if tokens[0] == "vercel" and (
        len(tokens) == 1 or tokens[1] == "deploy" or tokens[1].startswith("-")
    ):
        return _deploy("vercel/app")
    if tokens[0] in {"fly", "flyctl"} and "deploy" in tokens:
        return _deploy("fly/app")
    if tokens[0] == "railway" and ("up" in tokens or "deploy" in tokens):
        return _deploy("railway/app")
    return None


def _resolve_process(args: dict[str, Any]) -> MappingResult:
    action = (_string_arg(args, "action") or "").lower()
    if not action:
        return MappingResult(kind="error", reason="malformed_payload")
    if action == "list":
        return MappingResult(
            kind="mapped", action="read", resource="process/list", source="builtin"
        )
    session_id = _safe_arg(args, "session_id", default="unknown")
    if session_id is None:
        return MappingResult(kind="error", reason="parse_unsafe")
    if action in {"poll", "log", "wait"}:
        return MappingResult(
            kind="mapped", action="read", resource=f"process/{session_id}", source="builtin"
        )
    if action in {"write", "submit"}:
        return MappingResult(
            kind="mapped", action="write", resource=f"process/{session_id}", source="builtin"
        )
    if action in {"kill", "close"}:
        return MappingResult(
            kind="mapped", action="delete", resource=f"process/{session_id}", source="builtin"
        )
    if action == "run":
        return MappingResult(
            kind="mapped", action="execute", resource=f"process/{session_id}", source="builtin"
        )
    return MappingResult(kind="unmapped")


def _resolve_memory(args: dict[str, Any]) -> MappingResult:
    action = (_string_arg(args, "action") or "").lower()
    target = _safe_arg(args, "target", default="memory")
    if target is None:
        return MappingResult(kind="error", reason="parse_unsafe")
    if action in {"add", "replace"}:
        return MappingResult(
            kind="mapped", action="write", resource=f"memory/{target}", source="builtin"
        )
    if action == "remove":
        return MappingResult(
            kind="mapped", action="delete", resource=f"memory/{target}", source="builtin"
        )
    if action in {"search", "read", "list"}:
        return MappingResult(
            kind="mapped", action="read", resource=f"memory/{target}", source="builtin"
        )
    return MappingResult(kind="error", reason="malformed_payload")


def _resolve_cronjob(args: dict[str, Any]) -> MappingResult:
    action = (_string_arg(args, "action") or "").lower()
    if not action:
        return MappingResult(kind="error", reason="malformed_payload")
    if action == "list":
        return MappingResult(kind="mapped", action="read", resource="cron/jobs", source="builtin")
    job_id = _safe_arg(args, "job_id", default="new")
    if job_id is None:
        return MappingResult(kind="error", reason="parse_unsafe")
    resource = f"cron/job/{job_id}"
    if action in {"create", "update", "pause", "resume"}:
        return MappingResult(kind="mapped", action="write", resource=resource, source="builtin")
    if action in {"remove", "delete"}:
        return MappingResult(kind="mapped", action="delete", resource=resource, source="builtin")
    if action in {"run", "trigger"}:
        return MappingResult(kind="mapped", action="execute", resource=resource, source="builtin")
    return MappingResult(kind="unmapped")


def _resolve_web_extract(args: dict[str, Any]) -> MappingResult:
    urls = args.get("urls")
    if isinstance(urls, list):
        string_urls = [url for url in urls if isinstance(url, str) and url]
        if len(string_urls) != len(urls):
            return MappingResult(kind="error", reason="malformed_payload")
        resource = network_resource_for_urls(string_urls)
    else:
        url = _string_arg(args, "url")
        resource = network_resource_for_url(url) if url else None
    if resource is None:
        return MappingResult(kind="error", reason="malformed_payload")
    return MappingResult(kind="mapped", action="send", resource=resource, source="builtin")


def _resolve_browser(tool_name: str, args: dict[str, Any]) -> MappingResult:
    if tool_name in {"browser_navigate", "browser_goto", "browser_open"}:
        url = _string_arg(args, "url")
        resource = network_resource_for_url(url) if url else None
        if resource is None:
            return MappingResult(kind="error", reason="malformed_payload")
        return MappingResult(kind="mapped", action="send", resource=resource, source="builtin")
    if tool_name == "browser_cdp":
        return MappingResult(
            kind="mapped", action="execute", resource="browser/cdp", source="builtin"
        )
    if tool_name in _BROWSER_READ_TOOLS:
        return MappingResult(
            kind="mapped", action="read", resource="browser/page", source="builtin"
        )
    if tool_name in _BROWSER_ACTION_TOOLS:
        return MappingResult(
            kind="mapped", action="execute", resource="browser/action", source="builtin"
        )
    return MappingResult(kind="unmapped")


def _resolve_send_message(args: dict[str, Any]) -> MappingResult:
    action = (_string_arg(args, "action") or "send").lower()
    if action == "list":
        return MappingResult(
            kind="mapped", action="read", resource="message/list", source="builtin"
        )
    target = _safe_arg(args, "target", default=None)
    if target is None:
        return MappingResult(kind="error", reason="malformed_payload")
    return MappingResult(
        kind="mapped", action="send", resource=f"message/{target}", source="builtin"
    )


def _rule_value(
    rule: Rule,
    tool_name: str,
    args: dict[str, Any],
    command: str | None,
) -> str | None:
    if rule.input_field:
        return _string_arg(args, rule.input_field)
    if tool_name == "terminal":
        return _normalize_command(command or "")
    if tool_name in _CONFIG_PATH_RULE_TOOLS or tool_name == "patch":
        return _string_arg(args, "path") or _string_arg(args, "file_path")
    return tool_name


def _matches(rule: Rule, value: str) -> bool:
    if rule.match_type == "exact":
        return value == rule.pattern
    if rule.match_type == "prefix":
        return value == rule.pattern or value.startswith(f"{rule.pattern} ")
    return fnmatch.fnmatchcase(value, rule.pattern)


def _specificity_key(rule: Rule) -> tuple[int, int, int, int]:
    match_rank = {"exact": 0, "prefix": 1, "glob": 2}[rule.match_type]
    literal_tokens = len([token for token in re.split(r"\s+", rule.pattern) if "*" not in token])
    wildcard_count = rule.pattern.count("*")
    return (rule.priority, match_rank, -literal_tokens, wildcard_count, -len(rule.pattern))


def _normalize_command(command: str) -> str:
    return " ".join(command.strip().split())


def _scan_static_shell_words(command: str) -> tuple[list[str], bool, bool]:
    words: list[str] = []
    current: list[str] = []
    started = False
    quote: str | None = None

    def result(safe: bool, commented: bool = False) -> tuple[list[str], bool, bool]:
        complete = list(words)
        if started:
            complete.append("".join(current))
        return complete, safe, commented

    index = 0
    while index < len(command):
        char = command[index]
        next_char = command[index + 1] if index + 1 < len(command) else ""
        if char in {"\0", "\n", "\r"}:
            return result(False)

        if quote == "single":
            if char == "'":
                quote = None
            else:
                current.append(char)
            index += 1
            continue
        if quote == "ansi":
            if char == "'":
                quote = None
            elif char == "\\":
                return result(False)
            else:
                current.append(char)
            index += 1
            continue
        if quote == "double":
            if char == '"':
                quote = None
            elif char in {"$", "`"}:
                return result(False)
            elif char == "\\":
                if not next_char or next_char in {"\n", "\r"}:
                    return result(False)
                if next_char in {"$", "`", '"', "\\"}:
                    current.append(next_char)
                    index += 1
                else:
                    current.append(char)
            else:
                current.append(char)
            index += 1
            continue

        if char in {" ", "\t", "\v", "\f"}:
            if started:
                words.append("".join(current))
                current = []
                started = False
            index += 1
            continue
        if char == "#" and not started:
            return result(True, commented=True)
        if char == "'":
            quote = "single"
            started = True
            index += 1
            continue
        if char == '"':
            quote = "double"
            started = True
            index += 1
            continue
        if char == "$" and next_char in {"'", '"'}:
            quote = "ansi" if next_char == "'" else "double"
            started = True
            index += 2
            continue
        if char in {"$", "`", "*", "?", "[", "{", "}"}:
            return result(False)
        if char == "\\":
            if not next_char or next_char in {"\n", "\r"}:
                return result(False)
            current.append(next_char)
            started = True
            index += 2
            continue
        if char in {";", "&", "|", "<", ">", "(", ")"}:
            return result(False)
        current.append(char)
        started = True
        index += 1

    if quote is not None:
        return result(False)
    return result(True)


_SHELL_REINTERPRETERS = frozenset(
    {"sh", "ash", "bash", "zsh", "dash", "ksh", "csh", "tcsh", "fish"}
)
_UNBOUNDED_EXECUTORS = frozenset({"ssh", "awk", "gawk", "mawk", "nawk"})
_CODE_REINTERPRETER_FLAGS: dict[str, tuple[str, ...]] = {
    "node": (r"^-e(?:$|.)", r"^--eval(?:=|$)", r"^-p(?:$|.)", r"^--print(?:=|$)"),
    "nodejs": (r"^-e(?:$|.)", r"^--eval(?:=|$)", r"^-p(?:$|.)", r"^--print(?:=|$)"),
    "perl": (r"^-[eE](?:$|.)",),
    "php": (r"^-r(?:$|.)",),
    "ruby": (r"^-e(?:$|.)",),
    "lua": (r"^-e(?:$|.)",),
    "r": (r"^-e(?:$|.)", r"^--expression(?:=|$)"),
    "rscript": (r"^-e(?:$|.)", r"^--expression(?:=|$)"),
    "su": (r"^-c(?:$|.)", r"^--command(?:=|$)"),
    "env": (r"^-[^-]*S(?:$|.)", r"^--split-string(?:=|$)"),
}


def _unsafe_shell_reinterpreter(words: list[str]) -> bool:
    for index, word in enumerate(words):
        executable = word.rsplit("/", 1)[-1].lower()
        if executable == "eval":
            return True
        if executable in _UNBOUNDED_EXECUTORS:
            return True
        code_flags = (
            (r"^-c(?:$|.)",)
            if re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", executable)
            else _CODE_REINTERPRETER_FLAGS.get(executable)
        )
        if code_flags and any(
            re.match(flag, arg)
            for flag in code_flags
            for arg in words[index + 1 :]
        ):
            return True
        if executable not in _SHELL_REINTERPRETERS:
            continue
        if any(re.match(r"^-[^-]*c", arg) for arg in words[index + 1 :]):
            return True
    return False


def _unsafe_shell_result() -> MappingResult:
    return MappingResult(kind="unmapped", reason="unsafe_shell")


_UNSAFE_GIT_GLOBAL_VALUE_OPTIONS = frozenset({"-c", "--config-env"})
_GIT_GLOBAL_FLAG_OPTIONS = frozenset(
    {
        "-p",
        "--paginate",
        "-P",
        "--no-pager",
        "--no-replace-objects",
        "--bare",
        "--literal-pathspecs",
        "--glob-pathspecs",
        "--noglob-pathspecs",
        "--icase-pathspecs",
        "--no-optional-locks",
        "--no-lazy-fetch",
        "--no-advice",
    }
)
_TRUSTED_GIT_EXECUTABLES = frozenset(
    {"git", "/bin/git", "/usr/bin/git", "/usr/local/bin/git", "/opt/homebrew/bin/git"}
)
_GIT_PREFIX_WRAPPERS = frozenset({"command", "env"})
_STANDARD_GIT_SCHEMES = frozenset({"file", "git", "http", "https", "ssh"})


def _is_destructive_push_argument(token: str) -> bool:
    option = token.partition("=")[0]
    return (
        token in {"-f", "--force"}
        or _is_force_with_lease(token)
        or (option.startswith("--de") and "--delete".startswith(option))
        or (option.startswith("--m") and "--mirror".startswith(option))
        or (option.startswith("--pru") and "--prune".startswith(option))
        or bool(re.fullmatch(r"-[dfu]*[df][dfu]*", token))
        or (token.startswith(":") and len(token) > 1)
        or (token.startswith("+") and len(token) > 1)
    )


def _is_allowed_push_option(token: str) -> bool:
    return (
        _is_destructive_push_argument(token)
        or token in {"-u", "--set-upstream", "--tags"}
    )


def _is_explicit_safe_remote(token: str) -> bool:
    scheme_match = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*)://", token)
    if scheme_match:
        return scheme_match.group(1).lower() in _STANDARD_GIT_SCHEMES
    if re.match(r"^(?:[^/@\s]+@)?[^:/\s]+:.+", token):
        return True
    return token in {".", ".."} or token.startswith(("/", "./", "../"))


def _unsafe_git_execution_options(tokens: list[str]) -> bool:
    subcommand = tokens[1] if len(tokens) > 1 else ""
    args = tokens[2:]
    for token in args:
        option = token.split("=", 1)[0]
        scheme_match = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*)://", token)
        if (
            subcommand in {"fetch", "pull", "clone", "push"}
            and scheme_match
            and scheme_match.group(1).lower()
            not in _STANDARD_GIT_SCHEMES
        ):
            return True
        if (
            option == "--ext-diff"
            or (option.startswith("--ext-d") and "--ext-diff".startswith(option))
            or option == "--textconv"
            or (option.startswith("--textc") and "--textconv".startswith(option))
        ):
            return True
        if subcommand in {"fetch", "pull", "clone"} and (
            (
                (
                    option.startswith("--u")
                    if subcommand == "clone"
                    else option.startswith("--upl")
                )
                and "--upload-pack".startswith(option)
            )
            or (
                (
                    option.startswith("--no-u")
                    if subcommand == "clone"
                    else option.startswith("--no-upl")
                )
                and "--no-upload-pack".startswith(option)
            )
        ):
            return True
        if subcommand == "clone" and re.match(r"^-[^-]*u", token):
            return True
        if subcommand == "push" and (
            (option.startswith("--rece") and "--receive-pack".startswith(option))
            or (
                option.startswith("--no-rece")
                and "--no-receive-pack".startswith(option)
            )
            or (option.startswith("--e") and "--exec".startswith(option))
            or (option.startswith("--no-e") and "--no-exec".startswith(option))
        ):
            return True
    if subcommand in {"fetch", "pull"} and any(token.startswith("-") for token in args):
        return True
    if subcommand == "push" and any(
        token.startswith("-") and not _is_allowed_push_option(token) for token in args
    ):
        return True
    if subcommand in {"fetch", "pull"} or (
        subcommand == "push"
        and not any(_is_destructive_push_argument(token) for token in args)
    ):
        target = next((token for token in args if not token.startswith("-")), None)
        return target is None or not _is_explicit_safe_remote(target)
    return False


def _resolve_static_git_tokens(tokens: list[str]) -> tuple[list[str] | None, bool]:
    git_index = 1 if tokens and tokens[0] == "!" else 0
    while git_index < len(tokens) and tokens[git_index] in _GIT_PREFIX_WRAPPERS:
        git_index += 1

    if git_index >= len(tokens) or tokens[git_index] not in _TRUSTED_GIT_EXECUTABLES:
        has_later_git = any(
            token.rsplit("/", 1)[-1] == "git" for token in tokens[git_index:]
        )
        return None, not has_later_git

    cursor = git_index + 1
    while cursor < len(tokens):
        token = tokens[cursor]
        if not token.startswith("-"):
            command_tokens = ["git", *tokens[cursor:]]
            if _unsafe_git_execution_options(command_tokens) or (
                command_tokens[1] in {"fetch", "pull", "clone", "push"}
                and any("::" in word for word in command_tokens[2:])
            ):
                return None, False
            return command_tokens, True
        if token in _UNSAFE_GIT_GLOBAL_VALUE_OPTIONS or any(
            token.startswith(f"{option}=")
            for option in _UNSAFE_GIT_GLOBAL_VALUE_OPTIONS
        ):
            return None, False
        if token in _GIT_GLOBAL_FLAG_OPTIONS:
            cursor += 1
            continue
        return None, False
    return None, False


def _static_git_command(command: str) -> MappingResult | None:
    tokens, safe, _ = _scan_static_shell_words(command)
    if not safe:
        return None
    git_tokens, resolved = _resolve_static_git_tokens(tokens)
    if not resolved:
        return _unsafe_shell_result()
    if git_tokens is None:
        return None
    return _git_command(git_tokens) or _unsafe_shell_result()


def _shell_control_result(command: str) -> MappingResult | None:
    unsupported, pipe_count = _scan_shell_control_operators(command)
    if unsupported or pipe_count > 1:
        return _unsafe_shell_result()
    if pipe_count == 0:
        return None
    pipe_result = _pipe_to_shell(_normalize_command(command))
    if pipe_result is not None and pipe_result.kind == "mapped":
        return pipe_result
    return _unsafe_shell_result()


def _scan_shell_control_operators(command: str) -> tuple[bool, int]:
    quote: str | None = None
    pipe_count = 0
    index = 0

    while index < len(command):
        char = command[index]
        next_char = command[index + 1] if index + 1 < len(command) else ""

        if char in {"\0", "\r", "\n"}:
            return True, pipe_count
        if quote == "single":
            if char == "'":
                quote = None
            index += 1
            continue
        if char == "\\":
            if not next_char or next_char in {"\r", "\n"}:
                return True, pipe_count
            index += 2
            continue
        if char == "'" and quote is None:
            quote = "single"
            index += 1
            continue
        if char == '"':
            quote = None if quote == "double" else "double"
            index += 1
            continue
        if char == "`" or (char == "$" and next_char == "("):
            return True, pipe_count
        if quote == "double":
            index += 1
            continue
        if char == "|":
            if next_char == "|":
                return True, pipe_count
            pipe_count += 1
            index += 2 if next_char == "&" else 1
            continue
        if char in {";", "&", "<", ">", "(", ")"}:
            return True, pipe_count
        index += 1

    return quote is not None, pipe_count


def _split_command(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _branch_creation(tokens: list[str]) -> str | None:
    if len(tokens) >= 4 and tokens[:3] == ["git", "switch", "-c"]:
        return tokens[3]
    if len(tokens) >= 4 and tokens[:3] == ["git", "checkout", "-b"]:
        return tokens[3]
    if len(tokens) >= 4 and tokens[:3] == ["git", "branch", "-m"]:
        return tokens[3]
    if len(tokens) >= 3 and tokens[:2] == ["git", "branch"] and not tokens[2].startswith("-"):
        return tokens[2]
    return None


# Canon (vinctor-conformance): local git operations classify over shell/git;
# `git push` classifies over the push remote's repo - write
# github/<owner>/<repo>/contents, or delete for the force spellings (a force
# push destroys the remote ref's previous history).
_GIT_READ_SUBCOMMANDS = {"status", "log", "diff", "show", "fetch", "blame", "describe", "rev-parse"}
_GIT_WRITE_LOCAL_SUBCOMMANDS = {"add", "commit", "stash", "pull", "clone"}
_GITHUB_REMOTE_PATTERNS = (
    re.compile(r"^https://github\.com/([^/]+)/([^/]+?)/?$"),
    re.compile(r"^git@github\.com:([^/]+)/([^/]+?)$"),
    re.compile(r"^ssh://git@github\.com/([^/]+)/([^/]+?)/?$"),
)
_RESOURCE_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")


def _valid_resource_segment(segment: str) -> bool:
    # Vinctor resources are hierarchical path prefixes and the PDP rejects
    # `.`/`..` segments - never emit them.
    return bool(_RESOURCE_SEGMENT.match(segment)) and segment not in {".", ".."}


def _parse_github_remote(token: str) -> tuple[str, str] | None:
    for pattern in _GITHUB_REMOTE_PATTERNS:
        match = pattern.match(token)
        if match:
            owner = match.group(1)
            repo = re.sub(r"\.git$", "", match.group(2))
            if _valid_resource_segment(owner) and _valid_resource_segment(repo):
                return owner, repo
            return None
    return None


def _git_command(tokens: list[str]) -> MappingResult | None:
    if tokens[0] != "git" or len(tokens) < 2:
        return None
    branch = _branch_creation(tokens)
    if branch:
        return MappingResult(
            kind="mapped",
            action="write",
            resource=f"repo/branch/{branch}",
            source="builtin",
        )
    sub = tokens[1]
    if sub in _GIT_READ_SUBCOMMANDS:
        return MappingResult(kind="mapped", action="read", resource="shell/git", source="builtin")
    if sub in _GIT_WRITE_LOCAL_SUBCOMMANDS:
        return MappingResult(kind="mapped", action="write", resource="shell/git", source="builtin")
    if sub == "push":
        return _git_push(tokens)
    if sub == "reset" and "--hard" in tokens[2:]:
        return MappingResult(
            kind="mapped", action="delete", resource="shell/git", source="builtin"
        )
    if sub == "branch" and any(token in {"-D", "--delete", "-d"} for token in tokens[2:]):
        return MappingResult(
            kind="mapped", action="delete", resource="shell/git", source="builtin"
        )
    if sub == "clean" and any(
        token == "--force" or ("f" in token and token.startswith("-")) for token in tokens[2:]
    ):
        return MappingResult(
            kind="mapped", action="delete", resource="shell/git", source="builtin"
        )
    return None


def _is_force_with_lease(token: str) -> bool:
    option = token.partition("=")[0]
    return option.startswith("--force-w") and "--force-with-lease".startswith(option)


def _git_push(tokens: list[str]) -> MappingResult:
    rest = tokens[2:]
    if any(token.startswith("-") and not _is_allowed_push_option(token) for token in rest):
        return _unsafe_shell_result()
    destructive = any(_is_destructive_push_argument(token) for token in rest)
    # A non-force push needs an explicit GitHub URL because a named remote's
    # target is unavailable here. Force spellings can still be classified
    # conservatively as delete:shell/git without guessing that target.
    remote_token = next((token for token in rest if not token.startswith("-")), None)
    remote = _parse_github_remote(remote_token) if remote_token else None
    if remote is None:
        if destructive:
            return MappingResult(
                kind="mapped", action="delete", resource="shell/git", source="builtin"
            )
        return MappingResult(kind="error", reason="parse_unsafe")
    owner, repo = remote
    return MappingResult(
        kind="mapped",
        action="delete" if destructive else "write",
        resource=f"github/{owner}/{repo}/contents",
        source="builtin",
    )


# Shell interpreters whose stdin is executed as a program. Matched by basename
# so a path-prefixed interpreter (/bin/sh) counts too - otherwise a read-mapped
# producer (git show ... | /bin/sh) would launder arbitrary execution through a
# read:shell/git grant.
_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
# Wrapper words that forward execution to the next token. Matched by basename
# like the interpreters (| /usr/bin/env bash, | /bin/sudo bash) and skipped in
# a loop so stacked wrappers (| sudo env bash) step through too.
_WRAPPERS = frozenset({"sudo", "env"})
_SAFE_FIRST_TOKEN = re.compile(r"^[A-Za-z0-9._-]+$")
# Shell path tokens that cannot expand to something else (no globs,
# variables, tildes, quotes/whitespace).
_SAFE_SHELL_PATH = re.compile(r"^[A-Za-z0-9_@%+=:,./-]+$")


def _pipe_to_shell(normalized: str) -> MappingResult | None:
    # Canon: piped/subshell execution of streamed content (curl ... | sh) is
    # its own operation - execute:shell/<first-token>. The resource is the
    # opaque first token; deobfuscating what actually runs is the
    # authorization service's job, not the taxonomy's. This check runs
    # before the per-command classifiers: execute over the piped source
    # outranks the source command's own class.
    unsupported, pipe_count = _scan_shell_control_operators(normalized)
    if unsupported or pipe_count > 1:
        return MappingResult(kind="unmapped")
    if pipe_count == 0:
        return None

    tokens = normalized.split(" ")
    for i in range(1, len(tokens) - 1):
        # A real pipe token (not ||), optionally |&.
        if tokens[i] not in ("|", "|&"):
            continue
        j = i + 1
        # Step over sudo/env wrapper words (| sudo bash, | /usr/bin/env sh,
        # | sudo env bash) - basename-matched, like the interpreter below.
        while j < len(tokens) and tokens[j].rsplit("/", 1)[-1] in _WRAPPERS:
            j += 1
        if j >= len(tokens) or tokens[j].rsplit("/", 1)[-1] not in _SHELLS:
            continue
        # Producer token keeps its fail-closed guard.
        first = tokens[0].rsplit("/", 1)[-1]
        if not _SAFE_FIRST_TOKEN.match(first):
            return MappingResult(kind="error", reason="parse_unsafe")
        return MappingResult(
            kind="mapped", action="execute", resource=f"shell/{first}", source="builtin"
        )
    return None


def _shell_delete(tokens: list[str]) -> MappingResult | None:
    # Canon: rm/rmdir -> delete over the single explicit target path (D-4
    # repo/ vs fs/ split, secret overlay). Fail-closed rules: several
    # targets have no single (action, resource); tokens the shell would
    # expand (globs, variables, ~user) never become resources.
    if tokens[0] not in {"rm", "unlink", "rmdir"}:
        return None
    positionals = [token for token in tokens[1:] if not token.startswith("-")]
    if not positionals:
        return MappingResult(kind="error", reason="malformed_payload")
    if len(positionals) != 1:
        return MappingResult(kind="error", reason="parse_unsafe")
    target = positionals[0]
    if not _SAFE_SHELL_PATH.match(target):
        return MappingResult(kind="error", reason="parse_unsafe")
    resource = repo_or_secret_resource(target)
    if resource is None:
        return MappingResult(kind="error", reason="parse_unsafe")
    return MappingResult(kind="mapped", action="delete", resource=resource, source="builtin")


# Canon grammar: container/<registry>/<image>. Unqualified references bind
# docker's default registry (docker.io); the tag/digest is not part of the
# resource. docker-run flags we can safely step over when locating the image
# token; anything dash-prefixed outside these sets (and not --flag=value
# form) makes the image position ambiguous - fail closed, never a guess.
_DOCKER_RUN_BOOL_FLAGS = {
    "-d", "--detach", "--rm", "-i", "--interactive", "-t", "--tty", "-it", "-ti",
    "--init", "--privileged", "-P", "--publish-all", "--read-only", "--no-healthcheck",
}  # fmt: skip
_DOCKER_RUN_VALUE_FLAGS = {
    "-e", "--env", "-v", "--volume", "-p", "--publish", "--name", "--network", "--net",
    "-w", "--workdir", "-u", "--user", "--entrypoint", "-l", "--label", "--mount",
    "--add-host", "--dns", "-m", "--memory", "--cpus", "--restart", "--platform",
    "--pull", "-h", "--hostname", "--env-file",
}  # fmt: skip


def _parse_image_ref(token: str) -> tuple[str, str] | None:
    ref = token.split("@")[0]  # strip digest
    slash = ref.rfind("/")
    colon = ref.rfind(":")
    if colon > slash:
        ref = ref[:colon]  # strip tag (not a registry port)
    if not ref:
        return None
    parts = ref.split("/")
    registry = "docker.io"
    image_parts = parts
    if len(parts) >= 2 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
        registry = parts[0]
        image_parts = parts[1:]
    if not image_parts:
        return None
    # The registry may carry a :port; image segments must be clean segments.
    registry_host = registry.split(":")[0]
    if not _valid_resource_segment(registry_host):
        return None
    if not all(_valid_resource_segment(part) for part in image_parts):
        return None
    return registry, "/".join(image_parts)


def _docker_mapped(action: Action, ref: tuple[str, str]) -> MappingResult:
    registry, image = ref
    return MappingResult(
        kind="mapped", action=action, resource=f"container/{registry}/{image}", source="builtin"
    )


def _docker_find_run_image(rest: list[str]) -> str | None:
    index = 0
    while index < len(rest):
        token = rest[index]
        if token.startswith("-"):
            if "=" in token or token in _DOCKER_RUN_BOOL_FLAGS:
                index += 1
                continue
            if token in _DOCKER_RUN_VALUE_FLAGS:
                index += 2
                continue
            return None  # unknown flag: the next token may be its value
        return token
    return None


def _docker_find_build_tag(rest: list[str]) -> str | None:
    for index, token in enumerate(rest):
        if token in {"-t", "--tag"}:
            return rest[index + 1] if index + 1 < len(rest) else None
        if token.startswith("--tag="):
            return token.removeprefix("--tag=")
    return None


def _docker_command(tokens: list[str]) -> MappingResult | None:
    if tokens[0] != "docker" or len(tokens) < 2:
        return None
    sub = tokens[1]
    rest = tokens[2:]
    if sub == "image" and rest[:1] == ["rm"]:
        sub, rest = "rmi", rest[1:]
    if sub in {"push", "rmi"}:
        positionals = [token for token in rest if not token.startswith("-")]
        if len(positionals) != 1:
            # none: ambiguous; several: multi-target (no single resource)
            return MappingResult(kind="error", reason="parse_unsafe")
        ref = _parse_image_ref(positionals[0])
        if ref is None:
            return MappingResult(kind="error", reason="parse_unsafe")
        return _docker_mapped("deploy" if sub == "push" else "delete", ref)
    if sub == "build":
        tag = _docker_find_build_tag(rest)
        ref = _parse_image_ref(tag) if tag else None
        if ref is None:
            # An untagged build has no canon resource to bind.
            return MappingResult(kind="error", reason="parse_unsafe")
        return _docker_mapped("execute", ref)
    if sub == "run":
        image_token = _docker_find_run_image(rest)
        ref = _parse_image_ref(image_token) if image_token else None
        if ref is None:
            return MappingResult(kind="error", reason="parse_unsafe")
        return _docker_mapped("execute", ref)
    return None


# Canon: gh subcommands are CLI analogs of the GitHub API operations and
# classify identically over github/<owner>/<repo>/<kind>. The target repo is
# taken from the --repo/-R flag only; without it gh resolves the repo from
# local git config this classifier does not read -> fail closed (never
# mutate an ambiguous target).
_GH_SUBCOMMANDS: dict[tuple[str, str], tuple[Action, str]] = {
    ("pr", "merge"): ("deploy", "pr"),  # analog of merge_pull_request
    ("pr", "create"): ("write", "pr"),  # analog of create_pull_request
    ("release", "create"): ("deploy", "release"),  # analog of create_release
    ("secret", "set"): ("write", "secret"),  # manage-secret over the repo's secret kind
    ("workflow", "run"): ("execute", "workflow"),  # analog of run_workflow
    ("workflow", "rerun"): ("execute", "workflow"),  # analog of rerun_workflow_run
    ("workflow", "cancel"): ("write", "workflow"),  # mutates run state; dispatches nothing
}


def _parse_gh_repo_flag(tokens: list[str]) -> tuple[str, str] | None:
    # Accepts the flag-with-value and --repo=VALUE spellings; values in the
    # [HOST/]OWNER/REPO or full-URL forms.
    value: str | None = None
    for index, token in enumerate(tokens):
        if token in {"--repo", "-R"}:
            if index + 1 < len(tokens):
                value = tokens[index + 1]
            break
        if token.startswith("--repo="):
            value = token.removeprefix("--repo=")
            break
    if not value:
        return None
    stripped = re.sub(r"^https://github\.com/", "", value)
    parts = stripped.split("/")
    if len(parts) == 3 and "." in parts[0]:
        parts = parts[1:]  # HOST/OWNER/REPO
    if len(parts) != 2:
        return None
    owner, repo = parts[0], re.sub(r"\.git$", "", parts[1])
    if _valid_resource_segment(owner) and _valid_resource_segment(repo):
        return owner, repo
    return None


def _github_cli_command(tokens: list[str]) -> MappingResult | None:
    if tokens[0] != "gh":
        return None
    key = (tokens[1] if len(tokens) > 1 else "", tokens[2] if len(tokens) > 2 else "")
    desc = _GH_SUBCOMMANDS.get(key)
    if desc is None:
        return None
    repo = _parse_gh_repo_flag(tokens[3:])
    if repo is None:
        return MappingResult(kind="error", reason="parse_unsafe")
    action, kind = desc
    owner, name = repo
    return MappingResult(
        kind="mapped",
        action=action,
        resource=f"github/{owner}/{name}/{kind}",
        source="builtin",
    )


# Canon (vinctor-conformance): npm-family package scripts and install
# lifecycles run arbitrary code -> execute:shell/<first-token>; npx fetches
# and runs an arbitrary binary -> execute:shell/npx; publish ships to the
# registry -> deploy:pkg/npm/<name>.
_NPM_FAMILY = {"npm", "pnpm", "yarn", "npx"}
_NPM_EXECUTE_SUBCOMMANDS = {"test", "run", "install", "ci"}
# npm package name shapes (bare or scoped). First char alphanumeric, so a
# dot-segment can never form a resource part.
_NPM_BARE_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*$", re.IGNORECASE)
_NPM_SCOPED_NAME = re.compile(r"^@[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*$", re.IGNORECASE)


def _npm_workspace_name(rest: list[str]) -> str | None:
    # The published package name when `npm publish -w/--workspace <name>`
    # names exactly one workspace by package name. Workspace values can also
    # be paths and the flag can repeat - anything but a single name-shaped
    # value returns None and the caller falls back to the unknown segment.
    values: list[str] = []
    for index, token in enumerate(rest):
        if token in {"-w", "--workspace"}:
            if index + 1 < len(rest):
                values.append(rest[index + 1])
        elif token.startswith("--workspace="):
            values.append(token.removeprefix("--workspace="))
    if len(values) != 1:
        return None
    value = values[0]
    if _NPM_BARE_NAME.match(value) or _NPM_SCOPED_NAME.match(value):
        return value
    return None


def _npm_command(tokens: list[str]) -> MappingResult | None:
    head = tokens[0]
    if head not in _NPM_FAMILY:
        return None
    if head == "npx":
        return MappingResult(
            kind="mapped", action="execute", resource="shell/npx", source="builtin"
        )
    sub = tokens[1] if len(tokens) > 1 else None
    if sub == "publish":
        # The bare spelling publishes the cwd package; its name lives in
        # package.json, which this text classifier cannot read - bind the
        # registry-scoped unknown-segment form instead of guessing.
        name = _npm_workspace_name(tokens[2:]) if head == "npm" else None
        return MappingResult(
            kind="mapped",
            action="deploy",
            resource=f"pkg/npm/{name or '_'}",
            source="builtin",
        )
    if sub in _NPM_EXECUTE_SUBCOMMANDS:
        return MappingResult(
            kind="mapped", action="execute", resource=f"shell/{head}", source="builtin"
        )
    return None


def _is_test_command(tokens: list[str]) -> bool:
    if tokens[0] in _TEST_COMMANDS:
        return True
    if tokens[:2] == ["go", "test"]:
        return True
    if tokens[:2] == ["cargo", "test"]:
        return True
    return bool(tokens[0] == "python" and len(tokens) > 2 and tokens[1:3] == ["-m", "pytest"])


def _is_build_command(tokens: list[str]) -> bool:
    if tokens[0] in {"npm", "pnpm", "yarn"} and "build" in tokens[1:4]:
        return True
    return tokens[:2] in (["cargo", "build"], ["go", "build"])


def _is_deploy_command(tokens: list[str]) -> bool:
    if any(token in _DEPLOY_TOKENS for token in tokens):
        return True
    return any("deploy" in token.lower() for token in tokens)


def _deploy_env(tokens: list[str]) -> str:
    lowered = [token.lower() for token in tokens]
    if any(
        token in {"--prod", "--production", "production", "prod"} or "production" in token
        for token in lowered
    ):
        return "production"
    if "staging" in lowered or "stage" in lowered:
        return "staging"
    return "unknown"


def _is_env_file(token: str) -> bool:
    base = token.rsplit("/", 1)[-1]
    return base == ".env" or base.startswith(".env.")


def _is_secret_read_command(tokens: list[str]) -> bool:
    # Terminal secrets-read parity with the Claude Code / Codex hooks
    # (`cat .env`, `printenv` → read:secret/env).
    if tokens[0] == "printenv":
        return True
    return tokens[0] == "cat" and any(_is_env_file(token) for token in tokens[1:])


def _safe_arg(args: dict[str, Any], name: str, *, default: str | None) -> str | None:
    value = args.get(name)
    if value is None:
        return default
    if not isinstance(value, str) or not value:
        return default
    return safe_identifier(value, default=default)


def _string_arg(args: dict[str, Any], name: str) -> str | None:
    value = args.get(name)
    if not isinstance(value, str) or not value:
        return None
    return value
