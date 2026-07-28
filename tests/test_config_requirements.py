"""PKA-173: an operator rule may ADD a charge; it may never SUBTRACT an effect.

Operator config is resolved BEFORE the builtin resolvers and returned a mapping
with an empty ``also_requires``, so ONE rule undid PKA-145, PKA-148 and PKA-149
at once: a rule naming ``mcp__github__fork_repository`` collapsed its three
effects to the rule's single pair, and the destination-namespace write and the
source contents read simply vanished.

The sibling hooks reached the rule that holds after two failed attempts, both
pinned here so neither can come back:

  1. collapse the classifier's set entirely on the config path;
  2. union only the classifier's ``also_requires`` and silently drop its
     PRIMARY - which for ``move_file`` is the DESTINATION write, so a
     ``/tmp``-scoped rule plus a ``/tmp``-scoped grant wrote into ``~/.ssh``.

So the classifier's FULL required set is unioned in, its primary included, minus
the rule's own pair. Built-in mappings are a floor, not a default.

Every credential-shaped path here is a DECOY STRING classified in-process.
"""

import unittest

from test_multi_effect_enforcement import BLOCK, env, serving

from vinctor_hermes_plugin.boundary import VinctorHermesBoundary
from vinctor_hermes_plugin.config import Config, Rule
from vinctor_hermes_plugin.mapping import resolve_tool_call

FORK_TOOL = "mcp__github__fork_repository"
FORK_ARGS = {"owner": "acme", "repo": "api", "organization": "myorg"}
FORK_CANON = {
    ("write", "github/acme/api/fork"),
    ("read", "github/acme/api/contents"),
    ("write", "github/myorg/_/repo"),
}
# A rule whose pair is DISTINCT from anything the classifier produces, so its
# presence in the required set is proof the rule actually matched. A rule that
# silently never fires would make every assertion below vacuous.
FORK_RULE = Rule(
    tool=FORK_TOOL,
    match_type="exact",
    pattern=FORK_TOOL,
    action="write",
    resource="vinctor/fork-review",
)
# The same rule spelled with the classifier's own primary pair, for the
# no-double-charge end of the contract.
FORK_RULE_SAME_PAIR = Rule(
    tool=FORK_TOOL,
    match_type="exact",
    pattern=FORK_TOOL,
    action="write",
    resource="github/acme/api/fork",
)

# A plausible operator rule: "a move whose SOURCE is under /tmp is a scratch
# write". It matches on `source`, so it says nothing about where the move lands.
SCRATCH_MOVE_RULE = Rule(
    tool="move_file",
    match_type="glob",
    pattern="/tmp/*",
    action="write",
    resource="fs/tmp/scratch",
    input_field="source",
)
SCRATCH_MOVE_ARGS = {"source": "/tmp/x", "destination": "/home/u/.ssh/authorized_keys"}

MULTI_READ_RULE = Rule(
    tool="mcp__filesystem__read_multiple_files",
    match_type="exact",
    pattern="mcp__filesystem__read_multiple_files",
    action="read",
    resource="fs/bundle",
)
WRITE_RULE = Rule(
    tool="mcp__filesystem__write_file",
    match_type="exact",
    pattern="mcp__filesystem__write_file",
    action="write",
    resource="fs/allowed",
)
PATCH_RULE = Rule(
    tool="patch",
    match_type="glob",
    pattern="*",
    action="write",
    resource="repo/allowed",
    input_field="patch",
)
RENAME_RULE = Rule(
    tool="read_file",
    match_type="glob",
    pattern="*",
    action="read",
    resource="fs/custom/notes",
    input_field="path",
)


def config(*rules):
    return Config(version=1, rules=rules)


def required_set(result):
    return {(result.action, result.resource)} | {
        (r.action, r.resource) for r in result.also_requires
    }


class ConfigKeepsClassifierRequirementsTests(unittest.TestCase):
    def test_a_rule_on_fork_repository_keeps_all_three_effects(self):
        result = resolve_tool_call(FORK_TOOL, dict(FORK_ARGS), config(FORK_RULE))

        # Premise: the rule really matched (its pair is not one the classifier
        # can produce), so the assertion below is about the union, not about a
        # rule that never fired.
        self.assertEqual(result.source, "config")
        self.assertEqual((result.action, result.resource), ("write", "vinctor/fork-review"))
        self.assertEqual(required_set(result), {("write", "vinctor/fork-review")} | FORK_CANON)

    def test_the_rules_own_pair_is_not_charged_twice(self):
        result = resolve_tool_call(FORK_TOOL, dict(FORK_ARGS), config(FORK_RULE_SAME_PAIR))

        pairs = [(result.action, result.resource)] + [
            (r.action, r.resource) for r in result.also_requires
        ]
        self.assertEqual(result.source, "config")
        self.assertEqual(len(pairs), len(set(pairs)))
        self.assertEqual(set(pairs), FORK_CANON)

    def test_a_scratch_rule_cannot_drop_the_classifiers_primary(self):
        """Failed attempt 2: unioning only ``also_requires``.

        ``move_file``'s classifier primary IS the destination write, so a union
        that keeps only ``also_requires`` loses exactly the pair that names
        where the credential lands.
        """
        result = resolve_tool_call(
            "move_file", dict(SCRATCH_MOVE_ARGS), config(SCRATCH_MOVE_RULE)
        )

        self.assertEqual(result.source, "config")
        self.assertEqual((result.action, result.resource), ("write", "fs/tmp/scratch"))
        self.assertIn(("write", "secret/ssh"), required_set(result))
        self.assertEqual(
            required_set(result),
            {
                ("write", "fs/tmp/scratch"),
                ("write", "secret/ssh"),
                ("read", "fs/tmp/x"),
                ("delete", "fs/tmp/x"),
            },
        )

    def test_a_rule_on_a_multi_read_keeps_every_member(self):
        result = resolve_tool_call(
            "mcp__filesystem__read_multiple_files",
            {"paths": ["/home/u/.env", "/home/u/.ssh/id_rsa"]},
            config(MULTI_READ_RULE),
        )

        self.assertEqual(result.source, "config")
        self.assertEqual(
            required_set(result),
            {("read", "fs/bundle"), ("read", "secret/env"), ("read", "secret/ssh")},
        )

    def test_a_classifier_refusal_is_not_config_overridable(self):
        # Premise first: the SAME rule does take effect on an argument the
        # classifier can express, so the refusal below is the rule losing to a
        # refusal - not a rule that never matched this tool.
        matched = resolve_tool_call(
            "mcp__filesystem__write_file", {"path": "/project/a.py"}, config(WRITE_RULE)
        )
        self.assertEqual((matched.source, matched.resource), ("config", "fs/allowed"))

        result = resolve_tool_call(
            "mcp__filesystem__write_file", {"path": "../../etc/passwd"}, config(WRITE_RULE)
        )

        self.assertEqual(result.kind, "error")
        self.assertEqual(result.reason, "parse_unsafe")

    def test_a_refused_patch_target_is_not_config_overridable(self):
        matched = resolve_tool_call(
            "patch",
            {"patch": "*** Begin Patch\n*** Update File: src/app.py\n*** End Patch"},
            config(PATCH_RULE),
        )
        self.assertEqual((matched.source, matched.resource), ("config", "repo/allowed"))

        result = resolve_tool_call(
            "patch",
            {"patch": "*** Begin Patch\n*** Update File: ../../etc/passwd\n*** End Patch"},
            config(PATCH_RULE),
        )

        self.assertEqual(result.kind, "error")

    def test_a_single_effect_rename_stays_a_rename(self):
        """The other end of the rule: a rename must not double-charge.

        A single-effect classifier's primary IS the whole effect, so unioning it
        back in would charge the built-in resource on top of every operator
        remapping and break the documented escape hatch.
        """
        result = resolve_tool_call("read_file", {"path": "src/app.py"}, config(RENAME_RULE))

        self.assertEqual(required_set(result), {("read", "fs/custom/notes")})

    def test_an_unclassified_tool_still_maps_from_config_alone(self):
        rule = Rule(
            tool="get_weather",
            match_type="exact",
            pattern="get_weather",
            action="read",
            resource="weather/city",
        )
        result = resolve_tool_call("get_weather", {"city": "seoul"}, config(rule))

        self.assertEqual(required_set(result), {("read", "weather/city")})
        self.assertEqual(result.source, "config")


class ConfigRequirementEnforcementTests(unittest.TestCase):
    """The same property at the enforcement point, over a real socket.

    Mapping the extra effects is only half of it - the boundary must ASK for
    them. Every assertion checks what reached the service.
    """

    @staticmethod
    def _boundary(endpoint, *rules):
        return VinctorHermesBoundary(
            env=env(endpoint),
            config=config(*rules),
        )

    def test_a_fork_rule_still_asks_for_the_destination_namespace(self):
        with serving() as (endpoint, handler):
            boundary = self._boundary(endpoint, FORK_RULE)
            result = boundary.pre_tool_call(tool_name=FORK_TOOL, args=dict(FORK_ARGS))

        self.assertIsNone(result)
        # The rule's own pair reaching the service is the premise: config fired.
        self.assertEqual(set(handler.seen), {("write", "vinctor/fork-review")} | FORK_CANON)

    def test_denying_the_destination_namespace_denies_the_configured_fork(self):
        with serving({("write", "github/myorg/_/repo")}) as (endpoint, _handler):
            boundary = self._boundary(endpoint, FORK_RULE)
            result = boundary.pre_tool_call(tool_name=FORK_TOOL, args=dict(FORK_ARGS))

        self.assertEqual(result, BLOCK)

    def test_a_tmp_scoped_grant_cannot_write_into_ssh_through_a_tmp_scoped_rule(self):
        # The PDP here grants exactly what the operator rule names: writes under
        # fs/tmp. Nothing else. The move must be denied on the secret/ssh write.
        with serving({("write", "secret/ssh")}) as (endpoint, handler):
            boundary = self._boundary(endpoint, SCRATCH_MOVE_RULE)
            result = boundary.pre_tool_call(
                tool_name="move_file", args=dict(SCRATCH_MOVE_ARGS)
            )

        self.assertEqual(result, BLOCK)
        self.assertIn(("write", "secret/ssh"), handler.seen)
        # Premise: the operator rule fired - its own pair was asked for first.
        self.assertIn(("write", "fs/tmp/scratch"), handler.seen)


if __name__ == "__main__":
    unittest.main()
