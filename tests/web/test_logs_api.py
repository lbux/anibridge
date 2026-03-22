"""Tests for log history API file discovery."""

import logging

from anibridge.app.web.routes.api import logs as logs_api


def test_list_log_files_case_insensitive_filename_match(tmp_path, monkeypatch):
    """File discovery is case-insensitive, but only lowercase filename is active."""
    mixed_case = tmp_path / "AniBridge.INFO.log"
    mixed_case.write_text("line\n", encoding="utf-8")
    lower_case = tmp_path / "anibridge.INFO.log"
    lower_case.write_text("line\n", encoding="utf-8")

    monkeypatch.setattr(logs_api, "LOG_DIR", tmp_path)

    logger = logging.getLogger("anibridge")
    original_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        result = logs_api.list_log_files()
    finally:
        logger.setLevel(original_level)

    mixed_entry = next(item for item in result if item.name == "AniBridge.INFO.log")
    lower_entry = next(item for item in result if item.name == "anibridge.INFO.log")

    assert mixed_entry.current is False
    assert lower_entry.current is True


def test_get_log_file_returns_tail_when_length_limited(tmp_path, monkeypatch):
    """Length-limited reads should return the final N lines, oldest to newest."""
    log_file = tmp_path / "anibridge.DEBUG.log"
    log_file.write_text(
        "\n".join([f"line-{i}" for i in range(1, 11)]) + "\n", encoding="utf-8"
    )

    monkeypatch.setattr(logs_api, "LOG_DIR", tmp_path)

    result = logs_api.get_log_file("anibridge.DEBUG.log", lines=3)

    assert [entry.message for entry in result] == ["line-8", "line-9", "line-10"]


def test_get_log_file_returns_all_lines_when_unlimited(tmp_path, monkeypatch):
    """A lines=0 request should return every line in file order."""
    log_file = tmp_path / "anibridge.DEBUG.log"
    log_file.write_text(
        "\n".join([f"line-{i}" for i in range(1, 6)]) + "\n", encoding="utf-8"
    )

    monkeypatch.setattr(logs_api, "LOG_DIR", tmp_path)

    result = logs_api.get_log_file("anibridge.DEBUG.log", lines=0)

    assert [entry.message for entry in result] == [
        "line-1",
        "line-2",
        "line-3",
        "line-4",
        "line-5",
    ]


def test_get_log_file_tail_without_trailing_newline(tmp_path, monkeypatch):
    """Tail reads should work when the file does not end with a newline."""
    log_file = tmp_path / "anibridge.DEBUG.log"
    log_file.write_text("\n".join([f"line-{i}" for i in range(1, 6)]), encoding="utf-8")

    monkeypatch.setattr(logs_api, "LOG_DIR", tmp_path)

    result = logs_api.get_log_file("anibridge.DEBUG.log", lines=2)

    assert [entry.message for entry in result] == ["line-4", "line-5"]
