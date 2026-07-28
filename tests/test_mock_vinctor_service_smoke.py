from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path

from vinctor_hermes_plugin.boundary import VinctorHermesBoundary

MOCK_AGENT_KEY = "aak_mock"
MOCK_GRANT_REF = "grt_mock"


class MockVinctorServiceSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock = _load_mock_module()

    def test_permit_response_allows_mapped_action(self):
        with _mock_service(
            self.mock,
            self.mock.MockDecisionConfig(
                default_decision="deny",
                permit=frozenset({"execute:shell/npm"}),
            ),
        ) as service:
            endpoint, _server = service
            result = _boundary(endpoint).pre_tool_call(
                tool_name="terminal",
                args={"command": "npm test"},
            )

        self.assertIsNone(result)

    def test_deny_response_blocks_mapped_action(self):
        with _mock_service(
            self.mock,
            self.mock.MockDecisionConfig(
                default_decision="permit",
                deny=frozenset({"deploy:vercel/app"}),
            ),
        ) as service:
            endpoint, _server = service
            result = _boundary(endpoint).pre_tool_call(
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

    def test_invalid_agent_key_fails_closed(self):
        with _mock_service(self.mock, self.mock.MockDecisionConfig()) as service:
            endpoint, _server = service
            result = _boundary(endpoint, agent_key="bad_key").pre_tool_call(
                tool_name="terminal",
                args={"command": "npm test"},
            )

        self.assertEqual(
            result,
            {
                "action": "block",
                "message": "Denied by Vinctor authorization: service_unavailable.",
            },
        )

    def test_boundary_id_is_forwarded_as_header_not_body(self):
        with _mock_service(
            self.mock,
            self.mock.MockDecisionConfig(
                default_decision="deny",
                permit=frozenset({"execute:shell/npm"}),
            ),
        ) as service:
            endpoint, server = service
            boundary = _boundary(endpoint, boundary_id="bnd_mock")
            result = boundary.pre_tool_call(
                tool_name="terminal",
                args={"command": "npm test"},
            )
            log_entry = server.mock_log[0]

        self.assertIsNone(result)
        self.assertEqual(log_entry.action_resource, "execute:shell/npm")
        self.assertEqual(log_entry.boundary_id, "bnd_mock")

    def test_unavailable_mock_fails_closed(self):
        with _mock_service(
            self.mock,
            self.mock.MockDecisionConfig(mode="unavailable", status=503),
        ) as service:
            endpoint, _server = service
            result = _boundary(endpoint).pre_tool_call(
                tool_name="terminal",
                args={"command": "npm test"},
            )

        self.assertEqual(
            result,
            {
                "action": "block",
                "message": "Denied by Vinctor authorization: service_unavailable.",
            },
        )

    def test_unreachable_endpoint_fails_closed(self):
        result = _boundary("http://127.0.0.1:1").pre_tool_call(
            tool_name="terminal",
            args={"command": "npm test"},
        )

        self.assertEqual(
            result,
            {
                "action": "block",
                "message": "Denied by Vinctor authorization: service_unavailable.",
            },
        )


class _mock_service:
    def __init__(self, mock, config):
        self.mock = mock
        self.config = config
        self.server = None
        self.thread = None

    def __enter__(self):
        try:
            self.server = self.mock.create_mock_server(("127.0.0.1", 0), config=self.config)
        except PermissionError as error:
            raise unittest.SkipTest("local socket bind is not permitted") from error
        self.thread = self.mock.run_server_in_thread(self.server)
        host, port = self.server.server_address
        return f"http://{host}:{port}", self.server

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


def _boundary(endpoint: str, *, agent_key: str = MOCK_AGENT_KEY, boundary_id: str | None = None):
    env = {
        "VINCTOR_ENDPOINT": endpoint,
        "VINCTOR_AGENT_KEY": agent_key,
        "VINCTOR_GRANT_REF": MOCK_GRANT_REF,
    }
    if boundary_id is not None:
        env["VINCTOR_BOUNDARY_ID"] = boundary_id
    boundary = VinctorHermesBoundary.from_env(env=env)
    return boundary


def _load_mock_module():
    root = Path(__file__).resolve().parents[2]
    core = Path(os.environ.get("VINCTOR_CORE_PATH", root / "vinctor-core"))
    mock_path = core / "tools" / "mock_vinctor_service.py"
    if not mock_path.exists():
        raise unittest.SkipTest(f"vinctor-core mock service not found at {mock_path}")
    spec = importlib.util.spec_from_file_location("mock_vinctor_service", mock_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["mock_vinctor_service"] = module
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    unittest.main()
