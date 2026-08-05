import io
import json
import unittest
import urllib.error

from vinctor_hermes_plugin.enforce import (
    ActionDeniedError,
    EnforceClient,
    ServiceUnavailableError,
)


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.body).encode("utf-8")


class RecordingOpener:
    def __init__(self, response=None, error=None):
        self.response = response or FakeResponse(
            200, {"decision": "permit", "audit_event_id": "evt_permit"}
        )
        self.error = error
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        if self.error is not None:
            raise self.error
        return self.response


class EnforceClientTests(unittest.TestCase):
    def test_permit_posts_strict_v1_body_and_agent_key(self):
        opener = RecordingOpener()
        client = EnforceClient(
            endpoint="https://vinctor.example",
            agent_key="aak_test",
            timeout_ms=500,
            opener=opener,
        )

        outcome = client.enforce("grt_test", "write", "repo/src/app.py")

        request, timeout = opener.requests[0]
        self.assertEqual(outcome.decision, "permit")
        self.assertEqual(outcome.audit_event_id, "evt_permit")
        self.assertEqual(request.full_url, "https://vinctor.example/v1/enforce")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.headers["X-agent-key"], "aak_test")
        self.assertEqual(timeout, 0.5)
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {
                "grant_ref": "grt_test",
                "action": "write",
                "resource": "repo/src/app.py",
            },
        )

    def test_optional_boundary_id_header_is_forwarded(self):
        opener = RecordingOpener()
        client = EnforceClient(
            endpoint="https://vinctor.example",
            agent_key="aak_test",
            boundary_id="bnd_hermes",
            timeout_ms=500,
            opener=opener,
        )

        client.enforce("grt_test", "execute", "ci/test")

        request, _timeout = opener.requests[0]
        self.assertEqual(request.headers["X-vinctor-boundary-id"], "bnd_hermes")

    def test_deny_raises_action_denied_with_audit_id(self):
        error = urllib.error.HTTPError(
            url="https://vinctor.example/v1/enforce",
            code=403,
            msg="Forbidden",
            hdrs={},
            fp=io.BytesIO(
                json.dumps(
                    {
                        "decision": "deny",
                        "error": "action_denied",
                        "audit_event_id": "evt_deny",
                    }
                ).encode("utf-8")
            ),
        )
        client = EnforceClient(
            endpoint="https://vinctor.example",
            agent_key="aak_test",
            timeout_ms=500,
            opener=RecordingOpener(error=error),
        )

        with self.assertRaises(ActionDeniedError) as caught:
            client.enforce("grt_test", "execute", "deploy/production")

        self.assertEqual(caught.exception.reason, "action_denied")
        self.assertEqual(caught.exception.audit_event_id, "evt_deny")

    def test_unavailable_endpoint_raises_service_unavailable(self):
        client = EnforceClient(
            endpoint="http://127.0.0.1:1",
            agent_key="aak_test",
            timeout_ms=50,
            opener=RecordingOpener(error=OSError("connection refused")),
        )

        with self.assertRaises(ServiceUnavailableError):
            client.enforce("grt_test", "execute", "ci/test")

    def test_200_response_must_explicitly_permit(self):
        cases = [
            FakeResponse(200, {"decision": "deny", "audit_event_id": "evt_wrong"}),
            FakeResponse(200, {"audit_event_id": "evt_missing_decision"}),
        ]
        for response in cases:
            with self.subTest(body=response.body):
                client = EnforceClient(
                    endpoint="https://vinctor.example",
                    agent_key="aak_test",
                    timeout_ms=500,
                    opener=RecordingOpener(response=response),
                )

                with self.assertRaises(ServiceUnavailableError):
                    client.enforce("grt_test", "execute", "ci/test")

    def test_200_permit_requires_a_non_empty_audit_event_id(self):
        # PKA-116: a permit without durable decision evidence is not a permit.
        # Every allowed action must carry a non-empty string audit_event_id, in
        # parity with the other adapters; anything else fails closed.
        invalid_bodies = [
            {"decision": "permit"},  # missing
            {"decision": "permit", "audit_event_id": None},  # null
            {"decision": "permit", "audit_event_id": ""},  # empty
            {"decision": "permit", "audit_event_id": 123},  # non-string
            {"decision": "permit", "audit_event_id": "   "},  # whitespace-only
            {"decision": "permit", "audit_event_id": "\u0085"},  # NEL
            {"decision": "permit", "audit_event_id": "\ufeff"},  # BOM
            {"decision": "permit", "audit_event_id": "\u200b"},  # zero-width space
            {"decision": "permit", "audit_event_id": "\u001c"},  # information separator
            {"decision": "permit", "audit_event_id": ["evt"]},  # non-scalar
        ]
        for body in invalid_bodies:
            with self.subTest(body=body):
                client = EnforceClient(
                    endpoint="https://vinctor.example",
                    agent_key="aak_test",
                    timeout_ms=500,
                    opener=RecordingOpener(response=FakeResponse(200, body)),
                )
                with self.assertRaises(ServiceUnavailableError):
                    client.enforce("grt_test", "execute", "ci/test")

    def test_200_permit_with_audit_event_id_succeeds(self):
        client = EnforceClient(
            endpoint="https://vinctor.example",
            agent_key="aak_test",
            timeout_ms=500,
            opener=RecordingOpener(
                response=FakeResponse(200, {"decision": "permit", "audit_event_id": "evt_permit"})
            ),
        )

        outcome = client.enforce("grt_test", "execute", "ci/test")

        self.assertEqual(outcome.decision, "permit")
        self.assertEqual(outcome.audit_event_id, "evt_permit")
