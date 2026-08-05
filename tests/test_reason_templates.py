import unittest

from vinctor_hermes_plugin.boundary import VinctorHermesBoundary
from vinctor_hermes_plugin.config import Config
from vinctor_hermes_plugin.enforce import ActionDeniedError

AUTH_ENV = {
    "VINCTOR_ENDPOINT": "http://127.0.0.1:9999",
    "VINCTOR_AGENT_KEY": "aak_test",
    "VINCTOR_GRANT_REF": "grt_test",
}

ALLOWED_MESSAGES = {
    "Denied by Vinctor authorization: action_denied.",
    "Denied by Vinctor authorization: missing_auth_env.",
    "Denied by Vinctor authorization: service_unavailable.",
    "Denied by Vinctor authorization: invalid_config.",
    "Denied by Vinctor authorization: parse_unsafe.",
    "Denied by Vinctor authorization: malformed_payload.",
    "Denied by Vinctor authorization: unmapped_tool.",
}


class ReasonTemplateTests(unittest.TestCase):
    def test_service_deny_reason_is_collapsed_to_fixed_template(self):
        boundary = VinctorHermesBoundary(
            env=AUTH_ENV,
            config=Config(version=1, rules=()),
            enforce_func=lambda grant_ref, action, resource: (_ for _ in ()).throw(
                ActionDeniedError("raw-deny-reason-with-secret", "evt_test")
            ),
        )

        result = boundary.pre_tool_call(tool_name="terminal", args={"command": "npm test"})

        self.assertEqual(
            result,
            {
                "action": "block",
                "message": "Denied by Vinctor authorization: action_denied.",
            },
        )

    def test_block_messages_stay_inside_known_public_templates(self):
        cases = [
            VinctorHermesBoundary(env={}, config=Config(version=1, rules=())),
            VinctorHermesBoundary(
                env={**AUTH_ENV, "VINCTOR_HERMES_UNMAPPED_POLICY": "block"},
                config=Config(version=1, rules=()),
            ),
        ]

        results = [
            cases[0].pre_tool_call(tool_name="terminal", args={"command": "npm test"}),
            cases[1].pre_tool_call(tool_name="unknown", args={}),
        ]

        for result in results:
            with self.subTest(result=result):
                self.assertEqual(result["action"], "block")
                self.assertIn(result["message"], ALLOWED_MESSAGES)


if __name__ == "__main__":
    unittest.main()
