import contextlib
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_HARNESS_PATH = REPO_ROOT / "scripts" / "coverage_harness.py"
_spec = importlib.util.spec_from_file_location("coverage_harness", _HARNESS_PATH)
assert _spec and _spec.loader
harness = importlib.util.module_from_spec(_spec)
# Register before exec so dataclass type resolution can find the module.
sys.modules["coverage_harness"] = harness
_spec.loader.exec_module(harness)


class CoverageHarnessTests(unittest.TestCase):
    def test_synthetic_mode_reports_mapping_without_runtime_traversal_claim(self):
        results = harness.run_probes(
            enforce_mode="permit",
            unmapped_policy=None,
            runtime_traversal="unmeasured (synthetic)",
        )

        self.assertEqual(len(results), len(harness.PROBES))
        for result in results:
            # The harness must never claim runtime traversal in synthetic mode.
            self.assertEqual(result.runtime_traversal, "unmeasured (synthetic)")
            self.assertIn(result.mapping_status, {"mapped", "unmapped", "error"})

        by_family = {r.family: r for r in results}
        ci = by_family["terminal/CI test"]
        self.assertEqual(ci.mapping_status, "mapped")
        self.assertEqual(ci.action, "execute")
        self.assertEqual(ci.resource, "shell/npm")
        self.assertFalse(ci.blocked)

    def test_every_core_probe_maps_and_dynamic_mcp_stays_unmapped(self):
        results = harness.run_probes(
            enforce_mode="permit",
            unmapped_policy=None,
            runtime_traversal="unmeasured (synthetic)",
        )
        by_family = {r.family: r for r in results}

        # The single intentionally-unmapped probe is the unknown dynamic MCP tool.
        unmapped = [r.family for r in results if r.mapping_status == "unmapped"]
        self.assertEqual(unmapped, ["MCP unmapped (dynamic)"])
        self.assertEqual(by_family["MCP unmapped (dynamic)"].blocked, False)

    def test_deny_mode_blocks_mapped_calls(self):
        results = harness.run_probes(
            enforce_mode="deny",
            unmapped_policy=None,
            runtime_traversal="unmeasured (synthetic)",
        )
        deploy = next(r for r in results if r.family == "terminal/deploy")
        self.assertTrue(deploy.blocked)
        self.assertEqual(deploy.block_reason, "action_denied")

    def test_strict_unmapped_policy_blocks_unmapped_probe(self):
        results = harness.run_probes(
            enforce_mode="permit",
            unmapped_policy="block",
            runtime_traversal="unmeasured (synthetic)",
        )
        dynamic = next(r for r in results if r.family == "MCP unmapped (dynamic)")
        self.assertTrue(dynamic.blocked)
        self.assertEqual(dynamic.block_reason, "unmapped_tool")

    def test_explicit_defer_policy_leaves_unmapped_probe_to_hermes(self):
        results = harness.run_probes(
            enforce_mode="permit",
            unmapped_policy="defer",
            runtime_traversal="unmeasured (synthetic)",
        )
        dynamic = next(r for r in results if r.family == "MCP unmapped (dynamic)")
        self.assertFalse(dynamic.blocked)

    def test_json_output_is_well_formed_and_carries_claim_discipline(self):
        results = harness.run_probes(
            enforce_mode="permit",
            unmapped_policy=None,
            runtime_traversal="unmeasured (synthetic)",
        )
        payload = json.loads(
            harness.render_json(results, {"runtime_traversal": "unmeasured (synthetic)"})
        )
        self.assertEqual(len(payload["results"]), len(harness.PROBES))
        self.assertEqual(payload["meta"]["runtime_traversal"], "unmeasured (synthetic)")

    def test_main_runs_without_error(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(harness.main(["--json"]), 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["meta"]["unmapped_policy"], "defer")

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(harness.main(["--format", "markdown"]), 0)


if __name__ == "__main__":
    unittest.main()
