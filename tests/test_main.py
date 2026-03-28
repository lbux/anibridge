"""Tests for top-level application process helpers."""

import asyncio
from types import SimpleNamespace

import pytest

import main


@pytest.mark.asyncio
async def test_shutdown_web_server_requests_graceful_exit() -> None:
    """Graceful shutdown should mark the server for exit and await completion."""
    server = SimpleNamespace(should_exit=False, force_exit=False)

    async def complete_soon() -> None:
        await asyncio.sleep(0)

    server_task = asyncio.create_task(complete_soon())

    await main._shutdown_web_server(
        server,  # ty:ignore[invalid-argument-type]
        server_task,
        timeout=0.1,
        force_timeout=0.1,
    )

    assert server.should_exit is True
    assert server.force_exit is False
    assert server_task.done() is True


@pytest.mark.asyncio
async def test_shutdown_web_server_forces_exit_when_graceful_stop_hangs() -> None:
    """Hung web shutdowns should escalate to force_exit and task cancellation."""
    server = SimpleNamespace(should_exit=False, force_exit=False)
    blocker = asyncio.Event()

    async def never_finishes() -> None:
        await blocker.wait()

    server_task = asyncio.create_task(never_finishes())

    await main._shutdown_web_server(
        server,  # ty:ignore[invalid-argument-type]
        server_task,
        timeout=0.01,
        force_timeout=0.01,
    )

    assert server.should_exit is True
    assert server.force_exit is True
    assert server_task.cancelled() is True
