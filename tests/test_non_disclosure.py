import unittest

from vinctor_hermes_plugin.boundary import VinctorHermesBoundary
from vinctor_hermes_plugin.config import Config, Rule
from vinctor_hermes_plugin.enforce import ActionDeniedError


class NonDisclosureTests(unittest.TestCase):
    def test_block_message_does_not_disclose_secret_runtime_values_or_tool_input(self):
        boundary = VinctorHermesBoundary(
            env={
                "VINCTOR_ENDPOINT": "http://127.0.0.1:9999",
                "VINCTOR_AGENT_KEY": "aak_secret_agent",
                "VINCTOR_GRANT_REF": "grt_secret_runtime_ref",
            },
            config=Config(
                version=1,
                rules=(
                    Rule(
                        tool="terminal",
                        match_type="exact",
                        pattern="deploy --token raw-secret-token",
                        action="execute",
                        resource="deploy/production",
                    ),
                ),
            ),
            enforce_func=lambda grant_ref, action, resource: (_ for _ in ()).throw(
                ActionDeniedError("action_denied", "evt_secret_audit")
            ),
        )

        result = boundary.pre_tool_call(
            tool_name="terminal",
            args={"command": "deploy --token raw-secret-token"},
        )
        serialized = str(result)

        self.assertEqual(
            result,
            {
                "action": "block",
                "message": "Denied by Vinctor authorization: action_denied.",
            },
        )
        self.assertNotIn("grt_secret_runtime_ref", serialized)
        self.assertNotIn("aak_secret_agent", serialized)
        self.assertNotIn("raw-secret-token", serialized)
        self.assertNotIn("evt_secret_audit", serialized)
        self.assertNotIn("deploy/production", serialized)
