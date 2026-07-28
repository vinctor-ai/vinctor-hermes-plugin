import json
import unittest

from tests.test_enforce import FakeResponse, RecordingOpener
from vinctor_hermes_plugin.enforce import EnforceClient


class EnforceBodyStrictTests(unittest.TestCase):
    def test_enforce_body_contains_exactly_v1_contract_fields(self):
        opener = RecordingOpener(
            response=FakeResponse(200, {"decision": "permit", "audit_event_id": "evt_ok"})
        )
        client = EnforceClient(
            endpoint="https://vinctor.example",
            agent_key="aak_test",
            timeout_ms=500,
            opener=opener,
        )

        client.enforce("grt_test", "write", "repo/src/app.py")

        request, _timeout = opener.requests[0]
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(set(body), {"grant_ref", "action", "resource"})
        self.assertEqual(
            body,
            {
                "grant_ref": "grt_test",
                "action": "write",
                "resource": "repo/src/app.py",
            },
        )

    def test_enforce_uses_agent_key_header_not_body_token(self):
        opener = RecordingOpener(
            response=FakeResponse(200, {"decision": "permit", "audit_event_id": "evt_ok"})
        )
        client = EnforceClient(
            endpoint="https://vinctor.example",
            agent_key="aak_test",
            timeout_ms=500,
            opener=opener,
        )

        client.enforce("grt_test", "execute", "ci/test")

        request, _timeout = opener.requests[0]
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.headers["X-agent-key"], "aak_test")
        self.assertNotIn("agent_key", body)
        self.assertNotIn("workspace_token", body)


if __name__ == "__main__":
    unittest.main()
