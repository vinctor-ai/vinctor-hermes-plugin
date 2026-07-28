import json
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from vinctor_hermes_plugin.boundary import VinctorHermesBoundary
from vinctor_hermes_plugin.enforce import ActionDeniedError, EnforceOutcome, ServiceUnavailableError


class _EnforceHandler(BaseHTTPRequestHandler):
    """Answers POST /v1/enforce with a configured body over real HTTP."""

    body: dict = {}
    hits = 0

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler API
        type(self).hits += 1
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        payload = json.dumps(self.body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        return


@contextmanager
def serving(body):
    """A real listening service returning `body` — no opener injection."""
    handler = type("_H", (_EnforceHandler,), {"body": body, "hits": 0})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", handler
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


class ContractService:
    def __init__(self):
        self.audit_events = []

    def enforce(self, grant_ref, action, resource):
        del grant_ref
        scope = f"{action}:{resource}"
        allowed = {
            "execute:shell/npm",
            "write:repo/src/app.py",
            "execute:deploy/staging",
        }
        decision = "permit" if scope in allowed else "deny"
        audit_event = {
            "event_id": f"evt_{len(self.audit_events) + 1}",
            "decision": decision,
            "action": action,
            "resource": resource,
        }
        self.audit_events.append(audit_event)
        if decision == "permit":
            return EnforceOutcome(decision="permit", audit_event_id=audit_event["event_id"])
        raise ActionDeniedError("action_denied", audit_event["event_id"])


class InjectedServiceContractTests(unittest.TestCase):
    def test_injected_boundary_proves_permit_deny_fail_closed_and_audit(self):
        service = ContractService()
        boundary = VinctorHermesBoundary.from_env(
            env=auth_env("http://127.0.0.1:9999"),
            enforce_func=service.enforce,
        )

        permit = boundary.pre_tool_call(tool_name="terminal", args={"command": "npm test"})
        deny = boundary.pre_tool_call(
            tool_name="terminal", args={"command": "vercel deploy --prod"}
        )
        fail_closed = VinctorHermesBoundary.from_env(
            env=auth_env("http://127.0.0.1:1"),
            enforce_func=lambda grant_ref, action, resource: (_ for _ in ()).throw(
                ServiceUnavailableError("connection refused")
            ),
        ).pre_tool_call(
            tool_name="terminal",
            args={"command": "npm test"},
        )

        self.assertIsNone(permit)
        self.assertEqual(
            deny,
            {
                "action": "block",
                "message": "Denied by Vinctor authorization: action_denied.",
            },
        )
        self.assertEqual(
            fail_closed,
            {
                "action": "block",
                "message": "Denied by Vinctor authorization: service_unavailable.",
            },
        )
        self.assertEqual(
            service.audit_events,
            [
                {
                    "event_id": "evt_1",
                    "decision": "permit",
                    "action": "execute",
                    "resource": "shell/npm",
                },
                {
                    "event_id": "evt_2",
                    "decision": "deny",
                    "action": "deploy",
                    "resource": "vercel/app",
                },
            ],
        )


class AuditlessPermitE2ETests(unittest.TestCase):
    """PKA-116 over REAL HTTP: a 200 permit whose audit_event_id is missing,
    null, empty, whitespace-only, or not a string must block end-to-end —
    boundary -> real EnforceClient -> real socket -> real urllib response.

    The first version of this test injected a fake opener, so it never
    exercised the HTTP path it claimed to cover (review finding)."""

    def test_boundary_blocks_a_permit_without_a_usable_audit_event_id(self):
        for body in (
            {"decision": "permit"},
            {"decision": "permit", "audit_event_id": None},
            {"decision": "permit", "audit_event_id": ""},
            {"decision": "permit", "audit_event_id": "   "},
            {"decision": "permit", "audit_event_id": 123},
            {"decision": "permit", "audit_event_id": ["evt_1"]},
            {"decision": "permit", "audit_event_id": {"id": "evt_1"}},
        ):
            with self.subTest(body=body), serving(body) as (endpoint, handler):
                boundary = VinctorHermesBoundary.from_env(env=auth_env(endpoint))

                result = boundary.pre_tool_call(
                    tool_name="terminal", args={"command": "npm test"}
                )

                self.assertEqual(
                    result,
                    {
                        "action": "block",
                        "message": "Denied by Vinctor authorization: service_unavailable.",
                    },
                )
                self.assertEqual(handler.hits, 1)

    def test_a_real_permit_carrying_an_audit_event_id_is_allowed(self):
        with serving({"decision": "permit", "audit_event_id": "evt_real"}) as (
            endpoint,
            handler,
        ):
            boundary = VinctorHermesBoundary.from_env(env=auth_env(endpoint))

            self.assertIsNone(
                boundary.pre_tool_call(tool_name="terminal", args={"command": "npm test"})
            )
            self.assertEqual(handler.hits, 1)


def auth_env(endpoint):
    return {
        "VINCTOR_ENDPOINT": endpoint,
        "VINCTOR_AGENT_KEY": "aak_test",
        "VINCTOR_GRANT_REF": "grt_test",
    }
