import tempfile
import unittest
from pathlib import Path

from vinctor_hermes_plugin.boundary import VinctorHermesBoundary
from vinctor_hermes_plugin.config import Config, Rule
from vinctor_hermes_plugin.enforce import ActionDeniedError, ServiceUnavailableError

SECRET_ENV = {
    "VINCTOR_ENDPOINT": "http://127.0.0.1:9999",
    "VINCTOR_AGENT_KEY": "aak_secret_agent",
    "VINCTOR_GRANT_REF": "grt_secret_runtime_ref",
}

SENSITIVE_STRINGS = [
    "aak_secret_agent",
    "grt_secret_runtime_ref",
    "evt_secret_audit",
    "raw-secret-token",
    "deploy/production",
    "exact-secret-pattern",
    "service-body-with-token",
    "src/app.py",
]


class NonDisclosureMatrixTests(unittest.TestCase):
    def test_denial_and_service_failure_do_not_disclose_sensitive_values(self):
        cases = [
            ("action_denied", ActionDeniedError("action_denied", "evt_secret_audit")),
            ("service_unavailable", ServiceUnavailableError("service-body-with-token")),
        ]
        for reason, error in cases:
            with self.subTest(reason=reason):
                boundary = VinctorHermesBoundary(
                    env=SECRET_ENV,
                    config=_sensitive_config(),
                    enforce_func=lambda grant_ref, action, resource, error=error: (
                        _ for _ in ()
                    ).throw(error),
                )

                result = boundary.pre_tool_call(
                    tool_name="terminal",
                    args={"command": "deploy --token raw-secret-token"},
                )

                self.assertEqual(result["message"], f"Denied by Vinctor authorization: {reason}.")
                self._assert_no_sensitive_output(result)

    def test_missing_auth_parse_unsafe_and_malformed_payload_are_safe(self):
        cases = [
            (
                VinctorHermesBoundary(env={}, config=Config(version=1, rules=())),
                "terminal",
                {"command": "deploy --token raw-secret-token"},
                "missing_auth_env",
            ),
            (
                VinctorHermesBoundary(env=SECRET_ENV, config=Config(version=1, rules=())),
                "write_file",
                {"path": "src/app.py\0raw-secret-token"},
                "parse_unsafe",
            ),
            (
                VinctorHermesBoundary(env=SECRET_ENV, config=Config(version=1, rules=())),
                "write_file",
                {},
                "malformed_payload",
            ),
        ]
        for boundary, tool_name, args, reason in cases:
            with self.subTest(reason=reason):
                result = boundary.pre_tool_call(tool_name=tool_name, args=args)

                self.assertEqual(result["message"], f"Denied by Vinctor authorization: {reason}.")
                self._assert_no_sensitive_output(result)

    def test_invalid_config_message_does_not_disclose_config_contents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "bad.json"
            config_path.write_text(
                '{"version":2,"rules":[{"pattern":"exact-secret-pattern"}]}',
                encoding="utf-8",
            )
            boundary = VinctorHermesBoundary.from_env(
                env={**SECRET_ENV, "VINCTOR_HERMES_PLUGIN_CONFIG": str(config_path)}
            )

            result = boundary.pre_tool_call(
                tool_name="terminal",
                args={"command": "deploy --token raw-secret-token"},
            )

        self.assertEqual(result["message"], "Denied by Vinctor authorization: invalid_config.")
        self._assert_no_sensitive_output(result)

    def _assert_no_sensitive_output(self, result):
        serialized = str(result)
        for sensitive in SENSITIVE_STRINGS:
            self.assertNotIn(sensitive, serialized)


def _sensitive_config():
    return Config(
        version=1,
        rules=(
            Rule(
                tool="terminal",
                match_type="exact",
                pattern="deploy --token raw-secret-token",
                action="execute",
                resource="deploy/production",
                input_field=None,
            ),
        ),
    )


if __name__ == "__main__":
    unittest.main()
