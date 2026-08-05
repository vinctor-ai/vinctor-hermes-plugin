import io
import json
import tempfile
import unittest
from pathlib import Path

from vinctor_hermes_plugin.cli import run


def _doctor(env, *, json_output=True):
    stdout, stderr = io.StringIO(), io.StringIO()
    argv = ["doctor", "--json"] if json_output else ["doctor"]
    code = run(argv, stdout=stdout, stderr=stderr, env=env)
    return code, stdout.getvalue(), stderr.getvalue()


class DoctorTests(unittest.TestCase):
    """PKA-119 review: `validate <path>` required the operator to supply the path
    by hand, so nothing reported the source actually selected from the
    environment. `doctor` reads the env the boundary reads and says what is in
    effect — including when the answer is 'nothing'."""

    def test_reports_the_builtin_default_when_no_path_is_configured(self):
        code, out, _ = _doctor({})

        payload = json.loads(out)
        self.assertEqual(code, 0)
        self.assertTrue(payload["valid"])
        self.assertIsNone(payload["config_path"])
        self.assertEqual(payload["config_source"], "built-in empty config")
        self.assertEqual(payload["rule_count"], 0)

    def test_reports_the_active_path_from_the_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
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

            code, out, _ = _doctor({"VINCTOR_HERMES_PLUGIN_CONFIG": str(path)})

        payload = json.loads(out)
        self.assertEqual(code, 0)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["config_path"], str(path))
        self.assertEqual(payload["config_source"], "VINCTOR_HERMES_PLUGIN_CONFIG")
        self.assertEqual(payload["rule_count"], 1)

    def test_a_broken_configured_path_is_visible_and_non_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.json"

            code, out, _ = _doctor({"VINCTOR_HERMES_PLUGIN_CONFIG": str(missing)})

        payload = json.loads(out)
        self.assertEqual(code, 1)
        self.assertFalse(payload["valid"])
        self.assertEqual(payload["config_path"], str(missing))
        self.assertEqual(payload["config_source"], "VINCTOR_HERMES_PLUGIN_CONFIG")
        self.assertTrue(payload["errors"])
        self.assertIn("does not exist", payload["errors"][0])

    def test_text_output_names_the_active_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"version": 1, "rules": []}), encoding="utf-8")

            code, out, _ = _doctor(
                {"VINCTOR_HERMES_PLUGIN_CONFIG": str(path)}, json_output=False
            )

        self.assertEqual(code, 0)
        self.assertIn(str(path), out)


if __name__ == "__main__":
    unittest.main()
