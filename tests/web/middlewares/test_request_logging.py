"""Tests for the request logging middleware."""

from typing import Any, cast

import pytest
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from anibridge.app.web.middlewares import request_logging
from anibridge.app.web.middlewares.request_logging import RequestLoggingMiddleware

pytestmark = pytest.mark.asyncio


class _DummyLogger:
    """Simple logger that captures debug messages for assertions."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def debug(self, message: str, *args, **kwargs) -> None:
        if args:
            message = message % args
        self.messages.append(message)


async def _noop_app(scope: Scope, receive: Receive, send: Send) -> None:
    """No-op ASGI app; required to satisfy BaseHTTPMiddleware."""
    return None


def _make_request(
    method: str = "GET",
    path: str = "/",
    query: str = "",
    body: bytes = b"",
    headers: dict[str, str] | None = None,
) -> Request:
    """Create a Starlette Request suitable for exercising the middleware."""
    scope: dict[str, Any] = {
        "type": "http",
        "method": method,
        "path": path,
        "root_path": "",
        "scheme": "http",
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "query_string": query.encode(),
        "headers": [
            (name.lower().encode("utf-8"), value.encode("utf-8"))
            for name, value in (headers or {}).items()
        ],
    }

    body_sent = False

    async def receive() -> dict[str, Any]:
        nonlocal body_sent
        if body_sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        body_sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


def _make_scope(
    *,
    method: str = "GET",
    path: str = "/",
    headers: dict[str, str] | None = None,
) -> Scope:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "path": path,
        "root_path": "",
        "scheme": "http",
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "query_string": b"",
        "headers": [
            (name.lower().encode("utf-8"), value.encode("utf-8"))
            for name, value in (headers or {}).items()
        ],
    }


@pytest.fixture
def dummy_logger(
    monkeypatch: pytest.MonkeyPatch,
) -> _DummyLogger:
    """Patch the module logger with a simple message collector."""
    logger = _DummyLogger()
    monkeypatch.setattr(request_logging, "log", logger)
    return logger


@pytest.fixture
def middleware() -> RequestLoggingMiddleware:
    """Create the middleware under test."""
    return RequestLoggingMiddleware(_noop_app)


async def test_request_logging_middleware_logs_success(
    dummy_logger: _DummyLogger,
    middleware: RequestLoggingMiddleware,
) -> None:
    """Middleware logs method, path, query, and status for successful requests."""
    request = _make_request(path="/status", query="ready=true")

    async def call_next(req: Request) -> Response:
        return Response(content=b"ok", status_code=204)

    response = await middleware.dispatch(request, call_next)

    assert response.status_code == 204
    assert dummy_logger.messages, "expected debug output"
    assert "GET /status?ready=true" in dummy_logger.messages[0]
    assert "Response: 204" in dummy_logger.messages[0]


async def test_request_logging_middleware_captures_json_body(
    dummy_logger: _DummyLogger,
    middleware: RequestLoggingMiddleware,
) -> None:
    """Middleware captures readable request bodies without consuming the stream."""
    json_body = b'{"message":"hello"}'
    request = _make_request(
        method="POST",
        path="/api/items",
        body=json_body,
        headers={"content-type": "application/json"},
    )

    async def call_next(req: Request) -> Response:
        # Ensure downstream handler can still access the body.
        assert await req.body() == json_body
        return Response(status_code=201)

    response = await middleware.dispatch(request, call_next)

    assert response.status_code == 201
    assert any('Body: {"message":"hello"}' in msg for msg in dummy_logger.messages)
    stored_body = request.scope.get("body")
    assert stored_body is not None
    assert stored_body.getvalue() == json_body


async def test_request_logging_middleware_logs_failures(
    dummy_logger: _DummyLogger,
    middleware: RequestLoggingMiddleware,
) -> None:
    """Middleware logs failures and re-raises downstream exceptions."""
    request = _make_request(method="DELETE", path="/api/items/42")

    async def failing_call_next(_: Request) -> Response:
        # Exercise the middleware's failure logging path.
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await middleware.dispatch(request, failing_call_next)

    assert any("Failed" in message for message in dummy_logger.messages)


async def test_request_logging_middleware_truncates_long_text_body(
    dummy_logger: _DummyLogger,
    middleware: RequestLoggingMiddleware,
) -> None:
    """Large text payloads are truncated to avoid oversized log entries."""
    long_body = ("x" * 1200).encode()
    request = _make_request(
        method="POST",
        path="/big",
        body=long_body,
        headers={"content-type": "application/json"},
    )

    async def call_next(req: Request) -> Response:
        assert len(await req.body()) == len(long_body)
        return Response(status_code=202)

    await middleware.dispatch(request, call_next)

    assert any(
        "..." in message and "Body:" in message for message in dummy_logger.messages
    )


async def test_request_logging_middleware_handles_binary_payloads(
    dummy_logger: _DummyLogger,
    middleware: RequestLoggingMiddleware,
) -> None:
    """Binary payloads are logged with metadata instead of decoded text."""
    request = _make_request(
        method="POST",
        path="/upload",
        body=b"\x00\x01",
        headers={"content-type": "application/octet-stream"},
    )

    async def call_next(req: Request) -> Response:
        assert await req.body() == b"\x00\x01"
        return Response(status_code=200)

    await middleware.dispatch(request, call_next)

    assert any(
        "<application/octet-stream, 2 bytes>" in msg for msg in dummy_logger.messages
    )


async def test_request_logging_middleware_handles_decode_errors(
    dummy_logger: _DummyLogger,
    middleware: RequestLoggingMiddleware,
) -> None:
    """UnicodeDecodeError branches fall back to binary metadata logging."""
    bad_body = b"\xff\xfe"
    request = _make_request(
        method="POST",
        path="/garbled",
        body=bad_body,
        headers={"content-type": "text/plain"},
    )

    async def call_next(req: Request) -> Response:
        assert await req.body() == bad_body
        return Response(status_code=200)

    await middleware.dispatch(request, call_next)

    assert any("binary data" in message for message in dummy_logger.messages)


async def test_request_logging_middleware_handles_body_read_errors(
    dummy_logger: _DummyLogger,
    middleware: RequestLoggingMiddleware,
) -> None:
    """Exceptions while reading the body are logged and do not break the request."""
    request = _make_request(method="POST", path="/broken")

    async def broken_body() -> bytes:
        raise RuntimeError("boom")

    request.body = broken_body  # ty:ignore[invalid-assignment]

    async def call_next(req: Request) -> Response:
        return Response(status_code=204)

    response = await middleware.dispatch(request, call_next)
    assert response.status_code == 204
    assert any("<error reading" in message for message in dummy_logger.messages)


async def test_request_logging_middleware_asgi_call_replays_body_and_logs_response(
    dummy_logger: _DummyLogger,
) -> None:
    """ASGI entrypoint should replay the request body to the downstream app."""
    captured: list[bytes] = []
    messages: list[dict[str, Any]] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        first = await receive()
        captured.append(first["body"])
        await send({"type": "http.response.start", "status": 201, "headers": []})
        await send({"type": "http.response.body", "body": b"ok", "more_body": False})

    middleware = RequestLoggingMiddleware(app)
    scope = _make_scope(
        method="POST",
        path="/upload",
        headers={"content-type": "application/json"},
    )
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {
            "type": "http.request",
            "body": b'{"hello":"world"}',
            "more_body": False,
        }

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    await middleware(scope, receive, cast(Send, send))

    assert captured == [b'{"hello":"world"}']
    assert messages[0]["status"] == 201
    assert any("Response: 201" in message for message in dummy_logger.messages)


async def test_request_logging_middleware_asgi_call_handles_non_http(
    dummy_logger: _DummyLogger,
) -> None:
    """Non-HTTP scopes should pass through without request logging."""
    called = False

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal called
        called = True

    middleware = RequestLoggingMiddleware(app)

    await middleware({"type": "websocket"}, lambda: None, lambda _message: None)

    assert called is True
    assert dummy_logger.messages == []


async def test_request_logging_middleware_asgi_call_closes_on_failure(
    dummy_logger: _DummyLogger,
) -> None:
    """ASGI entrypoint should log failures and re-raise downstream errors."""

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        raise RuntimeError("boom")

    middleware = RequestLoggingMiddleware(app)

    with pytest.raises(RuntimeError):
        await middleware(
            _make_scope(path="/broken"),
            lambda: {"type": "http.request", "body": b"", "more_body": False},
            lambda _message: None,
        )

    assert any("Failed" in message for message in dummy_logger.messages)
