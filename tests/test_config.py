import json
import os
import signal
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from vinctor_hermes_plugin.boundary import VinctorHermesBoundary
from vinctor_hermes_plugin.config import (
    MAX_CONFIG_BYTES,
    ConfigError,
    load_config,
    load_runtime_config,
)
from vinctor_hermes_plugin.enforce import ActionDeniedError, EnforceOutcome


def _denying_enforce(grant_ref, action, resource):
    raise ActionDeniedError("action_denied", "evt_denied")


class LoadConfigTests(unittest.TestCase):
    """PKA-119: an absent optional setting and a broken explicitly-requested one
    are different states. No path → documented empty/default. An explicit path
    that is missing, a directory, unreadable, or malformed → ConfigError (which
    the boundary turns into a fail-closed invalid_config block)."""

    def test_no_configured_path_is_the_empty_default(self):
        for path in (None, ""):
            with self.subTest(path=path):
                config = load_config(path)
                self.assertEqual(config.version, 1)
                self.assertEqual(config.rules, ())

    def test_explicit_missing_path_fails_closed(self):
        with TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "does-not-exist.json")
            with self.assertRaises(ConfigError):
                load_config(missing)

    def test_explicit_directory_path_fails_closed(self):
        with TemporaryDirectory() as tmp, self.assertRaises(ConfigError):
            load_config(tmp)

    def test_explicit_malformed_json_fails_closed(self):
        with TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text("{ not json", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(str(bad))

    @unittest.skipIf(os.geteuid() == 0, "root bypasses file permissions")
    def test_explicit_unreadable_path_fails_closed(self):
        with TemporaryDirectory() as tmp:
            locked = Path(tmp) / "locked.json"
            locked.write_text(json.dumps({"version": 1, "rules": []}), encoding="utf-8")
            locked.chmod(0o000)
            try:
                with self.assertRaises(ConfigError):
                    load_config(str(locked))
            finally:
                locked.chmod(0o600)

    def test_recovers_after_the_file_is_created(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            # Missing → fail closed.
            with self.assertRaises(ConfigError):
                load_config(str(path))
            # Operator drops the file in → loads cleanly, no restart semantics needed.
            path.write_text(json.dumps({"version": 1, "rules": []}), encoding="utf-8")
            config = load_config(str(path))
            self.assertEqual(config.version, 1)
            self.assertEqual(config.rules, ())


if __name__ == "__main__":
    unittest.main()


class NonRegularSourceTests(unittest.TestCase):
    """PKA-119 review: an explicitly configured source that is not a regular file
    must fail closed IMMEDIATELY. A FIFO passes exists()/is_dir() and then blocks
    the reader forever — an availability failure, not a bounded fail-closed."""

    def test_fifo_config_path_fails_closed_without_blocking(self):
        with TemporaryDirectory() as tmp:
            fifo = Path(tmp) / "config.fifo"
            os.mkfifo(fifo)

            def guard(signum, frame):
                raise AssertionError("load_config blocked on a FIFO instead of failing closed")

            previous = signal.signal(signal.SIGALRM, guard)
            signal.alarm(3)
            try:
                with self.assertRaises(ConfigError):
                    load_config(str(fifo))
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, previous)

    def test_oversized_config_fails_closed(self):
        with TemporaryDirectory() as tmp:
            big = Path(tmp) / "big.json"
            big.write_text("[" + ("0," * (MAX_CONFIG_BYTES // 2)) + "0]", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(str(big))


class BoundaryConfigRecoveryTests(unittest.TestCase):
    """PKA-119 review: recovery must work on the LONG-LIVED boundary, not just on
    a fresh loader call. An init-container/mount rollout race must not leave a
    running plugin permanently blocked after operators repair the file."""

    @staticmethod
    def _env(path):
        return {
            "VINCTOR_ENDPOINT": "http://vinctor.test",
            "VINCTOR_AGENT_KEY": "aak_test",
            "VINCTOR_GRANT_REF": "grt_test",
            "VINCTOR_HERMES_PLUGIN_CONFIG": str(path),
        }

    def test_same_boundary_instance_recovers_after_the_file_is_created(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            boundary = VinctorHermesBoundary.from_env(
                env=self._env(path),
                enforce_func=lambda grant_ref, action, resource: EnforceOutcome(
                    decision="permit", audit_event_id="evt_1"
                ),
            )

            blocked = boundary.pre_tool_call(tool_name="terminal", args={"command": "npm test"})
            self.assertEqual(
                blocked,
                {"action": "block", "message": "Denied by Vinctor authorization: invalid_config."},
            )

            path.write_text(json.dumps({"version": 1, "rules": []}), encoding="utf-8")

            recovered = boundary.pre_tool_call(tool_name="terminal", args={"command": "npm test"})
            self.assertIsNone(recovered, "same boundary instance stayed latched on invalid_config")

    def test_boundary_reloads_only_when_the_configured_source_changes(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            calls = 0

            def counted_load(*args, **kwargs):
                nonlocal calls
                calls += 1
                return load_runtime_config(*args, **kwargs)

            with patch(
                "vinctor_hermes_plugin.boundary.load_runtime_config",
                side_effect=counted_load,
            ):
                boundary = VinctorHermesBoundary.from_env(
                    env=self._env(path),
                    enforce_func=lambda grant_ref, action, resource: EnforceOutcome(
                        decision="permit", audit_event_id="evt_1"
                    ),
                )
                boundary.pre_tool_call(tool_name="terminal", args={"command": "npm test"})
                path.write_text(json.dumps({"version": 1, "rules": []}), encoding="utf-8")
                self.assertIsNone(
                    boundary.pre_tool_call(tool_name="terminal", args={"command": "npm test"})
                )
                self.assertIsNone(
                    boundary.pre_tool_call(tool_name="terminal", args={"command": "npm test"})
                )

            self.assertEqual(calls, 3)

    def test_boundary_blocks_again_after_the_configured_file_is_deleted(self):
        """PKA-119's property is that an explicitly configured path which is not
        there fails closed. Caching the first valid snapshot for the process
        lifetime traded that away: the file could be deleted — or replaced with
        a revoked ruleset — and the boundary kept permitting from the stale
        snapshot until someone restarted it."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"version": 1, "rules": []}), encoding="utf-8")
            boundary = VinctorHermesBoundary.from_env(
                env=self._env(path),
                enforce_func=lambda grant_ref, action, resource: EnforceOutcome(
                    decision="permit", audit_event_id="evt_1"
                ),
            )
            self.assertIsNone(
                boundary.pre_tool_call(tool_name="terminal", args={"command": "npm test"})
            )

            path.unlink()

            self.assertEqual(
                boundary.pre_tool_call(tool_name="terminal", args={"command": "npm test"}),
                {
                    "action": "block",
                    "message": "Denied by Vinctor authorization: invalid_config.",
                },
            )

    def test_boundary_applies_a_tightened_ruleset_without_a_restart(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"version": 1, "rules": []}), encoding="utf-8")
            boundary = VinctorHermesBoundary.from_env(
                env=self._env(path),
                enforce_func=_denying_enforce,
            )
            # No rule covers this tool yet: unmapped, and the default unmapped
            # policy lets it through.
            self.assertIsNone(boundary.pre_tool_call(tool_name="get_weather", args={"city": "s"}))

            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "rules": [
                            {
                                "tool": "get_weather",
                                "matchType": "exact",
                                "pattern": "get_weather",
                                "action": "read",
                                "resource": "weather/city",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                boundary.pre_tool_call(tool_name="get_weather", args={"city": "s"}),
                {
                    "action": "block",
                    "message": "Denied by Vinctor authorization: action_denied.",
                },
            )

    def test_boundary_keeps_blocking_while_the_config_is_still_broken(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            boundary = VinctorHermesBoundary.from_env(env=self._env(path))
            for _ in range(2):
                self.assertEqual(
                    boundary.pre_tool_call(tool_name="terminal", args={"command": "npm test"}),
                    {
                        "action": "block",
                        "message": "Denied by Vinctor authorization: invalid_config.",
                    },
                )
