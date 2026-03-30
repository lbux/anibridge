"""Tests for version utility helpers."""

import builtins
import importlib.metadata
import string
import tomllib
from pathlib import Path

import pytest

from anibridge.app.utils import version as version_module


def test_get_pyproject_version_matches_pyproject() -> None:
    """Test that get_pyproject_version matches the version in pyproject.toml."""
    with Path("pyproject.toml").open("rb") as f:
        pyproject = tomllib.load(f)

    expected_version = pyproject["project"]["version"]

    assert version_module.get_pyproject_version() == expected_version


def test_get_git_hash_returns_hex_or_unknown() -> None:
    """Test that get_git_hash returns a valid git hash or 'unknown'."""
    git_hash = version_module.get_git_hash()

    assert isinstance(git_hash, str)
    if git_hash != "unknown":
        assert len(git_hash) in {7, 40}
        assert all(char in string.hexdigits for char in git_hash)


def test_get_pyproject_version_returns_unknown_for_uninstalled_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Package metadata lookup failures should degrade to 'unknown'."""

    def _raise_missing(_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(importlib.metadata, "version", _raise_missing)

    assert version_module.get_pyproject_version() == "unknown"


def test_get_git_hash_returns_unknown_without_project_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing project root should skip git probing."""
    monkeypatch.setattr(version_module, "PROJECT_ROOT", None)

    assert version_module.get_git_hash() == "unknown"


def test_get_git_hash_reads_direct_head_commit(tmp_path: Path, monkeypatch) -> None:
    """Detached HEAD commits should be returned directly from `.git/HEAD`."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("abc123\n", encoding="utf-8")
    monkeypatch.setattr(version_module, "PROJECT_ROOT", tmp_path)

    assert version_module.get_git_hash() == "abc123"


def test_get_git_hash_reads_branch_ref_file(tmp_path: Path, monkeypatch) -> None:
    """Branch refs should be resolved from the referenced file when present."""
    git_dir = tmp_path / ".git"
    ref_dir = git_dir / "refs" / "heads"
    ref_dir.mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (ref_dir / "main").write_text("def456\n", encoding="utf-8")
    monkeypatch.setattr(version_module, "PROJECT_ROOT", tmp_path)

    assert version_module.get_git_hash() == "def456"


def test_get_git_hash_reads_packed_refs_fallback(tmp_path: Path, monkeypatch) -> None:
    """Packed refs should be consulted when the loose ref file is absent."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git_dir / "packed-refs").write_text(
        "# pack-refs\n789abc refs/heads/main\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(version_module, "PROJECT_ROOT", tmp_path)

    assert version_module.get_git_hash() == "789abc"


def test_get_git_hash_handles_missing_git_metadata(tmp_path: Path, monkeypatch) -> None:
    """Missing or unreadable git metadata should return 'unknown'."""
    monkeypatch.setattr(version_module, "PROJECT_ROOT", tmp_path)
    assert version_module.get_git_hash() == "unknown"

    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    monkeypatch.setattr(builtins, "open", lambda *_args, **_kwargs: 1 / 0)
    assert version_module.get_git_hash() == "unknown"


def test_get_docker_status_uses_dockerenv_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Docker detection should depend on both existence and file status."""

    class FakePath:
        def __init__(self, _value: str) -> None:
            pass

        def exists(self) -> bool:
            return True

        def is_file(self) -> bool:
            return True

    monkeypatch.setattr(version_module, "Path", FakePath)
    assert version_module.get_docker_status() is True

    class MissingPath(FakePath):
        def exists(self) -> bool:
            return False

    monkeypatch.setattr(version_module, "Path", MissingPath)
    assert version_module.get_docker_status() is False
