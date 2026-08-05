import hashlib
import json
import unittest
from pathlib import Path

from vinctor_hermes_plugin.config import empty_config
from vinctor_hermes_plugin.mapping import resolve_tool_call

FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE_PATH = FIXTURE_DIR / "multi-effect.json"
PROVENANCE_PATH = FIXTURE_DIR / "multi-effect.provenance.json"
CURRENT_MULTI_EFFECT_SHA256 = (
    "7d29a8b08177b2df6acda962c2da46a33298972477b9af1f2b691036a7702a10"
)

_FIXTURE_BYTES = FIXTURE_PATH.read_bytes()
FIXTURE = json.loads(_FIXTURE_BYTES)
PROVENANCE = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))

HERMES_SURFACES = {"hermes/filesystem", "hermes/patch"}
HERMES_VECTORS = [v for v in FIXTURE["vectors"] if v["surface"] in HERMES_SURFACES]

# PKA-148/PKA-156: the canonical mcp/filesystem vectors are consumed through the
# `mcp__filesystem__*` spelling, with paths absolutized so hermes' fs/-space
# resources match the fixture's vocabulary (relative paths would classify
# repo/).
MCP_FS_VECTORS = [v for v in FIXTURE["vectors"] if v["surface"] == "mcp/filesystem"]
MCP_READ_VECTORS = [v for v in MCP_FS_VECTORS if v["operation"] == "read_multiple_files"]
MCP_MOVE_VECTORS = [v for v in MCP_FS_VECTORS if v["operation"] == "move_file"]
MCP_SINGLE_PATH_VECTORS = [
    v for v in MCP_FS_VECTORS if v["operation"] not in {"read_multiple_files", "move_file"}
]

# PKA-149: hermes exposes fork_repository through the MCP github surface.
# Surfaces this adapter does not expose at all. `codex/apply_patch` is the
# Codex-native envelope (the fixture's own note scopes it to the codex hook);
# its vectors bind that adapter's protected-path resource policy
# (repo/manifest/npm, infra/dockerfile, ci/workflow) which Hermes deliberately
# does not implement - Hermes classifies every path into repo//fs//secret/. The
# SAME envelope shape IS consumed here through the canon's own `hermes/patch`
# vectors.
UNEXPOSED_SURFACES = {"codex/apply_patch"}

# The canonical github/fork vectors are consumed through resolve_mcp_tool with
# the params passed verbatim (owner/repo/organization are identifiers, not
# paths).
MCP_FORK_VECTORS = [v for v in FIXTURE["vectors"] if v["surface"] == "github/fork"]

# Every vector id this module drives through a Hermes surface. PKA-156: 13 of
# the 26 canonical vectors were consumed by no Hermes test at all, which is how
# the MCP move resolver kept charging one pair after the native one was fixed.
CONSUMED_IDS = {
    v["id"]
    for v in HERMES_VECTORS + MCP_FS_VECTORS + MCP_FORK_VECTORS
}


def required_set(result):
    """The complete (action, resource) set this mapping asks the PDP for."""
    pairs = {(result.action, result.resource)}
    pairs |= {(r.action, r.resource) for r in result.also_requires}
    return pairs


class MultiEffectProvenanceTests(unittest.TestCase):
    """PKA-145: the vendored catalogue is pinned to the canonical source, so
    editing it here without re-vendoring fails instead of drifting."""

    def test_vendored_fixture_matches_its_provenance_hash(self):
        actual = hashlib.sha256(_FIXTURE_BYTES).hexdigest()
        self.assertEqual(PROVENANCE["sha256"], CURRENT_MULTI_EFFECT_SHA256)
        self.assertEqual(
            actual,
            CURRENT_MULTI_EFFECT_SHA256,
            f"vendored fixture does not match {PROVENANCE['source']}; re-vendor from "
            "vinctor-conformance and update sha256 in multi-effect.provenance.json",
        )

    def test_records_where_the_canonical_fixture_came_from(self):
        self.assertRegex(
            PROVENANCE["source"], r"^github\.com/pkachuc/vinctor-conformance@[0-9a-f]{7,40} "
        )

    def test_the_hermes_surfaces_are_actually_covered(self):
        self.assertGreaterEqual(len(HERMES_VECTORS), 5)
        self.assertEqual({v["surface"] for v in HERMES_VECTORS}, HERMES_SURFACES)

    def test_every_vector_for_a_surface_this_adapter_exposes_is_consumed(self):
        """PKA-156: unconsumed canon vectors are the measurable form of the gap.

        A vector nobody runs is a contract nobody checks - that is how the MCP
        move resolver stayed at one pair through three multi-effect fixes. Every
        vector must therefore be either driven through a Hermes surface by this
        module, or belong to a surface this adapter does not expose at all, and
        that second list is asserted exactly so it cannot quietly grow.
        """
        surfaces = {v["surface"] for v in FIXTURE["vectors"]}
        self.assertEqual(surfaces & UNEXPOSED_SURFACES, UNEXPOSED_SURFACES)

        unconsumed = {
            v["id"]
            for v in FIXTURE["vectors"]
            if v["id"] not in CONSUMED_IDS and v["surface"] not in UNEXPOSED_SURFACES
        }
        self.assertEqual(unconsumed, set())
        self.assertEqual(
            {v["surface"] for v in FIXTURE["vectors"] if v["id"] not in CONSUMED_IDS},
            UNEXPOSED_SURFACES,
        )


class MultiEffectMappingTests(unittest.TestCase):
    """PKA-145: a compound operation must ask the PDP for EVERY effect it causes.

    Before this change Hermes asked for one pair: move_file authorized only the
    destination write (so a `write:fs/*` grant moved a credential out of the
    tree with no read and no delete on the source), and a patch envelope
    authorized only its first matching target.
    """

    def test_every_canonical_hermes_vector_maps_to_its_full_requirement_set(self):
        for vector in HERMES_VECTORS:
            with self.subTest(vector=vector["id"]):
                result = resolve_tool_call(
                    vector["operation"], dict(vector["params"]), empty_config()
                )
                self.assertEqual(result.kind, "mapped", vector["why"])
                expected = {(r["action"], r["resource"]) for r in vector["requires"]}
                self.assertEqual(required_set(result), expected, vector["why"])

    def test_the_primary_pair_is_a_member_of_the_required_set(self):
        for vector in HERMES_VECTORS:
            with self.subTest(vector=vector["id"]):
                result = resolve_tool_call(
                    vector["operation"], dict(vector["params"]), empty_config()
                )
                self.assertEqual(
                    (result.action, result.resource),
                    (vector["primary"]["action"], vector["primary"]["resource"]),
                )
                self.assertIn((result.action, result.resource), required_set(result))

    def test_a_single_target_patch_keeps_exactly_one_requirement(self):
        patch = "*** Begin Patch\n*** Update File: src/app.py\n*** End Patch"
        result = resolve_tool_call("patch", {"patch": patch}, empty_config())
        self.assertEqual(required_set(result), {("write", "repo/src/app.py")})

    def test_an_unparseable_member_fails_closed_rather_than_dropping_the_effect(self):
        # A target the resource mapper cannot express must not silently vanish
        # from the required set — that would authorize the rest of the envelope
        # while the unmapped target still executes.
        patch = "*** Begin Patch\n*** Update File: ../../etc/passwd\n*** End Patch"
        result = resolve_tool_call("patch", {"patch": patch}, empty_config())
        self.assertEqual(result.kind, "error")

    def test_move_file_with_an_unmappable_source_fails_closed(self):
        result = resolve_tool_call(
            "move_file", {"source": "../../etc/shadow", "destination": "/tmp/x"}, empty_config()
        )
        self.assertEqual(result.kind, "error")


class McpReadMultipleFilesVectorTests(unittest.TestCase):
    """PKA-148: read_multiple_files must ask the PDP for EVERY path.

    Before this change the MCP resolver returned the FIRST credential-shaped
    path as the whole required set, so a grant covering any one member of the
    list read every other member unenforced - and an all-ordinary list fell to
    `unmapped`, which the default unmapped policy defers OPEN.
    """

    @staticmethod
    def _resolve(vector):
        args = {"paths": [f"/{p}" for p in vector["params"]["paths"]]}
        return resolve_tool_call("mcp__filesystem__read_multiple_files", args, empty_config())

    def test_the_read_vectors_are_present(self):
        self.assertGreaterEqual(
            len([v for v in MCP_READ_VECTORS if len(v["requires"]) > 1]), 3
        )
        self.assertGreaterEqual(len([v for v in MCP_READ_VECTORS if not v["requires"]]), 1)

    def test_every_read_vector_maps_to_its_full_requirement_set(self):
        for vector in [v for v in MCP_READ_VECTORS if v["requires"]]:
            with self.subTest(vector=vector["id"]):
                result = self._resolve(vector)
                self.assertEqual(result.kind, "mapped", vector["why"])
                expected = {(r["action"], r["resource"]) for r in vector["requires"]}
                self.assertEqual(required_set(result), expected, vector["why"])
                self.assertEqual(
                    (result.action, result.resource),
                    (vector["primary"]["action"], vector["primary"]["resource"]),
                )

    def test_an_inexpressible_member_blocks_rather_than_deferring(self):
        # `unmapped` would DEFER the whole read open under the default policy;
        # the refusal must be an error the boundary turns into a block, the
        # same contract as the native move/patch resolvers.
        for vector in [v for v in MCP_READ_VECTORS if not v["requires"]]:
            with self.subTest(vector=vector["id"]):
                result = self._resolve(vector)
                self.assertEqual(result.kind, "error", vector["why"])
                self.assertEqual(result.reason, "parse_unsafe")


def _mcp_fs_args(vector):
    """The vector's params as this adapter's MCP filesystem input.

    Canonical mcp/filesystem paths are resource-path form (no leading slash);
    Hermes' D-4 rule sends RELATIVE paths to repo/, so they are absolutized to
    meet the fixture's fs/-space vocabulary - the same translation PKA-148
    already used for the read vectors.
    """
    return {
        key: [f"/{p}" for p in value] if isinstance(value, list) else f"/{value}"
        for key, value in vector["params"].items()
    }


class McpFilesystemVectorTests(unittest.TestCase):
    """PKA-156 gap 1: the MCP move resolver charged ONE pair.

    ``mcp__filesystem__move_file`` on a credential-shaped source asked only for
    ``write secret/env``, so the destination write AND the source read and
    delete all ran unauthorized - while this repo's own NATIVE surface already
    asked for three pairs on identical arguments. These are the canonical
    mcp/filesystem vectors, previously consumed by no Hermes test.
    """

    @staticmethod
    def _resolve(vector):
        return resolve_tool_call(
            f"mcp__filesystem__{vector['operation']}", _mcp_fs_args(vector), empty_config()
        )

    def test_the_move_vectors_are_present(self):
        self.assertGreaterEqual(len(MCP_MOVE_VECTORS), 4)
        self.assertGreaterEqual(
            len([v for v in MCP_MOVE_VECTORS if len(v["requires"]) == 4]), 2
        )

    def test_every_move_vector_maps_to_its_full_requirement_set(self):
        for vector in MCP_MOVE_VECTORS:
            with self.subTest(vector=vector["id"]):
                result = self._resolve(vector)
                self.assertEqual(result.kind, "mapped", vector["why"])
                expected = {(r["action"], r["resource"]) for r in vector["requires"]}
                self.assertEqual(required_set(result), expected, vector["why"])
                self.assertEqual(
                    (result.action, result.resource),
                    (vector["primary"]["action"], vector["primary"]["resource"]),
                )

    def test_every_single_path_vector_maps_to_its_full_requirement_set(self):
        self.assertGreaterEqual(len(MCP_SINGLE_PATH_VECTORS), 3)
        for vector in MCP_SINGLE_PATH_VECTORS:
            with self.subTest(vector=vector["id"]):
                result = self._resolve(vector)
                self.assertEqual(result.kind, "mapped", vector["why"])
                expected = {(r["action"], r["resource"]) for r in vector["requires"]}
                self.assertEqual(required_set(result), expected, vector["why"])


class BothSurfacesRunTheSameVectorsTests(unittest.TestCase):
    """PKA-156: every canon vector, through BOTH spellings of its operation.

    The root cause was two implementations of one contract, so a vector run
    through one spelling proves nothing about the other. The single canon-pinned
    difference is the move primary: the catalogue keeps EACH surface's
    historical primary pair (move-file-secret-source vs
    hermes-move-file-secret-source), and the primary is a member of the required
    set, so a credential-shaped SOURCE adds `write secret/<kind>` on the MCP
    surface only. Everything else must be identical.
    """

    @staticmethod
    def _native(vector):
        return resolve_tool_call(vector["operation"], _mcp_fs_args(vector), empty_config())

    @staticmethod
    def _mcp(vector):
        return resolve_tool_call(
            f"mcp__filesystem__{vector['operation']}", _mcp_fs_args(vector), empty_config()
        )

    def test_the_native_spelling_agrees_with_every_non_move_vector(self):
        vectors = MCP_SINGLE_PATH_VECTORS + [v for v in MCP_READ_VECTORS if v["requires"]]
        self.assertGreaterEqual(len(vectors), 8)
        for vector in vectors:
            with self.subTest(vector=vector["id"]):
                result = self._native(vector)
                self.assertEqual(result.kind, "mapped", vector["why"])
                expected = {(r["action"], r["resource"]) for r in vector["requires"]}
                self.assertEqual(required_set(result), expected, vector["why"])

    def test_a_refusal_vector_refuses_on_both_spellings(self):
        vectors = [v for v in MCP_READ_VECTORS if not v["requires"]]
        self.assertGreaterEqual(len(vectors), 1)
        for vector in vectors:
            with self.subTest(vector=vector["id"]):
                for result in (self._native(vector), self._mcp(vector)):
                    self.assertEqual(result.kind, "error", vector["why"])
                    self.assertEqual(result.reason, "parse_unsafe")

    def test_the_move_vectors_differ_only_by_the_canon_pinned_primary(self):
        escalated = 0
        for vector in MCP_MOVE_VECTORS:
            with self.subTest(vector=vector["id"]):
                native = self._native(vector)
                mcp = self._mcp(vector)
                self.assertEqual(native.kind, "mapped")
                source = f"/{vector['params']['source']}"
                secret_source = resolve_tool_call(
                    "read_file", {"path": source}, empty_config()
                ).resource
                if secret_source.startswith("secret/"):
                    escalated += 1
                    self.assertEqual((mcp.action, mcp.resource), ("write", secret_source))
                    self.assertEqual(
                        required_set(mcp), required_set(native) | {("write", secret_source)}
                    )
                else:
                    self.assertEqual((mcp.action, mcp.resource), (native.action, native.resource))
                    self.assertEqual(required_set(mcp), required_set(native))
        self.assertGreaterEqual(escalated, 2, "the escalating branch never fired")


class McpForkRepositoryVectorTests(unittest.TestCase):
    """PKA-149: fork_repository must ask the PDP for the source fork, the source
    contents read, and the destination namespace write.

    Before this change the MCP resolver charged one pair - the source fork - so
    a fork grant on acme/api created a repository, and a copy of its contents,
    inside any org named in `organization` that the operator never authorized.
    """

    @staticmethod
    def _resolve(vector):
        return resolve_tool_call(
            "mcp__github__fork_repository", dict(vector["params"]), empty_config()
        )

    def test_the_fork_vectors_are_present(self):
        self.assertGreaterEqual(len(MCP_FORK_VECTORS), 1)
        self.assertTrue(all(len(v["requires"]) == 3 for v in MCP_FORK_VECTORS))

    def test_every_fork_vector_maps_to_its_full_requirement_set(self):
        for vector in MCP_FORK_VECTORS:
            with self.subTest(vector=vector["id"]):
                result = self._resolve(vector)
                self.assertEqual(result.kind, "mapped", vector["why"])
                expected = {(r["action"], r["resource"]) for r in vector["requires"]}
                self.assertEqual(required_set(result), expected, vector["why"])
                self.assertEqual(
                    (result.action, result.resource),
                    (vector["primary"]["action"], vector["primary"]["resource"]),
                )

    def test_an_ambiguous_source_does_not_fork(self):
        result = resolve_tool_call(
            "mcp__github__fork_repository",
            {"owner": "acme", "organization": "myorg"},
            empty_config(),
        )
        self.assertEqual(result.kind, "unmapped")


if __name__ == "__main__":
    unittest.main()
