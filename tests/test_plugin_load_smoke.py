import subprocess
import sys
import unittest
from pathlib import Path


class PluginLoadSmokeTests(unittest.TestCase):
    def test_plugin_load_smoke_reports_registered_pre_tool_call(self):
        result = subprocess.run(
            [sys.executable, "scripts/plugin_load_smoke.py"],
            cwd=Path(__file__).resolve().parents[1],
            env={"PYTHONPATH": "src"},
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "registered pre_tool_call\n")
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
