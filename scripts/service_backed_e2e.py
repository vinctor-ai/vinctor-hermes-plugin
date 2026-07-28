#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from vinctor_hermes_plugin.boundary import VinctorHermesBoundary  # noqa: E402


class ContractServiceHandler(BaseHTTPRequestHandler):
    audit_events: list[dict[str, str]] = []

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return None

    def do_POST(self) -> None:
        if self.path != "/v1/enforce":
            self._send(404, {"error": "not_found"})
            return
        if self.headers.get("X-Agent-Key") != "aak_e2e":
            self._send(401, {"error": "authentication_required"})
            return
        length = int(self.headers["Content-Length"])
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        if set(body) != {"grant_ref", "action", "resource"}:
            self._send(400, {"error": "invalid_request"})
            return

        scope = f"{body['action']}:{body['resource']}"
        decision = "permit" if scope == "execute:shell/npm" else "deny"
        event = {
            "event_id": f"evt_{len(self.audit_events) + 1}",
            "decision": decision,
            "action": body["action"],
            "resource": body["resource"],
        }
        self.audit_events.append(event)
        if decision == "permit":
            self._send(200, {"decision": "permit", "audit_event_id": event["event_id"]})
        else:
            self._send(
                403,
                {
                    "decision": "deny",
                    "error": "action_denied",
                    "audit_event_id": event["event_id"],
                },
            )

    def _send(self, status: int, body: dict[str, str]) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> int:
    endpoint, server, thread = _start_service()
    try:
        boundary = VinctorHermesBoundary.from_env(env=_env(endpoint))
        permit = boundary.pre_tool_call(tool_name="terminal", args={"command": "npm test"})
        deny = boundary.pre_tool_call(
            tool_name="terminal", args={"command": "vercel deploy --prod"}
        )
        fail_closed = VinctorHermesBoundary.from_env(env=_env("http://127.0.0.1:1")).pre_tool_call(
            tool_name="terminal",
            args={"command": "npm test"},
        )

        assert permit is None
        assert deny == {
            "action": "block",
            "message": "Denied by Vinctor authorization: action_denied.",
        }
        assert fail_closed == {
            "action": "block",
            "message": "Denied by Vinctor authorization: service_unavailable.",
        }
        assert ContractServiceHandler.audit_events == [
            {
                "event_id": "evt_1",
                "decision": "permit",
                "action": "execute",
                "resource": "shell/npm",
            },
            {
                "event_id": "evt_2",
                "decision": "deny",
                # Converged taxonomy (D-2): platform deploys use the `deploy`
                # verb with the platform resource, not execute:deploy/{env}.
                "action": "deploy",
                "resource": "vercel/app",
            },
        ]
        print("ALL VINCTOR HERMES PLUGIN SERVICE E2E STEPS PASSED")
        return 0
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _start_service() -> tuple[str, ThreadingHTTPServer, threading.Thread]:
    ContractServiceHandler.audit_events = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), ContractServiceHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return f"http://{host}:{port}", server, thread


def _env(endpoint: str) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "VINCTOR_ENDPOINT": endpoint,
            "VINCTOR_AGENT_KEY": "aak_e2e",
            "VINCTOR_GRANT_REF": "grt_e2e",
        }
    )
    return env


if __name__ == "__main__":
    raise SystemExit(main())
