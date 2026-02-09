"""Shared fixtures for Maude tests."""

from __future__ import annotations

import os

import pytest

from maude.client.http import GovernorClient


def governor_url() -> str | None:
    """Return GOVERNOR_URL if set, else None."""
    return os.environ.get("GOVERNOR_URL")


def requires_governor(reason: str = "GOVERNOR_URL not set"):
    """Skip test if no live governor is available."""
    return pytest.mark.skipif(governor_url() is None, reason=reason)


@pytest.fixture
async def client():
    """Async GovernorClient pointed at GOVERNOR_URL.

    Skips if GOVERNOR_URL is not set.
    """
    url = governor_url()
    if url is None:
        pytest.skip("GOVERNOR_URL not set — run via test-with-governor.sh")
    c = GovernorClient(base_url=url)
    yield c
    await c.close()
