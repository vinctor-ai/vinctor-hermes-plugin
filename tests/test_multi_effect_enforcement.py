import json
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from vinctor_hermes_plugin.boundary import VinctorHermesBoundary


class _EnforceHandler(BaseHTTPRequestHandler):
    """A real /v1/enforce that permits or denies per (action, resource)."""

    deny_pairs: set = set()
    seen: list = []

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler API
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        body = json.loads(raw.decode("utf-8"))
        pair = (body.get("action"), body.get("resource"))
        type(self).seen.append(pair)
        if pair in type(self).deny_pairs:
            payload = json.dumps(
                {"decision": "deny", "error": "action_denied", "audit_event_id": "evt_deny"}
            ).encode("utf-8")
            self.send_response(403)
        else:
            payload = json.dumps(
                {"decision": "permit", "audit_event_id": "evt_ok"}
            ).encode("utf-8")
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        return


@contextmanager
def serving(deny_pairs=frozenset()):
    handler = type(
        "_H", (_EnforceHandler,), {"deny_pairs": set(deny_pairs), "seen": []}
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", handler
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def env(endpoint):
    return {
        "VINCTOR_ENDPOINT": endpoint,
        "VINCTOR_AGENT_KEY": "aak_test",
        "VINCTOR_GRANT_REF": "grt_test",
    }


BLOCK = {"action": "block", "message": "Denied by Vinctor authorization: action_denied."}
MOVE = {"source": "/home/u/.env", "destination": "/tmp/x"}
PATCH = (
    "*** Begin Patch\n"
    "*** Update File: src/app.py\n"
    "*** Delete File: /home/u/.env\n"
    "*** Add File: /tmp/exfil\n"
    "*** End Patch"
)


class MultiEffectEnforcementTests(unittest.TestCase):
    """PKA-145 at the enforcement point, over a real socket.

    Mapping the extra effects is only half the fix: the boundary must actually
    ASK the PDP for every one of them, and one denial must deny the whole call.
    A boundary that maps three effects and enforces one is exactly as unsafe as
    before — so every assertion here also checks what reached the service.
    """

    def test_move_file_asks_for_all_three_effects(self):
        with serving() as (endpoint, handler):
            boundary = VinctorHermesBoundary.from_env(env=env(endpoint))
            result = boundary.pre_tool_call(tool_name="move_file", args=dict(MOVE))

        self.assertIsNone(result)
        self.assertEqual(
            set(handler.seen),
            {
                ("write", "fs/tmp/x"),
                ("read", "secret/env"),
                ("delete", "secret/env"),
            },
        )

    def test_denying_only_the_source_read_denies_the_whole_move(self):
        with serving({("read", "secret/env")}) as (endpoint, handler):
            boundary = VinctorHermesBoundary.from_env(env=env(endpoint))
            result = boundary.pre_tool_call(tool_name="move_file", args=dict(MOVE))

        self.assertEqual(result, BLOCK)
        self.assertIn(("read", "secret/env"), handler.seen)

    def test_denying_only_the_source_delete_denies_the_whole_move(self):
        with serving({("delete", "secret/env")}) as (endpoint, _handler):
            boundary = VinctorHermesBoundary.from_env(env=env(endpoint))
            result = boundary.pre_tool_call(tool_name="move_file", args=dict(MOVE))

        self.assertEqual(result, BLOCK)

    def test_denying_only_the_destination_write_denies_the_whole_move(self):
        with serving({("write", "fs/tmp/x")}) as (endpoint, _handler):
            boundary = VinctorHermesBoundary.from_env(env=env(endpoint))
            result = boundary.pre_tool_call(tool_name="move_file", args=dict(MOVE))

        self.assertEqual(result, BLOCK)

    def test_patch_asks_for_every_target(self):
        with serving() as (endpoint, handler):
            boundary = VinctorHermesBoundary.from_env(env=env(endpoint))
            result = boundary.pre_tool_call(tool_name="patch", args={"patch": PATCH})

        self.assertIsNone(result)
        self.assertEqual(
            set(handler.seen),
            {
                ("write", "repo/src/app.py"),
                ("delete", "secret/env"),
                ("write", "fs/tmp/exfil"),
            },
        )

    def test_denying_any_single_patch_target_denies_the_whole_patch(self):
        for denied in [
            ("write", "repo/src/app.py"),
            ("delete", "secret/env"),
            ("write", "fs/tmp/exfil"),
        ]:
            with self.subTest(denied=denied):
                with serving({denied}) as (endpoint, _handler):
                    boundary = VinctorHermesBoundary.from_env(env=env(endpoint))
                    result = boundary.pre_tool_call(tool_name="patch", args={"patch": PATCH})
                self.assertEqual(result, BLOCK)

    def test_a_service_failure_on_any_effect_fails_closed(self):
        # Unreachable service on the very first check: no effect may be assumed.
        boundary = VinctorHermesBoundary.from_env(env=env("http://127.0.0.1:1"))
        result = boundary.pre_tool_call(tool_name="move_file", args=dict(MOVE))
        self.assertEqual(
            result,
            {"action": "block", "message": "Denied by Vinctor authorization: service_unavailable."},
        )

    def test_a_single_effect_call_still_asks_exactly_once(self):
        with serving() as (endpoint, handler):
            boundary = VinctorHermesBoundary.from_env(env=env(endpoint))
            result = boundary.pre_tool_call(
                tool_name="read_file", args={"path": "src/app.py"}
            )

        self.assertIsNone(result)
        self.assertEqual(handler.seen, [("read", "repo/src/app.py")])


READ_TOOL = "mcp__filesystem__read_multiple_files"
MIXED_LIST = {"paths": ["/repo/notes.txt", "/home/u/.env", "/home/u/.ssh/id_rsa"]}


class ReadMultipleFilesEnforcementTests(unittest.TestCase):
    """PKA-148 at the enforcement point, over a real socket.

    The pre-fix resolver sent `read secret/env` ALONE for the mixed list, so a
    secret/env grant read the ssh key and the ordinary file too — and an
    all-ordinary list was unmapped, which the default policy defers OPEN with
    ZERO enforce calls. Every assertion here checks what reached the service.
    """

    def test_read_multiple_files_asks_for_every_distinct_resource(self):
        with serving() as (endpoint, handler):
            boundary = VinctorHermesBoundary.from_env(env=env(endpoint))
            result = boundary.pre_tool_call(tool_name=READ_TOOL, args=dict(MIXED_LIST))

        self.assertIsNone(result)
        self.assertEqual(
            set(handler.seen),
            {
                ("read", "secret/env"),
                ("read", "secret/ssh"),
                ("read", "fs/repo/notes.txt"),
            },
        )
        self.assertEqual(len(handler.seen), 3, "one PDP question per distinct resource")

    def test_the_exploit_denying_the_ssh_read_denies_the_whole_list(self):
        with serving({("read", "secret/ssh")}) as (endpoint, handler):
            boundary = VinctorHermesBoundary.from_env(env=env(endpoint))
            result = boundary.pre_tool_call(tool_name=READ_TOOL, args=dict(MIXED_LIST))

        self.assertEqual(result, BLOCK)
        self.assertIn(("read", "secret/ssh"), handler.seen)

    def test_denying_the_ordinary_member_denies_the_whole_list(self):
        with serving({("read", "fs/repo/notes.txt")}) as (endpoint, _handler):
            boundary = VinctorHermesBoundary.from_env(env=env(endpoint))
            result = boundary.pre_tool_call(tool_name=READ_TOOL, args=dict(MIXED_LIST))

        self.assertEqual(result, BLOCK)

    def test_an_all_ordinary_list_is_enforced_per_path_not_deferred(self):
        with serving() as (endpoint, handler):
            boundary = VinctorHermesBoundary.from_env(env=env(endpoint))
            result = boundary.pre_tool_call(
                tool_name=READ_TOOL, args={"paths": ["/repo/a.txt", "/docs/readme.md"]}
            )

        self.assertIsNone(result)
        self.assertEqual(
            set(handler.seen),
            {("read", "fs/repo/a.txt"), ("read", "fs/docs/readme.md")},
        )

    def test_paths_folding_to_the_same_resource_are_charged_once(self):
        with serving() as (endpoint, handler):
            boundary = VinctorHermesBoundary.from_env(env=env(endpoint))
            result = boundary.pre_tool_call(
                tool_name=READ_TOOL, args={"paths": ["/home/u/.env", "/home/u2/.env"]}
            )

        self.assertIsNone(result)
        self.assertEqual(handler.seen, [("read", "secret/env")])

    def test_an_inexpressible_member_blocks_with_zero_pdp_calls(self):
        # Even against a permit-everything PDP: no complete requirement set
        # exists, so no pair may be spent on a call that will not run.
        with serving() as (endpoint, handler):
            boundary = VinctorHermesBoundary.from_env(env=env(endpoint))
            result = boundary.pre_tool_call(
                tool_name=READ_TOOL, args={"paths": ["/repo/a.txt", "//", "/home/u/.env"]}
            )

        self.assertEqual(
            result,
            {"action": "block", "message": "Denied by Vinctor authorization: parse_unsafe."},
        )
        self.assertEqual(handler.seen, [])


MCP_MOVE_TOOL = "mcp__filesystem__move_file"
MCP_WRITE_TOOL = "mcp__filesystem__write_file"
NATIVE_READ_TOOL = "read_multiple_files"


class McpFilesystemSurfaceEnforcementTests(unittest.TestCase):
    """PKA-156 at the enforcement point, over a real socket.

    The MCP surface was a second, unfixed copy of the native one. Each test here
    drives the exploit through ``pre_tool_call`` and asserts what reached the
    service, because a mapping that is never asked for is not enforcement.

    Every credential-shaped path is a DECOY STRING. Nothing here is opened.
    """

    def test_the_mcp_move_asks_for_all_four_effects(self):
        # PKA-156 gap 1. The old resolver sent ONE pair - `write secret/env` -
        # so the destination write, the source read and the source delete all
        # ran unauthorized. Canon vector: move-file-secret-source.
        with serving() as (endpoint, handler):
            boundary = VinctorHermesBoundary.from_env(env=env(endpoint))
            result = boundary.pre_tool_call(tool_name=MCP_MOVE_TOOL, args=dict(MOVE))

        self.assertIsNone(result)
        self.assertEqual(
            set(handler.seen),
            {
                ("write", "secret/env"),
                ("read", "secret/env"),
                ("delete", "secret/env"),
                ("write", "fs/tmp/x"),
            },
        )

    def test_denying_only_the_mcp_destination_write_denies_the_whole_move(self):
        # The exploit: a secret/env grant used to carry the destination write.
        with serving({("write", "fs/tmp/x")}) as (endpoint, handler):
            boundary = VinctorHermesBoundary.from_env(env=env(endpoint))
            result = boundary.pre_tool_call(tool_name=MCP_MOVE_TOOL, args=dict(MOVE))

        self.assertEqual(result, BLOCK)
        self.assertIn(("write", "fs/tmp/x"), handler.seen)

    def test_denying_only_the_mcp_source_delete_denies_the_whole_move(self):
        with serving({("delete", "secret/env")}) as (endpoint, _handler):
            boundary = VinctorHermesBoundary.from_env(env=env(endpoint))
            result = boundary.pre_tool_call(tool_name=MCP_MOVE_TOOL, args=dict(MOVE))

        self.assertEqual(result, BLOCK)

    def test_an_unmappable_mcp_path_blocks_instead_of_deferring_open(self):
        # PKA-156 gap 2: this returned `unmapped`, which the default
        # VINCTOR_HERMES_UNMAPPED_POLICY defers OPEN - zero enforce calls, call
        # allowed - while the native spelling blocked on the same argument.
        with serving() as (endpoint, handler):
            boundary = VinctorHermesBoundary.from_env(env=env(endpoint))
            result = boundary.pre_tool_call(
                tool_name=MCP_WRITE_TOOL, args={"path": "../../etc/passwd"}
            )

        self.assertEqual(
            result,
            {"action": "block", "message": "Denied by Vinctor authorization: parse_unsafe."},
        )
        self.assertEqual(handler.seen, [])

    def test_an_unmappable_mcp_move_endpoint_blocks_instead_of_deferring_open(self):
        with serving() as (endpoint, handler):
            boundary = VinctorHermesBoundary.from_env(env=env(endpoint))
            result = boundary.pre_tool_call(
                tool_name=MCP_MOVE_TOOL,
                args={"source": "/home/u/.env", "destination": "../../etc/passwd"},
            )

        self.assertEqual(
            result,
            {"action": "block", "message": "Denied by Vinctor authorization: parse_unsafe."},
        )
        self.assertEqual(handler.seen, [])

    def test_the_native_read_multiple_files_spelling_is_enforced_per_path(self):
        # PKA-156 gap 3: PKA-148 fixed only the `mcp__*` spelling, so the bare
        # name was in no native tool table and deferred OPEN with zero enforce
        # calls.
        with serving() as (endpoint, handler):
            boundary = VinctorHermesBoundary.from_env(env=env(endpoint))
            result = boundary.pre_tool_call(
                tool_name=NATIVE_READ_TOOL,
                args={"paths": ["/home/u/.env", "/home/u/.ssh/id_rsa"]},
            )

        self.assertIsNone(result)
        self.assertEqual(
            set(handler.seen), {("read", "secret/env"), ("read", "secret/ssh")}
        )

    def test_denying_one_member_denies_the_native_read_multiple_files_call(self):
        with serving({("read", "secret/ssh")}) as (endpoint, _handler):
            boundary = VinctorHermesBoundary.from_env(env=env(endpoint))
            result = boundary.pre_tool_call(
                tool_name=NATIVE_READ_TOOL,
                args={"paths": ["/home/u/.env", "/home/u/.ssh/id_rsa"]},
            )

        self.assertEqual(result, BLOCK)


FORK_TOOL = "mcp__github__fork_repository"
FORK = {"owner": "acme", "repo": "api", "organization": "myorg"}


class ForkRepositoryEnforcementTests(unittest.TestCase):
    """PKA-149 at the enforcement point, over a real socket.

    The pre-fix resolver sent `write github/acme/api/fork` ALONE, so a fork grant
    on acme/api created a repository - and a copy of its contents - inside myorg,
    which the grant never covered. Every assertion here checks what reached the
    service.
    """

    def test_fork_asks_for_all_three_effects(self):
        with serving() as (endpoint, handler):
            boundary = VinctorHermesBoundary.from_env(env=env(endpoint))
            result = boundary.pre_tool_call(tool_name=FORK_TOOL, args=dict(FORK))

        self.assertIsNone(result)
        self.assertEqual(
            set(handler.seen),
            {
                ("write", "github/acme/api/fork"),
                ("read", "github/acme/api/contents"),
                ("write", "github/myorg/_/repo"),
            },
        )

    def test_the_exploit_denying_the_destination_write_denies_the_fork(self):
        with serving({("write", "github/myorg/_/repo")}) as (endpoint, handler):
            boundary = VinctorHermesBoundary.from_env(env=env(endpoint))
            result = boundary.pre_tool_call(tool_name=FORK_TOOL, args=dict(FORK))

        self.assertEqual(result, BLOCK)
        self.assertIn(("write", "github/myorg/_/repo"), handler.seen)

    def test_denying_the_source_read_denies_the_fork(self):
        with serving({("read", "github/acme/api/contents")}) as (endpoint, _handler):
            boundary = VinctorHermesBoundary.from_env(env=env(endpoint))
            result = boundary.pre_tool_call(tool_name=FORK_TOOL, args=dict(FORK))

        self.assertEqual(result, BLOCK)

    def test_a_no_org_fork_still_charges_the_unscoped_namespace(self):
        with serving() as (endpoint, handler):
            boundary = VinctorHermesBoundary.from_env(env=env(endpoint))
            result = boundary.pre_tool_call(
                tool_name=FORK_TOOL, args={"owner": "acme", "repo": "api"}
            )

        self.assertIsNone(result)
        self.assertIn(("write", "github/_/_/repo"), set(handler.seen))


if __name__ == "__main__":
    unittest.main()
