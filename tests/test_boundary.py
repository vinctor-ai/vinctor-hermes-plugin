import json
import tempfile
import unittest
from pathlib import Path

from vinctor_hermes_plugin.boundary import VinctorHermesBoundary, _client_from_env
from vinctor_hermes_plugin.config import Config
from vinctor_hermes_plugin.enforce import ActionDeniedError, EnforceOutcome, ServiceUnavailableError


class RecordingEnforcer:
    def __init__(self, outcome=None, error=None):
        self.outcome = outcome or EnforceOutcome(decision="permit", audit_event_id="evt_ok")
        self.error = error
        self.calls = []

    def __call__(self, grant_ref, action, resource):
        self.calls.append((grant_ref, action, resource))
        if self.error is not None:
            raise self.error
        return self.outcome


class BoundaryTests(unittest.TestCase):
    def test_permit_returns_none_and_allows_hermes_to_continue(self):
        enforcer = RecordingEnforcer()
        boundary = VinctorHermesBoundary(
            env=auth_env(),
            config=Config(version=1, rules=()),
            enforce_func=enforcer,
        )

        result = boundary.pre_tool_call(tool_name="terminal", args={"command": "npm test"})

        self.assertIsNone(result)
        self.assertEqual(enforcer.calls, [("grt_test", "execute", "shell/npm")])

    def test_deny_returns_safe_block_directive_without_execution_details(self):
        enforcer = RecordingEnforcer(error=ActionDeniedError("action_denied", "evt_secret"))
        boundary = VinctorHermesBoundary(
            env=auth_env(),
            config=Config(version=1, rules=()),
            enforce_func=enforcer,
        )

        result = boundary.pre_tool_call(
            tool_name="terminal",
            args={"command": "vercel deploy --prod"},
        )

        self.assertEqual(
            result,
            {
                "action": "block",
                "message": "Denied by Vinctor authorization: action_denied.",
            },
        )
        self.assertNotIn("evt_secret", result["message"])
        self.assertNotIn("deploy/production", result["message"])

    def test_missing_auth_blocks_only_mapped_calls(self):
        boundary = VinctorHermesBoundary(
            env={},
            config=Config(version=1, rules=()),
            enforce_func=RecordingEnforcer(),
        )

        mapped = boundary.pre_tool_call(tool_name="terminal", args={"command": "npm test"})
        unmapped = boundary.pre_tool_call(tool_name="get_weather", args={"city": "Seoul"})

        self.assertEqual(
            mapped,
            {
                "action": "block",
                "message": "Denied by Vinctor authorization: missing_auth_env.",
            },
        )
        self.assertIsNone(unmapped)

    def test_explicit_defer_matches_the_default_unmapped_policy(self):
        enforcer = RecordingEnforcer()
        boundary = VinctorHermesBoundary(
            env={**auth_env(), "VINCTOR_HERMES_UNMAPPED_POLICY": "defer"},
            config=Config(version=1, rules=()),
            enforce_func=enforcer,
        )

        result = boundary.pre_tool_call(tool_name="get_weather", args={"city": "Seoul"})

        self.assertIsNone(result)
        self.assertEqual(enforcer.calls, [])

    def test_only_exact_block_enables_strict_unmapped_policy(self):
        enforcer = RecordingEnforcer()
        boundary = VinctorHermesBoundary(
            env={**auth_env(), "VINCTOR_HERMES_UNMAPPED_POLICY": "invalid"},
            config=Config(version=1, rules=()),
            enforce_func=enforcer,
        )

        result = boundary.pre_tool_call(tool_name="get_weather", args={"city": "Seoul"})

        self.assertIsNone(result)
        self.assertEqual(enforcer.calls, [])

    def test_strict_unmapped_policy_blocks_unknown_calls_without_service_call(self):
        enforcer = RecordingEnforcer()
        boundary = VinctorHermesBoundary(
            env={**auth_env(), "VINCTOR_HERMES_UNMAPPED_POLICY": "block"},
            config=Config(version=1, rules=()),
            enforce_func=enforcer,
        )

        result = boundary.pre_tool_call(tool_name="get_weather", args={"city": "Seoul"})

        self.assertEqual(
            result,
            {
                "action": "block",
                "message": "Denied by Vinctor authorization: unmapped_tool.",
            },
        )
        self.assertEqual(enforcer.calls, [])

    def test_shell_safety_rejection_blocks_without_opt_in_unmapped_policy(self):
        enforcer = RecordingEnforcer()
        boundary = VinctorHermesBoundary(
            env=auth_env(),
            config=Config(version=1, rules=()),
            enforce_func=enforcer,
        )

        result = boundary.pre_tool_call(
            tool_name="terminal",
            args={"command": "git status\nrm -rf ~/x"},
        )

        self.assertEqual(
            result,
            {
                "action": "block",
                "message": "Denied by Vinctor authorization: unmapped_tool.",
            },
        )
        self.assertEqual(enforcer.calls, [])

    def test_permit_and_deny_can_record_non_model_decision_metadata(self):
        events = []
        boundary = VinctorHermesBoundary(
            env=auth_env(),
            config=Config(version=1, rules=()),
            enforce_func=RecordingEnforcer(
                outcome=EnforceOutcome(decision="permit", audit_event_id="evt_ok")
            ),
            decision_recorder=events.append,
        )

        result = boundary.pre_tool_call(tool_name="terminal", args={"command": "npm test"})

        self.assertIsNone(result)
        self.assertEqual(
            events,
            [
                {
                    "decision": "permit",
                    "action": "execute",
                    "resource": "shell/npm",
                    "audit_event_id": "evt_ok",
                }
            ],
        )

    def test_env_decision_log_writes_local_jsonl_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "decisions.jsonl"
            boundary = VinctorHermesBoundary.from_env(
                env={**auth_env(), "VINCTOR_HERMES_DECISION_LOG": str(log_path)},
                enforce_func=RecordingEnforcer(),
            )

            result = boundary.pre_tool_call(
                tool_name="terminal",
                args={"command": "npm test"},
            )

            self.assertIsNone(result)
            self.assertEqual(
                json.loads(log_path.read_text(encoding="utf-8")),
                {
                    "decision": "permit",
                    "action": "execute",
                    "resource": "shell/npm",
                    "audit_event_id": "evt_ok",
                },
            )

    def test_env_boundary_id_is_available_to_enforce_client(self):
        client = _client_from_env({**auth_env(), "VINCTOR_BOUNDARY_ID": "bnd_hermes"})

        self.assertEqual(client.boundary_id, "bnd_hermes")

    def test_service_unavailable_blocks_mapped_calls(self):
        boundary = VinctorHermesBoundary(
            env=auth_env(),
            config=Config(version=1, rules=()),
            enforce_func=RecordingEnforcer(error=ServiceUnavailableError("connection refused")),
        )

        result = boundary.pre_tool_call(tool_name="terminal", args={"command": "npm test"})

        self.assertEqual(
            result,
            {
                "action": "block",
                "message": "Denied by Vinctor authorization: service_unavailable.",
            },
        )

    def test_invalid_config_blocks_before_mapping(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "bad.json"
            config_path.write_text('{"version": 2, "rules": []}', encoding="utf-8")
            boundary = VinctorHermesBoundary.from_env(
                env={**auth_env(), "VINCTOR_HERMES_PLUGIN_CONFIG": str(config_path)}
            )

            result = boundary.pre_tool_call(tool_name="get_weather", args={"city": "Seoul"})

            self.assertEqual(
                result,
                {
                    "action": "block",
                    "message": "Denied by Vinctor authorization: invalid_config.",
                },
            )

    def test_malformed_mapped_call_blocks_without_service_call(self):
        enforcer = RecordingEnforcer()
        boundary = VinctorHermesBoundary(
            env=auth_env(),
            config=Config(version=1, rules=()),
            enforce_func=enforcer,
        )

        result = boundary.pre_tool_call(
            tool_name="write_file",
            args={"path": "src/app.py\0secret"},
        )

        self.assertEqual(
            result,
            {
                "action": "block",
                "message": "Denied by Vinctor authorization: parse_unsafe.",
            },
        )
        self.assertEqual(enforcer.calls, [])


def auth_env():
    return {
        "VINCTOR_ENDPOINT": "http://127.0.0.1:9999",
        "VINCTOR_AGENT_KEY": "aak_test",
        "VINCTOR_GRANT_REF": "grt_test",
    }
