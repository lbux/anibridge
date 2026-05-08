"""API endpoints for accessing historical log files."""

import logging
import re
from pathlib import Path

import msgspec
from litestar.handlers.http_handlers.decorators import get
from litestar.router import Router

from anibridge.app import config
from anibridge.app.exceptions import InvalidLogFileNameError, LogFileNotFoundError

__all__ = ["router"]


class LogFileModel(msgspec.Struct):
    name: str
    size: int
    mtime: int  # epoch ms
    current: bool


class LogEntryModel(msgspec.Struct):
    level: str
    message: str
    timestamp: str | None = None


LOG_DIR: Path = (config.data_path / "logs").resolve()


def _is_log_filename(name: str) -> bool:
    lower_name = name.lower()
    return lower_name.startswith("anibridge.") and ".log" in lower_name


LINE_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - "
    r"(?P<logger>[^ ]+?) - (?P<level>[A-Z]+)\t(?P<message>.*)$"
)


def _list_log_files() -> list[Path]:
    if not LOG_DIR.exists():
        return []
    # Include the active log file and rotated backups.
    files = {
        path.name: path
        for path in LOG_DIR.iterdir()
        if path.is_file() and _is_log_filename(path.name)
    }

    return sorted(files.values(), key=lambda p: p.stat().st_mtime, reverse=True)


@get(path="/files", sync_to_thread=True)
def list_log_files() -> list[LogFileModel]:
    """Return metadata about available log files.

    Returns:
        list[LogFileModel]: Log file metadata sorted by most recent first.
    """
    files = _list_log_files()
    res: list[LogFileModel] = []

    # Determine current effective log level to identify active file.
    root_logger = logging.getLogger("anibridge")
    current_level_name = logging.getLevelName(root_logger.getEffectiveLevel())
    active_basename = f"anibridge.{current_level_name}.log"

    for f in files:
        st = f.stat()
        res.append(
            LogFileModel(
                name=f.name,
                size=st.st_size,
                mtime=int(st.st_mtime * 1000),
                # Active file must exactly match the lowercase logger filename
                current=f.name == active_basename,
            )
        )

    return res


def _safe_resolve(name: str) -> Path:
    """Resolve a user-supplied file name safely within LOG_DIR.

    Args:
        name (str): The file name to resolve.

    Raises:
        InvalidLogFileNameError: If the file name is invalid or attempts traversal.
        LogFileNotFoundError: If the file does not exist.
    """
    if "/" in name or ".." in name:
        raise InvalidLogFileNameError("Invalid log file name")

    target = (LOG_DIR / name).resolve()

    if not str(target).startswith(str(LOG_DIR)):
        raise InvalidLogFileNameError("Invalid log file name")

    if not target.exists() or not target.is_file():
        raise LogFileNotFoundError("Log file not found")

    return target


def _tail_lines(path: Path, max_lines: int) -> list[str]:
    """Return up to the last max_lines of the file efficiently.

    Args:
        path (Path): The path to the log file.
        max_lines (int): The maximum number of lines to return. If 0, return all lines.

    Returns:
        list[str]: The last max_lines lines of the file (oldest first). If
                   max_lines == 0, return all lines.
    """
    if max_lines < 0:
        return []

    if max_lines == 0:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            return [ln.rstrip("\n\r") for ln in fh]

    chunk_size = 8192

    with path.open("rb") as fh:
        fh.seek(0, 2)
        file_size = fh.tell()
        if file_size <= 0:
            return []

        pos = file_size
        blocks: list[bytes] = []
        newline_count = 0

        # Read backwards until we have enough separators to reconstruct
        # the final max_lines entries.
        while pos > 0 and newline_count <= max_lines:
            read_size = min(chunk_size, pos)
            pos -= read_size
            fh.seek(pos)
            block = fh.read(read_size)
            blocks.append(block)
            newline_count += block.count(b"\n")

    data = b"".join(reversed(blocks))
    tail_bytes = data.splitlines()[-max_lines:]
    return [line.decode("utf-8", errors="replace") for line in tail_bytes]


@get(path="/file/{name:str}", sync_to_thread=True)
def get_log_file(name: str, lines: int = 500) -> list[LogEntryModel]:
    """Return the last N lines of a log file parsed into JSON entries.

    Args:
        name (str): File name (basename) of the log file.
        lines (int): Maximum number of lines to return (tail). Default 500.

    Returns:
        list[LogEntryModel]: Ordered list (oldest first) of parsed log entries.

    Raises:
        InvalidLogFileNameError: If the file name is invalid.
        LogFileNotFoundError: If the requested log file does not exist.
    """
    path = _safe_resolve(name)
    raw_lines = _tail_lines(path, lines)
    res: list[LogEntryModel] = []

    for ln in raw_lines:
        ln = ln.rstrip("\n\r")
        m = LINE_RE.match(ln)
        if m:
            gd = m.groupdict()
            res.append(
                LogEntryModel(
                    timestamp=gd["timestamp"], level=gd["level"], message=gd["message"]
                )
            )
        else:
            res.append(LogEntryModel(timestamp=None, level="INFO", message=ln))

    return res


router = Router(path="/logs", route_handlers=[list_log_files, get_log_file])
