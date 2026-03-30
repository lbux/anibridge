"""Shared pytest configuration and fixtures for the test suite."""

import atexit
import importlib
import os
import shutil
import sys
import tempfile
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Protocol

import pytest
import yaml
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="ab-tests-"))
os.environ["AB_DATA_PATH"] = str(_TEST_DATA_DIR)
_TEST_CONFIG_FILE = _TEST_DATA_DIR / "config.yaml"

_TEST_CONFIG_FILE.write_text(
    yaml.safe_dump(
        {
            "providers": {
                "anilist": {"token": "anilist-token"},
                "plex": {
                    "token": "plex-token",
                    "user": "eliasbenb",
                    "url": "http://plex:32400",
                },
            },
        },
        sort_keys=False,
    ),
    encoding="utf-8",
)

from anibridge.utils.limiter import Limiter  # noqa: E402

from anibridge.app.config import settings as settings_module  # noqa: E402
from anibridge.app.config.database import db as db_factory  # noqa: E402
from anibridge.app.models.db.base import Base  # noqa: E402
from anibridge.app.utils import logging as logging_module  # noqa: E402
from anibridge.app.web.state import get_app_state  # noqa: E402

settings_module.get_config.cache_clear()
logging_module.get_logger.cache_clear()
db_factory.cache_clear()

src_module = sys.modules.get("anibridge.app")
if src_module is None:
    src_module = importlib.import_module("anibridge.app")

src_module.config = settings_module.get_config()  # type: ignore
src_module.log = logging_module.get_logger()  # type: ignore

Limiter.DISABLED = True


class _SessionContextOwner(Protocol):
    _session_ctx: ContextVar[Session | None]


def pytest_sessionstart() -> None:
    """Fail fast if tests are configured to use the real data directory."""
    data_path = Path(os.getenv("AB_DATA_PATH", "./data")).resolve()
    repo_data_path = (Path(__file__).resolve().parents[1] / "data").resolve()
    if data_path == repo_data_path or data_path == Path("./data").resolve():
        raise RuntimeError(
            "Refusing to run tests against the real data directory. "
            "Set AB_DATA_PATH to a temporary location."
        )


@pytest.fixture(autouse=True)
def _reset_app_state():
    """Ensure each test interacts with a fresh AppState instance."""
    get_app_state.cache_clear()
    state = get_app_state()
    yield state
    get_app_state.cache_clear()


@pytest.fixture
def in_memory_db_factory():
    """Build disposable SQLite-backed DB stubs patched into target modules."""
    resources: list[tuple[_SessionContextOwner, Engine]] = []

    def _factory(
        monkeypatch: pytest.MonkeyPatch,
        *modules: object,
    ) -> _SessionContextOwner:
        from sqlalchemy.engine import create_engine
        from sqlalchemy.orm import sessionmaker

        engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(
            bind=engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            future=True,
        )

        class _DB:
            def __init__(self) -> None:
                self._session_ctx: ContextVar[Session | None] = ContextVar(
                    "test_db_session",
                    default=None,
                )
                self._session_tokens: ContextVar[tuple[Token[Session | None], ...]] = (
                    ContextVar("test_db_session_tokens", default=())
                )

            def __enter__(self):
                session = session_factory()
                token = self._session_ctx.set(session)
                tokens = self._session_tokens.get()
                self._session_tokens.set((*tokens, token))
                return self

            def __exit__(self, exc_type, exc_val, exc_tb) -> None:
                session = self._session_ctx.get()
                if session is not None:
                    session.close()

                tokens = self._session_tokens.get()
                if not tokens:
                    self._session_ctx.set(None)
                    return

                token = tokens[-1]
                self._session_tokens.set(tokens[:-1])
                self._session_ctx.reset(token)

            @property
            def session(self):
                session = self._session_ctx.get()
                if session is None:
                    session = session_factory()
                    token = self._session_ctx.set(session)
                    tokens = self._session_tokens.get()
                    self._session_tokens.set((*tokens, token))
                return session

        db_instance = _DB()

        for module in modules:
            monkeypatch.setattr(module, "db", lambda: db_instance)

        resources.append((db_instance, engine))
        return db_instance

    yield _factory

    for db_instance, engine in reversed(resources):
        session = db_instance._session_ctx.get()
        if session is not None:
            session.close()
        engine.dispose()


@atexit.register
def _cleanup_test_data_dir() -> None:
    """Remove the temporary test data directory after the test session."""
    shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)
