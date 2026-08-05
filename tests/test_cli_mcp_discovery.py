import io
import json
import tempfile
import unittest
from pathlib import Path

from vinctor_hermes_plugin.cli import run


class CliMcpDiscoveryTests(unittest.TestCase):
    def test_draft_mcp_config_outputs_generated_rules_and_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = Path(temp_dir) / "tools.json"
            registry.write_text(
                json.dumps(
                    {
                        "tools": [
                            {"name": "mcp_github_get_me"},
                            {"name": "mcp_notion_create_page"},
                            {"name": "mcp_unknown_frob"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()

            code = run(
                ["draft-mcp-config", str(registry), "--json"],
                stdout=stdout,
                stderr=io.StringIO(),
            )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["generated_rule_count"], 1)
        self.assertEqual(payload["known_builtin"], ["mcp_github_get_me"])
        self.assertEqual(
            payload["skipped"],
            [{"name": "mcp_unknown_frob", "reason": "could_not_infer_action"}],
        )
        self.assertEqual(
            payload["config"],
            {
                "version": 1,
                "rules": [
                    {
                        "tool": "mcp_notion_create_page",
                        "matchType": "exact",
                        "pattern": "mcp_notion_create_page",
                        "action": "write",
                        "resource": "mcp/notion/create_page",
                    }
                ],
            },
        )

    def test_explain_does_not_use_env_mcp_registry_without_explicit_allow(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = Path(temp_dir) / "tools.json"
            event = Path(temp_dir) / "event.json"
            registry.write_text(
                json.dumps({"tools": [{"name": "mcp_notion_create_page"}]}),
                encoding="utf-8",
            )
            event.write_text(
                '{"tool_name":"mcp_notion_create_page","args":{}}',
                encoding="utf-8",
            )
            stdout = io.StringIO()

            code = run(
                ["explain", str(event), "--json"],
                stdout=stdout,
                stderr=io.StringIO(),
                env={"VINCTOR_HERMES_MCP_REGISTRY": str(registry)},
            )

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), {"status": "unmapped"})

    def test_explain_uses_env_mcp_registry_when_explicitly_allowed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = Path(temp_dir) / "tools.json"
            event = Path(temp_dir) / "event.json"
            registry.write_text(
                json.dumps({"tools": [{"name": "mcp_notion_create_page"}]}),
                encoding="utf-8",
            )
            event.write_text('{"tool_name":"mcp_notion_create_page","args":{}}', encoding="utf-8")
            stdout = io.StringIO()

            code = run(
                ["explain", str(event), "--json"],
                stdout=stdout,
                stderr=io.StringIO(),
                env={
                    "VINCTOR_HERMES_MCP_REGISTRY": str(registry),
                    "VINCTOR_HERMES_ALLOW_MCP_REGISTRY_RUNTIME_RULES": "1",
                },
            )

        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {
                "status": "mapped",
                "action": "write",
                "resource": "mcp/notion/create_page",
                "source": "config",
            },
        )


if __name__ == "__main__":
    unittest.main()
