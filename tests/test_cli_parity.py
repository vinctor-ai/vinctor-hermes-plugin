import io
import json
import tempfile
import unittest
from pathlib import Path

from vinctor_hermes_plugin.cli import run


class CliParityTests(unittest.TestCase):
    def test_version_flag_reports_package_name_and_version(self):
        stdout = io.StringIO()

        code = run(["--version"], stdout=stdout, stderr=io.StringIO())

        self.assertEqual(code, 0)
        self.assertIn("vinctor-hermes-plugin", stdout.getvalue())
        self.assertIn("0.6.0", stdout.getvalue())

    def test_validate_json_includes_path_rule_count_and_note(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "rules": [
                            {
                                "tool": "terminal",
                                "matchType": "exact",
                                "pattern": "npm test",
                                "action": "execute",
                                "resource": "ci/test",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()

            code = run(["validate", str(config), "--json"], stdout=stdout, stderr=io.StringIO())

        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {
                "valid": True,
                "errors": [],
                "path": str(config),
                "rule_count": 1,
                "note": None,
            },
        )

    def test_validate_explicit_missing_config_fails_closed(self):
        # PKA-119: an explicitly requested config path that does not exist is
        # invalid_config (exit 1), not a silent valid-empty config.
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing.json"
            stdout = io.StringIO()

            code = run(["validate", str(missing), "--json"], stdout=stdout, stderr=io.StringIO())

        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["valid"])
        self.assertEqual(payload["path"], str(missing))
        self.assertEqual(payload["rule_count"], 0)
        self.assertTrue(payload["errors"])
        self.assertIn("does not exist", payload["errors"][0])

    def test_explain_uses_env_config_when_config_flag_is_absent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "config.json"
            config.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "rules": [
                            {
                                "tool": "terminal",
                                "matchType": "exact",
                                "pattern": "npm test",
                                "action": "execute",
                                "resource": "ci/custom",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            event = Path(temp_dir) / "event.json"
            event.write_text(
                '{"tool_name":"terminal","args":{"command":"npm test"}}',
                encoding="utf-8",
            )
            stdout = io.StringIO()

            code = run(
                ["explain", str(event), "--json"],
                stdout=stdout,
                stderr=io.StringIO(),
                env={"VINCTOR_HERMES_PLUGIN_CONFIG": str(config)},
            )

        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {
                "status": "mapped",
                "action": "execute",
                "resource": "ci/custom",
                "source": "config",
            },
        )


if __name__ == "__main__":
    unittest.main()
