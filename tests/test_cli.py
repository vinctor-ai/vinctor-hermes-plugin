import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from vinctor_hermes_plugin.cli import run


class CliTests(unittest.TestCase):
    def test_help_lists_available_subcommands(self):
        stdout = io.StringIO()
        stderr = io.StringIO()

        code = run(["--help"], stdout=stdout, stderr=stderr)

        self.assertEqual(code, 0)
        self.assertEqual(stderr.getvalue(), "")
        help_text = stdout.getvalue()
        self.assertIn("validate", help_text)
        self.assertIn("explain", help_text)
        self.assertIn("draft-mcp-config", help_text)

    def test_unknown_subcommand_returns_exit_2_without_traceback(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        real_stderr = io.StringIO()

        with redirect_stderr(real_stderr):
            code = run(["vlaidate"], stdout=stdout, stderr=stderr)

        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(real_stderr.getvalue(), "")
        self.assertIn("invalid choice", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_validate_reports_valid_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "config.json"
            config.write_text('{"version":1,"rules":[]}', encoding="utf-8")
            stdout = io.StringIO()

            code = run(["validate", str(config), "--json"], stdout=stdout, stderr=io.StringIO())

        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {
                "valid": True,
                "errors": [],
                "path": str(config),
                "rule_count": 0,
                "note": None,
            },
        )

    def test_explain_reports_mapping_without_service_call(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            event = Path(temp_dir) / "event.json"
            event.write_text(
                '{"tool_name":"terminal","args":{"command":"npm test"}}',
                encoding="utf-8",
            )
            stdout = io.StringIO()

            code = run(["explain", str(event), "--json"], stdout=stdout, stderr=io.StringIO())

        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {
                "status": "mapped",
                "action": "execute",
                "resource": "shell/npm",
                "source": "builtin",
            },
        )

    def test_explain_debug_reports_config_paths_on_config_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "bad.json"
            event = Path(temp_dir) / "event.json"
            config.write_text('{"version":2,"rules":[]}', encoding="utf-8")
            event.write_text('{"tool_name":"terminal","args":{}}', encoding="utf-8")
            stderr = io.StringIO()

            code = run(
                ["explain", str(event), "--config", str(config), "--json"],
                stdout=io.StringIO(),
                stderr=stderr,
                env={"VINCTOR_HERMES_DEBUG": "1"},
            )

        self.assertEqual(code, 1)
        self.assertIn("invalid_config", stderr.getvalue())
        self.assertIn(f"config={config}", stderr.getvalue())
