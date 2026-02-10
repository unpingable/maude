"""Shared fixtures for Maude tests."""

from __future__ import annotations

import os

import pytest

from maude.client.rpc import GovernorClient


def governor_socket() -> str | None:
    """Return GOVERNOR_SOCKET if set, else None."""
    return os.environ.get("GOVERNOR_SOCKET")


def governor_dir() -> str | None:
    """Return GOVERNOR_DIR if set, else None."""
    return os.environ.get("GOVERNOR_DIR")


def requires_governor(reason: str = "GOVERNOR_SOCKET/GOVERNOR_DIR not set"):
    """Skip test if no live governor is available."""
    return pytest.mark.skipif(
        governor_socket() is None and governor_dir() is None,
        reason=reason,
    )


@pytest.fixture
async def client():
    """Async GovernorClient connected to daemon via Unix socket.

    Skips if neither GOVERNOR_SOCKET nor GOVERNOR_DIR is set.
    """
    sock = governor_socket()
    gdir = governor_dir()
    if sock is None and gdir is None:
        pytest.skip("GOVERNOR_SOCKET/GOVERNOR_DIR not set — run via test-with-governor.sh")
    c = GovernorClient(socket_path=sock, governor_dir=gdir)
    await c.connect()
    yield c
    await c.close()
