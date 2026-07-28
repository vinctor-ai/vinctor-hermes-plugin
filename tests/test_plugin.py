import unittest
from pathlib import Path

from vinctor_hermes_plugin import __version__
from vinctor_hermes_plugin.plugin import register


class FakeContext:
    def __init__(self):
        self.hooks = []

    def register_hook(self, name, callback):
        self.hooks.append((name, callback))


class PluginTests(unittest.TestCase):
    def test_register_installs_pre_tool_call_hook(self):
        ctx = FakeContext()

        register(ctx)

        self.assertEqual(len(ctx.hooks), 1)
        self.assertEqual(ctx.hooks[0][0], "pre_tool_call")
        self.assertTrue(callable(ctx.hooks[0][1]))

    def test_plugin_manifest_version_matches_package(self):
        root = Path(__file__).resolve().parents[1]
        manifest = root / "plugin.yaml"
        version_line = next(
            line
            for line in manifest.read_text(encoding="utf-8").splitlines()
            if line.startswith("version:")
        )

        self.assertEqual(version_line, f"version: {__version__}")
