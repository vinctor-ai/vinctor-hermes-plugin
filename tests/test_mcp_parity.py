import unittest

from vinctor_hermes_plugin.config import Config
from vinctor_hermes_plugin.mapping import resolve_tool_call

EMPTY_CONFIG = Config(version=1, rules=())


def mapped(tool_name, args):
    result = resolve_tool_call(tool_name, args, EMPTY_CONFIG)
    return result.kind, result.action, result.resource


class McpParityTests(unittest.TestCase):
    def test_filesystem_matches_claude_hook_tool_table(self):
        cases = [
            (
                "mcp_filesystem_read_text_file",
                {"path": "/project/src/main.ts"},
                ("mapped", "read", "fs/project/src/main.ts"),
            ),
            (
                "mcp_filesystem_read_media_file",
                {"path": "/project/img.png"},
                ("mapped", "read", "fs/project/img.png"),
            ),
            (
                "mcp_filesystem_list_directory_with_sizes",
                {"path": "/project"},
                ("mapped", "read", "fs/project"),
            ),
            (
                "mcp_filesystem_directory_tree",
                {"path": "/project"},
                ("mapped", "read", "fs/project"),
            ),
            (
                "mcp_filesystem_get_file_info",
                {"path": "/project/a.py"},
                ("mapped", "read", "fs/project/a.py"),
            ),
            ("mcp_filesystem_list_allowed_directories", {}, ("mapped", "read", "fs/_allowed-dirs")),
            (
                "mcp_filesystem_edit_file",
                {"path": "/project/a.py", "dryRun": True},
                ("mapped", "write", "fs/project/a.py"),
            ),
            (
                "mcp_filesystem_move_file",
                {"source": "/home/u/.env", "destination": "/project/.env.copy"},
                ("mapped", "write", "secret/env"),
            ),
            (
                "mcp_filesystem_read_multiple_files",
                {"paths": ["/project/a.py", "/home/u/.aws/credentials"]},
                ("mapped", "read", "secret/aws"),
            ),
            # Canon/spec name; delete_directory is the reference-fork alias.
            (
                "mcp_filesystem_remove_directory",
                {"path": "/project/tmp"},
                ("mapped", "delete", "fs/project/tmp"),
            ),
        ]
        for tool_name, args, expected in cases:
            with self.subTest(tool_name=tool_name):
                self.assertEqual(mapped(tool_name, args), expected)

    def test_filesystem_multiple_non_sensitive_files_map_per_path(self):
        # PKA-148: this used to pin `unmapped` — which the default unmapped
        # policy defers OPEN, so an all-ordinary multi-read ran with zero
        # enforcement. Now it is one read per path, like the claude hook.
        result = resolve_tool_call(
            "mcp_filesystem_read_multiple_files",
            {"paths": ["/project/a.py", "/project/b.py"]},
            EMPTY_CONFIG,
        )

        self.assertEqual(result.kind, "mapped")
        self.assertEqual((result.action, result.resource), ("read", "fs/project/a.py"))
        self.assertEqual(
            [(r.action, r.resource) for r in result.also_requires],
            [("read", "fs/project/b.py")],
        )

    def test_github_matches_claude_hook_read_scopes(self):
        # Canon kinds: the file/code/branch kinds collapse into `contents`,
        # and secret-scanning reads bind the repo-scoped `secret` kind.
        cases = [
            ("mcp_github_get_me", {}, ("mapped", "read", "github/_/context")),
            ("mcp_github_search_users", {"query": "alice"}, ("mapped", "read", "github/_/context")),
            ("mcp_github_search_repositories", {"query": "x"}, ("mapped", "read", "github/_/repo")),
            ("mcp_github_search_code", {"query": "x"}, ("mapped", "read", "github/_/contents")),
            (
                "mcp_github_get_file_contents",
                {"owner": "acme", "repo": "api"},
                ("mapped", "read", "github/acme/api/contents"),
            ),
            (
                "mcp_github_list_commits",
                {"owner": "acme", "repo": "api"},
                ("mapped", "read", "github/acme/api/contents"),
            ),
            (
                "mcp_github_list_branches",
                {"owner": "acme", "repo": "api"},
                ("mapped", "read", "github/acme/api/contents"),
            ),
            (
                "mcp_github_list_releases",
                {"owner": "acme", "repo": "api"},
                ("mapped", "read", "github/acme/api/release"),
            ),
            (
                "mcp_github_list_issue_types",
                {"owner": "acme"},
                ("mapped", "read", "github/acme/_/issue"),
            ),
            ("mcp_github_search_issues", {}, ("mapped", "read", "github/_/issue")),
            (
                "mcp_github_get_code_scanning_alert",
                {"owner": "acme", "repo": "api"},
                ("mapped", "read", "github/acme/api/security"),
            ),
            (
                "mcp_github_get_secret_scanning_alert",
                {"owner": "acme", "repo": "api"},
                ("mapped", "read", "github/acme/api/secret"),
            ),
            (
                "mcp_github_list_secret_scanning_alerts",
                {"owner": "acme", "repo": "api"},
                ("mapped", "read", "github/acme/api/secret"),
            ),
        ]
        for tool_name, args, expected in cases:
            with self.subTest(tool_name=tool_name):
                self.assertEqual(mapped(tool_name, args), expected)

    def test_github_matches_claude_hook_mutation_and_workflow_scopes(self):
        repo = {"owner": "acme", "repo": "api"}
        cases = [
            (
                "mcp_github_create_or_update_file",
                repo,
                ("mapped", "write", "github/acme/api/contents"),
            ),
            ("mcp_github_push_files", repo, ("mapped", "write", "github/acme/api/contents")),
            ("mcp_github_create_branch", repo, ("mapped", "write", "github/acme/api/contents")),
            ("mcp_github_delete_file", repo, ("mapped", "delete", "github/acme/api/contents")),
            # PKA-150: create_repository is a namespace write. With no
            # organization it degrades to the coarse github/_/_/repo (owner from
            # `organization`), matching the claude hook. Parity checks the
            # primary pair; fork_repository's full set is in test_multi_effect.
            (
                "mcp_github_create_repository",
                {"name": "svc"},
                ("mapped", "write", "github/_/_/repo"),
            ),
            (
                "mcp_github_create_repository",
                {"organization": "myorg", "name": "svc"},
                ("mapped", "write", "github/myorg/_/repo"),
            ),
            ("mcp_github_fork_repository", repo, ("mapped", "write", "github/acme/api/fork")),
            ("mcp_github_create_issue", repo, ("mapped", "write", "github/acme/api/issue")),
            ("mcp_github_update_issue_state", repo, ("mapped", "write", "github/acme/api/issue")),
            ("mcp_github_create_pull_request", repo, ("mapped", "write", "github/acme/api/pr")),
            (
                "mcp_github_update_pull_request_branch",
                repo,
                ("mapped", "write", "github/acme/api/pr"),
            ),
            # Canon: merge is the deploy moment (write + becomes shipping
            # baseline -> deploy by precedence).
            ("mcp_github_merge_pull_request", repo, ("mapped", "deploy", "github/acme/api/pr")),
            ("mcp_github_run_workflow", repo, ("mapped", "execute", "github/acme/api/workflow")),
            (
                "mcp_github_cancel_workflow_run",
                repo,
                ("mapped", "write", "github/acme/api/workflow"),
            ),
            (
                "mcp_github_delete_workflow_run_logs",
                repo,
                ("mapped", "delete", "github/acme/api/workflow"),
            ),
        ]
        for tool_name, args, expected in cases:
            with self.subTest(tool_name=tool_name):
                self.assertEqual(mapped(tool_name, args), expected)

    def test_github_canon_classic_names_and_release_deploys(self):
        # Canon operation names from the classic GitHub server, and the
        # deploy-verb release publications (externally effective).
        repo = {"owner": "acme", "repo": "api"}
        cases = [
            ("mcp_github_get_issue", repo, ("mapped", "read", "github/acme/api/issue")),
            ("mcp_github_update_issue", repo, ("mapped", "write", "github/acme/api/issue")),
            ("mcp_github_get_pull_request", repo, ("mapped", "read", "github/acme/api/pr")),
            ("mcp_github_get_release", repo, ("mapped", "read", "github/acme/api/release")),
            ("mcp_github_create_release", repo, ("mapped", "deploy", "github/acme/api/release")),
            ("mcp_github_publish_release", repo, ("mapped", "deploy", "github/acme/api/release")),
        ]
        for tool_name, args, expected in cases:
            with self.subTest(tool_name=tool_name):
                self.assertEqual(mapped(tool_name, args), expected)

    def test_github_actions_run_trigger_uses_method_specific_action(self):
        repo = {"owner": "acme", "repo": "api"}
        cases = [
            ({**repo, "method": "run_workflow"}, ("mapped", "execute", "github/acme/api/workflow")),
            (
                {**repo, "method": "rerun_failed_jobs"},
                ("mapped", "execute", "github/acme/api/workflow"),
            ),
            (
                {**repo, "method": "cancel_workflow_run"},
                ("mapped", "write", "github/acme/api/workflow"),
            ),
            (
                {**repo, "method": "delete_workflow_run_logs"},
                ("mapped", "delete", "github/acme/api/workflow"),
            ),
        ]
        for args, expected in cases:
            with self.subTest(method=args["method"]):
                self.assertEqual(mapped("mcp_github_actions_run_trigger", args), expected)

        self.assertEqual(
            resolve_tool_call("mcp_github_actions_run_trigger", repo, EMPTY_CONFIG).kind,
            "unmapped",
        )

    def test_slack_matches_claude_hook_tool_table(self):
        # Canon (vinctor-conformance): chat/slack[/<channel>] resource grammar.
        channel = "C01AB2CD3EF"
        cases = [
            ("mcp_slack_slack_list_channels", {}, ("mapped", "read", "chat/slack")),
            ("mcp_slack_slack_get_users", {}, ("mapped", "read", "chat/slack")),
            ("mcp_slack_channels_list", {}, ("mapped", "read", "chat/slack")),
            ("mcp_slack_users_search", {}, ("mapped", "read", "chat/slack")),
            (
                "mcp_slack_slack_get_channel_history",
                {"channel_id": channel},
                ("mapped", "read", f"chat/slack/{channel}"),
            ),
            ("mcp_slack_conversations_history", {}, ("mapped", "read", "chat/slack")),
            (
                "mcp_slack_conversations_search_messages",
                {"filter_in_channel": channel},
                ("mapped", "read", f"chat/slack/{channel}"),
            ),
            ("mcp_slack_conversations_search_messages", {}, ("mapped", "read", "chat/slack")),
            (
                "mcp_slack_slack_post_message",
                {"channel_id": channel},
                ("mapped", "send", f"chat/slack/{channel}"),
            ),
            (
                "mcp_slack_conversations_add_message",
                {"channel_id": "#general"},
                ("mapped", "send", "chat/slack/#general"),
            ),
            (
                "mcp_slack_reactions_remove",
                {"channel_id": channel},
                ("mapped", "send", f"chat/slack/{channel}"),
            ),
            # Legacy Hermes short name: workspace-scoped search reads bind the
            # platform prefix (no pseudo-channel segment).
            ("mcp_slack_search_messages", {"query": "deploy"}, ("mapped", "read", "chat/slack")),
        ]
        for tool_name, args, expected in cases:
            with self.subTest(tool_name=tool_name):
                self.assertEqual(mapped(tool_name, args), expected)

    def test_slack_send_without_channel_defers(self):
        result = resolve_tool_call("mcp_slack_slack_post_message", {"text": "hi"}, EMPTY_CONFIG)

        self.assertEqual(result.kind, "unmapped")

    def test_claude_style_mcp_separator_is_accepted_for_operator_fixture_parity(self):
        self.assertEqual(
            mapped("mcp__github__get_me", {}),
            ("mapped", "read", "github/_/context"),
        )


if __name__ == "__main__":
    unittest.main()
