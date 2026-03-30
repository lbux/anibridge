"""Tests for the minimal htpasswd parser."""

import base64
import hashlib

import pytest

from anibridge.app.utils.htpasswd import HtpasswdFile


def test_htpasswd_parser_validates_input_lines() -> None:
    with pytest.raises(ValueError, match="Malformed"):
        HtpasswdFile("missing-delimiter")

    with pytest.raises(ValueError, match="Malformed"):
        HtpasswdFile(":$2y$10$hash")

    with pytest.raises(ValueError, match="Unsupported"):
        HtpasswdFile("user:plain-text")

    parsed = HtpasswdFile(
        "\n# comment\n"
        "sha:{SHA}" + base64.b64encode(hashlib.sha1(b"secret").digest()).decode("ascii")
    )
    assert "sha" in parsed.users


def test_htpasswd_from_file_wraps_missing_files(tmp_path) -> None:
    with pytest.raises(OSError, match="not found"):
        HtpasswdFile.from_file(tmp_path / "missing")


def test_htpasswd_check_password_supports_sha_and_bcrypt() -> None:
    parser = HtpasswdFile(
        "sha:{SHA}"
        + base64.b64encode(hashlib.sha1(b"secret").digest()).decode("ascii")
        + "\n"
        + "bcrypt:$2y$10$AVmi7rydBM1wRpzyrv2V5eGmBdYiHLIq07V.xOGza.tBTkTa1eZ1S"
    )

    assert parser.check_password("missing", "secret") is False
    assert parser.check_password("sha", "secret") is True
    assert parser.check_password("sha", "wrong") is False
    assert parser.check_password("bcrypt", "test") is True
    assert parser.check_password("bcrypt", "wrong") is False
