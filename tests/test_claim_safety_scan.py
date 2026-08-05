import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ClaimSafetyScanTests(unittest.TestCase):
    def test_scan_fails_on_prohibited_claim(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "README.md"
            target.write_text(
                "\n".join(
                    [
                        "This is an official Hermes integration.",
                        "This provides sandboxing.",
                        "This is a hosted service.",
                        "This supports raw tool interception.",
                    ]
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, "scripts/claim_safety_scan.py", str(target)],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("official Hermes integration", result.stdout)
        self.assertIn("provides sandboxing", result.stdout)
        self.assertIn("hosted service", result.stdout)
        self.assertIn("raw tool interception", result.stdout)

    def test_scan_allows_non_claim_disclaimer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "README.md"
            target.write_text(
                "This is not an official Hermes integration.\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, "scripts/claim_safety_scan.py", str(target)],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
