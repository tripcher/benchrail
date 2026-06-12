"""Tests for release versioning helpers."""

from pathlib import Path

import pytest

from benchrail.versioning import bump_version_file, bump_version_parts, read_version, release_tag


def test_bump_version_parts_supports_semver_levels() -> None:
    assert bump_version_parts((1, 2, 3), "patch") == (1, 2, 4)
    assert bump_version_parts((1, 2, 3), "minor") == (1, 3, 0)
    assert bump_version_parts((1, 2, 3), "major") == (2, 0, 0)


def test_bump_version_parts_rejects_unknown_bump() -> None:
    with pytest.raises(ValueError, match="Unsupported bump type"):
        bump_version_parts((1, 2, 3), "banana")


def test_bump_version_file_updates_init_version(tmp_path: Path) -> None:
    version_file = tmp_path / "__init__.py"
    version_file.write_text('"""meta"""\n\n__version__ = "0.2.1"\n')

    new_version = bump_version_file("patch", version_file=version_file)

    assert new_version == "0.2.2"
    assert read_version(version_file) == "0.2.2"
    assert release_tag(version_file) == "v0.2.2"


def test_bump_version_file_requires_version_assignment(tmp_path: Path) -> None:
    version_file = tmp_path / "__init__.py"
    version_file.write_text('"""meta"""\n')

    with pytest.raises(ValueError, match="Unable to locate __version__"):
        bump_version_file("patch", version_file=version_file)
