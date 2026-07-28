import unittest

from vinctor_hermes_plugin.config import Config, Rule
from vinctor_hermes_plugin.mapping import resolve_tool_call

EMPTY_CONFIG = Config(version=1, rules=())


class MappingTests(unittest.TestCase):
    def test_write_file_maps_to_repo_write_path(self):
        result = resolve_tool_call("write_file", {"path": "src/app.py"}, EMPTY_CONFIG)

        self.assertEqual(result.kind, "mapped")
        self.assertEqual(result.action, "write")
        self.assertEqual(result.resource, "repo/src/app.py")

    def test_patch_maps_to_repo_write_path(self):
        result = resolve_tool_call("patch", {"file_path": "./README.md"}, EMPTY_CONFIG)

        self.assertEqual(result.kind, "mapped")
        self.assertEqual(result.action, "write")
        self.assertEqual(result.resource, "repo/README.md")

    def test_d4_absolute_paths_map_to_fs_relative_to_repo_secret_wins(self):
        # D-4: external (absolute) paths → fs/; in-tree (relative) → repo/.
        external = resolve_tool_call(
            "write_file", {"path": "/etc/nginx/nginx.conf"}, EMPTY_CONFIG
        )
        self.assertEqual(
            (external.kind, external.action, external.resource),
            ("mapped", "write", "fs/etc/nginx/nginx.conf"),
        )
        in_tree = resolve_tool_call("write_file", {"path": "src/app.py"}, EMPTY_CONFIG)
        self.assertEqual(
            (in_tree.kind, in_tree.action, in_tree.resource),
            ("mapped", "write", "repo/src/app.py"),
        )
        # secret classification wins regardless of location (absolute secret → secret/).
        secret = resolve_tool_call(
            "write_file", {"path": "/home/u/.ssh/id_rsa"}, EMPTY_CONFIG
        )
        self.assertEqual(
            (secret.kind, secret.action, secret.resource),
            ("mapped", "write", "secret/ssh"),
        )

    def test_branch_creation_maps_to_repo_branch_write(self):
        result = resolve_tool_call(
            "terminal",
            {"command": "git switch -c feature/hermes-boundary"},
            EMPTY_CONFIG,
        )

        self.assertEqual(result.kind, "mapped")
        self.assertEqual(result.action, "write")
        self.assertEqual(result.resource, "repo/branch/feature/hermes-boundary")

    def test_test_and_build_commands_map_to_expected_execute_resources(self):
        # Canon: npm-family scripts and install lifecycles run arbitrary code
        # -> execute:shell/<first-token>. Non-canon test runners keep ci/test.
        npm_test = resolve_tool_call("terminal", {"command": "npm test"}, EMPTY_CONFIG)
        pytest_result = resolve_tool_call("terminal", {"command": "pytest tests"}, EMPTY_CONFIG)
        build = resolve_tool_call("terminal", {"command": "npm run build"}, EMPTY_CONFIG)

        self.assertEqual(
            (npm_test.kind, npm_test.action, npm_test.resource),
            ("mapped", "execute", "shell/npm"),
        )
        self.assertEqual(
            (pytest_result.kind, pytest_result.action, pytest_result.resource),
            ("mapped", "execute", "ci/test"),
        )
        self.assertEqual(
            (build.kind, build.action, build.resource),
            ("mapped", "execute", "shell/npm"),
        )

    def test_release_uses_deploy_verb_and_deploy_command_taxonomy(self):
        deploy = resolve_tool_call("terminal", {"command": "vercel deploy --prod"}, EMPTY_CONFIG)
        release = resolve_tool_call(
            "terminal",
            {"command": "gh release create v1.0.0 --repo acme/api"},
            EMPTY_CONFIG,
        )

        # Canon: outward publication uses the `deploy` verb over the repo's
        # release kind (github/<owner>/<repo>/release).
        self.assertEqual(
            (release.kind, release.action, release.resource),
            ("mapped", "deploy", "github/acme/api/release"),
        )
        # D-6: platform-deploy CLIs use the `deploy` verb + platform resource.
        self.assertEqual(
            (deploy.kind, deploy.action, deploy.resource),
            ("mapped", "deploy", "vercel/app"),
        )

    def test_memory_and_session_retrieval_map_to_read_resources(self):
        memory = resolve_tool_call("memory_search", {"query": "release context"}, EMPTY_CONFIG)
        session = resolve_tool_call("session_search", {"query": "last build"}, EMPTY_CONFIG)

        self.assertEqual(
            (memory.kind, memory.action, memory.resource),
            ("mapped", "read", "memory/search"),
        )
        self.assertEqual(
            (session.kind, session.action, session.resource),
            ("mapped", "read", "session/search"),
        )

    def test_operator_config_overrides_builtins(self):
        config = Config(
            version=1,
            rules=(
                Rule(
                    tool="terminal",
                    match_type="exact",
                    pattern="npm test",
                    action="execute",
                    resource="ci/custom-test",
                ),
            ),
        )

        result = resolve_tool_call("terminal", {"command": "npm test"}, config)

        self.assertEqual(
            (result.kind, result.action, result.resource, result.source),
            ("mapped", "execute", "ci/custom-test", "config"),
        )

    def test_unknown_tool_returns_unmapped(self):
        result = resolve_tool_call("get_weather", {"city": "Seoul"}, EMPTY_CONFIG)

        self.assertEqual(result.kind, "unmapped")

    def test_known_mapped_tool_with_malformed_path_fails_closed_at_mapping_layer(self):
        result = resolve_tool_call("write_file", {"path": "src/app.py\0secret"}, EMPTY_CONFIG)

        self.assertEqual(result.kind, "error")
        self.assertEqual(result.reason, "parse_unsafe")
