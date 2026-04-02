"""Tests for HTTP Basic Authentication middleware and integration."""

import base64
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from pytest import MonkeyPatch

from anibridge.app.config.database import db
from anibridge.app.config.settings import AnibridgeConfig, BasicAuthConfig, WebConfig
from anibridge.app.models.db.sync_history import SyncHistory, SyncOutcome
from anibridge.app.web import app as app_module
from anibridge.app.web.middlewares import basic_auth as basic_auth_module
from anibridge.app.web.middlewares.basic_auth import BasicAuthMiddleware
from anibridge.app.web.state import get_app_state


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    """Build an Authorization header for HTTP Basic credentials."""
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_basic_auth_middleware_challenges_and_allows_access() -> None:
    """BasicAuthMiddleware challenges invalid credentials and allows valid ones."""
    test_app = FastAPI()
    test_app.add_middleware(
        BasicAuthMiddleware,  # type: ignore[arg-type]
        username="admin",
        password="secret",
        realm="Realm",
    )

    @test_app.get("/protected")
    async def protected() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(test_app)

    # Missing credentials
    response = client.get("/protected")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == 'Basic realm="Realm"'

    # Wrong credentials
    wrong = client.get("/protected", headers=_basic_auth_header("admin", "wrong"))
    assert wrong.status_code == 401

    # Correct credentials
    success = client.get("/protected", headers=_basic_auth_header("admin", "secret"))
    assert success.status_code == 200
    assert success.json() == {"ok": True}


def test_basic_auth_middleware_allows_access_with_htpasswd(
    tmp_path: Path,
) -> None:
    """BasicAuthMiddleware allows access with valid htpasswd credentials."""
    htpasswd_file = tmp_path / "htpasswd"
    htpasswd_file.write_text(
        "test:$2y$10$AVmi7rydBM1wRpzyrv2V5eGmBdYiHLIq07V.xOGza.tBTkTa1eZ1S",
        encoding="utf-8",
    )  # bcrypt hash for "test"

    test_app = FastAPI()
    test_app.add_middleware(
        BasicAuthMiddleware,  # type: ignore[arg-type]
        htpasswd_path=htpasswd_file,
        realm="Realm",
    )

    @test_app.get("/protected")
    async def protected() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(test_app)

    # Wrong credentials
    wrong = client.get("/protected", headers=_basic_auth_header("test", "wrong"))
    assert wrong.status_code == 401

    # Correct credentials
    success = client.get("/protected", headers=_basic_auth_header("test", "test"))
    assert success.status_code == 200
    assert success.json() == {"ok": True}


def test_basic_auth_middleware_plain_and_htpasswd(
    tmp_path: Path,
) -> None:
    """BasicAuthMiddleware allows access with both plain and htpasswd credentials."""
    htpasswd_file = tmp_path / "htpasswd"
    htpasswd_file.write_text(
        "htuser:$2y$10$AVmi7rydBM1wRpzyrv2V5eGmBdYiHLIq07V.xOGza.tBTkTa1eZ1S",
        encoding="utf-8",
    )  # bcrypt hash for "test"

    test_app = FastAPI()
    test_app.add_middleware(
        BasicAuthMiddleware,  # type: ignore[arg-type]
        username="plainuser",
        password="plainpass",
        htpasswd_path=htpasswd_file,
        realm="Realm",
    )

    @test_app.get("/protected")
    async def protected() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(test_app)

    # Correct plain credentials
    success_plain = client.get(
        "/protected", headers=_basic_auth_header("plainuser", "plainpass")
    )
    assert success_plain.status_code == 200
    assert success_plain.json() == {"ok": True}

    # Correct htpasswd credentials
    success_htpasswd = client.get(
        "/protected", headers=_basic_auth_header("htuser", "test")
    )
    assert success_htpasswd.status_code == 200
    assert success_htpasswd.json() == {"ok": True}


def test_basic_auth_middleware_bypasses_probe_endpoints() -> None:
    """BasicAuthMiddleware should not challenge unauthenticated probe endpoints."""
    test_app = FastAPI()
    test_app.add_middleware(
        BasicAuthMiddleware,  # type: ignore[arg-type]
        username="admin",
        password="secret",
        realm="Realm",
    )

    @test_app.get("/livez")
    async def livez() -> dict[str, str]:
        return {"status": "ok"}

    @test_app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @test_app.get("/readyz")
    async def readyz() -> dict[str, object]:
        return {"status": "ok", "ready": True}

    @test_app.get("/protected")
    async def protected() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(test_app)

    legacy_health = client.get("/healthz")
    assert legacy_health.status_code == 200
    assert legacy_health.json() == {"status": "ok"}

    health = client.get("/livez")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ok", "ready": True}

    assert client.get("/protected").status_code == 401


def test_basic_auth_extract_credentials_handles_invalid_headers() -> None:
    """Malformed Authorization headers should be ignored safely."""

    def _app(scope, receive, send):
        pass

    middleware = BasicAuthMiddleware(_app)

    scope = {"type": "http", "headers": []}
    assert middleware._extract_credentials(scope) is None

    bad_scheme = {"type": "http", "headers": [(b"authorization", b"Bearer token")]}
    assert middleware._extract_credentials(bad_scheme) is None

    invalid_base64 = {
        "type": "http",
        "headers": [(b"authorization", b"Basic !!!")],
    }
    assert middleware._extract_credentials(invalid_base64) is None

    missing_separator = {
        "type": "http",
        "headers": [(b"authorization", b"Basic dXNlcg==")],
    }
    assert middleware._extract_credentials(missing_separator) is None


def test_basic_auth_load_htpasswd_handles_cache_and_errors(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """htpasswd loading should cache results and tolerate read failures."""
    htpasswd_file = tmp_path / "htpasswd"
    htpasswd_file.write_text(
        "test:$2y$10$AVmi7rydBM1wRpzyrv2V5eGmBdYiHLIq07V.xOGza.tBTkTa1eZ1S",
        encoding="utf-8",
    )

    def _app(scope, receive, send):
        pass

    middleware = BasicAuthMiddleware(  # type: ignore[arg-type]
        _app,
        htpasswd_path=htpasswd_file,
    )

    calls = {"count": 0}
    original_from_file = basic_auth_module.HtpasswdFile.from_file

    def _from_file(path: Path):
        calls["count"] += 1
        return original_from_file(path)

    monkeypatch.setattr(basic_auth_module.HtpasswdFile, "from_file", _from_file)
    first = middleware._load_htpasswd()
    second = middleware._load_htpasswd()
    assert first is second
    assert calls["count"] == 1
    assert middleware._validate_htpasswd("test", "test") is True

    missing = BasicAuthMiddleware(  # type: ignore[arg-type]
        lambda scope, receive, send: None,
        htpasswd_path=tmp_path / "missing",
    )
    assert missing._load_htpasswd() is None

    class _BrokenPath:
        def stat(self):
            raise OSError("boom")

    broken = BasicAuthMiddleware(  # type: ignore[arg-type]
        lambda scope, receive, send: None,
        htpasswd_path=_BrokenPath(),
    )
    assert broken._load_htpasswd() is None


@pytest.mark.asyncio
async def test_basic_auth_middleware_passes_through_non_http() -> None:
    """Non-HTTP scopes should be forwarded unchanged."""
    called = False

    async def app(scope, receive, send) -> None:
        nonlocal called
        called = True

    def _middleware_receive():
        return {"type": "websocket.receive", "text": "hello"}

    async def _middleware_send(message) -> None:
        pass

    middleware = BasicAuthMiddleware(app)
    await middleware({"type": "websocket"}, _middleware_receive, _middleware_send)

    assert called is True


def test_create_app_registers_basic_auth_middleware_when_configured(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """create_app should attach BasicAuthMiddleware when credentials are configured."""
    web_config = WebConfig(
        basic_auth=BasicAuthConfig(
            username="admin",
            password=SecretStr("secret"),
            htpasswd_path=None,
            realm="Realm",
        )
    )
    test_config = AnibridgeConfig(web=web_config)
    monkeypatch.setattr(app_module, "config", test_config, raising=False)

    # Ensure the SPA assets check passes
    index_file = tmp_path / "index.html"
    index_file.write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(app_module, "FRONTEND_BUILD_DIR", tmp_path, raising=False)

    app = app_module.create_app()

    middleware_classes = {middleware.cls for middleware in app.user_middleware}
    assert BasicAuthMiddleware in middleware_classes


def test_create_app_skips_basic_auth_without_complete_credentials(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """create_app should skip BasicAuthMiddleware if either credential is missing."""
    web_config = WebConfig(
        basic_auth=BasicAuthConfig(
            username="admin",
            password=None,
            htpasswd_path=None,
            realm="Realm",
        )
    )
    incomplete_config = AnibridgeConfig(web=web_config)
    monkeypatch.setattr(app_module, "config", incomplete_config, raising=False)

    index_file = tmp_path / "index.html"
    index_file.write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(app_module, "FRONTEND_BUILD_DIR", tmp_path, raising=False)

    app = app_module.create_app()

    middleware_classes = {middleware.cls for middleware in app.user_middleware}
    assert BasicAuthMiddleware not in middleware_classes


def test_create_app_registers_basic_auth_middleware_with_htpasswd(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """create_app should attach BasicAuthMiddleware when htpasswd path is configured."""
    htpasswd_file = tmp_path / "htpasswd"
    htpasswd_file.write_text(
        "test:$2y$10$AVmi7rydBM1wRpzyrv2V5eGmBdYiHLIq07V.xOGza.tBTkTa1eZ1S",
        encoding="utf-8",
    )  # bcrypt hash for "test"

    web_config = WebConfig(
        basic_auth=BasicAuthConfig(
            username=None,
            password=None,
            htpasswd_path=htpasswd_file,
            realm="Realm",
        )
    )
    test_config = AnibridgeConfig(web=web_config)
    monkeypatch.setattr(app_module, "config", test_config, raising=False)

    # Ensure the SPA assets check passes
    index_file = tmp_path / "index.html"
    index_file.write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(app_module, "FRONTEND_BUILD_DIR", tmp_path, raising=False)

    app = app_module.create_app()

    middleware_classes = {middleware.cls for middleware in app.user_middleware}
    assert BasicAuthMiddleware in middleware_classes


def test_create_app_lifespan_purges_ephemeral_history_on_startup(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """Starting the app should delete ephemeral history rows."""
    with db() as ctx:
        ctx.session.query(SyncHistory).delete()
        ctx.session.add_all(
            [
                SyncHistory(
                    profile_name="profile",
                    library_namespace="lib",
                    library_section_key="1",
                    library_media_key="persisted",
                    list_namespace="alist",
                    list_media_key="persisted",
                    media_kind="movie",
                    outcome=SyncOutcome.SYNCED,
                    ephemeral=False,
                ),
                SyncHistory(
                    profile_name="profile",
                    library_namespace="lib",
                    library_section_key="1",
                    library_media_key="ephemeral",
                    list_namespace="alist",
                    list_media_key="ephemeral",
                    media_kind="movie",
                    outcome=SyncOutcome.SYNCED,
                    ephemeral=True,
                ),
            ]
        )
        ctx.session.commit()

    index_file = tmp_path / "index.html"
    index_file.write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(app_module, "FRONTEND_BUILD_DIR", tmp_path, raising=False)

    async def _ensure_public_anilist():
        return SimpleNamespace()

    monkeypatch.setattr(
        get_app_state(),
        "ensure_public_anilist",
        _ensure_public_anilist,
        raising=True,
    )

    app = app_module.create_app()
    with TestClient(app):
        pass

    with db() as ctx:
        rows = (
            ctx.session.query(SyncHistory)
            .order_by(SyncHistory.library_media_key.asc())
            .all()
        )
        assert len(rows) == 1
        assert rows[0].library_media_key == "persisted"
        assert rows[0].ephemeral is False
