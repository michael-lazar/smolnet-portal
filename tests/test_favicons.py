import asyncio

import pytest

from geminiportal.favicons import FaviconCache
from geminiportal.urls import URLReference


async def test_favicon_cache(session_factory, monkeypatch):
    url = URLReference("gemini://mozz.us")
    cache = FaviconCache(session_factory)

    # Keep the background fetch hanging, so the task is still
    # running when the cache is checked for the second time.
    async def fetch_forever(favicon_url):
        await asyncio.Event().wait()

    monkeypatch.setattr(cache, "_fetch_favicon", fetch_forever)

    assert await cache.check(url) is None
    assert len(cache.tasks) == 1

    assert await cache.check(url) is None
    assert len(cache.tasks) == 1

    cache.shutdown()


@pytest.mark.integration
async def test_favicon_cache_update(session_factory):
    url = URLReference("gemini://mozz.us")
    cache = FaviconCache(session_factory)

    assert await cache.check(url) is None
    assert len(cache.tasks) == 1

    task = next(iter(cache.tasks.values()))
    await asyncio.wait_for(task, 10)
    assert await cache.check(url) == "🐟"
    assert len(cache.tasks) == 0

    cache.shutdown()
