import json
import os
import signal
import tempfile
import unittest
from pathlib import Path

from vinctor_hermes_plugin.boundary import VinctorHermesBoundary
from vinctor_hermes_plugin.config import MAX_CONFIG_BYTES, ConfigError, load_runtime_config
from vinctor_hermes_plugin.mapping import resolve_tool_call


class RuntimeMcpRegistryConfigTests(unittest.TestCase):
    def test_opted_in_fifo_registry_fails_closed_without_blocking(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = Path(temp_dir) / "mcp-tools.fifo"
            os.mkfifo(registry)

            def guard(signum, frame):
                raise AssertionError(
                    "load_runtime_config blocked on a FIFO instead of failing closed"
                )

            previous = signal.signal(signal.SIGALRM, guard)
            signal.alarm(3)
            try:
                with self.assertRaises(ConfigError):
                    load_runtime_config(
                        None,
                        str(registry),
                        allow_mcp_registry_runtime_rules=True,
                    )
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, previous)

    def test_opted_in_oversized_registry_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = Path(temp_dir) / "mcp-tools.json"
            registry.write_text(
                "[" + ("0," * (MAX_CONFIG_BYTES // 2)) + "0]",
                encoding="utf-8",
            )

            with self.assertRaises(ConfigError):
                load_runtime_config(
                    None,
                    str(registry),
                    allow_mcp_registry_runtime_rules=True,
                )

    def test_opted_in_non_utf8_registry_fails_closed(self):
        # _read_regular_file decodes as UTF-8, so a registry holding an invalid
        # byte raises UnicodeDecodeError. load_config already turns that into
        # ConfigError; the registry path must too, or it escapes the adapter as
        # an uncaught exception instead of a fail-closed block.
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = Path(temp_dir) / "mcp-tools.json"
            registry.write_bytes(b'{"tools": [{"name": "mcp_\xff_page"}]}')

            with self.assertRaises(ConfigError):
                load_runtime_config(
                    None,
                    str(registry),
                    allow_mcp_registry_runtime_rules=True,
                )

    def test_opted_in_non_utf8_registry_blocks_at_the_boundary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = Path(temp_dir) / "mcp-tools.json"
            registry.write_bytes(b'{"tools": [{"name": "mcp_\xff_page"}]}')
            env = {
                "VINCTOR_ENDPOINT": "http://vinctor.test",
                "VINCTOR_AGENT_KEY": "aak_test",
                "VINCTOR_GRANT_REF": "grt_test",
                "VINCTOR_HERMES_MCP_REGISTRY": str(registry),
                "VINCTOR_HERMES_ALLOW_MCP_REGISTRY_RUNTIME_RULES": "1",
            }

            boundary = VinctorHermesBoundary.from_env(env=env)

            self.assertEqual(
                boundary.pre_tool_call(tool_name="terminal", args={"command": "npm test"}),
                {
                    "action": "block",
                    "message": "Denied by Vinctor authorization: invalid_config.",
                },
            )

    def test_runtime_config_does_not_append_discovered_rules_by_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = Path(temp_dir) / "mcp-tools.json"
            registry.write_text(
                json.dumps({"tools": [{"name": "mcp_notion_create_page"}]}),
                encoding="utf-8",
            )

            config = load_runtime_config(None, str(registry))

        result = resolve_tool_call("mcp_notion_create_page", {}, config)

        self.assertEqual(result.kind, "unmapped")

    def test_runtime_config_appends_discovered_mcp_rules_when_explicitly_allowed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = Path(temp_dir) / "mcp-tools.json"
            registry.write_text(
                json.dumps({"tools": [{"name": "mcp_notion_create_page"}]}),
                encoding="utf-8",
            )

            config = load_runtime_config(
                None,
                str(registry),
                allow_mcp_registry_runtime_rules=True,
            )

        result = resolve_tool_call("mcp_notion_create_page", {}, config)

        self.assertEqual(
            (result.kind, result.action, result.resource),
            ("mapped", "write", "mcp/notion/create_page"),
        )

    def test_explicit_config_rule_wins_over_discovered_mcp_rule(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            registry = Path(temp_dir) / "mcp-tools.json"
            config_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "rules": [
                            {
                                "tool": "mcp_notion_create_page",
                                "matchType": "exact",
                                "pattern": "mcp_notion_create_page",
                                "action": "write",
                                "resource": "mcp/notion/approved-pages",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            registry.write_text(
                json.dumps({"tools": [{"name": "mcp_notion_create_page"}]}),
                encoding="utf-8",
            )

            config = load_runtime_config(
                str(config_path),
                str(registry),
                allow_mcp_registry_runtime_rules=True,
            )

        result = resolve_tool_call("mcp_notion_create_page", {}, config)

        self.assertEqual(
            (result.kind, result.action, result.resource, result.source),
            ("mapped", "write", "mcp/notion/approved-pages", "config"),
        )

    def test_explicit_broad_config_rule_wins_over_generated_exact_rule(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            registry = Path(temp_dir) / "mcp-tools.json"
            config_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "rules": [
                            {
                                "tool": "mcp_notion_create_page",
                                "matchType": "glob",
                                "pattern": "mcp_notion_*",
                                "action": "write",
                                "resource": "mcp/notion/reviewed",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            registry.write_text(
                json.dumps({"tools": [{"name": "mcp_notion_create_page"}]}),
                encoding="utf-8",
            )

            config = load_runtime_config(
                str(config_path),
                str(registry),
                allow_mcp_registry_runtime_rules=True,
            )

        result = resolve_tool_call("mcp_notion_create_page", {}, config)

        self.assertEqual(
            (result.kind, result.action, result.resource, result.source),
            ("mapped", "write", "mcp/notion/reviewed", "config"),
        )


if __name__ == "__main__":
    unittest.main()
