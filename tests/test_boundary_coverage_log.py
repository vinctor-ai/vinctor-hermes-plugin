import json
import tempfile
import unittest
from pathlib import Path

from vinctor_hermes_plugin.boundary import VinctorHermesBoundary
from vinctor_hermes_plugin.enforce import EnforceOutcome


class RecordingEnforcer:
    def __call__(self, grant_ref, action, resource):
        return EnforceOutcome(decision="permit", audit_event_id="evt_secret")


class BoundaryCoverageLogTests(unittest.TestCase):
    def test_coverage_log_records_hook_entry_without_raw_args_or_runtime_secrets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "coverage.jsonl"
            boundary = VinctorHermesBoundary.from_env(
                env={
                    **auth_env(),
                    "VINCTOR_HERMES_COVERAGE_LOG": str(log_path),
                },
                enforce_func=RecordingEnforcer(),
            )

            result = boundary.pre_tool_call(
                tool_name="terminal",
                args={"command": "npm test --token raw-secret"},
            )

            payload = log_path.read_text(encoding="utf-8")
            event = json.loads(payload)

        self.assertIsNone(result)
        self.assertEqual(event["event"], "pre_tool_call")
        self.assertEqual(event["tool_name"], "terminal")
        self.assertEqual(event["arg_keys"], ["command"])
        self.assertEqual(event["mapping_status"], "mapped")
        self.assertEqual(event["action"], "execute")
        self.assertEqual(event["resource"], "shell/npm")
        self.assertEqual(event["blocked"], False)
        self.assertIn("args_sha256", event)
        self.assertNotIn("raw-secret", payload)
        self.assertNotIn("grt_secret", payload)
        self.assertNotIn("evt_secret", payload)

    def test_coverage_log_records_strict_unmapped_blocking(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "coverage.jsonl"
            boundary = VinctorHermesBoundary.from_env(
                env={
                    **auth_env(),
                    "VINCTOR_HERMES_COVERAGE_LOG": str(log_path),
                    "VINCTOR_HERMES_UNMAPPED_POLICY": "block",
                },
                enforce_func=RecordingEnforcer(),
            )

            result = boundary.pre_tool_call(tool_name="unknown_tool", args={"value": "x"})

            event = json.loads(log_path.read_text(encoding="utf-8"))

        self.assertEqual(
            result,
            {
                "action": "block",
                "message": "Denied by Vinctor authorization: unmapped_tool.",
            },
        )
        self.assertEqual(event["tool_name"], "unknown_tool")
        self.assertEqual(event["mapping_status"], "unmapped")
        self.assertEqual(event["strict_unmapped_policy"], "block")
        self.assertEqual(event["blocked"], True)
        self.assertEqual(event["block_reason"], "unmapped_tool")

    def test_coverage_log_records_defer_as_the_default_unmapped_policy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "coverage.jsonl"
            boundary = VinctorHermesBoundary.from_env(
                env={
                    **auth_env(),
                    "VINCTOR_HERMES_COVERAGE_LOG": str(log_path),
                },
                enforce_func=RecordingEnforcer(),
            )

            result = boundary.pre_tool_call(tool_name="unknown_tool", args={"value": "x"})
            event = json.loads(log_path.read_text(encoding="utf-8"))

        self.assertIsNone(result)
        self.assertEqual(event["mapping_status"], "unmapped")
        self.assertEqual(event["strict_unmapped_policy"], "defer")
        self.assertEqual(event["blocked"], False)

    def test_coverage_log_can_include_raw_args_for_controlled_fixture_runs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "coverage.jsonl"
            boundary = VinctorHermesBoundary.from_env(
                env={
                    **auth_env(),
                    "VINCTOR_HERMES_COVERAGE_LOG": str(log_path),
                    "VINCTOR_HERMES_COVERAGE_LOG_INCLUDE_ARGS": "1",
                },
                enforce_func=RecordingEnforcer(),
            )

            boundary.pre_tool_call(
                tool_name="terminal",
                args={"command": "npm test"},
            )

            event = json.loads(log_path.read_text(encoding="utf-8"))

        self.assertEqual(event["args"], {"command": "npm test"})


def auth_env():
    return {
        "VINCTOR_ENDPOINT": "http://127.0.0.1:9999",
        "VINCTOR_AGENT_KEY": "aak_secret",
        "VINCTOR_GRANT_REF": "grt_secret",
    }


if __name__ == "__main__":
    unittest.main()
