from __future__ import annotations

from vinctor_hermes_plugin.plugin import register


class _Context:
    def __init__(self) -> None:
        self.hooks: list[tuple[str, object]] = []

    def register_hook(self, name: str, callback: object) -> None:
        self.hooks.append((name, callback))


def main() -> int:
    context = _Context()
    register(context)
    if len(context.hooks) != 1:
        print("expected one hook registration")
        return 1
    name, callback = context.hooks[0]
    if name != "pre_tool_call" or not callable(callback):
        print("pre_tool_call hook was not registered")
        return 1
    print("registered pre_tool_call")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
