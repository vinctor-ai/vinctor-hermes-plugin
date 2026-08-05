import tomllib
from pathlib import Path


def test_published_package_points_to_the_public_repository() -> None:
    metadata = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["urls"] == {
        "Homepage": "https://github.com/vinctor-ai/vinctor-hermes-plugin#readme",
        "Repository": "https://github.com/vinctor-ai/vinctor-hermes-plugin",
        "Issues": "https://github.com/vinctor-ai/vinctor-hermes-plugin/issues",
    }
