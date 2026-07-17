import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from geminiportal import db
from geminiportal.errors import BaseProxyError
from geminiportal.models import Favicon
from geminiportal.protocols import build_proxy_request
from geminiportal.urls import URLReference
from geminiportal.utils import smart_decode

_logger = logging.getLogger(__name__)


class FaviconCache:
    """
    Download favicon.txt files from sites in the background, and
    stash the results in the sqlite database.
    """

    FAVICON_PATH = "/favicon.txt"
    EXPIRATION = timedelta(hours=4)

    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None):
        self.session_factory = session_factory or db.session_factory

        # References to coroutines that are currently fetching favicons
        self.tasks: dict[str, asyncio.Task] = {}

    async def check(self, url: URLReference) -> str | None:
        if url.scheme not in ("gemini", "spartan"):
            return None

        favicon_url = url.join(self.FAVICON_PATH)
        key = favicon_url.get_url()
        async with self.session_factory() as session:
            favicon = await session.scalar(
                select(Favicon).where(
                    Favicon.url == key,
                    Favicon.expires_at > datetime.utcnow(),
                )
            )
            if favicon is not None:
                return favicon.emoji

        # Schedule a background task to download and save the favicon
        # Only make one request per-domain at a time to avoid spamming
        if key not in self.tasks:
            self.tasks[key] = asyncio.create_task(self._update(favicon_url))
            self.tasks[key].add_done_callback(lambda *_: self.tasks.pop(key))

        return None

    def shutdown(self) -> None:
        for _, task in self.tasks.items():
            task.cancel()

    async def _update(self, favicon_url: URLReference) -> None:
        emoji = None
        try:
            emoji = await self._fetch_favicon(favicon_url)
        except BaseProxyError:
            _logger.warning("Error fetching favicon")

        _logger.info(f"Favicon for {favicon_url}: {emoji}")
        key = favicon_url.get_url()
        async with self.session_factory() as session:
            favicon = await session.scalar(select(Favicon).where(Favicon.url == key))
            if favicon is None:
                favicon = Favicon(url=key)
                session.add(favicon)

            favicon.emoji = emoji
            favicon.expires_at = datetime.utcnow() + self.EXPIRATION
            await session.commit()

    async def _fetch_favicon(self, favicon_url: URLReference) -> str | None:
        request = build_proxy_request(favicon_url)
        response = await request.get_response()
        if response.status.startswith("2") and response.meta.startswith("text/plain"):
            body = await response.get_body(truncate=True)
            favicon, _ = smart_decode(body, response.charset)
            favicon = favicon.strip()
            if len(favicon) <= 8:  # Emojis can contain up to 8 code points
                return favicon

        return None


favicon_cache = FaviconCache()
