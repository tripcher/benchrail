"""Helpers for manual version bumps and release tags."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Final

VERSION_FILE: Final = Path(__file__).with_name("__init__.py")
VERSION_PATTERN: Final = re.compile(r'__version__ = "(\d+)\.(\d+)\.(\d+)"')
VALID_BUMPS: Final = ("major", "minor", "patch")


def bump_version_parts(version: tuple[int, int, int], bump: str) -> tuple[int, int, int]:
    """Return the next semantic version for the requested bump type."""
    major, minor, patch = version

    if bump == "major":
        return (major + 1, 0, 0)
    if bump == "minor":
        return (major, minor + 1, 0)
    if bump == "patch":
        return (major, minor, patch + 1)

    valid_bumps = ", ".join(VALID_BUMPS)
    raise ValueError(f"Unsupported bump type: {bump}. Expected one of: {valid_bumps}.")


def read_version(version_file: Path = VERSION_FILE) -> str:
    """Read the current package version from the version file."""
    text = version_file.read_text()
    match = VERSION_PATTERN.search(text)
    if match is None:
        raise ValueError(f"Unable to locate __version__ in {version_file}.")

    return ".".join(match.groups())


def bump_version_file(bump: str, version_file: Path = VERSION_FILE) -> str:
    """Update the version file in place and return the new version string."""
    text = version_file.read_text()
    match = VERSION_PATTERN.search(text)
    if match is None:
        raise ValueError(f"Unable to locate __version__ in {version_file}.")

    major, minor, patch = (int(part) for part in match.groups())
    next_version = ".".join(str(part) for part in bump_version_parts((major, minor, patch), bump))
    updated_text = VERSION_PATTERN.sub(f'__version__ = "{next_version}"', text, count=1)
    version_file.write_text(updated_text)
    return next_version


def release_tag(version_file: Path = VERSION_FILE) -> str:
    """Return the Git tag name for the current package version."""
    return f"v{read_version(version_file)}"


def main(argv: list[str] | None = None) -> int:
    """Bump the package version from the command line."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        valid_bumps = "|".join(VALID_BUMPS)
        print(f"Usage: python -m benchrail.versioning <{valid_bumps}>", file=sys.stderr)
        return 1

    try:
        new_version = bump_version_file(args[0])
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(new_version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
