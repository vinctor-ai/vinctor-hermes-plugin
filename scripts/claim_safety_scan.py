from __future__ import annotations

import sys
from pathlib import Path

PROHIBITED_PHRASES = (
    "Hermes-native",
    "official Hermes integration",
    "official Nous integration",
    "official Hermes plugin",
    "official Nous plugin",
    "official support",
    "provides sandboxing",
    "hosted service",
    "production-ready",
    "raw tool interception",
)

DEFAULT_TARGETS = (
    "README.md",
    "ROADMAP.md",
    "CONTRIBUTING.md",
    "docs",
    "src",
    "plugin.yaml",
    "pyproject.toml",
)

SKIPPED_DIRS = {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__"}
TEXT_SUFFIXES = {".md", ".py", ".toml", ".yaml", ".yml", ".json", ".txt"}
NEGATING_PREFIXES = (
    "not ",
    "not a ",
    "not an ",
    "does not ",
    "do not ",
    "must not claim ",
    "avoid: ",
)
NEGATING_LINE_MARKERS = ("does not provide", "not provide")


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    root = Path.cwd()
    targets = [Path(item) for item in (args or DEFAULT_TARGETS)]
    findings = []
    for path in _iter_files(root, targets):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(lines, start=1):
            for phrase in PROHIBITED_PHRASES:
                if _is_prohibited_claim(line, phrase):
                    findings.append((path, line_number, phrase))

    for path, line_number, phrase in findings:
        print(f"{path}:{line_number}: prohibited claim: {phrase}")
    return 1 if findings else 0


def _iter_files(root: Path, targets: list[Path]):
    for target in targets:
        path = target if target.is_absolute() else root / target
        if path.is_file() and _is_text_file(path):
            yield path
        elif path.is_dir():
            for child in path.rglob("*"):
                if any(part in SKIPPED_DIRS for part in child.parts):
                    continue
                if child.is_file() and _is_text_file(child):
                    yield child


def _is_text_file(path: Path) -> bool:
    return path.suffix in TEXT_SUFFIXES


def _is_prohibited_claim(line: str, phrase: str) -> bool:
    lowered = line.lower()
    stripped = lowered.strip()
    if stripped.startswith("- no ") or stripped.startswith("no "):
        return False
    if any(marker in lowered for marker in NEGATING_LINE_MARKERS):
        return False
    needle = phrase.lower()
    index = lowered.find(needle)
    if index < 0:
        return False
    prefix = lowered[max(0, index - 16) : index]
    return not any(prefix.endswith(item) for item in NEGATING_PREFIXES)


if __name__ == "__main__":
    raise SystemExit(main())
