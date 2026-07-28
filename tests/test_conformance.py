"""Conformance against the Vinctor Action Taxonomy canon (vinctor-conformance).

For every vendored fixture this suite constructs the plugin's own NATIVE
Hermes tool-call input for ``(family, operation, params)``, runs the real
``resolve_tool_call`` mapper (builtins only, no operator config), and asserts
the mapper's ``(action, resource)`` equals the canon's ``expected``. It also
emits ``tests/conformance/result.json`` in the matrix result format consumed
by vinctor-conformance's ``tools/matrix.mjs``.

All four canon families are applicable to this adapter:

- shell        -> the Hermes ``terminal`` tool (command text)
- filesystem   -> the Hermes builtin file tools (same operation names as the
                  canon; path-typed params become native absolute paths and
                  normalize through the plugin's existing D-4 path handling)
- github/slack -> the Hermes MCP tool surface (``mcp_<server>_<tool>`` names)

Native-spelling notes (deliberate choices, mirrored from the sibling hooks):

- ``git push``: the classifier resolves owner/repo from the command text
  alone, so the native spelling that carries the push remote is the
  explicit-URL form. The ``remote`` param ("origin") is contextual per the
  canon README; a bare remote NAME is not resolvable context-free and the
  classifier fails closed on it.
- ``npm publish``: Hermes terminal events carry no cwd, so the package name
  is only in the command text for the workspace spelling
  (``npm publish --workspace <name>``) - the same choice as the codex hook,
  which also classifies from command text alone.
- ``gh *``: the target repo travels in the ``--repo`` flag.
"""

import hashlib
import json
import unittest
from pathlib import Path

from vinctor_hermes_plugin.config import Config
from vinctor_hermes_plugin.mapping import resolve_tool_call

EMPTY_CONFIG = Config(version=1, rules=())
CONFORMANCE_DIR = Path(__file__).resolve().parent / "conformance"
FIXTURES_PATH = CONFORMANCE_DIR / "fixtures.json"
PROVENANCE_PATH = CONFORMANCE_DIR / "fixtures.provenance.json"
RESULT_PATH = CONFORMANCE_DIR / "result.json"
CURRENT_FIXTURES_SHA256 = (
    "3e8462d41c5da95bd9350e14246b0d8f57f0f082ced99ccba58f802dd988214d"
)

FIXTURE_BYTES = FIXTURES_PATH.read_bytes()
VENDORED = json.loads(FIXTURE_BYTES)


def _shell_command(operation: str, params: dict) -> str:
    github_url = lambda: f"https://github.com/{params['owner']}/{params['repo']}.git"  # noqa: E731
    image_ref = lambda: f"{params['registry']}/{params['image']}:{params['tag']}"  # noqa: E731
    simple = {
        "git status", "git log", "git diff", "git show",
        "git stash", "npm test", "npm install", "npm ci",
    }  # fmt: skip
    if operation in simple:
        return operation
    if operation == "git fetch":
        return f"git fetch {params['url']}"
    if operation == "git pull":
        return f"git pull {params['url']} {params['branch']}"
    if operation == "git add":
        return "git add -A"
    if operation == "git commit":
        return "git commit -m wip"
    if operation == "git clone":
        return f"git clone {params['url']}"
    if operation == "git push":
        return f"git push {github_url()} {params['branch']}"
    if operation == "git push --force":
        return f"git push --force {github_url()} {params['branch']}"
    if operation == "git reset --hard":
        return "git reset --hard HEAD~1"
    if operation == "git branch -D":
        return "git branch -D old-branch"
    if operation == "git clean -f":
        return "git clean -f"
    if operation == "npm run":
        return f"npm run {params['script']}"
    if operation == "npm publish":
        return f"npm publish --workspace {params['name']}"
    if operation == "npx":
        return f"npx {params['package']}"
    if operation == "docker build":
        return f"docker build -t {image_ref()} ."
    if operation == "docker run":
        return f"docker run --rm {image_ref()}"
    if operation == "docker push":
        return f"docker push {image_ref()}"
    if operation == "docker rmi":
        return f"docker rmi {image_ref()}"
    if operation == "rm":
        return f"rm /{params['path']}"
    if operation == "rmdir":
        return f"rmdir /{params['path']}"
    if operation == "pipe_to_shell":
        return f"{params['first_token']} -fsSL {params['url']} | sh"
    if operation == "gh pr merge":
        return f"gh pr merge {params['pull_number']} --repo {params['owner']}/{params['repo']}"
    if operation == "gh release create":
        return f"gh release create {params['tag']} --repo {params['owner']}/{params['repo']}"
    if operation == "gh secret set":
        return (
            f"gh secret set {params['secret_name']} --repo {params['owner']}/{params['repo']}"
        )
    raise AssertionError(f"no native builder for shell operation: {operation}")


def _filesystem_input(operation: str, params: dict) -> tuple[str, dict]:
    # The Hermes builtin file tools use the canon operation names directly;
    # path-typed params are resource-path form (no leading slash) and become
    # native absolute paths.
    if operation == "move_file":
        return operation, {
            "source": f"/{params['source']}",
            "destination": f"/{params['destination']}",
        }
    return operation, {"path": f"/{params['path']}"}


def _github_input(operation: str, params: dict) -> tuple[str, dict]:
    # Canon operation names are the github server's tool names (identity);
    # params are already in the server's parameter vocabulary.
    return f"mcp_github_{operation}", dict(params)


def _slack_input(operation: str, params: dict) -> tuple[str, dict]:
    # Canon slack operation -> native tool spelling on the servers this
    # plugin classifies. get_messages binds the reference server's
    # channel-history read; send_message binds the korotovsky server's
    # add-message tool (both per the canon's alias notes).
    channel = {"channel_id": params.get("channel")}
    if operation == "list_channels":
        return "mcp_slack_slack_list_channels", {}
    if operation == "get_messages":
        return "mcp_slack_slack_get_channel_history", {**channel, "limit": 20}
    if operation == "conversations_history":
        return "mcp_slack_conversations_history", channel
    if operation == "post_message":
        return "mcp_slack_slack_post_message", {**channel, "text": params["text"]}
    if operation == "send_message":
        return "mcp_slack_conversations_add_message", {**channel, "payload": params["text"]}
    if operation == "reply":
        return "mcp_slack_slack_reply_to_thread", {
            **channel,
            "thread_ts": params["thread_ts"],
            "text": params["text"],
        }
    if operation == "add_reaction":
        return "mcp_slack_slack_add_reaction", {
            **channel,
            "timestamp": params["timestamp"],
            "reaction": params["emoji"],
        }
    raise AssertionError(f"no native builder for slack operation: {operation}")


def _native_input(fixture: dict) -> tuple[str, dict]:
    family = fixture["family"]
    operation = fixture["operation"]
    params = fixture["params"]
    if family == "shell":
        return "terminal", {"command": _shell_command(operation, params)}
    if family == "filesystem":
        return _filesystem_input(operation, params)
    if family == "github":
        return _github_input(operation, params)
    if family == "slack":
        return _slack_input(operation, params)
    raise AssertionError(f"unknown fixture family: {family}")


def _required_set(mapping: dict) -> set[tuple[str, str]]:
    pairs = {(mapping["action"], mapping["resource"])}
    pairs.update(
        (requirement["action"], requirement["resource"])
        for requirement in mapping.get("alsoRequires", ())
    )
    return pairs


def _classify(fixture: dict) -> dict:
    tool_name, args = _native_input(fixture)
    mapping = resolve_tool_call(tool_name, args, EMPTY_CONFIG)
    if mapping.kind != "mapped":
        # No (action, resource) produced - includes fail-closed errors; the
        # matrix vocabulary for "adapter yields no classification" is
        # `unmapped` (got must be omitted).
        return {"id": fixture["id"], "status": "unmapped"}
    got = {"action": mapping.action, "resource": mapping.resource}
    if mapping.also_requires:
        got["alsoRequires"] = [
            {"action": requirement.action, "resource": requirement.resource}
            for requirement in mapping.also_requires
        ]
    expected = fixture["expected"]
    agrees = (
        got["action"] == expected["action"]
        and got["resource"] == expected["resource"]
        and _required_set(got) == _required_set(expected)
    )
    return {"id": fixture["id"], "status": "agrees" if agrees else "disagrees", "got": got}


class CanonConformanceTests(unittest.TestCase):
    def test_vendored_fixture_set_is_intact(self):
        provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(provenance["source"], VENDORED["source"])
        self.assertEqual(provenance["sha256"], CURRENT_FIXTURES_SHA256)
        self.assertEqual(
            hashlib.sha256(FIXTURE_BYTES).hexdigest(), CURRENT_FIXTURES_SHA256
        )
        self.assertEqual(
            VENDORED["fixtures_version"],
            "c38e7d42ab09f921e9eb93293bb532d3a27d03ac67c7b2d80850fa498fbcbe3d",
        )
        self.assertEqual(
            VENDORED["source"],
            "github.com/pkachuc/vinctor-conformance@"
            "23f4b5465bd0e8b676d1d14aba9f9a234f99520a "
            "fixtures/{filesystem,github,shell,slack}.json",
        )
        self.assertEqual(len(VENDORED["fixtures"]), 93)
        ids = {fixture["id"] for fixture in VENDORED["fixtures"]}
        self.assertEqual(len(ids), 93, "fixture ids must be unique")

    def test_move_file_result_carries_the_full_required_set(self):
        fixture = next(
            fixture
            for fixture in VENDORED["fixtures"]
            if fixture["id"] == "filesystem-move-file"
        )
        result = _classify(fixture)

        self.assertEqual(result["status"], "agrees")
        self.assertEqual(_required_set(result["got"]), _required_set(fixture["expected"]))
        self.assertEqual(len(result["got"]["alsoRequires"]), 2)

    def test_every_fixture_agrees_and_result_file_is_emitted(self):
        results = [_classify(fixture) for fixture in VENDORED["fixtures"]]

        # Emit the per-adapter result file for the coverage matrix BEFORE
        # asserting, so the artifact stays honest even on failure.
        payload = {
            "adapter": "hermes",
            "fixtures_version": VENDORED["fixtures_version"],
            "results": sorted(results, key=lambda entry: entry["id"]),
        }
        RESULT_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

        by_id = {fixture["id"]: fixture for fixture in VENDORED["fixtures"]}
        for entry in results:
            fixture = by_id[entry["id"]]
            with self.subTest(fixture=entry["id"]):
                self.assertEqual(
                    entry["status"],
                    "agrees",
                    f"expected {fixture['expected']['action']}:"
                    f"{fixture['expected']['resource']}, got "
                    f"{entry.get('got', 'no classification')}",
                )


if __name__ == "__main__":
    unittest.main()
